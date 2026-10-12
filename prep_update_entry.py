import re

with open("main.py", "r", encoding="utf-8") as f:
    content = f.read()

target = """                is_downtrend = (current_price < ema50) and (ema50 <= ema50_prev)
                entry_action = None

                # TREND FILTER
                from config import TREND_FILTER
                if entry_action and TREND_FILTER:
                    sma200 = float(bar.get("SMA_200", ema200))
                    if entry_action == "BUY" and current_price < sma200:
                        logger.debug(f"[TREND] Filtered: long {ticker} vs SMA200 down")
                        entry_action = None
                    elif entry_action == "SHORT" and current_price > sma200:
                        logger.debug(f"[TREND] Filtered: short {ticker} vs SMA200 up")
                        entry_action = None

                if True:
                    if memory is not None and not is_soft_penalty:
                        # Hard regime filter block..."""

# We actually need to replace the entire chunk of entry_action assignment. Let's just use python `re` to find the start of entry evaluation and end before `if entry_action:`.

replace_script = """
import re

with open("main.py", "r", encoding="utf-8") as f:
    content = f.read()

# Find the block starting from `# 2. Evaluate Entry Signals if slots available` to `if entry_action:`
start_str = "# 2. Evaluate Entry Signals if slots available"
end_str = "if entry_action:"

start_idx = content.find(start_str)
end_idx = content.find(end_str, start_idx)

if start_idx == -1 or end_idx == -1:
    print("Could not find boundaries")
else:
    new_logic = '''# 2. Evaluate Entry Signals (Confluence Scoring Engine)
            elif len(positions) < max_open_positions:
                rsi = float(bar.get("RSI_14", 50.0) or 50.0)
                ema9 = float(bar.get("EMA_9", current_price) or current_price)
                ema21 = float(bar.get("EMA_21", current_price) or current_price)
                ema50 = float(bar.get("EMA_50", current_price) or current_price)
                ema200 = float(bar.get("EMA_200", current_price) or current_price)
                macd_hist = float(bar.get("MACD_HIST", 0.0) or 0.0)
                
                from signals.confluence import calculate_confluence_score
                from config import CONFLUENCE_THRESHOLD
                
                l_score, s_score, l_brk, s_brk = calculate_confluence_score(bar, prev_bar)
                
                entry_action = None
                if l_score >= CONFLUENCE_THRESHOLD:
                    entry_action = "BUY"
                    # print(f"--- Confluence Trigger [{ticker}] BUY --- Score: {l_score}\\n{l_brk}")
                elif s_score >= CONFLUENCE_THRESHOLD:
                    entry_action = "SHORT"
                    # print(f"--- Confluence Trigger [{ticker}] SHORT --- Score: {s_score}\\n{s_brk}")
                    
                vetoed = False
                is_soft_penalty = False
                
                # Check lessons
                if entry_action and memory is not None:
                    if ticker not in ticker_lessons_cache:
                        ticker_lessons_cache[ticker] = memory.retrieve_lessons(f"{ticker} RSI MACD confluence", n_results=3)
                    lessons = ticker_lessons_cache[ticker]
                    
                    l_low = " ".join([l.lower() for l in lessons])
                    if "avoid" in l_low or "restrict" in l_low:
                        local_veto = False
                        if ("price < ema 50" in l_low or "below 50 ema" in l_low) and current_price < ema50 and entry_action == "BUY":
                            local_veto = True
                        elif ("rsi > 70" in l_low or "rsi > 58" in l_low or "above rsi 58" in l_low) and rsi > 58.0 and entry_action == "BUY":
                            local_veto = True
                        if local_veto:
                            if locals().get("LESSON_MODE", "soft") == "soft":
                                is_soft_penalty = True
                            else:
                                vetoed = True
                                entry_action = None

                '''
    content = content[:start_idx] + new_logic + content[end_idx:]
    with open("main.py", "w", encoding="utf-8") as f:
        f.write(content)
    print("Replaced entry logic")
"""
with open("update_entry_logic.py", "w") as f:
    f.write(replace_script)
