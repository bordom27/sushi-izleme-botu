"""
COKLU VARLIK BACKTEST - "45 varlikta da isler mi?" sorusunu gercekten test eder
================================================================================
genel_izleme_bulut.py'nin taradigi HER varligi (Binance top-N kripto + ABD/BIST
hisseleri) tek tek gecmis veri uzerinde backtest eder. Amac: "bu strateji
sadece SUSHI'de mi isliyor, yoksa genelde de bir seyler yakaliyor mu" sorusuna
VARSAYIMLA degil, GERCEK SONUCLARLA cevap vermek.

Ciktida her varlik icin: islem sayisi, kazanma orani, getiri%, max drawdown.
Sonuclar getiriye gore siralanir ve 'coklu_varlik_sonuclari.csv'ye kaydedilir.

Bu sonuca gore genel_izleme_bulut.py'deki CRYPTO/US_STOCKS/BIST_STOCKS
listelerini SADECE burada pozitif ve yeterli islem sayisina sahip ciktilarla
sinirlamani oneririm - boylece "doğrulanmamis varsayim" riski "gecmis veride
olculmus performans"a doner (yine de gelecegin garantisi degildir).

Gerekli kutuphaneler: pip install pandas numpy requests
"""

import os
import sys
import time
import numpy as np
import pandas as pd
import requests

# Windows'ta bazi konsol kodlamalari (orn. Turkce cp1254) bazi karakterleri
# yazdirirken hata verebiliyor. Bunu onlemek icin ciktiyi UTF-8'e zorluyoruz.
sys.stdout.reconfigure(encoding="utf-8", errors="replace")
sys.stderr.reconfigure(encoding="utf-8", errors="replace")


def send_telegram(mesaj: str):
    """GitHub Actions'ta otomatik calistiginda ozet sonucu Telegram'a gonderir.
    Yerel bilgisayarda TELEGRAM_BOT_TOKEN/CHAT_ID tanimli degilse sessizce atlar."""
    token = os.environ.get("TELEGRAM_BOT_TOKEN")
    chat_id = os.environ.get("TELEGRAM_CHAT_ID")
    if not token or not chat_id:
        return
    url = f"https://api.telegram.org/bot{token}/sendMessage"
    try:
        if len(mesaj) > 3800:
            mesaj = mesaj[:3800] + "\n... (devami kirpildi, tam liste CSV'de)"
        resp = requests.post(url, data={"chat_id": chat_id, "text": mesaj}, timeout=15)
        if not resp.ok:
            print(f"Telegram gonderim hatasi: {resp.status_code} {resp.text}")
    except Exception as exc:
        print(f"Telegram gonderim hatasi: {exc}")

