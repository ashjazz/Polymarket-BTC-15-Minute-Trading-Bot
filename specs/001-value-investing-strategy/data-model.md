# 数据模型：价值投资策略 + 分批止盈系统

**日期**: 2026-03-10

## 实体关系图

```
┌─────────────────┐       ┌─────────────────┐
│ StrategyConfig  │       │   MarketState   │
│  (策略配置)      │       │   (市场状态)     │
├─────────────────┤       ├─────────────────┤
│ entry_price_*   │       │ market_slug     │
│ position_size   │       │ yes_price       │
│ buy_window      │       │ no_price        │
│ take_profit_*   │       │ current_position│
│ stop_loss       │       │ tp*_checked     │
└─────────────────┘       └────────┬────────┘
                                   │
                                   │ 1:1
                                   ▼
                          ┌─────────────────┐
                          │    Position     │
                          │    (持仓)        │
                          ├─────────────────┤
                          │ market_slug     │
                          │ direction       │
                          │ entry_price     │
                          │ entry_time (T0) │
                          │ size_usd        │
                          │ status          │
                          │ exit_price      │
                          │ exit_time       │
                          │ exit_reason     │
                          └─────────────────┘
```

## 1. StrategyConfig（策略配置）

**用途**: 从环境变量加载并验证策略参数

```python
from dataclasses import dataclass
from decimal import Decimal
from typing import List

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
        import os
        from decimal import Decimal

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

        if self.entry_price_low >= self.entry_price_high:
            errors.append("entry_price_low 必须 < entry_price_high")

        if self.position_size_usd <= 0:
            errors.append("position_size_usd 必须 > 0")

        if self.buy_window_minutes <= 0:
            errors.append("buy_window_minutes 必须 > 0")

        # 止盈阶梯必须递增
        if not (self.take_profit_1_minutes < self.take_profit_2_minutes < self.take_profit_3_minutes):
            errors.append("止盈检查点时间必须递增")

        if not (self.take_profit_1_price < self.take_profit_2_price < self.take_profit_3_price):
            errors.append("止盈目标价格必须递增")

        # 止损价格必须低于入场区间
        if self.stop_loss_price >= self.entry_price_low:
            errors.append("stop_loss_price 必须 < entry_price_low")

        return errors
```

## 2. Position（持仓）

**用途**: 跟踪单个市场的持仓状态

```python
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

    def close(self, exit_price: Decimal, exit_time: datetime, reason: str, status: PositionStatus) -> None:
        """平仓"""
        self.exit_price = exit_price
        self.exit_time = exit_time
        self.exit_reason = reason
        self.status = status

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
```

## 3. TokenPrice（代币价格）

**用途**: 缓存代币价格快照

```python
from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import Decimal

@dataclass
class TokenPrice:
    """代币价格快照"""
    bid: Decimal
    ask: Decimal
    mid: Decimal
    timestamp: datetime

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
        return self.spread / self.mid * 100
```

## 4. MarketState（市场状态）

**用途**: 管理单个市场的监控状态

```python
from dataclasses import dataclass, field
from datetime import datetime, timezone
from decimal import Decimal
from typing import Optional

@dataclass
class MarketState:
    """市场监控状态"""

    market_slug: str
    market_start_time: datetime      # 市场开盘时间
    market_end_time: datetime        # 市场结束时间

    # 当前价格
    yes_price: Optional[TokenPrice] = None   # UP/YES 代币价格
    no_price: Optional[TokenPrice] = None    # DOWN/NO 代币价格

    # 当前持仓
    current_position: Optional[Position] = None

    # 检查点状态
    tp1_checked: bool = False        # 第一止盈点是否已检查
    tp2_checked: bool = False        # 第二止盈点是否已检查
    tp3_checked: bool = False        # 第三止盈点是否已检查

    @property
    def minutes_since_open(self) -> float:
        """市场开盘后经过的分钟数"""
        now = datetime.now(timezone.utc)
        return (now - self.market_start_time).total_seconds() / 60

    @property
    def is_in_buy_window(self, config: StrategyConfig) -> bool:
        """是否在买入窗口内"""
        return self.minutes_since_open < config.buy_window_minutes

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
```

