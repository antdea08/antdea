import ast
import ccxt
import json
import logging
import os
from datetime import datetime, timezone

import pandas as pd


# =========================================================
# KONFIGURASI
# =========================================================

SYMBOL = "DOGE/USDT"
TIMEFRAME = "5m"

BUY_FRAC = 0.90
SL_PCT = 0.03

MIN_USDT = 1.00
MIN_POSITION_VALUE = 1.00

STATE_FILE = "entry.json"


# =========================================================
# LOGGING
# =========================================================

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s UTC | %(levelname)s | %(message)s",
)


# =========================================================
# API MEXC
# =========================================================

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


# =========================================================
# ENTRY STATE
# =========================================================

def save_entry(entry_price):
    data = {
        "entry": entry_price,
        "time": datetime.now(timezone.utc).isoformat(),
    }

    with open(STATE_FILE, "w", encoding="utf-8") as file:
        json.dump(
            data,
            file,
            indent=2,
            ensure_ascii=False,
        )


def clear_entry():
    save_entry(None)


def load_entry():
    """
    Membaca entry.json.

    Fungsi ini juga memperbaiki otomatis format lama seperti:
    {'entry': None}
    """

    if not os.path.exists(STATE_FILE):
        logging.warning(
            "entry.json belum ada. Membuat file baru."
        )
        save_entry(None)
        return None

    try:
        with open(STATE_FILE, "r", encoding="utf-8") as file:
            raw = file.read().strip()

    except OSError as error:
        raise RuntimeError(
            f"Tidak bisa membaca {STATE_FILE}: {error}"
        )

    if not raw:
        logging.warning(
            "entry.json kosong. Membuat file baru."
        )
        save_entry(None)
        return None

    # Coba baca sebagai JSON normal
    try:
        data = json.loads(raw)

    except json.JSONDecodeError:
        # Recovery untuk format Python lama:
        # {'entry': None}
        try:
            data = ast.literal_eval(raw)

        except Exception as error:
            raise RuntimeError(
                "entry.json rusak dan tidak bisa diperbaiki: "
                f"{error}"
            )

        if not isinstance(data, dict):
            raise RuntimeError(
                "entry.json harus berisi object/dictionary."
            )

        entry = data.get("entry")

        if entry is not None:
            try:
                entry = float(entry)
            except (TypeError, ValueError):
                raise RuntimeError(
                    "Nilai entry di entry.json harus angka atau null."
                )

        # Tulis ulang menjadi JSON valid
        save_entry(entry)

        logging.warning(
            "Format lama entry.json ditemukan. "
            "File sudah diperbaiki otomatis."
        )

        return entry

    if not isinstance(data, dict):
        raise RuntimeError(
            "Format entry.json tidak valid. "
            "Isinya harus object JSON."
        )

    entry = data.get("entry")

    if entry is None:
        return None

    try:
        return float(entry)

    except (TypeError, ValueError):
        raise RuntimeError(
            "Nilai entry di entry.json harus angka atau null."
        )


# =========================================================
# MARKET DATA
# =========================================================

def get_dataframe():
    candles = exchange.fetch_ohlcv(
        SYMBOL,
        timeframe=TIMEFRAME,
        limit=100,
    )

    if len(candles) < 30:
        raise RuntimeError(
            "Data candle tidak cukup."
        )

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

    # Candle terakhir masih berjalan.
    # Buang candle tersebut agar sinyal tidak berubah-ubah.
    df = df.iloc[:-1].copy()

    df["ema9"] = (
        df["close"]
        .ewm(span=9, adjust=False)
        .mean()
    )

    df["ema21"] = (
        df["close"]
        .ewm(span=21, adjust=False)
        .mean()
    )

    return df


def get_signal(df):
    if len(df) < 3:
        raise RuntimeError(
            "Candle selesai tidak cukup untuk membaca sinyal."
        )

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


# =========================================================
# BALANCE
# =========================================================

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


# =========================================================
# MARKET LIMITS
# =========================================================

def get_market_limits():
    market = exchange.market(SYMBOL)
    limits = market.get("limits", {})

    amount_limits = limits.get("amount", {})
    cost_limits = limits.get("cost", {})

    min_amount = float(
        amount_limits.get("min", 0) or 0
    )

    min_cost = float(
        cost_limits.get("min", 0) or 0
    )

    return min_amount, min_cost


def format_amount(amount):
    formatted = exchange.amount_to_precision(
        SYMBOL,
        amount,
    )

    return float(formatted)


