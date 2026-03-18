import os
import requests
import telebot
import pandas as pd
import pandas_ta as ta
from groq import Groq
import time
import json
from datetime import datetime
import threading

# === CONFIGURATION (Railway Variables) ===
TOKEN_TELEGRAM = os.getenv("TELEGRAM_TOKEN")
GROQ_API_KEY = os.getenv("GROQ_API_KEY")
CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")

bot = telebot.TeleBot(TOKEN_TELEGRAM)
client = Groq(api_key=GROQ_API_KEY)

# DAFTAR API BINANCE UNTUK REDUNDANCY
BINANCE_URLS = [
    "https://api1.binance.com", 
    "https://api2.binance.com", 
    "https://api3.binance.com", 
    "https://data-api.binance.vision"
]

# RAM STORAGE (Antrean Sinyal & Laporan)
active_signals = []
daily_stats = {"total": 0, "tp_hit": 0, "sl_hit": 0}

def call_binance_api(endpoint):
    for base_url in BINANCE_URLS:
        try:
            url = f"{base_url}{endpoint}"
            response = requests.get(url, timeout=10)
            if response.status_code == 200:
                data = response.json()
                if isinstance(data, (list, dict)):
                    return data
        except:
            continue
    return None

def get_technical_data(symbol):
    try:
        data = call_binance_api(f"/api/v3/klines?symbol={symbol}&interval=1h&limit=100")
        if not data: return {"rsi": 50, "price": 0}
        
        df = pd.DataFrame(data, columns=['ts', 'o', 'h', 'l', 'c', 'v', 'ct', 'qv', 'nt', 'tbv', 'tqv', 'i'])
        df['close'] = df['c'].astype(float)
        df['rsi'] = ta.rsi(df['close'], length=14)
        return {"rsi": round(df['rsi'].iloc[-1], 2), "price": df['close'].iloc[-1]}
    except:
        return {"rsi": 50, "price": 0}

def get_ai_analysis(coin, condition):
    tech = get_technical_data(coin['symbol'])
    if tech['price'] == 0: return None
    
    # PROMPT DILONGGARKAN: AI diminta lebih agresif mencari peluang di trend kecil
    prompt = f"""
    COIN: {coin['symbol']} | PRICE: {tech['price']} | RSI: {tech['rsi']} | 24h Change: {coin['priceChangePercent']}%
    CONDITION: {condition} | LEVERAGE: 20x
    
    Tugas: Berikan sinyal scalping Futures meskipun trend kecil. 
    Jika RSI > 50 dan harga naik, pertimbangkan LONG. Jika RSI < 50 dan harga turun, pertimbangkan SHORT.
    Berikan alasan singkat yang meyakinkan.
    Hitung TP1 (ROI 20%), TP2 (ROI 40%), TP3 (ROI 100%) dan SL (ROI -50%) berdasarkan Leverage 20x.
    
    OUTPUT WAJIB JSON:
    {{"symbol": "{coin['symbol']}", "signal": "LONG/SHORT", "entry": {tech['price']}, "tp1": 0, "tp2": 0, "tp3": 0, "sl": 0, "rsi": {tech['rsi']}, "reason": "Alasan singkat"}}
    """
    
    try:
        completion = client.chat.completions.create(
            model="llama3-70b-8192",
            messages=[{"role": "user", "content": prompt}],
            response_format={ "type": "json_object" }
        )
        return json.loads(completion.choices[0].message.content)
    except:
        return None

