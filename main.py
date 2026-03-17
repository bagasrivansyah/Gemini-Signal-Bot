import os
import requests
import telebot
import pandas as pd
import pandas_ta as ta
from groq import Groq
import time
import json
from datetime import datetime

# === CONFIGURATION (Railway Variables) ===
TOKEN_TELEGRAM = os.getenv("TELEGRAM_TOKEN")
GROQ_API_KEY = os.getenv("GROQ_API_KEY")
CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")

bot = telebot.TeleBot(TOKEN_TELEGRAM)
client = Groq(api_key=GROQ_API_KEY)

# RAM STORAGE
active_signals = []
daily_stats = {"total": 0, "tp_hit": 0, "sl_hit": 0}

def get_technical_data(symbol):
    """Mengambil data RSI 1h dari Binance"""
    try:
        url = f"https://api.binance.com/api/v3/klines?symbol={symbol}&interval=1h&limit=100"
        response = requests.get(url, timeout=10)
        data = response.json()
        if not isinstance(data, list): return {"rsi": 50, "price": 0}
        
        df = pd.DataFrame(data, columns=['ts', 'o', 'h', 'l', 'c', 'v', 'ct', 'qv', 'nt', 'tbv', 'tqv', 'i'])
        df['close'] = df['c'].astype(float)
        df['rsi'] = ta.rsi(df['close'], length=14)
        
        return {"rsi": round(df['rsi'].iloc[-1], 2), "price": df['close'].iloc[-1]}
    except Exception as e:
        print(f"Error Tech Data {symbol}: {e}")
        return {"rsi": 50, "price": 0}

def get_ai_analysis(coin, condition):
    tech = get_technical_data(coin['symbol'])
    if tech['price'] == 0: return None
    
    prompt = f"""
    COIN: {coin['symbol']} | PRICE: {tech['price']} | RSI: {tech['rsi']} | 24h Change: {coin['priceChangePercent']}%
    CONDITION: {condition} | LEVERAGE: 20x
    
    Tugas: Analisa Teknikal & berikan Sinyal Futures. 
    Berikan penjelasan singkat (maks 20 kata) kenapa memilih signal tersebut berdasarkan RSI dan harga.
    Hitung TP1 (ROI 20%), TP2 (ROI 40%), TP3 (ROI 100%) dan SL (ROI -50%) berdasarkan Leverage 20x.
    
    Berikan output WAJIB JSON:
    {{"symbol": "{coin['symbol']}", "signal": "LONG/SHORT", "entry": {tech['price']}, "tp1": 0, "tp2": 0, "tp3": 0, "sl": 0, "rsi": {tech['rsi']}, "reason": "Tulis penjelasan AI di sini"}}
    """
    
    try:
        completion = client.chat.completions.create(
            model="llama3-70b-8192",
            messages=[{"role": "user", "content": prompt}],
            response_format={ "type": "json_object" }
        )
        return json.loads(completion.choices[0].message.content)
    except Exception as e:
        print(f"Gagal mendapatkan analisa AI: {e}")
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
    try:
        bot.send_message(CHAT_ID, msg, parse_mode="Markdown", disable_web_page_preview=False)
    except Exception as e:
        print(f"Gagal mengirim Telegram: {e}")

def check_monitoring():
    global active_signals, daily_stats
    if not active_signals: return

    try:
        response = requests.get("https://api.binance.com/api/v3/ticker/price", timeout=10)
        prices = response.json()
        if not isinstance(prices, list): return
        
        price_map = {p['symbol']: float(p['price']) for p in prices}

        for sig in active_signals[:]:
            cp = price_map.get(sig['symbol'])
            if not cp: continue
            
            is_long = sig['signal'].upper() == "LONG"

            # Cek SL
            if (is_long and cp <= sig['sl']) or (not is_long and cp >= sig['sl']):
                bot.send_message(CHAT_ID, f"❌ **{sig['symbol']} SL HIT!**\nSinyal ditutup.")
                daily_stats["sl_hit"] += 1
                active_signals.remove(sig)
                continue

            # Cek TP (1, 2, 3)
            for i in range(1, 4):
                tp_key = f'tp{i}'
                hit_key = f'hit_tp{i}'
                if hit_key not in sig:
                    is_hit = (cp >= sig[tp_key]) if is_long else (cp <= sig[tp_key])
                    if is_hit:
                        bot.send_message(CHAT_ID, f"✅ **{sig['symbol']} TP{i} HIT!** 🚀")
                        sig[hit_key] = True
                        if i == 3:
                            daily_stats["tp_hit"] += 1
                            active_signals.remove(sig)
    except Exception as e:
        print(f"Monitor Error: {e}")

def run_scanner():
    global daily_stats
    print("Memindai Pasar...")
    try:
        res = requests.get("https://api.binance.com/api/v3/ticker/24hr", timeout=10).json()
        if not isinstance(res, list): return

        usdt_pairs = [c for c in res if c.get('symbol', '').endswith("USDT") and float(c.get('quoteVolume', 0)) > 2000000]
        if not usdt_pairs: return
        
        sorted_c = sorted(usdt_pairs, key=lambda x: float(x['priceChangePercent']))
        
        # Ambil Top Pump & Top Dump
        targets = [sorted_c[0], sorted_c[-1]]
        for t in targets:
            cond = "PUMP" if float(t['priceChangePercent']) > 0 else "DUMP"
            sig = get_ai_analysis(t, cond)
            if sig:
                active_signals.append(sig)
                send_signal_ui(sig)
                daily_stats["total"] += 1
                time.sleep(2)
    except Exception as e:
        print(f"Scanner Error: {e}")

if __name__ == "__main__":
    print("Bot AI Futures Bagas Rivansyah Aktif!")
    last_scan = 0
    while True:
        current_time = time.time()
        
        # Scan tiap 2 jam (7200 detik)
        if current_time - last_scan > 7200:
            run_scanner()
            last_scan = current_time
            
        # Laporan Harian jam 12 Malam (Local Server Time)
        if datetime.now().hour == 0 and datetime.now().minute == 0:
            if daily_stats["total"] > 0:
                report = (f"📊 **DAILY REPORT**\n"
                         f"━━━━━━━━━━━━━━━━━━━━\n"
                         f"Sinyal Hari Ini: {daily_stats['total']}\n"
                         f"TP Hit: {daily_stats['tp_hit']}\n"
                         f"SL Hit: {daily_stats['sl_hit']}\n"
                         f"━━━━━━━━━━━━━━━━━━━━")
                bot.send_message(CHAT_ID, report, parse_mode="Markdown")
                daily_stats = {"total": 0, "tp_hit": 0, "sl_hit": 0}
                time.sleep(60) # Hindari double report

        check_monitoring()
        time.sleep(30) # Monitoring tiap 30 detik
