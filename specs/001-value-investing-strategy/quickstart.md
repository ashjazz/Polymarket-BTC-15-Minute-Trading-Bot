# 价值投资策略快速入门指南

本文档介绍独立策略模块的架构和使用方法。

---

## 快速启动

### 1. 环境准备

```bash
# 激活 conda 环境（必需）
conda activate poly

# 安装依赖
pip install -r requirements.txt

# 启动 Redis（用于模式切换，可选）
redis-server
```

### 2. 配置环境变量

复制并编辑 `.env` 文件：

```bash
cp .env.example .env
```

**必需配置：**

```bash
# Polymarket API 凭证（从 Polymarket 网站获取）
POLYMARKET_PK=你的私钥
POLYMARKET_API_KEY=你的API密钥
POLYMARKET_API_SECRET=你的API密钥
POLYMARKET_PASSPHRASE=你的密码

# Redis（可选，用于动态模式切换）
REDIS_HOST=localhost
REDIS_PORT=6379
REDIS_DB=2

# 代理（如在中国大陆）
PROXY_URL=http://localhost:7890
```

**策略参数（可选，使用默认值）：**

```bash
# 入场条件
ENTRY_PRICE_LOW=0.28
ENTRY_PRICE_HIGH=0.32
POSITION_SIZE_USD=2.0
BUY_WINDOW_MINUTES=8

# 止盈目标价（逗号分隔，从高到低）
TAKE_PROFIT_PRICES=0.55,0.50,0.45

# 止损价格
STOP_LOSS_PRICE=0.20
```

### 3. 启动机器人

```bash
# 模拟模式（默认，纸面交易，无真实订单）
python bot.py

# 测试模式（更快的交易间隔，用于测试）
python bot.py --test-mode

# 实盘模式（真实资金！）
python bot.py --live

# 禁用 Grafana 监控
python bot.py --no-grafana

# 使用自动重启包装器（推荐生产环境使用）
python 15m_bot_runner.py              # 模拟模式
python 15m_bot_runner.py --test-mode  # 测试模式
python 15m_bot_runner.py --live       # 实盘模式
```

### 4. 运行模式说明

| 模式 | 命令 | 说明 |
|------|------|------|
| **模拟模式** | `python bot.py` | 纸面交易，不会下真实订单 |
| **测试模式** | `python bot.py --test-mode` | 更快的交易间隔（1分钟），用于策略测试 |
| **实盘模式** | `python bot.py --live` | 真实资金交易，请谨慎使用 |

### 5. 查看交易记录

```bash
# 查看纸面交易记录
python view_paper_trades.py

# 检查账户状态
python check_account.py

# 检查余额
python check_balance.py
```

---

## 系统架构概览

```
┌─────────────────────────────────────────────────────────────────────┐
│                        策略模块架构                                   │
├─────────────────────────────────────────────────────────────────────┤
│                                                                      │
│  strategy/                                                           │
│  ├── __init__.py          # 模块入口，统一导出                        │
│  ├── config.py            # 策略配置（多目标价止盈）                   │
│  ├── position.py          # 持仓状态管理                              │
│  ├── market_state.py      # 市场状态和价格数据                        │
│  ├── entry_logic.py       # 入场逻辑（价值区检测）                    │
│  └── exit_logic.py        # 出场逻辑（实时价格监控）                   │
│                                                                      │
│  tests/                                                              │
│  ├── test_config.py       # 配置测试（10 个测试）                     │
│  ├── test_exit_logic.py   # 出场逻辑测试（16 个测试）                  │
│  └── test_integration.py  # 集成测试（5 个测试）                      │
│                                                                      │
└─────────────────────────────────────────────────────────────────────┘
```

## 核心组件说明

### 1. StrategyConfig - 策略配置

```python
from strategy import StrategyConfig
from decimal import Decimal

# 使用默认配置
config = StrategyConfig()

# 从环境变量加载
config = StrategyConfig.from_env()

# 自定义配置
config = StrategyConfig(
    entry_price_low=Decimal("0.25"),
    entry_price_high=Decimal("0.35"),
    position_size_usd=Decimal("5.0"),
    buy_window_minutes=10,
    take_profit_prices=[Decimal("0.60"), Decimal("0.55"), Decimal("0.50")],
    stop_loss_price=Decimal("0.15"),
)
```

