import ccxt, os, time, json, logging
import pandas as pd
from datetime import datetime

# ================== KONFIGURASI ==================
SYMBOL        = 'DOGE/USDT'
TIMEFRAME     = '5m'
LIMIT         = 100
BUY_FRAC      = 0.95            # % USDT buat beli
SL_PCT        = 0.08            # stop-loss 8% dari entry
TP_PCT        = 0.15            # take-profit +15% dari entry
STATE_FILE    = 'state.json'    # nyimpen entry price
DRY_RUN       = True            # True = simulasi, nggak eksekusi
DEFAULT_MIN_COST = 1.1
MIN_POS_BUF   = 0.000001
# =================================================

logging.basicConfig(level=logging.INFO, format='%(asctime)s %(levelname)s %(message)s')
log = logging.getLogger('doge-bot')

exchange = ccxt.mexc({
    'apiKey': os.getenv('MEXC_API_KEY'),
    'secret': os.getenv('MEXC_SECRET'),
    'enableRateLimit': True,
})

def load_state():
    if os.path.exists(STATE_FILE):
        with open(STATE_FILE) as f:
            return json.load(f)
    return {}

def save_state(entry_price=None):
    with open(STATE_FILE, 'w') as f:
        json.dump({'entry_price': entry_price}, f)

def place_order(kind, symbol, amount, price=None):
    if DRY_RUN:
        log.info(f"[DRY-RUN] {kind.upper()} {amount} {symbol.split('/')[0]} @ {price or 'MARKET'}")
        return {'id': 'DRY'}
    try:
        if kind == 'buy':
            order = exchange.create_market_buy_order(symbol, amount)
        else:
            order = exchange.create_market_sell_order(symbol, amount)
        log.info(f"ORDER OK: {kind} {order.get('id')} | filled={order.get('filled')} | avg={order.get('average')}")
        return order
    except Exception as e:
        log.error(f"ORDER GAGAL ({kind}): {type(e).__name__}: {e}")
        return None

def main():
    try:
        # ---- data candle + EMA ----
        candles = exchange.fetch_ohlcv(SYMBOL, TIMEFRAME, limit=LIMIT)
        df = pd.DataFrame(candles, columns=['t','o','h','l','c','v'])
        df['ema9']  = df['c'].ewm(span=9,  adjust=False).mean()
        df['ema21'] = df['c'].ewm(span=21, adjust=False).mean()

        last, prev = df.iloc[-1], df.iloc[-2]
        price = float(last['c'])   # harga candle DKK terakhir (fallback)
        e9, e21 = float(last['ema9']), float(last['ema21'])
        pe9, pe21 = float(prev['ema9']), float(prev['ema21'])

        # ---- harga live (biar SL/TP pakai harga sekarang, bukan bubble harga candle) ----
        try:
            ticker = exchange.fetch_ticker(SYMBOL)
            price = float(ticker['last'])
        except Exception:
            pass  # kalau gagal, pakai close candle

        # cek data fresh
        age = time.time() - (df.iloc[-1]['t'] / 1000)
        if age > 2 * 60 * int(TIMEFRAME[:-1]):
            log.warning(f"Data basi ({age/60:.0f}m) - skip.")
            return

        # ---- sinyal ----
        cross_up   = pe9 <= pe21 and e9 > e21
        cross_down = pe9 >= pe21 and e9 < e21

        # ---- saldo & limits ----
        bal = exchange.fetch_balance()
        usdt = float(bal.get('USDT', {}).get('free', 0) or 0)
        doge = float(bal.get('DOGE', {}).get('free', 0) or 0)

        m = exchange.market(SYMBOL)
        min_cost = m['limits']['cost']['min'] or DEFAULT_MIN_COST
        min_qty  = m['limits']['amount']['min'] or 0
        step     = m['precision']['amount'] or 0.00000001

        state = load_state()
        entry = state.get('entry_price')

        # status posisi: simpan entry di file + masih pegang DOGE
        in_position = entry is not None and doge > min_qty

        log.info(f"Price={price:.8f} | EMA9={e9:.8f} | EMA21={e21:.8f} | entry={entry}")
        log.info(f"USDT={usdt:.2f} | DOGE={doge:.8f} | in_position={in_position}")
        log.info(f"CrossUP={cross_up} | CrossDOWN={cross_down}")

        # ============ LOGIKA ============
        if in_position:
            pnl = (price / entry) - 1
            log.info(f"P&L saat ini: {pnl*100:+.2f}% (SL=-{SL_PCT*100:.0f}% | TP=+{TP_PCT*100:.0f}%)")

            # 1. STOP-LOSS dulu (darurat, prioritas tertinggi)
            if price <= entry * (1 - SL_PCT):
                log.info(f"🔻 STOP-LOSS dipicu ({pnl*100:+.2f}%)")
                if place_order('sell', SYMBOL, exchange.amount_to_precision(SYMBOL, max(doge - MIN_POS_BUF, 0)), price):
                    save_state(None)

            # 2. TAKE-PROFIT
            elif price >= entry * (1 + TP_PCT):
                log.info(f"🚀 TAKE-PROFIT dipicu ({pnl*100:+.2f}%)")
                if place_order('sell', SYMBOL, exchange.amount_to_precision(SYMBOL, max(doge - MIN_POS_BUF, 0)), price):
                    save_state(None)

            # 3. Exit EMA normal (penutupan sane)
            elif cross_down:
                log.info(f"↩ EXIT EMA crossover ({pnl*100:+.2f}%)")
                if place_order('sell', SYMBOL, exchange.amount_to_precision(SYMBOL, max(doge - MIN_POS_BUF, 0)), price):
                    save_state(None)

            else:
                log.info("HOLD - posisi aman, nunggu SL/TP/exit")

        else:
            # di luar posisi: SL/TP nggak relevan, cuma cari sinyal beli
            if entry is not None and doge <= min_qty:
                log.info("State kebawa entry tapi saldo DOGE kosong - reset state.")
                save_state(None)

            if cross_up:
                if usdt >= min_cost:
                    cost = round(usdt * BUY_FRAC, 2)
                    if cost >= min_cost:
                        order = place_order('buy', SYMBOL, cost, price)
                        if order:
                            # simpan entry price (pakai harga rata-rata isi kalo ada)
                            fill_price = float(order.get('average') or price)
                            save_state(fill_price)
                            log.info(f"BUY {cost} USDT DOGE | entry={fill_price}")
                else:
                    log.warning(f"USDT ({usdt:.2f}) < min_cost ({min_cost}) - skip")
            else:
                log.info("HOLD - nunggu crossover beli")

    except Exception as e:
        log.error(f"GAGAL: {type(e).__name__}: {e}")

if __name__ == '__main__':
    main()
