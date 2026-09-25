ShielZ07:
import ccxt, os, time, json, logging
import pandas as pd
from datetime import datetime

# =================== KONFIGURASI ===================
SYMBOL     = 'DOGE/USDT'
TIMEFRAME  = '5m'
LIMIT      = 100
BUY_FRAC   = 0.95
SL_PCT     = 0.03
STATE_FILE = 'state.json'
DRY_RUN    = True
DEFAULT_MIN_COST = 1.1
MIN_POS_BUF      = 0.000001
# ===================================================

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(message)s')
log = logging.getLogger('doge-bot')

exchange = ccxt.mexc({
    'apiKey': os.getenv('MEXC_API_KEY'),
    'secret': os.getenv('MEXC_SECRET'),
    'enableRateLimit': True,
})

def load_state():
    try:
        if os.path.exists(STATE_FILE):
            with open(STATE_FILE, 'r') as f:
                return json.load(f).get('entry')
    except: pass
    return None

def save_state(entry):
    try:
        with open(STATE_FILE, 'w') as f:
            json.dump({'entry': entry, 'time': str(datetime.now())}, f)
    except Exception as e:
        log.error(f"Gagal save state: {e}")

def place_order(side, symbol, amount, price, dry=DRY_RUN):
    if dry:
        log.info(f"[DRY_RUN] {side.upper()} {amount} {symbol} @ {price}")
        return {'average': price}
    try:
        if side == 'buy':
            return exchange.create_market_buy_order(symbol, amount)
        else:
            return exchange.create_market_sell_order(symbol, amount)
    except Exception as e:
        log.error(f"Order {side} GAGAL: {type(e).name}: {e}")
        return None

def main():
    try:
        candles = exchange.fetch_ohlcv(SYMBOL, TIMEFRAME, limit=LIMIT)
        df = pd.DataFrame(candles, columns=['t','o','h','l','c','v'])
        df['ema9']  = df['c'].ewm(span=9, adjust=False).mean()
        df['ema21'] = df['c'].ewm(span=21, adjust=False).mean()

        last, prev = df.iloc[-1], df.iloc[-2]
        price = float(last['c'])
        e9, e21 = float(last['ema9']), float(last['ema21'])
        pe9, pe21 = float(prev['ema9']), float(prev['ema21'])

        cross_up = pe9 <= pe21 and e9 > e21
        cross_down = pe9 >= pe21 and e9 < e21

        balance = exchange.fetch_balance()
        usdt = float(balance.get('USDT', {}).get('free', 0) or 0)
        doge = float(balance.get('DOGE', {}).get('free', 0) or 0)
        doge_value = doge * price

        market = exchange.market(SYMBOL)
        min_cost = market['limits']['cost']['min'] or DEFAULT_MIN_COST
        min_qty = market['limits']['amount']['min'] or 0

        entry = load_state()
        pnl = (price - entry) / entry if entry else 0

        log.info(f"--- CEK AKTIF --- Harga:{price:.6f} EMA9:{e9:.6f} EMA21:{e21:.6f} CrossUp:{cross_up} CrossDown:{cross_down}")
        log.info(f"Saldo USDT:{usdt:.2f} DOGE:{doge:.4f} Entry:{entry} PnL:{pnl*100:+.2f}%")

        if doge_value > 1 and entry is not None:
            if price <= entry * (1 - SL_PCT):
                log.info(f"🔻 SL 3% dipicu ({pnl*100:+.2f}%)")
                amount = exchange.amount_to_precision(SYMBOL, max(doge - MIN_POS_BUF, 0))
                if place_order('sell', SYMBOL, amount, price):
                    save_state(None)
            elif cross_down:
                log.info(f"↩ TP CROSSING dipicu ({pnl*100:+.2f}%)")
                amount = exchange.amount_to_precision(SYMBOL, max(doge - MIN_POS_BUF, 0))
                if place_order('sell', SYMBOL, amount, price):
                    save_state(None)
            else:
                log.info("HOLD - nunggu SL 3% / TP Crossing")
        else:
            if entry is not None and doge <= min_qty:
                log.info("State kebawa entry tapi DOGE kosong - reset")
                save_state(None)
            if cross_up:
                if usdt >= min_cost:
                    cost = round(usdt * BUY_FRAC, 2)

if cost >= min_cost:
                        order = place_order('buy', SYMBOL, cost, price)
                        if order:
                            fill_price = float(order.get('average') or price)
                            save_state(fill_price)
                            log.info(f"🚀 BUY {cost} USDT @ {fill_price}")
                else:
                    log.warning(f"USDT {usdt:.2f} < min_cost {min_cost} - skip")
            else:
                log.info("HOLD - nunggu cross_up")

    except Exception as e:
        log.error(f"GAGAL: {type(e).name}: {e}")

if name == 'main':
    main()
