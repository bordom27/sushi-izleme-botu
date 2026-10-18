"""
KIRILIM69 PRO v6 - Python cekirdegi
================================================================================
TradingView'daki "Kirilim69 PRO" (v6) gostergesinin karar mantiginin birebir
Python karsiligi. Bot (genel_izleme_bulut.py) ve aylik dogrulama
(v6_backtest.py) bu dosyayi kullanir; mantik TEK yerde durur.

Ayni girdi -> ayni sinyal: elekler, kirilim/retest/teyit zamanlamasi,
yapisal stop, fib/engel bazli TP1-TP2, TP1 kismi kar + basabas+, chandelier
trailing, zaman stopu ve komisyon dahil R hesabi Pine koduyla ayni sirada
uygulanir. Ust zaman dilimi verileri (gunluk/haftalik) KAPANMIS mumlardan
alinir (Pine: request.security + lookahead_on + [1]).

Gostergeler TradingView'in yerlesik fonksiyonlariyla ayni tohumlama
(SMA ile baslayan EMA/RMA) kullanilarak hesaplanir.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field

import numpy as np
import pandas as pd

# ------------------------------------------------------------------------------------
# PARAMETRELER (Pine varsayilanlari - "Dengeli (test edildi)" profili)
# ------------------------------------------------------------------------------------
PARAMS = {
    "yon": "Long + Short",          # "Long + Short" | "Sadece Long" | "Sadece Short"
    "dengeli": True,                # Elek sikiligi: Dengeli
    "yuksek_isabet": False,         # Profil: Yuksek isabet (deneysel)
    "min_yumusak": 4,

    # 1) Piyasa
    "use_mkt": True,
    "mkt_ema_len": 50,
    "long_sart": "BTC > EMA200",    # "Kapali" | "BTC > EMA200" | "Coin > EMA200" | "BTC ve coin > EMA200"
    "mkt_macd_req": False,
    "use_panic": True,
    "panic_bars": 6,
    "panic_pct": 4.0,

    # 2) Ust zaman dilimi
    "use_ana_trend": False,
    "d_ema_long": 200,
    "slope_len": 10,
    "w_ema_len": 21,
    "use_w_macd": False,
    "w_macd_mode": "MACD > 0 veya Hist > 0",
    "use_d_macd": False,
    "d_macd_mode": "Hist > 0 veya yukseliyor",
    "na_gecir": False,              # "Ust TF verisi yetersizse": Engelle

    # 3) Grafik TF
    "ema_fast": 21,
    "trend_ema": 50,
    "macd_fast": 12,
    "macd_slow": 26,
    "macd_signal": 9,
    "use_ltf_macd": True,
    "ltf_macd_mode": "Hist > 0 veya yukseliyor",
    "rsi_len": 14,
    "rsi_min": 50.0,
    "use_adx": True,
    "di_len": 14,
    "adx_smooth": 14,
    "adx_min": 25.0,

    # 4) Kirilim
    "entry_mode": "Kirilim kapanisi",  # "Hibrit" | "Sadece retest" | "Kirilim kapanisi" (Ekim 2026 testi: kapanis en iyi)
    "resistance_len": 80,
    "break_buf_atr": 0.1,
    "use_volume": True,
    "vol_len": 20,
    "vol_mult": 2.5,                # Ekim 2026: secici mod (2x yerine 2.5x) - daha az sinyal, isabet ~%69
    "strong_vol_mult": 2.0,
    "min_close_pos": 0.6,
    "max_candle_range_atr": 3.0,
    "max_ext_atr": 3.0,
    "use_base": False,
    "max_base_atr": 6.0,
    "retest_bars": 6,
    "use_teyit": True,
    "retest_tol_atr": 0.3,
    "fail_atr": 0.5,
    "cooldown_bars": 3,

    # 5) Fib
    "use_fib": False,               # Ekim 2026: fib 0.618 giris filtresi kaldirildi (3 donemde de iyilesti); fib TP hedefleri duruyor
    "fib_len": 89,
    "use_fib_tp": True,

    # 6) Risk
    "atr_len": 14,
    "stop_lookback": 5,
    "stop_buf_atr": 0.2,
    "seviye_stop_atr": 1.5,
    "min_stop_atr": 1.0,
    "max_stop_atr": 3.5,
    "max_risk_pct": 12.0,
    "tp1_r": 0.8,
    "tp1_min_r": 0.6,
    "tp1_max_r": 1.1,
    "tp2_max_r": 6.0,
    "tp_offset_atr": 0.1,
    "use_room": True,
    "room_pivot_len": 10,
    "min_room_r": 0.5,
    "hesap_risk": 0.5,              # islem basi hesap riski (%) - 46 coinde max dusus ~13R
    "komisyon_pct": 0.1,
    "min_kalite": "C",
    "max_atr_pct": 0.0,

    # 7) Yonetim
    "tp1_pct": 90.0,
    "be_buf_r": 0.1,
    "trail_atr_mult": 2.5,
    "use_time_stop": True,
    "time_stop_bars": 20,
    "time_stop_min_r": 0.5,
    "use_trend_exit": False,
    "erken_be_r": 0.0,

    # 9) Basarisiz kirilim cikisi (Ekim 2026 testi: ayni kazanc, ~%25 daha kucuk max dusus):
    #    TP1 alinmadan, girisin ilk 3 mumunda kapanis kirilan seviyenin 0.3 ATR gerisine
    #    donerse stopu beklemeden kapanista cik.
    # 19) Piyasa uyumu (v6.4, Ekim 2026): son genislik_bar mumda GENISLIK_COINLER'den herhangi biri
    #     80 mumluk tepesinin ustunde kapattiysa yeni SHORT acilmaz (piyasa tek yonlu dususte degil).
    "genislik_filtre": True,
    "genislik_bar": 6,
    "genislik_max": 0,
    "basarisiz_cikis": True,
    "bc_bar": 3,
    "bc_atr": 0.15,

    # 8) Sembol tablosu
    "use_auto_params": True,
    "def_rsi_max": 70.0,
    "def_tp2_r": 2.5,
}

# Pine'daki sembol tablosu: (RSI ust siniri, ATR stop carpani, TP2 alt R)
SEMBOL_TABLOSU = {
    "JSTUSDT": (75, 2.0, 1.5), "PHAUSDT": (75, 2.0, 1.5), "PAXGUSDT": (75, 2.5, 1.5),
    "TRXUSDT": (75, 2.5, 2.5), "TUSDT": (75, 2.5, 1.5), "AGLDUSDT": (75, 2.0, 1.5),
    "NEARUSDT": (65, 2.5, 3.0), "ZILUSDT": (75, 2.0, 1.5), "DEXEUSDT": (75, 2.0, 1.5),
    "KAITOUSDT": (75, 2.5, 2.0), "AVAUSDT": (75, 1.5, 1.5), "RAYUSDT": (60, 2.0, 3.0),
    "SKLUSDT": (75, 2.0, 1.5), "CHZUSDT": (65, 2.5, 3.0), "NFPUSDT": (70, 1.5, 1.5),
    "PEPEUSDT": (75, 1.5, 1.5), "ARBUSDT": (75, 1.5, 1.5), "EPICUSDT": (75, 1.5, 2.0),
    "CUSDT": (70, 1.5, 1.5), "DOTUSDT": (60, 1.5, 1.5), "ETHFIUSDT": (60, 2.0, 3.0),
    "ENAUSDT": (70, 1.5, 1.5), "FILUSDT": (65, 2.0, 1.5), "ZENUSDT": (60, 2.5, 3.0),
    "LOGO": (75, 2.0, 2.0), "CTSIUSDT": (75, 2.5, 1.5), "SARKY": (75, 1.5, 3.0),
    "DASHUSDT": (65, 1.5, 1.5), "PLUMEUSDT": (65, 2.5, 1.5), "EREGL": (75, 2.5, 2.0),
    "AAVEUSDT": (65, 2.0, 3.0), "NILUSDT": (75, 2.5, 3.0), "HFTUSDT": (65, 2.0, 1.5),
    "CAKEUSDT": (75, 2.0, 2.0), "ECILC": (60, 2.0, 3.0), "PETKM": (75, 1.5, 1.5),
    "ALLOUSDT": (75, 2.5, 1.5), "MORPHOUSDT": (60, 2.5, 1.5), "PROMUSDT": (75, 2.5, 1.5),
    "MINAUSDT": (60, 2.5, 1.5), "KCHOL": (65, 2.0, 1.5), "SISE": (65, 1.5, 3.0),
    "ASTOR": (60, 1.5, 3.0), "ALGOUSDT": (75, 1.5, 1.5), "BERAUSDT": (75, 2.0, 1.5),
    "ZAMAUSDT": (75, 2.0, 1.5), "ENKAI": (70, 2.0, 2.5), "TUPRS": (65, 1.5, 2.5),
    "NUGYO": (75, 2.0, 2.5), "PYTHUSDT": (75, 2.5, 1.5), "XTZUSDT": (60, 1.5, 1.5),
    "IZMDC": (70, 2.0, 1.5), "SUSDT": (65, 1.5, 1.5), "XRPUSDT": (75, 2.5, 3.0),
    "INDES": (75, 1.5, 1.5), "ACEUSDT": (70, 2.0, 1.5), "JTOUSDT": (70, 2.5, 1.5),
    "ICBCT": (60, 2.5, 3.0), "SOPHUSDT": (70, 1.5, 1.5), "SAGAUSDT": (65, 1.5, 2.0),
    "ZECUSDT": (70, 2.5, 2.5), "APTUSDT": (60, 2.0, 1.5), "METUSDT": (60, 2.5, 3.0),
    "YKBNK": (70, 1.5, 1.5), "SKYUSDT": (65, 1.5, 2.0), "FUSDT": (70, 1.5, 3.0),
    "ALARK": (75, 1.5, 1.5), "GUNUSDT": (70, 2.0, 3.0), "TTKOM": (55, 1.5, 1.5),
}

GERI = (0.236, 0.382, 0.5, 0.618, 0.786)
UZAT = (1.272, 1.414, 1.618, 2.0, 2.618)


# ------------------------------------------------------------------------------------
# TradingView ile ayni tohumlamali gostergeler
# ------------------------------------------------------------------------------------
def _seeded(src: np.ndarray, length: int, alpha: float) -> np.ndarray:
    """Pine ta.ema / ta.rma: ilk 'length' gecerli degerin SMA'si ile baslar."""
    out = np.full(len(src), np.nan)
    run = 0
    prev = np.nan
    for i, v in enumerate(src):
        if np.isnan(prev):
            if np.isnan(v):
                run = 0
                continue
            run += 1
            if run >= length:
                prev = float(np.mean(src[i - length + 1:i + 1]))
                out[i] = prev
        else:
            if np.isnan(v):
                out[i] = np.nan  # Pine: na girdi -> na cikti (nz(sum[1]) sonraki barda devam)
                continue
            prev = alpha * v + (1 - alpha) * prev
            out[i] = prev
    return out


