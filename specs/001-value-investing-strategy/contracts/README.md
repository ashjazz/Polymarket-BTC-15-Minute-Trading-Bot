# 内部模块接口契约

## 概述

本文档定义了策略模块之间的内部接口契约。这些接口确保模块间的松耦合和可测试性。

## 模块依赖关系

```
┌─────────────────────────────────────────────────────────────┐
│                        bot.py                                │
│  (IntegratedBTCStrategy - NautilusTrader Strategy 子类)     │
└──────────────────────────┬──────────────────────────────────┘
                           │
           ┌───────────────┼───────────────┐
           │               │               │
           ▼               ▼               ▼
┌─────────────────┐ ┌─────────────────┐ ┌─────────────────┐
│ strategy/config │ │ strategy/entry  │ │ strategy/exit   │
│  (配置加载)      │ │  (入场逻辑)      │ │  (出场逻辑)      │
└─────────────────┘ └─────────────────┘ └─────────────────┘
                           │               │
                           └───────┬───────┘
                                   │
                                   ▼
                          ┌─────────────────┐
                          │strategy/position│
                          │  (持仓状态)      │
                          └─────────────────┘
```

## 1. StrategyConfig 接口

**文件**: `strategy/config.py`

### 公共方法

```python
@classmethod
def from_env() -> StrategyConfig:
    """从环境变量加载配置"""

def validate() -> List[str]:
    """验证配置，返回错误列表"""

def is_entry_price(price: Decimal) -> bool:
    """检查价格是否在入场区间内"""

def is_in_buy_window(minutes_since_open: float) -> bool:
    """检查是否在买入窗口内"""
```

### 使用示例

```python
config = StrategyConfig.from_env()
errors = config.validate()
if errors:
    raise ValueError(f"配置错误: {errors}")

if config.is_entry_price(current_price) and config.is_in_buy_window(minutes):
    # 执行买入
    pass
```

## 2. EntryLogic 接口

**文件**: `strategy/entry_logic.py`

### 公共方法

```python
def check_entry(
    yes_price: Optional[TokenPrice],
    no_price: Optional[TokenPrice],
    config: StrategyConfig,
    market_state: MarketState,
) -> Optional[EntrySignal]:
    """
    检查是否满足入场条件

    返回:
        - EntrySignal: 包含方向和价格，如果满足入场条件
        - None: 如果不满足入场条件
    """
```

### EntrySignal 数据结构

```python
@dataclass
class EntrySignal:
    direction: PositionDirection  # UP 或 DOWN
    price: Decimal               # 入场价格
    reason: str                  # 触发原因
```

## 3. ExitLogic 接口

**文件**: `strategy/exit_logic.py`

### 公共方法

```python
def check_exit(
    position: Position,
    current_price: Decimal,
    config: StrategyConfig,
) -> Optional[ExitSignal]:
    """
    检查是否满足出场条件（止盈或止损）

    返回:
        - ExitSignal: 包含出场原因和状态
        - None: 如果不满足出场条件
    """
```

### ExitSignal 数据结构

```python
@dataclass
class ExitSignal:
    exit_price: Decimal
    exit_status: PositionStatus  # CLOSED_TP1, CLOSED_TP2, CLOSED_TP3, CLOSED_SL
    reason: str
```

## 4. Position 接口

**文件**: `strategy/position.py`

### 公共方法

```python
def close(
    exit_price: Decimal,
    exit_time: datetime,
    reason: str,
    status: PositionStatus,
) -> None:
    """平仓"""

def to_dict() -> dict:
    """序列化为字典"""

@property
def pnl() -> Optional[Decimal]:
    """已实现盈亏"""

@property
def holding_minutes() -> float:
    """持有时间（分钟）"""
```

## 5. MarketState 接口

**文件**: `strategy/market_state.py`

### 公共方法

```python
def update_yes_price(bid: Decimal, ask: Decimal) -> None:
    """更新 YES 代币价格"""

def update_no_price(bid: Decimal, ask: Decimal) -> None:
    """更新 NO 代币价格"""

@property
def has_position() -> bool:
    """是否有活跃持仓"""

@property
def is_in_buy_window() -> bool:
    """是否在买入窗口内"""
```

## 6. 与 NautilusTrader 的集成接口

### on_quote_tick 处理流程

```python
def on_quote_tick(self, tick: QuoteTick):
    """
    行情处理入口点

    流程:
    1. 识别 tick 来自哪个代币（YES 或 NO）
    2. 更新 MarketState 中的价格
    3. 如果有持仓，检查出场条件
    4. 如果无持仓且在买入窗口，检查入场条件
    """
```

### 订单执行接口

```python
async def _place_buy_order(
    instrument_id: InstrumentId,
    size_usd: Decimal,
) -> None:
    """执行买入订单"""

async def _place_sell_order(
    instrument_id: InstrumentId,
    size_usd: Decimal,
) -> None:
    """执行卖出订单"""
```

## 测试契约

每个模块必须提供以下测试：

### StrategyConfig 测试

```python
def test_config_from_env():
    """测试从环境变量加载配置"""

def test_config_validation():
    """测试配置验证"""

def test_is_entry_price():
    """测试入场价格判断"""
```

### EntryLogic 测试

```python
def test_check_entry_yes_trigger():
    """测试 YES 代币入场触发"""

def test_check_entry_no_trigger():
    """测试 NO 代币入场触发"""

def test_check_entry_outside_window():
    """测试窗口外不触发"""

def test_check_entry_already_has_position():
    """测试已有持仓时不触发"""
```

### ExitLogic 测试

```python
def test_take_profit_1_trigger():
    """测试第一止盈点触发"""

def test_take_profit_2_trigger():
    """测试第二止盈点触发"""

def test_take_profit_3_trigger():
    """测试第三止盈点触发"""

def test_stop_loss_trigger():
    """测试止损触发"""

def test_no_exit_condition():
    """测试无出场条件时返回 None"""
```

## 版本控制

当修改接口时：

1. **向后兼容的变更**: 可以直接修改
2. **破坏性变更**: 必须创建新版本的接口，并保留旧版本一段时间
3. **所有变更**: 必须更新本文档

## 当前版本

- StrategyConfig: v1.0
- EntryLogic: v1.0
- ExitLogic: v1.0
- Position: v1.0
- MarketState: v1.0
