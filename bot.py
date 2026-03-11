import asyncio
import os
import sys
from pathlib import Path
from datetime import datetime, timezone, timedelta
import math
from decimal import Decimal
import time
from dataclasses import dataclass
from typing import List, Optional, Dict
import random

# =============================================================================
# PROXY CONFIGURATION - 设置代理以访问 Polymarket API
# =============================================================================
# 重要说明：
# NautilusTrader 的 WebSocket 客户端使用 Rust 实现，不会自动使用环境变量中的代理。
# 如果你在中国大陆等需要代理的地区，请使用以下方法之一：
#
# 方法 1: 安装 aiohttp_socks (推荐)
#   pip install aiohttp_socks
#
# 方法 2: 配置系统级代理
#   - Clash: 开启 TUN 模式 或 "设置为系统代理"
#   - Proxifier: 配置 Python 使用代理
#   -Surge: 开启增强模式
#
# 方法 3: 使用 VPN
#
# 你可以在 .env 文件中设置:
#   PROXY_URL=http://localhost:8001
#   如果不设置或留空，则不使用代理，直接连接
# =============================================================================

PROXY_URL = os.getenv("PROXY_URL", "").strip()
if PROXY_URL:
    os.environ["HTTP_PROXY"] = PROXY_URL
    os.environ["HTTPS_PROXY"] = PROXY_URL
    os.environ["ALL_PROXY"] = PROXY_URL
    print(f"[PROXY] 已配置代理: {PROXY_URL}")
    print("[PROXY] 注意: NautilusTrader WebSocket 可能需要系统级代理")
else:
    # 清除可能存在的代理环境变量，确保直连
    for key in ["HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY", "http_proxy", "https_proxy", "all_proxy"]:
        os.environ.pop(key, None)
    print("[PROXY] 未配置代理，使用直连模式")

# Add project to path
project_root = Path(__file__).parent
sys.path.insert(0, str(project_root))


try:
    from patch_gamma_markets import apply_gamma_markets_patch, verify_patch
    patch_applied = apply_gamma_markets_patch()
    if patch_applied:
        verify_patch()
    else:
        print("ERROR: Failed to apply gamma_market patch")
        sys.exit(1)
except ImportError as e:
    print(f"ERROR: Could not import patch module: {e}")
    print("Make sure patch_gamma_markets.py is in the same directory")
    sys.exit(1)

# Now import Nautilus
from nautilus_trader.config import (
    InstrumentProviderConfig,
    LiveDataEngineConfig,
    LiveExecEngineConfig,
    LiveRiskEngineConfig,
    LoggingConfig,
    TradingNodeConfig,
)
from nautilus_trader.live.node import TradingNode
from nautilus_trader.adapters.polymarket import POLYMARKET
from nautilus_trader.adapters.polymarket import (
    PolymarketDataClientConfig,
    PolymarketExecClientConfig,
)
from nautilus_trader.adapters.polymarket.factories import (
    PolymarketLiveDataClientFactory,
    PolymarketLiveExecClientFactory,
)
from nautilus_trader.trading.strategy import Strategy
from nautilus_trader.model.identifiers import InstrumentId, ClientOrderId
from nautilus_trader.model.enums import OrderSide, TimeInForce
from nautilus_trader.model.objects import Quantity
from nautilus_trader.model.data import QuoteTick

from dotenv import load_dotenv
from loguru import logger
import redis

# Import enhanced connection modules for timeout handling
from connection_config import CONNECTION_CONFIG
from circuit_breaker import get_circuit_breaker, get_retry_manager

# Import our phases
from core.strategy_brain.signal_processors.spike_detector import SpikeDetectionProcessor
from core.strategy_brain.signal_processors.sentiment_processor import SentimentProcessor
from core.strategy_brain.signal_processors.divergence_processor import PriceDivergenceProcessor
from core.strategy_brain.signal_processors.orderbook_processor import OrderBookImbalanceProcessor
from core.strategy_brain.signal_processors.tick_velocity_processor import TickVelocityProcessor
from core.strategy_brain.signal_processors.deribit_pcr_processor import DeribitPCRProcessor
from core.strategy_brain.fusion_engine.signal_fusion import get_fusion_engine
from execution.risk_engine import get_risk_engine
from monitoring.performance_tracker import get_performance_tracker
from monitoring.grafana_exporter import get_grafana_exporter
from feedback.learning_engine import get_learning_engine

# =============================================================================
# NEW STRATEGY MODULE - 价值投资 + 多目标价止盈策略
# =============================================================================
from strategy import (
    StrategyConfig,
    Position, PositionStatus, PositionDirection,
    MarketState, TokenPrice,
    check_entry, EntrySignal, should_skip_entry, format_entry_log,
    check_exit, check_take_profit, check_stop_loss,
    ExitSignal, format_exit_log,
)

load_dotenv()
from patch_market_orders import apply_market_order_patch
patch_applied = apply_market_order_patch()
if patch_applied:
    logger.info("Market order patch applied successfully")
else:
    logger.warning("Market order patch failed - orders may be rejected")

# WebSocket 代理补丁 - 解决 Rust WebSocket 客户端无法使用代理的问题
try:
    from patch_websocket_proxy import apply_websocket_proxy_patch
    ws_patch_applied = apply_websocket_proxy_patch()
    if ws_patch_applied:
        logger.info("WebSocket proxy patch applied successfully")
    else:
        logger.warning("WebSocket proxy patch failed - connection may fail in restricted networks")
except ImportError as e:
    logger.warning(f"Could not import WebSocket proxy patch: {e}")


# =============================================================================
# CONSTANTS
# =============================================================================
QUOTE_STABILITY_REQUIRED = 3      # Need only 3 valid ticks to be stable (faster startup)
QUOTE_MIN_SPREAD = 0.001          # Both bid AND ask must be at least this
MARKET_INTERVAL_SECONDS = 900     # 15-minute markets


@dataclass
class PaperTrade:
    """Track paper/simulation trades"""
    timestamp: datetime
    direction: str
    size_usd: float
    price: float
    signal_score: float
    signal_confidence: float
    outcome: str = "PENDING"

    def to_dict(self):
        return {
            'timestamp': self.timestamp.isoformat(),
            'direction': self.direction,
            'size_usd': self.size_usd,
            'price': self.price,
            'signal_score': self.signal_score,
            'signal_confidence': self.signal_confidence,
            'outcome': self.outcome,
        }


def init_redis():
    """Initialize Redis connection for simulation mode control."""
    try:
        redis_client = redis.Redis(
            host=os.getenv('REDIS_HOST', 'localhost'),
            port=int(os.getenv('REDIS_PORT', 6379)),
            db=int(os.getenv('REDIS_DB', 2)),
            decode_responses=True,
            socket_connect_timeout=CONNECTION_CONFIG.REDIS_CONNECT_TIMEOUT,
            socket_timeout=CONNECTION_CONFIG.REDIS_SOCKET_TIMEOUT,
            socket_keepalive=True,
            socket_keepalive_options={},
            retry_on_timeout=True,  # 超时自动重试
            health_check_interval=30,  # 定期健康检查
        )
        redis_client.ping()
        logger.info(f"Redis connection established (timeout={CONNECTION_CONFIG.REDIS_SOCKET_TIMEOUT}s)")
        return redis_client
    except Exception as e:
        logger.warning(f"Redis connection failed: {e}")
        logger.warning("Simulation mode will be static (from .env)")
        return None


