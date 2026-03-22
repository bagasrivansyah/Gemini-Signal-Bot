import os
import requests
import telebot
import json
import time
import threading
import re
from datetime import datetime, timezone, timedelta
from telebot.types import ReplyKeyboardMarkup, KeyboardButton, InlineKeyboardMarkup, InlineKeyboardButton
from groq import Groq 

# === CONFIGURATION ===
TOKEN_TELEGRAM = os.getenv("TOKEN_TELEGRAM")
CHAT_ID = os.getenv("CHAT_ID") or os.getenv("ID_CHAT_TELEGRAM")
GROQ_API_KEY = os.getenv("GROQ_API_KEY")

# --- KEAMANAN: WHITELIST SYSTEM (OS VAR) ---
RAW_WHITELIST = os.getenv("WHITELIST_IDS", "")
WHITELIST_IDS = [int(i.strip()) for i in RAW_WHITELIST.split(",") if i.strip().isdigit()]

# --- STORAGE DI RAM (RESET JIKA RESTART) ---
ACTIVE_SIGNALS = []
TRADE_HISTORY = [] 
COOLDOWN_COINS = {} 
LEVERAGE = 20

# --- AI LEARNING CORE ---
AI_MEMORY = {
    "total_trades": 0,
    "wins": 0,
    "losses": 0,
    "total_roi": 0.0,
    "last_bias": "NEUTRAL"
}

STABLE_COINS = ["USDCUSDT", "FDUSDUSDT", "TUSDUSDT", "DAIUSDT", "AEURUSDT", "EURUSDT", "GBPUSDT", "BUSDUSDT", "USDPUSDT", "USD1USDT", "USDTUSDT"]
GROQ_MODEL = "llama-3.3-70b-versatile"

bot = telebot.TeleBot(TOKEN_TELEGRAM, threaded=True, num_threads=15)
client_groq = Groq(api_key=GROQ_API_KEY) if GROQ_API_KEY else None

# --- FUNGSI PROTEKSI ---
def is_authorized(uid):
    if not WHITELIST_IDS: return True
    return uid in WHITELIST_IDS

def denied_access(message):
    msg = (
        f"╔══════════════════════╗\n"
        f"    **SYSTEM ACCESS DENIED**\n"
        f"╚══════════════════════╝\n\n"
        f"🔴 **CRITICAL:** ID `{message.from_user.id}` is unregistered.\n"
        f"⚠️ This terminal is encrypted for VIP members only."
    )
    bot.reply_to(message, msg, parse_mode="Markdown")

# --- HELPER ---
def calculate_roi(entry, target, side):
    try:
        entry, target = float(entry), float(target)
        if entry == 0: return 0
        diff = (target - entry) if str(side).upper() == "LONG" else (entry - target)
        return (diff / entry) * 100 * LEVERAGE
    except: return 0

def format_price(val):
    try:
        if val is None or float(val) == 0: return "0"
        val = float(val)
        if val < 0.0001: return f"{val:.10f}".rstrip('0').rstrip('.')
        if val < 1: return f"{val:.6f}".rstrip('0').rstrip('.')
        return f"{val:,.2f}"
    except: return str(val)

def call_binance_api(endpoint):
    try:
        r = requests.get(f"https://api.binance.com{endpoint}", timeout=10)
        if r.status_code == 200: return r.json()
    except: pass
    return None

# --- TECHNICAL ---
def get_multi_tf_technical(symbol):
    try:
        data_4h = call_binance_api(f"/api/v3/klines?symbol={symbol}&interval=4h&limit=15")
        data_1h = call_binance_api(f"/api/v3/klines?symbol={symbol}&interval=1h&limit=30")
        if not data_4h or not data_1h: return "INSUFFICIENT"
        c4h = [{"c": float(x[4])} for x in data_4h]
        trend_4h = "BULLISH" if c4h[-1]['c'] > c4h[-5]['c'] else "BEARISH"
        c1h = [{"c": float(x[4]), "h": float(x[2]), "l": float(x[3])} for x in data_1h]
        return {
            "trend_4h": trend_4h,
            "price_1h": c1h[-1]['c'],
            "high_24h": max([x['h'] for x in c1h]),
            "low_24h": min([x['l'] for x in c1h])
        }
    except:
        return None

