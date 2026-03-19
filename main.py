import os
import requests
import telebot
import json
import time
import threading
import re
from datetime import datetime, timezone, timedelta
from telebot.types import ReplyKeyboardMarkup, KeyboardButton
from groq import Groq 

# === CONFIGURATION ===
TOKEN_TELEGRAM = os.getenv("TOKEN_TELEGRAM")
CHAT_ID = os.getenv("CHAT_ID") or os.getenv("ID_CHAT_TELEGRAM")
GROQ_API_KEY = os.getenv("GROQ_API_KEY")

ACTIVE_SIGNALS = []
TRADE_HISTORY = [] 
COOLDOWN_COINS = {} 
LEVERAGE = 20

STABLE_COINS = ["USDCUSDT", "FDUSDUSDT", "TUSDUSDT", "DAIUSDT", "AEURUSDT", "EURUSDT", "GBPUSDT", "BUSDUSDT", "USDPUSDT", "PAXGUSDT", "USDTUSDT"]
GROQ_MODEL = "llama-3.3-70b-versatile"

bot = telebot.TeleBot(TOKEN_TELEGRAM)
client_groq = Groq(api_key=GROQ_API_KEY) if GROQ_API_KEY else None

# --- HELPER: HITUNG ROI ---
def calculate_roi(entry, target, side):
    try:
        entry, target = float(entry), float(target)
        diff = (target - entry) if side.upper() == "LONG" else (entry - target)
        return (diff / entry) * 100 * LEVERAGE
    except: return 0

# --- HELPER: FORMAT HARGA (DIPERBAIKI UNTUK MICIN) ---
def format_price(val):
    try:
        if val is None or float(val) == 0: return "0"
        val = float(val)
        if val < 0.0001: return f"{val:.10f}".rstrip('0').rstrip('.')
        if val < 1: return f"{val:.6f}".rstrip('0').rstrip('.')
        return f"{val:,.2f}"
    except: return str(val)

def call_binance_api(endpoint):
    endpoints = ["https://api.binance.com", "https://api3.binance.com", "https://data-api.binance.vision"]
    for base_url in endpoints:
        try:
            response = requests.get(f"{base_url}{endpoint}", timeout=10) 
            if response.status_code == 200: return response.json()
        except: continue
    return None

# --- UPGRADE: MULTI-TIMEFRAME TECHNICAL ANALYSIS (FIXED INDEX ERROR) ---
def get_multi_tf_technical(symbol):
    try:
        # 1. Ambil Data 4 Jam (4H) - Institutional Trend
        data_4h = call_binance_api(f"/api/v3/klines?symbol={symbol}&interval=4h&limit=20")
        # 2. Ambil Data 1 Jam (1H) - Sniper Entry
        data_1h = call_binance_api(f"/api/v3/klines?symbol={symbol}&interval=1h&limit=50")
        
        # VALIDASI: Pastikan data cukup sebelum di-index agar tidak error "out of range"
        if not data_4h or len(data_4h) < 5 or not data_1h or len(data_1h) < 2:
            print(f"⚠️ {symbol}: Data history tidak cukup untuk analisa Multi-TF.")
            return None

        # Proses 4H Trend
        c4h = [{"c": float(x[4])} for x in data_4h]
        trend_4h = "BULLISH" if c4h[-1]['c'] > c4h[-5]['c'] else "BEARISH"
        
        # Proses 1H Detail
        c1h = [{"c": float(x[4]), "h": float(x[2]), "l": float(x[3]), "v": float(x[5])} for x in data_1h]
        price_now = c1h[-1]['c']
        
        # Hitung volatilitas dengan aman
        vol_change = abs(c1h[-1]['c'] - c1h[-2]['c'])
        volatility = "HIGH" if vol_change > (price_now * 0.005) else "NORMAL"
        
        return {
            "trend_4h": trend_4h,
            "price_1h": price_now,
            "high_24h": max([x['h'] for x in c1h]),
            "low_24h": min([x['l'] for x in c1h]),
            "volatility": volatility
        }
    except Exception as e:
        print(f"❌ Kesalahan Teknis Multi-TF {symbol}: {e}")
        return None

