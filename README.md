# 🤖 Self-Improving AI Trading Agent

An autonomous, 24/7 algorithmic trading system powered by local **Llama 3.1 8B (via Ollama)**, **LangGraph**, **ChromaDB**, **pandas-ta**, **SQLite**, and **Alpaca Paper Trading**. 

The system incorporates a closed-loop **Self-Improvement Reflection Cycle** that analyzes past trade outcomes, extracts actionable lessons into vector memory, and injects those lessons into future trading decisions.

---

## 🌟 Architecture Overview

```
                        [ Market Data (yfinance) ]
                                    │
                                    ▼
                          ┌──────────────────┐
                          │   FETCH_DATA     │ ──► Compute RSI, MACD, EMA, BB, ATR
                          └────────┬─────────┘
                                   │
                                   ▼
[ ChromaDB Vector Memory ] ──► ┌──────────────────┐
(Past Lessons Injected)        │     ANALYZE      │ ──► Local Llama 3.1 (Ollama)
                               └────────┬─────────┘     (Strict JSON Output)
                                        │
                                        ▼
                          ┌──────────────────┐
                          │    RISK_CHECK    │ ──► Rule-Based: Max 10% Size, 2% SL,
                          └────────┬─────────┘     4% TP, Max 3 Open Positions
                                   │
                                   ▼
                          ┌──────────────────┐
                          │     EXECUTE      │ ──► Alpaca Paper API / Paper Sim
                          └────────┬─────────┘     (SL & TP Breaches Checked)
                                   │
                                   ▼
                          ┌──────────────────┐
                          │    LOG_TRADE     │ ──► SQLite Journal (trades.db)
                          └──────────────────┘

                        [ DAILY REFLECTION LOOP (15:30 IST) ]
                                    │
                                    ▼
       Fetch Last 30 Trades ──► LLM Mistake Analysis ──► Save Lessons to ChromaDB
```

---

## 🚀 Key Features

1. **100% Free & Open Source Stack**: Runs on local Llama 3.1 via Ollama (zero API costs), free paper trading on Alpaca, and open-source quantitative libraries.
2. **LangGraph State Machine**: Deterministic, verifiable node workflow: `FETCH_DATA -> ANALYZE -> RISK_CHECK -> EXECUTE -> LOG_TRADE`.
3. **Strict Rule-Based Risk Management**:
   - **Max Position Size**: 10% of portfolio equity per trade.
   - **Stop Loss**: 2% (hard ceiling).
   - **Take Profit**: 4% (fixed target).
   - **Max Open Positions**: 3 concurrent positions maximum.
4. **Self-Improving Reflection Loop**:
   - Runs daily at **15:30 IST** after market close.
   - Analyzes recent wins/losses from SQLite trade journals.
   - Synthesizes 3–5 actionable trading lessons.
   - Embeds lessons in **ChromaDB** and retrieves the top 5 relevant rules on future analysis calls.
5. **24/7 Scheduling**: 6 daily decision cycles (09:30, 10:30, 11:30, 12:30, 13:30, 14:30 IST) with continuous error-recovery.
6. **Built-in Backtesting**: Replays the last 6 months of historical data with `--backtest`.

---

## 📁 Project Structure

```
trading_agent/
├── main.py                  # CLI entry point, scheduler loop, backtesting engine
├── config.py                # Environment loading, constants, risk parameters, logger
├── graph/
│   ├── workflow.py          # LangGraph state machine compiler
│   └── state.py             # AgentState schema
├── nodes/
│   ├── fetch_data.py        # Node 1: Downloads OHLCV data & calculates indicators
│   ├── analyze.py           # Node 2: LLM decision node with ChromaDB lesson retrieval
│   ├── risk_check.py        # Node 3: Rule-based position sizing and risk filters
│   ├── execute.py           # Node 4: Alpaca order placement & SL/TP trigger monitoring
│   └── log_trade.py         # Node 5: SQLite trade journal persistence
├── reflection/
│   ├── reflect.py           # Daily reflection job (extracts lessons from SQLite)
│   └── memory.py            # ChromaDB vector store for lessons
├── data/
│   ├── market_data.py       # yfinance historical & live data fetcher
│   └── indicators.py        # pandas-ta indicator computation (RSI, MACD, EMA, BB, ATR)
├── broker/
│   └── alpaca_client.py     # Alpaca Paper Trading API client + local fallback simulator
├── storage/
│   ├── database.py          # SQLite database connection & CRUD operations
│   └── models.py            # Dataclasses & Pydantic models
├── requirements.txt
├── .env.example
└── README.md
```