def ema(src, length):
    return _seeded(np.asarray(src, dtype=float), length, 2.0 / (length + 1))


def rma(src, length):
    return _seeded(np.asarray(src, dtype=float), length, 1.0 / length)


def sma(src, length):
    return pd.Series(src).rolling(length).mean().to_numpy()


def macd(close, fast, slow, sig):
    m = ema(close, fast) - ema(close, slow)
    s = ema(m, sig)
    return m, s, m - s


def rsi(close, length):
    c = np.asarray(close, dtype=float)
    ch = np.diff(c, prepend=np.nan)
    up = rma(np.where(np.isnan(ch), np.nan, np.maximum(ch, 0)), length)
    dn = rma(np.where(np.isnan(ch), np.nan, np.maximum(-ch, 0)), length)
    out = np.where(dn == 0, 100.0, np.where(up == 0, 0.0, 100 - 100 / (1 + up / np.where(dn == 0, 1, dn))))
    out[np.isnan(up) | np.isnan(dn)] = np.nan
    return out


def true_range(h, l, c, handle_na: bool):
    pc = np.concatenate([[np.nan], c[:-1]])
    tr = np.fmax(h - l, np.fmax(np.abs(h - pc), np.abs(l - pc)))
    if handle_na:
        tr[0] = h[0] - l[0]
    else:
        tr[0] = np.nan
    return tr


def fixnan(a):
    return pd.Series(a).ffill().to_numpy()