# --- AI SNIPER ANALYSIS (PRO) ---
def get_ai_analysis(coin_data):
    if not client_groq: return None
    symbol = coin_data['symbol']
    price = float(coin_data.get('lastPrice') or coin_data.get('price'))
    change = coin_data.get('priceChangePercent', '0')
    tf_data = get_multi_tf_technical(symbol)
    
    if not tf_data: return None

    prompt = f"""
    Role: Senior Institutional Trader & SMC Expert.
    Market Data {symbol}:
    - Current Price: {format_price(price)}
    - 24h Change: {change}%
    - Institutional Trend (4H): {tf_data['trend_4h']}
    - Intra-day Volatility (1H): {tf_data['volatility']}

    Task: Cari Sniper Entry menggunakan Smart Money Concepts (SMC).
    STRATEGI:
    1. Entry 1H wajib searah dengan Trend 4H.
    2. Jika arah tidak selaras, kembalikan signal "WAIT".
    3. RR minimal 1:2. SL maksimal 3%. No scientific notation.
    Output RAW JSON ONLY.
    """
    try:
        completion = client_groq.chat.completions.create(
            model=GROQ_MODEL, messages=[{"role": "user", "content": prompt}],
            response_format={"type": "json_object"}
        )
        return json.loads(completion.choices[0].message.content)
    except: return None

# --- UI DISPLAY ---
def send_signal_ui(sig_data, target_chat=CHAT_ID):
    if not sig_data or sig_data.get('signal') not in ['LONG', 'SHORT']: return
    symbol = sig_data['symbol']
    side = sig_data['signal'].upper()
    entry = sig_data['entry']
    
    roi1 = calculate_roi(entry, sig_data['tp1'], side)
    roi2 = calculate_roi(entry, sig_data['tp2'], side)
    roi3 = calculate_roi(entry, sig_data['tp3'], side)
    
    side_emoji = "🟢 LONG" if side == "LONG" else "🔴 SHORT"
    tv_link = f"https://www.tradingview.com/chart/?symbol=BINANCE:{symbol}"
    
    msg = (
        f"🏛️ **MULTI-TF SNIPER SIGNAL**\n"
        f"━━━━━━━━━━━━━━━━━━━━\n"
        f"🪙 **Pair:** #{symbol} | `{LEVERAGE}x`\n"
        f"📈 **Side:** {side_emoji}\n"
        f"━━━━━━━━━━━━━━━━━━━━\n"
        f"💎 **Entry:** `{format_price(entry)}`\n\n"
        f"🎯 **TP1:** `{format_price(sig_data['tp1'])}` ({roi1:+.1f}%)\n"
        f"🎯 **TP2:** `{format_price(sig_data['tp2'])}` ({roi2:+.1f}%)\n"
        f"🎯 **TP3:** `{format_price(sig_data['tp3'])}` ({roi3:+.1f}%)\n"
        f"🛑 **SL:** `{format_price(sig_data['sl'])}`\n"
        f"━━━━━━━━━━━━━━━━━━━━\n"
        f"💡 **AI Logic:** {sig_data.get('reason', 'Aligned with 4H Trend')}\n\n"
        f"📊 [Lihat Chart TradingView]({tv_link})\n"
        f"━━━━━━━━━━━━━━━━━━━━\n"
        f"👤 *Sniper Dev: Bagas Rivansyah*"
    )
    bot.send_message(target_chat, msg, parse_mode="Markdown", disable_web_page_preview=False)
    ACTIVE_SIGNALS.append(sig_data) 

# --- MANUAL CHECK HANDLER ---
@bot.message_handler(commands=['cek'])
@bot.message_handler(func=lambda m: m.text.lower().startswith('cek'))
def manual_check(message):
    try:
        parts = message.text.split()
        if len(parts) < 2:
            bot.reply_to(message, "💡 Gunakan format: `/cek BTC` atau `/cek PEPE`", parse_mode="Markdown")
            return
            
        coin = parts[1].upper().replace("USDT", "")
        symbol = f"{coin}USDT"
        
        if symbol in STABLE_COINS:
            bot.reply_to(message, "⚠️ Koin stable tidak didukung.")
            return

        sent_msg = bot.send_message(message.chat.id, f"🔍 Menganalisis **{symbol}** dengan Sniper AI...")
        res = call_binance_api(f"/api/v3/ticker/24hr?symbol={symbol}")
        
        if res and 'lastPrice' in res:
            sig = get_ai_analysis(res)
            if sig:
                if sig.get('signal') == "WAIT":
                    bot.edit_message_text(f"☕ **{symbol}**: AI menyarankan **WAIT**.", message.chat.id, sent_msg.message_id)
                else:
                    bot.delete_message(message.chat.id, sent_msg.message_id)
                    send_signal_ui(sig, message.chat.id)
            else:
                bot.edit_message_text(f"❌ Gagal analisis {symbol}. Data mungkin tidak cukup.", message.chat.id, sent_msg.message_id)
        else:
            bot.edit_message_text(f"❌ Pair **{symbol}** tidak ditemukan di Binance Spot.", message.chat.id, sent_msg.message_id)
    except Exception as e:
        bot.send_message(message.chat.id, f"⚠️ Error: {str(e)}")

