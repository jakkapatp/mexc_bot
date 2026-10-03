import os
import sys
import time
import threading
import requests
import pandas as pd
import pandas_ta as ta
import numpy as np
from flask import Flask

sys.stdout.reconfigure(line_buffering=True)

app = Flask(__name__)

# --- ข้อมูล Telegram & Trading ---
TELEGRAM_TOKEN = "8389657702:AAGYbKxFBC-GD1_0MMCOvS5GQ2bg0pnRGg4"
CHAT_ID = "8876853259"

# รายชื่อคู่เหรียญเฝ้าระวัง (Futures)
SYMBOLS = ["ETH_USDT", "DOGE_USDT", "SOL_USDT", "XRP_USDT", "TRUMP_USDT", "ONE_USDT"]

bot_started = False
lock = threading.Lock()

last_hourly_time = 0
last_instant_alerts = {}  # {symbol: timestamp}

def normalize_symbol(symbol):
    s = symbol.strip().upper()
    if not s.endswith("_USDT"):
        s = s[:-4] + "_USDT" if s.endswith("USDT") else s + "_USDT"
    return s

def send_telegram(message):
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    payload = {"chat_id": CHAT_ID, "text": message, "parse_mode": "HTML"}
    try:
        requests.post(url, json=payload, timeout=10)
    except Exception as e:
        print(f"[Telegram API Error]: {e}", file=sys.stderr, flush=True)

def fetch_mexc_kline(symbol, interval):
    """ดึงข้อมูลกราฟจาก MEXC Futures API โดยตัด underscore ออกเพื่อให้ตรงกับระบบ Futures"""
    try:
        clean_symbol = normalize_symbol(symbol).replace("_", "")
        url = f"https://contract.mexc.com/api/v1/contract/kline/{clean_symbol}?interval={interval}"
        res = requests.get(url, timeout=10).json()
        if res.get("success") and "data" in res:
            data = res["data"]
            if "close" in data and len(data["close"]) > 0:
                df = pd.DataFrame({
                    "close": [float(x) for x in data["close"]],
                    "high": [float(x) for x in data["high"]],
                    "low": [float(x) for x in data["low"]]
                })
                return df
    except Exception as e:
        print(f"[MEXC Futures API Error - {symbol}]: {e}", file=sys.stderr, flush=True)
    return None

def get_daily_change_pct(symbol):
    """คำนวณ % การเปลี่ยนแปลงรายวันจาก Futures API"""
    try:
        clean_symbol = normalize_symbol(symbol).replace("_", "")
        url = f"https://contract.mexc.com/api/v1/contract/kline/{clean_symbol}?interval=Day1"
        res = requests.get(url, timeout=5).json()
        if res.get("success") and "data" in res:
            data = res["data"]
            if "close" in data and len(data["close"]) >= 2:
                closes = [float(x) for x in data["close"]]
                prev_close = closes[-2]
                curr_close = closes[-1]
                pct = ((curr_close - prev_close) / prev_close) * 100
                return pct
    except Exception as e:
        print(f"[Daily Change Error - {symbol}]: {e}", file=sys.stderr, flush=True)
    return 0.0

def get_startup_message():
    """สร้างข้อความเริ่มต้นแสดง % รายวัน"""
    lines = ["<b>ผู้ช่วยเทรด กำลังวิเคราะห์กราฟ Futures แบบ Real-time คู่เทรดดังนี้</b>"]
    for s in SYMBOLS:
        clean_s = normalize_symbol(s)
        pct = get_daily_change_pct(clean_s)
        if pct < 0:
            pct_str = f"🔴 {pct:.2f}%"
        else:
            pct_str = f"🟢 +{pct:.2f}%" if pct > 0 else f"🟢 {pct:.2f}%"
        lines.append(f"{clean_s}   {pct_str}")
    return "\n".join(lines)