---

## 🛠️ Installation & Setup

### Step 1: Clone or Navigate to Project
```bash
cd "self imrpoving trading agent"
```

### Step 2: Create and Activate Virtual Environment
```bash
# Windows
python -m venv venv
.\venv\Scripts\activate

# Linux / macOS
python3 -m venv venv
source venv/bin/activate
```

### Step 3: Install Dependencies
```bash
pip install -r requirements.txt
```

### Step 4: Setup Ollama and Llama 3.1
1. Download and install Ollama from [ollama.com](https://ollama.com).
2. Pull the Llama 3.1 model:
```bash
ollama pull llama3.1
```
3. Make sure the Ollama server is running (default port `11434`).

### Step 5: Configure Environment Variables
Copy `.env.example` to `.env`:
```bash
copy .env.example .env   # Windows
cp .env.example .env     # Linux / macOS
```

Open `.env` and configure your settings:
```ini
OLLAMA_BASE_URL=http://localhost:11434
OLLAMA_MODEL=llama3.1

# Alpaca Paper Trading API Keys (Free at https://alpaca.markets)
ALPACA_API_KEY=your_alpaca_paper_api_key_here
ALPACA_SECRET_KEY=your_alpaca_paper_secret_key_here
ALPACA_BASE_URL=https://paper-api.alpaca.markets

# Target symbols
TRADING_TICKERS=AAPL,MSFT,NVDA,GOOGL,AMZN,TSLA
```
*(Note: If Alpaca keys are omitted, the agent automatically falls back to an integrated Local Paper Simulator with $100,000 virtual balance).*

---

## 💻 Usage & CLI Commands

### 1. Run a Single Test Trading Cycle (`--once`)
Executes an immediate single end-to-end cycle across all configured tickers, prints the decision table, and logs records to SQLite:
```bash
python main.py --once
```

### 2. Run 6-Month Historical Backtesting (`--backtest`)
Replays the past 6 months of historical market data through the technical indicators and quantitative risk model:
```bash
python main.py --backtest
```
Outputs:
- Initial & Final Capital
- Total Return (%)
- Total / Winning / Losing Trades
- Win Rate (%)
- Maximum Drawdown (%)

### 3. Run On-Demand Reflection Cycle (`--reflect`)
Analyzes recorded trades in the SQLite journal, generates 3–5 lessons with Llama 3.1, and saves them into ChromaDB:
```bash
python main.py --reflect
```

### 4. Start 24/7 Autonomous Agent
Runs the perpetual scheduler loop at the 6 fixed intervals (09:30, 10:30, 11:30, 12:30, 13:30, 14:30 IST) and triggers reflection at 15:30 IST:
```bash
python main.py
```

---

## 🛡️ Risk Management Rules

| Rule | Parameter | Description |
|---|---|---|
| **Max Allocation** | `10%` | Maximum capital allocated per trade |
| **Stop Loss** | `2%` | Automatic exit if price drops 2% from entry |
| **Take Profit** | `4%` | Automatic exit if price rises 4% from entry |
| **Max Concurrent Positions** | `3` | Caps risk exposure across the portfolio |
| **Confidence Threshold** | `0.60` | Rejects any LLM buy signal below 60% confidence |

---

## 📝 License
MIT Open Source License.