def send_signal_ui(sig_data):
    if not sig_data: return
    symbol = sig_data['symbol']
    chart_url = f"https://www.tradingview.com/chart/?symbol=BINANCE:{symbol}PERP"
    
    msg = (
        f"🔥 **NEW FUTURES SIGNAL** 🔥\n"
        f"━━━━━━━━━━━━━━━━━━━━\n"
        f"🪙 **Pair:** #{symbol}\n"
        f"📈 **Type:** {sig_data['signal']} | 20x (Cross)\n"
        f"📊 **RSI:** {sig_data['rsi']}\n"
        f"━━━━━━━━━━━━━━━━━━━━\n"
        f"🎯 **Entry:** {sig_data['entry']}\n\n"
        f"✅ **Target Profit:**\n"
        f"  └ TP1: {sig_data['tp1']} (ROI 20%)\n"
        f"  └ TP2: {sig_data['tp2']} (ROI 40%)\n"
        f"  └ TP3: {sig_data['tp3']} (ROI 100%)\n\n"
        f"🛑 **Stop Loss:** {sig_data['sl']}\n"
        f"━━━━━━━━━━━━━━━━━━━━\n"
        f"💡 **AI Reason:** _{sig_data.get('reason', 'N/A')}_\n"
        f"━━━━━━━━━━━━━━━━━━━━\n"
        f"🔗 [LIHAT CHART DI TRADINGVIEW]({chart_url})\n"
        f"⚠️ *Gunakan Risk Management!*"
    )
    bot.send_message(CHAT_ID, msg, parse_mode="Markdown", disable_web_page_preview=False)

def check_monitoring():
    global active_signals, daily_stats
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
                daily_stats["sl_hit"] += 1
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
                        if i == 3:
                            daily_stats["tp_hit"] += 1
                            active_signals.remove(sig)
    except Exception as e:
        print(f"Monitor Error: {e}")

def run_scanner():
    global daily_stats
    print("Scanning Market...")
    try:
        res = call_binance_api("/api/v3/ticker/24hr")
        if not res: 
            bot.send_message(CHAT_ID, "❌ Gagal mengambil data Binance.")
            return
        
        # Volume filter tetap 500k agar koin yang dipantau cukup likuid
        usdt_pairs = [c for c in res if c['symbol'].endswith("USDT") and float(c['quoteVolume']) > 500000]
        sorted_c = sorted(usdt_pairs, key=lambda x: float(x['priceChangePercent']))
        
        # PERUBAHAN UTAMA: Mengambil 10 koin terlemah dan 10 koin terkuat (Total 20 target)
        targets = sorted_c[:10] + sorted_c[-10:]
        
        found_any = False
        for t in targets:
            cond = "PUMP" if float(t['priceChangePercent']) > 0 else "DUMP"
            sig = get_ai_analysis(t, cond)
            if sig:
                active_signals.append(sig)
                send_signal_ui(sig)
                daily_stats["total"] += 1
                found_any = True
                # Jeda singkat agar tidak terkena rate limit API Groq
                time.sleep(1)
        
        if not found_any:
            bot.send_message(CHAT_ID, "🔍 Scan selesai: Belum ada setup yang pas di volume > 500k.")
            
    except Exception as e:
        print(f"Scanner Error: {e}")

def main_keyboard():
    markup = telebot.types.ReplyKeyboardMarkup(row_width=2, resize_keyboard=True)
    btn_scan = telebot.types.KeyboardButton('🔍 Scan Market Sekarang')
    btn_status = telebot.types.KeyboardButton('📊 Status Bot')
    markup.add(btn_scan, btn_status)
    return markup

@bot.message_handler(func=lambda message: message.text == '🔍 Scan Market Sekarang')
def manual_scan(message):
    bot.send_message(CHAT_ID, "🚀 Memulai pemindaian manual (20 koin target)...")
    run_scanner()

@bot.message_handler(func=lambda message: message.text == '📊 Status Bot')
def bot_status(message):
    msg = (f"🤖 **Status Bot:** Aktif\n"
           f"📈 Sinyal Aktif: {len(active_signals)}\n"
           f"💰 Volume Filter: > 500,000 USDT\n"
           f"🎯 Target Scan: 20 Koin (Top 10 Gain/Loss)")
    bot.send_message(CHAT_ID, msg, parse_mode="Markdown")

if __name__ == "__main__":
    try:
        bot.send_message(CHAT_ID, "🚀 **Bot AI Bagas Rivansyah Online!**\nTarget diperluas ke 20 koin.", reply_markup=main_keyboard())
    except:
        pass
        
    threading.Thread(target=bot.infinity_polling).start()

    last_scan = 0
    while True:
        # Scan otomatis dipercepat ke setiap 1 jam (3600 detik)
        if time.time() - last_scan > 3600:
            run_scanner()
            last_scan = time.time()
        
        check_monitoring()
        time.sleep(30)
