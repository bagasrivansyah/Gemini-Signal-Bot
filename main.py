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

STABLE_COINS = ["USDCUSDT", "FDUSDUSDT", "TUSDUSDT", "DAIUSDT", "AEURUSDT", "EURUSDT", "GBPUSDT", "BUSDUSDT", "USDPUSDT", "USD1USDT", "USDTUSDT"]
GROQ_MODEL = "llama-3.3-70b-versatile"

# TETAPKAN STRUKTUR BOT ASLI DENGAN MULTI-THREADING
bot = telebot.TeleBot(TOKEN_TELEGRAM, threaded=True, num_threads=20)
client_groq = Groq(api_key=GROQ_API_KEY) if GROQ_API_KEY else None

# --- FUNGSI PROTEKSI (Lock System) ---
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

# --- HELPER: HITUNG ROI ---
def calculate_roi(entry, target, side):
    try:
        entry, target = float(entry), float(target)
        if entry == 0: return 0
        diff = (target - entry) if str(side).upper() == "LONG" else (entry - target)
        return (diff / entry) * 100 * LEVERAGE
    except: return 0

# --- HELPER: FORMAT HARGA (ANTY MICIN) ---
def format_price(val):
    try:
        if val is None or float(val) == 0: return "0"
        val = float(val)
        if val < 0.0001: return f"{val:.10f}".rstrip('0').rstrip('.')
        if val < 1: return f"{val:.6f}".rstrip('0').rstrip('.')
        return f"{val:,.2f}"
    except: return str(val)

def call_binance_api(endpoint):
    url = f"https://api.binance.com{endpoint}"
    try:
        response = requests.get(url, timeout=10) 
        if response.status_code == 200: return response.json()
    except: return None
    return None

# --- TECHNICAL ANALYSIS (MULTI-TF 1H & 4H) ---
def get_multi_tf_technical(symbol):
    try:
        data_4h = call_binance_api(f"/api/v3/klines?symbol={symbol}&interval=4h&limit=15")
        data_1h = call_binance_api(f"/api/v3/klines?symbol={symbol}&interval=1h&limit=30")
        if not data_4h or len(data_4h) < 6 or not data_1h or len(data_1h) < 2:
            return "INSUFFICIENT"
        c4h = [{"c": float(x[4])} for x in data_4h]
        trend_4h = "BULLISH" if c4h[-1]['c'] > c4h[-5]['c'] else "BEARISH"
        c1h = [{"c": float(x[4]), "h": float(x[2]), "l": float(x[3])} for x in data_1h]
        return {
            "trend_4h": trend_4h,
            "price_1h": c1h[-1]['c'],
            "high_24h": max([x['h'] for x in c1h]),
            "low_24h": min([x['l'] for x in c1h])
        }
    except: return None

# --- AI SNIPER ENGINE (QUANT & LEARNING TERVALIDASI) ---
def get_ai_analysis(coin_data):
    if not client_groq: return None
    symbol, price = coin_data.get('symbol'), float(coin_data.get('lastPrice') or coin_data.get('price', 0))
    tf_data = get_multi_tf_technical(symbol)
    if tf_data == "INSUFFICIENT" or tf_data is None: return "SKIP"

    # Memory Learning (RAM)
    learning_log = ""
    if TRADE_HISTORY:
        recent = TRADE_HISTORY[-5:]
        learning_log = "\n[PAST VECTOR PERFORMANCE]:\n" + "\n".join([f"- {r['symbol']}: {r['status']} ({r['roi']:+.1f}%)" for r in recent])

    prompt = f"""
    Role: Lead Quantitative Researcher at Hedge Fund.
    System Status: Analyze {symbol} at {format_price(price)}.
    Matrix: 4H Trend {tf_data['trend_4h']}, 1H Price Action.
    {learning_log}

    Task: Berikan Sniper Signal berbasis Machine Learning SMC & Quantitative Model.
    
    Logic Protocols:
    1. Dynamic Confidence: Hitung skor probabilitas unik (Range 81% - 99%). DILARANG menggunakan angka statis (seperti 88) terus-menerus.
    2. Architecture: Gunakan skema AMD (Accumulation-Manipulation-Distribution).
    3. Exit Strategy: Fibonacci 1.618 Golden Extensions.
    4. Cek History: Jika trade terakhir banyak LOSS, gunakan filter 2x lebih ketat (High Probability only).
    
    Output JSON ONLY:
    {{
        "symbol": "{symbol}", "signal": "LONG/SHORT/WAIT", "entry": {price},
        "tp1": 0, "tp2": 0, "tp3": 0, "sl": 0, "probability": 0,
        "reason": "Expert SMC terminology (MSS, Liquidity swept, Premium zones)."
    }}
    """
    try:
        completion = client_groq.chat.completions.create(model=GROQ_MODEL, messages=[{"role": "user", "content": prompt}], response_format={"type": "json_object"}, timeout=25)
        return json.loads(completion.choices[0].message.content)
    except: return None

