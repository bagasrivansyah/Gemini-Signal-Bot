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

BINANCE_URLS = [
    "https://api1.binance.com", 
    "https://api2.binance.com", 
    "https://api3.binance.com", 
    "https://data-api.binance.vision"
]

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
        # Mengambil data 1 jam untuk melihat tren (EMA & Volume)
        data = call_binance_api(f"/api/v3/klines?symbol={symbol}&interval=1h&limit=50")
        if not data: return {"trend": "neutral", "price": 0, "vol_spike": "1x"}
        
        df = pd.DataFrame(data, columns=['ts', 'o', 'h', 'l', 'c', 'v', 'ct', 'qv', 'nt', 'tbv', 'tqv', 'i'])
        df['close'] = df['close_price'] = df['c'].astype(float)
        df['vol'] = df['v'].astype(float)
        
        # PERUBAHAN TEKNIKAL: Menggunakan EMA 9 & 21
        df['ema_fast'] = ta.ema(df['close'], length=9)
        df['ema_slow'] = ta.ema(df['close'], length=21)
        
        current_price = df['close'].iloc[-1]
        
        # Deteksi Volume Spike (Volume saat ini vs rata-rata 20 jam)
        avg_vol = df['vol'].iloc[-21:-1].mean()
        current_vol = df['vol'].iloc[-1]
        vol_ratio = round(current_vol / avg_vol, 2)
        
        # Logika Trend
        is_bullish = df['ema_fast'].iloc[-1] > df['ema_slow'].iloc[-1]
        trend_status = "UP" if is_bullish else "DOWN"
        
        return {
            "trend": trend_status, 
            "price": current_price, 
            "vol_spike": f"{vol_ratio}x"
        }
    except:
        return {"trend": "neutral", "price": 0, "vol_spike": "1x"}

def get_ai_analysis(coin, condition):
    tech = get_technical_data(coin['symbol'])
    if tech['price'] == 0: return None
    
    # PROMPT: Fokus murni pada Momentum & EMA Trend
    prompt = f"""
    BERTINDAKLAH SEBAGAI TRADER MOMENTUM.
    PAIR: {coin['symbol']} | PRICE: {tech['price']} | TREND: {tech['trend']} | VOL SPIKE: {tech['vol_spike']}
    24h Change: {coin['priceChangePercent']}% | LEVERAGE: 20x
    
    Tugas: Wajib berikan sinyal LONG atau SHORT.
    - Jika TREND UP dan VOL SPIKE > 1.1x: Prioritas LONG.
    - Jika TREND DOWN dan VOL SPIKE > 1.1x: Prioritas SHORT.
    Hitung TP1 (ROI 20%), TP2 (ROI 50%), TP3 (ROI 100%) dan SL (ROI -50%) secara presisi.
    
    OUTPUT WAJIB JSON:
    {{"symbol": "{coin['symbol']}", "signal": "LONG/SHORT", "entry": {tech['price']}, "tp1": 0, "tp2": 0, "tp3": 0, "sl": 0, "data_info": "{tech['vol_spike']}", "reason": "Momentum Technical"}}
    """
    
    try:
        completion = client.chat.completions.create(
            model="llama3-70b-8192",
            messages=[{"role": "system", "content": "You are a professional trader. Always output valid JSON."},
                      {"role": "user", "content": prompt}],
            response_format={ "type": "json_object" }
        )
        return json.loads(completion.choices[0].message.content)
    except:
        return None

def send_signal_ui(sig_data):
    if not sig_data: return
    symbol = sig_data['symbol']
    chart_url = f"https://www.tradingview.com/chart/?symbol=BINANCE:{symbol}PERP"
    
    # Tetap menggunakan format visual Bagas Rivansyah
    msg = (
        f"🔥 **NEW FUTURES SIGNAL** 🔥\n"
        f"━━━━━━━━━━━━━━━━━━━━\n"
        f"🪙 **Pair:** #{symbol}\n"
        f"📈 **Type:** {sig_data['signal']} | 20x (Cross)\n"
        f"📊 **Vol Spike:** {sig_data.get('data_info', 'N/A')}\n"
        f"━━━━━━━━━━━━━━━━━━━━\n"
        f"🎯 **Entry:** {sig_data['entry']}\n\n"
        f"✅ **Target Profit:**\n"
        f"  └ TP1: {sig_data['tp1']} (ROI 20%)\n"
        f"  └ TP2: {sig_data['tp2']} (ROI 50%)\n"
        f"  └ TP3: {sig_data['tp3']} (ROI 100%)\n\n"
        f"🛑 **Stop Loss:** {sig_data['sl']}\n"
        f"━━━━━━━━━━━━━━━━━━━━\n"
        f"💡 **AI Reason:** _{sig_data.get('reason', 'N/A')}_\n"
        f"━━━━━━━━━━━━━━━━━━━━\n"
        f"🔗 [LIHAT CHART]({chart_url})\n"
        f"⚠️ *Bagas Rivansyah: Gunakan RM!*"
    )
    bot.send_message(CHAT_ID, msg, parse_mode="Markdown")

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
    global daily_stats
    print("Scanning Market...")
    try:
        res = call_binance_api("/api/v3/ticker/24hr")
        if not res: return
        
        usdt_pairs = [c for c in res if c['symbol'].endswith("USDT") and float(c['quoteVolume']) > 100000]
        sorted_c = sorted(usdt_pairs, key=lambda x: abs(float(x['priceChangePercent'])), reverse=True)
        
        targets = sorted_c[:20]
        
        found_any = False
        for t in targets:
            sig = get_ai_analysis(t, "SCAN")
            if sig and 'signal' in sig:
                active_signals.append(sig)
                send_signal_ui(sig)
                daily_stats["total"] += 1
                found_any = True
                time.sleep(1)
        
        if not found_any:
            bot.send_message(CHAT_ID, "🔍 Scan selesai: Market sedang sideways berat.")
    except Exception as e:
        print(f"Scanner Error: {e}")

def main_keyboard():
    markup = telebot.types.ReplyKeyboardMarkup(row_width=2, resize_keyboard=True)
    markup.add(telebot.types.KeyboardButton('🔍 Scan Market Sekarang'), telebot.types.KeyboardButton('📊 Status Bot'))
    return markup

@bot.message_handler(func=lambda message: message.text == '🔍 Scan Market Sekarang')
def manual_scan(message):
    bot.send_message(CHAT_ID, "🚀 Memulai pemindaian teknikal (Target 20 koin)...")
    run_scanner()

@bot.message_handler(func=lambda message: message.text == '📊 Status Bot')
def bot_status(message):
    msg = (f"🤖 **Status Bot:** Aktif\n"
           f"📈 Sinyal Aktif: {len(active_signals)}\n"
           f"💰 Volume Filter: > 100,000 USDT\n"
           f"🎯 Strategi: EMA Cross & Volume Spike")
    bot.send_message(CHAT_ID, msg, parse_mode="Markdown")

if __name__ == "__main__":
    try:
        bot.send_message(CHAT_ID, f"🚀 **Bot AI Bagas Rivansyah Online!**\nSistem monitoring teknikal aktif.", reply_markup=main_keyboard())
    except: pass
    
    threading.Thread(target=bot.infinity_polling, daemon=True).start()

    last_scan = 0
    while True:
        if time.time() - last_scan > 3600:
            run_scanner()
            last_scan = time.time()
        check_monitoring()
        time.sleep(30)
