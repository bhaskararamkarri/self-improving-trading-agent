"""ANALYZE Node: Queries local Llama 3.1 via Ollama with strict confluence rules and indicator auditing."""

from __future__ import annotations

import json
import re
from typing import Dict, Any, List, Optional
import requests

from config import OLLAMA_BASE_URL, OLLAMA_MODEL, logger
from graph.state import AgentState
from reflection.memory import LessonMemory


def analyze_node(state: AgentState) -> Dict[str, Any]:
    """LangGraph node that evaluates technical indicators, hard regime filters, lesson vetoes, and short setups."""
    snapshots = state.get("market_snapshots", {})
    is_backtest = state.get("is_backtest", False)
    logger.info(f"--- [NODE: ANALYZE] Analyzing {len(snapshots)} market snapshots ---")

    if not snapshots:
        logger.warning("No market snapshots available in state to analyze.")
        return {"raw_decisions": [], "past_lessons": []}

    memory = LessonMemory()
    raw_decisions: List[Dict[str, Any]] = []
    all_past_lessons: List[str] = []

    for ticker, snapshot in snapshots.items():
        ind = snapshot["indicators"]
        price = snapshot["current_price"]
        rsi = ind.get("rsi_14", 50.0)
        ema_9 = ind.get("ema_9", price)
        ema_21 = ind.get("ema_21", price)
        ema_50 = ind.get("ema_50", price)
        ema_50_prev = ind.get("ema_50_prev", ema_50)
        macd_hist = ind.get("macd_hist", 0.0)
        volume_ratio = ind.get("volume_ratio", 1.0)
        is_downtrend = (price < ema_50) and (ema_50 <= ema_50_prev)

        # 1. Retrieve top 3 relevant past lessons from ChromaDB based on current market condition
        query = f"{ticker} RSI {rsi} MACD {ind.get('macd', 0.0)} {snapshot.get('trend_summary', '')}"
        past_lessons_dicts = memory.retrieve_lessons(query=query, n_results=3)
        past_lessons_texts = []
        for l_dict in past_lessons_dicts:
            text = l_dict["text"]
            if text not in all_past_lessons:
                all_past_lessons.append(text)
            past_lessons_texts.append(text)

        # 2. Build disciplined LLM prompt with snapshot + strict rules + retrieved lessons
        prompt = _build_decision_prompt(ticker=ticker, snapshot=snapshot, past_lessons=past_lessons_texts)

        # 3. Call Llama 3.1 via Ollama with retry
        decision_dict = _call_ollama_with_retry(prompt=prompt, ticker=ticker, snapshot=snapshot)

        # 4. HARD REGIME FILTER & LESSON VETO GATING
        action = decision_dict.get("action", "HOLD").upper()
        conf = float(decision_dict.get("confidence", 0.0))

        # Check for Lesson Hard Veto or Soft Penalty
        from config import LESSON_MODE
        lesson_veto_result = _check_lesson_veto(past_lessons_dicts, price, ema_50, rsi, ema_9, ema_21)
        
        if lesson_veto_result and action == "BUY":
            veto_reason, lesson_id = lesson_veto_result
            if LESSON_MODE.lower() == "soft":
                logger.warning(f"  [LESSON] Applied: {lesson_id} -> size 50% (soft). Veto bypassed as penalty.")
                decision_dict["soft_penalty"] = True
                decision_dict["soft_penalty_reason"] = veto_reason
                decision_dict["lesson_id"] = lesson_id
            else:
                logger.warning(f"  [LESSON_VETO] Blocked BUY {ticker} due to learned rule: {veto_reason}")
                decision_dict["action"] = "HOLD"
                decision_dict["reasoning"] = f"[LESSON REJECTED: {veto_reason}] {decision_dict.get('reasoning', '')}"

        # (A) Hard Regime Filter: If price < EMA 50 AND EMA 50 slope is negative, reject all BUYs
        if action == "BUY" and is_downtrend:
            logger.warning(f"  [REGIME_FILTERED] Blocked BUY {ticker}: Price (${price:.2f}) < EMA50 (${ema_50:.2f}) & EMA50 slope negative.")
            # Evaluate SHORT setup alternative in downtrend regime
            short_setup_triggered = _evaluate_short_setup(snapshot, is_backtest=is_backtest)
            if short_setup_triggered and conf >= 0.70:
                decision_dict["action"] = "SHORT"
                decision_dict["confidence"] = round(conf, 2)
                decision_dict["stop_loss"] = round(price * 1.02, 2)  # 2% stop above
                decision_dict["take_profit"] = round(price * 0.96, 2)  # 4% take profit below
                decision_dict["reasoning"] = f"[DOWNTREND SHORT SETUP] Confirmed regime downtrend (Price < EMA50). Breakdown executed."
            else:
                decision_dict["action"] = "REGIME_FILTERED"
                decision_dict["reasoning"] = f"[REGIME_FILTERED] Blocked long entry: Price < EMA50 with negative slope."

        # (C) Confidence Threshold: Min 0.70 during detected downtrend regime, 0.60 otherwise
        min_conf = 0.70 if is_downtrend else 0.60
        if conf < min_conf and decision_dict["action"] in ("BUY", "SHORT"):
            orig = decision_dict["action"]
            decision_dict["action"] = "HOLD"
            decision_dict["reasoning"] = f"[Forced HOLD: Confidence {conf:.2f} < {min_conf:.2f} threshold (was {orig})]"

        # 5. Include indicator metrics in decision object for auditing/debugging
        decision_dict["indicators_used"] = {
            "rsi_14": rsi,
            "current_price": price,
            "ema_50": ema_50,
            "macd_hist": macd_hist,
            "volume_ratio": volume_ratio,
            "is_downtrend": is_downtrend,
        }

        # Print / Log exact indicator values used for decision
        logger.info(
            f"  Decision [{ticker}]: {decision_dict.get('action')} (Conf: {conf:.2f}) | "
            f"Indicators: RSI={rsi:.1f}, Price=${price:.2f}, EMA50=${ema_50:.2f}, "
            f"MACD_Hist={macd_hist:+.2f}, VolRatio={volume_ratio:.1f}x | "
            f"Reasoning: {decision_dict.get('reasoning')[:70]}..."
        )

        raw_decisions.append(decision_dict)

    return {
        "raw_decisions": raw_decisions,
        "past_lessons": all_past_lessons,
    }


