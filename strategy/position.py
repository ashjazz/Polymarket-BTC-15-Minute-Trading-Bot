"""
持仓状态模块

定义持仓方向、状态枚举和持仓数据类。
"""
from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import Decimal
from enum import Enum
from typing import Optional


class PositionStatus(Enum):
    """持仓状态"""
    OPEN = "OPEN"                    # 活跃持仓
    CLOSED_TP1 = "CLOSED_TP1"        # 第一止盈平仓
    CLOSED_TP2 = "CLOSED_TP2"        # 第二止盈平仓
    CLOSED_TP3 = "CLOSED_TP3"        # 第三止盈平仓
    CLOSED_SL = "CLOSED_SL"          # 止损平仓
    CLOSED_EOD = "CLOSED_EOD"        # 市场结束平仓


class PositionDirection(Enum):
    """持仓方向"""
    UP = "UP"      # 买入 YES（看涨）
    DOWN = "DOWN"  # 买入 NO（看跌）


@dataclass
class Position:
    """持仓状态"""

    # 必填字段
    market_slug: str                 # 市场标识符
    direction: PositionDirection     # 方向
    entry_price: Decimal             # 入场价格
    entry_time: datetime             # 入场时间（T0）
    size_usd: Decimal                # 仓位大小（USDC）

    # 状态
    status: PositionStatus = PositionStatus.OPEN

    # 平仓信息（如已平仓）
    exit_price: Optional[Decimal] = None
    exit_time: Optional[datetime] = None
    exit_reason: Optional[str] = None

    @property
    def pnl(self) -> Optional[Decimal]:
        """已实现盈亏（USDC）"""
        if self.exit_price is None:
            return None
        # 盈亏 = (出场价 - 入场价) / 入场价 * 仓位大小
        return (self.exit_price - self.entry_price) / self.entry_price * self.size_usd

    @property
    def pnl_percent(self) -> Optional[Decimal]:
        """盈亏百分比"""
        if self.exit_price is None:
            return None
        return (self.exit_price - self.entry_price) / self.entry_price * 100

    @property
    def is_open(self) -> bool:
        """是否活跃"""
        return self.status == PositionStatus.OPEN

    @property
    def holding_minutes(self) -> float:
        """持有时间（分钟）"""
        now = datetime.now(timezone.utc)
        return (now - self.entry_time).total_seconds() / 60

    def close(
        self,
        exit_price: Decimal,
        exit_time: datetime,
        reason: str,
        status: PositionStatus
    ) -> None:
        """平仓"""
        self.exit_price = exit_price
        self.exit_time = exit_time
        self.exit_reason = reason
        self.status = status

    def unrealized_pnl(self, current_price: Decimal) -> Decimal:
        """计算未实现盈亏"""
        return (current_price - self.entry_price) / self.entry_price * self.size_usd

    def unrealized_pnl_percent(self, current_price: Decimal) -> Decimal:
        """计算未实现盈亏百分比"""
        return (current_price - self.entry_price) / self.entry_price * 100

    def unrealized_pnl_percent(self, current_price: Decimal) -> Decimal:
        """计算未实现盈亏百分比"""
        return (current_price - self.entry_price) / self.entry_price * 100

    def to_dict(self) -> dict:
        """序列化为字典"""
        return {
            "market_slug": self.market_slug,
            "direction": self.direction.value,
            "entry_price": str(self.entry_price),
            "entry_time": self.entry_time.isoformat(),
            "size_usd": str(self.size_usd),
            "status": self.status.value,
            "exit_price": str(self.exit_price) if self.exit_price else None,
            "exit_time": self.exit_time.isoformat() if self.exit_time else None,
            "exit_reason": self.exit_reason,
            "pnl": str(self.pnl) if self.pnl else None,
            "pnl_percent": str(self.pnl_percent) if self.pnl_percent else None,
        }

    @classmethod
    def from_dict(cls, data: dict) -> 'Position':
        """从字典创建 Position"""
        return cls(
            market_slug=data["market_slug"],
            direction=PositionDirection(data["direction"]),
            entry_price=Decimal(data["entry_price"]),
            entry_time=datetime.fromisoformat(data["entry_time"]),
            size_usd=Decimal(data["size_usd"]),
            status=PositionStatus(data.get("status", "OPEN")),
            exit_price=Decimal(data["exit_price"]) if data.get("exit_price") else None,
            exit_time=datetime.fromisoformat(data["exit_time"]) if data.get("exit_time") else None,
            exit_reason=data.get("exit_reason"),
        )

    def __repr__(self) -> str:
        if self.is_open:
            return (
                f"Position({self.direction.value} @ {self.entry_price:.4f}, "
                f"size=${self.size_usd:.2f}, "
                f"holding={self.holding_minutes:.1f}min, "
                f"status={self.status.value})"
            )
        else:
            return (
                f"Position({self.direction.value} @ {self.entry_price:.4f} → {self.exit_price:.4f}, "
                f"pnl={self.pnl_percent:+.1f}%, "
                f"status={self.status.value})"
            )
