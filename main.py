import os
import ccxt
from datetime import datetime

print("=== antdea M5 EMA 9/21 LIVE ===")
print(f"Waktu cek: {datetime.now()}")

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
    candles = exchange.fetch_ohlcv('DOGE/USDT', '5m', limit=100)
    closes = [c[4] for c in candles]
    ema9 = ema(closes, 9)
    ema21 = ema(closes, 21)

    last_ema9, last_ema21 = ema9[-1], ema21[-1]
    prev_ema9, prev_ema21 = ema9[-2], ema21[-2]

    # CEK HARGA TERAKHIR LANGSUNG DARI TICKER (paling update)
    ticker = exchange.fetch_ticker('DOGE/USDT')
    price = ticker['last']

    balance = exchange.fetch_balance()
    usdt = float(balance.get('USDT',{}.get('free',0)or 0)
    doge = float(balance.get('DOGE',{}.get('free',0)or 0)

    print(f"--- CEK AKTIF ---")
    print(f"Harga DOGE terakhir: {price}")
    print(f"EMA9: {last_ema9} | EMA21: {last_ema21}")
    print(f"Saldo USDT: {usdt} | Saldo DOGE: {doge}")
    print(f"Total asset DOGE kalo dirupiahin USDT: {(doge * price) + usdt:.4f} USDT")

    # GOLDEN CROSS = BUY
    if prev_ema9 <= prev_ema21 and last_ema9 > last_ema21:
        if usdt > 1.1:
            amount = (usdt * 0.95) / price
            print(f"🚀 SIGNAL BUY -> Beli {amount} DOGE @ {price}")
            exchange.create_market_buy_order('DOGE/USDT', amount)
        else:
            print(f"GOLDEN CROSS tapi saldo USDT kurang: {usdt}")

    # DEATH CROSS = SELL
    elif prev_ema9 >= prev_ema21 and last_ema9 < last_ema21:
        if doge > 1:
            print(f"🔻 SIGNAL SELL -> Jual {doge} DOGE @ {price}")
            exchange.create_market_sell_order('DOGE/USDT', doge)
        else:
            print(f"DEATH CROSS tapi saldo DOGE kurang: {doge}")
    else:
        print("No cross, hold")

except Exception as e:
    print(f"Error: {e}")
