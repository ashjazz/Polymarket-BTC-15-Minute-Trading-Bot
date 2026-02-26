# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

A production-grade algorithmic trading bot for **Polymarket's 15-minute BTC price prediction markets**. The bot predicts whether BTC will go UP or DOWN in 15-minute intervals using a multi-signal fusion system with NautilusTrader as the execution framework.

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
# Edit .env with Polymarket API credentials
```

### Running the Bot
```bash
# Simulation mode (paper trading - default)
python bot.py

# Test mode (trades every minute for faster testing)
python bot.py --test-mode

# Live trading (REAL MONEY)
python bot.py --live

# With auto-restart wrapper
python 15m_bot_runner.py --test-mode
python 15m_bot_runner.py --live

# Disable Grafana metrics
python bot.py --no-grafana
```

### Testing Individual Phases
```bash
python core/ingestion/test_ingestion.py
python core/nautilus_core/test_nautilus.py
python core/strategy_brain/test_strategy.py
python scripts/test_data_sources.py
python scripts/test_execution.py
```

### View Paper Trades
```bash
python view_paper_trades.py
```

## Architecture: 7-Phase System

```
Phase 1: Data Sources      → External market data (Coinbase, Binance, Fear & Greed)
Phase 2: Ingestion         → Unified adapter, WebSocket manager, validators
Phase 3: Nautilus Core     → Trading framework, data engine, event dispatcher
Phase 4: Strategy Brain    → Signal processors + Fusion engine
Phase 5: Execution         → Order placement, risk management
Phase 6: Monitoring        → Performance tracking, Grafana metrics
Phase 7: Learning          → Weight optimization based on performance
```

### Key Components

**Entry Point:** `bot.py` - Main `IntegratedBTCStrategy` class extending NautilusTrader's `Strategy`

**Signal Processors (Phase 4):**
- `SpikeDetectionProcessor` - Detects price spikes vs historical average
- `SentimentProcessor` - Uses Fear & Greed Index extremes
- `PriceDivergenceProcessor` - Compares Polymarket price to spot BTC
- `OrderBookImbalanceProcessor` - Analyzes CLOB order book depth
- `TickVelocityProcessor` - Measures price change velocity
- `DeribitPCRProcessor` - Institutional sentiment from options PCR

**Signal Fusion (Phase 4):** `core/strategy_brain/fusion_engine/signal_fusion.py`
- Weighted voting system combining all signals
- Default weights: OrderBookImbalance(30%), TickVelocity(25%), PriceDivergence(18%), SpikeDetection(12%), DeribitPCR(10%), Sentiment(5%)

**Risk Management (Phase 5):** `execution/risk_engine.py`
- Max $1 per trade (hard cap)
- 30% stop loss, 20% take profit
- Max 5 concurrent positions
- 15% max drawdown circuit breaker

## Trading Logic

The bot trades in a **late-window strategy** (minutes 13-14 of each 15-min market):
- Uses a **trend filter** at the late window instead of signal-based direction
- `price > 0.60` → Buy YES (UP)
- `price < 0.40` → Buy NO (DOWN)
- `0.40-0.60` → Skip (coin flip territory)

Rationale: At minute 13, the Polymarket price reflects the nearly-decided outcome. This is not prediction but reading the trend.

## Configuration

Environment variables (`.env`):
```
POLYMARKET_PK=your_private_key
POLYMARKET_API_KEY=your_api_key
POLYMARKET_API_SECRET=your_api_secret
POLYMARKET_PASSPHRASE=your_passphrase
REDIS_HOST=localhost
REDIS_PORT=6379
REDIS_DB=2
MAX_POSITION_SIZE=1.0
STOP_LOSS_PCT=0.30
TAKE_PROFIT_PCT=0.20
```

## Important Files

| File | Purpose |
|------|---------|
| `bot.py` | Main strategy implementation |
| `patch_gamma_markets.py` | Polymarket API patches (must apply before imports) |
| `patch_market_orders.py` | Market order handling patches |
| `execution/risk_engine.py` | Position sizing, risk limits |
| `core/strategy_brain/fusion_engine/signal_fusion.py` | Signal combination logic |
| `feedback/learning_engine.py` | Weight optimization from trade history |
| `monitoring/performance_tracker.py` | Trade logging, Sharpe ratio, equity curve |

## Singleton Pattern

Most components use singletons accessed via `get_X()` functions:
- `get_fusion_engine()` - Signal fusion
- `get_risk_engine()` - Risk management
- `get_performance_tracker()` - Trade tracking
- `get_learning_engine()` - Weight optimization

## Key Constraints

1. **Always $1 per trade** - Position size is fixed, not variable
2. **15-minute market alignment** - Market slugs are Unix timestamps aligned to 15-min boundaries
3. **YES/NO token pairing** - Each market has two tokens; YES=UP, NO=DOWN
4. **IOC orders only** - Immediate-or-cancel for market orders
5. **Polymarket CLOB** - Uses py_clob_client for order book data

## Common Issues

- **"No liquidity" rejection**: Market orderbook is empty; bot will retry next tick
- **Market not found**: Ensure slug filters match current 15-min intervals
- **Redis connection failed**: Bot falls back to static mode from .env
- **Gamma markets patch required**: Must apply before importing NautilusTrader