CONFIG = {
    "CRYPTO_TOP_N": 80,
    "CRYPTO_INTERVAL": "4h",
    "CRYPTO_LOOKBACK_DAYS": 365,

    "US_STOCKS": [
        "AAPL", "MSFT", "GOOGL", "AMZN", "NVDA", "META", "TSLA", "AVGO",
        "JPM", "V", "MA", "UNH", "HD", "PG", "COST", "NFLX", "AMD", "ADBE",
        "CRM", "ORCL", "INTC", "CSCO", "PEP", "KO", "MCD", "NKE", "DIS",
        "BA", "CAT", "GE", "IBM", "QCOM", "TXN", "HON", "UPS", "LOW",
        "SBUX", "GS", "MS", "BLK", "PYPL", "UBER", "ABNB", "SHOP", "SQ",
        "PLTR", "COIN", "SNOW", "CRWD", "PANW",
        "WMT", "XOM", "CVX", "PFE", "MRK", "ABT", "TMO", "LIN", "ACN", "NOW",
        "INTU", "AMAT", "MU", "LRCX", "ADI", "REGN", "VRTX", "ISRG", "BKNG", "GILD",
    ],
    "BIST_STOCKS": [
        "THYAO.IS", "ASELS.IS", "GARAN.IS", "AKBNK.IS", "ISCTR.IS", "KCHOL.IS",
        "SAHOL.IS", "EREGL.IS", "BIMAS.IS", "SISE.IS", "TUPRS.IS", "FROTO.IS",
        "TCELL.IS", "PGSUS.IS", "YKBNK.IS", "ARCLK.IS", "TOASO.IS", "KOZAL.IS",
        "PETKM.IS", "HALKB.IS", "VAKBN.IS", "VESTL.IS", "ENKAI.IS", "TAVHL.IS",
        "MGROS.IS", "ULKER.IS", "SASA.IS", "KRDMD.IS", "OYAKC.IS", "TTKOM.IS",
        "DOAS.IS", "CCOLA.IS", "AEFES.IS", "SOKM.IS", "KONTR.IS", "ODAS.IS",
        "GUBRF.IS", "ALARK.IS", "ENJSA.IS", "ISGYO.IS", "CIMSA.IS", "AKSA.IS",
        "ISDMR.IS", "KOZAA.IS", "TRGYO.IS", "ZOREN.IS", "HEKTS.IS", "BERA.IS",
        "GESAN.IS", "KARSN.IS",
        "TKFEN.IS", "MAVI.IS", "ECILC.IS", "OTKAR.IS", "TSKB.IS", "AGHOL.IS",
        "ASTOR.IS", "EKGYO.IS", "ALFAS.IS", "IPEKE.IS", "GWIND.IS", "SELEC.IS",
        "MPARK.IS", "TTRAK.IS", "ANSGR.IS", "TURSG.IS", "BRSAN.IS", "BRYAT.IS",
        "CANTE.IS", "VESBE.IS",
    ],
    "STOCK_INTERVAL": "1d",
    "STOCK_RANGE": "2y",

    "RESISTANCE_LOOKBACK": 10,
    "SUPPORT_LOOKBACK": 10,
    "RSI_PERIOD": 14,
    "RSI_MAX_ENTRY": 65,
    "MACD_FAST": 12,
    "MACD_SLOW": 26,
    "MACD_SIGNAL": 9,
    "INITIAL_CAPITAL": 1000.0,
    "RISK_PER_TRADE": 0.015,
    "TP1_R": 1.5,
    "TP1_FRACTION": 0.5,
    "TP2_R": 2.0,
    "FEE_RATE": 0.0004,

    "MIN_TRADES_FOR_GUVENILIR": 8,   # bu sayidan az islemli sonuclar "yetersiz veri" etiketlenir
    "REQUEST_DELAY": 0.35,

    # YENI FILTRELER - sahte sinyalleri azaltmak icin
    "USE_VOLUME_FILTER": True,
    "VOLUME_LOOKBACK": 20,     # hacim ortalamasi icin bakilacak bar sayisi
    "VOLUME_MULT": 1.2,        # kirilim barinin hacmi, ortalamanin en az bu kati olmali
    "USE_TREND_FILTER": True,
    "TREND_EMA_LEN": 50,       # fiyat bu EMA'nin ustundeyse "genel trend yukari" sayilir

    # YENI RISK YONETIMI - ATR bazli dinamik stop + trailing stop
    "ATR_PERIOD": 14,
    "USE_ATR_STOP": True,      # True: stop ATR'ye gore, False: eski destek-bazli stop
    "ATR_STOP_MULT": 2.0,      # stop = giris - ATR_STOP_MULT * ATR
    "USE_TRAILING_STOP": True,
    "TRAIL_ATR_MULT": 2.5,     # TP1'den sonra stop, (kapanis - TRAIL_ATR_MULT*ATR) takip eder
}

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                  "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Accept": "application/json",
}


# ------------------------------------------------------------------------------------
# VERI CEKME
# ------------------------------------------------------------------------------------
def get_top_binance_symbols(n: int) -> list:
    url = "https://data-api.binance.vision/api/v3/ticker/24hr"
    resp = requests.get(url, headers=HEADERS, timeout=20)
    resp.raise_for_status()
    data = resp.json()
    haric = ("UP", "DOWN", "BULL", "BEAR")
    stablecoin_ciftleri = (
        "USDCUSDT", "FDUSDUSDT", "TUSDUSDT", "DAIUSDT", "RLUSDUSDT",
        "USD1USDT", "USDPUSDT", "PYUSDUSDT", "EURUSDT", "GBPUSDT",
    )
    adaylar = [
        d for d in data
        if d["symbol"].endswith("USDT")
        and not any(tag in d["symbol"] for tag in haric)
        and d["symbol"] not in stablecoin_ciftleri
        and not d["symbol"].startswith("U")
    ]
    adaylar.sort(key=lambda d: float(d["quoteVolume"]), reverse=True)
    return [d["symbol"] for d in adaylar[:n]]


