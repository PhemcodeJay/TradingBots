# === XAUUSD SIGNAL SCANNER FOR 5M WITH 3M & 1M CONFIRMATION ===

import MetaTrader5 as mt5
from datetime import datetime, timedelta, timezone
from time import sleep
try:
    from fpdf import FPDF
except ImportError:
    FPDF = None

# === CONFIGURATION ===
SYMBOL = "XAUUSD"
tz_utc3 = timezone(timedelta(hours=3))
INTERVAL_MAIN = mt5.TIMEFRAME_M5
INTERVALS_CONFIRM = [mt5.TIMEFRAME_M3, mt5.TIMEFRAME_M1]  # confirmation timeframes
RISK_PCT = 0.015
ACCOUNT_BALANCE = 100
LEVERAGE = 20
ENTRY_BUFFER_PCT = 0.002
RSI_ZONE = (20, 80)
LOT_SIZE = 0.01  # fixed lot size
MARGIN_USDT = 5  # USDT per trade

# === PDF GENERATOR ===
if FPDF:
    class SignalPDF(FPDF):
        def header(self):
            self.set_font("Arial", "B", 10)
            self.cell(0, 10, "XAUUSD Signals 5M + 3M/1M Confirm", 0, 1, "C")

        def add_signals(self, signals):
            self.set_font("Courier", size=8)
            for s in signals:
                self.set_text_color(0, 0, 0)
                self.set_font("Courier", "B", 8)
                self.cell(0, 5, f"==================== {s['Symbol']} ====================", ln=1)

                self.set_font("Courier", "", 8)
                self.set_text_color(0, 0, 139)
                self.cell(0, 4, f"TYPE: {s['Type']}    SIDE: {s['Side']}     SCORE: {s['Score']}%", ln=1)

                self.set_text_color(34, 139, 34)
                self.cell(0, 4, f"ENTRY: {s['Entry']}   TP: {s['TP']}   SL: {s['SL']}", ln=1)

                self.set_text_color(139, 0, 0)
                self.cell(0, 4, f"MARKET: {s['Market']}  BB: {s['BB Slope']}  TRAIL: {s['Trail']}", ln=1)

                self.set_text_color(0, 100, 100)
                self.cell(0, 4, f"QTY: {s['Qty']}  MARGIN: {s['Margin']} USDT  LIQ: {s['Liq']}", ln=1)

                self.set_text_color(0, 0, 0)
                self.cell(0, 4, f"TIME: {s['Time']}", ln=1)
                self.cell(0, 4, "=" * 57, ln=1)
                self.ln(1)
else:
    class SignalPDF:
        def __init__(self):
            print("FPDF not available, PDF generation disabled")
        def add_page(self): pass
        def add_signals(self, signals): pass
        def output(self, filename):
            print(f"PDF generation skipped: {filename}")

# === INDICATORS ===
def ema(prices, period):
    if len(prices) < period: return None
    mult = 2 / (period + 1)
    val = sum(prices[:period]) / period
    for p in prices[period:]:
        val = (p - val) * mult + val
    return val

def sma(prices, period):
    if len(prices) < period: return None
    return sum(prices[-period:]) / period

def rsi(prices, period=14):
    if len(prices) < period + 1: return None
    gains = [max(prices[i] - prices[i - 1], 0) for i in range(1, period + 1)]
    losses = [max(prices[i - 1] - prices[i], 0) for i in range(1, period + 1)]
    ag, al = sum(gains) / period, sum(losses) / period
    rs = ag / (al + 1e-10)
    return 100 - (100 / (1 + rs))

def bollinger(prices, period=20, sd=2):
    mid = sma(prices, period)
    if mid is None: return None, None, None
    var = sum((p - mid) ** 2 for p in prices[-period:]) / period
    std = var ** 0.5
    return mid + sd*std, mid, mid - sd*std

def macd(prices):
    fast = ema(prices, 12)
    slow = ema(prices, 26)
    return fast - slow if fast and slow else None

def classify_trend(e9, e21, s20):
    if e9 > e21 > s20: return "Trend"
    if e9 > e21: return "Swing"
    return "Scalp"

# === MT5 DATA FETCH ===
def get_candles_mt5(symbol, timeframe, count=200):
    rates = mt5.copy_rates_from_pos(symbol, timeframe, 0, count)
    if rates is None: return []
    return [{'high': r['high'], 'low': r['low'], 'close': r['close'], 'volume': r['tick_volume']} for r in rates]

