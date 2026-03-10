# Phase 2: 核心数据模型（US5 - 状态管理）

**阶段目标**: 实现持仓状态管理和市场状态跟踪的数据模型

**前置依赖**: Phase 1 完成

**用户故事**: US5 - 持仓跟踪与状态管理 (P2)

**预计耗时**: 20-25 分钟

---

## 任务清单

### T007 实现 Position 数据类
- [ ] T007 [P] 创建 `strategy/position.py`，定义持仓状态枚举和 Position 数据类

**文件**: `strategy/position.py`

**完整实现**:
```python
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
```

---

### T008 实现 TokenPrice 和 MarketState 数据类
- [ ] T008 [P] 创建 `strategy/market_state.py`，定义代币价格快照和市场状态

**文件**: `strategy/market_state.py`

**完整实现**:
```python
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
```

---

### T009 编写 Position 单元测试
- [ ] T009 [P] 创建 `tests/test_position.py`，测试持仓状态管理

**文件**: `tests/test_position.py`

**完整实现**:
```python
"""
Position 单元测试
"""
import pytest
from decimal import Decimal
from datetime import datetime, timezone, timedelta
from strategy.position import Position, PositionStatus, PositionDirection


class TestPosition:
    """Position 测试类"""

    @pytest.fixture
    def sample_position(self):
        """创建示例持仓"""
        return Position(
            market_slug="btc-updown-15m-1709251200",
            direction=PositionDirection.UP,
            entry_price=Decimal("0.30"),
            entry_time=datetime.now(timezone.utc) - timedelta(minutes=2),
            size_usd=Decimal("2.0"),
        )

    def test_position_creation(self, sample_position):
        """测试持仓创建"""
        assert sample_position.market_slug == "btc-updown-15m-1709251200"
        assert sample_position.direction == PositionDirection.UP
        assert sample_position.entry_price == Decimal("0.30")
        assert sample_position.size_usd == Decimal("2.0")
        assert sample_position.status == PositionStatus.OPEN
        assert sample_position.is_open is True

    def test_holding_minutes(self, sample_position):
        """测试持有时间计算"""
        # 持仓创建于 2 分钟前
        assert 1.9 < sample_position.holding_minutes < 2.1

    def test_close_position(self, sample_position):
        """测试平仓"""
        exit_time = datetime.now(timezone.utc)
        sample_position.close(
            exit_price=Decimal("0.40"),
            exit_time=exit_time,
            reason="TP1 triggered",
            status=PositionStatus.CLOSED_TP1,
        )

        assert sample_position.status == PositionStatus.CLOSED_TP1
        assert sample_position.is_open is False
        assert sample_position.exit_price == Decimal("0.40")
        assert sample_position.exit_reason == "TP1 triggered"

    def test_pnl_calculation(self, sample_position):
        """测试盈亏计算"""
        # 先平仓
        sample_position.close(
            exit_price=Decimal("0.40"),
            exit_time=datetime.now(timezone.utc),
            reason="TP1",
            status=PositionStatus.CLOSED_TP1,
        )

        # 盈亏 = (0.40 - 0.30) / 0.30 * 2.0 = 0.666...
        expected_pnl = (Decimal("0.40") - Decimal("0.30")) / Decimal("0.30") * Decimal("2.0")
        assert abs(sample_position.pnl - expected_pnl) < Decimal("0.01")

        # 盈亏百分比 = (0.40 - 0.30) / 0.30 * 100 = 33.33%
        expected_pnl_pct = (Decimal("0.40") - Decimal("0.30")) / Decimal("0.30") * 100
        assert abs(sample_position.pnl_percent - expected_pnl_pct) < Decimal("0.1")

    def test_loss_pnl_calculation(self, sample_position):
        """测试亏损计算"""
        sample_position.close(
            exit_price=Decimal("0.20"),
            exit_time=datetime.now(timezone.utc),
            reason="Stop loss",
            status=PositionStatus.CLOSED_SL,
        )

        # 亏损 = (0.20 - 0.30) / 0.30 * 2.0 = -0.666...
        assert sample_position.pnl < 0
        assert sample_position.pnl_percent < 0

    def test_unrealized_pnl(self, sample_position):
        """测试未实现盈亏"""
        # 当前价格 0.45
        unrealized = sample_position.unrealized_pnl(Decimal("0.45"))
        expected = (Decimal("0.45") - Decimal("0.30")) / Decimal("0.30") * Decimal("2.0")
        assert abs(unrealized - expected) < Decimal("0.01")

    def test_to_dict(self, sample_position):
        """测试序列化"""
        data = sample_position.to_dict()

        assert data["market_slug"] == "btc-updown-15m-1709251200"
        assert data["direction"] == "UP"
        assert data["entry_price"] == "0.30"
        assert data["status"] == "OPEN"
        assert data["exit_price"] is None

    def test_from_dict(self):
        """测试反序列化"""
        data = {
            "market_slug": "btc-updown-15m-1709251200",
            "direction": "UP",
            "entry_price": "0.30",
            "entry_time": "2026-03-10T00:00:00+00:00",
            "size_usd": "2.0",
            "status": "CLOSED_TP1",
            "exit_price": "0.40",
            "exit_time": "2026-03-10T00:02:00+00:00",
            "exit_reason": "TP1 triggered",
        }

        position = Position.from_dict(data)

        assert position.market_slug == "btc-updown-15m-1709251200"
        assert position.direction == PositionDirection.UP
        assert position.entry_price == Decimal("0.30")
        assert position.status == PositionStatus.CLOSED_TP1
        assert position.exit_price == Decimal("0.40")

    def test_position_directions(self):
        """测试持仓方向"""
        up_position = Position(
            market_slug="test",
            direction=PositionDirection.UP,
            entry_price=Decimal("0.30"),
            entry_time=datetime.now(timezone.utc),
            size_usd=Decimal("2.0"),
        )
        assert up_position.direction == PositionDirection.UP

        down_position = Position(
            market_slug="test",
            direction=PositionDirection.DOWN,
            entry_price=Decimal("0.30"),
            entry_time=datetime.now(timezone.utc),
            size_usd=Decimal("2.0"),
        )
        assert down_position.direction == PositionDirection.DOWN
```