def fetch_binance_klines(symbol: str, interval: str, lookback_days: int) -> pd.DataFrame:
    url = "https://data-api.binance.vision/api/v3/klines"
    end_time = int(time.time() * 1000)
    start_time = end_time - lookback_days * 24 * 60 * 60 * 1000
    all_rows = []
    cursor = start_time
    while cursor < end_time:
        params = {"symbol": symbol, "interval": interval, "startTime": cursor, "limit": 1000}
        resp = requests.get(url, params=params, headers=HEADERS, timeout=20)
        resp.raise_for_status()
        rows = resp.json()
        if not rows:
            break
        all_rows.extend(rows)
        cursor = rows[-1][6] + 1
        if len(rows) < 1000:
            break
        time.sleep(0.2)

    cols = ["open_time", "open", "high", "low", "close", "volume", "close_time",
            "qav", "trades", "taker_base", "taker_quote", "ignore"]
    df = pd.DataFrame(all_rows, columns=cols)
    df["open_time"] = pd.to_datetime(df["open_time"], unit="ms")
    for c in ["open", "high", "low", "close", "volume"]:
        df[c] = df[c].astype(float)
    return df[["open_time", "open", "high", "low", "close", "volume"]]


def fetch_yahoo_klines(symbol: str, interval: str, range_: str) -> pd.DataFrame:
    url = f"https://query1.finance.yahoo.com/v8/finance/chart/{symbol}"
    params = {"interval": interval, "range": range_}
    resp = requests.get(url, params=params, headers=HEADERS, timeout=20)
    resp.raise_for_status()
    data = resp.json()
    result = data.get("chart", {}).get("result")
    if not result:
        raise ValueError(f"{symbol}: Yahoo bos donus verdi.")
    r = result[0]
    timestamps = r.get("timestamp")
    if not timestamps:
        raise ValueError(f"{symbol}: zaman serisi bos.")
    quote = r["indicators"]["quote"][0]
    df = pd.DataFrame({
        "open_time": pd.to_datetime(timestamps, unit="s"),
        "open": quote["open"], "high": quote["high"],
        "low": quote["low"], "close": quote["close"], "volume": quote["volume"],
    })
    return df.dropna(subset=["close"]).reset_index(drop=True)


# ------------------------------------------------------------------------------------
# INDIKATORLER + BACKTEST (sushi_backtest_paper_trading.py ile ayni mantik)
# ------------------------------------------------------------------------------------
def add_indicators(df: pd.DataFrame, cfg: dict) -> pd.DataFrame:
    df = df.copy()
    ema_fast = df["close"].ewm(span=cfg["MACD_FAST"], adjust=False).mean()
    ema_slow = df["close"].ewm(span=cfg["MACD_SLOW"], adjust=False).mean()
    df["macd"] = ema_fast - ema_slow
    df["macd_signal"] = df["macd"].ewm(span=cfg["MACD_SIGNAL"], adjust=False).mean()
    df["macd_hist"] = df["macd"] - df["macd_signal"]

    delta = df["close"].diff()
    gain = delta.clip(lower=0)
    loss = -delta.clip(upper=0)
    avg_gain = gain.ewm(alpha=1 / cfg["RSI_PERIOD"], adjust=False).mean()
    avg_loss = loss.ewm(alpha=1 / cfg["RSI_PERIOD"], adjust=False).mean()
    rs = avg_gain / avg_loss.replace(0, np.nan)
    df["rsi"] = 100 - (100 / (1 + rs))

    df["resistance"] = df["high"].rolling(cfg["RESISTANCE_LOOKBACK"]).max().shift(1)
    df["support"] = df["low"].rolling(cfg["SUPPORT_LOOKBACK"]).min().shift(1)

    df["vol_avg"] = df["volume"].rolling(cfg["VOLUME_LOOKBACK"]).mean().shift(1)
    df["trend_ema"] = df["close"].ewm(span=cfg["TREND_EMA_LEN"], adjust=False).mean()

    prev_close = df["close"].shift(1)
    tr = pd.concat([
        df["high"] - df["low"],
        (df["high"] - prev_close).abs(),
        (df["low"] - prev_close).abs(),
    ], axis=1).max(axis=1)
    df["atr"] = tr.rolling(cfg["ATR_PERIOD"]).mean().shift(1)
    return df