class IntegratedBTCStrategy(Strategy):
    """
    Integrated BTC Strategy - FIXED VERSION
    - Subscribes immediately at startup
    - Forces stability for first trade
    - Correct timing for market switching
    """

    def __init__(self, redis_client=None, enable_grafana=True, test_mode=False):
        super().__init__()

        self.bot_start_time = datetime.now(timezone.utc)
        self.restart_after_minutes = 90

        # Nautilus
        self.instrument_id = None
        self.redis_client = redis_client
        self.current_simulation_mode = False

        # Store ALL BTC instruments
        self.all_btc_instruments: List[Dict] = []
        self.current_instrument_index: int = -1
        self.next_switch_time: Optional[datetime] = None

        # Quote-stability tracking
        self._stable_tick_count = 0
        self._market_stable = False
        self._last_instrument_switch = None

        # =========================================================================
        # FIX 1: Force first trade by setting last_trade_time to -1
        # =========================================================================
        self.last_trade_time = -1  # Force first trade immediately!
        self._waiting_for_market_open = False  # True when waiting for a future market to open
        self._last_bid_ask = None  # (bid_decimal, ask_decimal) from last tick, for liquidity checks

        # Tick buffer: rolling 90s of ticks for TickVelocityProcessor
        from collections import deque
        self._tick_buffer: deque = deque(maxlen=500)  # ~500 ticks = well over 90s

        # YES token id for the current market (set in _load_all_btc_instruments)
        self._yes_token_id: Optional[str] = None

        # =========================================================================
        # NEW STRATEGY MODULE - 价值投资 + 多目标价止盈策略
        # =========================================================================
        self.strategy_config = StrategyConfig.from_env()
        self.market_states: Dict[str, MarketState] = {}  # key: market_slug

        # Validate strategy config
        config_errors = self.strategy_config.validate()
        if config_errors:
            logger.error("策略配置验证失败:")
            for err in config_errors:
                logger.error(f"  - {err}")
            raise ValueError(f"Invalid strategy config: {config_errors}")
        else:
            logger.info(f"策略配置加载成功: {self.strategy_config}")

        # Phase 4: Signal Processors
        self.spike_detector = SpikeDetectionProcessor(
            spike_threshold=0.05,       # FIXED: was 0.15 (too high for probabilities)
            lookback_periods=20,
        )
        self.sentiment_processor = SentimentProcessor(
            extreme_fear_threshold=25,
            extreme_greed_threshold=75,
        )
        self.divergence_processor = PriceDivergenceProcessor(
            divergence_threshold=0.05,
        )
        self.orderbook_processor = OrderBookImbalanceProcessor(
            imbalance_threshold=0.30,   # 30% skew to signal
            min_book_volume=50.0,       # ignore illiquid books
        )
        self.tick_velocity_processor = TickVelocityProcessor(
            velocity_threshold_60s=0.015,  # 1.5% move in 60s
            velocity_threshold_30s=0.010,  # 1.0% move in 30s
        )
        self.deribit_pcr_processor = DeribitPCRProcessor(
            bullish_pcr_threshold=1.20,
            bearish_pcr_threshold=0.70,
            max_days_to_expiry=2,
            cache_seconds=300,          # refresh every 5 min
        )

        # Phase 4: Signal Fusion — update weights for 6 processors
        self.fusion_engine = get_fusion_engine()
        # Rebalanced weights (must sum ≤ 1.0; higher = more influence)
        self.fusion_engine.set_weight("OrderBookImbalance", 0.30)  # best real-time signal
        self.fusion_engine.set_weight("TickVelocity",       0.25)  # fast poly momentum
        self.fusion_engine.set_weight("PriceDivergence",    0.18)  # spot momentum
        self.fusion_engine.set_weight("SpikeDetection",     0.12)  # mean reversion
        self.fusion_engine.set_weight("DeribitPCR",         0.10)  # institutional sentiment
        self.fusion_engine.set_weight("SentimentAnalysis",  0.05)  # daily F&G (weak)

        # Phase 5: Risk Management
        self.risk_engine = get_risk_engine()

        # Phase 6: Performance Tracking
        self.performance_tracker = get_performance_tracker()

        # Phase 7: Learning Engine
        self.learning_engine = get_learning_engine()

        # Phase 6: Grafana (optional)
        if enable_grafana:
            self.grafana_exporter = get_grafana_exporter()
        else:
            self.grafana_exporter = None

        # Price history
        self.price_history = []
        self.max_history = 100

        # Paper trading tracker
        self.paper_trades: List[PaperTrade] = []

        self.test_mode = test_mode

        if test_mode:
            logger.info("=" * 80)
            logger.info("  TEST MODE ACTIVE - Trading every minute!")
            logger.info("=" * 80)

        logger.info("=" * 80)
        logger.info("INTEGRATED BTC STRATEGY INITIALIZED - FIXED VERSION")
        logger.info("  Phase 4: Signal processors ready")
        logger.info("  Phase 5: Risk engine ready")
        logger.info("  Phase 6: Performance tracking ready")
        logger.info("  Phase 7: Learning engine ready")
        logger.info(f"  ${os.getenv('MARKET_BUY_USD', '5.00')} per trade maximum (configurable via MARKET_BUY_USD)")
        logger.info("=" * 80)

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _seconds_to_next_15min_boundary(self) -> float:
        """Return seconds until the next 15-minute UTC boundary."""
        now_ts = datetime.now(timezone.utc).timestamp()
        next_boundary = (math.floor(now_ts / MARKET_INTERVAL_SECONDS) + 1) * MARKET_INTERVAL_SECONDS
        return next_boundary - now_ts

    def _is_quote_valid(self, bid, ask) -> bool:
        """Return True only when BOTH bid and ask are present and make sense."""
        if bid is None or ask is None:
            return False
        try:
            b = float(bid)
            a = float(ask)
        except (TypeError, ValueError):
            return False
        if b < QUOTE_MIN_SPREAD or a < QUOTE_MIN_SPREAD:
            return False
        if b > 0.999 or a > 0.999:
            return False
        return True

    def _reset_stability(self, reason: str = ""):
        """Mark the market as unstable and reset the counter."""
        if self._market_stable:
            logger.warning(f"Market stability RESET{' – ' + reason if reason else ''}")
        self._market_stable = False
        self._stable_tick_count = 0

    # ------------------------------------------------------------------
    # Redis
    # ------------------------------------------------------------------

    async def check_simulation_mode(self) -> bool:
        """Check Redis for current simulation mode."""
        if not self.redis_client:
            return self.current_simulation_mode
        try:
            sim_mode = self.redis_client.get('btc_trading:simulation_mode')
            if sim_mode is not None:
                redis_simulation = sim_mode == '1'
                if redis_simulation != self.current_simulation_mode:
                    self.current_simulation_mode = redis_simulation
                    mode_text = "SIMULATION" if redis_simulation else "LIVE TRADING"
                    logger.warning(f"Trading mode changed to: {mode_text}")
                    if not redis_simulation:
                        logger.warning("LIVE TRADING ACTIVE - Real money at risk!")
                return redis_simulation
        except Exception as e:
            logger.warning(f"Failed to check Redis simulation mode: {e}")
        return self.current_simulation_mode

    def check_connection_health(self) -> bool:
        """
        检查所有关键连接的健康状态
        Returns: True 如果所有连接健康
        """
        # 检查 Redis
        if self.redis_client:
            try:
                self.redis_client.ping()
            except Exception as e:
                logger.error(f"Redis health check failed: {e}")
                return False
        
        # 检查数据引擎
        if hasattr(self, 'data_engine') and not self.data_engine.is_running:
            logger.error("Data engine is not running")
            return False
        
        # 检查执行引擎
        if hasattr(self, 'exec_engine') and not self.exec_engine.is_running:
            logger.error("Exec engine is not running")
            return False
        
        logger.debug("All connections healthy")
        return True

    # ------------------------------------------------------------------
    # Strategy lifecycle
    # ------------------------------------------------------------------

    def on_start(self):
        """Called when strategy starts - LOAD ALL MARKETS AND SUBSCRIBE IMMEDIATELY"""
        logger.info("=" * 80)
        logger.info("INTEGRATED BTC STRATEGY STARTED - FIXED VERSION")
        logger.info("=" * 80)

        # =========================================================================
        # FIX 2: Load ALL BTC instruments at startup
        # =========================================================================
        self._load_all_btc_instruments()

        # =========================================================================
        # FIX 3: Force subscribe to current market IMMEDIATELY
        # NEW STRATEGY: Subscribe to BOTH YES and NO tokens for dual monitoring
        # =========================================================================
        if self.instrument_id:
            # Subscribe to YES token (primary)
            self.subscribe_quote_ticks(self.instrument_id)
            logger.info(f"✓ SUBSCRIBED to YES token: {self.instrument_id}")

            # Subscribe to NO token if available
            if self._no_instrument_id:
                self.subscribe_quote_ticks(self._no_instrument_id)
                logger.info(f"✓ SUBSCRIBED to NO token: {self._no_instrument_id}")

            # Try to get current price from cache
            try:
                quote = self.cache.quote_tick(self.instrument_id)
                if quote and quote.bid_price and quote.ask_price:
                    current_price = (quote.bid_price + quote.ask_price) / 2
                    self.price_history.append(current_price)
                    logger.info(f"✓ Initial YES price: ${float(current_price):.4f}")
            except Exception as e:
                logger.debug(f"No initial price yet: {e}")

        # Generate synthetic history if needed
        if len(self.price_history) < 20:
            self._generate_synthetic_history(target_count=20, existing_count=len(self.price_history))

        # =========================================================================
        # FIX 4: Start the timer loop (but don't rely on it for trading)
        # =========================================================================
        self.run_in_executor(self._start_timer_loop)

        if self.grafana_exporter:
            import threading
            threading.Thread(target=self._start_grafana_sync, daemon=True).start()

        logger.info("=" * 80)
        logger.info("策略启动 - 价值投资 + 多目标价止盈策略")
        logger.info(f"  入场区间: [{self.strategy_config.entry_price_low:.2f} - {self.strategy_config.entry_price_high:.2f}]")
        logger.info(f"  买入窗口: 前 {self.strategy_config.buy_window_minutes} 分钟")
        logger.info(f"  止盈目标: {', '.join([f'{p:.2f}' for p in self.strategy_config.take_profit_prices])}")
        logger.info(f"  止损价格: {self.strategy_config.stop_loss_price:.2f}")
        logger.info(f"  仓位大小: ${self.strategy_config.position_size_usd:.2f} USDC")
        logger.info(f"  已监控市场: {len(self.market_states)} 个")
        logger.info("=" * 80)

    def _generate_synthetic_history(self, target_count: int = 20, existing_count: int = 0):
        """Generate synthetic price history for testing"""
        if self.price_history:
            base_price = self.price_history[-1]
        else:
            base_price = Decimal("0.5")
        needed = target_count - existing_count
        if needed <= 0:
            return
        for _ in range(needed):
            change = Decimal(str(random.uniform(-0.03, 0.03)))
            new_price = base_price * (Decimal("1.0") + change)
            new_price = max(Decimal("0.01"), min(Decimal("0.99"), new_price))
            self.price_history.append(new_price)
            base_price = new_price

    # ------------------------------------------------------------------
    # Load all BTC instruments at once
    # ------------------------------------------------------------------

    def _load_all_btc_instruments(self):
        """Load ALL BTC instruments from cache and sort by start time"""
        instruments = self.cache.instruments()
        logger.info(f"Loading ALL BTC instruments from {len(instruments)} total...")
        
        now = datetime.now(timezone.utc)
        current_timestamp = int(now.timestamp())
        
        btc_instruments = []
        
        for instrument in instruments:
            try:
                if hasattr(instrument, 'info') and instrument.info:
                    question = instrument.info.get('question', '').lower()
                    slug = instrument.info.get('market_slug', '').lower()
                    
                    if ('btc' in question or 'btc' in slug) and '15m' in slug:
                        try:
                            timestamp_part = slug.split('-')[-1]
                            market_timestamp = int(timestamp_part)
                            
                            # The slug timestamp IS the market start time (Unix, no offset).
                            # end_date_iso is a DATE-only string (e.g. "2026-02-20"), NOT a datetime,
                            # so parsing it gives midnight UTC which is wrong for intraday markets.
                            # Always derive end_timestamp from the slug: start + 900s.
                            real_start_ts = market_timestamp
                            end_timestamp = market_timestamp + 900  # 15-min markets always
                            time_diff = real_start_ts - current_timestamp
                            
                            # Only include markets that haven't ended yet
                            if end_timestamp > current_timestamp:
                                # Extract YES token ID for CLOB order book API.
                                # Nautilus instrument ID format:
                                #   {condition_id}-{token_id}.POLYMARKET
                                # The CLOB /book endpoint only accepts the token_id
                                # (the part after the dash, before .POLYMARKET).
                                raw_id = str(instrument.id)
                                # Strip .POLYMARKET suffix first
                                without_suffix = raw_id.split('.')[0] if '.' in raw_id else raw_id
                                # Then take the token_id after the condition_id dash
                                yes_token_id = without_suffix.split('-')[-1] if '-' in without_suffix else without_suffix

                                btc_instruments.append({
                                    'instrument': instrument,
                                    'slug': slug,
                                    'start_time': datetime.fromtimestamp(real_start_ts, tz=timezone.utc),
                                    'end_time': datetime.fromtimestamp(end_timestamp, tz=timezone.utc),
                                    'market_timestamp': market_timestamp,
                                    'end_timestamp': end_timestamp,
                                    'time_diff_minutes': time_diff / 60,
                                    'yes_token_id': yes_token_id,
                                })
                        except (ValueError, IndexError):
                            continue
            except Exception:
                continue
        
        # Pair YES and NO tokens by slug.
        # Each Polymarket market has two tokens loaded as separate Nautilus instruments.
        # The first instrument found for a slug is stored as the primary (YES/UP).
        # The second instrument found for the same slug is the NO/DOWN token.
        seen_slugs = {}
        deduped = []
        for inst in btc_instruments:
            slug = inst['slug']
            if slug not in seen_slugs:
                # First token seen = YES (UP)
                inst['yes_instrument_id'] = inst['instrument'].id
                inst['no_instrument_id'] = None  # will be filled when second token found
                seen_slugs[slug] = inst
                deduped.append(inst)
            else:
                # Second token seen = NO (DOWN) — store it on the existing entry
                seen_slugs[slug]['no_instrument_id'] = inst['instrument'].id
        btc_instruments = deduped
        
        # Sort by start time (absolute timestamp, not time-of-day)
        btc_instruments.sort(key=lambda x: x['market_timestamp'])
        
        logger.info("=" * 80)
        logger.info(f"FOUND {len(btc_instruments)} BTC 15-MIN MARKETS:")
        for i, inst in enumerate(btc_instruments):
            # A market is ACTIVE if it has started AND not yet ended
            is_active = inst['time_diff_minutes'] <= 0 and inst['end_timestamp'] > current_timestamp
            status = "ACTIVE" if is_active else "FUTURE" if inst['time_diff_minutes'] > 0 else "PAST"
            logger.info(f"  [{i}] {inst['slug']}: {status} (starts at {inst['start_time'].strftime('%H:%M:%S')}, ends at {inst['end_time'].strftime('%H:%M:%S')})")
        logger.info("=" * 80)

        self.all_btc_instruments = btc_instruments

        # =========================================================================
        # NEW STRATEGY: Initialize MarketState for each market
        # =========================================================================
        for inst in btc_instruments:
            slug = inst['slug']
            if slug not in self.market_states:
                self.market_states[slug] = MarketState(
                    market_slug=slug,
                    market_start_time=inst['start_time'],
                    market_end_time=inst['end_time'],
                )
        logger.info(f"Initialized MarketState for {len(self.market_states)} markets")

        # Find current market and SUBSCRIBE IMMEDIATELY
        # FIXED: A market is current if it has STARTED and not yet ENDED (use end_time, not a hardcoded 15-min window)
        for i, inst in enumerate(btc_instruments):
            is_active = inst['time_diff_minutes'] <= 0 and inst['end_timestamp'] > current_timestamp
            if is_active:
                self.current_instrument_index = i
                self.instrument_id = inst['instrument'].id
                self.next_switch_time = inst['end_time']
                self._yes_token_id = inst.get('yes_token_id')
                self._yes_instrument_id = inst.get('yes_instrument_id', inst['instrument'].id)
                self._no_instrument_id = inst.get('no_instrument_id')
                logger.info(f"✓ CURRENT MARKET: {inst['slug']} (index {i})")
                logger.info(f"  Next switch at: {self.next_switch_time.strftime('%H:%M:%S')}")
                logger.info(f"  YES token: {self._yes_token_id[:16]}…" if self._yes_token_id else "  YES token: unknown")
                
                # =========================================================================
                # CRITICAL FIX: Subscribe immediately!
                # =========================================================================
                self.subscribe_quote_ticks(self.instrument_id)
                logger.info(f"  ✓ SUBSCRIBED to current market")
                break
        
        if self.current_instrument_index == -1 and btc_instruments:
            # No currently-active market — find the NEAREST upcoming one
            # (smallest positive time_diff_minutes = starts soonest)
            future_markets = [inst for inst in btc_instruments if inst['time_diff_minutes'] > 0]
            if future_markets:
                nearest = min(future_markets, key=lambda x: x['time_diff_minutes'])
                nearest_idx = btc_instruments.index(nearest)
            else:
                # All markets are in the past — use the last one
                nearest = btc_instruments[-1]
                nearest_idx = len(btc_instruments) - 1

            self.current_instrument_index = nearest_idx
            inst = nearest
            self.instrument_id = inst['instrument'].id
            self._yes_token_id = inst.get('yes_token_id')
            self._yes_instrument_id = inst.get('yes_instrument_id', inst['instrument'].id)
            self._no_instrument_id = inst.get('no_instrument_id')
            self.next_switch_time = inst['start_time']  # switch_time = when it OPENS
            logger.info(f"⚠ NO CURRENT MARKET - WAITING FOR NEAREST FUTURE: {inst['slug']}")
            logger.info(f"  Starts in {inst['time_diff_minutes']:.1f} min at {self.next_switch_time.strftime('%H:%M:%S')} UTC")

            # Subscribe so we get ticks when it opens
            self.subscribe_quote_ticks(self.instrument_id)
            logger.info(f"  ✓ SUBSCRIBED to future market")
            # Block trading until the market actually opens (timer loop sets _market_open flag)
            self._waiting_for_market_open = True
            
    def _switch_to_next_market(self):
        """Switch to the next market in the pre-loaded list"""
        if not self.all_btc_instruments:
            logger.error("No instruments loaded!")
            return False
        
        next_index = self.current_instrument_index + 1
        if next_index >= len(self.all_btc_instruments):
            logger.warning("No more markets available - will restart bot")
            return False
        
        next_market = self.all_btc_instruments[next_index]
        now = datetime.now(timezone.utc)
        
        # Check if next market is ready
        if now < next_market['start_time']:
            logger.info(f"Waiting for next market at {next_market['start_time'].strftime('%H:%M:%S')}")
            return False
        
        # Switch to next market
        self.current_instrument_index = next_index
        self.instrument_id = next_market['instrument'].id
        self.next_switch_time = next_market['end_time']
        self._yes_token_id = next_market.get('yes_token_id')
        self._yes_instrument_id = next_market.get('yes_instrument_id', next_market['instrument'].id)
        self._no_instrument_id = next_market.get('no_instrument_id')

        # =========================================================================
        # NEW STRATEGY: Ensure MarketState exists for this market
        # =========================================================================
        slug = next_market['slug']
        if slug not in self.market_states:
            self.market_states[slug] = MarketState(
                market_slug=slug,
                market_start_time=next_market['start_time'],
                market_end_time=next_market['end_time'],
            )
        # Reset checkpoints for new market
        self.market_states[slug].reset_checkpoints()

        logger.info("=" * 80)
        logger.info(f"SWITCHING TO NEXT MARKET: {next_market['slug']}")
        logger.info(f"  Current time: {now.strftime('%H:%M:%S')}")
        logger.info(f"  Market ends at: {self.next_switch_time.strftime('%H:%M:%S')}")
        logger.info("=" * 80)
        
        # =========================================================================
        # FIX 5: Force stability for new market and reset trade timer correctly
        # =========================================================================
        self._stable_tick_count = QUOTE_STABILITY_REQUIRED  # Force stable immediately
        self._market_stable = True
        self._waiting_for_market_open = False  # Market is now active
        
        # Reset trade timer so we trade at the NEXT quote we receive
        # Use -1 so any interval will trigger (same as startup)
        self.last_trade_time = -1
        logger.info(f"  Trade timer reset — will trade on next tick")
        
        self.subscribe_quote_ticks(self.instrument_id)
        return True

    # ------------------------------------------------------------------
    # Timer loop - SIMPLIFIED
    # ------------------------------------------------------------------

    def _start_timer_loop(self):
        """Start timer loop in executor"""
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        try:
            loop.run_until_complete(self._timer_loop())
        finally:
            loop.close()

    async def _timer_loop(self):
        """
        Timer loop: checks every 10 seconds if it's time to switch markets.
        Also handles the case where we're waiting for a future market to open.
        NEW: Handles EOD (end-of-day/market) forced liquidation.
        """
        while True:
            # --- auto-restart check ---
            uptime_minutes = (datetime.now(timezone.utc) - self.bot_start_time).total_seconds() / 60
            if uptime_minutes >= self.restart_after_minutes:
                logger.warning("AUTO-RESTART TIME - Loading fresh filters")
                import signal as _signal
                os.kill(os.getpid(), _signal.SIGTERM)
                return

            now = datetime.now(timezone.utc)

            # =========================================================================
            # NEW STRATEGY: Check for EOD forced liquidation
            # =========================================================================
            await self._check_eod_liquidation(now)

            if self.next_switch_time and now >= self.next_switch_time:
                if self._waiting_for_market_open:
                    # The future market we were waiting for has now opened
                    # Treat it like a market switch so trade timer resets
                    logger.info("=" * 80)
                    logger.info(f"⏰ WAITING MARKET NOW OPEN: {now.strftime('%H:%M:%S')} UTC")
                    logger.info("=" * 80)
                    # Update next_switch_time to the market's END time
                    if (self.current_instrument_index >= 0 and
                            self.current_instrument_index < len(self.all_btc_instruments)):
                        current_market = self.all_btc_instruments[self.current_instrument_index]
                        self.next_switch_time = current_market['end_time']
                        logger.info(f"  Market ends at {self.next_switch_time.strftime('%H:%M:%S')} UTC")
                    self._waiting_for_market_open = False
                    self._market_stable = True
                    self._stable_tick_count = QUOTE_STABILITY_REQUIRED
                    self.last_trade_time = -1  # Trade immediately on next tick
                    logger.info("  ✓ MARKET OPEN — ready to trade on next tick")
                else:
                    # Normal market switch
                    self._switch_to_next_market()

            await asyncio.sleep(10)

    async def _check_eod_liquidation(self, now: datetime):
        """
        Check all markets for EOD (market end) forced liquidation.

        If a market has ended and we still have an open position, force close it.
        """
        for slug, market_state in self.market_states.items():
            if not market_state.has_position:
                continue

            # Check if market has ended
            if now >= market_state.market_end_time:
                position = market_state.current_position
                if not position.is_open:
                    continue

                logger.warning("=" * 80)
                logger.warning(f"⏰ EOD 强制平仓: {slug}")
                logger.warning(f"  市场已结束于 {market_state.market_end_time.strftime('%H:%M:%S')} UTC")
                logger.warning("=" * 80)

                # Get current price (or use last known price)
                if position.direction == PositionDirection.UP:
                    current_price = market_state.yes_price.mid if market_state.yes_price else position.entry_price
                else:
                    current_price = market_state.no_price.mid if market_state.no_price else position.entry_price

                # Create EOD exit signal
                eod_signal = ExitSignal(
                    exit_price=current_price,
                    exit_status=PositionStatus.CLOSED_EOD,
                    reason="Market ended - forced liquidation",
                    level=0,
                )

                # Handle the exit
                await self._handle_exit_signal(eod_signal, position, market_state, current_price)

    # ------------------------------------------------------------------
    # Quote tick handler - NEW STRATEGY: 价值投资 + 多目标价止盈
    # ------------------------------------------------------------------

    def on_quote_tick(self, tick: QuoteTick):
        """
        Handle quote tick - NEW STRATEGY IMPLEMENTATION

        新策略逻辑:
        1. 更新 MarketState 中的价格（区分 YES 和 NO 代币）
        2. 如果有持仓 → 调用 check_exit() 检查出场（止损或止盈）
        3. 如果无持仓 → 调用 check_entry() 检查入场（价格进入价值区）
        4. 调用对应的处理方法执行订单
        """
        try:
            # Determine which token this tick is for
            is_yes_token = tick.instrument_id == self.instrument_id
            is_no_token = hasattr(self, '_no_instrument_id') and self._no_instrument_id and tick.instrument_id == self._no_instrument_id

            # Only process ticks from YES or NO tokens of current market
            if not is_yes_token and not is_no_token:
                return

            now = datetime.now(timezone.utc)
            bid = tick.bid_price
            ask = tick.ask_price

            if bid is None or ask is None:
                return

            try:
                bid_decimal = bid.as_decimal()
                ask_decimal = ask.as_decimal()
            except:
                return

            mid_price = (bid_decimal + ask_decimal) / 2

            # Always store price history (use YES price as primary)
            if is_yes_token:
                self.price_history.append(mid_price)
                if len(self.price_history) > self.max_history:
                    self.price_history.pop(0)

            # Store latest bid/ask for liquidity check
            self._last_bid_ask = (bid_decimal, ask_decimal)

            # Tick buffer for TickVelocityProcessor
            self._tick_buffer.append({'ts': now, 'price': mid_price})

            # Stability gate
            if not self._market_stable:
                self._stable_tick_count += 1
                if self._stable_tick_count >= 1:
                    self._market_stable = True
                    logger.info(f"✓ Market STABLE immediately")
                else:
                    return

            # Block trading if waiting for a future market to open
            if self._waiting_for_market_open:
                return

            # Get current market info
            if (self.current_instrument_index < 0 or
                    self.current_instrument_index >= len(self.all_btc_instruments)):
                return

            current_market = self.all_btc_instruments[self.current_instrument_index]
            slug = current_market['slug']

            # Get or create MarketState
            market_state = self.market_states.get(slug)
            if not market_state:
                logger.warning(f"MarketState not found for {slug}, creating...")
                market_state = MarketState(
                    market_slug=slug,
                    market_start_time=current_market['start_time'],
                    market_end_time=current_market['end_time'],
                )
                self.market_states[slug] = market_state

            # =========================================================================
            # STEP 1: Update prices in MarketState
            # =========================================================================
            if is_yes_token:
                market_state.update_yes_price(bid_decimal, ask_decimal)
            elif is_no_token:
                market_state.update_no_price(bid_decimal, ask_decimal)

            # =========================================================================
            # STEP 2: Check for EXIT if we have a position
            # =========================================================================
            if market_state.has_position:
                position = market_state.current_position

                # Determine current price based on position direction
                if position.direction == PositionDirection.UP:
                    current_price = market_state.yes_price.mid if market_state.yes_price else mid_price
                else:
                    current_price = market_state.no_price.mid if market_state.no_price else mid_price

                # Check exit conditions (stop loss or take profit)
                exit_signal = check_exit(
                    position=position,
                    current_price=current_price,
                    config=self.strategy_config,
                    market_state=market_state,
                )

                if exit_signal:
                    logger.info(format_exit_log(exit_signal, position))
                    self.run_in_executor(
                        lambda: self._handle_exit_signal_sync(
                            exit_signal, position, market_state, current_price
                        )
                    )
                    return  # Exit handled, no further processing

            # =========================================================================
            # STEP 3: Check for ENTRY if we don't have a position
            # =========================================================================
            else:
                # Double-check: ensure no position exists (race condition protection)
                if market_state.has_position:
                    return

                # Check entry conditions (both YES and NO prices)
                entry_signal = check_entry(
                    yes_price=market_state.yes_price,
                    no_price=market_state.no_price,
                    config=self.strategy_config,
                    market_state=market_state,
                )

                if entry_signal:
                    # CRITICAL: Mark position as pending IMMEDIATELY to prevent duplicate entries
                    # This creates a placeholder position to block subsequent entry signals
                    pending_position = Position(
                        market_slug=market_state.market_slug,
                        direction=entry_signal.direction,
                        entry_price=entry_signal.price,
                        entry_time=now,  # Use current time
                        size_usd=self.strategy_config.position_size_usd,
                    )
                    market_state.current_position = pending_position

                    logger.info(format_entry_log(entry_signal, self.strategy_config, slug))
                    self.run_in_executor(
                        lambda: self._handle_entry_signal_sync(
                            entry_signal, market_state, current_market
                        )
                    )

        except Exception as e:
            logger.error(f"Error processing quote tick: {e}")
            import traceback
            traceback.print_exc()

    # =========================================================================
    # NEW STRATEGY: Entry and Exit Signal Handlers
    # =========================================================================

    def _handle_entry_signal_sync(self, signal: EntrySignal, market_state: MarketState, current_market: Dict):
        """Synchronous wrapper for entry signal handling"""
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        try:
            loop.run_until_complete(self._handle_entry_signal(signal, market_state, current_market))
        finally:
            loop.close()

    async def _handle_entry_signal(self, signal: EntrySignal, market_state: MarketState, current_market: Dict):
        """
        Handle entry signal from the new strategy module.

        Executes the buy order. Position is already created in on_quote_tick.
        """
        # Check simulation mode
        is_simulation = await self.check_simulation_mode()

        # Use the existing position (created in on_quote_tick to prevent race conditions)
        position = market_state.current_position
        if not position:
            logger.error("No position found in MarketState - this should not happen!")
            return

        logger.info("=" * 80)
        logger.info(f"[{'SIMULATION' if is_simulation else 'LIVE'}] 入场执行")
        logger.info(f"  市场: {market_state.market_slug}")
        logger.info(f"  方向: {signal.direction.value} ({signal.token_type})")
        logger.info(f"  价格: {signal.price:.4f}")
        logger.info(f"  金额: ${self.strategy_config.position_size_usd:.2f} USDC")
        logger.info(f"  原因: {signal.reason}")
        logger.info("=" * 80)

        if is_simulation:
            await self._record_paper_entry(position, signal)
        else:
            await self._execute_entry_order(position, signal, current_market)

    def _handle_exit_signal_sync(self, signal: ExitSignal, position: Position, market_state: MarketState, current_price: Decimal):
        """Synchronous wrapper for exit signal handling"""
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        try:
            loop.run_until_complete(self._handle_exit_signal(signal, position, market_state, current_price))
        finally:
            loop.close()

    async def _handle_exit_signal(self, signal: ExitSignal, position: Position, market_state: MarketState, current_price: Decimal):
        """
        Handle exit signal from the new strategy module.

        Closes the position and executes the sell order.
        """
        # Check simulation mode
        is_simulation = await self.check_simulation_mode()

        # Close the position in MarketState
        position.close(
            exit_price=signal.exit_price,
            exit_time=datetime.now(timezone.utc),
            reason=signal.reason,
            status=signal.exit_status,
        )

        logger.info("=" * 80)
        logger.info(f"[{'SIMULATION' if is_simulation else 'LIVE'}] 出场执行")
        logger.info(f"  市场: {market_state.market_slug}")
        logger.info(f"  方向: {position.direction.value}")
        logger.info(f"  入场价: {position.entry_price:.4f}")
        logger.info(f"  出场价: {signal.exit_price:.4f}")
        logger.info(f"  盈亏: ${position.pnl:+.2f} ({position.pnl_percent:+.1f}%)")
        logger.info(f"  原因: {signal.reason}")
        logger.info("=" * 80)

        if is_simulation:
            await self._record_paper_exit(position, signal)
        else:
            await self._execute_exit_order(position, signal, market_state)

        # Record trade in performance tracker
        self.performance_tracker.record_trade(
            trade_id=f"{market_state.market_slug}_{int(datetime.now().timestamp())}",
            direction=position.direction.value.lower(),
            entry_price=position.entry_price,
            exit_price=signal.exit_price,
            size=position.size_usd,
            entry_time=position.entry_time,
            exit_time=position.exit_time,
            signal_score=0.0,  # New strategy doesn't use signal scores
            signal_confidence=1.0,
            metadata={
                "exit_status": signal.exit_status.value,
                "exit_reason": signal.reason,
                "strategy": "value_investing",
            }
        )

        # Update Grafana if available
        if hasattr(self, 'grafana_exporter') and self.grafana_exporter:
            self.grafana_exporter.increment_trade_counter(won=(position.pnl > 0))

    # =========================================================================
    # NEW STRATEGY: Paper Trade Recording
    # =========================================================================

    async def _record_paper_entry(self, position: Position, signal: EntrySignal):
        """Record paper trade entry"""
        paper_trade = PaperTrade(
            timestamp=position.entry_time,
            direction=position.direction.value,
            size_usd=float(position.size_usd),
            price=float(position.entry_price),
            signal_score=0.0,
            signal_confidence=1.0,
            outcome="PENDING",
        )
        self.paper_trades.append(paper_trade)
        self._save_paper_trades()

        logger.info(f"[SIMULATION] 纸面交易入场已记录 (共 {len(self.paper_trades)} 笔)")

    async def _record_paper_exit(self, position: Position, signal: ExitSignal):
        """Record paper trade exit"""
        # Find the most recent PENDING trade for this market
        for trade in reversed(self.paper_trades):
            if trade.outcome == "PENDING" and trade.direction == position.direction.value:
                trade.outcome = "WIN" if position.pnl > 0 else "LOSS"
                break

        self._save_paper_trades()
        logger.info(f"[SIMULATION] 纸面交易出场已记录 (盈亏: {position.pnl:+.2f})")

    # =========================================================================
    # NEW STRATEGY: Real Order Execution
    # =========================================================================

    async def _execute_entry_order(self, position: Position, signal: EntrySignal, current_market: Dict):
        """Execute real entry order"""
        if not self.instrument_id:
            logger.error("No instrument available for entry order")
            return

        try:
            # Determine which token to buy
            if signal.direction == PositionDirection.UP:
                trade_instrument_id = getattr(self, '_yes_instrument_id', self.instrument_id)
                trade_label = "YES (UP)"
            else:
                trade_instrument_id = getattr(self, '_no_instrument_id', None)
                if trade_instrument_id is None:
                    logger.warning("NO token instrument not found — cannot buy DOWN")
                    return
                trade_label = "NO (DOWN)"

            instrument = self.cache.instrument(trade_instrument_id)
            if not instrument:
                logger.error(f"Instrument not in cache: {trade_instrument_id}")
                return

            logger.info("=" * 80)
            logger.info("LIVE MODE - PLACING ENTRY ORDER!")
            logger.info(f"  Buying {trade_label} token")
            logger.info(f"  Price: ${float(signal.price):.4f}")
            logger.info(f"  Size: ${float(position.size_usd):.2f} USDC")
            logger.info("=" * 80)

            # Get position size
            max_usd_amount = float(position.size_usd)
            precision = instrument.size_precision
            min_qty_val = float(getattr(instrument, 'min_quantity', None) or 5.0)
            token_qty = max(min_qty_val, 5.0)
            token_qty = round(token_qty, precision)

            qty = Quantity(token_qty, precision=precision)
            timestamp_ms = int(time.time() * 1000)
            unique_id = f"VALUE-ENTRY-${max_usd_amount:.0f}-{timestamp_ms}"

            order = self.order_factory.market(
                instrument_id=trade_instrument_id,
                order_side=OrderSide.BUY,
                quantity=qty,
                client_order_id=ClientOrderId(unique_id),
                quote_quantity=False,
                time_in_force=TimeInForce.IOC,
            )

            self.submit_order(order)
            logger.info(f"ENTRY ORDER SUBMITTED: {unique_id}")
            self._track_order_event("placed")

        except Exception as e:
            logger.error(f"Error placing entry order: {e}")
            import traceback
            traceback.print_exc()
            self._track_order_event("rejected")

    async def _execute_exit_order(self, position: Position, signal: ExitSignal, market_state: MarketState):
        """
        Execute real exit order.

        NOTE: On Polymarket, to "sell" a position, we need to buy the OPPOSITE token.
        This is because Polymarket positions are binary options that resolve to $1 or $0.
        """
        if not self.instrument_id:
            logger.error("No instrument available for exit order")
            return

        try:
            # To exit a position, we buy the opposite token
            # If we hold YES (UP), we sell by buying NO (DOWN)
            # If we hold NO (DOWN), we sell by buying YES (UP)
            if position.direction == PositionDirection.UP:
                # We hold YES, sell by buying NO
                trade_instrument_id = getattr(self, '_no_instrument_id', None)
                trade_label = "NO (SELL YES)"
            else:
                # We hold NO, sell by buying YES
                trade_instrument_id = getattr(self, '_yes_instrument_id', self.instrument_id)
                trade_label = "YES (SELL NO)"

            if trade_instrument_id is None:
                logger.error(f"Cannot exit: opposite token not found")
                return

            instrument = self.cache.instrument(trade_instrument_id)
            if not instrument:
                logger.error(f"Instrument not in cache: {trade_instrument_id}")
                return

            logger.info("=" * 80)
            logger.info("LIVE MODE - PLACING EXIT ORDER!")
            logger.info(f"  Selling via {trade_label}")
            logger.info(f"  Exit Price: ${float(signal.exit_price):.4f}")
            logger.info(f"  P&L: ${float(position.pnl):+.2f} ({float(position.pnl_percent):+.1f}%)")
            logger.info("=" * 80)

            # Calculate quantity based on position size
            max_usd_amount = float(position.size_usd)
            precision = instrument.size_precision
            min_qty_val = float(getattr(instrument, 'min_quantity', None) or 5.0)
            token_qty = max(min_qty_val, 5.0)
            token_qty = round(token_qty, precision)

            qty = Quantity(token_qty, precision=precision)
            timestamp_ms = int(time.time() * 1000)
            unique_id = f"VALUE-EXIT-${max_usd_amount:.0f}-{timestamp_ms}"

            order = self.order_factory.market(
                instrument_id=trade_instrument_id,
                order_side=OrderSide.BUY,  # Always BUY on Polymarket
                quantity=qty,
                client_order_id=ClientOrderId(unique_id),
                quote_quantity=False,
                time_in_force=TimeInForce.IOC,
            )

            self.submit_order(order)
            logger.info(f"EXIT ORDER SUBMITTED: {unique_id}")
            self._track_order_event("placed")

        except Exception as e:
            logger.error(f"Error placing exit order: {e}")
            import traceback
            traceback.print_exc()
            self._track_order_event("rejected")

    # ------------------------------------------------------------------
    # Trading decision (OLD - kept for reference, not used in new strategy)
    # ------------------------------------------------------------------

    def _make_trading_decision_sync(self, current_price):
        from decimal import Decimal
        price_decimal = Decimal(str(current_price))
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        try:
            loop.run_until_complete(self._make_trading_decision(price_decimal))
        finally:
            loop.close()
    
    def _make_trading_decision_sync(self, current_price):
        """Synchronous wrapper for trading decision (called from executor)."""
        # Convert float back to Decimal for processing
        from decimal import Decimal
        price_decimal = Decimal(str(current_price))
        
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        try:
            loop.run_until_complete(self._make_trading_decision(price_decimal))
        finally:
            loop.close()
            
    async def _fetch_market_context(self, current_price: Decimal) -> dict:
        """
        Fetch REAL external data to populate signal processor metadata.

        Returns a dict with:
          - sentiment_score (float 0-100): live Fear & Greed index, or None
          - spot_price (float): live BTC-USD from Coinbase, or None
          - deviation (float): polymarket price vs SMA-20 (always computed)
          - momentum (float): 5-period rate of change (always computed)
          - volatility (float): price std-dev over last 20 ticks (always computed)
        """
        current_price_float = float(current_price)

        # --- Always-available stats from local price_history ---
        recent_prices = [float(p) for p in self.price_history[-20:]]
        sma_20 = sum(recent_prices) / len(recent_prices)
        deviation = (current_price_float - sma_20) / sma_20
        momentum = (
            (current_price_float - float(self.price_history[-5])) / float(self.price_history[-5])
            if len(self.price_history) >= 5 else 0.0
        )
        variance = sum((p - sma_20) ** 2 for p in recent_prices) / len(recent_prices)
        volatility = math.sqrt(variance)

        metadata = {
            "deviation": deviation,
            "momentum": momentum,
            "volatility": volatility,
            # Tick buffer for TickVelocityProcessor
            "tick_buffer": list(self._tick_buffer),
            # YES token id for OrderBookImbalanceProcessor
            "yes_token_id": self._yes_token_id,
        }

        # --- Real sentiment: Fear & Greed Index via NewsSocialDataSource ---
        try:
            from data_sources.news_social.adapter import NewsSocialDataSource
            news_source = NewsSocialDataSource()
            await news_source.connect()
            fg = await news_source.get_fear_greed_index()
            await news_source.disconnect()
            if fg and "value" in fg:
                metadata["sentiment_score"] = float(fg["value"])
                metadata["sentiment_classification"] = fg.get("classification", "")
                logger.info(
                    f"Fear & Greed: {metadata['sentiment_score']:.0f} "
                    f"({metadata['sentiment_classification']})"
                )
            else:
                logger.warning("Fear & Greed fetch returned no data — sentiment processor skipped")
        except Exception as e:
            logger.warning(f"Could not fetch Fear & Greed index: {e} — sentiment processor skipped")

        # --- Real spot price: Coinbase BTC-USD REST API ---
        try:
            from data_sources.coinbase.adapter import CoinbaseDataSource
            coinbase = CoinbaseDataSource()
            await coinbase.connect()
            spot = await coinbase.get_current_price()
            await coinbase.disconnect()
            if spot:
                metadata["spot_price"] = float(spot)
                logger.info(f"Coinbase spot price: ${float(spot):,.2f}")
            else:
                logger.warning("Coinbase price fetch returned None — divergence processor skipped")
        except Exception as e:
            logger.warning(f"Could not fetch Coinbase spot price: {e} — divergence processor skipped")

        logger.info(
            f"Market context — deviation={deviation:.2%}, "
            f"momentum={momentum:.2%}, volatility={volatility:.4f}, "
            f"sentiment={'%.0f' % metadata['sentiment_score'] if 'sentiment_score' in metadata else 'N/A'}, "
            f"spot=${'%.2f' % metadata['spot_price'] if 'spot_price' in metadata else 'N/A'}"
        )
        return metadata

    async def _make_trading_decision(self, current_price: Decimal):
        """
        Make trading decision using our 7-phase system.

        Position size is configurable via MARKET_BUY_USD env variable (default $5.00).
        No variable sizing, no risk-engine calculation needed.
        The risk engine is still used to check that we don't already have too many open positions.
        """
        # --- Mode check ---
        is_simulation = await self.check_simulation_mode()
        logger.info(f"Mode: {'SIMULATION' if is_simulation else 'LIVE TRADING'}")

        # --- Minimum history guard ---
        if len(self.price_history) < 20:
            logger.warning(f"Not enough price history ({len(self.price_history)}/20)")
            return

        logger.info(f"Current price: ${float(current_price):,.4f}")

        # --- Phase 4a: Build real metadata for processors ---
        metadata = await self._fetch_market_context(current_price)

        # --- Phase 4b: Run all three signal processors ---
        signals = self._process_signals(current_price, metadata)

        if not signals:
            logger.info("No signals generated — no trade this interval")
            return

        logger.info(f"Generated {len(signals)} signal(s):")
        for sig in signals:
            logger.info(
                f"  [{sig.source}] {sig.direction.value}: "
                f"score={sig.score:.1f}, confidence={sig.confidence:.2%}"
            )

        # --- Phase 4c: Fuse signals into one consensus ---
        # min_score lowered to 40 because the TREND FILTER (price at min 11-13)
        # is now the primary decision maker. Fusion is informational context,
        # not the trade gate. The trend gate below is the real filter.
        fused = self.fusion_engine.fuse_signals(signals, min_signals=1, min_score=40.0)
        if not fused:
            logger.info("Fusion produced no actionable signal — no trade this interval")
            return

        logger.info(
            f"FUSED SIGNAL: {fused.direction.value} "
            f"(score={fused.score:.1f}, confidence={fused.confidence:.2%})"
        )

        # --- Phase 5: Position size from environment (default $5.00) ---
        POSITION_SIZE_USD = Decimal(os.getenv("MARKET_BUY_USD", "5.00"))

        # =========================================================================
        # TREND FILTER — replaces signal-based direction at the late trade window
        #
        # At minute 13, the Polymarket price IS the market's verdict on BTC direction.
        # We ignore what the signal processors say and simply follow the price:
        #
        #   price > 0.60 → market says UP with >60% confidence → buy YES
        #   price < 0.40 → market says DOWN with >60% confidence → buy NO
        #   price 0.40–0.60 → too close to call → SKIP (this is where we were losing)
        #
        # This directly addresses the observation that trades at 1.9–2.0+ shares
        # (price near $0.50) almost always lose, while trades at 1.4 shares
        # (price ~$0.71) mostly win.
        # =========================================================================
        TREND_UP_THRESHOLD   = 0.62   # price above this → buy YES (UP)
        TREND_DOWN_THRESHOLD = 0.38   # price below this → buy NO (DOWN)

        price_float = float(current_price)

        if price_float > TREND_UP_THRESHOLD:
            direction = "long"
            trend_confidence = price_float  # e.g. 0.72 = 72% confident UP
            logger.info(
                f" TREND: UP ({price_float:.2%} YES probability) → buying YES"
            )
        elif price_float < TREND_DOWN_THRESHOLD:
            direction = "short"
            trend_confidence = 1.0 - price_float  # e.g. 0.31 price = 69% confident DOWN
            logger.info(
                f" TREND: DOWN ({price_float:.2%} YES probability = {1-price_float:.2%} NO) → buying NO"
            )
        else:
            logger.info(
                f"⏭ TREND: NEUTRAL ({price_float:.2%}) — price too close to 0.50, SKIPPING trade "
                f"(coin flip territory: {TREND_DOWN_THRESHOLD:.0%}–{TREND_UP_THRESHOLD:.0%})"
            )
            return

        # Risk engine: only check position-count / exposure limits (no sizing math)
        is_valid, error = self.risk_engine.validate_new_position(
            size=POSITION_SIZE_USD,
            direction=direction,
            current_price=current_price,
        )
        if not is_valid:
            logger.warning(f"Risk engine blocked trade: {error}")
            return

        logger.info(f"Position size: ${POSITION_SIZE_USD} (from MARKET_BUY_USD) | Direction: {direction.upper()}")

        # --- Liquidity guard: don't place if market has no real depth ---
        # The current bid/ask come from the last processed quote tick.
        # If ask <= 0.02 or bid <= 0.02, the orderbook is essentially empty
        # and a FAK (IOC market) order will be rejected immediately.
        last_tick = getattr(self, '_last_bid_ask', None)
        if last_tick:
            last_bid, last_ask = last_tick
            MIN_LIQUIDITY = Decimal("0.02")
            if direction == "long" and last_ask <= MIN_LIQUIDITY:
                logger.warning(
                    f"⚠ No liquidity for BUY: ask=${float(last_ask):.4f} ≤ {float(MIN_LIQUIDITY):.2f} — skipping trade, will retry next tick"
                )
                self.last_trade_time = -1  # Allow retry next tick
                return
            if direction == "short" and last_bid <= MIN_LIQUIDITY:
                logger.warning(
                    f"⚠ No liquidity for SELL: bid=${float(last_bid):.4f} ≤ {float(MIN_LIQUIDITY):.2f} — skipping trade, will retry next tick"
                )
                self.last_trade_time = -1  # Allow retry next tick
                return

        # --- Phase 5 / 6: Execute ---
        if is_simulation:
            await self._record_paper_trade(fused, POSITION_SIZE_USD, current_price, direction)
        else:
            await self._place_real_order(fused, POSITION_SIZE_USD, current_price, direction)
            
    async def _record_paper_trade(self, signal, position_size, current_price, direction):
        exit_delta = timedelta(minutes=1) if self.test_mode else timedelta(minutes=15)
        exit_time = datetime.now(timezone.utc) + exit_delta

        if "BULLISH" in str(signal.direction):
            movement = random.uniform(-0.02, 0.08)
        else:
            movement = random.uniform(-0.08, 0.02)

        exit_price = current_price * (Decimal("1.0") + Decimal(str(movement)))
        exit_price = max(Decimal("0.01"), min(Decimal("0.99"), exit_price))

        if direction == "long":
            pnl = position_size * (exit_price - current_price) / current_price
        else:
            pnl = position_size * (current_price - exit_price) / current_price

        outcome = "WIN" if pnl > 0 else "LOSS"
        paper_trade = PaperTrade(
            timestamp=datetime.now(timezone.utc),
            direction=direction.upper(),
            size_usd=float(position_size),
            price=float(current_price),
            signal_score=signal.score,
            signal_confidence=signal.confidence,
            outcome=outcome,
        )
        self.paper_trades.append(paper_trade)

        self.performance_tracker.record_trade(
            trade_id=f"paper_{int(datetime.now().timestamp())}",
            direction=direction,
            entry_price=current_price,
            exit_price=exit_price,
            size=position_size,
            entry_time=datetime.now(timezone.utc),
            exit_time=exit_time,
            signal_score=signal.score,
            signal_confidence=signal.confidence,
            metadata={
                "simulated": True,
                "num_signals": signal.num_signals if hasattr(signal, 'num_signals') else 1,
                "fusion_score": signal.score,
            }
        )

        if hasattr(self, 'grafana_exporter') and self.grafana_exporter:
            self.grafana_exporter.increment_trade_counter(won=(pnl > 0))
            self.grafana_exporter.record_trade_duration(exit_delta.total_seconds())

        logger.info("=" * 80)
        logger.info("[SIMULATION] PAPER TRADE RECORDED")
        logger.info(f"  Direction: {direction.upper()}")
        logger.info(f"  Size: ${float(position_size):.2f}")
        logger.info(f"  Entry Price: ${float(current_price):,.4f}")
        logger.info(f"  Simulated Exit: ${float(exit_price):,.4f}")
        logger.info(f"  Simulated P&L: ${float(pnl):+.2f} ({movement*100:+.2f}%)")
        logger.info(f"  Outcome: {outcome}")
        logger.info(f"  Total Paper Trades: {len(self.paper_trades)}")
        logger.info("=" * 80)

        self._save_paper_trades()

    def _save_paper_trades(self):
        import json
        try:
            trades_data = [t.to_dict() for t in self.paper_trades]
            with open('paper_trades.json', 'w') as f:
                json.dump(trades_data, f, indent=2)
        except Exception as e:
            logger.error(f"Failed to save paper trades: {e}")

    # ------------------------------------------------------------------
    # Real order (unchanged)
    # ------------------------------------------------------------------

    async def _place_real_order(self, signal, position_size, current_price, direction):
        if not self.instrument_id:
            logger.error("No instrument available")
            return

        try:
            # instrument is fetched below after determining YES vs NO token

            logger.info("=" * 80)
            logger.info("LIVE MODE - PLACING REAL ORDER!")
            logger.info("=" * 80)

            # On Polymarket, both UP and DOWN are BUY orders.
            # Bullish = buy YES token (self._yes_instrument_id)
            # Bearish = buy NO token  (self._no_instrument_id)
            # There is NO sell — you always buy whichever side you want.
            side = OrderSide.BUY

            if direction == "long":
                trade_instrument_id = getattr(self, '_yes_instrument_id', self.instrument_id)
                trade_label = "YES (UP)"
            else:
                no_id = getattr(self, '_no_instrument_id', None)
                if no_id is None:
                    logger.warning(
                        "NO token instrument not found for this market — "
                        "cannot bet DOWN. Skipping trade."
                    )
                    return
                trade_instrument_id = no_id
                trade_label = "NO (DOWN)"

            instrument = self.cache.instrument(trade_instrument_id)
            if not instrument:
                logger.error(f"Instrument not in cache: {trade_instrument_id}")
                return

            logger.info(f"Buying {trade_label} token: {trade_instrument_id}")

            trade_price = float(current_price)
            max_usd_amount = float(position_size)

            precision = instrument.size_precision

            # Always BUY — the market-order patch converts this to a USD amount.
            # Pass dummy qty=5 (minimum) so Nautilus risk engine doesn't deny it.
            min_qty_val = float(getattr(instrument, 'min_quantity', None) or 5.0)
            token_qty = max(min_qty_val, 5.0)
            token_qty = round(token_qty, precision)
            logger.info(
                f"BUY {trade_label}: dummy qty={token_qty:.6f} "
                f"(patch converts to ${max_usd_amount:.2f} USD)"
            )

            qty = Quantity(token_qty, precision=precision)
            timestamp_ms = int(time.time() * 1000)
            unique_id = f"BTC-15MIN-${max_usd_amount:.0f}-{timestamp_ms}"

            order = self.order_factory.market(
                instrument_id=trade_instrument_id,
                order_side=side,
                quantity=qty,
                client_order_id=ClientOrderId(unique_id),
                quote_quantity=False,
                time_in_force=TimeInForce.IOC,
            )

            self.submit_order(order)

            logger.info(f"REAL ORDER SUBMITTED!")
            logger.info(f"  Order ID: {unique_id}")
            logger.info(f"  Direction: {trade_label}")
            logger.info(f"  Side: BUY")
            logger.info(f"  Token Quantity: {token_qty:.6f}")
            logger.info(f"  Estimated Cost: ~${max_usd_amount:.2f}")
            logger.info(f"  Price: ${trade_price:.4f}")
            logger.info("=" * 80)

            self._track_order_event("placed")

        except Exception as e:
            logger.error(f"Error placing real order: {e}")
            import traceback
            traceback.print_exc()
            self._track_order_event("rejected")

    # ------------------------------------------------------------------
    # Signal processing
    # ------------------------------------------------------------------

    def _process_signals(self, current_price, metadata=None):
        signals = []
        if metadata is None:
            metadata = {}

        processed_metadata = {}
        for key, value in metadata.items():
            if isinstance(value, float):
                processed_metadata[key] = Decimal(str(value))
            else:
                processed_metadata[key] = value

        spike_signal = self.spike_detector.process(
            current_price=current_price,
            historical_prices=self.price_history,
            metadata=processed_metadata,
        )
        if spike_signal:
            signals.append(spike_signal)

        if 'sentiment_score' in processed_metadata:
            sentiment_signal = self.sentiment_processor.process(
                current_price=current_price,
                historical_prices=self.price_history,
                metadata=processed_metadata,
            )
            if sentiment_signal:
                signals.append(sentiment_signal)

        if 'spot_price' in processed_metadata:
            divergence_signal = self.divergence_processor.process(
                current_price=current_price,
                historical_prices=self.price_history,
                metadata=processed_metadata,
            )
            if divergence_signal:
                signals.append(divergence_signal)

        # --- Order Book Imbalance (real-time Polymarket CLOB depth) ---
        if processed_metadata.get('yes_token_id'):
            ob_signal = self.orderbook_processor.process(
                current_price=current_price,
                historical_prices=self.price_history,
                metadata=processed_metadata,
            )
            if ob_signal:
                signals.append(ob_signal)

        # --- Tick Velocity (last 60s of Polymarket probability movement) ---
        if processed_metadata.get('tick_buffer'):
            tv_signal = self.tick_velocity_processor.process(
                current_price=current_price,
                historical_prices=self.price_history,
                metadata=processed_metadata,
            )
            if tv_signal:
                signals.append(tv_signal)

        # --- Deribit Put/Call Ratio (institutional options sentiment) ---
        pcr_signal = self.deribit_pcr_processor.process(
            current_price=current_price,
            historical_prices=self.price_history,
            metadata=processed_metadata,
        )
        if pcr_signal:
            signals.append(pcr_signal)

        return signals

    # ------------------------------------------------------------------
    # Order events
    # ------------------------------------------------------------------

    def _track_order_event(self, event_type: str) -> None:
        """
        Safely track an order event on the performance tracker.

        PerformanceTracker does not expose `increment_order_counter`, so we
        use whichever method is actually available, or fall back to a no-op.
        Supported event_type values: "placed", "filled", "rejected".
        """
        try:
            pt = self.performance_tracker
            # Try the method that actually exists first
            if hasattr(pt, 'record_order_event'):
                pt.record_order_event(event_type)
            elif hasattr(pt, 'increment_counter'):
                pt.increment_counter(event_type)
            elif hasattr(pt, 'increment_order_counter'):
                pt.increment_order_counter(event_type)
            else:
                # No suitable method found – log and carry on
                logger.debug(
                    f"PerformanceTracker has no order-counter method; "
                    f"ignoring event '{event_type}'"
                )
        except Exception as e:
            logger.warning(f"Failed to track order event '{event_type}': {e}")

    def on_order_filled(self, event):
        logger.info("=" * 80)
        logger.info(f"ORDER FILLED!")
        logger.info(f"  Order: {event.client_order_id}")
        logger.info(f"  Fill Price: ${float(event.last_px):.4f}")
        logger.info(f"  Quantity: {float(event.last_qty):.6f}")
        logger.info("=" * 80)
        self._track_order_event("filled")

    def on_order_denied(self, event):
        logger.error("=" * 80)
        logger.error(f"ORDER DENIED!")
        logger.error(f"  Order: {event.client_order_id}")
        logger.error(f"  Reason: {event.reason}")
        logger.error("=" * 80)
        self._track_order_event("rejected")

    def on_order_rejected(self, event):
        """Handle order rejection — reset trade timer so we can retry next tick."""
        reason = str(getattr(event, 'reason', ''))
        reason_lower = reason.lower()
        if 'no orders found' in reason_lower or 'fak' in reason_lower or 'no match' in reason_lower:
            logger.warning(
                f"⚠ FAK rejected (no liquidity) — resetting timer to retry next tick\n"
                f"  Reason: {reason}"
            )
            self.last_trade_time = -1  # Allow retry on next quote tick
        else:
            logger.warning(f"Order rejected: {reason}")

    # ------------------------------------------------------------------
    # Grafana / stop
    # ------------------------------------------------------------------

    def _start_grafana_sync(self):
        import asyncio
        try:
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            loop.run_until_complete(self.grafana_exporter.start())
            logger.info("Grafana metrics started on port 8000")
        except Exception as e:
            logger.error(f"Failed to start Grafana: {e}")

    def on_stop(self):
        logger.info("Integrated BTC strategy stopped")
        logger.info(f"Total paper trades recorded: {len(self.paper_trades)}")
        if self.grafana_exporter:
            import asyncio
            try:
                loop = asyncio.new_event_loop()
                loop.run_until_complete(self.grafana_exporter.stop())
            except Exception:
                pass

