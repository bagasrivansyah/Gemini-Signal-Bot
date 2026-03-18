import os
import requests
import telebot
import pandas as pd
import pandas_ta as ta
import google.generativeai as genai
import time
import json
from datetime import datetime
import threading

# === CONFIGURATION (Railway Variables) ===
# Menggunakan proteksi .get() agar tidak error jika variabel kosong
TOKEN_TELEGRAM = os.getenv("TOKEN_TELEGRAM") or os.getenv("TOKEN TELEGRAM")
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY") or os.getenv("KUNCI_API_GEMINI")
CHAT_ID = os.getenv("CHAT_ID") or os.getenv("ID_CHAT_TELEGRAM")

# Inisialisasi Gemini AI dengan Error Handling
try:
    if not GEMINI_API_KEY:
        print("❌ ERROR: GEMINI_API_KEY tidak ditemukan!")
    genai.configure(api_key=GEMINI_API_KEY)
    model_ai = genai.GenerativeModel('gemini-1.5-flash')
    print("✅ Gemini AI Terhubung.")
except Exception as e:
    print(f"❌ Gagal Inisialisasi AI: {e}")

# Inisialisasi Bot Telegram
if not TOKEN_TELEGRAM:
    print("❌ ERROR: TOKEN_TELEGRAM tidak ditemukan!")
    exit()

bot = telebot.TeleBot(TOKEN_TELEGRAM)

BINANCE_URLS = [
    "https://api1.binance.com", 
    "https://api2.binance.com", 
    "https://api3.binance.com"
]

active_signals = []
daily_stats = {"total": 0, "tp_hit": 0, "sl_hit": 0}

def call_binance_api(endpoint):
    for base_url in BINANCE_URLS:
        try:
            url = f"{base_url}{endpoint}"
            response = requests.get(url, timeout=10)
            if response.status_code == 200:
                return response.json()
        except:
            continue
    return None

def get_technical_data(symbol):
    try:
        data = call_binance_api(f"/api/v3/klines?symbol={symbol}&interval=1h&limit=50")
        if not data: return {"trend": "neutral", "price": 0, "vol_spike": "1x"}
        
        df = pd.DataFrame(data, columns=['ts', 'o', 'h', 'l', 'c', 'v', 'ct', 'qv', 'nt', 'tbv', 'tqv', 'i'])
        df['close'] = df['c'].astype(float)
        df['vol'] = df['v'].astype(float)
        
        # TEKNIKAL: EMA 9 & 21
        df['ema_9'] = ta.ema(df['close'], length=9)
        df['ema_21'] = ta.ema(df['close'], length=21)
        
        current_price = df['close'].iloc[-1]
        avg_vol = df['vol'].iloc[-21:-1].mean()
        vol_ratio = round(df['vol'].iloc[-1] / avg_vol, 2)
        
        trend = "UP" if df['ema_9'].iloc[-1] > df['ema_21'].iloc[-1] else "DOWN"
        
        return {"trend": trend, "price": current_price, "vol_spike": f"{vol_ratio}x"}
    except:
        return {"trend": "neutral", "price": 0, "vol_spike": "1x"}

def get_ai_analysis(coin):
    tech = get_technical_data(coin['symbol'])
    if tech['price'] == 0: return None
    
    prompt = f"""
    Act as an expert Momentum Trader. Analyze {coin['symbol']}.
    Price: {tech['price']}, Trend: {tech['trend']}, Vol Spike: {tech['vol_spike']}, 24h: {coin['priceChangePercent']}%.
    Requirement: 20x Leverage Signal. 
    If Trend UP and Vol Spike > 1.1x: LONG. If Trend DOWN and Vol Spike > 1.1x: SHORT.
    Output MUST be raw JSON:
    {{"symbol": "{coin['symbol']}", "signal": "LONG/SHORT", "entry": {tech['price']}, "tp1": 0, "tp2": 0, "tp3": 0, "sl": 0, "data_info": "{tech['vol_spike']}", "reason": "Expert tech reason"}}
    """
    
    try:
        response = model_ai.generate_content(prompt)
        clean_json = response.text.strip().replace('```json', '').replace('```', '')
        return json.loads(clean_json)
    except Exception as e:
        print(f"⚠️ Gemini Error on {coin['symbol']}: {e}")
        return None

