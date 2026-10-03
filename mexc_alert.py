import os
import time
import threading
import requests
import pandas as pd
import pandas_ta as ta
from flask import Flask

app = Flask(__name__)

# --- ข้อมูล Telegram & Trading ---
TELEGRAM_TOKEN = "8389657782:AAGYbKxFBC-GD1_BMMCOvS5GQ2bg8pnRSg4"
CHAT_ID = "8876853259"

# รายชื่อคู่เหรียญที่ต้องการให้เฝ้าระวัง
SYMBOLS = ["ETH_USDT", "DOGE_USDT", "XRP_USDT", "TRUMP_USDT", "ONE_USDT"]

bot_started = False
lock = threading.Lock()

def send_telegram(message):
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    payload = {"chat_id": CHAT_ID, "text": message, "parse_mode": "HTML"}
    try:
        res = requests.post(url, json=payload, timeout=10)
        print("Telegram Status:", res.status_code, res.text)
    except Exception as e:
        print("Telegram Send Error:", e)

def fetch_mexc_kline(symbol):
    try:
        url = f"https://contract.mexc.com/api/v1/contract/kline/{symbol}?interval=Min15"
        res = requests.get(url, timeout=5).json()
        if res.get("success") and "data" in res and isinstance(res["data"], dict):
            df = pd.DataFrame({
                "close": res["data"]["close"],
                "high": res["data"]["high"],
                "low": res["data"]["low"]
            })
            return df
    except Exception as e:
        print(f"Fetch Error ({symbol}):", e)
    return None

def analyze_and_notify(symbol):
    df = fetch_mexc_kline(symbol)
    if df is None or len(df) < 30:
        return

    df['RSI'] = ta.rsi(df['close'], length=14)
    macd = ta.macd(df['close'])
    df['MACDh'] = macd['MACDh_12_26_9']

    price = float(df['close'].iloc[-1])
    rsi = float(df['RSI'].iloc[-1])
    macdh = float(df['MACDh'].iloc[-1])
    prev_macdh = float(df['MACDh'].iloc[-2])

    signal = None
    if rsi < 30 or (macdh > prev_macdh and macdh < 0):
        signal = "🟢 <b>BUY / LONG Signal</b>"
    elif rsi > 70 or (macdh < prev_macdh and macdh > 0):
        signal = "🔴 <b>SELL / SHORT Signal</b>"

    if signal:
        msg = f"""🚨 <b>MEXC Alert ({symbol})</b> 🚨
ราคาปัจจุบัน: <b>${price:,.4f}</b>
• RSI (14): {rsi:.2f}
• MACD Hist: {macdh:.6f}
---------------------------------
สัญญาณ: {signal}"""
        send_telegram(msg)

def bot_loop():
    symbols_text = ", ".join(SYMBOLS)
    send_telegram(f"🚀 ระบบผู้ช่วยเฝ้ากระดาน MEXC ({symbols_text}) เริ่มทำงานแล้วค่ะ")
    while True:
        for symbol in SYMBOLS:
            analyze_and_notify(symbol)
            time.sleep(2)
        time.sleep(60)

def start_bot_once():
    global bot_started
    with lock:
        if not bot_started:
            bot_started = True
            threading.Thread(target=bot_loop, daemon=True).start()
            print("Bot background thread started successfully!")

@app.route('/')
def home():
    start_bot_once()
    return "MEXC Bot is running 24/7!"

start_bot_once()

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8080))
    app.run(host='0.0.0.0', port=port)
