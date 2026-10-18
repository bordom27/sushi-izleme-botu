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
    "btc_long_ema": 200,            # long_sart'taki BTC gunluk EMA uzunlugu
    "short_sart": "Kapali",         # "Kapali" | "BTC < EMA200" | "Coin < EMA200"
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
    "vol_mult": 2.0,
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
    "use_fib": True,
    "fib_len": 89,
    "use_fib_tp": True,

    # 6) Risk
    "atr_len": 14,
    "stop_lookback": 5,
    "stop_buf_atr": 0.2,
    "seviye_stop_atr": 1.5,
    "min_stop_atr": 1.0,
    "max_stop_atr": 3.0,
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
    "tp1_pct": 70.0,
    "be_buf_r": 0.1,
    "trail_atr_mult": 2.5,
    "use_time_stop": True,
    "time_stop_bars": 20,
    "time_stop_min_r": 0.5,
    "use_trend_exit": False,
    "erken_be_r": 0.0,

    # 18) Yeni fikirler (varsayilan KAPALI)
    "tp2_yok": False,               # True: TP2 yok, kalan kisim sadece iz suren stopla
    "gunluk_ema_onay": 0,           # >0: long icin gunluk kapanis > gunluk EMA(N), short icin altinda
    "btc_vol_rejim": "",            # "" | "yuksek" | "dusuk": BTC 4s ATR% kendi 180 mumluk medyaninin ustu/alti

    # 17) Seviye tanimi (varsayilan = son R mumun en yuksek fitili)
    "seviye_tipi": "fitil",         # "fitil" | "kapanis" (govde kapanislarinin en yuksegi)
    "gunluk_seviye": 0,             # >0: direnc = son N kapanmis gunun en yuksek degeri (gunluk veri gerekir)
    "rsi_dinamik": "",              # "" | "ust" | "orta" | "ikisi": RSI eşikleri yerine RSI'nin 200 mumluk Bollinger bandi
    "z_max": 0.0,                   # >0: kapanisin z-skoru (SMA z_len'den sapma / std) bu degeri asarsa red
    "z_len": 20,
    "er_min": 0.0,                  # >0: Kaufman verimlilik orani (er_len) en az bu kadar
    "er_len": 20,
    "chop_max": 0.0,                # >0: Choppiness index (14) bu degerden kucuk olmali
    "fvg_atr": 0.0,                 # >0: girisin bu kadar ATR ustunde/icinde doldurulmamis ters FVG varsa red
    "fvg_bak": 300,
    "kor_min": -9.0,                # > -1: coin ile BTC 4s getiri korelasyonu (kor_len) en az bu kadar
    "kor_len": 30,
    "ters_l": None,                 # pd.Series (zaman -> evrende son N mumda ASAGI kirilim yapan coin sayisi); long filtresi
    "ters_s": None,                 # pd.Series (yukari kirilim yapan coin sayisi); short filtresi
    "ters_max": -1, 
    "l_seri": None,                 # pd.Series: long icin genislik olcusu (ayni yon kirilim sayisi / EMA50 ustu orani)
    "l_min": -1.0,                  # >=0: l_seri bu degerin altindaysa long yok                # >=0: bu sayidan fazlaysa sinyal yok
    "rs_bar": 0,                    # >0: goreli guc (coin getirisi - BTC getirisi, son rs_bar mum)
    "rs_min": 0.0,                  # long: rs > rs_min, short: rs < -rs_min (oran, 0.05 = %5)
    "yeniden_giris": 0,             # >0: basarisiz kirilim cikisindan sonra bu kadar mum icinde seviye geri alinirsa tekrar gir
    "yeniden_buf_atr": 0.1,
    "min_seviye_yas": 0,            # >0: kirilan tepe/dip en az bu kadar mum once olusmus olmali (dunku mumun tepesi 'direnc' sayilmaz)
    "min_test": 0,                  # >0: seviye en az bu kadar pivotla test edilmis olmali
    "test_tol_atr": 0.5,

    # 16) Basarisiz kirilim cikisi (varsayilan KAPALI): TP1 alinmadan, girisin ilk K mumunda
    #     kapanis kirilan seviyenin x ATR gerisine donerse stopu beklemeden kapanista cik.
    "basarisiz_cikis": False,
    "bc_bar": 6,                    # kac mum boyunca kontrol edilir (0 = TP1'e kadar her zaman)
    "bc_atr": 0.0,                  # seviyenin bu kadar ATR gerisinde kapanis gerekir

    # 14) Kucuk zaman diliminde giris (varsayilan KAPALI): 4s sinyalden sonra 1s grafikte
    #     geri cekilme + mikro yapi kirilimi (1s mum onceki 1s tepesinin ustunde kapanir) ile giris.
    "ltf_giris": "",                # "" | "geri_cekilme" (0.382 geri cekilme sart) | "ilk_dusus" (ilk kirmizi 1s mum yeter)
    "ltf_max_bar4": 3,              # en fazla kac 4s mum beklenir
    "ltf_stop_buf": 0.1,            # 1s dibinin altina tampon (4s ATR)
    "ltf_min_stop": 0.5,            # min stop mesafesi (4s ATR)
    # 15) Trend ici geri cekilme sinyali (varsayilan KAPALI): EMA21'e dokunup donus mumu
    "geri_cekilme": False,
    "gc_taze_bar": 10,              # son 20 mumun tepesi en fazla bu kadar mum once yapilmis olmali (taze trend)

    # 13) Limit emirle giris (varsayilan KAPALI): sinyal mumunda kapanistan girmek yerine
    #     geri cekilmede limit emir. Dolmazsa / once TP1'e giderse iptal.
    "limit_mod": "",                # "" | "seviye" | "orta" | "seviye_atr"
    "limit_atr": 0.3,               # seviye_atr: kirilan seviye + bu kadar ATR (long)
    "limit_bar": 6,                 # emir en fazla bu kadar mum bekler

    # 12) Kovalama korumasi (varsayilan KAPALI)
    "max_kirilim_atr": 0.0,         # kapanis kirilan seviyenin en fazla bu kadar ATR otesinde (0 = kapali)
    "max_onceki_atr": 0.0,          # son 10 mumun dibinden (short: tepesinden) kapanisa hareket en fazla bu kadar ATR

    # 11) Formasyonlar (varsayilan KAPALI - acikken TradingView gostergesinde de olmali)
    "formasyonlar": (),            # "CIFT", "OBO", "TREND", "UCGEN", "BAYRAK"
    "form_pivot": 5,                # formasyon pivot hassasiyeti (bar)
    "form_vol_mult": 1.5,           # formasyon kiriliminda hacim esigi (x ortalama, 0 = yok)
    "form_trend_serbest": False,    # True: donus formasyonlarinda EMA dizilimi aranmaz (piyasa + RSI yeter)
    "sadece_formasyon": False,      # True: yatay kirilimlar kapali (sadece formasyon sinyali) - test icin

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
def simule_et(symbol: str, df: pd.DataFrame, gunluk: pd.DataFrame | None,
              btc_gunluk: pd.DataFrame | None, btc_4h: pd.DataFrame | None,
              haftalik: pd.DataFrame | None = None, params: dict | None = None,
              giris_bas: pd.Timestamp | None = None, giris_bit: pd.Timestamp | None = None,
              saatlik: pd.DataFrame | None = None) -> Sonuc:
    """
    df          : grafik TF (4 saat) - SADECE KAPANMIS mumlar. Kolonlar: open_time, open, high, low, close, volume
    gunluk      : coinin gunluk mumlari (Coin > EMA200 / ana trend / gunluk MACD icin)
    btc_gunluk  : BTCUSDT gunluk (piyasa elegi)
    btc_4h      : BTCUSDT grafik TF (ani hareket / panik elegi)
    haftalik    : coinin haftalik mumlari (sadece haftalik MACD / ana trend aciksa gerekir)
    giris_bas/bit: sadece bu aralikta yeni islem acilir (test icin)
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
    if p["seviye_tipi"] == "kapanis":
        resistance = np.concatenate([[np.nan], highest(c, R)[:-1]])
        support = np.concatenate([[np.nan], lowest(c, R)[:-1]])
    else:
        resistance = np.concatenate([[np.nan], highest(h, R)[:-1]])
        support = np.concatenate([[np.nan], lowest(l, R)[:-1]])
    MT = p["min_test"]
    if MT > 0:
        ph5 = pivot(h, 5, True)
        pl5 = pivot(l, 5, False)
    vol_avg = np.concatenate([[np.nan], sma(v, p["vol_len"])[:-1]])

    F = p["fib_len"]
    fib_low = np.concatenate([[np.nan], lowest(l, F)[:-1]])
    fib_high = np.concatenate([[np.nan], highest(h, F)[:-1]])
    lb = bars_offset(l, F, True)
    hb = bars_offset(h, F, False)
    low_ago = np.concatenate([[0], np.nan_to_num(lb[:-1], nan=0)]).astype(int)
    high_ago = np.concatenate([[0], np.nan_to_num(hb[:-1], nan=0)]).astype(int)

    FORMLAR = set(p["formasyonlar"])
    FP = p["form_pivot"]
    ph_f = pivot(h, FP, True) if FORMLAR else None
    pl_f = pivot(l, FP, False) if FORMLAR else None
    fph: list = []   # (bar, fiyat) onayli pivot tepeler
    fpl: list = []
    form_kullanildi: set = set()
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

    GS = p["gunluk_seviye"]
    if GS > 0 and gunluk is not None and len(gunluk):
        gh_ = pd.Series(gunluk["high"].to_numpy(float)).rolling(GS).max().to_numpy()
        gl_ = pd.Series(gunluk["low"].to_numpy(float)).rolling(GS).min().to_numpy()
        GL = _htf_onceki(ot, gunluk, "D", {"h": gh_, "l": gl_})
        resistance = GL["h"]
        support = GL["l"]

    if btc_gunluk is not None and len(btc_gunluk):
        bc = btc_gunluk["close"].to_numpy(float)
        _, _, bh = macd(bc, p["macd_fast"], p["macd_slow"], p["macd_signal"])
        M = _htf_onceki(ot, btc_gunluk, "D", {"c": bc, "e": ema(bc, p["mkt_ema_len"]), "h": bh, "e2": ema(bc, p["btc_long_ema"])})
    else:
        M = {k: np.full(n, np.nan) for k in ("c", "e", "h", "e2")}

    GE = p["gunluk_ema_onay"]
    if GE > 0 and gunluk is not None and len(gunluk):
        gcl = gunluk["close"].to_numpy(float)
        GEo = _htf_onceki(ot, gunluk, "D", {"c": gcl, "e": ema(gcl, GE)})
    else:
        GEo = None
    BVR = p["btc_vol_rejim"]
    btc_yuksek_vol = np.full(n, np.nan)
    if BVR and btc_4h is not None and len(btc_4h):
        b4_ = btc_4h.reset_index(drop=True)
        bh, bl, bc_ = (b4_[k_].to_numpy(float) for k_ in ("high", "low", "close"))
        bap = rma(true_range(bh, bl, bc_, True), 14) / bc_
        med = pd.Series(bap).rolling(180, min_periods=60).median().to_numpy()
        btc_yuksek_vol = pd.Series(np.where(np.isnan(med), np.nan, (bap > med).astype(float)),
                                   index=pd.to_datetime(b4_["open_time"])).reindex(ot).to_numpy(float)

    mk_roc = np.full(n, np.nan)
    if btc_4h is not None and len(btc_4h):
        b4 = btc_4h.reset_index(drop=True)
        bcl = b4["close"].to_numpy(float)
        pb = p["panic_bars"]
        roc = np.full(len(bcl), np.nan)
        roc[pb:] = 100 * (bcl[pb:] - bcl[:-pb]) / bcl[:-pb]
        s = pd.Series(roc, index=pd.to_datetime(b4["open_time"]))
        mk_roc = s.reindex(ot).to_numpy(float)

    _cs = pd.Series(c)
    _rs = pd.Series(rsi_v)
    rbb_m = _rs.rolling(200).mean().to_numpy(); rbb_s = _rs.rolling(200).std(ddof=0).to_numpy()
    rbb_u, rbb_l = rbb_m + 2 * rbb_s, rbb_m - 2 * rbb_s
    z_dizi = ((_cs - _cs.rolling(p["z_len"]).mean()) / _cs.rolling(p["z_len"]).std(ddof=0)).to_numpy()
    _E = p["er_len"]
    er_dizi = (( _cs - _cs.shift(_E)).abs() / _cs.diff().abs().rolling(_E).sum()).to_numpy()
    _tr1 = pd.Series(true_range(h, l, c, True))
    chop_dizi = (100 * np.log10(_tr1.rolling(14).sum() / (pd.Series(h).rolling(14).max() - pd.Series(l).rolling(14).min())) / np.log10(14)).to_numpy()
    kor_dizi = np.full(n, np.nan)
    if p["kor_min"] > -1 and btc_4h is not None and len(btc_4h):
        _b2 = btc_4h.reset_index(drop=True)
        _bc2 = pd.Series(_b2["close"].to_numpy(float), index=pd.to_datetime(_b2["open_time"])).reindex(ot).reset_index(drop=True)
        kor_dizi = _cs.pct_change().rolling(p["kor_len"]).corr(_bc2.pct_change()).to_numpy()
    fvg_ayi, fvg_boga = [], []   # (alt, ust, bar)
    TM = p["ters_max"]
    l_dizi = p["l_seri"].reindex(ot).to_numpy(float) if (p["l_min"] >= 0 and p["l_seri"] is not None) else None
    ters_l = p["ters_l"].reindex(ot).to_numpy(float) if (TM >= 0 and p["ters_l"] is not None) else None
    ters_s = p["ters_s"].reindex(ot).to_numpy(float) if (TM >= 0 and p["ters_s"] is not None) else None

    rs_dizi = np.full(n, np.nan)
    if p["rs_bar"] > 0 and btc_4h is not None and len(btc_4h):
        _b = btc_4h.reset_index(drop=True)
        _bc = pd.Series(_b["close"].to_numpy(float), index=pd.to_datetime(_b["open_time"])).reindex(ot).to_numpy(float)
        N_ = p["rs_bar"]
        rs_dizi[N_:] = (c[N_:] / c[:-N_] - 1) - (_bc[N_:] / _bc[:-N_] - 1)

    LTF = bool(p["ltf_giris"]) and saatlik is not None and len(saatlik) > 0
    if LTF:
        s1 = saatlik.reset_index(drop=True)
        t1 = pd.to_datetime(s1["open_time"]).to_numpy()
        o1, h1, l1, c1 = (s1[k_].to_numpy(float) for k_ in ("open", "high", "low", "close"))
        ot_np = ot.to_numpy()
        bas1 = np.searchsorted(t1, ot_np)
        bit1 = np.searchsorted(t1, ot_np + np.timedelta64(4, "h"))
    lt = None
    min_isinma = max(R, p["macd_slow"] + p["macd_signal"], p["atr_len"], p["trend_ema"], p["vol_len"], F) + 5

    # --- durum
    olaylar: list[Olay] = []
    islemler: list[dict] = []
    direncler: list[float] = []
    destekler: list[float] = []
    son_stop_bar = None

    pos = None          # dict
    lim = None          # bekleyen limit emir
    pend = None         # dict
    yeniden = None      # basarisiz kirilim sonrasi yeniden giris adayi
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

    def cizgi(p1, p2, x):
        (x1, y1), (x2, y2) = p1, p2
        return y1 + (y2 - y1) * (x - x1) / (x2 - x1)

    def formasyon_ara(i, a):
        """Bar i'de (kapanista) taze formasyon kirilimi: [(yon, seviye, tip, anahtar)]"""
        out = []
        if not (a > 0) or i < 2:
            return out
        # --- CIFT TEPE / CIFT DIP
        if "CIFT" in FORMLAR:
            if len(fph) >= 2:
                (b1, p1), (b2, p2) = fph[-2], fph[-1]
                if abs(p1 - p2) <= 0.6 * a and 8 <= b2 - b1 <= 60 and i - b2 <= 30:
                    t = float(np.min(l[b1:b2 + 1]))
                    if min(p1, p2) - t >= 2 * a and c[i] < t and c[i - 1] >= t:
                        out.append((-1, t, "CIFT TEPE", ("CT", b1, b2)))
            if len(fpl) >= 2:
                (b1, p1), (b2, p2) = fpl[-2], fpl[-1]
                if abs(p1 - p2) <= 0.6 * a and 8 <= b2 - b1 <= 60 and i - b2 <= 30:
                    t = float(np.max(h[b1:b2 + 1]))
                    if t - max(p1, p2) >= 2 * a and c[i] > t and c[i - 1] <= t:
                        out.append((1, t, "CIFT DIP", ("CD", b1, b2)))
        # --- OBO / TOBO
        if "OBO" in FORMLAR:
            if len(fph) >= 3:
                (ba, pa), (bb, pb), (bc, pc) = fph[-3:]
                if pb > pa + 0.5 * a and pb > pc + 0.5 * a and abs(pa - pc) <= 1.5 * a \
                        and 5 <= bb - ba <= 50 and 5 <= bc - bb <= 50 and i - bc <= 25:
                    k1 = ba + int(np.argmin(l[ba:bb + 1])); k2 = bb + int(np.argmin(l[bb:bc + 1]))
                    if k2 > k1:
                        n0 = cizgi((k1, l[k1]), (k2, l[k2]), i)
                        n1 = cizgi((k1, l[k1]), (k2, l[k2]), i - 1)
                        if c[i] < n0 and c[i - 1] >= n1:
                            out.append((-1, n0, "OBO", ("OBO", ba, bb, bc)))
            if len(fpl) >= 3:
                (ba, pa), (bb, pb), (bc, pc) = fpl[-3:]
                if pb < pa - 0.5 * a and pb < pc - 0.5 * a and abs(pa - pc) <= 1.5 * a \
                        and 5 <= bb - ba <= 50 and 5 <= bc - bb <= 50 and i - bc <= 25:
                    k1 = ba + int(np.argmax(h[ba:bb + 1])); k2 = bb + int(np.argmax(h[bb:bc + 1]))
                    if k2 > k1:
                        n0 = cizgi((k1, h[k1]), (k2, h[k2]), i)
                        n1 = cizgi((k1, h[k1]), (k2, h[k2]), i - 1)
                        if c[i] > n0 and c[i - 1] <= n1:
                            out.append((1, n0, "TOBO", ("TOBO", ba, bb, bc)))
        # --- EGIK TREND CIZGISI ve UCGEN/KAMA
        if "TREND" in FORMLAR or "UCGEN" in FORMLAR:
            ust = alt = None
            if len(fph) >= 2:
                (b1, p1), (b2, p2) = fph[-2], fph[-1]
                if p2 < p1 - 0.3 * a and b2 - b1 >= 8 and i - b1 <= 120:
                    seg = c[b2 + 1:i]
                    xs = np.arange(b2 + 1, i)
                    if len(seg) == 0 or np.all(seg <= cizgi((b1, p1), (b2, p2), xs)):
                        ust = ((b1, p1), (b2, p2))
            if len(fpl) >= 2:
                (b1, p1), (b2, p2) = fpl[-2], fpl[-1]
                if p2 > p1 + 0.3 * a and b2 - b1 >= 8 and i - b1 <= 120:
                    seg = c[b2 + 1:i]
                    xs = np.arange(b2 + 1, i)
                    if len(seg) == 0 or np.all(seg >= cizgi((b1, p1), (b2, p2), xs)):
                        alt = ((b1, p1), (b2, p2))
            ucgen = ust is not None and alt is not None and max(ust[0][0], alt[0][0]) >= i - 80
            for yon, hat in ((1, ust), (-1, alt)):
                if hat is None:
                    continue
                v0 = cizgi(hat[0], hat[1], i)
                v1 = cizgi(hat[0], hat[1], i - 1)
                kir = (c[i] > v0 + 0.1 * a and c[i - 1] <= v1) if yon == 1 else (c[i] < v0 - 0.1 * a and c[i - 1] >= v1)
                if not kir:
                    continue
                if ucgen and "UCGEN" in FORMLAR:
                    out.append((yon, v0, "UCGEN", ("UC", yon, hat[0][0], hat[1][0])))
                elif "TREND" in FORMLAR:
                    out.append((yon, v0, "TREND KIRILIMI", ("TR", yon, hat[0][0], hat[1][0])))
        # --- BAYRAK / FLAMA (guclu itki + dar duzeltme + itki yonunde kirilim)
        if "BAYRAK" in FORMLAR and i >= 40:
            w0 = i - 25
            hk = w0 + int(np.argmax(h[w0:i]))   # itki tepesi (bar i haric)
            m = i - 1 - hk
            if 4 <= m <= 20:
                H = h[hk]
                dip = float(np.min(l[max(0, hk - 10):hk + 1]))
                itki = H - dip
                kons_dip = float(np.min(l[hk + 1:i]))
                if itki >= 4 * a and kons_dip >= H - 0.5 * itki and c[i] > H + 0.1 * a and c[i - 1] <= H:
                    out.append((1, H, "BAYRAK", ("BY", 1, hk)))
            lk = w0 + int(np.argmin(l[w0:i]))
            m = i - 1 - lk
            if 4 <= m <= 20:
                L_ = l[lk]
                tepe = float(np.max(h[max(0, lk - 10):lk + 1]))
                itki = tepe - L_
                kons_tepe = float(np.max(h[lk + 1:i]))
                if itki >= 4 * a and kons_tepe <= L_ + 0.5 * itki and c[i] < L_ - 0.1 * a and c[i - 1] >= L_:
                    out.append((-1, L_, "AYI BAYRAGI", ("BY", -1, lk)))
        return out

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
            coin_ust200 if ls == "Coin > EMA200" else (btc_ust200 or coin_ust200) if ls == "BTC veya coin > EMA200" \
            else (btc_ust200 and coin_ust200)
        ss_ = p["short_sart"]
        short_ek = True if ss_ == "Kapali" else (not btc_ust200) if ss_ == "BTC < EMA200" else (not coin_ust200)
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
        RD = p["rsi_dinamik"]
        if RD and not math.isnan(rbb_u[i]):
            if RD in ("ust", "ikisi"):
                L7 = r0 >= p["rsi_min"] and _pine_min(r0, r1) < rbb_u[i]
                S7 = r0 <= 100 - p["rsi_min"] and _pine_max(r0, r1) > rbb_l[i]
            if RD in ("orta", "ikisi"):
                L7 = L7 and r0 >= rbb_m[i]
                S7 = S7 and r0 <= rbb_m[i]
        adx2 = adx_v[i - 2] if i >= 2 else np.nan
        adx_guc = adx_v[i] >= p["adx_min"] or adx_v[i] > adx2
        L8 = (not p["use_adx"]) or (di_p[i] > di_m[i] and adx_guc)
        S8 = (not p["use_adx"]) or (di_m[i] > di_p[i] and adx_guc)
        c_cool = son_stop_bar is None or (i - son_stop_bar) >= p["cooldown_bars"]
        isinma = i >= min_isinma
        e9 = c_cool and isinma

        long_set = long_izin and long_ek and L1 and L2 and L3 and L4 and L5 and L7 and e9 and (dengeli or (L6 and L8))
        short_set = short_izin and short_ek and S1 and S2 and S3 and S4 and S5 and S7 and e9 and (dengeli or (S6 and S8))
        if GEo is not None:
            gc_, ge_ = GEo["c"][i], GEo["e"][i]
            if math.isnan(gc_) or math.isnan(ge_):
                long_set = short_set = False
            else:
                long_set = long_set and gc_ > ge_
                short_set = short_set and gc_ < ge_
        if BVR:
            bv = btc_yuksek_vol[i]
            ok_ = (not math.isnan(bv)) and ((bv == 1.0) if BVR == "yuksek" else (bv == 0.0))
            long_set = long_set and ok_
            short_set = short_set and ok_

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
        if p["sadece_formasyon"]:
            aday_l = aday_s = False
        if MT > 0 and (aday_l or aday_s) and a > 0:
            tol_ = p["test_tol_atr"] * a
            j0 = max(0, i - R + 5)
            if aday_l:
                n_t = sum(1 for j in range(j0, i + 1) if not math.isnan(ph5[j]) and abs(ph5[j] - resistance[i]) <= tol_)
                aday_l = n_t >= MT
            if aday_s:
                n_t = sum(1 for j in range(j0, i + 1) if not math.isnan(pl5[j]) and abs(pl5[j] - support[i]) <= tol_)
                aday_s = n_t >= MT
        # FVG listelerini guncelle (bu barda olusan + dolanlari sil)
        if p["fvg_atr"] > 0:
            if i >= 2 and h[i] < l[i - 2]:
                fvg_ayi.append((h[i], l[i - 2], i))
            if i >= 2 and l[i] > h[i - 2]:
                fvg_boga.append((h[i - 2], l[i], i))
            fvg_ayi = [f for f in fvg_ayi if h[i] < f[1] and i - f[2] <= p["fvg_bak"]]
            fvg_boga = [f for f in fvg_boga if l[i] > f[0] and i - f[2] <= p["fvg_bak"]]
            if aday_l and a > 0 and any(f[1] > c[i] and f[0] < c[i] + p["fvg_atr"] * a for f in fvg_ayi):
                aday_l = False
            if aday_s and a > 0 and any(f[0] < c[i] and f[1] > c[i] - p["fvg_atr"] * a for f in fvg_boga):
                aday_s = False
        if l_dizi is not None and aday_l and not (l_dizi[i] >= p["l_min"]):
            aday_l = False
        if ters_l is not None and aday_l and not (ters_l[i] <= TM):
            aday_l = False
        if ters_s is not None and aday_s and not (ters_s[i] <= TM):
            aday_s = False
        if p["z_max"] > 0:
            zv = z_dizi[i]
            if aday_l and not math.isnan(zv) and zv > p["z_max"]:
                aday_l = False
            if aday_s and not math.isnan(zv) and zv < -p["z_max"]:
                aday_s = False
        if p["er_min"] > 0 and (aday_l or aday_s):
            if math.isnan(er_dizi[i]) or er_dizi[i] < p["er_min"]:
                aday_l = aday_s = False
        if p["chop_max"] > 0 and (aday_l or aday_s):
            if math.isnan(chop_dizi[i]) or chop_dizi[i] >= p["chop_max"]:
                aday_l = aday_s = False
        if p["kor_min"] > -1 and (aday_l or aday_s):
            if math.isnan(kor_dizi[i]) or kor_dizi[i] < p["kor_min"]:
                aday_l = aday_s = False
        if p["rs_bar"] > 0:
            rsv = rs_dizi[i]
            if aday_l and (math.isnan(rsv) or rsv <= p["rs_min"]):
                aday_l = False
            if aday_s and (math.isnan(rsv) or rsv >= -p["rs_min"]):
                aday_s = False
        if p["min_seviye_yas"] > 0 and i >= R:
            if aday_l and int(np.argmax(h[i - R:i][::-1])) < p["min_seviye_yas"]:
                aday_l = False
            if aday_s and int(np.argmin(l[i - R:i][::-1])) < p["min_seviye_yas"]:
                aday_s = False
        if p["max_kirilim_atr"] > 0 and a > 0:
            if aday_l and (c[i] - resistance[i]) > p["max_kirilim_atr"] * a:
                aday_l = False
            if aday_s and (support[i] - c[i]) > p["max_kirilim_atr"] * a:
                aday_s = False
        if p["max_onceki_atr"] > 0 and a > 0 and i >= 10:
            if aday_l and (c[i] - float(np.min(l[i - 10:i]))) > p["max_onceki_atr"] * a:
                aday_l = False
            if aday_s and (float(np.max(h[i - 10:i])) - c[i]) > p["max_onceki_atr"] * a:
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

        if FORMLAR:
            if not math.isnan(ph_f[i]):
                fph.append((i - FP, ph_f[i]))
                if len(fph) > 10:
                    fph.pop(0)
            if not math.isnan(pl_f[i]):
                fpl.append((i - FP, pl_f[i]))
                if len(fpl) > 10:
                    fpl.pop(0)

        # pivot engelleri (bu barda onaylananlar dahil)
        if not math.isnan(ph_room[i]):
            direncler.append(ph_room[i])
            if len(direncler) > 30:
                direncler.pop(0)
        if not math.isnan(pl_room[i]):
            destekler.append(pl_room[i])
            if len(destekler) > 30:
                destekler.pop(0)

        # ---------------- 1 SAATLIK GIRIS (bekleyen 4s sinyal)
        if LTF and lt is not None and pos is None and i > lt["bar"]:
            LL = lt["yon"] == 1
            dd_ = lt["yon"]
            iptal = None
            for kk in range(bas1[i], bit1[i]):
                if pos is None:
                    if (l1[kk] <= lt["stop4"]) if LL else (h1[kk] >= lt["stop4"]):
                        iptal = "stop seviyesi"; break
                    if (h1[kk] >= lt["tp1"]) if LL else (l1[kk] <= lt["tp1"]):
                        iptal = "giris olmadan TP1"; break
                    lt["uc"] = min(lt["uc"], l1[kk]) if LL else max(lt["uc"], h1[kk])
                    if not lt["cekildi"]:
                        if p["ltf_giris"] == "ilk_dusus":
                            lt["cekildi"] = (c1[kk] < o1[kk]) if LL else (c1[kk] > o1[kk])
                        else:
                            lt["cekildi"] = (l1[kk] <= lt["Z"]) if LL else (h1[kk] >= lt["Z"])
                    elif lt["onceki_uc"] is not None and (
                            (c1[kk] > lt["onceki_uc"] and c1[kk] > o1[kk]) if LL else (c1[kk] < lt["onceki_uc"] and c1[kk] < o1[kk])):
                        gir = c1[kk]
                        stp = lt["uc"] - dd_ * lt["buf"]
                        stp = max(stp, lt["stop4"]) if LL else min(stp, lt["stop4"])
                        if dd_ * (gir - stp) < lt["minstop"]:
                            stp = gir - dd_ * lt["minstop"]
                        rk = dd_ * (gir - stp)
                        if rk <= 0 or dd_ * (lt["tp1"] - gir) < 0.5 * rk:
                            iptal = "hedefe yer kalmadi"; break
                        pos = {"yon": dd_, "giris": gir, "risk": rk, "stop": stp, "stop_ilk": stp,
                               "tp1": lt["tp1"], "tp2": lt["tp2"], "hh": h1[kk], "ll": l1[kk], "real_r": 0.0,
                               "tp1_done": False, "bar": i, "zaman": ot[i], "tip": lt["tip"] + " 1S",
                               "kalite": lt["kalite"], "tp1_kay": lt["tp1_kay"], "tp2_kay": lt["tp2_kay"],
                               "risk_pct": rk / gir * 100, "poz_pct": min(p["hesap_risk"] / (rk / gir * 100) * 100, 100)}
                        olaylar.append(Olay(ot[i], "GIRIS", dd_, {k_: pos[k_] for k_ in (
                            "giris", "stop", "tp1", "tp2", "tip", "kalite", "tp1_kay", "tp2_kay", "risk_pct", "poz_pct", "risk")}))
                        lt = None
                        continue
                    lt["onceki_uc"] = h1[kk] if LL else l1[kk]
                else:
                    # ayni 4s mumun kalan 1s mumlarinda yonetim (once stop - temkinli)
                    pos["hh"] = max(pos["hh"], h1[kk]); pos["ll"] = min(pos["ll"], l1[kk])
                    if (l1[kk] <= pos["stop"]) if LL else (h1[kk] >= pos["stop"]):
                        cik = min(pos["stop"], o1[kk]) if LL else max(pos["stop"], o1[kk])
                        kalan = (1 - tp1_pct) if pos["tp1_done"] else 1.0
                        rr = pos["real_r"] + kalan * dd_ * (cik - pos["giris"]) / pos["risk"] - 2 * kom * pos["giris"] / pos["risk"]
                        islem = {"symbol": sembol, "yon": dd_, "tip": pos["tip"], "kalite": pos["kalite"],
                                 "giris_zaman": pos["zaman"], "cikis_zaman": ot[i], "giris": pos["giris"], "cikis": cik,
                                 "stop_ilk": pos["stop_ilk"], "tp1": pos["tp1"], "tp2": pos["tp2"], "tp1_done": pos["tp1_done"],
                                 "neden": "STOP_TP1" if pos["tp1_done"] else "STOP", "sonuc_r": rr, "bar_sayisi": 0}
                        islemler.append(islem); olaylar.append(Olay(ot[i], "CIKIS", dd_, dict(islem)))
                        if rr < 0:
                            son_stop_bar = i
                        pos = None
                        break
                    if not pos["tp1_done"] and ((h1[kk] >= pos["tp1"]) if LL else (l1[kk] <= pos["tp1"])):
                        pos["tp1_done"] = True
                        dol = max(pos["tp1"], o1[kk]) if LL else min(pos["tp1"], o1[kk])
                        pos["real_r"] += tp1_pct * dd_ * (dol - pos["giris"]) / pos["risk"]
                        be = pos["giris"] + dd_ * p["be_buf_r"] * pos["risk"]
                        pos["stop"] = max(pos["stop"], be) if LL else min(pos["stop"], be)
                        olaylar.append(Olay(ot[i], "TP1", dd_, {"fiyat": dol, "yeni_stop": pos["stop"],
                                                               "giris": pos["giris"], "tp2": pos["tp2"]}))
                    if pos["tp1_done"] and ((h1[kk] >= pos["tp2"]) if LL else (l1[kk] <= pos["tp2"])):
                        cik = max(pos["tp2"], o1[kk]) if LL else min(pos["tp2"], o1[kk])
                        rr = pos["real_r"] + (1 - tp1_pct) * dd_ * (cik - pos["giris"]) / pos["risk"] - 2 * kom * pos["giris"] / pos["risk"]
                        islem = {"symbol": sembol, "yon": dd_, "tip": pos["tip"], "kalite": pos["kalite"],
                                 "giris_zaman": pos["zaman"], "cikis_zaman": ot[i], "giris": pos["giris"], "cikis": cik,
                                 "stop_ilk": pos["stop_ilk"], "tp1": pos["tp1"], "tp2": pos["tp2"], "tp1_done": True,
                                 "neden": "TP2", "sonuc_r": rr, "bar_sayisi": 0}
                        islemler.append(islem); olaylar.append(Olay(ot[i], "CIKIS", dd_, dict(islem)))
                        pos = None
                        break
            if lt is not None and iptal is None and i - lt["bar"] >= p["ltf_max_bar4"]:
                iptal = "zaman asimi"
            if lt is not None and iptal is not None:
                olaylar.append(Olay(ot[i], "LTF_IPTAL", lt["yon"], {"neden": iptal}))
                lt = None

        # ---------------- BEKLEYEN LIMIT EMIR
        if lim is not None and pos is None and i > lim["bar"]:
            LL = lim["yon"] == 1
            dd_ = lim["yon"]
            dokundu = l[i] <= lim["fiyat"] if LL else h[i] >= lim["fiyat"]
            if dokundu:
                fill = min(lim["fiyat"], o[i]) if LL else max(lim["fiyat"], o[i])
                risk_ = dd_ * (fill - lim["stop"])
                if risk_ > 0:
                    pos = {
                        "yon": dd_, "giris": fill, "risk": risk_, "stop": lim["stop"], "stop_ilk": lim["stop"],
                        "tp1": lim["tp1"], "tp2": lim["tp2"], "hh": h[i], "ll": l[i], "real_r": 0.0, "tp1_done": False,
                        "bar": i, "zaman": ot[i], "tip": lim["tip"], "kalite": lim["kalite"],
                        "tp1_kay": lim["tp1_kay"], "tp2_kay": lim["tp2_kay"], "risk_pct": risk_ / fill * 100,
                        "poz_pct": min(p["hesap_risk"] / (risk_ / fill * 100) * 100, 100),
                    }
                    olaylar.append(Olay(ot[i], "LIMIT_DOLDU", dd_, {"fiyat": fill, "stop": pos["stop"],
                                                                   "tp1": pos["tp1"], "tp2": pos["tp2"]}))
                    stop_ayni = l[i] <= pos["stop"] if LL else h[i] >= pos["stop"]
                    if stop_ayni:
                        cik = pos["stop"]
                        rr = dd_ * (cik - fill) / risk_ - 2 * (p["komisyon_pct"] / 100) * fill / risk_
                        islem = {"symbol": sembol, "yon": dd_, "tip": pos["tip"], "kalite": pos["kalite"],
                                 "giris_zaman": ot[i], "cikis_zaman": ot[i], "giris": fill, "cikis": cik,
                                 "stop_ilk": pos["stop"], "tp1": pos["tp1"], "tp2": pos["tp2"], "tp1_done": False,
                                 "neden": "STOP", "sonuc_r": rr, "bar_sayisi": 0}
                        islemler.append(islem)
                        olaylar.append(Olay(ot[i], "CIKIS", dd_, dict(islem)))
                        son_stop_bar = i
                        pos = None
                lim = None
            elif (h[i] >= lim["tp1"] if LL else l[i] <= lim["tp1"]) or i - lim["bar"] >= p["limit_bar"]:
                olaylar.append(Olay(ot[i], "LIMIT_IPTAL", lim["yon"], {"fiyat": lim["fiyat"]}))
                lim = None

        pos_open_basta = pos is not None or lim is not None or lt is not None

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
                if neden == "BASARISIZ" and p["yeniden_giris"] > 0 and not pos["tip"].startswith("YENIDEN"):
                    yeniden = {"yon": d, "seviye": pos["seviye"], "bar": i, "kalite": pos["kalite"]}
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
            if (not giris_sinyal) and yeniden is not None and i > yeniden["bar"]:
                if i - yeniden["bar"] > p["yeniden_giris"]:
                    yeniden = None
                else:
                    yd = yeniden["yon"]
                    geri = yd * (c[i] - yeniden["seviye"]) > p["yeniden_buf_atr"] * a
                    mum_ok = (c[i] > o[i] and close_pos >= 0.5 and long_set) if yd == 1 else (c[i] < o[i] and close_pos <= 0.5 and short_set)
                    if geri and mum_ok:
                        giris_sinyal, g_dir, g_tip, g_kal, g_sev = True, yd, "YENIDEN", yeniden["kalite"], yeniden["seviye"]
                        yeniden = None
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

        if p["geri_cekilme"] and not pos_open_basta and not giris_sinyal and i >= 20 and a > 0:
            tz = p["gc_taze_bar"]
            tepe_once = int(np.argmax(h[i - 19:i + 1][::-1]))
            dip_once = int(np.argmin(l[i - 19:i + 1][::-1]))
            gc_l = (long_izin and long_ek and L1 and L5 and L8 and e9 and tepe_once <= tz and tepe_once >= 2
                    and l[i] <= ema_f[i] and c[i] > ema_f[i] and c[i] > o[i] and close_pos >= 0.6 and range_ok)
            gc_s = (short_izin and S1 and S5 and S8 and e9 and dip_once <= tz and dip_once >= 2
                    and h[i] >= ema_f[i] and c[i] < ema_f[i] and c[i] < o[i] and close_pos <= 0.4 and range_ok)
            if gc_l or gc_s:
                giris_sinyal, g_dir, g_tip, g_kal, g_sev = True, (1 if gc_l else -1), "GERI CEKILME", "G", np.nan

        if FORMLAR and not pos_open_basta and not giris_sinyal:
            for f_yon, f_sev, f_tip, f_key in formasyon_ara(i, a):
                if f_key in form_kullanildi:
                    continue
                form_kullanildi.add(f_key)
                fv = p["form_vol_mult"]
                vol_ok = fv <= 0 or (not math.isnan(vol_oran) and vol_oran >= fv)
                donus = f_tip in ("CIFT DIP", "CIFT TEPE", "OBO", "TOBO")
                if f_yon == 1:
                    temel = long_izin and long_ek and L1 and L7 and e9
                    trend_ok = L5 or (donus and p["form_trend_serbest"])
                    mum_ok = c_mum_temel_l and c_uzama_l and c_oynak
                else:
                    temel = short_izin and S1 and S7 and e9
                    trend_ok = S5 or (donus and p["form_trend_serbest"])
                    mum_ok = c_mum_temel_s and c_uzama_s and c_oynak
                if temel and trend_ok and mum_ok and vol_ok:
                    giris_sinyal, g_dir, g_tip, g_kal, g_sev = True, f_yon, f_tip, "F", f_sev
                    pend = None
                    break

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
            if p["tp2_yok"]:
                tp2 = giris + 1000 * rsk if gL else giris * 0.001
                tp2_kay = "yok"
            if (not gL) and tp2 <= 0:
                red = "TP2 hesaplanamadi"

            if red is not None:
                olaylar.append(Olay(ot[i], "RED", g_dir, {"neden": red, "tip": g_tip, "kapanis": giris}))
            elif LTF:
                stop = giris - g_dir * rsk
                sev = g_sev if not math.isnan(g_sev) else giris - g_dir * 0.5 * a
                lt = {"yon": g_dir, "stop4": stop, "tp1": tp1, "tp2": tp2, "bar": i, "tip": g_tip, "kalite": g_kal,
                      "tp1_kay": tp1_kay, "tp2_kay": tp2_kay, "Z": giris - 0.382 * (giris - sev),
                      "uc": giris, "cekildi": False, "onceki_uc": None,
                      "buf": p["ltf_stop_buf"] * a, "minstop": p["ltf_min_stop"] * a}
                olaylar.append(Olay(ot[i], "LTF_BEKLE", g_dir, {"kapanis": giris, "stop4": stop, "tp1": tp1, "tp2": tp2,
                                                               "tip": g_tip}))
            elif p["limit_mod"]:
                stop = giris - g_dir * rsk
                lm = p["limit_mod"]
                if lm == "seviye":
                    lf = g_sev
                elif lm == "orta":
                    lf = (o[i] + c[i]) / 2
                else:
                    lf = g_sev + g_dir * p["limit_atr"] * a
                if math.isnan(lf):
                    lf = giris
                lf = max(lf, stop + 0.5 * a) if gL else min(lf, stop - 0.5 * a)
                if (lf >= giris) if gL else (lf <= giris):
                    lf = giris
                lim = {"yon": g_dir, "fiyat": lf, "stop": stop, "tp1": tp1, "tp2": tp2, "bar": i,
                       "tip": g_tip + " LIMIT", "kalite": g_kal, "tp1_kay": tp1_kay, "tp2_kay": tp2_kay}
                olaylar.append(Olay(ot[i], "LIMIT", g_dir, {"fiyat": lf, "stop": stop, "tp1": tp1, "tp2": tp2,
                                                           "kapanis": giris, "tip": g_tip}))
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
