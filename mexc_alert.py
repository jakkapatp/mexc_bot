import os
import time
import threading
import requests
import pandas as pd
import pandas_ta as ta
from flask import Flask

# --- ระบบเว็บหลอกให้ Render รันฟรีได้ตลอด 24 ชม. ---
app = Flask(__name__)

@app.route('/')
def home():
    return "MEXC Bot is running 24/7!"

def run_web():
    port = int(os.environ.get("PORT", 8080))
    app.run(host='0.0.0.0', port=port)

# --- ข้อมูล Telegram ---
TELEGRAM_TOKEN = "8389657782:AAGYbKxFBC-GD1_BMMCOvS5GQ2bg8pnRSg4"
CHAT_ID = "วาง_CHAT_ID_ตรงนี้"  # ใส่ Chat ID ของพี่โด่ง
SYMBOL = "ETH_USDT"

def send_telegram(message):
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    payload = {"chat_id": CHAT_ID, "text": message, "parse_mode": "HTML"}
    try:
        requests.post(url, json=payload, timeout=5)
    except Exception as e:
        print("Send Error:", e)

def fetch_mexc_kline(symbol):
    try:
        url = f"https://contract.mexc.com/api/v1/contract/kline/{symbol}?interval=Min15"
        res = requests.get(url, timeout=5).json()
        if res.get("success") and "data" in res:
            df = pd.DataFrame({
                "close": res["data"]["close"],
                "high": res["data"]["high"],
                "low": res["data"]["low"]
            })
            return df
    except Exception as e:
        print("Fetch Error:", e)
    return None

def analyze_and_notify():
    df = fetch_mexc_kline(SYMBOL)
    if df is None or len(df) < 30:
        return

    df['RSI'] = ta.rsi(df['close'], length=14)
    macd = ta.macd(df['close'])
    df['MACDh'] = macd['MACDh_12_26_9']

    price = df['close'].iloc[-1]
    rsi = df['RSI'].iloc[-1]
    macdh = df['MACDh'].iloc[-1]
    prev_macdh = df['MACDh'].iloc[-2]

    signal = None
    if rsi < 30 or (macdh > prev_macdh and macdh < 0):
        signal = "🟢 <b>BUY / LONG Signal</b>"
    elif rsi > 70 or (macdh < prev_macdh and macdh > 0):
        signal = "🔴 <b>SELL / SHORT Signal</b>"

    if signal:
        msg = f"""🚨 <b>MEXC Alert ({SYMBOL})</b> 🚨
ราคาปัจจุบัน: <b>${price:,.4f}</b>
• RSI (14): {rsi:.2f}
• MACD Hist: {macdh:.6f}
---------------------------------
สัญญาณ: {signal}"""
        send_telegram(msg)

def bot_loop():
    send_telegram(f"🚀 ระบบ AI เฝ้ากระดาน MEXC ({SYMBOL}) เริ่มทำงานแล้วค่ะ")
    while True:
        analyze_and_notify()
        time.sleep(60)

if __name__ == "__main__":
    # รันบอทแยกเป็น Background Thread
    threading.Thread(target=bot_loop, daemon=True).start()
    # เปิดหน้า Web Server ให้ Render ตรวจผ่าน
    run_web()
