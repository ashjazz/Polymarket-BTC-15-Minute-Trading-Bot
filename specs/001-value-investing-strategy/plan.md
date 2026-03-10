# 实现计划：价值投资策略 + 分批止盈系统

**分支**: `001-value-investing-strategy` | **日期**: 2026-03-10 | **规格**: [spec.md](./spec.md)
**输入**: 功能规格说明 `/specs/001-value-investing-strategy/spec.md`

## 摘要

重写交易策略，从 "Late-Window Trend Following" 转向 "Value Investing + Tiered Take-Profit"。

**核心逻辑**：
1. 双向监控 UP/DOWN 代币价格
2. 价格跌入价值区间（0.28-0.32）时买入
3. 时间阶梯止盈（2min→0.40, 4min→0.48, 6min→0.55）
4. 持续止损监控（0.20）

## 技术上下文

**语言/版本**: Python 3.11 (conda environment: `poly`)
**主要依赖**: NautilusTrader, py_clob_client, redis, loguru, python-dotenv
**存储**: Redis（模式切换），JSON 文件（纸面交易记录）
**测试**: pytest（待添加单元测试）
**目标平台**: Linux/macOS 服务器
**项目类型**: 交易机器人 / 后台服务
**性能目标**:
- 入场识别延迟 < 1秒
- 止盈/止损执行延迟 < 2秒
- 持续运行无需人工干预
**约束**:
- 依赖 Polymarket WebSocket 连接稳定性
- 需要 USDC 余额支持交易
- 网络中断需优雅处理
**规模/范围**: 单用户，单策略，15分钟市场周期

## Constitution Check

*GATE: Must pass before Phase 0 research. Re-check after Phase 1 design.*

| 检查项 | 状态 | 说明 |
|--------|------|------|
| 无复杂度违规 | ✅ | 单一策略重构，无新增架构层 |
| 可测试性 | ✅ | 支持模拟模式，可独立测试各模块 |
| 可观测性 | ✅ | 保留 loguru 日志，Grafana 可选 |
| 简洁性 | ✅ | 移除不需要的信号处理器，简化逻辑 |

## 项目结构

### 文档（本功能）

```text
specs/001-value-investing-strategy/
├── spec.md              # 功能规格说明
├── plan.md              # 本文件（实现计划）
├── research.md          # Phase 0 研究输出
├── data-model.md        # Phase 1 数据模型
├── quickstart.md        # Phase 1 快速开始指南
└── contracts/           # Phase 1 接口契约
    └── strategy-api.md  # 策略接口定义
```

### 源代码（仓库根目录）

```text
bot.py                          # 主入口，策略实现 [需重构]
├── patch_gamma_markets.py      # Polymarket API 补丁 [保留]
├── patch_market_orders.py      # 市场订单补丁 [保留]
│
├── strategy/                   # 新增：策略核心模块
│   ├── __init__.py
│   ├── config.py               # 策略配置类（从 .env 加载）
│   ├── position.py             # 持仓状态管理
│   ├── entry_logic.py          # 入场逻辑（双向监控）
│   ├── exit_logic.py           # 出场逻辑（止盈+止损）
│   └── state_machine.py        # 状态机（检查点管理）
│
├── execution/                  # 执行层
│   └── risk_engine.py          # 风险管理 [保留，简化]
│
├── monitoring/                 # 监控层
│   └── performance_tracker.py  # 交易记录 [保留]
│
├── data_sources/               # 外部数据源 [保留]
│   ├── coinbase/
│   └── news_social/
│
├── tests/                      # 测试 [新增]
│   ├── test_entry_logic.py
│   ├── test_exit_logic.py
│   └── test_state_machine.py
│
└── specs/                      # 规格文档
    └── 001-value-investing-strategy/
```

**结构决策**: 在现有代码库基础上新增 `strategy/` 模块，将核心策略逻辑从 `bot.py` 中抽离，提高可测试性和可维护性。保留现有的 NautilusTrader 集成和执行层。

## 重构范围

### 需要修改的文件

| 文件 | 修改类型 | 说明 |
|------|----------|------|
| `bot.py` | 重构 | 移除旧的信号处理器，集成新的策略模块 |
| `execution/risk_engine.py` | 简化 | 移除不需要的风控逻辑，保留基础检查 |
| `.env.example` | 更新 | 添加新的策略配置参数 |

### 需要新增的文件

| 文件 | 说明 |
|------|------|
| `strategy/config.py` | 策略配置加载和验证 |
| `strategy/position.py` | 持仓状态数据类 |
| `strategy/entry_logic.py` | 入场条件判断 |
| `strategy/exit_logic.py` | 止盈止损逻辑 |
| `strategy/state_machine.py` | 检查点状态机 |
| `tests/test_*.py` | 单元测试 |

### 可以移除/弃用的代码

| 代码 | 状态 | 说明 |
|------|------|------|
| 信号处理器（6个） | 弃用 | SpikeDetection, Sentiment, Divergence, OrderBook, TickVelocity, DeribitPCR |
| 融合引擎 | 弃用 | signal_fusion.py |
| 学习引擎 | 弃用 | learning_engine.py |
| Late-window 逻辑 | 移除 | 第13-14分钟趋势跟随逻辑 |

## 复杂度跟踪

> 无违规需要记录

| 违规项 | 原因 | 被拒绝的简单替代方案 |
|--------|------|---------------------|
| 无 | - | - |

## 里程碑

1. **M1: 策略模块** - 完成 `strategy/` 目录下的核心逻辑
2. **M2: 集成重构** - 重构 `bot.py`，集成新策略模块
3. **M3: 测试覆盖** - 添加单元测试和集成测试
4. **M4: 文档完善** - 更新 CLAUDE.md 和 README

## 风险与缓解

| 风险 | 影响 | 缓解措施 |
|------|------|----------|
| Polymarket API 变更 | 高 | 保留现有补丁机制，添加 API 版本检查 |
| 流动性不足 | 中 | 添加流动性检查，订单失败重试 |
| 网络中断 | 中 | 现有的断路器机制，优雅重连 |
| 配置错误 | 低 | 配置验证，默认值保护 |