def analyze_symbol_data(symbol, interval):
    df = fetch_mexc_kline(symbol, interval)
    if df is None or len(df) < 30:
        return None

    df['RSI'] = ta.rsi(df['close'], length=14)
    
    stoch = ta.stoch(df['high'], df['low'], df['close'])
    stoch_col = [c for c in stoch.columns if 'STOCHk' in c]
    df['STOCH'] = stoch[stoch_col[0]] if stoch_col else 50.0
    
    bb = ta.bbands(df['close'], length=20)
    bb_col = [c for c in bb.columns if 'BBM' in c]
    df['BB_MID'] = bb[bb_col[0]] if bb_col else df['close']
    
    psar = ta.psar(df['high'], df['low'], df['close'])
    psar_l_col = [c for c in psar.columns if 'PSARl' in c]
    psar_s_col = [c for c in psar.columns if 'PSARs' in c]
    df['PSAR_L'] = psar[psar_l_col[0]] if psar_l_col else np.nan
    df['PSAR_S'] = psar[psar_s_col[0]] if psar_s_col else np.nan
    
    df['EMA'] = ta.ema(df['close'], length=20)
    df['CCI'] = ta.cci(df['high'], df['low'], df['close'], length=20)
    
    macd = ta.macd(df['close'])
    macd_h_col = [c for c in macd.columns if 'MACDh' in c]
    df['MACD_H'] = macd[macd_h_col[0]] if macd_h_col else 0.0

    curr = df.iloc[-1]
    prev = df.iloc[-2]

    pivot = (prev['high'] + prev['low'] + prev['close']) / 3
    s1 = (2 * pivot) - prev['high']
    r1 = (2 * pivot) - prev['low']
    
    price = curr['close']
    rsi = curr['RSI'] if pd.notna(curr['RSI']) else 50.0
    stoch_val = curr['STOCH'] if pd.notna(curr['STOCH']) else 50.0
    bb_val = curr['BB_MID'] if pd.notna(curr['BB_MID']) else price
    sar_l = curr['PSAR_L']
    sar_s = curr['PSAR_S']
    ema = curr['EMA'] if pd.notna(curr['EMA']) else price
    cci = curr['CCI'] if pd.notna(curr['CCI']) else 0.0
    macd_val = curr['MACD_H'] if pd.notna(curr['MACD_H']) else 0.0

    up_count = 0
    down_count = 0

    def check_dir(is_up):
        nonlocal up_count, down_count
        if is_up:
            up_count += 1
            return "⬆️"
        else:
            down_count += 1
            return "⬇️"

    rsi_dir = check_dir(rsi > 50)
    stoch_dir = check_dir(stoch_val > 50)
    bb_dir = check_dir(price > bb_val)
    
    if pd.notna(sar_l):
        sar_val = sar_l
        sar_dir = check_dir(True)
    else:
        sar_val = sar_s if pd.notna(sar_s) else price
        sar_dir = check_dir(False)
        
    ema_dir = check_dir(price > ema)
    cci_dir = check_dir(cci > 0)
    macd_dir = check_dir(macd_val > 0)

    # เงื่อนไขสัญญาณทั่วไป: สัมพันธ์กันตั้งแต่ 6 ตัวขึ้นไป (>= 6)
    if up_count >= 6:
        signal = "BUY / LONG Signal 🟢"
        action = f"จุดเข้าซื้อ: 🟢 ${price:,.4f}" if price < 1 else f"จุดเข้าซื้อ: 🟢 ${price:,.2f}"
    elif down_count >= 6:
        signal = "SELL / SHORT Signal 🔴"
        action = f"จุดเทขาย: 🔴 ${price:,.4f}" if price < 1 else f"จุดเทขาย: 🔴 ${price:,.2f}"
    else:
        signal = "NEUTRAL Signal ⚪"
        action = f"จุดเฝ้าระวัง: ⚪ ${price:,.4f}" if price < 1 else f"จุดเฝ้าระวัง: ⚪ ${price:,.2f}"

    return {
        "price": price, "s1": s1, "r1": r1,
        "rsi": rsi, "rsi_dir": rsi_dir,
        "stoch": stoch_val, "stoch_dir": stoch_dir,
        "bb": bb_val, "bb_dir": bb_dir,
        "sar": sar_val, "sar_dir": sar_dir,
        "ema": ema, "ema_dir": ema_dir,
        "cci": cci, "cci_dir": cci_dir,
        "macd": macd_val, "macd_dir": macd_dir,
        "up_count": up_count, "down_count": down_count,
        "signal": signal, "action": action
    }

def format_report_text(data):
    p_fmt = f"${data['price']:,.4f}" if data['price'] < 1 else f"${data['price']:,.2f}"
    s1_fmt = f"${data['s1']:,.4f}" if data['s1'] < 1 else f"${data['s1']:,.2f}"
    r1_fmt = f"${data['r1']:,.4f}" if data['r1'] < 1 else f"${data['r1']:,.2f}"
    return f"""ราคาปัจจุบัน: <b>{p_fmt}</b>
แนวรับ : {s1_fmt}
แนวต้าน : {r1_fmt}
• RSI : {data['rsi']:.2f} {data['rsi_dir']}
• Stochastic : {data['stoch']:.2f} {data['stoch_dir']}
• Bollinger : {data['bb']:,.4f} {data['bb_dir']}
• SAR : {data['sar']:,.4f} {data['sar_dir']}
• EMA 20 : {data['ema']:,.4f} {data['ema_dir']}
• CCI 20 : {data['cci']:.2f} {data['cci_dir']}
• MACD : {data['macd']:.6f} {data['macd_dir']}
---------------------------------
สัญญาณ: {data['signal']}
<b>{data['action']}</b>"""