# =========================================================
# BUY
# =========================================================

def buy_position(price, usdt_free):
    min_amount, min_cost = get_market_limits()

    cost = usdt_free * BUY_FRAC

    if cost < MIN_USDT:
        logging.warning(
            "Saldo tidak cukup untuk membeli: "
            "%.8f USDT",
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
        "Mengirim order BUY sekitar %.8f USDT",
        cost,
    )

    order = None

    # Cara pertama: order market dengan nilai quote USDT
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
            "BUY quoteOrderQty ditolak MEXC: %s",
            error,
        )

    # Cara kedua: hitung jumlah DOGE jika cara pertama gagal
    if order is None:
        ticker = exchange.fetch_ticker(SYMBOL)
        last_price = float(
            ticker.get("last") or price
        )

        amount = format_amount(
            cost / last_price
        )

        if amount <= 0:
            logging.warning(
                "Jumlah DOGE hasil perhitungan tidak valid."
            )
            return False

        if min_amount and amount < min_amount:
            logging.warning(
                "Jumlah %.8f DOGE di bawah minimum %.8f",
                amount,
                min_amount,
            )
            return False

        try:
            order = exchange.create_market_buy_order(
                SYMBOL,
                amount,
            )

        except Exception as error:
            logging.error(
                "BUY gagal: %s",
                error,
            )
            return False

    average = order.get("average")
    filled = order.get("filled")
    order_cost = order.get("cost")

    if average:
        entry_price = float(average)

    elif filled and order_cost:
        filled_amount = float(filled)

        if filled_amount <= 0:
            entry_price = price
        else:
            entry_price = (
                float(order_cost) / filled_amount
            )

    else:
        entry_price = price

    save_entry(entry_price)

    logging.info(
        "BUY berhasil | Entry: %.8f | Order ID: %s",
        entry_price,
        order.get("id"),
    )

    return True


# =========================================================
# SELL
# =========================================================

def sell_position(doge_free, reason):
    min_amount, min_cost = get_market_limits()

    amount = format_amount(doge_free)

    if amount <= 0:
        logging.warning(
            "Jumlah DOGE tidak valid untuk dijual."
        )
        return False

    if min_amount and amount < min_amount:
        logging.warning(
            "Jumlah DOGE %.8f di bawah minimum %.8f",
            amount,
            min_amount,
        )
        return False

    ticker = exchange.fetch_ticker(SYMBOL)
    price = float(ticker["last"])

    estimated_value = amount * price

    if min_cost and estimated_value < min_cost:
        logging.warning(
            "Nilai jual %.8f di bawah minimum %.8f",
            estimated_value,
            min_cost,
        )
        return False

    try:
        order = exchange.create_market_sell_order(
            SYMBOL,
            amount,
        )

    except Exception as error:
        logging.error(
            "SELL gagal: %s",
            error,
        )
        return False

    clear_entry()

    logging.info(
        "SELL berhasil | Alasan: %s | "
        "Amount: %.8f | Order ID: %s",
        reason,
        amount,
        order.get("id"),
    )

    return True


# =========================================================
# STRATEGI
# =========================================================

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
    has_position = (
        position_value >= MIN_POSITION_VALUE
    )

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

    # Tidak ada saldo yang terbaca.
    if usdt_free <= 0 and doge_free <= 0:
        logging.warning(
            "Saldo USDT dan DOGE sama-sama nol. "
            "Bot berhenti tanpa order."
        )
        return

    # Ada posisi DOGE tetapi entry tidak diketahui.
    if has_position and entry is None:
        logging.error(
            "Ada posisi DOGE tetapi entry tidak ditemukan. "
            "Bot berhenti tanpa order."
        )
        return

    # Tidak ada posisi, tetapi entry lama masih tersimpan.
    if not has_position and entry is not None:
        logging.warning(
            "Tidak ada posisi DOGE. "
            "Entry lama dihapus."
        )
        clear_entry()
        entry = None

    # =====================================================
    # EXIT
    # =====================================================

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

    # =====================================================
    # ENTRY
    # =====================================================

    if not has_position and cross_up:
        buy_position(
            price,
            usdt_free,
        )
        return

    logging.info(
        "HOLD - tidak ada crossover EMA yang valid."
    )


# =========================================================
# START
# =========================================================

if __name__ == "__main__":
    try:
        main()

    except Exception:
        logging.exception(
            "Bot gagal dijalankan."
        )
        raise