def run_backtest(df: pd.DataFrame, cfg: dict):
    capital = cfg["INITIAL_CAPITAL"]
    trades = []
    position = None

    for i in range(max(cfg["RESISTANCE_LOOKBACK"], cfg["MACD_SLOW"], cfg["TREND_EMA_LEN"]) + 1, len(df)):
        row = df.iloc[i]

        if position is not None:
            hit_stop = row["low"] <= position["stop"]
            hit_tp1 = (not position["tp1_done"]) and row["high"] >= position["tp1_price"]
            hit_tp2 = row["high"] >= position["tp2_price"]

            if hit_stop:
                pnl = (position["stop"] - position["entry"]) * position["qty_remaining"]
                fee = position["stop"] * position["qty_remaining"] * cfg["FEE_RATE"]
                capital += pnl - fee
                trades.append({"exit_reason": "STOP", "pnl": pnl - fee})
                position = None
            else:
                if hit_tp1:
                    qty_close = position["qty_initial"] * cfg["TP1_FRACTION"]
                    pnl = (position["tp1_price"] - position["entry"]) * qty_close
                    fee = position["tp1_price"] * qty_close * cfg["FEE_RATE"]
                    capital += pnl - fee
                    position["qty_remaining"] -= qty_close
                    position["tp1_done"] = True
                    trades.append({"exit_reason": "TP1_PARTIAL", "pnl": pnl - fee})
                    position["stop"] = position["entry"]
                if position is not None and hit_tp2:
                    qty_close = position["qty_remaining"]
                    pnl = (position["tp2_price"] - position["entry"]) * qty_close
                    fee = position["tp2_price"] * qty_close * cfg["FEE_RATE"]
                    capital += pnl - fee
                    trades.append({"exit_reason": "TP2_FINAL", "pnl": pnl - fee})
                    position = None

                # TRAILING STOP: TP1'den sonra, ATR bazli olarak stop'u yukari cek
                # (asla asagi cekilmez, sadece kilitler).
                if (position is not None and position["tp1_done"]
                        and cfg["USE_TRAILING_STOP"] and pd.notna(row["atr"])):
                    trail_candidate = row["close"] - cfg["TRAIL_ATR_MULT"] * row["atr"]
                    if trail_candidate > position["stop"]:
                        position["stop"] = trail_candidate

        if position is None:
            breakout = row["close"] > row["resistance"] if pd.notna(row["resistance"]) else False
            macd_bullish = (row["macd_hist"] > 0) and (row["macd"] > row["macd_signal"])
            rsi_ok = pd.notna(row["rsi"]) and row["rsi"] < cfg["RSI_MAX_ENTRY"]

            if cfg["USE_VOLUME_FILTER"] and pd.notna(row["vol_avg"]):
                volume_ok = row["volume"] > row["vol_avg"] * cfg["VOLUME_MULT"]
            else:
                volume_ok = not cfg["USE_VOLUME_FILTER"]

            if cfg["USE_TREND_FILTER"] and pd.notna(row["trend_ema"]):
                trend_ok = row["close"] > row["trend_ema"]
            else:
                trend_ok = not cfg["USE_TREND_FILTER"]

            atr_ok = (not cfg["USE_ATR_STOP"]) or pd.notna(row["atr"])
            support_ok = (cfg["USE_ATR_STOP"]) or pd.notna(row["support"])

            if breakout and macd_bullish and rsi_ok and volume_ok and trend_ok and atr_ok and support_ok:
                entry = row["close"]
                if cfg["USE_ATR_STOP"]:
                    stop = entry - cfg["ATR_STOP_MULT"] * row["atr"]
                else:
                    stop = row["support"]
                risk_per_unit = entry - stop
                if risk_per_unit > 0:
                    risk_amount = capital * cfg["RISK_PER_TRADE"]
                    qty = risk_amount / risk_per_unit
                    position = {
                        "entry": entry, "stop": stop,
                        "tp1_price": entry + cfg["TP1_R"] * risk_per_unit,
                        "tp2_price": entry + cfg["TP2_R"] * risk_per_unit,
                        "qty_initial": qty, "qty_remaining": qty, "tp1_done": False,
                    }
                    capital -= entry * qty * cfg["FEE_RATE"]

    return pd.DataFrame(trades), capital


def summarize(label: str, trades_df: pd.DataFrame, final_capital: float, cfg: dict) -> dict:
    if trades_df.empty:
        final_only = trades_df
    else:
        final_only = trades_df[trades_df["exit_reason"] != "TP1_PARTIAL"]
    total_trades = len(final_only)
    wins = final_only[final_only["pnl"] > 0] if total_trades else final_only
    win_rate = (len(wins) / total_trades * 100) if total_trades else 0.0
    ret_pct = (final_capital / cfg["INITIAL_CAPITAL"] - 1) * 100
    return {
        "varlik": label,
        "islem_sayisi": total_trades,
        "kazanma_orani_%": round(win_rate, 1),
        "getiri_%": round(ret_pct, 1),
        "guvenilir_mi": "EVET" if total_trades >= cfg["MIN_TRADES_FOR_GUVENILIR"] else "AZ VERI",
    }