**配置参数说明：**

| 参数 | 默认值 | 说明 |
|------|--------|------|
| `entry_price_low` | 0.28 | 入场价格区间下限 |
| `entry_price_high` | 0.32 | 入场价格区间上限 |
| `position_size_usd` | 2.0 | 每次交易金额（USDC） |
| `buy_window_minutes` | 8 | 开盘后允许买入的窗口期（分钟） |
| `take_profit_prices` | [0.55, 0.50, 0.45] | 止盈目标价（从高到低） |
| `stop_loss_price` | 0.20 | 止损价格 |

### 2. Position - 持仓管理

```python
from strategy import Position, PositionDirection, PositionStatus
from decimal import Decimal
from datetime import datetime, timezone

# 创建持仓
position = Position(
    market_slug="btc-above-94000-1700000000",
    direction=PositionDirection.UP,  # 买入 YES（看涨）
    entry_price=Decimal("0.30"),
    entry_time=datetime.now(timezone.utc),
    size_usd=Decimal("2.0"),
)

# 检查持仓状态
position.is_open          # True
position.holding_minutes  # 持有时长（分钟）

# 计算未实现盈亏
position.unrealized_pnl(Decimal("0.50"))         # Decimal("1.33")
position.unrealized_pnl_percent(Decimal("0.50")) # Decimal("66.67")

# 平仓
position.close(
    exit_price=Decimal("0.55"),
    exit_time=datetime.now(timezone.utc),
    reason="止盈目标价1触发",
    status=PositionStatus.CLOSED_TP1,
)

# 查看已实现盈亏
position.pnl         # Decimal("1.67")
position.pnl_percent # Decimal("83.33")
```

### 3. MarketState - 市场状态

```python
from strategy import MarketState, TokenPrice
from datetime import datetime, timezone, timedelta

# 创建市场状态
market = MarketState(
    market_slug="btc-above-94000-1700000000",
    market_start_time=datetime.now(timezone.utc),
    market_end_time=datetime.now(timezone.utc) + timedelta(minutes=15),
)

# 设置价格
yes_price = TokenPrice.from_quote_tick(Decimal("0.29"), Decimal("0.31"))
no_price = TokenPrice.from_quote_tick(Decimal("0.70"), Decimal("0.72"))

market.yes_token_price = yes_price
market.no_token_price = no_price

# 关联持仓
market.current_position = position
```

### 4. 入场逻辑

```python
from strategy import check_entry, should_skip_entry, format_entry_log

# 检查入场条件
entry_signal = check_entry(yes_price, no_price, config, market)

if entry_signal:
    print(f"入场信号: {entry_signal.direction.value}")
    print(f"入场价格: {entry_signal.price}")
    print(f"入场原因: {entry_signal.reason}")

# 检查是否跳过入场
skip, reason = should_skip_entry(market, config)
if skip:
    print(f"跳过入场: {reason}")
```

**入场条件：**
1. 价格在价值区间内（0.28-0.32）
2. 在买入窗口期内（开盘后 8 分钟内）
3. 市场没有已持仓

### 5. 出场逻辑（实时价格监控）

```python
from strategy import check_exit, check_take_profit, check_stop_loss

# 综合检查出场（止损优先）
exit_signal = check_exit(position, current_price, config, market)

if exit_signal:
    print(f"出场价格: {exit_signal.exit_price}")
    print(f"出场状态: {exit_signal.exit_status.value}")
    print(f"出场原因: {exit_signal.reason}")
    print(f"目标级别: {exit_signal.level}")  # 1=最高, 2=中等, 3=最低, 0=止损

# 单独检查止盈
tp_signal = check_take_profit(position, config, current_price)

# 单独检查止损
sl_signal = check_stop_loss(position, current_price, config)
```

**出场逻辑特点：**
- **实时监控**：每次价格更新都检查，无检测空档期
- **高价格优先**：从高到低检查止盈目标价（0.55 → 0.50 → 0.45）
- **止损优先**：止损检查在止盈之前

