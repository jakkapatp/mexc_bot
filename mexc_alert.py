import os
import sys
import time
import threading
import requests
import pandas as pd
import pandas_ta as ta
import numpy as np
from datetime import datetime
from flask import Flask

sys.stdout.reconfigure(line_buffering=True)

app = Flask(__name__)

# --- ข้อมูล Telegram & Trading ---
TELEGRAM_TOKEN = "8389657702:AAGYbKxFBC-GD1_0MMCOvS5GQ2bg0pnRGg4"
CHAT_ID = "8876853259"

# รายชื่อคู่เหรียญเฝ้าระวัง (สามารถเพิ่ม/ลบผ่าน Telegram ได้)
SYMBOLS = ["ETH_USDT", "DOGE_USDT", "SOL_USDT", "XRP_USDT", "TRUMP_USDT", "ONE_USDT"]

bot_started = False
lock = threading.Lock()

last_alert_sent = {}      # {symbol: {"price": ..., "s1": ..., "r1": ..., "signal": ...}} สำหรับเทียบเงื่อนไขราคา
last_update_id = 0        # สำหรับเช็คข้อความคำสั่งจาก Telegram

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

def handle_telegram_commands():
    """ตรวจสอบและจัดการคำสั่งที่พิมพ์มาจาก Telegram แชทส่วนตัว"""
    global SYMBOLS, last_update_id
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/getUpdates?offset={last_update_id + 1}&timeout=5"
    try:
        res = requests.get(url, timeout=10).json()
        if res.get("ok"):
            for update in res.get("result", []):
                last_update_id = update["update_id"]
                message = update.get("message", {})
                chat_id = str(message.get("chat", {}).get("id"))
                
                # กรองเฉพาะแชทของพี่โด่ง
                if chat_id == CHAT_ID:
                    text = message.get("text", "").strip()
                    
                    if text.startswith("/add "):
                        raw_sym = text.replace("/add", "").strip()
                        clean_s = normalize_symbol(raw_sym)
                        if clean_s not in SYMBOLS:
                            SYMBOLS.append(clean_s)
                            send_telegram(f"✅ เพิ่มคู่เหรียญ <b>{clean_s}</b> เข้าสู่ระบบเรียบร้อยค่ะ!\n📋 รายชื่อปัจจุบัน: {', '.join(SYMBOLS)}")
                        else:
                            send_telegram(f"ℹ️ คู่เหรียญ <b>{clean_s}</b> มีอยู่ในรายการอยู่แล้วค่ะ")
                            
                    elif text.startswith("/remove "):
                        raw_sym = text.replace("/remove", "").strip()
                        clean_s = normalize_symbol(raw_sym)
                        if clean_s in SYMBOLS:
                            SYMBOLS.remove(clean_s)
                            send_telegram(f"🗑️ ลบคู่เหรียญ <b>{clean_s}</b> เรียบร้อยค่ะ!\n📋 รายชื่อปัจจุบัน: {', '.join(SYMBOLS)}")
                        else:
                            send_telegram(f"❌ ไม่พบเหรียญ <b>{clean_s}</b> ในรายการเฝ้าระวังค่ะ")
                            
                    elif text == "/list":
                        send_telegram(f"📋 <b>รายชื่อคู่เหรียญเฝ้าระวังปัจจุบัน:</b>\n" + "\n".join([f"• {s}" for s in SYMBOLS]))
                        
                    elif text == "/help":
                        help_msg = (
                            "<b>📚 คู่มือใช้งานบอทเทรด MEXC</b>\n\n"
                            "• <b>/add &lt;คู่เหรียญ&gt;</b> (เช่น /add BTC_USDT หรือ /add btc) เพื่อเพิ่มคู่เหรียญใหม่เข้าไปในระบบเฝ้าระวัง\n"
                            "• <b>/remove &lt;คู่เหรียญ&gt;</b> (เช่น /remove DOGE_USDT) เพื่อลบคู่เหรียญออก\n"
                            "• <b>/list</b> เพื่อดูรายชื่อคู่เหรียญทั้งหมดที่บอทกำลังเฝ้าระวังอยู่ตอนนี้\n"
                            "• <b>/help</b> เพื่อดูคู่มือการใช้งาน"
                        )
                        send_telegram(help_msg)
                        
    except Exception as e:
        print(f"[Command Error]: {e}", file=sys.stderr, flush=True)

