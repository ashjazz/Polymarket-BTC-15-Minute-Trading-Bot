# Phase 4: US2 - 时间阶梯止盈

**阶段目标**: 实现时间阶梯止盈逻辑

**前置依赖**: Phase 3 完成

**用户故事**: US2 - 时间阶梯止盈执行 (P1)

**预计耗时**: 15-20 分钟

---

## 任务清单

### T012 实现 ExitSignal 和止盈逻辑
- [X] T012 创建 `strategy/exit_logic.py`，实现出场信号和止盈检查函数

**文件**: `strategy/exit_logic.py`

**完整实现**:
```python
"""
出场逻辑模块

实现时间阶梯止盈和止损逻辑。
"""
from dataclasses import dataclass
from decimal import Decimal
from typing import Optional
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
    checkpoint: int  # 1, 2, 3 for TP, 0 for SL


def check_take_profit(
    position: Position,
    config: StrategyConfig,
    market_state: MarketState,
    current_price: Decimal,
) -> Optional[ExitSignal]:
    """
    检查是否满足止盈条件

    止盈条件（时间阶梯）:
    - T+2min: 价格 >= 0.40 → 卖出
    - T+4min: 价格 >= 0.48 → 卖出
    - T+6min: 价格 >= 0.55 → 卖出

    Args:
        position: 当前持仓
        config: 策略配置
        market_state: 市场状态
        current_price: 当前价格

    Returns:
        ExitSignal: 如果满足止盈条件
        None: 如果不满足止盈条件
    """
    if not position.is_open:
        return None

    holding_minutes = position.holding_minutes

    # 检查点 1: T+2分钟
    if not market_state.tp1_checked:
        tp1_minutes, tp1_price = config.get_take_profit_target(1)

        if holding_minutes >= tp1_minutes:
            market_state.mark_checkpoint_checked(1)
            logger.debug(f"[EXIT] TP1 检查点到达: {holding_minutes:.1f}min >= {tp1_minutes}min")

            if current_price >= tp1_price:
                logger.info(
                    f"[EXIT] TP1 触发: 价格 {current_price:.4f} >= 目标 {tp1_price:.4f}"
                )
                return ExitSignal(
                    exit_price=current_price,
                    exit_status=PositionStatus.CLOSED_TP1,
                    reason=f"Price reached TP1 target ({tp1_price:.2f}) at T+{tp1_minutes}min",
                    checkpoint=1,
                )
            else:
                logger.debug(
                    f"[EXIT] TP1 未达标: 价格 {current_price:.4f} < 目标 {tp1_price:.4f}"
                )

    # 检查点 2: T+4分钟
    if not market_state.tp2_checked:
        tp2_minutes, tp2_price = config.get_take_profit_target(2)

        if holding_minutes >= tp2_minutes:
            market_state.mark_checkpoint_checked(2)
            logger.debug(f"[EXIT] TP2 检查点到达: {holding_minutes:.1f}min >= {tp2_minutes}min")

            if current_price >= tp2_price:
                logger.info(
                    f"[EXIT] TP2 触发: 价格 {current_price:.4f} >= 目标 {tp2_price:.4f}"
                )
                return ExitSignal(
                    exit_price=current_price,
                    exit_status=PositionStatus.CLOSED_TP2,
                    reason=f"Price reached TP2 target ({tp2_price:.2f}) at T+{tp2_minutes}min",
                    checkpoint=2,
                )
            else:
                logger.debug(
                    f"[EXIT] TP2 未达标: 价格 {current_price:.4f} < 目标 {tp2_price:.4f}"
                )

    # 检查点 3: T+6分钟
    if not market_state.tp3_checked:
        tp3_minutes, tp3_price = config.get_take_profit_target(3)

        if holding_minutes >= tp3_minutes:
            market_state.mark_checkpoint_checked(3)
            logger.debug(f"[EXIT] TP3 检查点到达: {holding_minutes:.1f}min >= {tp3_minutes}min")

            if current_price >= tp3_price:
                logger.info(
                    f"[EXIT] TP3 触发: 价格 {current_price:.4f} >= 目标 {tp3_price:.4f}"
                )
                return ExitSignal(
                    exit_price=current_price,
                    exit_status=PositionStatus.CLOSED_TP3,
                    reason=f"Price reached TP3 target ({tp3_price:.2f}) at T+{tp3_minutes}min",
                    checkpoint=3,
                )
            else:
                logger.debug(
                    f"[EXIT] TP3 未达标: 价格 {current_price:.4f} < 目标 {tp3_price:.4f}"
                )

    return None


def check_exit(
    position: Position,
    current_price: Decimal,
    config: StrategyConfig,
    market_state: MarketState,
) -> Optional[ExitSignal]:
    """
    检查是否满足出场条件（止盈或止损）

    优先级:
    1. 止损（实时监控）
    2. 止盈（时间阶梯）

    Args:
        position: 当前持仓
        current_price: 当前价格
        config: 策略配置
        market_state: 市场状态

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

    # 然后检查止盈
    tp_signal = check_take_profit(position, config, market_state, current_price)
    if tp_signal:
        return tp_signal

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
            f"[EXIT] 止损触发: 价格 {current_price:.4f} <= 止损线 {config.stop_loss_price:.4f}"
        )
        return ExitSignal(
            exit_price=current_price,
            exit_status=PositionStatus.CLOSED_SL,
            reason=f"Price fell below stop-loss threshold ({config.stop_loss_price:.2f})",
            checkpoint=0,
        )

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
        header = f"TAKE-PROFIT TRIGGERED (TP{signal.checkpoint})"

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


def get_next_checkpoint(market_state: MarketState) -> int:
    """
    获取下一个待检查的止盈点

    Returns:
        检查点编号 (1, 2, 3) 或 0（如果都已检查）
    """
    if not market_state.tp1_checked:
        return 1
    if not market_state.tp2_checked:
        return 2
    if not market_state.tp3_checked:
        return 3
    return 0
