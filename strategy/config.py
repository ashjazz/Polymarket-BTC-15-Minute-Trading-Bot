"""
策略配置模块

从环境变量加载策略参数，提供配置验证功能。
"""
from dataclasses import dataclass
from decimal import Decimal
from typing import List
import os


@dataclass
class StrategyConfig:
    """策略配置参数"""

    # 入场条件
    entry_price_low: Decimal = Decimal("0.28")      # 入场区间下限
    entry_price_high: Decimal = Decimal("0.32")     # 入场区间上限
    position_size_usd: Decimal = Decimal("2.0")     # 每笔交易金额（USDC）
    buy_window_minutes: int = 8                      # 买入窗口（分钟）

    # 止盈阶梯
    take_profit_1_minutes: int = 2                  # 第一检查点时间（分钟）
    take_profit_1_price: Decimal = Decimal("0.40")  # 第一目标价
    take_profit_2_minutes: int = 4                  # 第二检查点时间（分钟）
    take_profit_2_price: Decimal = Decimal("0.48")  # 第二目标价
    take_profit_3_minutes: int = 6                  # 第三检查点时间（分钟）
    take_profit_3_price: Decimal = Decimal("0.55")  # 第三目标价

    # 止损
    stop_loss_price: Decimal = Decimal("0.20")      # 止损价格

    @classmethod
    def from_env(cls) -> 'StrategyConfig':
        """从环境变量加载配置"""
        def get_decimal(key: str, default: str) -> Decimal:
            return Decimal(os.getenv(key, default))

        def get_int(key: str, default: int) -> int:
            return int(os.getenv(key, str(default)))

        return cls(
            entry_price_low=get_decimal("ENTRY_PRICE_LOW", "0.28"),
            entry_price_high=get_decimal("ENTRY_PRICE_HIGH", "0.32"),
            position_size_usd=get_decimal("POSITION_SIZE_USD", "2.0"),
            buy_window_minutes=get_int("BUY_WINDOW_MINUTES", "8"),
            take_profit_1_minutes=get_int("TAKE_PROFIT_1_MINUTES", "2"),
            take_profit_1_price=get_decimal("TAKE_PROFIT_1_PRICE", "0.40"),
            take_profit_2_minutes=get_int("TAKE_PROFIT_2_MINUTES", "4"),
            take_profit_2_price=get_decimal("TAKE_PROFIT_2_PRICE", "0.48"),
            take_profit_3_minutes=get_int("TAKE_PROFIT_3_MINUTES", "6"),
            take_profit_3_price=get_decimal("TAKE_PROFIT_3_PRICE", "0.55"),
            stop_loss_price=get_decimal("STOP_LOSS_PRICE", "0.20"),
        )

    def validate(self) -> List[str]:
        """验证配置有效性，返回错误列表"""
        errors = []

        # 入场区间验证
        if self.entry_price_low >= self.entry_price_high:
            errors.append("entry_price_low 必须 < entry_price_high")

        if self.entry_price_low <= 0 or self.entry_price_high > 1:
            errors.append("入场价格必须在 (0, 1] 范围内")

        # 仓位大小验证
        if self.position_size_usd <= 0:
            errors.append("position_size_usd 必须 > 0")

        # 买入窗口验证
        if self.buy_window_minutes <= 0 or self.buy_window_minutes > 15:
            errors.append("buy_window_minutes 必须在 (0, 15] 范围内")

        # 止盈阶梯验证
        if not (self.take_profit_1_minutes < self.take_profit_2_minutes < self.take_profit_3_minutes):
            errors.append("止盈检查点时间必须递增")

        if not (self.take_profit_1_price < self.take_profit_2_price < self.take_profit_3_price):
            errors.append("止盈目标价格必须递增")

        # 止损价格验证
        if self.stop_loss_price >= self.entry_price_low:
            errors.append("stop_loss_price 必须 < entry_price_low")

        if self.stop_loss_price <= 0:
            errors.append("stop_loss_price 必须 > 0")

        return errors

    def is_entry_price(self, price: Decimal) -> bool:
        """检查价格是否在入场区间内"""
        return self.entry_price_low <= price <= self.entry_price_high

    def is_in_buy_window(self, minutes_since_open: float) -> bool:
        """检查是否在买入窗口内"""
        return 0 <= minutes_since_open < self.buy_window_minutes

    def get_take_profit_target(self, checkpoint: int) -> tuple[int, Decimal]:
        """
        获取指定检查点的止盈目标

        Args:
            checkpoint: 检查点编号 (1, 2, 3)

        Returns:
            (minutes, price) 元组
        """
        targets = {
            1: (self.take_profit_1_minutes, self.take_profit_1_price),
            2: (self.take_profit_2_minutes, self.take_profit_2_price),
            3: (self.take_profit_3_minutes, self.take_profit_3_price),
        }
        return targets.get(checkpoint, (0, Decimal("0")))

    def __repr__(self) -> str:
        return (
            f"StrategyConfig("
            f"entry=[{self.entry_price_low:.2f}-{self.entry_price_high:.2f}], "
            f"size=${self.position_size_usd:.2f}, "
            f"window={self.buy_window_minutes}min, "
            f"TP=[{self.take_profit_1_price:.2f}@{self.take_profit_1_minutes}min, "
            f"{self.take_profit_2_price:.2f}@{self.take_profit_2_minutes}min, "
            f"{self.take_profit_3_price:.2f}@{self.take_profit_3_minutes}min], "
            f"SL={self.stop_loss_price:.2f})"
        )
