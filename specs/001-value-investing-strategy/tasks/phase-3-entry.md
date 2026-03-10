# Phase 3: US1 - 双向监控与价值入场

**阶段目标**: 实现双向价格监控和价值区间入场逻辑

**前置依赖**: Phase 2 完成

**用户故事**: US1 - 双向监控与价值入场 (P1)

**预计耗时**: 20-25 分钟

---

## 任务清单

### T011 实现 EntrySignal 和入场逻辑
- [ ] T011 创建 `strategy/entry_logic.py`，实现入场信号和检查函数

**文件**: `strategy/entry_logic.py`

**完整实现**:
```python
"""
入场逻辑模块

实现双向价格监控和价值区间入场判断。
"""
from dataclasses import dataclass
from decimal import Decimal
from typing import Optional
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
        logger.debug(f"[ENTRY] 市场已有持仓，跳过入场检查: {market_state.market_slug}")
        return None

    # 检查是否在买入窗口内
    minutes_since_open = market_state.minutes_since_open
    if not config.is_in_buy_window(minutes_since_open):
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
