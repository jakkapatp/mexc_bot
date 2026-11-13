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

TELEGRAM_TOKEN = "8389657702:AAGYbKxFBC-GD1_0MMCOvS5GQ2bg0pnRGg4"
CHAT_ID = "8876853259"

MEME_KEYWORDS = ["DOGE", "SHIB", "PEPE", "FLOKI", "BONK", "TRUMP", "BOME", "NEIRO", "WIF", "PNUT", "GOAT", "MOODENG", "MEME", "CHILLGUY", "BTT", "BABYDOGE", "PORK", "SUNDOG"]

TOP10_SYMBOLS = []
MEME_SYMBOLS = []
SYMBOLS = []

show_tech_details = False

bot_started = False
lock = threading.Lock()

last_alert_sent = {}
last_update_id = 0

def normalize_symbol(symbol):
    s = symbol.strip().upper()
    if not s.endswith("_USDT"):
        s = s[:-4] + "_USDT" if s.endswith("USDT") else s + "_USDT"
    return s

def fetch_top_symbols_from_mexc():
    global TOP10_SYMBOLS, MEME_SYMBOLS, SYMBOLS
    try:
        url = "https://contract.mexc.com/api/v1/contract/ticker"
        res = requests.get(url, timeout=10).json()
        if res.get("success") and "data" in res:
            tickers = res["data"]
            usdt_tickers = [t for t in tickers if t.get("symbol", "").endswith("_USDT")]
            usdt_tickers.sort(key=lambda x: float(x.get("amount24", 0) or 0), reverse=True)
            
            top_10 = []
            meme_candidates = []
            
            for t in usdt_tickers:
                sym = t.get("symbol")
                if not sym:
                    continue
                
                norm_sym = normalize_symbol(sym)
                is_meme = any(kw in sym for kw in MEME_KEYWORDS)
                
                if not is_meme:
                    if len(top_10) < 10:
                        top_10.append(norm_sym)
                else:
                    meme_candidates.append(norm_sym)
                        
                if len(top_10) >= 10 and len(meme_candidates) >= 30:
                    break
            
            filtered_memes = []
            for m in meme_candidates:
                if m not in top_10:
                    if m not in filtered_memes:
                        filtered_memes.append(m)
                if len(filtered_memes) >= 10:
                    break
            
            if top_10:
                TOP10_SYMBOLS = top_10
            if filtered_memes:
                MEME_SYMBOLS = filtered_memes
            
            SYMBOLS = list(set(TOP10_SYMBOLS + MEME_SYMBOLS))
            print(f"[System] Auto-fetched Top 10 Volume & Non-overlapping Meme Coins successfully!", file=sys.stdout, flush=True)
    except Exception as e:
        print(f"[API Error fetching top symbols]: {e}", file=sys.stderr, flush=True)

def send_telegram(message):
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    payload = {"chat_id": CHAT_ID, "text": message, "parse_mode": "HTML"}
    try:
        requests.post(url, json=payload, timeout=10)
    except Exception as e:
        print(f"[Telegram API Error]: {e}", file=sys.stderr, flush=True)