def _check_lesson_veto(lessons: List[Dict[str, Any]], price: float, ema_50: float, rsi: float, ema_9: float, ema_21: float) -> Optional[tuple[str, str]]:
    """Evaluates if any retrieved lesson acts as a hard VETO against current conditions."""
    import re
    for l_dict in lessons:
        lesson = l_dict.get("text", "")
        lesson_id = l_dict.get("id", "unknown_lesson")
        meta = l_dict.get("metadata", {})
        
        sample_size = meta.get("min_sample_size", 0)
        loss_rate = meta.get("loss_rate", 0.0)
        
        # Fallback to parsing from text if not in metadata
        if not sample_size:
            match_samples = re.search(r'out of (\d+) trades', lesson)
            if match_samples:
                sample_size = int(match_samples.group(1))
        
        if not loss_rate:
            match_loss = re.search(r'\((\d+)% loss rate\)', lesson)
            if match_loss:
                loss_rate = float(match_loss.group(1)) / 100.0
                
        # "lesson only ACTIVE if >= 5 historical occurrences AND loss rate > 60%. Lekapothe lesson = 'observation'"
        if sample_size < 5 or loss_rate <= 0.60:
            logger.debug(f"Lesson {lesson_id} is OBSERVATION only (size={sample_size}, loss_rate={loss_rate:.2f})")
            continue
            
        l_lower = lesson.lower()
        if "avoid" in l_lower or "restrict" in l_lower:
            if ("price < ema 50" in l_lower or "below 50 ema" in l_lower) and price < ema_50:
                return f"VETO: Avoid buying below EMA 50 (Price ${price:.2f} < EMA50 ${ema_50:.2f})", lesson_id
            if ("rsi > 70" in l_lower or "rsi > 60" in l_lower or "rsi > 58" in l_lower or "above rsi 58" in l_lower) and rsi > 58.0:
                return f"VETO: Avoid buying at overbought levels (RSI={rsi:.1f} > 58)", lesson_id
            if ("ema 9 < ema 21" in l_lower or "ema9 < ema21" in l_lower) and ema_9 < ema_21:
                return f"VETO: Avoid buying when EMA 9 < EMA 21 (bearish alignment)", lesson_id
    return None