def check_instant_signal(symbol):
    """ตรวจสอบเงื่อนไขแจ้งเตือนด่วน: ต้องครบทั้ง 7 ตัว (= 7)"""
    clean_symbol = normalize_symbol(symbol)
    data = analyze_symbol_data(clean_symbol, "Hour4")
    if not data:
        return

    signal_type = None
    count_val = 0
    emoji_dir = ""
    
    if data['up_count'] == 7:
        signal_type = "LONG"
        count_val = data['up_count']
        emoji_dir = "🟢"
    elif data['down_count'] == 7:
        signal_type = "SHORT"
        count_val = data['down_count']
        emoji_dir = "🔴"
    else:
        return

    now = time.time()
    last_time = last_instant_alerts.get(clean_symbol, 0)
    if now - last_time > 900: # ป้องกันส่งซ้ำภายใน 15 นาที
        last_instant_alerts[clean_symbol] = now
        
        action_label = "จุดเข้าซื้อ" if signal_type == "LONG" else "จุดเทขาย"
        p_fmt = f"${data['price']:,.4f}" if data['price'] < 1 else f"${data['price']:,.2f}"
        s1_fmt = f"${data['s1']:,.4f}" if data['s1'] < 1 else f"${data['s1']:,.2f}"
        r1_fmt = f"${data['r1']:,.4f}" if data['r1'] < 1 else f"${data['r1']:,.2f}"

        msg = f"""🔥 <b>[แจ้งเตือนด่วน] สัญญาณ {signal_type} ครบถ้วน ({count_val}/7)</b> 🔥
<b>คู่เหรียญ: MEXC Futures ({clean_symbol})</b>
🎯 <b>{action_label}: {emoji_dir} {p_fmt}</b>

แนวรับ : {s1_fmt}
แนวต้าน : {r1_fmt}
---------------------------------
• RSI : {data['rsi']:.2f} {data['rsi_dir']}
• Stochastic : {data['stoch']:.2f} {data['stoch_dir']}
• Bollinger : {data['bb']:,.4f} {data['bb_dir']}
• SAR : {data['sar']:,.4f} {data['sar_dir']}
• EMA 20 : {data['ema']:,.4f} {data['ema_dir']}
• CCI 20 : {data['cci']:.2f} {data['cci_dir']}
• MACD : {data['macd']:.6f} {data['macd_dir']}
---------------------------------
💡 <i>อินดิเคเตอร์ฟิวเจอร์สสอดคล้องกันครบ 7/7 ตัวฝั่ง {signal_type} พร้อมลุยทันทีค่ะ!</i>
<b>{action_label}: {emoji_dir} {p_fmt}</b>"""
        send_telegram(msg)

def send_hourly_report(symbol):
    clean_symbol = normalize_symbol(symbol)
    short_term = analyze_symbol_data(clean_symbol, "Hour4")
    long_term = analyze_symbol_data(clean_symbol, "Week1")
    
    if not short_term or not long_term:
        return

    msg = f"""🚨 <b>MEXC Futures Alert ({clean_symbol})</b>

<b>วิเคราะห์ระยะสั้น 1-4 ชั่วโมง</b>
{format_report_text(short_term)}

<b>วิเคราะห์ระยะยาว 1w-1m</b>
{format_report_text(long_term)}"""
    
    send_telegram(msg)

def bot_loop():
    global last_hourly_time
    
    startup_msg = get_startup_message()
    send_telegram(startup_msg)
    
    for s in SYMBOLS:
        send_hourly_report(s)
        time.sleep(2)
    last_hourly_time = time.time()

    while True:
        now = time.time()
        
        # 1. ตรวจสอบสัญญาณด่วนเรียลไทม์ (ครบ 7 ตัว) ทุก 30 วินาที
        for s in SYMBOLS:
            check_instant_signal(s)
            time.sleep(2)

        # 2. ส่งรายงานสรุปรายชั่วโมง (ทุก 1 ชั่วโมง)
        if now - last_hourly_time >= 3600:
            for s in SYMBOLS:
                send_hourly_report(s)
                time.sleep(2)
            last_hourly_time = time.time()

        time.sleep(30)

def start_bot_thread():
    global bot_started
    with lock:
        if not bot_started:
            bot_started = True
            threading.Thread(target=bot_loop, daemon=True).start()
            print("[System] Real-time & Hourly Bot Loop started!", file=sys.stdout, flush=True)

@app.route('/')
def home():
    start_bot_thread()
    return "MEXC Futures Bot is running 24/7!"

start_bot_thread()

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8080))
    app.run(host='0.0.0.0', port=port)