def handle_telegram_commands():
    global SYMBOLS, TOP10_SYMBOLS, MEME_SYMBOLS, show_tech_details, last_update_id
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/getUpdates?offset={last_update_id + 1}&timeout=5"
    try:
        res = requests.get(url, timeout=10).json()
        if res.get("ok"):
            for update in res.get("result", []):
                last_update_id = update["update_id"]
                message = update.get("message", {})
                chat_id = str(message.get("chat", {}).get("id"))
                
                if chat_id == CHAT_ID:
                    text = message.get("text", "").strip()
                    
                    if text == "/list":
                        if not TOP10_SYMBOLS and not MEME_SYMBOLS:
                            list_msg = (
                                "⏳ <b>รอประมวลผล...</b>\n"
                                "<i>(ระบบกำลังดึงข้อมูล Top Volume และ Meme Coins จาก MEXC API)</i>\n\n"
                                "<b>📚 คู่มือการใช้งานเบื้องต้น:</b>\n"
                                "• <b>/list</b> ดูรายชื่อคู่เหรียญเฝ้าระวัง\n"
                                "• <b>/indicators</b> ดูรายชื่ออินดิเคเตอร์\n"
                                "• <b>/tech</b> เปิด/ปิด การแสดงผลรายละเอียดอินดิเคเตอร์\n"
                                "• <b>/help</b> ดูคู่มือทั้งหมด"
                            )
                        else:
                            top_str = ", ".join([s.replace('_', '/') for s in TOP10_SYMBOLS]) if TOP10_SYMBOLS else "รอประมวลผล..."
                            meme_str = ", ".join([s.replace('_', '/') for s in MEME_SYMBOLS]) if MEME_SYMBOLS else "รอประมวลผล..."
                            list_msg = (
                                "📋 <b>รายชื่อคู่เหรียญเฝ้าระวังปัจจุบัน (ดึงอัตโนมัติ):</b>\n\n"
                                f"<b>🥇 กลุ่ม 1 (Top 10 Volume - เฉพาะ LONG):</b>\n• {top_str}\n\n"
                                f"<b>🥈 กลุ่ม 2 (Top 10 Meme Coins - Long/Short):</b>\n• {meme_str}"
                            )
                        send_telegram(list_msg)
                        
                    elif text == "/indicators":
                        ind_msg = (
                            "<b>📊 รายชื่ออินดิเคเตอร์ (10 ตัว)</b>\n"
                            "<i>(กลุ่ม 1 ต้องสอดคล้อง 100% + ผ่าน 7/10 ขึ้นไป)</i>\n\n"
                            "<b>🥇 กลุ่ม 1: เทรนด์ & โมเมนตัม</b>\n"
                            "• EMA 20\n"
                            "• MACD\n"
                            "• RSI\n\n"
                            "<b>🥈 กลุ่ม 2: กรอบราคา & ความผันผวน</b>\n"
                            "• Bollinger Bands\n"
                            "• Parabolic SAR\n"
                            "• Stochastic Oscillator\n\n"
                            "<b>🥉 กลุ่ม 3: อินดิเคเตอร์เสริม</b>\n"
                            "• CCI 20\n"
                            "• Williams %R\n"
                            "• Awesome Oscillator (AO)\n"
                            "• Momentum (MOM)"
                        )
                        send_telegram(ind_msg)
                        
                    elif text == "/tech":
                        show_tech_details = not show_tech_details
                        status_str = "เปิด (ON)" if show_tech_details else "ปิด (OFF)"
                        send_telegram(f"⚙️ สลับสถานะการแสดงผลรายละเอียดอินดิเคเตอร์: <b>{status_str}</b>")
                        
                    elif text == "/help":
                        help_msg = (
                            "<b>📚 คู่มือใช้งานบอทเทรด MEXC</b>\n\n"
                            "• <b>/list</b> ดูรายชื่อคู่เหรียญทั้งหมด\n"
                            "• <b>/indicators</b> ดูรายชื่ออินดิเคเตอร์\n"
                            "• <b>/tech</b> เปิด/ปิด การแสดงผลรายละเอียดอินดิเคเตอร์\n"
                            "• <b>/help</b> ดูคู่มือการใช้งาน"
                        )
                        send_telegram(help_msg)
                        
    except Exception as e:
        print(f"[Command Error]: {e}", file=sys.stderr, flush=True)

def fetch_mexc_kline(symbol, interval):
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
    if df is None or len(df) < 35:
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

    willr = ta.willr(df['high'], df['low'], df['close'], length=14)
    df['WILLR'] = willr if isinstance(willr, pd.Series) else -50.0

    ao = ta.ao(df['high'], df['low'])
    df['AO'] = ao if isinstance(ao, pd.Series) else 0.0

    mom = ta.mom(df['close'], length=10)
    df['MOM'] = mom if isinstance(mom, pd.Series) else 0.0

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
    willr_val = curr['WILLR'] if pd.notna(curr['WILLR']) else -50.0
    ao_val = curr['AO'] if pd.notna(curr['AO']) else 0.0
    mom_val = curr['MOM'] if pd.notna(curr['MOM']) else 0.0

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

    rsi_is_up = rsi > 50
    rsi_dir = check_dir(rsi_is_up)
    
    stoch_dir = check_dir(stoch_val > 50)
    bb_dir = check_dir(price > bb_val)
    
    if pd.notna(sar_l):
        sar_val = sar_l
        sar_dir = check_dir(True)
    else:
        sar_val = sar_s if pd.notna(sar_s) else price
        sar_dir = check_dir(False)
        
    ema_is_up = price > ema
    ema_dir = check_dir(ema_is_up)
    
    cci_dir = check_dir(cci > 0)
    
    macd_is_up = macd_val > 0
    macd_dir = check_dir(macd_is_up)
    
    willr_dir = check_dir(willr_val > -50)
    ao_dir = check_dir(ao_val > 0)
    mom_dir = check_dir(mom_val > 0)

    return {
        "price": price, "s1": s1, "r1": r1,
        "rsi": rsi, "rsi_dir": rsi_dir, "rsi_is_up": rsi_is_up,
        "stoch": stoch_val, "stoch_dir": stoch_dir,
        "bb": bb_val, "bb_dir": bb_dir,
        "sar": sar_val, "sar_dir": sar_dir,
        "ema": ema, "ema_dir": ema_dir, "ema_is_up": ema_is_up,
        "cci": cci, "cci_dir": cci_dir,
        "macd": macd_val, "macd_dir": macd_dir, "macd_is_up": macd_is_up,
        "willr": willr_val, "willr_dir": willr_dir,
        "ao": ao_val, "ao_dir": ao_dir,
        "mom": mom_val, "mom_dir": mom_dir,
        "up_count": up_count, "down_count": down_count
    }

