import ccxt
import os
import json
import time
import logging
from datetime import datetime, timezone

import pandas as pd


# =========================
# KONFIGURASI
# =========================

SYMBOL = "DOGE/USDT"
TIMEFRAME = "5m"

BUY_FRAC = 0.90          # Pakai 90% saldo USDT
SL_PCT = 0.03            # Stop-loss 3%
MIN_USDT = 1.00           # Jangan trading jika saldo kurang dari ini
MIN_POSITION_VALUE = 1.00 # Nilai DOGE minimum agar dianggap posisi

STATE_FILE = "entry.json"


# =========================
# LOGGING
# =========================

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s UTC | %(levelname)s | %(message)s",
)


# =========================
# EXCHANGE
# =========================

api_key = os.getenv("MEXC_API_KEY")
secret = os.getenv("MEXC_SECRET")

if not api_key or not secret:
    raise RuntimeError(
        "MEXC_API_KEY atau MEXC_SECRET belum tersedia di environment."
    )

exchange = ccxt.mexc({
    "apiKey": api_key,
    "secret": secret,
    "enableRateLimit": True,
    "options": {
        "defaultType": "spot",
    },
})


# =========================
# STATE ENTRY
# =========================

def load_entry():
    if not os.path.exists(STATE_FILE):
        return None

    try:
        with open(STATE_FILE, "r", encoding="utf-8") as file:
            data = json.load(file)

        entry = data.get("entry")

        if entry is None:
            return None

        return float(entry)

    except Exception as error:
        logging.warning("Gagal membaca entry.json: %s", error)
        return None


def save_entry(entry_price):
    data = {
        "entry": entry_price,
        "time": datetime.now(timezone.utc).isoformat(),
    }

    with open(STATE_FILE, "w", encoding="utf-8") as file:
        json.dump(data, file, indent=2)


def clear_entry():
    save_entry(None)


# =========================
# DATA MARKET
# =========================

def get_dataframe():
    candles = exchange.fetch_ohlcv(
        SYMBOL,
        timeframe=TIMEFRAME,
        limit=100,
    )

    if len(candles) < 30:
        raise RuntimeError("Data candle tidak cukup.")

    df = pd.DataFrame(
        candles,
        columns=["timestamp", "open", "high", "low", "close", "volume"],
    )

    # Candle terakhir biasanya masih berjalan.
    # Buang candle terakhir agar sinyal hanya dari candle yang sudah selesai.
    df = df.iloc[:-1].copy()

    df["ema9"] = df["close"].ewm(
        span=9,
        adjust=False,
    ).mean()

    df["ema21"] = df["close"].ewm(
        span=21,
        adjust=False,
    ).mean()

    return df


def get_signal(df):
    previous = df.iloc[-2]
    latest = df.iloc[-1]

    cross_up = (
        previous["ema9"] <= previous["ema21"]
        and latest["ema9"] > latest["ema21"]
    )

    cross_down = (
        previous["ema9"] >= previous["ema21"]
        and latest["ema9"] < latest["ema21"]
    )

    return latest, cross_up, cross_down


# =========================
# BALANCE DAN ORDER
# =========================

def get_balances():
    balance = exchange.fetch_balance()

    usdt_free = float(
        balance.get("USDT", {}).get("free", 0) or 0
    )

    doge_free = float(
        balance.get("DOGE", {}).get("free", 0) or 0
    )

    return usdt_free, doge_free


def get_minimums():
    market = exchange.market(SYMBOL)

    limits = market.get("limits", {})

    min_amount = float(
        limits.get("amount", {}).get("min", 0) or 0
    )

    min_cost = float(
        limits.get("cost", {}).get("min", 0) or 0
    )

    return min_amount, min_cost


def safe_amount(amount):
    amount = float(amount)
    return float(exchange.amount_to_precision(SYMBOL, amount))


def get_order_entry(order, fallback_price):
    average = order.get("average")

    if average:
        return float(average)

    filled = order.get("filled")
    cost = order.get("cost")

    if filled and cost and float(filled) > 0:
        return float(cost) / float(filled)

    return float(fallback_price)


