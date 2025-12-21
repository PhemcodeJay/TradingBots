import requests
from fpdf import FPDF
from datetime import datetime, timedelta, timezone
from time import sleep
import sys
from typing import List, Dict, Any

# === CONFIGURATION ===
RISK_PCT = 0.015
ACCOUNT_BALANCE = 100
LEVERAGE = 20
ENTRY_BUFFER_PCT = 0.002
MIN_ATR_PCT = 0.001
RSI_ZONE = (20, 80)
INTERVALS = ['15', '60', '240']
MAX_SYMBOLS = 100

# Notifications (keep your existing webhooks)
DISCORD_WEBHOOK_URL = "https://discord.com/api/webhooks/1392538366570135594/lwRHMnC6D1nBMnpXhxf_bdMO0PacPIZxh7-yuKv1OvQm_WhagXAwmCUR9oRpU9sIg4WH"
TELEGRAM_BOT_TOKEN = "8160938302:AAFUmPahGk14OY8F1v5FLHGoVRD-pGTvSOY"
TELEGRAM_CHAT_ID = "5852301284"

tz_utc3 = timezone(timedelta(hours=3))

# === NOTIFICATIONS ===
def send_discord(message):
    if not DISCORD_WEBHOOK_URL:
        return
    try:
        requests.post(DISCORD_WEBHOOK_URL, json={"content": message})
    except:
        pass

def send_telegram(message):
    if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID:
        return
    try:
        url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
        requests.post(url, data={
            "chat_id": TELEGRAM_CHAT_ID,
            "text": message,
            "parse_mode": "Markdown"
        })
    except:
        pass

# === PDF GENERATOR (updated fields) ===
class SignalPDF(FPDF):
    def header(self):
        self.set_font("Arial", "B", 10)
        self.cell(0, 10, "Bybit Crypto Perpetual Advanced Signals", 0, 1, "C")

    def add_signals(self, signals):
        self.set_font("Courier", size=8)
        for s in signals:
            self.set_text_color(0, 0, 0)
            self.set_font("Courier", "B", 8)
            self.cell(0, 5, f"==================== {s['Symbol']} ====================", ln=1)

            self.set_font("Courier", "", 8)
            self.set_text_color(0, 0, 139)
            self.cell(0, 4, f"SIDE: {s['Side']}    SCORE: {s['Score']}%    MARKET: {s['Market Type']}", ln=1)

            self.set_text_color(34, 139, 34)
            self.cell(0, 4, f"ENTRY: {s['Entry']}   TP: {s['TP']}   SL: {s['SL']}", ln=1)

            self.set_text_color(139, 0, 0)
            self.cell(0, 4, f"TRAIL: {s['Trail']}   LIQ: {s['Liq']}   BB: {s['BB Slope']}", ln=1)

            self.set_text_color(0, 100, 100)
            self.cell(0, 4, f"MARGIN: {s['Margin']}   RR: {s['Risk:Reward']}   TIME: {s['Time']}", ln=1)

            self.set_text_color(0, 0, 0)
            self.cell(0, 4, "=" * 60, ln=1)
            self.ln(1)

# === FORMATTER (updated with new fields) ===
def format_signal_block(s):
    return (
        f"==================== {s['Symbol']} ====================\n"
        f"📈 SIDE: {s['Side']}     🏆 SCORE: {s['Score']}%     📊 MARKET: {s['Market Type']}\n"
        f"💵 ENTRY: {s['Entry']}   🎯 TP: {s['TP']}   🛡️ SL: {s['SL']}\n"
        f"🔄 TRAIL: {s['Trail']}   ⚠️ LIQ: {s['Liq']}   📍 BB: {s['BB Slope']}\n"
        f"⚖️ MARGIN: {s['Margin']}   📉 RR: {s['Risk:Reward']}:1\n"
        f"⏰ TIME: {s['Time']}\n"
        "=========================================================\n"
    )

# === INDICATOR FUNCTIONS ===
def get_candles(sym, interval):
    url = f"https://api.bybit.com/v5/market/kline?category=linear&symbol={sym}&interval={interval}&limit=200"
    try:
        data = requests.get(url).json()
        return [{
            'high': float(c[2]),
            'low': float(c[3]),
            'close': float(c[4]),
            'volume': float(c[5])
        } for c in reversed(data['result']['list'])]
    except:
        return []

def ema(prices, period):
    if len(prices) < period: return None
    mult = 2/(period+1)
    val = sum(prices[:period])/period
    for p in prices[period:]:
        val = (p-val)*mult + val
    return val

def sma(prices, period):
    if len(prices) < period: return None
    return sum(prices[-period:]) / period

def rsi(prices, period=14):
    if len(prices) < period+1: return None
    gains = [max(prices[i]-prices[i-1],0) for i in range(1,period+1)]
    losses = [max(prices[i-1]-prices[i],0) for i in range(1,period+1)]
    ag, al = sum(gains)/period, sum(losses)/period
    rs = ag/(al+1e-10)
    return 100 - (100/(1+rs))

