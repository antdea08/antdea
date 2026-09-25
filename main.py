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
    candles = exchange.fetch_ohlcv('DOGE/USDT', '5m', limit=50)
    close = [c[4] for c in candles]
    ema9 = ema(close, 9)
    ema21 = ema(close, 21)
    ema9 = ema9[-len(ema21):]

    print(f"Harga: {close[-1]} | EMA9: {ema9[-1]:.6f} | EMA21: {ema21[-1]:.6f}")

    bal = exchange.fetch_balance()
    usdt = bal.get('USDT', {}).get('free', 0) or 0
    doge = bal.get('DOGE', {}).get('free', 0) or 0
    print(f"USDT: {usdt} | DOGE: {doge}")

    buy_signal = ema9[-1] > ema21[-1] and ema9[-2] <= ema21[-2]
    sell_signal = ema9[-1] < ema21[-1] and ema9[-2] >= ema21[-2]

    # Cek -3%
    stop_loss = False
    try:
        trades = exchange.fetch_my_trades('DOGE/USDT', limit=1)
        if trades and doge > 1:
            last = trades[0]['price']
            pct = (close[-1] - last) / last * 100
            print(f"Last buy {last} | {pct:.2f}%")
            if pct <= -3:
                stop_loss = True
    except Exception as e:
        print(f"Skip cek rugi: {e}")

    if buy_signal and float(usdt) >= 1.1:
        amt = 1.1 / close[-1]
        print(f"BUY SIGNAL! {amt}")
        exchange.create_market_buy_order('DOGE/USDT', amt)
        print("REAL BUY EKSEKUSI!")
    elif (sell_signal or stop_loss) and float(doge) > 1:
        print(f"SELL SIGNAL! Reason: {'Cross' if sell_signal else '-3%'}")
        exchange.create_market_sell_order('DOGE/USDT', doge)
        print("REAL SELL EKSEKUSI!")
    else:
        print("No signal - standby")

except Exception as e:
    print(f"ERROR UTAMA: {e}")

print("=== DONE ===")
