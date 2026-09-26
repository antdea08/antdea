import ccxt
import os
import json
import logging
from datetime import datetime, timezone

import pandas as pd


# =========================
# KONFIGURASI
# =========================

SYMBOL = "DOGE/USDT"
TIMEFRAME = "5m"

BUY_FRAC = 0.90
SL_PCT = 0.03

MIN_USDT = 1.00
MIN_POSITION_VALUE = 1.00

STATE_FILE = "entry.json"


# =========================
# LOGGING
# =========================

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s UTC | %(levelname)s | %(message)s",
)


# =========================
# API MEXC
# =========================

api_key = os.getenv("MEXC_API_KEY")
secret = os.getenv("MEXC_SECRET")

if not api_key or not secret:
    raise RuntimeError(
        "MEXC_API_KEY atau MEXC_SECRET belum tersedia."
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
# FILE ENTRY
# =========================

def load_entry():
    if not os.path.exists(STATE_FILE):
        return None

    try:
        with open(STATE_FILE, "r", encoding="utf-8") as file:
            raw = file.read().strip()

        if not raw:
            raise ValueError("entry.json kosong")

        data = json.loads(raw)
        entry = data.get("entry")

        if entry is None:
            return None

        return float(entry)

    except Exception as error:
        # Jangan otomatis reset file rusak.
        # Lebih aman berhenti daripada salah menghitung stop-loss.
        raise RuntimeError(
            f"entry.json rusak atau tidak valid: {error}"
        )


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
        columns=[
            "timestamp",
            "open",
            "high",
            "low",
            "close",
            "volume",
        ],
    )

    # Candle terakhir masih bisa berubah.
    # Hanya gunakan candle yang sudah selesai.
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
# BALANCE
# =========================

def get_balances():
    balance = exchange.fetch_balance()

    free_balances = balance.get("free", {})

    usdt_free = float(
        free_balances.get("USDT", 0) or 0
    )

    doge_free = float(
        free_balances.get("DOGE", 0) or 0
    )

    logging.info(
        "Saldo Spot | USDT: %.8f | DOGE: %.8f",
        usdt_free,
        doge_free,
    )

    return usdt_free, doge_free


def get_market_limits():
    market = exchange.market(SYMBOL)

    limits = market.get("limits", {})

    min_amount = float(
        limits.get("amount", {}).get("min", 0) or 0
    )

    min_cost = float(
        limits.get("cost", {}).get("min", 0) or 0
    )

    return min_amount, min_cost


def format_amount(amount):
    return float(
        exchange.amount_to_precision(SYMBOL, amount)
    )


# =========================
# ORDER
# =========================

def buy_position(price, usdt_free):
    min_amount, min_cost = get_market_limits()

    cost = usdt_free * BUY_FRAC

    if cost < MIN_USDT:
        logging.warning(
            "Saldo tidak cukup untuk membeli: %.8f USDT",
            cost,
        )
        return False

    if min_cost and cost < min_cost:
        logging.warning(
            "Nilai order %.8f di bawah minimum %.8f",
            cost,
            min_cost,
        )
        return False

    logging.info(
        "Mengirim BUY market sekitar %.8f USDT",
        cost,
    )

    try:
        order = exchange.create_order(
            SYMBOL,
            "market",
            "buy",
            None,
            None,
            {
                "quoteOrderQty": cost,
            },
        )

    except Exception as error:
        logging.warning(
            "quoteOrderQty ditolak MEXC: %s",
            error,
        )

        amount = format_amount(cost / price)

        if min_amount and amount < min_amount:
            logging.warning(
                "Jumlah %.8f di bawah minimum %.8f",
                amount,
                min_amount,
            )
            return False

        order = exchange.create_market_buy_order(
            SYMBOL,
            amount,
        )

    average = order.get("average")
    filled = order.get("filled")
    order_cost = order.get("cost")

    if average:
        entry_price = float(average)
    elif filled and order_cost and float(filled) > 0:
        entry_price = float(order_cost) / float(filled)
    else:
        entry_price = price

    save_entry(entry_price)

    logging.info(
        "BUY berhasil | Entry: %.8f | Order ID: %s",
        entry_price,
        order.get("id"),
    )

    return True


def sell_position(doge_free, reason):
    min_amount, min_cost = get_market_limits()

    amount = format_amount(doge_free)

    if min_amount and amount < min_amount:
        logging.warning(
            "Jumlah DOGE terlalu kecil: %.8f",
            amount,
        )
        return False

    ticker = exchange.fetch_ticker(SYMBOL)
    price = float(ticker["last"])

    estimated_value = amount * price

    if min_cost and estimated_value < min_cost:
        logging.warning(
            "Nilai jual terlalu kecil: %.8f",
            estimated_value,
        )
        return False

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

    return True


# =========================
# LOGIKA BOT
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
        "Harga: %.8f | EMA9: %.8f | EMA21: %.8f",
        price,
        ema9,
        ema21,
    )

    logging.info(
        "CrossUp: %s | CrossDown: %s | Entry: %s",
        cross_up,
        cross_down,
        entry,
    )

    # Saldo nol bisa berarti API salah akun atau dana bukan di Spot.
    if usdt_free == 0 and doge_free == 0:
        logging.error(
            "Saldo USDT dan DOGE sama-sama nol. "
            "Bot berhenti tanpa order."
        )
        return

    # Ada DOGE tetapi entry tidak diketahui.
    # Jangan jual karena stop-loss tidak bisa dihitung dengan aman.
    if has_position and entry is None:
        logging.error(
            "Ada posisi DOGE tetapi entry.json tidak punya entry. "
            "Bot berhenti tanpa order."
        )
        return

    # =========================
    # EXIT
    # =========================

    if has_position and entry is not None:
        stop_price = entry * (1 - SL_PCT)

        if price <= stop_price:
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
            stop_price,
        )
        return

    # =========================
    # ENTRY
    # =========================

    if not has_position and cross_up:
        buy_position(price, usdt_free)
        return

    logging.info(
        "HOLD - tidak ada crossover EMA yang valid."
    )


if __name__ == "__main__":
    try:
        main()
    except Exception:
        logging.exception("Bot gagal dijalankan.")
        raise