def dmi(h, l, c, di_len, adx_len):
    up = np.diff(h, prepend=np.nan)
    down = -np.diff(l, prepend=np.nan)
    plus_dm = np.where(np.isnan(up), np.nan, np.where((up > down) & (up > 0), up, 0.0))
    minus_dm = np.where(np.isnan(down), np.nan, np.where((down > up) & (down > 0), down, 0.0))
    trur = rma(true_range(h, l, c, False), di_len)
    with np.errstate(divide="ignore", invalid="ignore"):
        plus = fixnan(100 * rma(plus_dm, di_len) / trur)
        minus = fixnan(100 * rma(minus_dm, di_len) / trur)
        s = plus + minus
        adx = 100 * rma(np.abs(plus - minus) / np.where(s == 0, 1, s), adx_len)
    return plus, minus, adx


def highest(a, n):
    return pd.Series(a).rolling(n).max().to_numpy()


def lowest(a, n):
    return pd.Series(a).rolling(n).min().to_numpy()


def bars_offset(a: np.ndarray, n: int, en_dusuk: bool) -> np.ndarray:
    """Pine ta.lowestbars / ta.highestbars: en uc degerin kac bar once oldugu (pozitif)."""
    out = np.full(len(a), np.nan)
    for i in range(n - 1, len(a)):
        w = a[i - n + 1:i + 1]
        if np.isnan(w).any():
            continue
        # esitlikte en yakin (en yeni) bari sec
        rev = w[::-1]
        k = int(np.argmin(rev) if en_dusuk else np.argmax(rev))
        out[i] = k
    return out


def pivot(a: np.ndarray, L: int, tepe: bool) -> np.ndarray:
    """Pine ta.pivothigh/pivotlow(src, L, L): bar i'de, i-L'deki pivot degeri (yoksa NaN)."""
    out = np.full(len(a), np.nan)
    for i in range(2 * L, len(a)):
        c = a[i - L]
        sol = a[i - 2 * L:i - L]
        sag = a[i - L + 1:i + 1]
        if tepe:
            if c > sol.max() and c >= sag.max():
                out[i] = c
        else:
            if c < sol.min() and c <= sag.min():
                out[i] = c
    return out


# ------------------------------------------------------------------------------------
# Ust zaman dilimi hizalama (kapanmis mum)
# ------------------------------------------------------------------------------------
def _htf_onceki(chart_open: pd.Series, htf: pd.DataFrame, period: str, cols: dict) -> dict:
    """Grafik barinin icinde bulundugu ust TF mumunun BIR ONCEKI (kapanmis) mumundaki degerler."""
    if htf is None or len(htf) == 0:
        return {k: np.full(len(chart_open), np.nan) for k in cols}
    if period == "D":
        anahtar = chart_open.dt.floor("D")
    else:  # haftalik, Pazartesi 00:00 UTC
        gun = chart_open.dt.floor("D")
        anahtar = gun - pd.to_timedelta(gun.dt.weekday, unit="D")
    idx = pd.Index(htf["open_time"])
    pos = idx.get_indexer(anahtar)  # -1: ust TF mumu yok
    out = {}
    for k, arr in cols.items():
        arr = np.asarray(arr, dtype=float)
        v = np.full(len(chart_open), np.nan)
        ok = pos >= 1
        v[ok] = arr[pos[ok] - 1]
        out[k] = v
    return out


def _macd_poz(m, h, hp, mode):
    yuk = (not math.isnan(hp)) and h > hp
    if mode == "MACD > 0 veya Hist > 0":
        return m > 0 or h > 0
    if mode == "Hist > 0":
        return h > 0
    if mode == "Hist > 0 veya yukseliyor":
        return h > 0 or yuk
    if mode == "MACD > 0":
        return m > 0
    return h > 0 and m > 0


def _macd_neg(m, h, hp, mode):
    dus = (not math.isnan(hp)) and h < hp
    if mode == "MACD > 0 veya Hist > 0":
        return m < 0 or h < 0
    if mode == "Hist > 0":
        return h < 0
    if mode == "Hist > 0 veya yukseliyor":
        return h < 0 or dus
    if mode == "MACD > 0":
        return m < 0
    return h < 0 and m < 0


def _nan(x):
    return x is None or (isinstance(x, float) and math.isnan(x))


# ------------------------------------------------------------------------------------
# Sonuc yapilari
# ------------------------------------------------------------------------------------
@dataclass
class Olay:
    zaman: pd.Timestamp          # olayin gerceklestigi mumun ACILIS zamani (UTC)
    tur: str                     # GIRIS | TP1 | CIKIS | KIRILIM | SAHTE | ZAMAN_ASIMI | RED
    yon: int                     # 1 long, -1 short
    veri: dict = field(default_factory=dict)


@dataclass
class Sonuc:
    olaylar: list
    islemler: list               # kapanan islemler: dict(giris_zaman, cikis_zaman, yon, sonuc_r, neden, ...)
    acik: dict | None            # su anki acik pozisyon (yoksa None)
    bekleyen: dict | None        # retest bekleyen kirilim (yoksa None)
    son_bar: pd.Timestamp | None
    son_kapanis: float | None
    filtre: dict                 # son bardaki elek durumu (ozet)


# ------------------------------------------------------------------------------------
# ANA SIMULASYON
# ------------------------------------------------------------------------------------
def genislik_serisi(veriler: dict, liste: list, bar: int = 6, R: int = 80) -> pd.Series:
    """Her 4s mum icin: listedeki coinlerden kacinin son `bar` mumda R-mumluk tepesinin ustunde kapattigi."""
    kolon = {}
    for s in liste:
        df = veriler.get(s)
        if df is None or len(df) <= R:
            continue
        h = df["high"].to_numpy(float)
        c = df["close"].to_numpy(float)
        hh = pd.Series(h).rolling(R).max().shift(1).to_numpy()
        kir = np.where(np.arange(len(c)) >= R, (c > hh).astype(float), 0.0)
        kolon[s] = pd.Series(kir, index=pd.to_datetime(df["open_time"]))
    if not kolon:
        return pd.Series(dtype=float)
    m = pd.DataFrame(kolon).sort_index().fillna(0)
    return (m.rolling(bar, min_periods=1).max() > 0).sum(axis=1).astype(float)