def fetch_mexc_kline(symbol, interval):
    """ดึงข้อมูลกราฟจาก MEXC API โดยใช้รูปแบบมาตรฐาน (มีขีดล่าง เช่น ETH_USDT)"""
    try:
        clean_symbol = normalize_symbol(symbol)
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
        print(f"[MEXC API Error - {symbol}]: {e}", file=sys.stderr, flush=True)
    return None

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

    return {
        "price": price, "s1": s1, "r1": r1,
        "rsi": rsi, "rsi_dir": rsi_dir,
        "stoch": stoch_val, "stoch_dir": stoch_dir,
        "bb": bb_val, "bb_dir": bb_dir,
        "sar": sar_val, "sar_dir": sar_dir,
        "ema": ema, "ema_dir": ema_dir,
        "cci": cci, "cci_dir": cci_dir,
        "macd": macd_val, "macd_dir": macd_dir,
        "up_count": up_count, "down_count": down_count
    }

def check_instant_signal(symbol):
    """แจ้งเตือนด่วน: วิเคราะห์กราฟ 1w-1m (Week1) ครบ 7 ตัว พร้อมเช็คเงื่อนไขราคาเทียบแนวรับ-แนวต้านรอบแรก"""
    clean_symbol = normalize_symbol(symbol)
    data = analyze_symbol_data(clean_symbol, "Week1")
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

    price = data['price']
    s1 = data['s1']
    r1 = data['r1']

    # เงื่อนไข: เทียบราคาจากแจ้งเตือนรอบแรก หากค่าไม่ถึงแนวต้าน (LONG) หรือแนวรับ (SHORT) ไม่ต้องแจ้งเตือน
    prev = last_alert_sent.get(clean_symbol)
    if prev:
        if signal_type == "LONG" and price < prev['r1']:
            return
        elif signal_type == "SHORT" and price > prev['s1']:
            return

    # บันทึกข้อมูลราคาและแนวรับ/แนวต้านของรอบนี้ไว้เทียบในรอบถัดไป
    last_alert_sent[clean_symbol] = {
        "price": price,
        "s1": s1,
        "r1": r1,
        "signal": signal_type
    }
    
    action_label = "จุดเข้าซื้อ" if signal_type == "LONG" else "จุดเทขาย"
    p_fmt = f"${price:,.4f}" if price < 1 else f"${price:,.2f}"
    s1_fmt = f"${s1:,.4f}" if s1 < 1 else f"${s1:,.2f}"
    r1_fmt = f"${r1:,.4f}" if r1 < 1 else f"${r1:,.2f}"

    # ดึงวันที่และเวลาปัจจุบันในรูปแบบ dd/mm/yyyy เวลา : 00:00:00 (ไม่มี 24h แล้ว)
    time_str = datetime.now().strftime("%d/%m/%Y เวลา : %H:%M:%S")

    msg = f"""🔥 <b>[แจ้งเตือนด่วน 1w-1m] สัญญาณ {signal_type} ครบถ้วน ({count_val}/7)</b> 🔥
<b>คู่เหรียญ: MEXC ({clean_symbol})</b>
ราคาปัจจุบัน : {p_fmt}
แนวต้าน : {r1_fmt}
<b>{action_label} : {emoji_dir} {p_fmt}</b>
แนวรับ : {s1_fmt}
---------------------------------
• RSI : {data['rsi']:.2f} {data['rsi_dir']}
• Stochastic : {data['stoch']:.2f} {data['stoch_dir']}
• Bollinger : {data['bb']:,.4f} {data['bb_dir']}
• SAR : {data['sar']:,.4f} {data['sar_dir']}
• EMA 20 : {data['ema']:,.4f} {data['ema_dir']}
• CCI 20 : {data['cci']:.2f} {data['cci_dir']}
• MACD : {data['macd']:.6f} {data['macd_dir']}
---------------------------------
📅 วันที่ : {time_str}"""
    send_telegram(msg)

def bot_loop():
    while True:
        # 1. ตรวจสอบคำสั่งจากแชท Telegram ทุกๆ รอบลูป (เช่น /add, /remove, /list, /help)
        handle_telegram_commands()

        # 2. ตรวจสอบสัญญาณด่วนเรียลไทม์ 1w-1m (ครบ 7 ตัว) ทุกๆ 30 วินาที พร้อมเงื่อนไขเช็คราคา
        current_symbols = list(SYMBOLS)
        for s in current_symbols:
            check_instant_signal(s)
            time.sleep(2)

        time.sleep(30)

def start_bot_thread():
    global bot_started
    with lock:
        if not bot_started:
            bot_started = True
            threading.Thread(target=bot_loop, daemon=True).start()
            print("[System] Real-time Bot Loop started!", file=sys.stdout, flush=True)

@app.route('/')
def home():
    start_bot_thread()
    return "MEXC Bot is running 24/7!"

start_bot_thread()

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8080))
    app.run(host='0.0.0.0', port=port)