def send_signal_ui(sig_data):
    if not sig_data: return
    symbol = sig_data['symbol']
    chart_url = f"https://www.tradingview.com/chart/?symbol=BINANCE:{symbol}PERP"
    
    msg = (
        f"🔥 **NEW FUTURES SIGNAL (GEMINI)** 🔥\n"
        f"━━━━━━━━━━━━━━━━━━━━\n"
        f"🪙 **Pair:** #{symbol}\n"
        f"📈 **Type:** {sig_data['signal']} | 20x (Cross)\n"
        f"📊 **Vol Spike:** {sig_data.get('data_info', 'N/A')}\n"
        f"━━━━━━━━━━━━━━━━━━━━\n"
        f"🎯 **Entry:** {sig_data['entry']}\n\n"
        f"✅ **Target Profit:**\n"
        f"  └ TP1: {sig_data['tp1']}\n"
        f"  └ TP2: {sig_data['tp2']}\n"
        f"  └ TP3: {sig_data['tp3']}\n\n"
        f"🛑 **Stop Loss:** {sig_data['sl']}\n"
        f"━━━━━━━━━━━━━━━━━━━━\n"
        f"💡 **AI Reason:** _{sig_data.get('reason', 'N/A')}_\n"
        f"━━━━━━━━━━━━━━━━━━━━\n"
        f"🔗 [LIHAT CHART]({chart_url})\n"
        f"⚠️ *Bagas Rivansyah: Gunakan RM!*"
    )
    bot.send_message(CHAT_ID, msg, parse_mode="Markdown")

def check_monitoring():
    global active_signals
    if not active_signals: return
    try:
        prices = call_binance_api("/api/v3/ticker/price")
        if not prices: return
        price_map = {p['symbol']: float(p['price']) for p in prices}
        
        for sig in active_signals[:]:
            cp = price_map.get(sig['symbol'])
            if not cp: continue
            
            is_long = sig['signal'].upper() == "LONG"
            if (is_long and cp <= sig['sl']) or (not is_long and cp >= sig['sl']):
                bot.send_message(CHAT_ID, f"❌ **#{sig['symbol']} SL HIT!**")
                active_signals.remove(sig)
                continue
            
            for i in range(1, 4):
                tp_key = f'tp{i}'
                hit_key = f'hit_tp{i}'
                if hit_key not in sig:
                    is_hit = (cp >= sig[tp_key]) if is_long else (cp <= sig[tp_key])
                    if is_hit:
                        bot.send_message(CHAT_ID, f"✅ **#{sig['symbol']} TP{i} HIT!** 🚀")
                        sig[hit_key] = True
                        if i == 3: active_signals.remove(sig)
    except: pass

def run_scanner():
    print("🔍 Gemini Scanning Market...")
    try:
        res = call_binance_api("/api/v3/ticker/24hr")
        if not res: return
        
        # Filter: Volume > 100k USDT
        targets = [c for c in res if c['symbol'].endswith("USDT") and float(c['quoteVolume']) > 100000]
        targets = sorted(targets, key=lambda x: abs(float(x['priceChangePercent'])), reverse=True)[:15]
        
        found = False
        for t in targets:
            sig = get_ai_analysis(t)
            if sig and 'signal' in sig:
                active_signals.append(sig)
                send_signal_ui(sig)
                found = True
                time.sleep(1) # Delay minimal
        
        if not found:
            bot.send_message(CHAT_ID, "🔍 Scan selesai: Market sedang sideways berat.")
    except Exception as e:
        print(f"Scanner Error: {e}")

def main_keyboard():
    markup = telebot.types.ReplyKeyboardMarkup(row_width=2, resize_keyboard=True)
    markup.add(telebot.types.KeyboardButton('🔍 Scan Market Sekarang'), telebot.types.KeyboardButton('📊 Status Bot'))
    return markup

@bot.message_handler(func=lambda message: message.text == '🔍 Scan Market Sekarang')
def manual_scan(message):
    bot.send_message(CHAT_ID, "🚀 Gemini AI sedang memindai momentum market...")
    run_scanner()

@bot.message_handler(func=lambda message: message.text == '📊 Status Bot')
def bot_status(message):
    msg = (f"🤖 **Status Bot:** Aktif (Gemini 1.5 Flash)\n"
           f"📈 Sinyal Aktif: {len(active_signals)}\n"
           f"🎯 Strategi: EMA 9/21 & Volume Spike\n"
           f"👤 Developer: Bagas Rivansyah")
    bot.send_message(CHAT_ID, msg, parse_mode="Markdown")

if __name__ == "__main__":
    print("🚀 Bot Starting...")
    try:
        bot.send_message(CHAT_ID, f"🚀 **Bot Gemini Bagas Rivansyah Online!**", reply_markup=main_keyboard())
    except Exception as e:
        print(f"Gagal kirim pesan start: {e}")
    
    threading.Thread(target=bot.infinity_polling, daemon=True).start()

    last_scan = 0
    while True:
        # Auto scan setiap 1 jam
        if time.time() - last_scan > 3600:
            run_scanner()
            last_scan = time.time()
        check_monitoring()
        time.sleep(30)