def bollinger(prices, period=20, sd=2):
    mid = sma(prices, period)
    if mid is None: return None, None, None
    var = sum((p-mid)**2 for p in prices[-period:]) / period
    std = var**0.5
    return mid+sd*std, mid, mid-sd*std

def atr(highs, lows, closes, period=14):
    if len(highs) < period+1: return None
    trs = [max(h-l, abs(h-c), abs(l-c)) for h,l,c in zip(highs[1:], lows[1:], closes[:-1])]
    val = sum(trs[:period]) / period
    for t in trs[period:]:
        val = (val*(period-1)+t)/period
    return val

def macd(prices):
    fast = ema(prices,12)
    slow = ema(prices,26)
    return fast-slow if fast and slow else None

# === ADVANCED SIGNAL SCORING & ENHANCEMENT ===
def calculate_signal_score(analysis: Dict[str, Any]) -> float:
    indicators = analysis.get("indicators", {})
    trend_score = indicators.get("trend_score", 0)
    rsi_val = indicators.get("rsi", 50)
    macd_hist = indicators.get("macd_histogram", 0)
    ema_9 = indicators.get("ema_9", 0)
    ema_21 = indicators.get("ema_21", 0)

    buy_signals = sell_signals = 0
    if trend_score > 0: buy_signals += 1
    elif trend_score < 0: sell_signals += 1
    if rsi_val < 50: buy_signals += 1
    elif rsi_val > 50: sell_signals += 1
    if macd_hist > 0: buy_signals += 1
    elif macd_hist < 0: sell_signals += 1
    if ema_9 > ema_21: buy_signals += 1
    elif ema_9 < ema_21: sell_signals += 1

    side = "Buy" if buy_signals > sell_signals else "Sell" if sell_signals > buy_signals else "Neutral"
    if side == "Neutral": return 0.0

    score = 60.0
    # RSI side-dependent
    if side == "Buy":
        if 25 <= rsi_val <= 35: score += 15
        elif rsi_val < 20: score += 5
        if 65 <= rsi_val <= 75: score -= 15
        elif rsi_val > 80: score -= 5
    else:
        if 65 <= rsi_val <= 75: score += 15
        elif rsi_val > 80: score += 5
        if 25 <= rsi_val <= 35: score -= 15
        elif rsi_val < 20: score -= 5

    # MACD side-dependent
    if side == "Buy":
        if macd_hist > 0.02: score += 15
        elif macd_hist > 0.01: score += 8
        if macd_hist < 0: score -= 10
    else:
        if macd_hist < -0.02: score += 15
        elif macd_hist < -0.01: score += 8
        if macd_hist > 0: score -= 10

    # EMA & trend alignment
    ema_diff = abs(ema_9 - ema_21) / ema_21 if ema_21 != 0 else 0
    if side == "Buy":
        if trend_score >= 3: score += 20
        elif trend_score >= 2: score += 10
        if ema_9 > ema_21 and ema_diff > 0.01: score += 10
        if ema_9 < ema_21: score -= 10
    else:
        if trend_score <= -3: score += 20
        elif trend_score <= -2: score += 10
        if ema_9 < ema_21 and ema_diff > 0.01: score += 10
        if ema_9 > ema_21: score -= 10

    return min(100.0, max(0.0, score))

def enhance_signal(analysis: Dict[str, Any]) -> Dict[str, Any]:
    indicators = analysis.get("indicators", {})
    price = indicators.get("price", 0)
    atr_val = indicators.get("atr", 0)
    side = analysis.get("side", "Buy").title()

    vol = indicators.get("volatility", 1.5)
    sl_percent = 0.08
    tp_percent = 0.40
    if vol > 3:
        sl_percent = 0.12
        tp_percent = 0.50
    elif vol < 1:
        sl_percent = 0.05
        tp_percent = 0.25

    if side == "Buy":
        sl = round(price * (1 - sl_percent), 6)
        tp = round(price * (1 + tp_percent), 6)
        liq = round(price * (1 - 0.9 / LEVERAGE), 6)
    else:
        sl = round(price * (1 + sl_percent), 6)
        tp = round(price * (1 - tp_percent), 6)
        liq = round(price * (1 + 0.9 / LEVERAGE), 6)

    trail = round(max(atr_val * 1.5, price * 0.03), 6) if atr_val > 0 else round(price * 0.03, 6)
    bb_slope = "Expanding" if (indicators.get("bb_upper", price) - indicators.get("bb_lower", price)) > price * 0.02 else "Contracting"
    market_type = "Low Vol" if vol < 1 else "High Vol" if vol > 3 else "Normal"
    risk_reward = round(abs(tp - price) / abs(price - sl), 2) if abs(price - sl) > 0 else 0

    enhanced = analysis.copy()
    enhanced.update({
        "Entry": round(price, 6),
        "TP": tp,
        "SL": sl,
        "Trail": trail,
        "Liq": liq,
        "Margin": round(3.0, 6),
        "BB Slope": bb_slope,
        "Market Type": market_type,
        "Risk:Reward": risk_reward,
        "Time": datetime.now(tz_utc3).strftime("%Y-%m-%d %H:%M UTC+3")
    })
    return enhanced