## 完整交易流程示例

```python
from decimal import Decimal
from datetime import datetime, timezone, timedelta

from strategy import (
    StrategyConfig,
    MarketState,
    TokenPrice,
    check_entry,
    check_exit,
    PositionDirection,
    PositionStatus,
)

# 1. 初始化配置
config = StrategyConfig()

# 2. 创建市场
now = datetime.now(timezone.utc)
market = MarketState(
    market_slug="btc-above-94000-1700000000",
    market_start_time=now,
    market_end_time=now + timedelta(minutes=15),
)

# 3. 模拟价格更新
def on_price_update(yes_bid: Decimal, yes_ask: Decimal,
                    no_bid: Decimal, no_ask: Decimal):
    """每次价格更新时调用"""

    # 更新市场价格
    yes_price = TokenPrice.from_quote_tick(yes_bid, yes_ask)
    no_price = TokenPrice.from_quote_tick(no_bid, no_ask)
    market.yes_token_price = yes_price
    market.no_token_price = no_price

    # 如果没有持仓，检查入场
    if market.current_position is None:
        entry_signal = check_entry(yes_price, no_price, config, market)
        if entry_signal:
            # 执行买入...
            print(f"入场: {entry_signal.direction.value} @ {entry_signal.price}")
            return

    # 如果有持仓，检查出场
    if market.current_position and market.current_position.is_open:
        # 获取当前价格
        if market.current_position.direction == PositionDirection.UP:
            current_price = yes_price.best_ask  # 卖出用卖价
        else:
            current_price = no_price.best_ask

        exit_signal = check_exit(
            market.current_position,
            current_price,
            config,
            market
        )

        if exit_signal:
            # 执行卖出...
            print(f"出场: {exit_signal.exit_status.value} @ {exit_signal.exit_price}")
            market.current_position.close(
                exit_price=exit_signal.exit_price,
                exit_time=datetime.now(timezone.utc),
                reason=exit_signal.reason,
                status=exit_signal.exit_status,
            )
```

## 策略规则总结

### 入场规则
```
价格在 [0.28, 0.32] 区间内
    AND
市场开盘时间 < 8 分钟
    AND
该市场无持仓
    ↓
买入 2 USDC（买入价格更低的那个方向）
```

### 出场规则（实时监控）

```
每次价格更新:
    ├─ 检查止损: 价格 ≤ 0.20?
    │       └─ YES → 立即卖出（-33%）
    │
    └─ 检查止盈（从高到低）:
            ├─ 价格 ≥ 0.55? → TP1 (+83%)
            ├─ 价格 ≥ 0.50? → TP2 (+67%)
            └─ 价格 ≥ 0.45? → TP3 (+50%)
```

## 运行测试

```bash
# 激活环境
conda activate poly

# 运行所有测试
pytest tests/ -v

# 运行特定测试文件
pytest tests/test_config.py -v
pytest tests/test_exit_logic.py -v
pytest tests/test_integration.py -v

# 查看测试覆盖率
pytest tests/ --cov=strategy --cov-report=html
```

## 环境变量配置

创建 `.env` 文件：

```bash
# 入场条件
ENTRY_PRICE_LOW=0.28
ENTRY_PRICE_HIGH=0.32
POSITION_SIZE_USD=2.0
BUY_WINDOW_MINUTES=8

# 止盈目标价（逗号分隔，从高到低）
TAKE_PROFIT_PRICES=0.55,0.50,0.45

# 止损价格
STOP_LOSS_PRICE=0.20
```

## 与主机器人集成

### 当前架构状态

```
┌─────────────────────────────────────────────────────────────────────┐
│                          系统架构                                    │
├─────────────────────────────────────────────────────────────────────┤
│                                                                      │
│  bot.py                          # 主机器人入口                      │
│  ├── NautilusTrader 框架         # WebSocket 实时价格推送            │
│  ├── IntegratedBTCStrategy       # 当前使用的策略类                  │
│  └── Polymarket API              # 订单执行                          │
│                                                                      │
│  strategy/                       # 新的价值投资策略模块（独立）        │
│  ├── config.py                   # 策略配置                          │
│  ├── position.py                 # 持仓管理                          │
│  ├── market_state.py             # 市场状态                          │
│  ├── entry_logic.py              # 入场逻辑                          │
│  └── exit_logic.py               # 出场逻辑                          │
│                                                                      │
└─────────────────────────────────────────────────────────────────────┘
```

