"""
出场逻辑模块

实现实时价格监控的多目标价止盈和止损逻辑。
"""
from dataclasses import dataclass
from decimal import Decimal
from typing import Optional, Tuple
from datetime import datetime, timezone
from loguru import logger

from strategy.config import StrategyConfig
from strategy.position import Position, PositionStatus
from strategy.market_state import MarketState


@dataclass
class ExitSignal:
    """出场信号"""
    exit_price: Decimal
    exit_status: PositionStatus  # CLOSED_TP1, CLOSED_TP2, CLOSED_TP3, CLOSED_SL
    reason: str
    level: int  # 命中的止盈级别 (1, 2, 3...) 或 0 表示止损


def check_take_profit(
    position: Position,
    config: StrategyConfig,
    current_price: Decimal,
) -> Optional[ExitSignal]:
    """
    检查是否达到任一止盈目标（实时监控）

    从高到低检查目标价列表，一旦当前价格 >= 任一目标价，立即触发卖出。
    这样当价格很高时（如0.55），会优先以最高目标价卖出，获得最大收益。

    Args:
        position: 当前持仓
        config: 策略配置
        current_price: 当前价格

    Returns:
        ExitSignal: 如果满足止盈条件
        None: 如果不满足止盈条件
    """
    if not position.is_open:
        return None

    # 从高到低检查目标价
    hit, level, target_price = config.check_take_profit_hit(current_price)

    if hit:
        # 确定出场状态
        if level == 1:
            exit_status = PositionStatus.CLOSED_TP1
        elif level == 2:
            exit_status = PositionStatus.CLOSED_TP2
        elif level == 3:
            exit_status = PositionStatus.CLOSED_TP3
        else:
            # 支持更多级别
            exit_status = PositionStatus.CLOSED_TP3

        logger.info(
            f"[EXIT] TP{level} 触发: 当前价格 {current_price:.4f} >= 目标价 {target_price:.4f}"
        )

        return ExitSignal(
            exit_price=current_price,
            exit_status=exit_status,
            reason=f"Price reached TP{level} target ({target_price:.2f})",
            level=level,
        )

    return None


def check_stop_loss(
    position: Position,
    current_price: Decimal,
    config: StrategyConfig,
) -> Optional[ExitSignal]:
    """
    检查是否触发止损

    止损条件: 价格 <= 止损线（默认 0.20）

    Args:
        position: 当前持仓
        current_price: 当前价格
        config: 策略配置

    Returns:
        ExitSignal: 如果触发止损
        None: 如果未触发止损
    """
    if not position.is_open:
        return None

    if current_price <= config.stop_loss_price:
        logger.warning(
            f"[EXIT] 止损触发: 当前价格 {current_price:.4f} <= 止损线 {config.stop_loss_price:.4f}"
        )
        return ExitSignal(
            exit_price=current_price,
            exit_status=PositionStatus.CLOSED_SL,
            reason=f"Price fell below stop-loss threshold ({config.stop_loss_price:.2f})",
            level=0,
        )

    return None


def check_exit(
    position: Position,
    current_price: Decimal,
    config: StrategyConfig,
    market_state: Optional[MarketState] = None,
) -> Optional[ExitSignal]:
    """
    检查是否满足出场条件（止盈或止损）

    优先级:
    1. 止损（实时监控）
    2. 止盈（实时监控，从高到低检查目标价）

    Args:
        position: 当前持仓
        current_price: 当前价格
        config: 策略配置
        market_state: 市场状态（可选，用于日志）

    Returns:
        ExitSignal: 如果满足出场条件
        None: 如果不满足出场条件
    """
    if not position.is_open:
        return None

    # 优先检查止损
    sl_signal = check_stop_loss(position, current_price, config)
    if sl_signal:
        return sl_signal

    # 然后检查止盈（实时价格监控）
    tp_signal = check_take_profit(position, config, current_price)
    if tp_signal:
        return tp_signal

    return None


def format_exit_log(signal: ExitSignal, position: Position) -> str:
    """
    格式化出场日志

    Returns:
        格式化的日志字符串
    """
    separator = "=" * 70

    if signal.exit_status == PositionStatus.CLOSED_SL:
        header = "STOP-LOSS TRIGGERED"
    else:
        header = f"TAKE-PROFIT TRIGGERED (TP{signal.level})"

    pnl = position.unrealized_pnl(signal.exit_price)
    pnl_pct = position.unrealized_pnl_percent(signal.exit_price)

    return f"""
{separator}
 {header}
   Exit Price: ${signal.exit_price:.4f}
   Entry Price: ${position.entry_price:.4f}
   P&L: ${pnl:+.2f} USDC ({pnl_pct:+.1f}%)
   Reason: {signal.reason}
{separator}
"""


def get_distance_to_nearest_target(current_price: Decimal, config: StrategyConfig) -> Tuple[Decimal, int]:
    """
    获取当前价格距离最近目标价的距离

    Args:
        current_price: 当前价格
        config: 策略配置

    Returns:
        (distance, level): 距离和目标级别
    """
    min_distance = Decimal("999")
    nearest_level = 0

    for i, target_price in enumerate(config.take_profit_prices):
        if current_price < target_price:
            distance = target_price - current_price
            if distance < min_distance:
                min_distance = distance
                nearest_level = i + 1

    return (min_distance, nearest_level)
