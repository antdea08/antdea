import ccxt, os, json
import pandas as pd
from datetime import datetime

SYMBOL = 'DOGE/USDT'
TIMEFRAME = '5m'
BUY_FRAC = 0.95
SL_PCT = 0.03
STATE_FILE = 'entry.json'

exchange = ccxt.mexc({
    'apiKey': os.getenv('MEXC_API_KEY'),
    'secret': os.getenv('MEXC_SECRET'),
    'enableRateLimit': True,
})

def load_entry():
    if os.path.exists(STATE_FILE):
        with open(STATE_FILE,'r') as f:
            return json.load(f).get('entry')
    return None

def save_entry(p):
    with open(STATE_FILE,'w') as f:
        json.dump({'entry': p, 'time': str(datetime.now())}, f)

candles = exchange.fetch_ohlcv(SYMBOL, TIMEFRAME, limit=100)
df = pd.DataFrame(candles, columns=['t','o','h','l','c','v'])
df['ema9'] = df['c'].ewm(span=9).mean()
df['ema21'] = df['c'].ewm(span=21).mean()

last, prev = df.iloc[-1], df.iloc[-2]
price = float(last['c'])
cross_up = prev['ema9'] <= prev['ema21'] and last['ema9'] > last['ema21']
cross_down = prev['ema9'] >= prev['ema21'] and last['ema9'] < last['ema21']

bal = exchange.fetch_balance()
usdt = float(bal.get('USDT',{}).get('free',0) or 0)
doge = float(bal.get('DOGE',{}).get('free',0) or 0)
entry = load_entry()

print(f"{datetime.now()} | Harga: {price:.6f} | USDT: {usdt:.2f} | DOGE: {doge:.4f} | Entry: {entry}")
print(f"EMA9: {last['ema9']:.6f} | EMA21: {last['ema21']:.6f} | Up: {cross_up} | Down: {cross_down}")

# JUAL
if doge * price > 1 and entry:
    if price <= entry * (1 - SL_PCT):
        amt = exchange.amount_to_precision(SYMBOL, doge)
        exchange.create_market_sell_order(SYMBOL, amt)
        save_entry(None)
        print(f"SL 3% JUAL")
    elif cross_down:
        amt = exchange.amount_to_precision(SYMBOL, doge)
        exchange.create_market_sell_order(SYMBOL, amt)
        save_entry(None)
        print(f"TP Crossing JUAL")
# BELI
elif cross_up and usdt > 1:
    cost = round(usdt * BUY_FRAC, 2)
    order = exchange.create_market_buy_order(SYMBOL, cost)
    save_entry(float(order.get('average') or price))
    print(f"BUY {cost}")
else:
    print("HOLD")