**注意**：当前 `bot.py` 使用的是旧的 `IntegratedBTCStrategy` 策略。新的 `strategy/` 模块已完成开发和测试，但尚未集成到主机器人中。

### 集成方案（待实现）

策略模块设计为独立组件，可被主机器人（`bot.py`）调用：

```python
# 在 bot.py 中使用策略模块
from strategy import (
    StrategyConfig,
    check_entry,
    check_exit,
)

# 初始化
config = StrategyConfig.from_env()

# 在价格更新回调中
def on_tick(market_slug, yes_price, no_price):
    market = get_or_create_market(market_slug)
    entry_signal = check_entry(yes_price, no_price, config, market)

    if market.current_position:
        exit_signal = check_exit(
            market.current_position,
            current_price,
            config,
            market
        )
```

### 切换到新策略

要将新策略集成到主机器人，需要：

1. 修改 `bot.py` 中的 `IntegratedBTCStrategy` 类
2. 在 `on_tick` 或 `on_data` 回调中调用 `check_entry` 和 `check_exit`
3. 使用 `MarketState` 管理市场状态
4. 使用 `Position` 跟踪持仓

## 常见问题

### Q: 为什么目标价要从高到低排序？
A: 这样可以确保当价格同时满足多个目标价时，优先以最高价卖出，最大化收益。例如价格涨到 0.58 时，应该匹配 0.55（TP1）而不是 0.45（TP3）。

### Q: 实时价格监控会影响性能吗？
A: 不会。每次价格更新只是简单的数值比较，开销极小。相比原来的时间检查点策略，实时监控可以捕捉到更多的价格波动机会。

### Q: 止损和止盈哪个优先级更高？
A: 止损优先。在 `check_exit` 函数中，会先检查止损条件，再检查止盈条件。

### Q: 一个市场可以有多笔持仓吗？
A: 不可以。每个 15 分钟市场周期内只允许一笔持仓。

## 下一步

1. 阅读 [spec.md](./spec.md) 了解完整策略规格
2. 查看 [tests/](../../../tests/) 目录了解测试用例
3. 在模拟模式下测试策略参数调整效果

---

## 故障排除

### 常见启动问题

| 问题 | 原因 | 解决方案 |
|------|------|----------|
| `ModuleNotFoundError: No module named 'nautilus_trader'` | 依赖未安装 | `pip install -r requirements.txt` |
| `Redis connection failed` | Redis 未启动 | `redis-server` 或忽略（使用静态模式） |
| `No liquidity` 订单被拒绝 | 市场订单簿为空 | 机器人会自动重试 |
| `Market not found` | 市场不存在 | 检查 slug 过滤器是否正确 |
| WebSocket 连接超时 | 网络问题或代理 | 配置 `PROXY_URL` 或使用 VPN |

### 日志位置

```
logs/nautilus/    # NautilusTrader 日志
```

### 调试技巧

```bash
# 查看 Redis 状态
redis-cli ping

# 检查环境变量是否加载
python -c "from dotenv import load_dotenv; import os; load_dotenv(); print(os.getenv('POLYMARKET_PK', 'NOT SET')[:10])"

# 运行测试验证策略模块
pytest tests/ -v
```

---

## 文件索引

| 文件 | 用途 |
|------|------|
| `bot.py` | 主机器人入口 |
| `15m_bot_runner.py` | 自动重启包装器 |
| `strategy/` | 价值投资策略模块 |
| `tests/` | 单元测试和集成测试 |
| `execution/risk_engine.py` | 风险管理 |
| `monitoring/performance_tracker.py` | 交易记录 |
| `view_paper_trades.py` | 查看纸面交易 |
| `check_account.py` | 检查账户状态 |
| `check_balance.py` | 检查余额 |