# ---------------------------------------------------------------------------
# Runner
# ---------------------------------------------------------------------------

def run_integrated_bot(simulation: bool = False, enable_grafana: bool = True, test_mode: bool = False):
    """Run the integrated BTC 15-min trading bot - LOADS ALL BTC MARKETS FOR THE DAY"""
    
    print("=" * 80)
    print("INTEGRATED POLYMARKET BTC 15-MIN TRADING BOT")
    print("Nautilus + 7-Phase System + Redis Control")
    print("=" * 80)

    redis_client = init_redis()

    if redis_client:
        try:
            # ALWAYS overwrite Redis with the current session mode.
            # This prevents a stale value from a previous --live run
            # silently overriding --test-mode or --simulation runs.
            mode_value = '1' if simulation else '0'
            redis_client.set('btc_trading:simulation_mode', mode_value)
            mode_label = 'SIMULATION' if simulation else 'LIVE'
            logger.info(f"Redis simulation_mode forced to: {mode_label} ({mode_value})")
        except Exception as e:
            logger.warning(f"Could not set Redis simulation mode: {e}")

    print(f"\nConfiguration:")
    print(f"  Initial Mode: {'SIMULATION' if simulation else 'LIVE TRADING'}")
    print(f"  Redis Control: {'Enabled' if redis_client else 'Disabled'}")
    print(f"  Grafana: {'Enabled' if enable_grafana else 'Disabled'}")
    print(f"  Max Trade Size: ${os.getenv('MARKET_BUY_USD', '5.00')} (configurable via MARKET_BUY_USD)")
    print(f"  Quote stability gate: {QUOTE_STABILITY_REQUIRED} valid ticks")
    print()

    now = datetime.now(timezone.utc)
    
    # =========================================================================
    # Slug timestamps ARE standard Unix timestamps (no offset) aligned to
    # 15-min boundaries. Generate slugs for current + next 24 hours.
    # =========================================================================
    now = datetime.now(timezone.utc)
    unix_interval_start = (int(now.timestamp()) // 900) * 900  # current 15-min boundary

    btc_slugs = []
    # 预加载 194 个市场（约 48 小时），避免自动更新导致订阅中断
    for i in range(-1, 193):  # include 1 prior interval + 192 future intervals (~48 hours)
        timestamp = unix_interval_start + (i * 900)
        btc_slugs.append(f"btc-updown-15m-{timestamp}")

    filters = {
        "active": True,
        "closed": False,
        "archived": False,
        "slug": tuple(btc_slugs),
        "limit": 10,
    }

    logger.info("=" * 80)
    logger.info("LOADING BTC 15-MIN MARKETS BY SLUG")
    logger.info(f"  Interval start: {unix_interval_start} | Count: {len(btc_slugs)}")
    logger.info(f"  First: {btc_slugs[0]}  Last: {btc_slugs[-1]}")
    logger.info("=" * 80)

    instrument_cfg = InstrumentProviderConfig(
        load_all=True,
        filters=filters,
        use_gamma_markets=True,
    )

    poly_data_cfg = PolymarketDataClientConfig(
        private_key=os.getenv("POLYMARKET_PK"),
        api_key=os.getenv("POLYMARKET_API_KEY"),
        api_secret=os.getenv("POLYMARKET_API_SECRET"),
        passphrase=os.getenv("POLYMARKET_PASSPHRASE"),
        signature_type=1,
        instrument_provider=instrument_cfg,
        # WebSocket connection settings
        ws_connection_initial_delay_secs=10.0,  # Increased from 5s
        ws_connection_delay_secs=1.0,  # Increased from 0.1s
        # 禁用自动更新市场，避免订阅中断
        update_instruments_interval_mins=None,
    )

    poly_exec_cfg = PolymarketExecClientConfig(
        private_key=os.getenv("POLYMARKET_PK"),
        api_key=os.getenv("POLYMARKET_API_KEY"),
        api_secret=os.getenv("POLYMARKET_API_SECRET"),
        passphrase=os.getenv("POLYMARKET_PASSPHRASE"),
        signature_type=1,
        instrument_provider=instrument_cfg,
        # WebSocket retry settings
        max_retries=5,  # Increased retries for WebSocket connection
        retry_delay_initial_ms=1000,  # 1 second initial delay
        retry_delay_max_ms=30000,  # 30 seconds max delay
        ack_timeout_secs=10.0,  # Increased from 5s
    )

    config = TradingNodeConfig(
        environment="live",
        trader_id="BTC-15MIN-INTEGRATED-001",
        logging=LoggingConfig(
            log_level="INFO",
            log_directory="./logs/nautilus",
        ),
        data_engine=LiveDataEngineConfig(qsize=CONNECTION_CONFIG.DATA_ENGINE_QSIZE),
        exec_engine=LiveExecEngineConfig(qsize=CONNECTION_CONFIG.EXEC_ENGINE_QSIZE),
        risk_engine=LiveRiskEngineConfig(bypass=simulation),
        data_clients={POLYMARKET: poly_data_cfg},
        exec_clients={POLYMARKET: poly_exec_cfg},
        # ⭐ 使用连接配置中的超时值（解决超时问题）
        timeout_connection=float(CONNECTION_CONFIG.NODE_TIMEOUT),
        timeout_reconciliation=float(CONNECTION_CONFIG.DATA_ENGINE_TIMEOUT),
    )
    logger.info(f"TradingNode config: timeout_connection={CONNECTION_CONFIG.NODE_TIMEOUT}s, "
                f"qsize={CONNECTION_CONFIG.DATA_ENGINE_QSIZE}")

    strategy = IntegratedBTCStrategy(
        redis_client=redis_client,
        enable_grafana=enable_grafana,
        test_mode=test_mode,
    )

    print("\nBuilding Nautilus node...")
    node = TradingNode(config=config)
    node.add_data_client_factory(POLYMARKET, PolymarketLiveDataClientFactory)
    node.add_exec_client_factory(POLYMARKET, PolymarketLiveExecClientFactory)
    node.trader.add_strategy(strategy)
    node.build()
    logger.info("Nautilus node built successfully")

    print()
    print("=" * 80)
    print("BOT STARTING")
    print("=" * 80)

    try:
        node.run()
    except KeyboardInterrupt:
        print("\nShutting down...")
    except TimeoutError as e:
        logger.error(f"Timeout error: {e}")
        logger.error("Bot encountered timeout - will be restarted by wrapper")
        raise  # 让 wrapper 重新启动
    except ConnectionError as e:
        logger.error(f"Connection error: {e}")
        logger.error("Bot encountered connection issue - will be restarted by wrapper")
        raise  # 让 wrapper 重新启动
    except asyncio.TimeoutError as e:
        logger.error(f"Async timeout error: {e}")
        logger.error("Bot encountered async timeout - will be restarted by wrapper")
        raise
    except OSError as e:
        # Handle network-related OS errors (errno 60 = connection timed out)
        logger.error(f"Network OS error: {e} (errno: {e.errno if hasattr(e, 'errno') else 'N/A'})")
        logger.error("Bot encountered network issue - will be restarted by wrapper")
        raise
    except Exception as e:
        logger.error(f"Unexpected error: {e}")
        logger.error("Bot will be restarted by wrapper")
        raise  # 让 wrapper 重新启动
    finally:
        node.dispose()
        logger.info("Bot stopped")

def main():
    import argparse

    parser = argparse.ArgumentParser(description="Integrated BTC 15-Min Trading Bot")
    parser.add_argument("--live", action="store_true",
                        help="Run in LIVE mode (real money at risk!). Default is simulation.")
    parser.add_argument("--no-grafana", action="store_true", help="Disable Grafana metrics")
    parser.add_argument("--test-mode", action="store_true",
                        help="Run in TEST MODE (trade every minute for faster testing)")

    args = parser.parse_args()
    enable_grafana = not args.no_grafana
    test_mode = args.test_mode

    # --test-mode ALWAYS forces simulation even if --live is also passed
    if args.test_mode:
        simulation = True
    else:
        simulation = not args.live

    if not simulation:
        logger.warning("=" * 80)
        logger.warning("LIVE TRADING MODE — REAL MONEY AT RISK!")
        logger.warning("=" * 80)
    else:
        logger.info("=" * 80)
        logger.info(f"SIMULATION MODE — {'TEST MODE (fast clock)' if test_mode else 'paper trading only'}")
        logger.info("No real orders will be placed.")
        logger.info("=" * 80)

    run_integrated_bot(simulation=simulation, enable_grafana=enable_grafana, test_mode=test_mode)


if __name__ == "__main__":
    main()