---

### T010 编写 MarketState 单元测试
- [ ] T010 [P] 创建 `tests/test_market_state.py`，测试市场状态管理

**文件**: `tests/test_market_state.py`

**完整实现**:
```python
"""
MarketState 单元测试
"""
import pytest
from decimal import Decimal
from datetime import datetime, timezone, timedelta
from strategy.market_state import MarketState, TokenPrice
from strategy.position import Position, PositionDirection


class TestTokenPrice:
    """TokenPrice 测试类"""

    def test_from_quote_tick(self):
        """测试从报价创建"""
        price = TokenPrice.from_quote_tick(
            bid=Decimal("0.29"),
            ask=Decimal("0.31"),
        )

        assert price.bid == Decimal("0.29")
        assert price.ask == Decimal("0.31")
        assert price.mid == Decimal("0.30")
        assert price.timestamp is not None

    def test_spread_calculation(self):
        """测试价差计算"""
        price = TokenPrice.from_quote_tick(
            bid=Decimal("0.28"),
            ask=Decimal("0.32"),
        )

        assert price.spread == Decimal("0.04")
        # 价差百分比 = 0.04 / 0.30 * 100 = 13.33%
        expected_spread_pct = Decimal("0.04") / Decimal("0.30") * 100
        assert abs(price.spread_percent - expected_spread_pct) < Decimal("0.1")


class TestMarketState:
    """MarketState 测试类"""

    @pytest.fixture
    def sample_market(self):
        """创建示例市场状态"""
        now = datetime.now(timezone.utc)
        return MarketState(
            market_slug="btc-updown-15m-1709251200",
            market_start_time=now,
            market_end_time=now + timedelta(minutes=15),
        )

    def test_market_creation(self, sample_market):
        """测试市场状态创建"""
        assert sample_market.market_slug == "btc-updown-15m-1709251200"
        assert sample_market.yes_price is None
        assert sample_market.no_price is None
        assert sample_market.current_position is None
        assert sample_market.has_position is False

    def test_minutes_since_open(self, sample_market):
        """测试市场开盘时间计算"""
        # 市场刚开盘
        assert 0 <= sample_market.minutes_since_open < 0.1

    def test_update_prices(self, sample_market):
        """测试更新价格"""
        sample_market.update_yes_price(Decimal("0.70"), Decimal("0.72"))
        sample_market.update_no_price(Decimal("0.28"), Decimal("0.30"))

        assert sample_market.yes_price is not None
        assert sample_market.yes_price.mid == Decimal("0.71")
        assert sample_market.no_price is not None
        assert sample_market.no_price.mid == Decimal("0.29")

    def test_is_active(self, sample_market):
        """测试市场活跃状态"""
        assert sample_market.is_active is True

        # 创建已结束的市场
        ended_market = MarketState(
            market_slug="ended",
            market_start_time=datetime.now(timezone.utc) - timedelta(minutes=20),
            market_end_time=datetime.now(timezone.utc) - timedelta(minutes=5),
        )
        assert ended_market.is_active is False

    def test_has_position(self, sample_market):
        """测试持仓状态"""
        assert sample_market.has_position is False

        # 添加持仓
        sample_market.current_position = Position(
            market_slug="btc-updown-15m-1709251200",
            direction=PositionDirection.UP,
            entry_price=Decimal("0.30"),
            entry_time=datetime.now(timezone.utc),
            size_usd=Decimal("2.0"),
        )
        assert sample_market.has_position is True

    def test_checkpoint_management(self, sample_market):
        """测试检查点管理"""
        assert sample_market.tp1_checked is False
        assert sample_market.tp2_checked is False
        assert sample_market.tp3_checked is False

        # 标记检查点
        sample_market.mark_checkpoint_checked(1)
        assert sample_market.tp1_checked is True
        assert sample_market.is_checkpoint_checked(1) is True

        sample_market.mark_checkpoint_checked(2)
        assert sample_market.tp2_checked is True

        # 重置
        sample_market.reset_checkpoints()
        assert sample_market.tp1_checked is False
        assert sample_market.tp2_checked is False

    def test_to_dict(self, sample_market):
        """测试序列化"""
        sample_market.update_yes_price(Decimal("0.70"), Decimal("0.72"))

        data = sample_market.to_dict()

        assert data["market_slug"] == "btc-updown-15m-1709251200"
        assert data["yes_price"]["mid"] == "0.71"
        assert data["current_position"] is None
        assert "checkpoints" in data
```

---

## 阶段验收标准

- [ ] `strategy/position.py` 文件存在
- [ ] `strategy/market_state.py` 文件存在
- [ ] `Position` 类正确计算盈亏和持有时间
- [ ] `TokenPrice` 类正确计算中间价和价差
- [ ] `MarketState` 类正确管理价格和检查点状态
- [ ] 所有单元测试通过

---

## 验证命令

```bash
# 运行所有数据模型测试
python -m pytest tests/test_position.py tests/test_market_state.py -v

# 验证模块导入
python -c "
from strategy.position import Position, PositionStatus, PositionDirection
from strategy.market_state import MarketState, TokenPrice
print('数据模型模块导入成功')
"
```

---

## 完成后

继续执行 **Phase 3: 双向监控与价值入场** → `phase-3-entry.md`
