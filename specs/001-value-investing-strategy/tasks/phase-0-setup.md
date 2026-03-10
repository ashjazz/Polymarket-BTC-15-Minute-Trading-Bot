# Phase 0: 项目设置与准备

**阶段目标**: 创建必要的目录结构和配置文件，为后续开发做好准备

**前置依赖**: 无

**预计耗时**: 5-10 分钟

---

## 任务清单

### T001 [P] 创建 strategy 模块目录结构
- [ ] T001 [P] 创建 `strategy/__init__.py` 文件，定义模块初始化

**文件**: `strategy/__init__.py`

**内容**:
```python
"""
价值投资策略模块

包含:
- StrategyConfig: 策略配置
- Position: 持仓状态
- MarketState: 市场状态
- EntryLogic: 入场逻辑
- ExitLogic: 出场逻辑
"""

from strategy.config import StrategyConfig
from strategy.position import Position, PositionStatus, PositionDirection
from strategy.market_state import MarketState, TokenPrice
from strategy.entry_logic import check_entry, EntrySignal
from strategy.exit_logic import check_exit, ExitSignal

__all__ = [
    "StrategyConfig",
    "Position",
    "PositionStatus",
    "PositionDirection",
    "MarketState",
    "TokenPrice",
    "check_entry",
    "EntrySignal",
    "check_exit",
    "ExitSignal",
]
```

---

### T002 [P] 创建 tests 目录结构
- [ ] T002 [P] 创建 `tests/__init__.py` 文件（空文件即可）

**文件**: `tests/__init__.py`

---

### T003 [P] 更新 .env.example 添加策略参数
- [ ] T003 [P] 更新 `.env.example` 文件，添加所有策略配置参数

**文件**: `.env.example`

**新增内容**:
```bash
# ─────────────────────────────────────────────
# VALUE INVESTING STRATEGY PARAMETERS
# ─────────────────────────────────────────────

# Entry Conditions
ENTRY_PRICE_LOW=0.28          # 入场区间下限
ENTRY_PRICE_HIGH=0.32         # 入场区间上限
POSITION_SIZE_USD=2.0         # 每笔交易金额（USDC）
BUY_WINDOW_MINUTES=8          # 买入窗口（分钟）

# Take-Profit Targets (Tiered)
TAKE_PROFIT_1_MINUTES=2       # 第一检查点时间（分钟）
TAKE_PROFIT_1_PRICE=0.40      # 第一目标价
TAKE_PROFIT_2_MINUTES=4       # 第二检查点时间（分钟）
TAKE_PROFIT_2_PRICE=0.48      # 第二目标价
TAKE_PROFIT_3_MINUTES=6       # 第三检查点时间（分钟）
TAKE_PROFIT_3_PRICE=0.55      # 第三目标价

# Stop Loss
STOP_LOSS_PRICE=0.20          # 止损价格
```

---

### T004 验证目录结构
- [ ] T004 确认目录结构已正确创建

**验证命令**:
```bash
ls -la strategy/
ls -la tests/
cat .env.example | grep -A 20 "VALUE INVESTING"
```

---

## 阶段验收标准

- [ ] `strategy/__init__.py` 存在
- [ ] `tests/__init__.py` 存在
- [ ] `.env.example` 包含所有策略参数
- [ ] 目录结构与 plan.md 一致

---

## 完成后

继续执行 **Phase 1: 基础设施层** → `phase-1-foundation.md`