# === SIGNAL ANALYSIS ===
def analyze(symbol):
    # Main 5M timeframe
    candles = get_candles_mt5(symbol, INTERVAL_MAIN)
    if len(candles) < 30: return None
    closes = [c['close'] for c in candles]
    highs = [c['high'] for c in candles]
    lows = [c['low'] for c in candles]

    tf = {
        'close': closes[-1],
        'ema9': ema(closes, 9),
        'ema21': ema(closes, 21),
        'sma20': sma(closes, 20),
        'rsi': rsi(closes),
        'macd': macd(closes),
        'bb_up': bollinger(closes)[0],
        'bb_mid': bollinger(closes)[1],
        'bb_low': bollinger(closes)[2]
    }

    # Confirm with 3M and 1M
    for tfc in INTERVALS_CONFIRM:
        c_candles = get_candles_mt5(symbol, tfc)
        if len(c_candles) < 20: return None
        c_closes = [c['close'] for c in c_candles]
        c_ema21 = ema(c_closes, 21)
        if not c_ema21: return None
        # Simple confirmation: price above/below EMA21 matches main
        if (tf['close'] > tf['ema21'] and c_closes[-1] < c_ema21) or \
           (tf['close'] < tf['ema21'] and c_closes[-1] > c_ema21):
            return None  # conflicting direction

    # Determine side
    side = 'Buy' if tf['close'] > tf['ema21'] else 'Sell'
    trend = classify_trend(tf['ema9'], tf['ema21'], tf['sma20'])
    bb_dir = "Up" if tf['close'] > tf['bb_up'] else "Down" if tf['close'] < tf['bb_low'] else "No"
    entry = round(tf['close'], 2)
    tp = round(entry * (1.015 if side == 'Buy' else 0.985), 2)
    sl = round(entry * (0.985 if side == 'Buy' else 1.015), 2)
    trail = round(entry * (1 - ENTRY_BUFFER_PCT) if side == 'Buy' else entry * (1 + ENTRY_BUFFER_PCT), 2)
    liq = round(entry * (1 - 1 / LEVERAGE) if side == 'Buy' else entry * (1 + 1 / LEVERAGE), 2)

    score = 0
    score += 0.3 if tf['macd'] and tf['macd'] > 0 else 0
    score += 0.2 if tf['rsi'] < 30 or tf['rsi'] > 70 else 0
    score += 0.2 if bb_dir != "No" else 0
    score += 0.3 if trend in ["Trend", "Swing"] else 0

    return {
        'Symbol': symbol,
        'Side': side,
        'Type': trend,
        'Score': round(score * 100, 1),
        'Entry': entry,
        'TP': tp,
        'SL': sl,
        'Trail': trail,
        'Margin': MARGIN_USDT,
        'Qty': LOT_SIZE,
        'Market': entry,
        'Liq': liq,
        'BB Slope': bb_dir,
        'Time': datetime.now(tz_utc3).strftime("%Y-%m-%d %H:%M UTC+3")
    }

# === TERMINAL FORMATTER ===
def format_signal_terminal(s):
    return (
        f"==================== {s['Symbol']} ====================\n"
        f"📊 Type: {s['Type']}\n💰 Side: {s['Side']}\n⭐ Score: {s['Score']}%\n\n"
        f"💵 Entry Price: {s['Entry']}\n🎯 TP: {s['TP']}\n🛡️ SL: {s['SL']}\n🔄 Trail: {s['Trail']}\n\n"
        f"📦 Quantity: {s['Qty']} lots\n⚖️ Margin: {s['Margin']} USDT\n💸 Liquidation: {s['Liq']}\n\n"
        f"📈 Current Market: {s['Market']}\n📍 BB Slope: {s['BB Slope']}\n⏰ Time: {s['Time']}\n"
        "=========================================================\n"
    )

# === MAIN LOOP ===
def main():
    if not mt5.initialize():
        print("❌ MT5 initialize() failed")
        return

    SCAN_INTERVAL = 5 * 60  # 5 minutes in seconds

    while True:
        print("\n🔍 Scanning XAUUSD 5M + 3M/1M confirmation...\n")
        signal = analyze(SYMBOL)
        if signal:
            print(format_signal_terminal(signal))
            pdf = SignalPDF()
            pdf.add_page()
            pdf.add_signals([signal])
            fname = f"XAUUSD_signal_{datetime.now(tz_utc3).strftime('%H%M')}.pdf"
            pdf.output(fname)
            print(f"📄 PDF saved: {fname}\n")
        else:
            print("⚠️ No valid signal found\n")

        print(f"⏳ Next scan in 5 minutes...")
        for remaining in range(SCAN_INTERVAL, 0, -1):
            mins, secs = divmod(remaining, 60)
            print(f"\r⏱️  Time until next scan: {mins:02d}:{secs:02d}", end="")
            sleep(1)
        print()

if __name__ == "__main__":
    main()