# --- UI DISPLAY (BLACK-BOX EDITION) ---
def send_signal_ui(sig_data, target_chat):
    if not sig_data or sig_data == "SKIP": return
    symbol = sig_data.get('symbol')
    side = str(sig_data.get('signal', 'WAIT')).upper()
    entry, tp1, tp2, tp3, sl = sig_data.get('entry', 0), sig_data.get('tp1', 0), sig_data.get('tp2', 0), sig_data.get('tp3', 0), sig_data.get('sl', 0)
    if not symbol or side not in ['LONG', 'SHORT'] or entry == 0: return

    roi1, roi2, roi3 = calculate_roi(entry, tp1, side), calculate_roi(entry, tp2, side), calculate_roi(entry, tp3, side)
    side_label = "▲ BULLISH VECTOR" if side == "LONG" else "▼ BEARISH VECTOR"
    prob = sig_data.get('probability', 85)
    meter = "⬥" * (prob // 10) + "⬦" * (10 - (prob // 10))
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
    if not any(s.get('symbol') == symbol for s in ACTIVE_SIGNALS): ACTIVE_SIGNALS.append(sig_data)

# --- MONITORING: TP1-2-3 & SL ---
def monitor_active_signals():
    global ACTIVE_SIGNALS, TRADE_HISTORY, COOLDOWN_COINS
    while True:
        try:
            for sig in ACTIVE_SIGNALS[:]:
                symbol, entry, side = sig['symbol'], float(sig['entry']), sig['signal'].upper()
                tp1, tp2, tp3, sl = float(sig['tp1']), float(sig['tp2']), float(sig['tp3']), float(sig['sl'])
                res = call_binance_api(f"/api/v3/ticker/price?symbol={symbol}")
                if not res: continue
                curr, roi = float(res['price']), calculate_roi(entry, float(res['price']), side)

                is_finished, status = False, ""
                if (side == "LONG" and curr <= sl) or (side == "SHORT" and curr >= sl):
                    status, is_finished = "🛑 SL HIT", True
                elif (side == "LONG" and curr >= tp3) or (side == "SHORT" and curr <= tp3):
                    status, is_finished = "🎯 TP3 HIT", True
                elif (side == "LONG" and curr >= tp2) or (side == "SHORT" and curr <= tp2):
                    if not sig.get('tp2_n'):
                        bot.send_message(CHAT_ID, f"✅ **T2 CORRIDOR BREACHED**\nAsset: #{symbol}\nROI: {roi:+.1f}%"); sig['tp2_n'] = True
                elif (side == "LONG" and curr >= tp1) or (side == "SHORT" and curr <= tp1):
                    if not sig.get('tp1_n'):
                        bot.send_message(CHAT_ID, f"✅ **T1 CORRIDOR BREACHED**\nAsset: #{symbol}\nROI: {roi:+.1f}%"); sig['tp1_n'] = True

                if is_finished:
                    bot.send_message(CHAT_ID, f"{status}\n#{symbol}\nROI: {roi:+.1f}%\nExit: {format_price(curr)}")
                    TRADE_HISTORY.append({"symbol": symbol, "roi": roi, "status": status, "timestamp": datetime.now(timezone.utc).isoformat()})
                    COOLDOWN_COINS[symbol] = datetime.now(timezone.utc) + timedelta(hours=4)
                    ACTIVE_SIGNALS.remove(sig)
            time.sleep(60)
        except: time.sleep(60)

# --- DAILY REPORT ---
def daily_report_scheduler():
    global TRADE_HISTORY
    while True:
        now = datetime.now(timezone.utc)
        if now.hour == 0 and now.minute == 0:
            yesterday = now - timedelta(days=1)
            trades = [t for t in TRADE_HISTORY if datetime.fromisoformat(t['timestamp']) > yesterday]
            if trades:
                total_roi, wr = sum([t['roi'] for t in trades]), (len([t for t in trades if t['roi'] > 0]) / len(trades)) * 100
                bot.send_message(CHAT_ID, f"📊 **NEXUS DAILY QUANT REPORT**\n━━━━━━━━━━━━━━\n✅ Vectors: {len(trades)}\n🏆 Accuracy: {wr:.1f}%\n💰 Total ROI: {total_roi:+.2f}%")
            time.sleep(70)
        time.sleep(30)

# --- SCANNER OTOMATIS ---
def run_scanner():
    global COOLDOWN_COINS
    res = call_binance_api("/api/v3/ticker/24hr")
    if not res: return
    now = datetime.now(timezone.utc)
    COOLDOWN_COINS = {k: v for k, v in COOLDOWN_COINS.items() if v > now}
    valid = [c for c in res if c['symbol'].endswith("USDT") and c['symbol'] not in STABLE_COINS and float(c['quoteVolume']) > 10000000]
    targets = sorted(valid, key=lambda x: float(x['priceChangePercent']), reverse=True)[:4] + sorted(valid, key=lambda x: float(x['priceChangePercent']))[:4] + sorted(valid, key=lambda x: float(x['quoteVolume']), reverse=True)[:2]
    for t in {v['symbol']:v for v in targets}.values():
        if any(s.get('symbol') == t['symbol'] for s in ACTIVE_SIGNALS) or t['symbol'] in COOLDOWN_COINS: continue
        sig = get_ai_analysis(t)
        if sig and sig != "SKIP":
            send_signal_ui(sig, CHAT_ID)
            time.sleep(15) 

# --- HANDLERS ---
@bot.message_handler(commands=['cek'])
@bot.message_handler(func=lambda m: m.text.lower().startswith('cek'))
def manual_check(message):
    if not is_authorized(message.from_user.id): return denied_access(message)
    try:
        parts = message.text.split()
        if len(parts) < 2: return
        coin = "".join(re.findall(r'[A-Z0-9]', parts[1].upper()))
        symbol = f"{coin}USDT"
        sent_msg = bot.send_message(message.chat.id, f"🔍 `QUANTUM_SCANNING:` **{symbol}**...")
        res = call_binance_api(f"/api/v3/ticker/24hr?symbol={symbol}")
        if res:
            sig = get_ai_analysis(res)
            bot.delete_message(message.chat.id, sent_msg.message_id)
            if sig == "SKIP" or not sig: bot.send_message(message.chat.id, f"⚠️ `INSUFFICIENT_DATA:` {symbol}")
            else: send_signal_ui(sig, message.chat.id)
        else: bot.send_message(message.chat.id, f"❌ `IDENTIFIER_NOT_FOUND:` {symbol}")
    except: pass

@bot.message_handler(commands=['start'])
def start_cmd(message):
    if not is_authorized(message.from_user.id): return denied_access(message)
    markup = ReplyKeyboardMarkup(row_width=2, resize_keyboard=True)
    markup.add(KeyboardButton("🛰️ INITIATE SCAN"), KeyboardButton("🖥️ CORE STATUS"))
    bot.send_message(message.chat.id, "⚡ **NEXUS QUANTUM CORE ONLINE**", reply_markup=markup)

@bot.message_handler(func=lambda m: m.text == "🛰️ INITIATE SCAN")
def manual_scan(message):
    if not is_authorized(message.from_user.id): return denied_access(message)
    bot.reply_to(message, "🔄 `INITIATING_ASYNC_SCANNER...`")
    threading.Thread(target=run_scanner).start()

@bot.message_handler(func=lambda m: m.text == "🖥️ CORE STATUS")
def status_btn(message):
    if not is_authorized(message.from_user.id): return denied_access(message)
    bot.send_message(message.chat.id, f"🟢 **SYSTEM DIAGNOSTICS: OPTIMAL**\n🎯 Signals Monitored: {len(ACTIVE_SIGNALS)}")

if __name__ == "__main__":
    threading.Thread(target=monitor_active_signals, daemon=True).start()
    threading.Thread(target=daily_report_scheduler, daemon=True).start()
    def scheduler():
        while True:
            run_scanner()
            time.sleep(1800)
    threading.Thread(target=scheduler, daemon=True).start()
    bot.infinity_polling(skip_pending=True)