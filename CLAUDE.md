# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

A production-grade algorithmic trading bot for **Polymarket's 15-minute BTC price prediction markets**. The bot uses a **Value Investing Strategy with Tiered Take-Profit**:

1. **Entry**: Monitor both UP and DOWN token prices; buy when either drops into the value zone (default 0.28-0.32 USDC)
2. **Exit**: Tiered take-profit based on time elapsed since entry (2min→0.40, 4min→0.48, 6min→0.55)
3. **Protection**: Stop-loss at 0.20 USDC

All parameters are configurable via environment variables.

## Python Environment

This project uses **conda** for Python environment management. Always activate the `poly` environment before any development or execution:

```bash
conda activate poly
```

All commands below assume this environment is active.

## Commands

### Setup
```bash
# Activate conda environment (REQUIRED)
conda activate poly

# Install dependencies
pip install -r requirements.txt

# Start Redis (required for mode switching)
redis-server

# Configure environment
cp .env.example .env
# Edit .env with Polymarket API credentials and strategy parameters
```

### Running the Bot
```bash
# Simulation mode (paper trading - default)
python bot.py

# Test mode (faster intervals for testing)
python bot.py --test-mode

# Live trading (REAL MONEY)
python bot.py --live

# With auto-restart wrapper
python 15m_bot_runner.py --test-mode
python 15m_bot_runner.py --live

# Disable Grafana metrics
python bot.py --no-grafana
```

### View Paper Trades
```bash
python view_paper_trades.py
```

## Trading Strategy

### Value Investing + Tiered Take-Profit

```
┌─────────────────────────────────────────────────────────────────────┐
│                        15-Minute Market Cycle                        │
├─────────────────────────────────────────────────────────────────────┤
│                                                                      │
│  ┌──────────────┐                                                   │
│  │  BUY WINDOW  │  Market Open (T0)                                 │
│  │  0-8 min     │  ├─ Monitor UP & DOWN prices                      │
│  │              │  ├─ If price in 0.28-0.32 → BUY 2 USDC            │
│  │              │  └─ One position per market only                  │
│  └──────────────┘                                                   │
│         │                                                           │
│         ▼                                                           │
│  ┌──────────────────────────────────────────────────────────────┐  │
│  │                 TIERED TAKE-PROFIT                            │  │
│  │                                                               │  │
│  │  T+2min ──► Price ≥ 0.40? ──► YES ──► SELL ALL (+33%)        │  │
│  │              │                    │                           │  │
│  │              NO                   ▼                           │  │
│  │              │              Position Closed                   │  │
│  │              ▼                                                 │  │
│  │  T+4min ──► Price ≥ 0.48? ──► YES ──► SELL ALL (+60%)        │  │
│  │              │                    │                           │  │
│  │              NO                   ▼                           │  │
│  │              ▼              Position Closed                   │  │
│  │  T+6min ──► Price ≥ 0.55? ──► YES ──► SELL ALL (+83%)        │  │
│  │              │                    │                           │  │
│  │              NO                   ▼                           │  │
│  │              ▼              Position Closed                   │  │
│  │         Hold until market end                                  │  │
│  └──────────────────────────────────────────────────────────────┘  │
│                                                                      │
│  ┌──────────────────────────────────────────────────────────────┐  │
│  │  STOP-LOSS: Any time, Price ≤ 0.20 → SELL ALL (-33%)         │  │
│  └──────────────────────────────────────────────────────────────┘  │
│                                                                      │
└─────────────────────────────────────────────────────────────────────┘
```

### Strategy Logic

| Phase | Condition | Action | Expected Return |
|-------|-----------|--------|-----------------|
| **Entry** | UP or DOWN price in 0.28-0.32 | Buy 2 USDC | - |
| **TP1** | T+2min, price ≥ 0.40 | Sell all | +33% |
| **TP2** | T+4min, price ≥ 0.48 | Sell all | +60% |
| **TP3** | T+6min, price ≥ 0.55 | Sell all | +83% |
| **Stop** | Any time, price ≤ 0.20 | Sell all | -33% |

### Key Rules

1. **Dual Monitoring**: Watch both UP (YES) and DOWN (NO) tokens simultaneously
2. **First-to-Trigger**: Buy whichever token hits the entry zone first
3. **One Position Per Market**: No pyramiding within the same 15-minute cycle
4. **Time-Based Checkpoints**: Take-profit checks happen at fixed intervals from entry time
5. **Full Exit**: All exits are full position closes (no partial exits)

## Configuration

All strategy parameters are configurable via `.env` file:

