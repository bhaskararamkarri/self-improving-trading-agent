# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Commands

### Execution & Agent Workflows
- **Single Trading Cycle**: `python main.py --once` (Runs one full cycle across configured tickers and outputs decision table)
- **Live Paper Mode**: `python main.py --mode paper` (Launches FastAPI webhook server on port 8000 and the continuous Exit Monitor)
- **24/7 Automated Scheduler**: `python main.py` (Runs scheduled cycles at 09:30, 10:30, 11:30, 12:30, 13:30, 14:30 IST and reflection at 15:30 IST)
- **On-Demand Reflection**: `python main.py --reflect` (Analyzes recent trade journal entries in SQLite and persists lessons to ChromaDB)
- **6-Month Backtest & Walk-Forward Suite**: `python main.py --backtest` (Runs half-split baseline vs. self-improved backtest and 3-fold walk-forward validation)

### Testing & Verification Scripts
- **Webhook & Signal Ingestion Tests**: `python test_webhook.py` (Tests FastAPI endpoints, authentication, price sanity, and risk limits)
- **Exit Monitor & SL/TP Tests**: `python test_exit_monitor.py` (Verifies ATR stops, take-profit triggers, and trailing stop logic)
- **Crash Safety Tests**: `python test_crash_safety.py` (Validates network failure tolerance during price monitoring)
- **Position Sizing Math Tests**: `python test_sizing.py`
- **ATR Calculation Tests**: `python test_atr.py`
- **Mock Risk Verification**: `python mock_risk_test.py`

### Environment & Dependencies
- **Install Dependencies**: `pip install -r requirements.txt`
- **Environment Setup**: Copy `.env.example` to `.env` and configure credentials (`OLLAMA_BASE_URL`, `ALPACA_API_KEY`, etc.)

---

## High-Level Architecture

The system is a self-improving algorithmic trading agent combining a LangGraph state machine, local LLM reasoning (Llama 3.1 via Ollama with cloud API fallbacks), ChromaDB vector memory, and rule-based risk management.

```
                    [ Market Data (yfinance / Alpha Vantage) ]
                                        │
                                        ▼
                              ┌──────────────────┐
                              │    FETCH_DATA    │ ──► Compute RSI, MACD, EMA, BB, ATR
                              └────────┬─────────┘
                                       │
                                       ▼
    [ ChromaDB Vector Memory ] ──► ┌──────────────────┐
    (Past Lessons Injected)        │     ANALYZE      │ ──► Local Llama 3.1 (Ollama) / Cloud LLM
                                   └────────┬─────────┘     (Outputs structured JSON action)
                                            │
                                            ▼
                              ┌──────────────────┐
                              │    RISK_CHECK    │ ──► ATR position sizing, 1% risk budget,
                              └────────┬─────────┘     25% allocation cap, max open positions
                                       │
                                       ▼
                              ┌──────────────────┐
                              │     EXECUTE      │ ──► Alpaca Paper API / Paper Sim
                              └────────┬─────────┘
                                       │
                                       ▼
                              ┌──────────────────┐
                              │    LOG_TRADE     │ ──► SQLite Journal (trading_agent.db)
                              └──────────────────┘

                            [ REFLECTION CYCLE ]
                                       │
                                       ▼
           SQLite Closed Trades ──► LLM Reflection ──► ChromaDB Vector Store
```

### Key Modules & Responsibilities

- **`graph/` & `nodes/`**: LangGraph deterministic workflow orchestration.
  - `graph/workflow.py`: Compiles and executes the state graph (`FETCH_DATA -> ANALYZE -> RISK_CHECK -> EXECUTE -> LOG_TRADE`).
  - `graph/state.py`: Defines the typed `AgentState` dictionary passed between nodes.
  - `nodes/fetch_data.py`: Gathers OHLCV market bars and runs indicator computations.
  - `nodes/analyze.py`: Queries ChromaDB for top relevant past lessons, formats prompt with indicators & lessons, and requests structured JSON decision from the LLM.
  - `nodes/risk_check.py`: Applies strict quantitative risk filters (ATR-based stops, max positions, risk-based sizing).
  - `nodes/execute.py`: Dispatches orders to Alpaca Paper Trading or internal paper simulator.
  - `nodes/log_trade.py`: Persists trade state transitions and execution details into SQLite.

- **`reflection/`**: Closed-loop continuous learning.
  - `reflection/reflect.py`: `TradeReflector` audits past winning and losing trades, extracts actionable heuristic/LLM rules, and validates them against statistical trade evidence before saving.
  - `reflection/memory.py`: `LessonMemory` manages ChromaDB vector collections (`trading_lessons`) for semantic retrieval during analysis.

- **`signals/` & `server/`**: External signal handling & technical confluence.
  - `signals/confluence.py`: Multi-indicator confluence scoring (EMA alignment, RSI cross, MACD histogram, volume expansion).
  - `signals/external_validator.py`: Sanity checks external webhook signals against price tolerances, market hours, and duplicate exposure.
  - `server/webhook.py`: FastAPI server receiving TradingView alerts with `X-Webhook-Secret` authentication.

- **`engine/` & `broker/`**: Execution & live position tracking.
  - `engine/exit_monitor.py`: Continuous thread monitoring open paper positions against dynamic ATR stop losses and take profits.
  - `broker/alpaca_client.py`: Alpaca SDK wrapper with fallback to local paper trading simulator.
  - `broker/position_monitor.py`: Periodic background monitor for Alpaca account positions.

- **`data/` & `storage/`**: Market data and persistence layers.
  - `data/market_data.py`: Historical & real-time price fetching via `yfinance`.
  - `data/indicators.py`: Calculation of technical indicators (RSI-14, MACD, EMA 21/50/200, Bollinger Bands, ATR-14).
  - `storage/database.py`: SQLite database layer (`trading_agent.db`) handling trade records, performance statistics, and daily summaries.
  - `storage/models.py`: Pydantic models and dataclasses (`TradeRecord`, `TradeStatus`, `DecisionModel`).

- **`config.py`**: Centralized configuration, environment variable parsing, API secret masking, risk parameters (SL/TP ATR multipliers, risk per trade, max drawdown), and rotating file logger setup.
