"""
市场状态模块

管理单个市场的监控状态，包括价格快照和持仓状态。
"""
from dataclasses import dataclass, field
from datetime import datetime, timezone
from decimal import Decimal
from typing import Optional

from strategy.position import Position


@dataclass
class TokenPrice:
    """代币价格快照"""
    bid: Decimal                    # 买价
    ask: Decimal                    # 卖价
    mid: Decimal                    # 中间价
    timestamp: datetime             # 时间戳

    @classmethod
    def from_quote_tick(cls, bid: Decimal, ask: Decimal) -> 'TokenPrice':
        """从报价创建"""
        return cls(
            bid=bid,
            ask=ask,
            mid=(bid + ask) / 2,
            timestamp=datetime.now(timezone.utc),
        )

    @property
    def spread(self) -> Decimal:
        """价差"""
        return self.ask - self.bid

    @property
    def spread_percent(self) -> Decimal:
        """价差百分比"""
        if self.mid == 0:
            return Decimal("0")
        return self.spread / self.mid * 100

    def __repr__(self) -> str:
        return f"TokenPrice(mid={self.mid:.4f}, spread={self.spread_percent:.2f}%)"


@dataclass
class MarketState:
    """市场监控状态"""

    # 市场信息
    market_slug: str
    market_start_time: datetime      # 市场开盘时间
    market_end_time: datetime        # 市场结束时间

    # 当前价格
    yes_price: Optional[TokenPrice] = field(default=None)   # UP/YES 代币价格
    no_price: Optional[TokenPrice] = field(default=None)    # DOWN/NO 代币价格

    # 当前持仓
    current_position: Optional[Position] = field(default=None)

    # 检查点状态
    tp1_checked: bool = field(default=False)        # 第一止盈点是否已检查
    tp2_checked: bool = field(default=False)        # 第二止盈点是否已检查
    tp3_checked: bool = field(default=False)        # 第三止盈点是否已检查

    @property
    def minutes_since_open(self) -> float:
        """市场开盘后经过的分钟数"""
        now = datetime.now(timezone.utc)
        return (now - self.market_start_time).total_seconds() / 60

    @property
    def minutes_until_close(self) -> float:
        """距离市场关闭的分钟数"""
        now = datetime.now(timezone.utc)
        return (self.market_end_time - now).total_seconds() / 60

    @property
    def is_active(self) -> bool:
        """市场是否活跃"""
        return self.minutes_since_open >= 0 and self.minutes_until_close > 0

    @property
    def has_position(self) -> bool:
        """是否有活跃持仓"""
        return self.current_position is not None and self.current_position.is_open

    def update_yes_price(self, bid: Decimal, ask: Decimal) -> None:
        """更新 YES 代币价格"""
        self.yes_price = TokenPrice.from_quote_tick(bid, ask)

    def update_no_price(self, bid: Decimal, ask: Decimal) -> None:
        """更新 NO 代币价格"""
        self.no_price = TokenPrice.from_quote_tick(bid, ask)

    def get_position_holding_minutes(self) -> float:
        """获取持仓时间（分钟）"""
        if not self.has_position:
            return 0.0
        return self.current_position.holding_minutes

    def mark_checkpoint_checked(self, checkpoint: int) -> None:
        """标记检查点已检查"""
        if checkpoint == 1:
            self.tp1_checked = True
        elif checkpoint == 2:
            self.tp2_checked = True
        elif checkpoint == 3:
            self.tp3_checked = True

    def is_checkpoint_checked(self, checkpoint: int) -> bool:
        """检查指定检查点是否已检查"""
        if checkpoint == 1:
            return self.tp1_checked
        elif checkpoint == 2:
            return self.tp2_checked
        elif checkpoint == 3:
            return self.tp3_checked
        return True

    def reset_checkpoints(self) -> None:
        """重置所有检查点状态"""
        self.tp1_checked = False
        self.tp2_checked = False
        self.tp3_checked = False

    def to_dict(self) -> dict:
        """序列化为字典"""
        return {
            "market_slug": self.market_slug,
            "market_start_time": self.market_start_time.isoformat(),
            "market_end_time": self.market_end_time.isoformat(),
            "yes_price": {
                "bid": str(self.yes_price.bid),
                "ask": str(self.yes_price.ask),
                "mid": str(self.yes_price.mid),
            } if self.yes_price else None,
            "no_price": {
                "bid": str(self.no_price.bid),
                "ask": str(self.no_price.ask),
                "mid": str(self.no_price.mid),
            } if self.no_price else None,
            "current_position": self.current_position.to_dict() if self.current_position else None,
            "checkpoints": {
                "tp1_checked": self.tp1_checked,
                "tp2_checked": self.tp2_checked,
                "tp3_checked": self.tp3_checked,
            },
            "minutes_since_open": self.minutes_since_open,
        }

    def __repr__(self) -> str:
        yes_str = f"YES={self.yes_price.mid:.4f}" if self.yes_price else "YES=N/A"
        no_str = f"NO={self.no_price.mid:.4f}" if self.no_price else "NO=N/A"
        pos_str = f"POS={self.current_position.direction.value}" if self.has_position else "NO_POS"
        return f"MarketState({self.market_slug}, {yes_str}, {no_str}, {pos_str}, t+{self.minutes_since_open:.1f}min)"
