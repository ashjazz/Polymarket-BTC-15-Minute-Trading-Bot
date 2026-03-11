"""
策略配置模块

从环境变量加载策略参数，提供配置验证功能。
"""
from dataclasses import dataclass, field
from decimal import Decimal
from typing import List, Tuple
import os


@dataclass
class StrategyConfig:
    """策略配置参数"""

    # 入场条件
    entry_price_low: Decimal = Decimal("0.28")      # 入场区间下限
    entry_price_high: Decimal = Decimal("0.32")     # 入场区间上限
    position_size_usd: Decimal = Decimal("2.0")     # 每笔交易金额（USDC）
    buy_window_minutes: int = 8                      # 买入窗口（分钟）

    # 多目标价止盈（实时监控，从高到低检查，达到任一目标价立即卖出）
    # 注意：列表必须从高到低排序 [0.55, 0.50, 0.45]
    # 这样当价格=0.55时，会优先匹配最高目标价卖出
    take_profit_prices: List[Decimal] = field(default_factory=lambda: [
        Decimal("0.55"),  # 最高目标价（优先检查）
        Decimal("0.50"),  # 中等目标价
        Decimal("0.45"),  # 最低目标价
    ])

    # 止损
    stop_loss_price: Decimal = Decimal("0.20")      # 止损价格

    @classmethod
    def from_env(cls) -> 'StrategyConfig':
        """从环境变量加载配置"""
        def get_decimal(key: str, default: str) -> Decimal:
            return Decimal(os.getenv(key, default))

        def get_int(key: str, default: int) -> int:
            return int(os.getenv(key, str(default)))

        # 解析多目标价（逗号分隔，从高到低）
        tp_prices_str = os.getenv("TAKE_PROFIT_PRICES", "0.55,0.50,0.45")
        tp_prices = [Decimal(p.strip()) for p in tp_prices_str.split(",") if p.strip()]
        # 确保从高到低排序
        tp_prices = sorted(tp_prices, reverse=True)

        return cls(
            entry_price_low=get_decimal("ENTRY_PRICE_LOW", "0.28"),
            entry_price_high=get_decimal("ENTRY_PRICE_HIGH", "0.32"),
            position_size_usd=get_decimal("POSITION_SIZE_USD", "2.0"),
            buy_window_minutes=get_int("BUY_WINDOW_MINUTES", "8"),
            take_profit_prices=tp_prices if tp_prices else [
                Decimal("0.55"), Decimal("0.50"), Decimal("0.45")
            ],
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

        # 多目标价验证
        if not self.take_profit_prices:
            errors.append("take_profit_prices 不能为空")

        for i, price in enumerate(self.take_profit_prices):
            if price <= self.entry_price_high:
                errors.append(f"止盈目标价 {i+1} ({price}) 必须 > 入场区间上限 ({self.entry_price_high})")
            if price > 1:
                errors.append(f"止盈目标价 {i+1} ({price}) 不能 > 1")

        # 验证止盈目标价从高到低排序
        for i in range(len(self.take_profit_prices) - 1):
            if self.take_profit_prices[i] <= self.take_profit_prices[i + 1]:
                errors.append(f"止盈目标价必须从高到低排序: {self.take_profit_prices[i]} <= {self.take_profit_prices[i + 1]}")

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

    def get_lowest_take_profit(self) -> Decimal:
        """获取最低止盈目标价"""
        return min(self.take_profit_prices) if self.take_profit_prices else Decimal("1.0")

    def get_highest_take_profit(self) -> Decimal:
        """获取最高止盈目标价"""
        return max(self.take_profit_prices) if self.take_profit_prices else Decimal("1.0")

    def check_take_profit_hit(self, current_price: Decimal) -> Tuple[bool, int, Decimal]:
        """
        检查是否达到任一止盈目标（从高到低检查）

        Args:
            current_price: 当前价格

        Returns:
            (hit, level, target_price): 是否命中、命中的级别(1-based)、命中的目标价
        """
        # 从高到低检查，优先匹配最高目标价
        for i, target_price in enumerate(self.take_profit_prices):
            if current_price >= target_price:
                return (True, i + 1, target_price)
        return (False, 0, Decimal("0"))

    def __repr__(self) -> str:
        tp_str = ", ".join([f"{p:.2f}" for p in self.take_profit_prices])
        return (
            f"StrategyConfig("
            f"entry=[{self.entry_price_low:.2f}-{self.entry_price_high:.2f}], "
            f"size=${self.position_size_usd:.2f}, "
            f"window={self.buy_window_minutes}min, "
            f"TP=[{tp_str}], "
            f"SL={self.stop_loss_price:.2f})"
        )
