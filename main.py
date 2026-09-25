import ccxt, os
import pandas as pd

exchange = ccxt.mexc({
    'apiKey': os.getenv('MEXC_API_KEY'),
    'secret': os.getenv('MEXC_SECRET'),
    'enableRateLimit': True,          # jaga-jaga biar nggak kena rate limit
})

symbol = 'DOGE/USDT'

try:
    candles = exchange.fetch_ohlcv(symbol, '5m', limit=100)
    df = pd.DataFrame(candles, columns=['t','o','h','l','c','v'])
    df['ema9']  = df['c'].ewm(span=9,  adjust=False).mean()
    df['ema21'] = df['c'].ewm(span=21, adjust=False).mean()

    last, prev = df.iloc[-1], df.iloc[-2]
    price = last['c']
    e9, e21, pe9, pe21 = last['ema9'], last['ema21'], prev['ema9'], prev['ema21']

    balance = exchange.fetch_balance()
    usdt = float(balance.get('USDT', {}).get('free', 0) or 0)
    doge = float(balance.get('DOGE', {}).get('free', 0) or 0)
    doge_value = doge * price

    # ambil presisi & batas minimal dari market info
    market = exchange.market(symbol)
    min_cost = market['limits']['cost']['min'] or 1.1   # minimal USDT per order

    print(f"--- CEK AKTIF ---")
    print(f"Harga: {price:.6f} | EMA9: {e9:.6f} | EMA21: {e21:.6f}")
    print(f"Saldo USDT: {usdt:.2f} | DOGE: {doge:.4f} | Nilai DOGE: {doge_value:.2f}")

    if e9 > e21 and doge_value < 1:
        if usdt >= min_cost:
            cost = round(usdt * 0.95, 2)
            print(f"🚀 BUY -> {cost} USDT DOGE @ {price:.6f}")
            exchange.create_market_buy_order(symbol, cost)   # cost, bukan koin
        else:
            print(f"USDT ({usdt:.2f}) di bawah minimal {min_cost}")

    elif e9 < e21 and doge_value > 1:
        amount = exchange.amount_to_precision(symbol, doge)  # sesuai step size
        print(f"🔻 SELL -> Jual {amount} DOGE")
        exchange.create_market_sell_order(symbol, amount)

    else:
        print(f"HOLD - Posisi: {'PUNYA DOGE' if doge_value > 1 else 'PUNYA USDT'}")

except Exception as e:
    print(f"GAGAL: {type(e).name}: {e}")
