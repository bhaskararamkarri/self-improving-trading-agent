# Secure Environment & Configuration Setup Guide

Follow this guide to securely configure your API credentials and run the **Self-Improving AI Trading Agent**.

---

## 1. Quick Setup (Copy Environment Template)

In the root directory of the project, copy `.env.example` to create your local `.env` file:

### On Windows PowerShell:
```powershell
Copy-Item .env.example .env
```

### On macOS / Linux / Bash:
```bash
cp .env.example .env
```

---

## 2. Filling in Your API Keys (Manual & Secure)

Open the `.env` file in your text editor (e.g. VS Code, Notepad, Vim) and replace the placeholder values with your credentials. **Never commit `.env` to Git or share it publicly.**

### Overview of API Keys:

| Environment Variable | Description | Where to Get |
| :--- | :--- | :--- |
| `OPENAI_API_KEY` | OpenAI API key for GPT-4o / LLM reasoning | [platform.openai.com/api-keys](https://platform.openai.com/api-keys) |
| `ANTHROPIC_API_KEY` | Anthropic Claude API key | [console.anthropic.com/settings/keys](https://console.anthropic.com/settings/keys) |
| `ALPHA_VANTAGE_API_KEY` | Real-time & intraday technical indicator API | [alphavantage.co/support/#api-key](https://www.alphavantage.co/support/#api-key) (Free) |
| `TRADINGVIEW_WEBHOOK_SECRET` | Secret token to authenticate incoming TradingView alerts | Set your own secret string in TradingView Alert Webhook settings |
| `ALPACA_API_KEY` | Alpaca Paper Trading API Key | [alpaca.markets](https://alpaca.markets) (Free Paper Account) |
| `ALPACA_SECRET_KEY` | Alpaca Paper Trading Secret Key | Generated in Alpaca Paper Trading dashboard |
| `OLLAMA_BASE_URL` | Local Ollama endpoint (Default: `http://localhost:11434`) | Install local models via `ollama run llama3.1` |
| `OLLAMA_MODEL` | Local LLM model tag (e.g. `llama3.1`, `llama3.2:1b`) | Configured in Ollama |

---

## 3. Git Secrets Protection

The project `.gitignore` is pre-configured to automatically block all sensitive files:
- `.env`, `.env.local`, `.env.*.local`
- `*.pem`, `*.key`, `secrets.json`, `config/secrets/`
- SQLite databases (`*.db`) and log files (`*.log`)

---

## 4. Running the Trading Agent

### A. Run 6-Month Backtest & Walk-Forward Validation
```bash
python main.py --backtest
```
Runs the full 6-month historical simulation, executes reflection cycles, and generates out-of-sample walk-forward validation tables.

### B. Run a Single Immediate Live/Paper Trading Cycle
```bash
python main.py --once
```

### C. Trigger an On-Demand Reflection Cycle
```bash
python main.py --reflect
```

### D. Start 24/7 Automated Scheduler Mode
```bash
python main.py
```

---

## 5. Security Best Practices
- **Zero-Echo Policy**: The codebase never logs or displays raw API keys. All keys are masked (e.g. `sk-...1234`).
- **Startup Validation**: `config.py` validates all required parameters at startup.
- **Local Fallback**: If cloud LLM keys are absent, the engine falls back to local Ollama or rule-based deterministic execution.