# ------------------------------------------------------------------------------------
# ANA CALISTIRMA
# ------------------------------------------------------------------------------------
def main():
    cfg = CONFIG
    sonuclar = []

    crypto_symbols = get_top_binance_symbols(cfg["CRYPTO_TOP_N"])
    print(f"{len(crypto_symbols)} kripto parite test edilecek...")
    for symbol in crypto_symbols:
        try:
            df = fetch_binance_klines(symbol, cfg["CRYPTO_INTERVAL"], cfg["CRYPTO_LOOKBACK_DAYS"])
            df = add_indicators(df, cfg)
            trades_df, final_capital = run_backtest(df, cfg)
            sonuclar.append(summarize(f"[KRIPTO] {symbol}", trades_df, final_capital, cfg))
            print(f"  {symbol} tamamlandi.")
        except Exception as exc:
            print(f"  {symbol} HATA: {exc}")
        time.sleep(cfg["REQUEST_DELAY"])

    tum_hisseler = [(s, "[ABD HISSE]") for s in cfg["US_STOCKS"]] + \
                   [(s, "[BIST]") for s in cfg["BIST_STOCKS"]]
    print(f"\n{len(tum_hisseler)} hisse test edilecek...")
    for symbol, etiket in tum_hisseler:
        try:
            df = fetch_yahoo_klines(symbol, cfg["STOCK_INTERVAL"], cfg["STOCK_RANGE"])
            df = add_indicators(df, cfg)
            trades_df, final_capital = run_backtest(df, cfg)
            sonuclar.append(summarize(f"{etiket} {symbol}", trades_df, final_capital, cfg))
            print(f"  {symbol} tamamlandi.")
        except Exception as exc:
            print(f"  {symbol} HATA: {exc}")
        time.sleep(cfg["REQUEST_DELAY"])

    sonuc_df = pd.DataFrame(sonuclar).sort_values("getiri_%", ascending=False).reset_index(drop=True)
    sonuc_df.to_csv("coklu_varlik_sonuclari.csv", index=False)

    print("\n" + "=" * 80)
    print("TUM SONUCLAR (getiriye gore siralandi):")
    print("=" * 80)
    print(sonuc_df.to_string(index=False))

    pozitif_ve_guvenilir = sonuc_df[(sonuc_df["getiri_%"] > 0) & (sonuc_df["guvenilir_mi"] == "EVET")]
    print("\n" + "=" * 80)
    print(f"POZITIF GETIRILI VE YETERLI ISLEM SAYISINA SAHIP VARLIKLAR ({len(pozitif_ve_guvenilir)} adet):")
    print("=" * 80)
    if pozitif_ve_guvenilir.empty:
        print("Hicbiri bu kriteri karsilamiyor. Genel tarama listesini daraltmak riskli olabilir.")
    else:
        print(pozitif_ve_guvenilir.to_string(index=False))
        print("\nOneri: genel_izleme_bulut.py'deki listeleri SADECE bu varliklarla sinirla.")

    print("\nTum sonuclar 'coklu_varlik_sonuclari.csv' dosyasina kaydedildi.")
    print("NOT: Bu da gecmis veriye dayali bir simulasyondur, gelecek performansi garanti etmez.")

    # --- TELEGRAM OZETI (sadece TELEGRAM_BOT_TOKEN/CHAT_ID tanimliysa, orn. GitHub Actions'ta) ---
    satirlar = [
        f"AYLIK YENIDEN-DOGRULAMA TAMAMLANDI ({len(sonuc_df)} varlik tarandi)",
        f"Pozitif + guvenilir: {len(pozitif_ve_guvenilir)} varlik",
        "",
        "En iyi 10 (getiriye gore):",
    ]
    for _, r in sonuc_df.head(10).iterrows():
        satirlar.append(f"  {r['varlik']}: %{r['getiri_%']:.1f} getiri, "
                         f"%{r['kazanma_orani_%']:.0f} kazanma, {r['islem_sayisi']} islem ({r['guvenilir_mi']})")
    satirlar.append("\nTam liste 'coklu_varlik_sonuclari.csv' dosyasinda (repo'ya commit edildi).")
    satirlar.append("Onemli fark varsa genel_izleme_bulut.py'nin listesini elle guncelle.")
    send_telegram("\n".join(satirlar))


if __name__ == "__main__":
    main()