def simule_et(symbol: str, df: pd.DataFrame, gunluk: pd.DataFrame | None,
              btc_gunluk: pd.DataFrame | None, btc_4h: pd.DataFrame | None,
              haftalik: pd.DataFrame | None = None, params: dict | None = None,
              giris_bas: pd.Timestamp | None = None, giris_bit: pd.Timestamp | None = None,
              genislik: pd.Series | None = None) -> Sonuc:
    """
    df          : grafik TF (4 saat) - SADECE KAPANMIS mumlar. Kolonlar: open_time, open, high, low, close, volume
    gunluk      : coinin gunluk mumlari (Coin > EMA200 / ana trend / gunluk MACD icin)
    btc_gunluk  : BTCUSDT gunluk (piyasa elegi)
    btc_4h      : BTCUSDT grafik TF (ani hareket / panik elegi)
    haftalik    : coinin haftalik mumlari (sadece haftalik MACD / ana trend aciksa gerekir)
    giris_bas/bit: sadece bu aralikta yeni islem acilir (test icin)
    genislik    : genislik_serisi() ciktisi (verilmezse piyasa uyumu filtresi uygulanmaz)
    """
    p = dict(PARAMS)
    if params:
        p.update(params)

    use_ana_trend = p["use_ana_trend"] or p["yuksek_isabet"]
    use_w_macd = p["use_w_macd"] or p["yuksek_isabet"]
    max_atr_pct = 5.0 if (p["yuksek_isabet"] and p["max_atr_pct"] <= 0) else p["max_atr_pct"]
    dengeli = p["dengeli"]
    na_gecir = p["na_gecir"]

    sembol = symbol[:-2] if symbol.endswith(".P") else symbol
    is_btc_base = sembol.startswith("BTC") and sembol.endswith("USDT") and sembol[3:-4] == ""
    mkt_uygulanir = p["use_mkt"] and not is_btc_base
    long_izin = p["yon"] != "Sadece Short"
    short_izin = p["yon"] != "Sadece Long"

    ozel = SEMBOL_TABLOSU.get(sembol) if p["use_auto_params"] else None
    rsi_max = float(ozel[0]) if ozel else p["def_rsi_max"]
    tp2_r = float(ozel[2]) if ozel else p["def_tp2_r"]

    df = df.reset_index(drop=True)
    n = len(df)
    ot = pd.to_datetime(df["open_time"])
    gen_dizi = genislik.reindex(ot).to_numpy(float) if (p["genislik_filtre"] and genislik is not None and len(genislik)) else None
    o = df["open"].to_numpy(float)
    h = df["high"].to_numpy(float)
    l = df["low"].to_numpy(float)
    c = df["close"].to_numpy(float)
    v = df["volume"].to_numpy(float)

    # --- grafik TF gostergeleri
    atr = rma(true_range(h, l, c, True), p["atr_len"])
    m_line, s_line, hist = macd(c, p["macd_fast"], p["macd_slow"], p["macd_signal"])
    rsi_v = rsi(c, p["rsi_len"])
    ema_f = ema(c, p["ema_fast"])
    tr_ema = ema(c, p["trend_ema"])
    di_p, di_m, adx_v = dmi(h, l, c, p["di_len"], p["adx_smooth"])

    R = p["resistance_len"]
    resistance = np.concatenate([[np.nan], highest(h, R)[:-1]])
    support = np.concatenate([[np.nan], lowest(l, R)[:-1]])
    vol_avg = np.concatenate([[np.nan], sma(v, p["vol_len"])[:-1]])

    F = p["fib_len"]
    fib_low = np.concatenate([[np.nan], lowest(l, F)[:-1]])
    fib_high = np.concatenate([[np.nan], highest(h, F)[:-1]])
    lb = bars_offset(l, F, True)
    hb = bars_offset(h, F, False)
    low_ago = np.concatenate([[0], np.nan_to_num(lb[:-1], nan=0)]).astype(int)
    high_ago = np.concatenate([[0], np.nan_to_num(hb[:-1], nan=0)]).astype(int)

    ph_room = pivot(h, p["room_pivot_len"], True)
    pl_room = pivot(l, p["room_pivot_len"], False)
    swing_low = lowest(l, p["stop_lookback"])
    swing_high = highest(h, p["stop_lookback"])

    # --- ust zaman dilimleri
    if gunluk is not None and len(gunluk):
        gc = gunluk["close"].to_numpy(float)
        gm, _, gh = macd(gc, p["macd_fast"], p["macd_slow"], p["macd_signal"])
        geL = ema(gc, p["d_ema_long"])
        sl = p["slope_len"]
        geL_old = np.concatenate([np.full(sl, np.nan), geL[:-sl]]) if len(geL) > sl else np.full(len(geL), np.nan)
        gh_prev = np.concatenate([[np.nan], gh[:-1]])
        G = _htf_onceki(ot, gunluk, "D", {"m": gm, "h": gh, "hp": gh_prev, "c": gc, "e": geL, "eo": geL_old})
    else:
        G = {k: np.full(n, np.nan) for k in ("m", "h", "hp", "c", "e", "eo")}

    if haftalik is not None and len(haftalik):
        wc = haftalik["close"].to_numpy(float)
        wm, _, wh = macd(wc, p["macd_fast"], p["macd_slow"], p["macd_signal"])
        we = ema(wc, p["w_ema_len"])
        wh_prev = np.concatenate([[np.nan], wh[:-1]])
        W = _htf_onceki(ot, haftalik, "W", {"m": wm, "h": wh, "hp": wh_prev, "c": wc, "e": we})
    else:
        W = {k: np.full(n, np.nan) for k in ("m", "h", "hp", "c", "e")}

    if btc_gunluk is not None and len(btc_gunluk):
        bc = btc_gunluk["close"].to_numpy(float)
        _, _, bh = macd(bc, p["macd_fast"], p["macd_slow"], p["macd_signal"])
        M = _htf_onceki(ot, btc_gunluk, "D", {"c": bc, "e": ema(bc, p["mkt_ema_len"]), "h": bh, "e2": ema(bc, 200)})
    else:
        M = {k: np.full(n, np.nan) for k in ("c", "e", "h", "e2")}

    mk_roc = np.full(n, np.nan)
    if btc_4h is not None and len(btc_4h):
        b4 = btc_4h.reset_index(drop=True)
        bcl = b4["close"].to_numpy(float)
        pb = p["panic_bars"]
        roc = np.full(len(bcl), np.nan)
        roc[pb:] = 100 * (bcl[pb:] - bcl[:-pb]) / bcl[:-pb]
        s = pd.Series(roc, index=pd.to_datetime(b4["open_time"]))
        mk_roc = s.reindex(ot).to_numpy(float)

    min_isinma = max(R, p["macd_slow"] + p["macd_signal"], p["atr_len"], p["trend_ema"], p["vol_len"], F) + 5

    # --- durum
    olaylar: list[Olay] = []
    islemler: list[dict] = []
    direncler: list[float] = []
    destekler: list[float] = []
    son_stop_bar = None

    pos = None          # dict
    pend = None         # dict
    tp1_pct = p["tp1_pct"] / 100.0
    kom = p["komisyon_pct"] / 100.0

    def fib_seviyeler(i):
        fr = fib_high[i] - fib_low[i]
        if not (fr > 0):
            return []
        yukari = low_ago[i] > high_ago[i]
        s = [(fib_high[i] - r * fr) if yukari else (fib_low[i] + r * fr) for r in GERI]
        s += [fib_high[i], fib_low[i]]
        for e in UZAT:
            s += [fib_low[i] + e * fr, fib_high[i] - e * fr]
        return sorted(s)

    def fib_ustu(i, fiyat):
        for x in fib_seviyeler(i):
            if x > fiyat:
                return x
        return np.nan

    def fib_alti(i, fiyat):
        sonuc = np.nan
        for x in fib_seviyeler(i):
            if x >= fiyat:
                break
            if x > 0:
                sonuc = x
        return sonuc

    def tavan(fiyat):
        best = np.nan
        for x in direncler:
            if x > fiyat * 1.002 and (math.isnan(best) or x < best):
                best = x
        return best

    def zemin(fiyat):
        best = np.nan
        for x in destekler:
            if x < fiyat * 0.998 and (math.isnan(best) or x > best):
                best = x
        return best

    filtre_son = {}

    for i in range(n):
        a = atr[i]
        # ---------------- elekler
        mk_c, mk_e, mk_h, mk_e2 = M["c"][i], M["e"][i], M["h"][i], M["e2"][i]
        mk_yok = math.isnan(mk_c) or math.isnan(mk_e)
        mk_trend_l = na_gecir if mk_yok else (mk_c > mk_e and (not p["mkt_macd_req"] or mk_h > 0))
        mk_trend_s = na_gecir if mk_yok else (mk_c < mk_e and (not p["mkt_macd_req"] or mk_h < 0))
        roc_i = mk_roc[i]
        panik_l = (not p["use_panic"]) or math.isnan(roc_i) or roc_i > -p["panic_pct"]
        panik_s = (not p["use_panic"]) or math.isnan(roc_i) or roc_i < p["panic_pct"]
        L1 = (not mkt_uygulanir) or (mk_trend_l and panik_l)
        d_c, d_e = G["c"][i], G["e"][i]
        coin_ust200 = na_gecir if (math.isnan(d_c) or math.isnan(d_e)) else d_c > d_e
        if not mkt_uygulanir:
            btc_ust200 = coin_ust200
        else:
            btc_ust200 = na_gecir if (math.isnan(mk_c) or math.isnan(mk_e2)) else mk_c > mk_e2
        ls = p["long_sart"]
        long_ek = True if ls == "Kapali" else btc_ust200 if ls == "BTC > EMA200" else \
            coin_ust200 if ls == "Coin > EMA200" else (btc_ust200 and coin_ust200)
        S1 = (not mkt_uygulanir) or (mk_trend_s and panik_s)

        at_yok = math.isnan(G["e"][i]) or math.isnan(G["eo"][i]) or math.isnan(W["e"][i]) or math.isnan(W["c"][i])
        L2 = (not use_ana_trend) or (na_gecir if at_yok else (d_c > d_e and G["e"][i] >= G["eo"][i] and W["c"][i] > W["e"][i]))
        S2 = (not use_ana_trend) or (na_gecir if at_yok else (d_c < d_e and G["e"][i] <= G["eo"][i] and W["c"][i] < W["e"][i]))
        w_yok = math.isnan(W["h"][i]) or math.isnan(W["m"][i])
        L3 = (not use_w_macd) or (na_gecir if w_yok else _macd_poz(W["m"][i], W["h"][i], W["hp"][i], p["w_macd_mode"]))
        S3 = (not use_w_macd) or (na_gecir if w_yok else _macd_neg(W["m"][i], W["h"][i], W["hp"][i], p["w_macd_mode"]))
        d_yok = math.isnan(G["h"][i]) or math.isnan(G["m"][i])
        L4 = (not p["use_d_macd"]) or (na_gecir if d_yok else _macd_poz(G["m"][i], G["h"][i], G["hp"][i], p["d_macd_mode"]))
        S4 = (not p["use_d_macd"]) or (na_gecir if d_yok else _macd_neg(G["m"][i], G["h"][i], G["hp"][i], p["d_macd_mode"]))

        te3 = tr_ema[i - 3] if i >= 3 else np.nan
        L5 = c[i] > tr_ema[i] and ema_f[i] > tr_ema[i] and tr_ema[i] >= te3
        S5 = c[i] < tr_ema[i] and ema_f[i] < tr_ema[i] and tr_ema[i] <= te3
        hp1 = hist[i - 1] if i >= 1 else np.nan
        L6 = (not p["use_ltf_macd"]) or _macd_poz(m_line[i], hist[i], hp1, p["ltf_macd_mode"])
        S6 = (not p["use_ltf_macd"]) or _macd_neg(m_line[i], hist[i], hp1, p["ltf_macd_mode"])
        r0 = rsi_v[i]
        r1 = rsi_v[i - 1] if i >= 1 else np.nan
        L7 = r0 >= p["rsi_min"] and _pine_min(r0, r1) < rsi_max
        S7 = r0 <= 100 - p["rsi_min"] and _pine_max(r0, r1) > 100 - rsi_max
        adx2 = adx_v[i - 2] if i >= 2 else np.nan
        adx_guc = adx_v[i] >= p["adx_min"] or adx_v[i] > adx2
        L8 = (not p["use_adx"]) or (di_p[i] > di_m[i] and adx_guc)
        S8 = (not p["use_adx"]) or (di_m[i] > di_p[i] and adx_guc)
        c_cool = son_stop_bar is None or (i - son_stop_bar) >= p["cooldown_bars"]
        isinma = i >= min_isinma
        e9 = c_cool and isinma

        long_set = long_izin and long_ek and L1 and L2 and L3 and L4 and L5 and L7 and e9 and (dengeli or (L6 and L8))
        short_set = short_izin and S1 and S2 and S3 and S4 and S5 and S7 and e9 and (dengeli or (S6 and S8))

        # ---------------- kirilim ani
        rng = h[i] - l[i]
        close_pos = (c[i] - l[i]) / rng if rng > 0 else 0.5
        vol_oran = v[i] / vol_avg[i] if vol_avg[i] > 0 else np.nan
        range_ok = a <= 0 or rng <= p["max_candle_range_atr"] * a
        c_brk_l = c[i] > resistance[i] + p["break_buf_atr"] * a
        c_brk_s = c[i] < support[i] - p["break_buf_atr"] * a
        c_vol = (not p["use_volume"]) or (v[i] > vol_avg[i] * p["vol_mult"])
        c_mum_l = c[i] > o[i] and close_pos >= p["min_close_pos"] and range_ok
        c_mum_s = c[i] < o[i] and close_pos <= 1 - p["min_close_pos"] and range_ok
        c_mum_temel_l = c[i] > o[i] and close_pos >= 0.5 and range_ok
        c_mum_temel_s = c[i] < o[i] and close_pos <= 0.5 and range_ok
        c_uzama_l = a <= 0 or (c[i] - ema_f[i]) <= p["max_ext_atr"] * a
        c_uzama_s = a <= 0 or (ema_f[i] - c[i]) <= p["max_ext_atr"] * a
        c_taban = (not p["use_base"]) or (a > 0 and (resistance[i] - support[i]) <= p["max_base_atr"] * a)

        fr = fib_high[i] - fib_low[i]
        fib_gecerli = (not math.isnan(fr)) and fr > 0
        yukari = low_ago[i] > high_ago[i]
        ha, la = high_ago[i], low_ago[i]
        pb_low = float(np.min(l[i - ha:i])) if (ha >= 1 and i - ha >= 0) else np.nan
        pb_high = float(np.max(h[i - la:i])) if (la >= 1 and i - la >= 0) else np.nan
        if (not p["use_fib"]) or (not fib_gecerli):
            c_fib_l = c_fib_s = True
        else:
            c_fib_l = ((math.isnan(pb_low) or pb_low >= fib_high[i] - 0.618 * fr) if yukari
                       else c[i] >= fib_low[i] + 0.618 * fr)
            c_fib_s = ((math.isnan(pb_high) or pb_high <= fib_low[i] + 0.618 * fr) if not yukari
                       else c[i] <= fib_high[i] - 0.618 * fr)

        yum_l = int(bool(L6)) + int(bool(L8)) + int(bool(c_mum_l)) + int(bool(c_fib_l))
        yum_s = int(bool(S6)) + int(bool(S8)) + int(bool(c_mum_s)) + int(bool(c_fib_s))
        yum_ok_l = (c_mum_temel_l and yum_l >= p["min_yumusak"]) if dengeli else (L6 and L8 and c_mum_l and c_fib_l)
        yum_ok_s = (c_mum_temel_s and yum_s >= p["min_yumusak"]) if dengeli else (S6 and S8 and c_mum_s and c_fib_s)
        c_oynak = max_atr_pct <= 0 or (a / c[i] * 100) <= max_atr_pct
        aday_l = bool(long_set and c_brk_l and c_vol and c_uzama_l and c_taban and c_oynak and yum_ok_l)
        aday_s = bool(short_set and c_brk_s and c_vol and c_uzama_s and c_taban and c_oynak and yum_ok_s)
        if gen_dizi is not None and aday_s and not (gen_dizi[i] <= p["genislik_max"]):
            aday_s = False

        # kalite skoru
        s1 = (not math.isnan(vol_oran)) and vol_oran >= p["strong_vol_mult"]
        s3 = a > 0 and (resistance[i] - support[i]) <= 4 * a
        s2l = fib_gecerli and yukari and (math.isnan(pb_low) or pb_low >= fib_high[i] - 0.382 * fr)
        s2s = fib_gecerli and (not yukari) and (math.isnan(pb_high) or pb_high <= fib_low[i] + 0.382 * fr)
        s4l = (not mkt_uygulanir) or mk_h > 0
        s4s = (not mkt_uygulanir) or mk_h < 0
        skor_l = int(bool(s1)) + int(bool(s2l)) + int(bool(s3)) + int(bool(s4l)) + int(close_pos >= 0.8)
        skor_s = int(bool(s1)) + int(bool(s2s)) + int(bool(s3)) + int(bool(s4s)) + int(close_pos <= 0.2)
        kalite_l = "A" if skor_l >= 4 else "B" if skor_l >= 2 else "C"
        kalite_s = "A" if skor_s >= 4 else "B" if skor_s >= 2 else "C"
        mk = p["min_kalite"]
        kal_ok_l = mk == "C" or (skor_l >= 2 if mk == "B" else skor_l >= 4)
        kal_ok_s = mk == "C" or (skor_s >= 2 if mk == "B" else skor_s >= 4)

        # pivot engelleri (bu barda onaylananlar dahil)
        if not math.isnan(ph_room[i]):
            direncler.append(ph_room[i])
            if len(direncler) > 30:
                direncler.pop(0)
        if not math.isnan(pl_room[i]):
            destekler.append(pl_room[i])
            if len(destekler) > 30:
                destekler.pop(0)

        pos_open_basta = pos is not None

        # ---------------- CIKISLAR
        if pos is not None and i > pos["bar"]:
            isL = pos["yon"] == 1
            d = pos["yon"]
            cikis = np.nan
            neden = None
            stop_dokundu = l[i] <= pos["stop"] if isL else h[i] >= pos["stop"]
            if stop_dokundu:
                cikis = min(pos["stop"], o[i]) if isL else max(pos["stop"], o[i])
                neden = "STOP_TP1" if pos["tp1_done"] else "STOP"
            else:
                tp1_dok = h[i] >= pos["tp1"] if isL else l[i] <= pos["tp1"]
                if not pos["tp1_done"] and tp1_dok:
                    pos["tp1_done"] = True
                    dolum = max(pos["tp1"], o[i]) if isL else min(pos["tp1"], o[i])
                    pos["real_r"] += tp1_pct * d * (dolum - pos["giris"]) / pos["risk"]
                    be = pos["giris"] + d * p["be_buf_r"] * pos["risk"]
                    pos["stop"] = max(pos["stop"], be) if isL else min(pos["stop"], be)
                    olaylar.append(Olay(ot[i], "TP1", d, {"fiyat": dolum, "yeni_stop": pos["stop"],
                                                          "giris": pos["giris"], "tp2": pos["tp2"]}))
                if (not pos["tp1_done"]) and p["erken_be_r"] > 0 and \
                        (h[i] >= pos["giris"] + p["erken_be_r"] * pos["risk"] if isL
                         else l[i] <= pos["giris"] - p["erken_be_r"] * pos["risk"]):
                    pos["stop"] = max(pos["stop"], pos["giris"]) if isL else min(pos["stop"], pos["giris"])
                tp2_dok = h[i] >= pos["tp2"] if isL else l[i] <= pos["tp2"]
                trend_ters = c[i] < tr_ema[i] if isL else c[i] > tr_ema[i]
                if tp2_dok:
                    cikis = max(pos["tp2"], o[i]) if isL else min(pos["tp2"], o[i])
                    neden = "TP2"
                elif p["basarisiz_cikis"] and (not pos["tp1_done"]) and not math.isnan(pos.get("seviye", np.nan)) \
                        and (p["bc_bar"] <= 0 or (i - pos["bar"]) <= p["bc_bar"]) \
                        and d * (c[i] - pos["seviye"]) < -p["bc_atr"] * a:
                    cikis = c[i]
                    neden = "BASARISIZ"
                elif p["use_time_stop"] and (not pos["tp1_done"]) and (i - pos["bar"]) >= p["time_stop_bars"] \
                        and d * (c[i] - pos["giris"]) < p["time_stop_min_r"] * pos["risk"]:
                    cikis = c[i]
                    neden = "ZAMAN"
                elif p["use_trend_exit"] and pos["tp1_done"] and trend_ters:
                    cikis = c[i]
                    neden = "TREND"
            if math.isnan(cikis):
                pos["hh"] = max(pos["hh"], h[i])
                pos["ll"] = min(pos["ll"], l[i])
                if pos["tp1_done"]:
                    if isL:
                        t = pos["hh"] - p["trail_atr_mult"] * a
                        if t > pos["stop"]:
                            pos["stop"] = t
                    else:
                        t = pos["ll"] + p["trail_atr_mult"] * a
                        if t < pos["stop"]:
                            pos["stop"] = t
            else:
                kalan = (1 - tp1_pct) if pos["tp1_done"] else 1.0
                pos["real_r"] += kalan * d * (cikis - pos["giris"]) / pos["risk"]
                pos["real_r"] -= 2 * kom * pos["giris"] / pos["risk"]
                sonuc_r = pos["real_r"]
                if neden in ("STOP", "STOP_TP1") and sonuc_r < 0:
                    son_stop_bar = i
                islem = {
                    "symbol": sembol, "yon": d, "tip": pos["tip"], "kalite": pos["kalite"],
                    "giris_zaman": pos["zaman"], "cikis_zaman": ot[i], "giris": pos["giris"],
                    "cikis": cikis, "stop_ilk": pos["stop_ilk"], "tp1": pos["tp1"], "tp2": pos["tp2"],
                    "tp1_done": pos["tp1_done"], "neden": neden, "sonuc_r": sonuc_r,
                    "bar_sayisi": i - pos["bar"],
                }
                islemler.append(islem)
                olaylar.append(Olay(ot[i], "CIKIS", d, dict(islem)))
                pos = None

        # ---------------- GIRIS ZAMANLAMASI
        giris_sinyal = False
        g_dir = 0
        g_tip = ""
        g_kal = ""
        g_sev = np.nan
        if not pos_open_basta:
            if pend is not None and i > pend["bar"]:
                pL = pend["yon"] == 1
                tol = p["retest_tol_atr"] * a
                basarisiz = c[i] < pend["seviye"] - p["fail_atr"] * a if pL else c[i] > pend["seviye"] + p["fail_atr"] * a
                retest_l = l[i] <= pend["seviye"] + tol and c[i] > pend["seviye"] and c[i] > o[i] and close_pos >= 0.5 and long_set
                retest_s = h[i] >= pend["seviye"] - tol and c[i] < pend["seviye"] and c[i] < o[i] and close_pos <= 0.5 and short_set
                teyit_l = p["use_teyit"] and c[i] > pend["uc"] and c[i] > o[i] and close_pos >= 0.5 and long_set and c_uzama_l
                teyit_s = p["use_teyit"] and c[i] < pend["uc"] and c[i] < o[i] and close_pos <= 0.5 and short_set and c_uzama_s
                if basarisiz:
                    olaylar.append(Olay(ot[i], "SAHTE", pend["yon"], {"seviye": pend["seviye"]}))
                    pend = None
                elif i - pend["bar"] > p["retest_bars"]:
                    olaylar.append(Olay(ot[i], "ZAMAN_ASIMI", pend["yon"], {"seviye": pend["seviye"]}))
                    pend = None
                elif (retest_l if pL else retest_s):
                    giris_sinyal, g_dir, g_tip, g_kal, g_sev = True, pend["yon"], "RETEST", pend["kalite"], pend["seviye"]
                    pend = None
                elif (teyit_l if pL else teyit_s):
                    giris_sinyal, g_dir, g_tip, g_kal, g_sev = True, pend["yon"], "TEYIT", pend["kalite"], pend["seviye"]
                    pend = None
            if (not giris_sinyal) and ((aday_l and kal_ok_l) or (aday_s and kal_ok_s)):
                d = 1 if (aday_l and kal_ok_l) else -1
                guclu = ((math.isnan(vol_oran) and False) or (not math.isnan(vol_oran) and vol_oran >= p["strong_vol_mult"])) \
                    and (close_pos >= 0.75 if d == 1 else close_pos <= 0.25)
                harf = kalite_l if d == 1 else kalite_s
                em = p["entry_mode"]
                if em == "Kirilim kapanisi" or (em == "Hibrit" and guclu):
                    giris_sinyal, g_dir = True, d
                    g_tip = "GUCLU KIRILIM" if guclu else "KIRILIM"
                    g_kal = harf
                    g_sev = resistance[i] if d == 1 else support[i]
                    pend = None
                else:
                    pend = {"yon": d, "seviye": resistance[i] if d == 1 else support[i],
                            "uc": h[i] if d == 1 else l[i], "bar": i, "kalite": harf, "zaman": ot[i]}
                    olaylar.append(Olay(ot[i], "KIRILIM", d, {"seviye": pend["seviye"], "uc": pend["uc"],
                                                              "kalite": harf, "kapanis": c[i]}))

        if giris_sinyal and ((giris_bas is not None and ot[i] < giris_bas) or (giris_bit is not None and ot[i] > giris_bit)):
            giris_sinyal = False

        # ---------------- STOP / TP
        if giris_sinyal:
            gL = g_dir == 1
            giris = c[i]
            yapi_stop = swing_low[i] - p["stop_buf_atr"] * a if gL else swing_high[i] + p["stop_buf_atr"] * a
            if p["seviye_stop_atr"] > 0 and not math.isnan(g_sev):
                sev_stop = g_sev - g_dir * p["seviye_stop_atr"] * a
                yapi_stop = max(yapi_stop, sev_stop) if gL else min(yapi_stop, sev_stop)
            yapisal_risk = giris - yapi_stop if gL else yapi_stop - giris
            rsk = max(yapisal_risk, p["min_stop_atr"] * a)
            risk_pct = rsk / giris * 100
            tp_off = p["tp_offset_atr"] * a

            tp1 = giris + g_dir * p["tp1_r"] * rsk
            tp1_kay = "R"
            if p["use_fib_tp"]:
                L1f = fib_ustu(i, giris + p["tp1_min_r"] * rsk + tp_off) if gL else fib_alti(i, giris - p["tp1_min_r"] * rsk - tp_off)
                if not math.isnan(L1f):
                    aday1 = L1f - g_dir * tp_off
                    if abs(aday1 - giris) <= p["tp1_max_r"] * rsk:
                        tp1, tp1_kay = aday1, "Fib"

            red = None
            engel = tavan(giris) if gL else zemin(giris)
            engel_m = np.nan if math.isnan(engel) else abs(engel - giris)
            if rsk > p["max_stop_atr"] * a:
                red = f"Stop cok genis ({rsk / a:.1f} ATR)"
            elif risk_pct > p["max_risk_pct"]:
                red = f"Stop %{risk_pct:.1f} > %{p['max_risk_pct']:.1f}"
            elif p["use_room"] and not math.isnan(engel) and engel_m < p["min_room_r"] * rsk:
                red = ("Ust direnc" if gL else "Alt destek") + f" cok yakin ({engel_m / rsk:.1f}R)"

            if red is None and p["use_room"] and not math.isnan(engel):
                onu = engel - g_dir * tp_off
                if (onu < tp1) if gL else (onu > tp1):
                    tp1, tp1_kay = onu, ("Direnc" if gL else "Destek")

            tp2_m = max(max(tp2_r, p["tp1_r"] + 0.5) * rsk, abs(tp1 - giris) + 0.5 * rsk)
            tp2 = giris + g_dir * tp2_m
            tp2_kay = "R"
            if p["use_fib_tp"]:
                L2f = fib_ustu(i, tp2 + tp_off) if gL else fib_alti(i, tp2 - tp_off)
                if not math.isnan(L2f):
                    aday2 = L2f - g_dir * tp_off
                    if abs(aday2 - giris) <= p["tp2_max_r"] * rsk:
                        tp2, tp2_kay = aday2, "Fib"
            if (not gL) and tp2 <= 0:
                red = "TP2 hesaplanamadi"

            if red is not None:
                olaylar.append(Olay(ot[i], "RED", g_dir, {"neden": red, "tip": g_tip, "kapanis": giris}))
            else:
                stop = giris - g_dir * rsk
                pos = {
                    "yon": g_dir, "giris": giris, "risk": rsk, "stop": stop, "stop_ilk": stop,
                    "tp1": tp1, "tp2": tp2, "hh": h[i], "ll": l[i], "real_r": 0.0, "tp1_done": False,
                    "bar": i, "zaman": ot[i], "tip": g_tip, "kalite": g_kal, "seviye": g_sev,
                    "tp1_kay": tp1_kay, "tp2_kay": tp2_kay, "risk_pct": risk_pct,
                    "poz_pct": min(p["hesap_risk"] / risk_pct * 100, 100),
                }
                olaylar.append(Olay(ot[i], "GIRIS", g_dir, {k: pos[k] for k in (
                    "giris", "stop", "tp1", "tp2", "tip", "kalite", "tp1_kay", "tp2_kay", "risk_pct", "poz_pct", "risk")}))

        if i == n - 1:
            filtre_son = {
                "long_hazir": bool(long_set), "short_hazir": bool(short_set),
                "btc_ust200": bool(btc_ust200), "piyasa_long": bool(L1), "piyasa_short": bool(S1),
                "direnc": float(resistance[i]) if not math.isnan(resistance[i]) else None,
                "destek": float(support[i]) if not math.isnan(support[i]) else None,
                "atr": float(a) if not math.isnan(a) else None,
            }

    acik = None
    if pos is not None:
        acik = {k: (str(v) if isinstance(v, pd.Timestamp) else v) for k, v in pos.items()}
        son = c[-1]
        kalan = (1 - tp1_pct) if pos["tp1_done"] else 1.0
        acik["anlik_r"] = pos["real_r"] + kalan * pos["yon"] * (son - pos["giris"]) / pos["risk"]
    bekleyen = None
    if pend is not None:
        bekleyen = {k: (str(v) if isinstance(v, pd.Timestamp) else v) for k, v in pend.items()}

    return Sonuc(olaylar, islemler, acik, bekleyen,
                 ot.iloc[-1] if n else None, float(c[-1]) if n else None, filtre_son)


def _pine_min(a, b):
    # Pine math.min: herhangi biri na ise na
    if math.isnan(a) or math.isnan(b):
        return np.nan
    return min(a, b)


def _pine_max(a, b):
    if math.isnan(a) or math.isnan(b):
        return np.nan
    return max(a, b)
