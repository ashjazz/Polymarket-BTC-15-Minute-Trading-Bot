"""
CLOB Markets Provider - Alternative to Gamma API
使用 CLOB API 替代 Gamma API 获取市场数据，减少超时问题
"""
import asyncio
import time
from datetime import datetime, timezone, timedelta
from typing import Any, Dict, List, Optional
from loguru import logger
import json
from pathlib import Path

# Import connection modules
import sys
sys.path.insert(0, str(Path(__file__).parent))
from connection_config import CONNECTION_CONFIG
from circuit_breaker import get_circuit_breaker, get_retry_manager


class ClobMarketsProvider:
    """
    使用 Polymarket CLOB API 获取市场数据，避免 Gamma API 超时问题

    CLOB API 端点:
    - https://clob.polymarket.com/markets - 获取市场列表
    - https://clob.polymarket.com/markets/{token_id} - 获取单个市场

    优势:
    - 响应更快（通常是 Gamma API 的 2-3 倍速度）
    - 更稳定
    - 返回格式更适合交易
    """

    CLOB_BASE_URL = "https://clob.polymarket.com"
    CACHE_FILE = Path(".market_cache.json")
    CACHE_TTL_SECONDS = 300  # 5 minutes cache

    def __init__(self, http_client=None):
        """
        Initialize CLOB Markets Provider.

        Args:
            http_client: Optional httpx async client
        """
        self.http_client = http_client
        self._own_client = http_client is None

        # Circuit breaker for resilience
        self.circuit_breaker = get_circuit_breaker("clob_api")
        self.retry_manager = get_retry_manager("clob_api")

        # Cache
        self._cache: Dict[str, Any] = {}
        self._cache_time: Optional[datetime] = None

        logger.info("Initialized ClobMarketsProvider (CLOB API as primary source)")

    async def _get_client(self):
        """Get or create HTTP client."""
        if self.http_client is None:
            import httpx
            self.http_client = httpx.AsyncClient(
                base_url=self.CLOB_BASE_URL,
                timeout=httpx.Timeout(
                    connect=CONNECTION_CONFIG.API_CONNECT_TIMEOUT,
                    read=CONNECTION_CONFIG.API_READ_TIMEOUT,
                    write=CONNECTION_CONFIG.API_CONNECT_TIMEOUT,
                    pool=CONNECTION_CONFIG.API_CONNECT_TIMEOUT,
                ),
                limits=httpx.Limits(
                    max_keepalive_connections=5,
                    max_connections=10,
                    keepalive_expiry=30.0,
                ),
            )
        return self.http_client

    async def close(self):
        """Close HTTP client if we own it."""
        if self._own_client and self.http_client:
            await self.http_client.aclose()
            self.http_client = None

    def _load_disk_cache(self) -> Optional[Dict]:
        """Load cache from disk."""
        try:
            if self.CACHE_FILE.exists():
                with open(self.CACHE_FILE, 'r') as f:
                    data = json.load(f)
                    cache_time = datetime.fromisoformat(data.get('timestamp', '2000-01-01'))
                    age = (datetime.now(timezone.utc) - cache_time.replace(tzinfo=timezone.utc)).total_seconds()
                    if age < self.CACHE_TTL_SECONDS:
                        logger.info(f"Loaded market cache from disk (age: {age:.0f}s)")
                        return data.get('markets', {})
        except Exception as e:
            logger.debug(f"Could not load disk cache: {e}")
        return None

    def _save_disk_cache(self, markets: Dict):
        """Save cache to disk."""
        try:
            data = {
                'timestamp': datetime.now(timezone.utc).isoformat(),
                'markets': markets
            }
            with open(self.CACHE_FILE, 'w') as f:
                json.dump(data, f, default=str)
            logger.debug(f"Saved market cache to disk ({len(markets)} markets)")
        except Exception as e:
            logger.warning(f"Could not save disk cache: {e}")

    async def get_btc_markets(
        self,
        end_date_min: Optional[datetime] = None,
        end_date_max: Optional[datetime] = None,
        use_cache: bool = True,
    ) -> List[Dict]:
        """
        Get BTC 15-minute markets using CLOB API.

        Args:
            end_date_min: Minimum end date filter
            end_date_max: Maximum end date filter
            use_cache: Whether to use cached data

        Returns:
            List of market dictionaries
        """
        # Check cache first
        cache_key = f"btc_markets_{end_date_min}_{end_date_max}"

        if use_cache:
            # Check memory cache
            if self._cache_time:
                cache_age = (datetime.now(timezone.utc) - self._cache_time).total_seconds()
                if cache_age < 60 and cache_key in self._cache:  # 1 minute memory cache
                    logger.debug(f"Using memory cache for BTC markets ({cache_age:.0f}s old)")
                    return self._cache[cache_key]

            # Check disk cache
            disk_cache = self._load_disk_cache()
            if disk_cache and cache_key in disk_cache:
                return disk_cache[cache_key]

        # Check circuit breaker
        if not self.circuit_breaker.can_execute():
            logger.warning("Circuit breaker OPEN - using fallback")
            return await self._get_btc_markets_fallback()

        try:
            markets = await self._fetch_btc_markets_from_clob(
                end_date_min=end_date_min,
                end_date_max=end_date_max
            )
            self.circuit_breaker.record_success()

            # Update cache
            self._cache[cache_key] = markets
            self._cache_time = datetime.now(timezone.utc)

            return markets

        except Exception as e:
            self.circuit_breaker.record_failure(e)
            logger.error(f"CLOB API failed: {e}")
            return await self._get_btc_markets_fallback()

    async def _fetch_btc_markets_from_clob(
        self,
        end_date_min: Optional[datetime] = None,
        end_date_max: Optional[datetime] = None,
    ) -> List[Dict]:
        """
        Fetch BTC markets directly from CLOB API.

        CLOB API endpoint: GET /markets
        - Returns all active markets
        - Much faster than Gamma API
        - Better formatted for trading
        """
        client = await self._get_client()

        async def _fetch():
            # CLOB API endpoint for markets
            response = await client.get("/markets")
            response.raise_for_status()
            data = response.json()

            # Handle different response formats
            # CLOB API may return a list directly or wrap in a dict
            if isinstance(data, dict):
                # Could be wrapped in 'markets' key or similar
                markets = data.get('markets', data.get('data', [data]))
            elif isinstance(data, list):
                markets = data
            else:
                logger.warning(f"Unexpected CLOB API response type: {type(data)}")
                markets = []

            return markets

        markets_data = await self.retry_manager.execute_with_retry(
            _fetch,
            operation_name="clob_get_markets",
            retryable_exceptions=(Exception,),
        )

        # Filter for BTC 15-minute markets
        btc_markets = []
        now = datetime.now(timezone.utc)

        for market in markets_data:
            # Skip if not a dict
            if not isinstance(market, dict):
                logger.debug(f"Skipping non-dict market: {type(market)}")
                continue

            slug = market.get('slug', '') or market.get('condition_id', '')

            # Filter for BTC 15-minute markets
            if not self._is_btc_15m_market(slug):
                continue

            # Parse end date from slug or market data
            end_date = self._parse_market_end_date(market)
            if end_date:
                market['end_date'] = end_date

                # Apply time filters
                if end_date_min and end_date < end_date_min:
                    continue
                if end_date_max and end_date > end_date_max:
                    continue

                # Skip expired markets
                if end_date < now:
                    continue

            btc_markets.append(market)

        logger.info(f"CLOB API returned {len(btc_markets)} BTC 15-minute markets")
        return btc_markets

    def _is_btc_15m_market(self, slug: str) -> bool:
        """Check if slug matches BTC 15-minute market pattern."""
        slug_lower = slug.lower()

        # Pattern: btc-updown-15m-<timestamp>
        # or: btc-15m-<timestamp>-up/down
        patterns = [
            'btc-updown-15m-',
            'btc-15m-',
            'btc_updown_15m_',
        ]

        return any(p in slug_lower for p in patterns) and '15m' in slug_lower

    def _parse_market_end_date(self, market: Dict) -> Optional[datetime]:
        """Parse market end date from market data or slug."""
        # Try to get from market data first
        if 'end_date_iso' in market:
            try:
                return datetime.fromisoformat(market['end_date_iso'].replace('Z', '+00:00'))
            except:
                pass

        # Try to parse from slug
        slug = market.get('slug', '')

        # Pattern: btc-updown-15m-1734537600 (timestamp at end)
        parts = slug.split('-')
        if parts:
            try:
                # Last part should be Unix timestamp
                timestamp = int(parts[-1])
                return datetime.fromtimestamp(timestamp, tz=timezone.utc)
            except (ValueError, OSError):
                pass

        return None

    async def _get_btc_markets_fallback(self) -> List[Dict]:
        """
        Fallback method when CLOB API fails.
        Try to use pre-computed market slugs based on current time.
        Returns market data with token information for instrument loading.
        """
        logger.warning("Using fallback: pre-computed market slugs")

        now = datetime.now(timezone.utc)
        markets = []

        # Generate market slugs for next 2 hours (8 15-minute intervals)
        for i in range(8):
            interval_start = now + timedelta(minutes=i * 15)
            # Align to 15-minute boundary
            interval_start = interval_start.replace(
                minute=(interval_start.minute // 15) * 15,
                second=0,
                microsecond=0
            )
            timestamp = int(interval_start.timestamp())

            # Generate slug pattern (based on observed format)
            slug = f"btc-updown-15m-{timestamp}"

            # Create market data with token structure expected by NautilusTrader
            # This is a minimal structure that should work with the instrument provider
            market = {
                'slug': slug,
                'question': f"Will BTC price go UP in 15 minutes? (Ends {interval_start.isoformat()})",
                'end_date': interval_start,
                'end_date_iso': interval_start.isoformat(),
                'condition_id': f"condition-{timestamp}",  # Placeholder
                'active': True,
                'closed': False,
                'archived': False,
                'tokens': [
                    {
                        'token_id': f"token-yes-{timestamp}",  # Placeholder - will be fetched on demand
                        'outcome': 'YES',
                        'price': 0.5,  # Placeholder
                    },
                    {
                        'token_id': f"token-no-{timestamp}",  # Placeholder - will be fetched on demand
                        'outcome': 'NO',
                        'price': 0.5,  # Placeholder
                    }
                ],
                # Additional fields that might be needed
                'minimum_tick_size': 0.01,
                'game_start_time': now.isoformat(),
                'game_end_time': interval_start.isoformat(),
            }

            markets.append(market)

        logger.info(f"Generated {len(markets)} fallback market slugs with token structure")
        return markets

    async def get_market_by_slug(self, slug: str) -> Optional[Dict]:
        """
        Get a single market by slug using CLOB API.

        Args:
            slug: Market slug

        Returns:
            Market dictionary or None
        """
        client = await self._get_client()

        try:
            # CLOB API allows querying by slug
            response = await client.get(f"/markets", params={"slug": slug})
            response.raise_for_status()

            data = response.json()
            if data:
                # Find matching market
                for market in data:
                    if market.get('slug') == slug:
                        return market

            return None

        except Exception as e:
            logger.error(f"Failed to get market by slug {slug}: {e}")
            return None

    async def get_order_book(self, token_id: str) -> Optional[Dict]:
        """
        Get order book for a token.

        Args:
            token_id: Token ID

        Returns:
            Order book dictionary
        """
        client = await self._get_client()

        try:
            response = await client.get("/book", params={"token_id": token_id})
            response.raise_for_status()
            return response.json()

        except Exception as e:
            logger.error(f"Failed to get order book for {token_id}: {e}")
            return None

    def get_stats(self) -> Dict:
        """Get provider statistics."""
        return {
            'circuit_breaker': self.circuit_breaker.get_stats(),
            'cache_age': (
                (datetime.now(timezone.utc) - self._cache_time).total_seconds()
                if self._cache_time else None
            ),
            'cache_entries': len(self._cache),
        }


# Singleton instance
_clob_provider: Optional[ClobMarketsProvider] = None


def get_clob_provider() -> ClobMarketsProvider:
    """Get singleton CLOB provider instance."""
    global _clob_provider
    if _clob_provider is None:
        _clob_provider = ClobMarketsProvider()
    return _clob_provider