## 状态转换

### Position 状态转换图

```
                    ┌─────────────────────────────────────────┐
                    │              OPEN                        │
                    │  (entry_price, entry_time=T0)           │
                    └─────────────────┬───────────────────────┘
                                      │
          ┌───────────────────────────┼───────────────────────────┬───────────────┐
          │                           │                           │               │
          ▼                           ▼                           ▼               ▼
┌─────────────────┐       ┌─────────────────┐       ┌─────────────────┐   ┌─────────────┐
│   CLOSED_TP1    │       │   CLOSED_TP2    │       │   CLOSED_TP3    │   │  CLOSED_SL  │
│  T+2min ≥ 0.40  │       │  T+4min ≥ 0.48  │       │  T+6min ≥ 0.55  │   │ price ≤ 0.20│
│    (+33%)       │       │    (+60%)       │       │    (+83%)       │   │   (-33%)    │
└─────────────────┘       └─────────────────┘       └─────────────────┘   └─────────────┘

                                                                          │
                                                                          │ 市场结束
                                                                          ▼
                                                                  ┌─────────────┐
                                                                  │ CLOSED_EOD  │
                                                                  │ 强制平仓     │
                                                                  └─────────────┘
```

### MarketState 状态转换

```
┌─────────────────┐       ┌─────────────────┐       ┌─────────────────┐
│  MARKET_WAITING │ ────► │  MARKET_ACTIVE  │ ────► │  MARKET_ENDED   │
│  (等待开盘)      │       │  (活跃交易)      │       │  (已结束)        │
└─────────────────┘       └─────────────────┘       └─────────────────┘
                                │
                                │ 价格进入入场区间
                                ▼
                         ┌─────────────────┐
                         │  创建 Position   │
                         └─────────────────┘
```

## 数据流向

```
┌─────────────────┐
│  Environment    │
│  (.env file)    │
└────────┬────────┘
         │ from_env()
         ▼
┌─────────────────┐
│ StrategyConfig  │◄──────────────────────────────┐
└────────┬────────┘                               │
         │                                        │
         ▼                                        │
┌─────────────────┐      ┌─────────────────┐      │
│  EntryLogic     │─────►│    Position     │      │
│  (入场判断)      │      │    (持仓)        │      │
└─────────────────┘      └────────┬────────┘      │
                                  │               │
         ┌────────────────────────┼───────────────┘
         │                        │
         ▼                        ▼
┌─────────────────┐      ┌─────────────────┐
│   ExitLogic     │      │  MarketState    │
│  (出场判断)      │      │  (市场状态)      │
└─────────────────┘      └─────────────────┘
         │
         ▼
┌─────────────────┐
│ PerformanceTracker │
│  (绩效记录)       │
└─────────────────┘
```

## 持久化

### 纸面交易记录（JSON）

```json
{
  "trades": [
    {
      "market_slug": "btc-updown-15m-1709251200",
      "direction": "UP",
      "entry_price": "0.30",
      "entry_time": "2026-03-01T00:00:00Z",
      "size_usd": "2.0",
      "status": "CLOSED_TP2",
      "exit_price": "0.48",
      "exit_time": "2026-03-01T00:04:00Z",
      "exit_reason": "TP2 triggered at T+4min",
      "pnl": "1.20",
      "pnl_percent": "60.00"
    }
  ]
}
```

### 环境变量配置（.env）

```bash
# 入场条件
ENTRY_PRICE_LOW=0.28
ENTRY_PRICE_HIGH=0.32
POSITION_SIZE_USD=2.0
BUY_WINDOW_MINUTES=8

# 止盈阶梯
TAKE_PROFIT_1_MINUTES=2
TAKE_PROFIT_1_PRICE=0.40
TAKE_PROFIT_2_MINUTES=4
TAKE_PROFIT_2_PRICE=0.48
TAKE_PROFIT_3_MINUTES=6
TAKE_PROFIT_3_PRICE=0.55

# 止损
STOP_LOSS_PRICE=0.20
```
