"""Alpaca paper trading broker interface with local simulation fallback."""

from __future__ import annotations

import json
from typing import Dict, Any, List, Optional, Tuple
import requests

try:
    import pandas as pd
except ImportError:
    from data.dataframe_compat import PandasShim as pd

from config import (
    ALPACA_API_KEY,
    ALPACA_SECRET_KEY,
    ALPACA_BASE_URL,
    INITIAL_PAPER_CASH,
    LIVE_TRADING,
    DRY_RUN,
    ALLOW_EXTENDED_HOURS,
    logger,
)
from storage.models import TradeAction


def is_us_market_open(
    current_time: Optional[pd.Timestamp] = None,
    allow_extended: Optional[bool] = None,
) -> Tuple[bool, str]:
    """Checks if US equity market is currently open.
    Regular US Equity hours: 9:30 AM - 4:00 PM ET, Monday through Friday.
    Uses pandas Timestamp with 'America/New_York' timezone.
    Returns:
        (is_open: bool, message: str)
    """
    if allow_extended is None:
        try:
            allow_extended = ALLOW_EXTENDED_HOURS
        except Exception:
            allow_extended = False

    if current_time is None:
        now_et = pd.Timestamp.now(tz="America/New_York")
    else:
        if isinstance(current_time, str):
            current_time = pd.Timestamp(current_time)
        if current_time.tz is None:
            now_et = current_time.tz_localize("America/New_York")
        else:
            now_et = current_time.tz_convert("America/New_York")

    # 1. Weekday check (Mon=0, Tue=1, Wed=2, Thu=3, Fri=4, Sat=5, Sun=6)
    day_name = now_et.strftime("%A")
    if now_et.weekday() >= 5:
        return False, f"[MARKET] Closed — skipping execution (no orders sent) (Weekend: {day_name})"

    # 2. Simple US market holidays check (Fixed/Standard major market holidays)
    m, d = now_et.month, now_et.day
    # New Year's Day (Jan 1), Juneteenth (Jun 19), Independence Day (Jul 4), Christmas (Dec 25)
    if (m == 1 and d == 1) or (m == 6 and d == 19) or (m == 7 and d == 4) or (m == 12 and d == 25):
        return False, f"[MARKET] Closed — skipping execution (no orders sent) (Holiday: {m}/{d})"

    t = now_et.time()
    reg_open = pd.Timestamp("09:30").time()
    reg_close = pd.Timestamp("16:00").time()

    if allow_extended:
        ext_open = pd.Timestamp("04:00").time()
        ext_close = pd.Timestamp("20:00").time()
        if ext_open <= t < ext_close:
            return True, f"[MARKET] Open (Extended Hours: {t.strftime('%H:%M')} ET)"
        return False, f"[MARKET] Closed — skipping execution (no orders sent) (Outside extended hours: {t.strftime('%H:%M')} ET)"

    if reg_open <= t < reg_close:
        return True, f"[MARKET] Open (Regular Hours: {t.strftime('%H:%M')} ET)"
    else:
        return False, f"[MARKET] Closed — skipping execution (no orders sent) (Outside regular hours: {t.strftime('%H:%M')} ET, regular: 09:30-16:00 ET)"


