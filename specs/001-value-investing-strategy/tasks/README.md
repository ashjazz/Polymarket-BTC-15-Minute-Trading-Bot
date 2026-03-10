# 任务清单概览

**功能**: 价值投资策略 + 分批止盈系统
**分支**: `001-value-investing-strategy`
**创建日期**: 2026-03-10

## 任务组织结构

本项目的任务按照 **Phase（阶段）** 组织，每个 Phase 对应一个独立的可交付成果。

```
specs/001-value-investing-strategy/tasks/
├── README.md           # 本文件（概览）
├── phase-0-setup.md    # Phase 0: 项目设置与准备
├── phase-1-foundation.md    # Phase 1: 基础设施层（US4 - 配置系统）
├── phase-2-data-model.md    # Phase 2: 核心数据模型（US5 - 状态管理）
├── phase-3-entry.md         # Phase 3: US1 - 双向监控与价值入场
├── phase-4-exit-tp.md       # Phase 4: US2 - 时间阶梯止盈
├── phase-5-stop-loss.md     # Phase 5: US3 - 止损保护
└── phase-6-integration.md   # Phase 6: 集成、清理与测试
```

## Phase 依赖关系

```
Phase 0 (设置)
    │
    ▼
Phase 1 (配置系统) ─────────────────────────────┐
    │                                           │
    ▼                                           │
Phase 2 (数据模型)                               │
    │                                           │
    ├──────────────┬──────────────┐             │
    ▼              ▼              ▼             │
Phase 3      Phase 4      Phase 5               │
(入场)        (止盈)        (止损)               │
    │              │              │             │
    └──────────────┴──────────────┘             │
                   │                            │
                   ▼                            │
            Phase 6 (集成) ◄────────────────────┘
```

## 用户故事与 Phase 映射

| 用户故事 | 优先级 | 对应 Phase | 核心交付物 |
|---------|--------|-----------|-----------|
| US1: 双向监控与价值入场 | P1 | Phase 3 | `strategy/entry_logic.py` |
| US2: 时间阶梯止盈执行 | P1 | Phase 4 | `strategy/exit_logic.py` (TP部分) |
| US3: 止损保护 | P1 | Phase 5 | `strategy/exit_logic.py` (SL部分) |
| US4: 可配置的策略参数 | P2 | Phase 1 | `strategy/config.py` |
| US5: 持仓跟踪与状态管理 | P2 | Phase 2 | `strategy/position.py` |

## 任务统计

| Phase | 任务数 | 可并行 | 核心文件 |
|-------|--------|--------|----------|
| Phase 0 | 4 | 3 | 目录结构、.env.example |
| Phase 1 | 2 | 1 | strategy/config.py |
| Phase 2 | 4 | 3 | strategy/position.py, market_state.py |
| Phase 3 | 1 | 0 | strategy/entry_logic.py |
| Phase 4 | 1 | 0 | strategy/exit_logic.py |
| Phase 5 | 1 | 0 | tests/test_entry_logic.py |
| Phase 6 | 6 | 2 | bot.py, tests/ |
| **总计** | **19** | **9** | - |

## 任务 ID 索引

| 任务 ID | Phase | 描述 | 文件 |
|---------|-------|------|------|
| T001 | 0 | 创建 strategy 模块目录 | strategy/__init__.py |
| T002 | 0 | 创建 tests 目录 | tests/__init__.py |
| T003 | 0 | 更新 .env.example | .env.example |
| T004 | 0 | 验证目录结构 | - |
| T005 | 1 | 实现 StrategyConfig | strategy/config.py |
| T006 | 1 | 配置模块测试 | tests/test_config.py |
| T007 | 2 | 实现 Position | strategy/position.py |
| T008 | 2 | 实现 MarketState | strategy/market_state.py |
| T009 | 2 | Position 测试 | tests/test_position.py |
| T010 | 2 | MarketState 测试 | tests/test_market_state.py |
| T011 | 3 | 实现入场逻辑 | strategy/entry_logic.py |
| T012 | 4 | 实现出场逻辑 | strategy/exit_logic.py |
| T013 | 5 | 入场逻辑测试 | tests/test_entry_logic.py |
| T014 | 6 | 出场逻辑测试 | tests/test_exit_logic.py |
| T015 | 6 | 集成到 bot.py | bot.py |
| T016 | 6 | 简化 risk_engine | execution/risk_engine.py |
| T017 | 6 | 更新 .env.example | .env.example |
| T018 | 6 | 集成测试 | tests/test_integration.py |
| T019 | 6 | 运行完整测试 | - |

## MVP 范围建议

**最小可行产品（MVP）** = Phase 0 + Phase 1 + Phase 2 + Phase 3

完成后可验证：
- ✅ 双向价格监控
- ✅ 价值区间入场
- ✅ 买入窗口限制
- ✅ 配置参数加载

## 开始执行

请按顺序执行各 Phase 的任务。每个 Phase 文件包含：
- 阶段目标
- 前置依赖
- 任务清单（原子化）
- 验收标准

**建议执行顺序**：
1. 从 `phase-0-setup.md` 开始
2. 依次执行 Phase 1-5
3. 最后执行 `phase-6-integration.md` 完成集成