def _evaluate_short_setup(snapshot: Dict[str, Any], is_backtest: bool = False) -> bool:
    """Evaluates high-probability SHORT breakdown setup during confirmed downtrends."""
    ind = snapshot.get("indicators", {})
    price = snapshot.get("current_price", 0.0)
    ema_50 = ind.get("ema_50", price)
    ema_9 = ind.get("ema_9", price)
    ema_21 = ind.get("ema_21", price)
    macd_hist = ind.get("macd_hist", 0.0)
    rsi = ind.get("rsi_14", 50.0)
    open_p = float(snapshot.get("open", price))
    close_p = float(snapshot.get("close", price))
    is_red = close_p < open_p

    # Short setup criteria: Price < EMA 50 & EMA 9 < EMA 21 & negative MACD & red confirmation candle
    if (price < ema_50) and (ema_9 <= ema_21) and (macd_hist < 0.0) and is_red and (35.0 <= rsi <= 55.0):
        # Broker support check (always supported in backtesting mode; live requires margin/paper short capability)
        return True
    return False


def _build_decision_prompt(ticker: str, snapshot: Dict[str, Any], past_lessons: List[str]) -> str:
    """Constructs prompt for Llama 3.1 with disciplined instructions and strict confluence rules."""
    ind = snapshot["indicators"]
    price = snapshot["current_price"]
    open_price = float(snapshot.get("open", price))
    close_price = float(snapshot.get("close", price))
    is_green_candle = close_price >= open_price
    rsi = ind.get("rsi_14", 50.0)
    ema_9 = ind.get("ema_9", price)
    ema_21 = ind.get("ema_21", price)
    ema_50 = ind.get("ema_50", price)
    ema_200 = ind.get("ema_200", price)
    bb_upper = ind.get("bb_upper", price * 1.05)
    bb_middle = ind.get("bb_middle", price)
    bb_lower = ind.get("bb_lower", price * 0.95)
    macd_hist = ind.get("macd_hist", 0.0)
    vol_ratio = ind.get("volume_ratio", 1.0)
    lessons_text = "\n".join([f"- {l}" for l in past_lessons]) if past_lessons else "No recorded lessons yet."

    prompt = f"""You are a professional quantitative trading analyst. You enforce strict high-probability technical confluence rules with a 2% stop loss and 4% take profit. When indicators do not clearly align, always choose HOLD. Do not guess. Confidence below 0.60 must always result in HOLD.

### ASSET & INDICATOR SNAPSHOT for {ticker}
- Current Price: ${price:.2f} (Open: ${open_price:.2f}, High: ${snapshot.get('high', price):.2f}, Low: ${snapshot.get('low', price):.2f}, Close: ${close_price:.2f} -> {'GREEN reversal bar' if is_green_candle else 'RED bar'})
- Key Indicator Values:
  * RSI (14): {rsi:.2f} (Target momentum pullback range: 42.0 to 58.0)
  * EMAs: EMA 9=${ema_9:.2f}, EMA 21=${ema_21:.2f}, EMA 50=${ema_50:.2f}, EMA 200=${ema_200:.2f}
  * Trend Regime: {'Price ABOVE EMA 21 & EMA 50 (Strong Bullish)' if (price >= ema_21 and price >= ema_50) else ('Price ABOVE EMA 200 (Long-term Bullish)' if price >= ema_200 else 'Below Key EMAs (Bearish/Neutral)')}
  * Short-term Momentum: {'EMA 9 > EMA 21 (Bullish Alignment)' if ema_9 > ema_21 else 'EMA 9 <= EMA 21 (Bearish/Neutral)'}
  * MACD Histogram: {macd_hist:+.2f} ({'Positive Momentum' if macd_hist > 0 else 'Negative/Turning'})
  * Bollinger Bands: Upper=${bb_upper:.2f}, Middle=${bb_middle:.2f}, Lower=${bb_lower:.2f}
  * Volume Ratio: {vol_ratio:.2f}x 20-period average
- Trend Summary: {snapshot.get('trend_summary', 'N/A')}

### MANDATORY TRADING RULES (Strict Confluence for High Win Rate)
1. BUY Rule: You must ONLY say BUY when ALL of these conditions are met:
   - Condition A (Macro Trend): Current Price is above EMA 21 (Price >= ${ema_21:.2f}) AND above EMA 50 (Price >= ${ema_50:.2f} or ${ema_50:.2f} >= ${ema_200:.2f}).
   - Condition B (Momentum Pullback Zone): RSI (14) is between 42.0 and 58.0 (Healthy expansion zone, not overbought > 60).
   - Condition C (Reversal / Candle Confirmation): Current Bar is green (Close >= Open).
   - Condition D (Momentum): MACD Histogram >= 0.0 (Positive momentum confirmation).
   - Condition E (Clearance): Current Price is below Upper Bollinger Band (Price < ${bb_upper:.2f}).
   If even ONE condition fails, you MUST NOT say BUY.

2. SELL Rule: You must ONLY say SELL when AT LEAST ONE of these conditions is met:
   - Condition A: RSI (14) > 70 (Severely overbought).
   - Condition B: Current Price breaks below EMA 50 WITH high volume surge (Volume Ratio > 1.5x).

3. HOLD Rule: If the strict confluence BUY or SELL conditions are not met, you MUST choose HOLD.

4. Confidence Rule: If confidence is below 0.60, action must be HOLD.

### PAST LESSONS LEARNED (Memory)
{lessons_text}
NOTE: These are observations, not guarantees. If current market conditions differ from the lesson's context, ignore the lesson.

### RESPONSE FORMAT
Respond with STRICT JSON ONLY. No markdown or preamble outside JSON.
Schema:
{{
  "action": "BUY" | "SELL" | "HOLD",
  "ticker": "{ticker}",
  "confidence": 0.85,
  "reasoning": "Explain exact indicator values confirming or invalidating the trade."
}}
"""
    return prompt