# --- MONITORING & SCANNER ---
def monitor_active_signals():
    global ACTIVE_SIGNALS, COOLDOWN_COINS
    while True:
        try:
            for sig in ACTIVE_SIGNALS[:]:
                symbol = sig['symbol']
                res = call_binance_api(f"/api/v3/ticker/price?symbol={symbol}")
                if not res: continue
                curr_price = float(res['price'])
                entry = float(sig['entry'])
                side = sig['signal'].upper()
                
                is_hit = False
                if (side == "LONG" and curr_price <= float(sig['sl'])) or (side == "SHORT" and curr_price >= float(sig['sl'])):
                    bot.send_message(CHAT_ID, f"🛑 **SL HIT**\n#{symbol}\nPrice: {format_price(curr_price)}")
                    is_hit = True
                elif (side == "LONG" and curr_price >= float(sig['tp3'])) or (side == "SHORT" and curr_price <= float(sig['tp3'])):
                    bot.send_message(CHAT_ID, f"🎯 **TP3 HIT (MAX)**\n#{symbol}\nROI: {calculate_roi(entry, curr_price, side):.1f}%")
                    is_hit = True

                if is_hit:
                    COOLDOWN_COINS[symbol] = datetime.now(timezone.utc) + timedelta(hours=1)
                    ACTIVE_SIGNALS.remove(sig)
            time.sleep(60) 
        except: time.sleep(60)

def run_scanner():
    global COOLDOWN_COINS
    print(f"🔍 Multi-TF Sniper Scan: {datetime.now(timezone.utc)}")
    res = call_binance_api("/api/v3/ticker/24hr")
    if not res: return
    
    now = datetime.now(timezone.utc)
    COOLDOWN_COINS = {k: v for k, v in COOLDOWN_COINS.items() if v > now}
    valid = [c for c in res if c['symbol'].endswith("USDT") and c['symbol'] not in STABLE_COINS and float(c['quoteVolume']) > 10000000]
    
    gainers = sorted(valid, key=lambda x: float(x['priceChangePercent']), reverse=True)[:5]
    losers = sorted(valid, key=lambda x: float(x['priceChangePercent']))[:5]
    trending = sorted(valid, key=lambda x: float(x['quoteVolume']), reverse=True)[:5]
    
    targets = {t['symbol']: t for t in (gainers + losers + trending)}.values()
    
    for t in targets:
        symbol = t['symbol']
        try:
            if any(s['symbol'] == symbol for s in ACTIVE_SIGNALS): continue
            if symbol in COOLDOWN_COINS: continue
            
            sig = get_ai_analysis(t)
            if sig:
                send_signal_ui(sig, CHAT_ID)
                time.sleep(15) 
        except: continue

# --- HANDLERS ---
@bot.message_handler(commands=['start'])
def start_cmd(message):
    bot.send_message(message.chat.id, "🚀 **Sniper SMC Pro Online**", reply_markup=main_menu())

def main_menu():
    markup = ReplyKeyboardMarkup(row_width=2, resize_keyboard=True)
    markup.add(KeyboardButton("🔍 Scan Market Sekarang"), KeyboardButton("📊 Status Bot"))
    return markup

@bot.message_handler(func=lambda m: m.text == "🔍 Scan Market Sekarang")
def manual_scan_btn(message):
    bot.reply_to(message, "🔄 Memulai scan Multi-TF...")
    threading.Thread(target=run_scanner).start()

@bot.message_handler(func=lambda m: m.text == "📊 Status Bot")
def status_btn(message):
    total = len(ACTIVE_SIGNALS)
    pairs = ", ".join([s['symbol'] for s in ACTIVE_SIGNALS]) if ACTIVE_SIGNALS else "None"
    bot.send_message(message.chat.id, f"🟢 **Status: Online**\n🎯 Signals: {total}\n🪙 Monitoring: {pairs}")

if __name__ == "__main__":
    threading.Thread(target=monitor_active_signals, daemon=True).start()
    threading.Thread(target=bot.infinity_polling, daemon=True).start()
    while True:
        run_scanner()
        time.sleep(1800)