# === SIGNAL ANALYSIS (for crypto symbols) ===
def analyze(symbol):
    data = {}
    for tf in INTERVALS:
        candles = get_candles(symbol, tf)
        if len(candles) < 50: return None
        closes = [c['close'] for c in candles]
        highs = [c['high'] for c in candles]
        lows = [c['low'] for c in candles]

        data[tf] = {
            'close': closes[-1],
            'ema9': ema(closes, 9),
            'ema21': ema(closes, 21),
            'rsi': rsi(closes),
            'macd': macd(closes),
            'bb_up': bollinger(closes)[0],
            'bb_low': bollinger(closes)[2],
            'atr': atr(highs, lows, closes),
            'price': closes[-1],
        }

    tf60 = data['60']
    if tf60['atr']/tf60['price'] < MIN_ATR_PCT or not (RSI_ZONE[0] < tf60['rsi'] < RSI_ZONE[1]):
        return None

    sides = []
    for d in data.values():
        if d['close'] > d['bb_up']: sides.append('Buy')
        elif d['close'] < d['bb_low']: sides.append('Sell')
        elif d['close'] > d['ema21']: sides.append('Buy')
        elif d['close'] < d['ema21']: sides.append('Sell')

    if len(set(sides)) != 1: return None

    side = sides[0]
    price = tf60['price']

    # Build analysis for advanced scoring
    analysis = {
        "Symbol": symbol,
        "indicators": {
            "price": price,
            "rsi": tf60['rsi'],
            "macd_histogram": tf60['macd'] or 0,
            "ema_9": tf60['ema9'],
            "ema_21": tf60['ema21'],
            "bb_upper": tf60['bb_up'],
            "bb_lower": tf60['bb_low'],
            "atr": tf60['atr'],
            "volatility": tf60['atr'] / price * 100 if price else 1.5,
            "trend_score": 3 if side == "Buy" else -3,
        },
        "side": side,
        "score": 60.0
    }

    analysis["score"] = calculate_signal_score(analysis)
    if analysis["score"] < 50:  # Higher threshold for quality
        return None

    enhanced = enhance_signal(analysis)
    enhanced["Side"] = enhanced["side"].title()
    enhanced["Score"] = round(enhanced["score"], 1)

    return enhanced

# === FETCH CRYPTO SYMBOLS (USDT perpetuals only) ===
def get_crypto_symbols():
    try:
        data = requests.get("https://api.bybit.com/v5/market/tickers?category=linear").json()
        tickers = [i for i in data['result']['list'] if i['symbol'].endswith("USDT")]
        # Filter out non-crypto (e.g., forex, indices) by common crypto list
        crypto_suffixes = ["BTC", "ETH", "SOL", "XRP", "DOGE", "ADA", "BNB", "TRX", "LINK", "AVAX", "DOT", "MATIC", "LTC", "BCH", "SHIB", "PEPE", "SUI", "APT", "NEAR", "OP", "ARB"]
        crypto_tickers = [t for t in tickers if any(t['symbol'].startswith(base) for base in crypto_suffixes)]
        crypto_tickers.sort(key=lambda x: float(x['turnover24h']), reverse=True)
        return [t['symbol'] for t in crypto_tickers[:MAX_SYMBOLS]]
    except Exception as e:
        print(f"Error fetching symbols: {e}")
        return ["BTCUSDT", "ETHUSDT", "SOLUSDT", "XRPUSDT", "DOGEUSDT"]

# === MAIN LOOP ===
def main():
    while True:
        print("\n🔍 Scanning Bybit Crypto Perpetual Futures with Advanced Signal Logic...\n")
        symbols = get_crypto_symbols()
        print(f"Found {len(symbols)} crypto symbols to scan")
        signals = [analyze(s) for s in symbols]
        signals = [s for s in signals if s]

        if signals:
            signals.sort(key=lambda x: x['Score'], reverse=True)
            top5 = signals[:5]
            blocks = [format_signal_block(s) for s in top5]
            agg_msg = "\n".join(blocks)

            for blk in blocks:
                print(blk)

            # PDF
            pdf = SignalPDF()
            pdf.add_page()
            pdf.add_signals(signals[:20])
            fname = f"crypto_signals_{datetime.now(tz_utc3).strftime('%H%M')}.pdf"
            pdf.output(fname)
            print(f"📄 PDF saved: {fname}")

            # Notifications
            send_discord("📊 **Top 5 Advanced Crypto Signals**\n\n" + agg_msg)
            send_telegram("📊 *Top 5 Advanced Crypto Signals*\n\n" + agg_msg)
            print("✅ Notifications sent to Discord & Telegram.\n")
        else:
            print("⚠️ No high-quality crypto signals found (score ≥50%)\n")

        wait = 900
        print("⏳ Rescanning in 15 minutes...")
        for i in range(wait, 0, -1):
            sys.stdout.write(f"\r⏱️ Next scan in {i//60:02d}:{i%60:02d}")
            sys.stdout.flush()
            sleep(1)
        print()

if __name__ == "__main__":
    main()