def _call_ollama_with_retry(
    prompt: str,
    ticker: str,
    snapshot: Dict[str, Any],
    max_retries: int = 3,
) -> Dict[str, Any]:
    """Calls Ollama with retry logic to ensure valid JSON matching the required schema."""
    url = f"{OLLAMA_BASE_URL.rstrip('/')}/api/generate"

    current_prompt = prompt
    for attempt in range(1, max_retries + 1):
        try:
            payload = {
                "model": OLLAMA_MODEL,
                "prompt": current_prompt,
                "stream": False,
                "format": "json",
                "options": {
                    "temperature": 0.1,  # Low temperature for strict adherence
                    "top_p": 0.9,
                },
            }

            resp = requests.post(url, json=payload, timeout=45)
            if resp.status_code == 200:
                resp_json = resp.json()
                raw_text = resp_json.get("response", "").strip()

                parsed = _parse_and_validate_decision_json(raw_text, ticker, snapshot["current_price"])
                if parsed:
                    return parsed
                else:
                    logger.warning(f"Attempt {attempt}/{max_retries}: Invalid JSON output from Ollama for {ticker}: {raw_text[:120]}")
                    current_prompt = prompt + f"\n\nERROR: Return ONLY a valid JSON object matching the exact schema with action: BUY|SELL|HOLD, ticker: {ticker}, confidence (0-1), and reasoning."
            else:
                logger.error(f"Ollama API returned HTTP {resp.status_code}: {resp.text}")

        except Exception as e:
            logger.error(f"Attempt {attempt}/{max_retries}: Exception calling Ollama: {e}")

    # Fallback to strict rule-based decision if LLM fails
    logger.warning(f"Falling back to rule-based analysis for {ticker} due to LLM unavailability/errors.")
    return _rule_based_fallback_decision(ticker, snapshot)


