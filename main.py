import os
import ccxt

print("=== antdea M5 EMA 9/21 FIX ===")

API_KEY = os.getenv('MEXC_API_KEY')
API_SECRET = os.getenv('MEXC_SECRET')

exchange = ccxt.mexc({
    'apiKey': API_KEY,
    'secret': API_SECRET,
})

def ema(data, period):
    k = 2 / (period + 1)
    ema_vals = [sum(data[:period]) / period]
    for price in data[period:]:
        ema_vals.append(price * k + ema_vals[-1] * (1 - k))
    return ema_vals

try:
    # Candle M5
    candles = exchange.fetch_ohlcv('DOGE/USDT', '5m', limit=100)
    closes = [c[4] for c in candles]

    ema9 = ema(closes, 9)
    ema21 = ema(closes, 21)

    last_ema9 = ema9[-1]
    last_ema21 = ema21[-1]
    prev_ema9 = ema9[-2]
    prev_ema21 = ema21[-2]

    print(f"EMA9: {last_ema9} | EMA21: {last_ema21}")

    balance = exchange.fetch_balance()
    usdt = balance['USDT']['free'] if 'USDT' in balance else 0
    doge = balance['DOGE']['free'] if 'DOGE' in balance else 0

    # Golden cross = BUY
    if prev_ema9 <= prev_ema21 and last_ema9 > last_ema21:
        if usdt > 1:
            print(f"BUY signal! USDT: {usdt}")
            # exchange.create_market_buy_order('DOGE/USDT', usdt * 0.9 / closes[-1])
        else:
            print("BUY signal tapi USDT kurang")

    # Death cross = SELL
    elif prev_ema9 >= prev_ema21 and last_ema9 < last_ema21:
        if doge > 1:
            print(f"SELL signal! DOGE: {doge}")
            # exchange.create_market_sell_order('DOGE/USDT', doge)
        else:
            print("SELL signal tapi DOGE kurang")

    else:
        print("No cross, hold")

except Exception as e:
    print(f"Error: {e}")