def buy_position(price, usdt_free):
    min_amount, min_cost = get_minimums()

    available_cost = usdt_free * BUY_FRAC

    if available_cost < MIN_USDT:
        logging.info(
            "Saldo USDT terlalu kecil: %.4f USDT",
            available_cost,
        )
        return None

    if min_cost and available_cost < min_cost:
        logging.info(
            "Nilai order %.4f lebih kecil dari minimum cost %.4f",
            available_cost,
            min_cost,
        )
        return None

    logging.info(
        "Membeli DOGE dengan sekitar %.4f USDT",
        available_cost,
    )

    # Untuk market buy spot, sebagian exchange menerima quoteOrderQty.
    # Jika MEXC menolak format ini, gunakan jumlah DOGE seperti fallback.
    try:
        order = exchange.create_order(
            SYMBOL,
            "market",
            "buy",
            None,
            None,
            {
                "quoteOrderQty": available_cost,
            },
        )

    except Exception as error:
        logging.warning(
            "Format quoteOrderQty ditolak, mencoba amount DOGE: %s",
            error,
        )

        amount = safe_amount(available_cost / price)

        if min_amount and amount < min_amount:
            logging.error(
                "Amount %.8f lebih kecil dari minimum amount %.8f",
                amount,
                min_amount,
            )
            return None

        order = exchange.create_market_buy_order(
            SYMBOL,
            amount,
        )

    entry_price = get_order_entry(order, price)
    save_entry(entry_price)

    logging.info(
        "BUY berhasil | Entry: %.8f | Order ID: %s",
        entry_price,
        order.get("id"),
    )

    return order


def sell_position(doge_free, reason):
    min_amount, min_cost = get_minimums()

    amount = safe_amount(doge_free)

    if min_amount and amount < min_amount:
        logging.warning(
            "DOGE %.8f lebih kecil dari minimum amount %.8f",
            amount,
            min_amount,
        )
        return None

    ticker = exchange.fetch_ticker(SYMBOL)
    last_price = float(ticker["last"])
    estimated_cost = amount * last_price

    if min_cost and estimated_cost < min_cost:
        logging.warning(
            "Nilai jual %.8f lebih kecil dari minimum cost %.8f",
            estimated_cost,
            min_cost,
        )
        return None

    order = exchange.create_market_sell_order(
        SYMBOL,
        amount,
    )

    clear_entry()

    logging.info(
        "SELL berhasil | Alasan: %s | Amount: %.8f | Order ID: %s",
        reason,
        amount,
        order.get("id"),
    )

    return order


# =========================
# STRATEGI UTAMA
# =========================

def main():
    exchange.load_markets()

    df = get_dataframe()
    latest, cross_up, cross_down = get_signal(df)

    price = float(latest["close"])
    ema9 = float(latest["ema9"])
    ema21 = float(latest["ema21"])

    usdt_free, doge_free = get_balances()
    entry = load_entry()

    position_value = doge_free * price
    has_position = position_value >= MIN_POSITION_VALUE

    logging.info(
        "Harga: %.8f | USDT: %.4f | DOGE: %.8f | Entry: %s",
        price,
        usdt_free,
        doge_free,
        entry,
    )

    logging.info(
        "EMA9: %.8f | EMA21: %.8f | CrossUp: %s | CrossDown: %s",
        ema9,
        ema21,
        cross_up,
        cross_down,
    )

    # Jika punya DOGE tetapi entry.json hilang,
    # jangan menjalankan stop-loss berdasarkan entry palsu.
    if has_position and entry is None:
        logging.warning(
            "Ada posisi DOGE tetapi entry.json kosong. "
            "Bot tidak menjual dengan stop-loss sampai entry dipulihkan."
        )

    # =========================
    # EXIT
    # =========================

    if has_position and entry is not None:
        stop_loss_price = entry * (1 - SL_PCT)

        if price <= stop_loss_price:
            sell_position(
                doge_free,
                f"stop-loss {SL_PCT * 100:.1f}%",
            )
            return

        if cross_down:
            sell_position(
                doge_free,
                "EMA9 cross-down EMA21",
            )
            return

        logging.info(
            "HOLD posisi | Stop-loss: %.8f",
            stop_loss_price,
        )
        return

    # =========================
    # ENTRY
    # =========================

    if not has_position and cross_up:
        buy_position(price, usdt_free)
        return

    logging.info("HOLD - tidak ada sinyal trading.")


if __name__ == "__main__":
    try:
        main()
    except Exception:
        logging.exception("Bot gagal dijalankan.")
        raise
