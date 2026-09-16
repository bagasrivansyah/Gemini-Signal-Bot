import os
import requests
import telebot
import json
import time
import threading
import re
from datetime import datetime, timezone, timedelta
from flask import Flask, render_template_string
from telebot.types import ReplyKeyboardMarkup, KeyboardButton
from groq import Groq 

TOKEN_TELEGRAM = os.getenv("TOKEN_TELEGRAM")
CHAT_ID = os.getenv("CHAT_ID") or os.getenv("ID_CHAT_TELEGRAM")
GROQ_API_KEY = os.getenv("GROQ_API_KEY")
PORT = int(os.getenv("PORT", 8080))

ACTIVE_SIGNALS = []
TRADE_HISTORY = [] 
LEVERAGE = 20

bot = telebot.TeleBot(TOKEN_TELEGRAM, threaded=True, num_threads=15)
client_groq = Groq(api_key=GROQ_API_KEY) if GROQ_API_KEY else None
app = Flask(__name__)

HTML_TEMPLATE = """
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <title>NEXUS QUANTUM</title>
    <style>
        body { background: #000; color: #00ff88; font-family: monospace; margin: 0; padding: 20px; }
        .header { text-align: center; border-bottom: 1px solid #00ff88; padding: 20px 0; margin-bottom: 20px; }
        .header h1 { margin: 0; font-size: 24px; }
        .signal-card { background: rgba(10,10,10,0.8); border: 1px solid #333; margin-bottom: 15px; padding: 15px; }
        .symbol { font-size: 18px; color: #fff; margin-bottom: 10px; }
        .no-signal { text-align: center; margin-top: 50px; color: #666; }
    </style>
</head>
<body>
    <div class="header">
        <h1>NEXUS QUANTUM</h1>
        <p>v5.0.2 - LIVE CORE</p>
    </div>
    {% if signals %}
        {% for s in signals %}
        <div class="signal-card">
            <div class="symbol">#{{ s.symbol }}</div>
            <div>{{ s.signal }} at {{ s.entry }}</div>
        </div>
        {% endfor %}
    {% else %}
        <div class="no-signal">[ SEARCHING FOR DEEP LIQUIDITY ]</div>
    {% endif %}
</body>
</html>
"""

@app.route('/')
def dashboard():
    return render_template_string(HTML_TEMPLATE, signals=ACTIVE_SIGNALS)

def call_binance_api(endpoint):
    url = f"https://api.binance.com{endpoint}"
    try:
        response = requests.get(url, timeout=10) 
        if response.status_code == 200: 
            return response.json()
    except:
        return None
    return None

@bot.message_handler(commands=['start'])
def start_cmd(message):
    markup = ReplyKeyboardMarkup(row_width=2, resize_keyboard=True)
    markup.add(KeyboardButton("Scan"))
    bot.send_message(message.chat.id, "NEXUS QUANTUM ONLINE", reply_markup=markup)

@bot.message_handler(func=lambda m: m.text == "Scan")
def scan_cmd(message):
    bot.send_message(message.chat.id, "Scanning...")

if __name__ == "__main__":
    print("[NEXUS] Starting bot...")
    threading.Thread(target=lambda: app.run(host='0.0.0.0', port=PORT, use_reloader=False, debug=False), daemon=True).start()
    print(f"[NEXUS] Web server running on port {PORT}")
    print("[NEXUS] Bot polling started...")
    bot.infinity_polling(skip_pending=True)