def _parse_and_validate_decision_json(raw_text: str, ticker: str, current_price: float) -> Optional[Dict[str, Any]]:
    """Extracts, parses, and validates the decision JSON."""
    try:
        match = re.search(r"\{[\s\S]*\}", raw_text)
        if not match:
            return None

        data = json.loads(match.group(0))

        action_str = str(data.get("action", "")).upper().strip()
        if action_str not in ("BUY", "SELL", "HOLD"):
            return None

        conf = float(data.get("confidence", 0.5))
        conf = max(0.0, min(1.0, conf))

        reasoning = str(data.get("reasoning", "Evaluated based on indicator confluence")).strip()

        return {
            "ticker": ticker,
            "action": action_str,
            "confidence": round(conf, 2),
            "reasoning": reasoning,
            "entry_price": current_price,
            "stop_loss": round(current_price * 0.98, 2) if action_str == "BUY" else 0.0,
            "take_profit": round(current_price * 1.04, 2) if action_str == "BUY" else 0.0,
        }
    except Exception:
        return None


def _rule_based_fallback_decision(ticker: str, snapshot: Dict[str, Any]) -> Dict[str, Any]:
    """Strict quantitative indicator fallback decision when LLM is unavailable."""
    ind = snapshot["indicators"]
    price = snapshot["current_price"]
    open_price = float(snapshot.get("open", price))
    close_price = float(snapshot.get("close", price))
    is_green_candle = close_price >= open_price
    rsi = ind.get("rsi_14", 50.0)
    ema_9 = ind.get("ema_9", price)
    ema_21 = ind.get("ema_21", price)
    ema_50 = ind.get("ema_50", price)
    ema_200 = ind.get("ema_200", price)
    bb_upper = ind.get("bb_upper", price * 1.05)
    macd_hist = ind.get("macd_hist", 0.0)
    volume_ratio = ind.get("volume_ratio", 1.0)

    # 1. High-confluence Momentum Pullback BUY
    in_trend = (price >= ema_21) and (price >= ema_50 or ema_50 >= ema_200)
    rsi_pullback = 42.0 <= rsi <= 58.0
    reversal_momentum = is_green_candle and (macd_hist >= 0.0)
    clearance = price < bb_upper

    if in_trend and rsi_pullback and reversal_momentum and clearance:
        action = "BUY"
        conf = 0.85
        reasoning = (
            f"Strict confluence BUY: In trend (Price=${price:.2f} > EMA21=${ema_21:.2f} & EMA50=${ema_50:.2f}), "
            f"RSI momentum ({rsi:.1f}), green candle confirmation, and positive MACD Hist ({macd_hist:+.2f})."
        )
    # 2. Strict SELL
    elif rsi > 70 or (price < ema_50 and volume_ratio > 1.5):
        action = "SELL"
        conf = 0.75
        reasoning = (
            f"Strict SELL signal: RSI({rsi:.1f}) > 70 or Price (${price:.2f}) broke below EMA50 (${ema_50:.2f}) "
            f"with volume surge ({volume_ratio:.1f}x)."
        )
    # 3. Otherwise HOLD
    else:
        action = "HOLD"
        conf = 0.50
        reasoning = (
            f"Disciplined HOLD: Indicators not in strict confluence (RSI={rsi:.1f}, "
            f"Price=${price:.2f}/EMA50=${ema_50:.2f}, MACD_Hist={macd_hist:+.2f})."
        )

    return {
        "ticker": ticker,
        "action": action,
        "confidence": conf,
        "reasoning": reasoning,
        "entry_price": price,
        "stop_loss": round(price * 0.98, 2) if action == "BUY" else 0.0,
        "take_profit": round(price * 1.04, 2) if action == "BUY" else 0.0,
    }
