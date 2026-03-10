# 快速开始指南：价值投资策略 + 分批止盈系统

## 前置条件

1. **Python 环境**: conda + `poly` 环境
2. **Redis**: 用于模式切换（可选）
3. **Polymarket 账户**: API 凭证

## 快速配置

### 1. 激活环境

```bash
conda activate poly
```

### 2. 配置环境变量

复制并编辑 `.env` 文件：

```bash
cp .env.example .env
```

编辑 `.env`，设置以下关键参数：

```bash
# Polymarket API 凭证（必须）
POLYMARKET_PK=你的私钥
POLYMARKET_API_KEY=你的API密钥
POLYMARKET_API_SECRET=你的API密钥
POLYMARKET_PASSPHRASE=你的密码

# 策略参数（可选，有默认值）
ENTRY_PRICE_LOW=0.28
ENTRY_PRICE_HIGH=0.32
POSITION_SIZE_USD=2.0
BUY_WINDOW_MINUTES=8

TAKE_PROFIT_1_MINUTES=2
TAKE_PROFIT_1_PRICE=0.40
TAKE_PROFIT_2_MINUTES=4
TAKE_PROFIT_2_PRICE=0.48
TAKE_PROFIT_3_MINUTES=6
TAKE_PROFIT_3_PRICE=0.55

STOP_LOSS_PRICE=0.20
```

### 3. 启动 Redis（可选）

如果需要运行时模式切换：

```bash
redis-server
```

## 运行模式

### 模拟模式（推荐先用这个）

```bash
python bot.py
```

- 纸面交易，不花费真钱
- 交易记录保存在 `paper_trades.json`

### 测试模式

```bash
python bot.py --test-mode
```

- 更快的交易间隔，用于快速验证逻辑

### 实盘模式

```bash
python bot.py --live
```

⚠️ **警告**: 使用真实资金交易！

## 验证策略运行

### 检查日志

策略运行时会输出以下关键日志：

```
==========================================================================
 DUAL MONITORING ACTIVE
   Market: btc-updown-15m-1709251200
   YES Price: $0.7200 | NO Price: $0.2800
   Buy Window: 0-8 minutes (current: 2.3 min)
==========================================================================
```

### 入场触发

当价格进入入场区间时：

```
==========================================================================
 VALUE ENTRY TRIGGERED
   Direction: DOWN (NO)
   Entry Price: $0.2950
   Size: $2.00 USDC
   Entry Time: 2026-03-10 00:02:15 UTC (T0)
==========================================================================
```

### 止盈触发

当达到止盈目标时：

```
==========================================================================
 TAKE-PROFIT TRIGGERED
   Checkpoint: TP2 (T+4min)
   Exit Price: $0.4850
   Entry Price: $0.2950
   P&L: +$1.19 USDC (+59.5%)
   Reason: Price reached TP2 target at T+4min
==========================================================================
```

### 止损触发

当触发止损时：

```
==========================================================================
 STOP-LOSS TRIGGERED
   Exit Price: $0.1950
   Entry Price: $0.2950
   P&L: -$0.68 USDC (-33.9%)
   Reason: Price fell below stop-loss threshold
==========================================================================
```

## 查看交易记录

### 纸面交易

```bash
python view_paper_trades.py
```

或直接查看 JSON 文件：

```bash
cat paper_trades.json | python -m json.tool
```

## 常见问题

### 1. 没有入场

- 检查价格是否在入场区间（默认 0.28-0.32）
- 检查是否在买入窗口内（默认前8分钟）
- 检查是否已有持仓（每市场限一仓）

### 2. 订单被拒绝

- 检查 Polymarket 账户余额
- 检查 API 凭证是否正确
- 检查市场是否有足够流动性

### 3. 止盈/止损未触发

- 检查持仓状态是否为 OPEN
- 检查日志中是否有检查点记录
- 检查网络连接是否正常

## 策略参数调优

### 保守策略

```bash
ENTRY_PRICE_LOW=0.25
ENTRY_PRICE_HIGH=0.30
STOP_LOSS_PRICE=0.18
```

### 激进策略

```bash
ENTRY_PRICE_LOW=0.30
ENTRY_PRICE_HIGH=0.35
TAKE_PROFIT_1_PRICE=0.45
TAKE_PROFIT_2_PRICE=0.52
TAKE_PROFIT_3_PRICE=0.60
```

### 大仓位

```bash
POSITION_SIZE_USD=5.0
```

## 下一步

1. 在模拟模式运行至少 24 小时
2. 分析 `paper_trades.json` 中的交易记录
3. 根据结果调整策略参数
4. 确认策略稳定后再切换到实盘模式
