"""
入场逻辑模块

实现双向价格监控和价值区间入场判断。
"""
from dataclasses import dataclass
from decimal import Decimal
from typing import Optional
from datetime import datetime, timezone
from loguru import logger

from strategy.config import StrategyConfig
from strategy.position import PositionDirection
from strategy.market_state import MarketState, TokenPrice


@dataclass
class EntrySignal:
    """入场信号"""
    direction: PositionDirection  # UP 或 DOWN
    price: Decimal               # 入场价格（中间价）
    reason: str                  # 触发原因
    token_type: str              # "YES" 或 "NO"


# 日志节流：记录上次打印日志的时间，避免刷屏
_last_log_times: dict = {}
LOG_THROTTLE_SECONDS = 30  # 同一市场同一原因的日志间隔至少 30 秒


def _should_log(market_slug: str, reason: str) -> bool:
    """检查是否应该打印日志（节流机制）"""
    key = f"{market_slug}:{reason}"
    now = datetime.now(timezone.utc)
    last_time = _last_log_times.get(key)
    if last_time is None or (now - last_time).total_seconds() >= LOG_THROTTLE_SECONDS:
        _last_log_times[key] = now
        return True
    return False


def check_entry(
    yes_price: Optional[TokenPrice],
    no_price: Optional[TokenPrice],
    config: StrategyConfig,
    market_state: MarketState,
) -> Optional[EntrySignal]:
    """
    检查是否满足入场条件

    入场条件:
    1. 在买入窗口内（市场开盘后前N分钟）
    2. 任一代币价格在入场区间内
    3. 当前市场无持仓

    Args:
        yes_price: YES 代币价格（可选）
        no_price: NO 代币价格（可选）
        config: 策略配置
        market_state: 市场状态

    Returns:
        EntrySignal: 如果满足入场条件
        None: 如果不满足入场条件
    """
    # 检查是否已有持仓
    if market_state.has_position:
        return None

    # 检查是否在买入窗口内
    minutes_since_open = market_state.minutes_since_open
    if not config.is_in_buy_window(minutes_since_open):
        # 只在首次超出窗口时打印一次日志（节流）
        if _should_log(market_state.market_slug, "outside_window"):
            logger.debug(
                f"[ENTRY] 超出买入窗口: {minutes_since_open:.1f}min >= {config.buy_window_minutes}min"
            )
        return None

    # 检查 YES 代币价格
    if yes_price is not None:
        if config.is_entry_price(yes_price.mid):
            logger.info(
                f"[ENTRY] YES 代币价格进入入场区间: {yes_price.mid:.4f} "
                f"(区间: {config.entry_price_low:.2f}-{config.entry_price_high:.2f})"
            )
            return EntrySignal(
                direction=PositionDirection.UP,
                price=yes_price.mid,
                reason=f"YES price {yes_price.mid:.4f} in entry zone [{config.entry_price_low:.2f}-{config.entry_price_high:.2f}]",
                token_type="YES",
            )

    # 检查 NO 代币价格
    if no_price is not None:
        if config.is_entry_price(no_price.mid):
            logger.info(
                f"[ENTRY] NO 代币价格进入入场区间: {no_price.mid:.4f} "
                f"(区间: {config.entry_price_low:.2f}-{config.entry_price_high:.2f})"
            )
            return EntrySignal(
                direction=PositionDirection.DOWN,
                price=no_price.mid,
                reason=f"NO price {no_price.mid:.4f} in entry zone [{config.entry_price_low:.2f}-{config.entry_price_high:.2f}]",
                token_type="NO",
            )

    return None


def should_skip_entry(market_state: MarketState, config: StrategyConfig) -> tuple[bool, str]:
    """
    检查是否应该跳过入场（用于日志和调试）

    Returns:
        (should_skip, reason): 是否跳过及原因
    """
    if market_state.has_position:
        return True, "Already has position"

    minutes = market_state.minutes_since_open
    if minutes >= config.buy_window_minutes:
        return True, f"Outside buy window ({minutes:.1f}min >= {config.buy_window_minutes}min)"

    if minutes < 0:
        return True, "Market not yet open"

    return False, "OK to check entry"


def format_entry_log(signal: EntrySignal, config: StrategyConfig, market_slug: str) -> str:
    """
    格式化入场日志

    Returns:
        格式化的日志字符串
    """
    separator = "=" * 70
    return f"""
{separator}
 VALUE ENTRY TRIGGERED
   Market: {market_slug}
   Direction: {signal.direction.value} ({signal.token_type})
   Entry Price: ${signal.price:.4f}
   Size: ${config.position_size_usd:.2f} USDC
   Entry Time: T0 (now)
   Reason: {signal.reason}
{separator}
"""