```bash
# Polymarket API Credentials
POLYMARKET_PK=your_private_key
POLYMARKET_API_KEY=your_api_key
POLYMARKET_API_SECRET=your_api_secret
POLYMARKET_PASSPHRASE=your_passphrase

# Redis (for mode switching)
REDIS_HOST=localhost
REDIS_PORT=6379
REDIS_DB=2

# ─────────────────────────────────────────────
# STRATEGY PARAMETERS (All Configurable)
# ─────────────────────────────────────────────

# Entry Conditions
ENTRY_PRICE_LOW=0.28          # Buy when price ≤ this
ENTRY_PRICE_HIGH=0.32         # Buy when price ≥ this (defines range)
POSITION_SIZE_USD=2.0         # Amount to buy per trade (USDC)
BUY_WINDOW_MINUTES=8          # Minutes after market open to allow buys

# Take-Profit Targets (Tiered)
TAKE_PROFIT_1_MINUTES=2       # First checkpoint: 2 minutes after entry
TAKE_PROFIT_1_PRICE=0.40      # First target price (+33%)

TAKE_PROFIT_2_MINUTES=4       # Second checkpoint: 4 minutes after entry
TAKE_PROFIT_2_PRICE=0.48      # Second target price (+60%)

TAKE_PROFIT_3_MINUTES=6       # Third checkpoint: 6 minutes after entry
TAKE_PROFIT_3_PRICE=0.55      # Third target price (+83%)

# Stop Loss
STOP_LOSS_PRICE=0.20          # Exit if price drops to this (-33%)
```

## Architecture

```
bot.py                          # Main entry point, strategy implementation
├── patch_gamma_markets.py      # Polymarket API patches (apply before imports)
├── patch_market_orders.py      # Market order handling patches
│
├── core/
│   └── strategy_brain/         # Strategy logic (to be refactored)
│
├── execution/
│   └── risk_engine.py          # Position management, risk limits
│
├── monitoring/
│   └── performance_tracker.py  # Trade logging, P&L tracking
│
├── data_sources/               # External data providers
│   ├── coinbase/               # BTC spot price
│   └── news_social/            # Fear & Greed Index
│
└── specs/                      # Strategy specifications
    └── 001-value-investing-strategy/
        └── spec.md             # Full strategy specification
```

## Important Files

| File | Purpose |
|------|---------|
| `bot.py` | Main strategy implementation (to be refactored for new strategy) |
| `specs/001-value-investing-strategy/spec.md` | Complete strategy specification |
| `patch_gamma_markets.py` | Polymarket API patches (must apply before imports) |
| `patch_market_orders.py` | Market order handling patches |
| `execution/risk_engine.py` | Position sizing, risk limits |
| `monitoring/performance_tracker.py` | Trade logging, equity curve |

## Key Constraints

1. **Fixed Position Size**: Each trade is exactly `POSITION_SIZE_USD` (default 2 USDC)
2. **15-minute Market Alignment**: Market slugs are Unix timestamps aligned to 15-min boundaries
3. **YES/NO Token Pairing**: Each market has two tokens; YES=UP, NO=DOWN
4. **IOC Orders Only**: Immediate-or-cancel for market orders
5. **Polymarket CLOB**: Uses py_clob_client for order book data
6. **One Position Per Market**: No multiple positions in the same 15-minute cycle

## Position State Management

Each active position tracks:
- `market_slug`: Which 15-minute market
- `direction`: UP (YES) or DOWN (NO)
- `entry_price`: Price at which position was opened
- `entry_time`: Timestamp of entry (T0, used for checkpoint calculations)
- `size_usd`: Position size in USDC
- `status`: OPEN, CLOSED_TP1, CLOSED_TP2, CLOSED_TP3, CLOSED_SL, CLOSED_EOD

## Common Issues

- **"No liquidity" rejection**: Market orderbook is empty; bot will retry
- **Market not found**: Ensure slug filters match current 15-min intervals
- **Redis connection failed**: Bot falls back to static mode from .env
- **Gamma markets patch required**: Must apply before importing NautilusTrader
- **Position not closed**: Check if take-profit targets were met at checkpoint times

## Development Notes

### Current Status
The codebase is being refactored from a "late-window trend following" strategy to the new "value investing + tiered take-profit" strategy. See `specs/001-value-investing-strategy/spec.md` for the complete specification.

### Refactoring Priorities
1. Implement dual price monitoring (UP and DOWN simultaneously)
2. Implement value zone entry logic with configurable parameters
3. Implement tiered take-profit with time-based checkpoints
4. Implement continuous stop-loss monitoring
5. Update position state tracking for new exit types

### Testing
- Use `--test-mode` for faster iteration during development
- Simulation mode (`python bot.py`) for paper trading validation
- Always test configuration changes in simulation before live trading