def check_instant_signal(symbol):
    global show_tech_details
    clean_symbol = normalize_symbol(symbol)
    data = analyze_symbol_data(clean_symbol, "Week1")
    if not data:
        return

    signal_type = None
    count_val = 0
    emoji_dir = ""
    
    group1_long = data['rsi_is_up'] and data['ema_is_up'] and data['macd_is_up']
    group1_short = (not data['rsi_is_up']) and (not data['ema_is_up']) and (not data['macd_is_up'])

    normalized_top10 = [normalize_symbol(s) for s in TOP10_SYMBOLS]
    is_top10 = clean_symbol in normalized_top10

    if group1_long and data['up_count'] >= 7:
        signal_type = "LONG"
        count_val = data['up_count']
        emoji_dir = "🟢"
    elif group1_short and data['down_count'] >= 7:
        if is_top10:
            return
        signal_type = "SHORT"
        count_val = data['down_count']
        emoji_dir = "🔴"
    else:
        return

    price = data['price']
    s1 = data['s1']
    r1 = data['r1']

    prev = last_alert_sent.get(clean_symbol)
    if prev:
        if signal_type == "LONG" and price < prev['r1']:
            return
        elif signal_type == "SHORT" and price > prev['s1']:
            return

    last_alert_sent[clean_symbol] = {
        "price": price,
        "s1": s1,
        "r1": r1,
        "signal": signal_type
    }
    
    display_symbol = clean_symbol.replace("_", "/")
    percentage = count_val * 10
    bar_str = "I" * count_val + "-" * (10 - count_val)
    
    action_label = "จุดเข้าซื้อ" if signal_type == "LONG" else "จุดเทขาย"
    p_fmt = f"${price:,.4f}" if price < 1 else f"${price:,.2f}"
    s1_fmt = f"${s1:,.4f}" if s1 < 1 else f"${s1:,.2f}"
    r1_fmt = f"${r1:,.4f}" if r1 < 1 else f"${r1:,.2f}"

    time_str = datetime.now().strftime("%d/%m/%Y เวลา : %H:%M:%S")

    msg = f"""🔥🔥🔥 <b>แจ้งเตือนด่วน</b> 🔥🔥🔥
<b>สัญญาณ {signal_type} ({percentage}%) [{bar_str}]</b>
<b>คู่เหรียญ: {display_symbol}</b>
ราคาปัจจุบัน : {p_fmt}
แนวต้าน : {r1_fmt}
<b>{action_label} : {emoji_dir} {p_fmt}</b>
แนวรับ : {s1_fmt}"""

    if show_tech_details:
        tech_part = f"""
━━━━━━━━━━━━━━━━━━
<b>🥇 กลุ่ม 1: เทรนด์ & โมเมนตัม</b>
• EMA 20 : {data['ema']:,.4f} {data['ema_dir']}
• MACD : {data['macd']:.6f} {data['macd_dir']}
• RSI : {data['rsi']:.2f} {data['rsi_dir']}

<b>🥈 กลุ่ม 2: กรอบราคา & ความผันผวน</b>
• Bollinger : {data['bb']:,.4f} {data['bb_dir']}
• SAR : {data['sar']:,.4f} {data['sar_dir']}
• Stochastic : {data['stoch']:.2f} {data['stoch_dir']}

<b>🥉 กลุ่ม 3: อินดิเคเตอร์เสริม</b>
• CCI 20 : {data['cci']:.2f} {data['cci_dir']}
• Williams %R : {data['willr']:.2f} {data['willr_dir']}
• AO : {data['ao']:.4f} {data['ao_dir']}
• Momentum : {data['mom']:.4f} {data['mom_dir']}"""
        msg += tech_part

    footer_part = f"""
━━━━━━━━━━━━━━━━━━
📅 วันที่ : {time_str}"""
    msg += footer_part

    send_telegram(msg)

def bot_loop():
    loop_count = 0
    fetch_top_symbols_from_mexc()
    
    while True:
        handle_telegram_commands()

        if loop_count > 0 and loop_count % 120 == 0:
            fetch_top_symbols_from_mexc()

        if not SYMBOLS:
            time.sleep(5)
            loop_count += 1
            continue

        current_symbols = list(SYMBOLS)
        for s in current_symbols:
            check_instant_signal(s)
            time.sleep(2)

        loop_count += 1
        time.sleep(30)

def start_bot_thread():
    global bot_started
    with lock:
        if not bot_started:
            bot_started = True
            threading.Thread(target=bot_loop, daemon=True).start()
            print("[System] Real-time Bot Loop started successfully!", file=sys.stdout, flush=True)

@app.route('/')
def home():
    start_bot_thread()
    return "MEXC AI Analysis is Ready Now."

start_bot_thread()

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8080))
    app.run(host='0.0.0.0', port=port)