# --- AI ENGINE (REAL LEARNING) ---
def get_ai_analysis(coin_data):
    if not client_groq: return None

    symbol = coin_data.get('symbol')
    price = float(coin_data.get('lastPrice') or coin_data.get('price', 0))

    tf_data = get_multi_tf_technical(symbol)
    if tf_data == "INSUFFICIENT" or tf_data is None:
        return "SKIP"

    # --- LEARNING LOG ---
    learning_log = ""
    if TRADE_HISTORY:
        recent = TRADE_HISTORY[-5:]
        learning_log = "\n[PAST PERFORMANCE]:\n" + "\n".join(
            [f"- {r['symbol']}: {r['status']} ({r['roi']:+.1f}%)" for r in recent]
        )

    # --- REAL AI LEARNING CORE ---
    adaptive_context = ""
    if AI_MEMORY["total_trades"] > 0:
        winrate = (AI_MEMORY["wins"] / AI_MEMORY["total_trades"]) * 100
        avg_roi = AI_MEMORY["total_roi"] / AI_MEMORY["total_trades"]

        adaptive_context = f"""
        [QUANT AI CORE]
        Trades: {AI_MEMORY["total_trades"]}
        WinRate: {winrate:.1f}%
        AvgROI: {avg_roi:+.2f}%
        Mode: {AI_MEMORY["last_bias"]}

        Behavior:
        - DEFENSIVE → Only high probability trades
        - BALANCED → Normal execution
        - AGGRESSIVE → Early entry allowed
        """

    prompt = f"""
    Role: Lead Quantitative AI Trader.
    Analyze {symbol} at {format_price(price)}.
    Trend: {tf_data['trend_4h']}

    {learning_log}
    {adaptive_context}

    Rules:
    - Avoid impulse entries
    - Use smart money concepts (liquidity, imbalance)
    - TP based on realistic extension
    - Probability must vary (80-99)

    Output JSON:
    {{
        "symbol": "{symbol}",
        "signal": "LONG/SHORT/WAIT",
        "entry": {price},
        "tp1": 0,
        "tp2": 0,
        "tp3": 0,
        "sl": 0,
        "probability": 0,
        "reason": "SMC explanation"
    }}
    """

    try:
        res = client_groq.chat.completions.create(
            model=GROQ_MODEL,
            messages=[{"role": "user", "content": prompt}],
            response_format={"type": "json_object"},
            timeout=25
        )
        return json.loads(res.choices[0].message.content)
    except:
        return None

