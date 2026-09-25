import ccxt, os, pandas as pd

exchange = ccxt.mexc({
    'apiKey': os.getenv('MEXC_API_KEY'),
    'secret': os.getenv('MEXC_SECRET'),
})

# ambil 100 candle biar EMA akurat kayak TradingView
candles = exchange.fetch_ohlcv('DOGE/USDT', '5m', limit=100)
df = pd.DataFrame(candles, columns=['t','o','h','l','c','v'])

df['ema9'] = df['c'].ewm(span=9, adjust=False).mean()
df['ema21'] = df['c'].ewm(span=21, adjust=False).mean()

last = df.iloc[-1]
prev = df.iloc[-2]

price = last['c']
last_ema9 = last['ema9']
last_ema21 = last['ema21']
prev_ema9 = prev['ema9']
prev_ema21 = prev['ema21']

balance = exchange.fetch_balance()
usdt = float(balance.get('USDT', {}).get('free', 0) or 0)
doge = float(balance.get('DOGE', {}).get('free', 0) or 0)

print(f"--- CEK AKTIF ---")
print(f"Harga: {price}")
print(f"EMA9: {last_ema9} | EMA21: {last_ema21}")
print(f"PREV EMA9: {prev_ema9} | PREV EMA21: {prev_ema21}")
print(f"Saldo USDT: {usdt} | DOGE: {doge}")

# LOGIC ANTI KETINGGALAN
if last_ema9 > last_ema21 and doge * price < 1:
    if usdt > 1.1:
        amount = (usdt * 0.95) / price
        print(f"🚀 SIGNAL BUY -> Beli {amount} DOGE @ {price}")
        exchange.create_market_buy_order('DOGE/USDT', amount)
    else:
        print("USDT kurang dari $1.1")
elif last_ema9 < last_ema21 and doge * price > 1:
    print(f"🔻 SIGNAL SELL -> Jual {doge} DOGE")
    exchange.create_market_sell_order('DOGE/USDT', doge)
else:
    print(f"HOLD - Posisi: {'PUNYA DOGE' if doge*price>1 else 'PUNYA USDT'}")