class AlpacaBrokerClient:
    """Client for executing orders on Alpaca Paper Trading API or Local Paper Simulator."""

    def __init__(
        self,
        api_key: str = ALPACA_API_KEY,
        secret_key: str = ALPACA_SECRET_KEY,
        base_url: str = ALPACA_BASE_URL,
        simulated_cash: float = INITIAL_PAPER_CASH,
    ):
        self.api_key = api_key.strip() if api_key else ""
        self.secret_key = secret_key.strip() if secret_key else ""
        self.base_url = base_url.rstrip("/")
        # Determine if we should actually hit the Alpaca API (live paper) or fall back to simulator
        self.is_live_paper = bool(
            LIVE_TRADING and not DRY_RUN and self.api_key and self.secret_key and not self.api_key.startswith("your_")
        )

        # Local simulator state (used when Alpaca API keys are not provided)
        self.simulated_cash = simulated_cash
        self.simulated_positions: Dict[str, Dict[str, Any]] = {}
        self.peak_portfolio_value = simulated_cash

        if self.is_live_paper:
            logger.info(f"Initialized Alpaca Live Paper Trading Client connected to {self.base_url}")
        else:
            logger.info(f"No active Alpaca keys detected. Initialized Local Paper Simulator (${self.simulated_cash:,.2f} virtual cash).")

    def _get_headers(self) -> Dict[str, str]:
        return {
            "APCA-API-KEY-ID": self.api_key,
            "APCA-API-SECRET-KEY": self.secret_key,
            "Content-Type": "application/json",
        }

    def get_account(self) -> Dict[str, float]:
        """Returns account equity, cash, and buying power."""
        if self.is_live_paper:
            try:
                url = f"{self.base_url}/v2/account"
                resp = requests.get(url, headers=self._get_headers(), timeout=10)
                if resp.status_code == 200:
                    data = resp.json()
                    equity = float(data.get("equity", 0.0))
                    cash = float(data.get("cash", 0.0))
                    buying_power = float(data.get("buying_power", cash))
                    last_equity = float(data.get("last_equity", equity))
                    return {
                        "equity": equity,
                        "cash": cash,
                        "portfolio_value": equity,
                        "buying_power": buying_power,
                        "last_equity": last_equity,
                        "peak_equity": max(equity, last_equity),
                    }
                else:
                    logger.error(f"Alpaca get_account failed: {resp.status_code} {resp.text}")
            except Exception as e:
                logger.error(f"Error calling Alpaca get_account: {e}")

        # Fallback to local simulator
        portfolio_val = self.simulated_cash
        for ticker, pos in self.simulated_positions.items():
            portfolio_val += pos["qty"] * pos.get("current_price", pos["entry_price"])

        if portfolio_val > self.peak_portfolio_value:
            self.peak_portfolio_value = portfolio_val

        return {
            "equity": portfolio_val,
            "cash": self.simulated_cash,
            "portfolio_value": portfolio_val,
            "buying_power": self.simulated_cash,
            "last_equity": self.peak_portfolio_value,
            "peak_equity": self.peak_portfolio_value,
        }

    def get_positions(self) -> List[Dict[str, Any]]:
        """Returns list of open positions."""
        if self.is_live_paper:
            try:
                url = f"{self.base_url}/v2/positions"
                resp = requests.get(url, headers=self._get_headers(), timeout=10)
                if resp.status_code == 200:
                    positions = resp.json()
                    return [
                        {
                            "ticker": p.get("symbol"),
                            "qty": float(p.get("qty", 0.0)),
                            "current_price": float(p.get("current_price", 0.0)),
                            "entry_price": float(p.get("avg_entry_price", 0.0)),
                            "market_value": float(p.get("market_value", 0.0)),
                            "unrealized_pl": float(p.get("unrealized_pl", 0.0)),
                            "unrealized_plpc": float(p.get("unrealized_plpc", 0.0)) * 100.0,
                        }
                        for p in positions
                    ]
                else:
                    logger.error(f"Alpaca get_positions failed: {resp.status_code} {resp.text}")
            except Exception as e:
                logger.error(f"Error calling Alpaca get_positions: {e}")

        # Local simulator positions
        return list(self.simulated_positions.values())

    def get_position(self, ticker: str) -> Optional[Dict[str, Any]]:
        """Returns details for a specific open position, or None if not held."""
        positions = self.get_positions()
        for p in positions:
            if p["ticker"] == ticker:
                return p
        return None

    def submit_order(
        self,
        ticker: str,
        qty: float,
        side: str,  # "buy" or "sell"
        order_type: str = "market",
        time_in_force: str = "gtc",
        current_price: float = 0.0,
        stop_loss_price: Optional[float] = None,
        take_profit_price: Optional[float] = None,
        is_backtest: bool = False,
        check_market_hours: bool = True,
    ) -> Dict[str, Any]:
        """Submits an order to Alpaca Paper Trading or local simulator."""
        if not is_backtest and check_market_hours:
            is_open, market_msg = is_us_market_open()
            if not is_open:
                logger.warning(market_msg)
                return {
                    "status": "skipped",
                    "reason": market_msg,
                }

        if ticker.upper().endswith(".NS") or ticker.upper().endswith(".BO"):
            logger.error(f"❌ Indian broker executor not configured — NSE trade skipped: {ticker}")
            return {
                "status": "skipped",
                "reason": f"Indian broker executor not configured — NSE trade skipped: {ticker}",
            }

        logger.info(f"[Alpaca Route] Executing {side.upper()} order for {ticker}")
        side = side.lower()
        qty = round(qty, 4) if qty < 1 else int(qty)

        if qty <= 0:
            logger.warning(f"Order quantity {qty} is <= 0 for {ticker}. Order rejected.")
            return {"status": "rejected", "reason": "Quantity <= 0"}

        if self.is_live_paper:
            try:
                url = f"{self.base_url}/v2/orders"
                payload: Dict[str, Any] = {
                    "symbol": ticker,
                    "qty": str(qty),
                    "side": side,
                    "type": order_type,
                    "time_in_force": time_in_force,
                }

                # Bracket order support for live Alpaca if TP/SL provided
                if side == "buy" and stop_loss_price and take_profit_price:
                    payload["order_class"] = "bracket"
                    payload["take_profit"] = {"limit_price": str(round(take_profit_price, 2))}
                    payload["stop_loss"] = {"stop_price": str(round(stop_loss_price, 2))}

                resp = requests.post(url, headers=self._get_headers(), json=payload, timeout=10)
                if resp.status_code in (200, 201):
                    order_data = resp.json()
                    order_id = order_data.get("id")
                    logger.info(f"Alpaca Order Submitted: {side.upper()} {qty} {ticker} (Order ID: {order_id})")
                    return {
                        "status": "submitted",
                        "order_id": order_id,
                        "ticker": ticker,
                        "qty": qty,
                        "side": side,
                        "raw": order_data,
                    }
                else:
                    logger.error(f"Alpaca submit_order error: {resp.status_code} {resp.text}")
                    return {"status": "error", "message": resp.text}
            except Exception as e:
                logger.error(f"Exception while submitting Alpaca order: {e}")
                return {"status": "error", "message": str(e)}

        # Local Paper Simulator logic
        fill_price = current_price if current_price > 0 else 100.0
        trade_cost = fill_price * qty

        if side == "buy":
            if trade_cost > self.simulated_cash:
                logger.warning(f"Insufficient simulated cash (${self.simulated_cash:,.2f}) for trade cost (${trade_cost:,.2f}).")
                return {"status": "rejected", "reason": "Insufficient virtual buying power"}

            self.simulated_cash -= trade_cost
            self.simulated_positions[ticker] = {
                "ticker": ticker,
                "qty": qty,
                "entry_price": fill_price,
                "current_price": fill_price,
                "market_value": trade_cost,
                "stop_loss": stop_loss_price or (fill_price * 0.98),
                "take_profit": take_profit_price or (fill_price * 1.04),
                "unrealized_pl": 0.0,
                "unrealized_plpc": 0.0,
            }
            logger.info(f"[SIMULATOR] BOUGHT {qty} {ticker} @ ${fill_price:.2f}. Remaining Cash: ${self.simulated_cash:,.2f}")
            return {
                "status": "filled",
                "order_id": f"sim_{ticker}_{int(fill_price)}",
                "ticker": ticker,
                "qty": qty,
                "side": side,
                "fill_price": fill_price,
            }

        elif side == "sell":
            if ticker in self.simulated_positions:
                held_pos = self.simulated_positions.pop(ticker)
                revenue = fill_price * held_pos["qty"]
                self.simulated_cash += revenue
                pnl = (fill_price - held_pos["entry_price"]) * held_pos["qty"]
                pnl_pct = ((fill_price - held_pos["entry_price"]) / held_pos["entry_price"]) * 100.0
                logger.info(f"[SIMULATOR] SOLD {held_pos['qty']} {ticker} @ ${fill_price:.2f}. PnL: {pnl_pct:+.2f}% (${pnl:+.2f}). Cash: ${self.simulated_cash:,.2f}")
                return {
                    "status": "filled",
                    "order_id": f"sim_sell_{ticker}",
                    "ticker": ticker,
                    "qty": held_pos["qty"],
                    "side": side,
                    "fill_price": fill_price,
                    "pnl_amount": pnl,
                    "pnl_percent": pnl_pct,
                }
            else:
                logger.warning(f"[SIMULATOR] Cannot sell {ticker} - not in open simulated positions.")
                return {"status": "rejected", "reason": f"No open position in {ticker}"}

        return {"status": "unknown"}

    def close_position(self, ticker: str, current_price: float = 0.0) -> Dict[str, Any]:
        """Closes an open position."""
        if ticker.upper().endswith(".NS") or ticker.upper().endswith(".BO"):
            logger.error(f"❌ Indian broker executor not configured — NSE trade skipped: {ticker}")
            return {
                "status": "skipped",
                "reason": f"Indian broker executor not configured — NSE trade skipped: {ticker}",
            }
        if self.is_live_paper:
            try:
                url = f"{self.base_url}/v2/positions/{ticker}"
                resp = requests.delete(url, headers=self._get_headers(), timeout=10)
                if resp.status_code in (200, 204):
                    logger.info(f"Closed Alpaca position for {ticker}")
                    return {"status": "closed", "ticker": ticker}
                else:
                    logger.error(f"Failed to close Alpaca position for {ticker}: {resp.status_code} {resp.text}")
            except Exception as e:
                logger.error(f"Error closing Alpaca position: {e}")

        # Local simulator close
        if ticker in self.simulated_positions:
            pos = self.simulated_positions.pop(ticker)
            price = current_price if current_price > 0 else pos.get("current_price", pos["entry_price"])
            self.simulated_cash += price * pos["qty"]
            pnl = (price - pos["entry_price"]) * pos["qty"]
            pnl_pct = ((price - pos["entry_price"]) / pos["entry_price"]) * 100.0
            return {
                "status": "closed",
                "ticker": ticker,
                "exit_price": price,
                "pnl_amount": pnl,
                "pnl_percent": pnl_pct,
            }

        return {"status": "not_found", "ticker": ticker}