# --- UI (TIDAK DIUBAH) ---
def send_signal_ui(sig_data, target_chat):
    if not sig_data or sig_data == "SKIP": return
    symbol = sig_data.get('symbol')
    side = str(sig_data.get('signal', 'WAIT')).upper()
    entry, tp1, tp2, tp3, sl = sig_data.get('entry', 0), sig_data.get('tp1', 0), sig_data.get('tp2', 0), sig_data.get('tp3', 0), sig_data.get('sl', 0)
    if not symbol or side not in ['LONG', 'SHORT'] or entry == 0: return

    roi1, roi2, roi3 = calculate_roi(entry, tp1, side), calculate_roi(entry, tp2, side), calculate_roi(entry, tp3, side)
    side_label = "▲ BULLISH VECTOR" if side == "LONG" else "▼ BEARISH VECTOR"
    
    try:
        prob = int(float(sig_data.get('probability', 85)))
    except:
        prob = 85
    
    meter_fill = int(prob // 10)
    meter = "⬥" * meter_fill + "⬦" * (10 - meter_fill)
    
    tv_link = f"https://www.tradingview.com/chart/?symbol=BINANCE:{symbol}"

    msg = (
        f"╔══════════════════════╗\n"
        f"  **NEXUS QUANTUM TERMINAL**\n"
        f"╚══════════════════════╝\n\n"
        f"⬥ **IDENTIFIER:** `#{symbol}`\n"
        f"⬥ **EXECUTION:** `{side_label}`\n"
        f"⬥ **ALGORITHM:** `Neural-SMC v4.0`\n"
        f"⬥ **STRENGTH:** `[{meter}] {prob}%` \n"
        f"━━━━━━━━━━━━━━━━━━━━\n"
        f"┌─── **ENTRY CORRIDOR** ───┐\n"
        f"   ` {format_price(entry)} `\n"
        f"└──────────────────────┘\n\n"
        f"⬥ **QUANTITATIVE TARGETS**\n"
        f"  ├─ **T1:** `{format_price(tp1)}` (`{roi1:+.1f}%`)\n"
        f"  ├─ **T2:** `{format_price(tp2)}` (`{roi2:+.1f}%`)\n"
        f"  └─ **T3:** `{format_price(tp3)}` (`{roi3:+.1f}%`)\n\n"
        f"⬥ **RISK MITIGATION (SL)**\n"
        f"  └─ `{format_price(sl)}` (Isolated 20x)\n"
        f"━━━━━━━━━━━━━━━━━━━━\n"
        f"📝 **NEURAL REASONING:**\n"
        f"_{sig_data.get('reason', 'Market alignment confirmed.')}_\n\n"
        f"🔗 [ACCESS REAL-TIME DATA HUB]({tv_link})\n"
        f"━━━━━━━━━━━━━━━━━━━━\n"
        f"**SMC GLOBAL • INSTITUTIONAL GRADE**"
    )
    bot.send_message(target_chat, msg, parse_mode="Markdown", disable_web_page_preview=False)

    if not any(s.get('symbol') == symbol for s in ACTIVE_SIGNALS):
        ACTIVE_SIGNALS.append(sig_data)

# --- MONITOR (UPDATE LEARNING DI SINI) ---
def monitor_active_signals():
    global ACTIVE_SIGNALS, TRADE_HISTORY, COOLDOWN_COINS
    while True:
        try:
            for sig in ACTIVE_SIGNALS[:]:
                symbol = sig['symbol']
                entry = float(sig['entry'])
                side = sig['signal'].upper()
                tp3 = float(sig['tp3'])
                sl = float(sig['sl'])

                res = call_binance_api(f"/api/v3/ticker/price?symbol={symbol}")
                if not res: continue

                curr = float(res['price'])
                roi = calculate_roi(entry, curr, side)

                finished = False
                status = ""

                if (side == "LONG" and curr <= sl) or (side == "SHORT" and curr >= sl):
                    status, finished = "🛑 SL HIT", True
                elif (side == "LONG" and curr >= tp3) or (side == "SHORT" and curr <= tp3):
                    status, finished = "🎯 TP HIT", True

                if finished:
                    bot.send_message(CHAT_ID, f"{status}\n#{symbol}\nROI: {roi:+.1f}%")

                    TRADE_HISTORY.append({
                        "symbol": symbol,
                        "roi": roi,
                        "status": status,
                        "timestamp": datetime.now(timezone.utc).isoformat()
                    })

                    # --- AI LEARNING UPDATE ---
                    AI_MEMORY["total_trades"] += 1
                    AI_MEMORY["total_roi"] += roi

                    if roi > 0:
                        AI_MEMORY["wins"] += 1
                    else:
                        AI_MEMORY["losses"] += 1

                    if AI_MEMORY["total_trades"] > 5:
                        wr = (AI_MEMORY["wins"] / AI_MEMORY["total_trades"]) * 100
                        if wr > 60:
                            AI_MEMORY["last_bias"] = "AGGRESSIVE"
                        elif wr < 45:
                            AI_MEMORY["last_bias"] = "DEFENSIVE"
                        else:
                            AI_MEMORY["last_bias"] = "BALANCED"

                    ACTIVE_SIGNALS.remove(sig)

            time.sleep(60)
        except:
            time.sleep(60)

# --- SCANNER ---
def run_scanner():
    res = call_binance_api("/api/v3/ticker/24hr")
    if not res: return

    coins = [c for c in res if c['symbol'].endswith("USDT")]
    for c in coins[:10]:
        sig = get_ai_analysis(c)
        if sig and sig != "SKIP":
            send_signal_ui(sig, CHAT_ID)
            time.sleep(10)

# --- START ---
if __name__ == "__main__":
    threading.Thread(target=monitor_active_signals, daemon=True).start()

    def loop():
        while True:
            run_scanner()
            time.sleep(1800)

    threading.Thread(target=loop, daemon=True).start()
    bot.infinity_polling(skip_pending=True)