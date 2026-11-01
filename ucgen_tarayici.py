"""
DARALAN UCGEN TARAYICI
======================
Kripto (Binance, 4 saatlik + gunluk), BIST ve ABD hisseleri/ETF'ler (gunluk) icinde daralan ucgen
formasyonlarini bulur; fiyat kirilim seviyesine yaklasinca ve kirilim olunca Telegram'a grafikli mesaj atar.

Ucgen tanimi (TradingView gostergesi "Daralan Ucgen Avcisi" ile birebir ayni):
  * Pivot tepe/dip: solunda ve saginda PIVOT kadar mumdan yuksek/alcak mum (PIVOT mum sonra kesinlesir).
    Cizgi mumun gorunen ucuna dayanir; fitil govdeden 1 ATR'den uzunsa govdenin ucuna (igne cizgiyi bozmasin).
  * Ust cizgi: bir tepeden baslayip sonraki tepelere en siki yaslanan cizgi (hicbir tepe ve kapanis disari
    tasmaz). Alt cizgi diplerle ayni sekilde. Butun kombinasyonlar denenir, en iyisi secilir.
  * Fiyat iki cizgi arasinda gidip gelmeli: genisligin %40'i kadar her buyuk salinim karsi cizgiye degmeli
    (ortada donen buyuk salinim ucgeni bozar). Her cizgide en az 2 ayri dokunus, tek bacak <= surenin yarisi.
  * Formasyonun basindan beri kapanislar cizgilerin icinde; sonra baslayan cizgi geriye uzatildiginda bos
    alana tasmamali. Cizgiler yaklasmali (genislik <= %85), baslangic yuksekligi >= 3 ATR, sure 20-150 mum,
    tepe noktasi (apex) gecilmemis olmali.
  * Tip: ust alcalan + alt yukselen = SIMETRIK, ust yatay + alt yukselen = YUKSELEN,
    ust alcalan + alt yatay = ALCALAN. (Kama ve yatay kanal sayilmaz.)
Olaylar:
  * KIRILIMA YAKIN: kapanis, ust (ya da alt) cizgiye 0.75 ATR'den yakin.
  * KIRILIM: kapanis cizginin 0.3 ATR disinda (tolerans: cizgiye yapisik kapanislar kirilim sayilmaz). Hedef = kirilim seviyesi +/- baslangic yuksekligi (olculen hareket).

Kullanim:
  python ucgen_tarayici.py              # zamanlanmis calisma (4 saatte bir; 00 UTC'de gunlukler + ozet)
  python ucgen_tarayici.py --ozet       # ozeti ve gunlukleri hemen gonder
  python ucgen_tarayici.py --onizleme   # Telegram yok: grafikleri onizleme/ klasorune ciz, istatistik yaz
"""
from __future__ import annotations

import argparse
import io
import json
import math
import os
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone

import numpy as np
import requests

AYAR = dict(PIVOT=5, MAX_BAR=150, MIN_BAR=20, MAX_PIVOT=12, TOL_ATR=0.3, YATAY=0.10,
            MIN_YUKSEKLIK_ATR=3.0, DARALMA=0.85, YAKIN_ATR=0.75,
            # cizgi kalitesi (v2)
            FITIL_ATR=1.0,      # fitil govdeden bu kadar ATR'den uzunsa cizgi govdeye dayanir
            SALINIM=0.40,       # ucgen genisliginin bu kadari geri donus = buyuk salinim
            DOKUNUS_ATR=0.75, DOKUNUS_GEN=0.20,   # dokunus: cizgiye min(0.75 ATR, genisligin %20'si) yakinlik
            KABUL_ATR=1.5, KABUL_GEN=0.30,        # bundan uzakta kalan buyuk salinim ucgeni bozar
            MIN_DOKUNUS=2,      # her cizgide en az 2 ayri salinim dokunusu
            DENGE=0.50,         # iki cizginin baslangici arasindaki fark <= surenin yarisi
            TASMA=0.25,         # sonra baslayan cizgi geriye uzatildiginda gercek fiyatin disina tasma siniri
            MAX_BACAK=0.50,     # tek bir bacak <= surenin yarisi
            MAX_OMUR=450,       # baslangicindan bu kadar mum sonra hala kirilmadiysa bayat (TradingView gecmis siniri)
            TEK_MUM=0.5, TEK_MUM_ORT=2.0)  # bir bacagi tek mum yapamaz: govde > max(bacagin yarisi, 2 x ortalama mum) ise ret
DONUS = dict(                  # ikili tepe/dip ve omuz-bas-omuz (normal / ters)
    MIN_YUK_ATR=3.0,           # formasyon yuksekligi >= 3 ATR
    ESIT=0.15, ESIT_ATR=1.0,   # ikili: iki tepe farki <= min(yuksekligin %15'i, 1 ATR)
    MIN_ARA=10, MAX_ARA=100,   # ikili: iki tepe arasi mum
    DENGE=0.25,                # ikili: kisa bacak / uzun bacak (sure) >= 0.25
    ONCEKI=1.0,                # ikili: formasyona giriste hareket >= 1 x yukseklik, oncesinde daha yuksek tepe yok
    ONCEKI_OBO=0.6,            # OBO: sol omza giriste hareket >= 0.6 x bas yuksekligi
    TEMIZ=0.40,                # bacaklarda yukseklige gore %40'lik ters salinim olmamali (temiz M / W / OBO)
    DOLULUK=0.20,              # iki tepe arasindaki (OBO'da bas bolgesindeki) kapanislarin en az %20'si formasyonun
                               # ic yarisinda olmali: boyun / bas tek bir igneyle olusmasin
    FITIL_ATR=1.0,             # gercek fitil formasyon seviyesini en fazla 1 ATR asabilir
    BAS_FARK=0.20,             # OBO: bas, yuksek omuzdan >= yuksekligin %20'si fazla
    OMUZ_MIN=0.40,             # OBO: her omuz boyun cizgisinden >= %40 yukseklikte
    OMUZ_SEVIYE=0.30,          # OBO: iki omuz arasi fiyat farki <= %30 yukseklik
    BOYUN_EGIM=0.25,           # OBO: iki boyun dibi farki <= %25 yukseklik
    ZAMAN_ORAN=0.40,           # OBO: kisa yan / uzun yan (sure) >= 0.4
    MIN_GEN=15, MAX_GEN=150,   # OBO: sol omuzdan sag omuza mum
    ONAY=0.20, ONAY_ATR=1.0,   # son noktadan sonra fiyat max(1 ATR, %20 yukseklik) uzaklasinca formasyon gosterilir
    OMUR=0.75,                 # son noktadan sonra genisligin %75'i (en az 15 mum) icinde kirilmazsa biter
    YAKIN=2,                   # iki nokta 'ayni yer': ayni tip ve <= 2 mum
)
DESEN_AD = {"ucgen": "Daralan üçgen", "ikili_tepe": "İkili tepe", "ikili_dip": "İkili dip",
            "obo": "Omuz-baş-omuz", "ters_obo": "Ters omuz-baş-omuz"}
ONCELIK = {"obo": 3, "ters_obo": 3, "ucgen": 2, "ikili_tepe": 1, "ikili_dip": 1}
DURUM_DOSYASI = "ucgen_state.json"
LISTE_DOSYASI = "ucgen_izleme_listesi.txt"
MIN_KRIPTO_HACIM = 1e6        # 24 saatlik islem hacmi (USDT); botun coin listesi de her zaman eklenir

UA = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) "
                    "Chrome/126.0 Safari/537.36", "Accept": "application/json"}

ABD = ("META GOOGL MSFT AMZN NVDA AAPL TSLA AMD NFLX ADBE CRM ORCL INTC CSCO IBM QCOM TXN AVGO MU AMAT LRCX "
       "KLAC JPM BAC WFC C GS MS V MA PYPL AXP JNJ PFE MRK ABBV LLY UNH AMGN GILD BMY CVS WMT COST LOW HD TGT "
       "NKE SBUX MCD KO PEP PG CL XOM CVX SLB COP OXY HAL CAT DE BA GE MMM HON FDX UPS LMT F GM RTX T VZ DIS "
       "CMCSA DUK FCX NEE NEM AAL DAL UAL CCL KSS M PM MO BKNG ISRG REGN VRTX DXCM ALGN ENPH FSLR LULU CMG ODFL "
       "DECK CPRT MNST TTWO ETSY EBAY ROKU ZM SHOP UBER CRWD PLTR NOW PANW SNOW FTNT ANET ULTA AXON TSCO BBY "
       "DLTR DG COIN MSTR HOOD ARM SMCI DELL MRVL ASML TSM BABA PDD JD NIO RIVN SOFI "
       "SPY QQQ IWM DIA EFA EEM EWZ EWJ FXI GLD SLV USO UNG TLT IEF HYG XLK XLE XLV XLF XLI XLU XLB XLP XLY "
       "SMH XBI URA GDX KRE XHB ITB").split()
BIST = ("AEFES AGHOL AKBNK AKSA AKSEN ALARK ALFAS ALTNY ANSGR ARCLK ASELS ASTOR BERA BIMAS BINHO BRSAN BRYAT "
        "BSOKE BTCIM CANTE CCOLA CIMSA CLEBI CWENE DOAS DOHOL ECILC EFORC EGEEN EKGYO ENERY ENJSA ENKAI EREGL "
        "EUPWR FENER FROTO GARAN GESAN GOLTS GRSEL GUBRF HALKB HEKTS ISCTR ISMEN KARSN KCAER KCHOL KONTR KONYA "
        "KOZAA KOZAL KRDMD LMKDC MAVI MGROS MIATK MPARK ODAS OBAMS OTKAR OYAKC PASEU PETKM PGSUS QUAGR REEDR "
        "SAHOL SASA SELEC SISE SKBNK SMRTG SOKM TABGD TAVHL TCELL THYAO TKFEN TOASO TSKB TTKOM TTRAK TUKAS "
        "TUPRS TURSG ULKER VAKBN VESTL YEOTK YKBNK ZOREN AKFYE ALBRK GSDHO IHLAS LOGO NETAS DEVA BAGFS "
        "GLYHO ISGYO KLSER PEKGY TMSN AYDEM DEVA").split()


# ───────────────────────── Veri ─────────────────────────
def _get(url, params=None, deneme=4):
    for d in range(deneme):
        try:
            r = requests.get(url, params=params, headers=UA, timeout=25)
            if r.status_code == 200:
                return r.json()
            if r.status_code in (404, 400):
                return None
        except Exception:  # noqa: BLE001
            pass
        time.sleep(1 + 1.5 * d)
    return None


def kripto_listesi() -> list[str]:
    veri = _get("https://data-api.binance.vision/api/v3/ticker/24hr")
    if not veri:
        from coin_listesi import COINLER  # yedek: botun listesi
        return list(dict.fromkeys(COINLER))
    sabit = ("USDC", "FDUSD", "TUSD", "USDP", "DAI", "EUR", "BUSD", "USD1", "AEUR", "PAXG", "XAUT", "USDE", "BFUSD",
             "RLUSD", "PYUSD", "EURI", "XUSD", "USDS", "GBP", "TRY", "BRL")
    secilen = []
    for x in veri:
        s = x["symbol"]
        if not s.endswith("USDT") or s[:-4] in sabit or s[:-4].endswith(("UP", "DOWN", "BULL", "BEAR")):
            continue
        if float(x.get("quoteVolume") or 0) >= MIN_KRIPTO_HACIM and int(x.get("count") or 0) > 0:
            secilen.append(s)
    try:
        from coin_listesi import COINLER
        secilen += COINLER
    except Exception:  # noqa: BLE001
        pass
    return list(dict.fromkeys(secilen))


def binance(sym: str, aralik: str, adet: int = 400) -> dict | None:
    v = _get("https://data-api.binance.vision/api/v3/klines", dict(symbol=sym, interval=aralik, limit=adet))
    if not v:
        return None
    simdi = time.time() * 1000
    v = [k for k in v if k[6] < simdi]   # sadece kapanmis mumlar
    if len(v) < 120:
        return None
    aralik_ms = {"4h": 4 * 3600_000, "1d": 86400_000}.get(aralik, 86400_000)
    if simdi - v[-1][6] > 2 * aralik_ms:   # islem gormeyen / adi degisen coin (son mum eski)
        return None
    kap = np.array([float(k[4]) for k in v[-120:]])
    if kap.std() / kap.mean() < 0.01:      # stabil coin / sabit fiyat
        return None
    a = np.array([[k[0] / 1000, float(k[1]), float(k[2]), float(k[3]), float(k[4]), float(k[7])] for k in v])
    return dict(t=a[:, 0], o=a[:, 1], h=a[:, 2], l=a[:, 3], c=a[:, 4], v=a[:, 5])


def yahoo(sym: str) -> dict | None:
    for host in ("query1", "query2"):
        j = _get(f"https://{host}.finance.yahoo.com/v8/finance/chart/{requests.utils.quote(sym)}",
                 dict(range="2y", interval="1d"), deneme=2)
        if not j:
            continue
        try:
            x = j["chart"]["result"][0]
            q = x["indicators"]["quote"][0]
            bugun = int(time.time() // 86400)
            sat = [(t, o, h, l, c, v or 0) for t, o, h, l, c, v in
                   zip(x["timestamp"], q["open"], q["high"], q["low"], q["close"], q["volume"])
                   if None not in (o, h, l, c) and t // 86400 < bugun]
            if len(sat) < 120 or time.time() - sat[-1][0] > 8 * 86400:   # eski veri / islem durmus
                return None
            a = np.array(sat, dtype=float)
            return dict(t=a[:, 0], o=a[:, 1], h=a[:, 2], l=a[:, 3], c=a[:, 4], v=a[:, 5],
                        borsa=x["meta"].get("exchangeName", ""))
        except Exception:  # noqa: BLE001
            continue
    return None


# ───────────────────────── Tespit ─────────────────────────
def atr(h, l, c, n=14):
    out = np.full(len(c), np.nan)
    v = math.nan
    for i in range(1, len(c)):
        tr = max(h[i] - l[i], abs(h[i] - c[i - 1]), abs(l[i] - c[i - 1]))
        if i < n:
            v = tr if math.isnan(v) else v + tr
            if i == n - 1:
                v /= n
            else:
                continue
        else:
            v = (v * (n - 1) + tr) / n
        out[i] = v
    return out


def pivotlar(h, l, n):
    N = len(h)
    ph = np.zeros(N, bool)
    pl = np.zeros(N, bool)
    for i in range(n, N - n):
        if h[i] > h[i - n:i].max() and h[i] >= h[i + 1:i + n + 1].max():
            ph[i] = True
        if l[i] < l[i - n:i].min() and l[i] <= l[i + 1:i + n + 1].min():
            pl[i] = True
    return ph, pl


def uclar(d: dict, A: np.ndarray, idx):
    """Cizgilerin dayanacagi mum uclari. Fitil govdeden FITIL_ATR*ATR'den kisaysa fitilin ucu, daha uzunsa
    govdenin ucu kullanilir: cizgi gorunen tepeye/dibe deger, tek bir igne cizgiyi bozmaz, cizgi fitilin
    ortasindan da gecmez."""
    o, c, h, l, a = d["o"][idx], d["c"][idx], d["h"][idx], d["l"][idx], A[idx]
    gu, ga = np.maximum(o, c), np.minimum(o, c)
    k = AYAR["FITIL_ATR"]
    return np.where(h - gu <= k * a, h, gu), np.where(ga - l <= k * a, l, ga)


def tek_mum(d: dict, A: np.ndarray, xa: int, xb: int, genlik: float) -> bool:
    """xa'dan xb'ye giden bacagi tek bir mum mu yapmis (igne / haber mumu)? Govdesi hem bacagin yarisindan
    hem bacaktaki ortalama mumun 2 katindan buyuk mum varsa True: boyle bir 'formasyon' uydurmadir."""
    if xb <= xa:
        return False
    govde = np.abs(d["c"][xa + 1:xb + 1] - d["o"][xa + 1:xb + 1])
    aralik = (d["h"][xa + 1:xb + 1] - d["l"][xa + 1:xb + 1]).mean()   # bacaktaki ortalama mum boyu
    return bool(govde.max() > max(AYAR["TEK_MUM"] * abs(genlik), AYAR["TEK_MUM_ORT"] * aralik))


def cizgiler(idx: np.ndarray, P: np.ndarray, c: np.ndarray, b: int, tol: float, ust: bool, xmin: int) -> list:
    """Her baslangic pivotu icin o pivottan ve bir sonraki pivottan gecen, sonraki hicbir pivotun ve
    kapanisin tolerans disina tasmadigi EN SIKI cizgi (fiyata en cok yaslanan). 'serbest': cizgi geriye
    uzatildiginda kapanislarin ve pivotlarin icinde kaldigi en eski mum."""
    out = []
    sg = 1.0 if ust else -1.0
    for a in range(len(idx) - 1):
        i0, p0 = int(idx[a]), float(P[a])
        dx = idx[a + 1:] - i0
        egim = (P[a + 1:] - p0) / dx
        sinir = ((P[a + 1:] - sg * tol) - p0) / dx           # sonraki pivotlarin izin verdigi egim
        smin = sinir.max() if ust else sinir.min()
        gecerli = egim >= smin - 1e-12 if ust else egim <= smin + 1e-12
        xs = np.arange(i0, b + 1)
        for e in (np.argsort(egim) if ust else np.argsort(-egim)):
            if not gecerli[e]:
                continue
            s = float(egim[e])
            if np.any(sg * (c[i0:b + 1] - (p0 + s * (xs - i0))) > tol):
                continue
            x = i0 - 1
            while x >= xmin and sg * (c[x] - (p0 + s * (x - i0))) <= tol:
                x -= 1
            serbest = x + 1
            onc = (idx >= serbest) & (idx < i0)
            if np.any(onc):
                kotu = idx[onc][sg * (P[onc] - (p0 + s * (idx[onc] - i0))) > tol]
                if len(kotu):
                    serbest = int(kotu.max()) + 1
            out.append(dict(i0=i0, p0=p0, s=s, serbest=serbest))
            break
    return out


def salinim(d: dict, A: np.ndarray, x0: int, b: int, u: dict, lo: dict, ust_bas: bool):
    """Fiyat iki cizgi arasinda gidip geliyor mu? Ucgen genisligine gore olceklenmis zigzag:
    genisligin SALINIM katı kadar geri donus 'buyuk salinim' sayilir. Her buyuk tepe ust cizgiye, her buyuk
    dip alt cizgiye yakin olmali; ortada kalan buyuk salinim ihlaldir. Tek bir bacak formasyonun
    MAX_BACAK'indan uzun olamaz.
    Donus: (ihlal, ust_dokunus, alt_dokunus, yakin_gecen, dokunus_noktalari)."""
    xs = np.arange(x0, b + 1)
    Uv = u["p0"] + u["s"] * (xs - u["i0"])
    Lv = lo["p0"] + lo["s"] * (xs - lo["i0"])
    W = Uv - Lv
    if np.any(W <= 0):
        return 99, 0, 0, 0, []
    a = A[x0:b + 1]
    hu, lu = uclar(d, A, xs)
    hp, lp = (hu - Lv) / W, (lu - Lv) / W                      # 0 = alt cizgi, 1 = ust cizgi
    td = np.minimum(AYAR["DOKUNUS_ATR"] * a, AYAR["DOKUNUS_GEN"] * W) / W
    tk = np.minimum(AYAR["KABUL_ATR"] * a, AYAR["KABUL_GEN"] * W) / W
    T = AYAR["SALINIM"]
    ihlal = ud = ad = yakin = 0
    noktalar = [(x0, "u" if ust_bas else "l")]
    donus = [0]
    p_onc = hu[0] if ust_bas else lu[0]                       # bir onceki salinim noktasinin fiyati
    if ust_bas:
        ud, arar_dip, aday, ax = 1, True, lp[0], 0
    else:
        ad, arar_dip, aday, ax = 1, False, hp[0], 0
    for x in range(1, len(xs)):
        if arar_dip:
            if lp[x] < aday:
                aday, ax = lp[x], x
            elif hp[x] >= aday + T:                            # dip onaylandi
                if aday <= td[ax]:
                    ad += 1; noktalar.append((x0 + ax, "l"))
                elif aday > tk[ax]:
                    ihlal += 1
                else:
                    yakin += 1
                if tek_mum(d, A, x0 + donus[-1], x0 + ax, lu[ax] - p_onc):
                    ihlal += 1
                donus.append(ax); p_onc = lu[ax]
                arar_dip, aday, ax = False, hp[x], x
        else:
            if hp[x] > aday:
                aday, ax = hp[x], x
            elif lp[x] <= aday - T:                            # tepe onaylandi
                if 1 - aday <= td[ax]:
                    ud += 1; noktalar.append((x0 + ax, "u"))
                elif 1 - aday > tk[ax]:
                    ihlal += 1
                else:
                    yakin += 1
                if tek_mum(d, A, x0 + donus[-1], x0 + ax, hu[ax] - p_onc):
                    ihlal += 1
                donus.append(ax); p_onc = hu[ax]
                arar_dip, aday, ax = True, lp[x], x
    if np.diff(donus + [len(xs) - 1]).max() > AYAR["MAX_BACAK"] * (len(xs) - 1):
        ihlal += 1
    return ihlal, ud, ad, yakin, noktalar


def tip_bul(du: float, dl: float):
    y = AYAR["YATAY"]
    if du < -y and dl > y:
        return "Simetrik"
    if abs(du) <= y and dl > y:
        return "Yükselen"
    if du < -y and abs(dl) <= y:
        return "Alçalan"
    return None                                                # kama / kanal / genisleyen: ucgen degil


def degerlendir(d: dict, A: np.ndarray, b: int, u: dict, lo: dict):
    """Iki cizgi gecerli bir daralan ucgen olusturuyorsa (skor, formasyon) doner."""
    M = AYAR["MAX_BAR"]
    x0 = min(u["i0"], lo["i0"])
    sure = b - x0
    if not (AYAR["MIN_BAR"] <= sure <= M):
        return None
    if abs(u["i0"] - lo["i0"]) > AYAR["DENGE"] * sure or u["serbest"] > x0 or lo["serbest"] > x0:
        return None
    if abs(u["i0"] - lo["i0"]) < AYAR["PIVOT"]:      # iki cizgi ayni yerden (ayni mumdan) cikmasin
        return None
    if abs(u["i0"] - lo["i0"]) < 3:                     # iki cizgi ayni yerden cikmasin
        return None
    U = lambda x: u["p0"] + u["s"] * (x - u["i0"])     # noqa: E731
    L = lambda x: lo["p0"] + lo["s"] * (x - lo["i0"])  # noqa: E731
    w0, wb = U(x0) - L(x0), U(b) - L(b)
    if w0 <= 0 or wb <= 0 or wb / w0 > AYAR["DARALMA"] or w0 < AYAR["MIN_YUKSEKLIK_ATR"] * A[b]:
        return None
    tip = tip_bul((U(b) - U(x0)) / w0, (L(b) - L(x0)) / w0)
    if not tip:
        return None
    # baslangic genisligi gercek fiyatla desteklenmeli: sonra baslayan cizgi geriye uzatildiginda formasyonun
    # en yuksek / en dusuk fiyatini TASMA*genislikten fazla asmamali (bos alana uzanan ucgen olmasin)
    if U(x0) > d["h"][x0:b + 1].max() + AYAR["TASMA"] * w0 or L(x0) < d["l"][x0:b + 1].min() - AYAR["TASMA"] * w0:
        return None
    ihlal, ud, ad, yakin, noktalar = salinim(d, A, x0, b, u, lo, u["i0"] <= lo["i0"])
    if ihlal or ud < AYAR["MIN_DOKUNUS"] or ad < AYAR["MIN_DOKUNUS"]:
        return None
    apex = x0 + w0 / (w0 - wb) * sure
    f = dict(u=dict(i0=u["i0"], p0=u["p0"], s=u["s"], dok=ud), l=dict(i0=lo["i0"], p0=lo["p0"], s=lo["s"], dok=ad),
             x0=x0, w0=w0, apex=apex, tip=tip, dok=ud + ad, noktalar=noktalar,
             key=(int(d["t"][u["i0"]]), int(d["t"][lo["i0"]])))
    # en cok dokunus; esitlikte yakin gecen salinimi az olan ve daha derli toplu (kisa) formasyon
    return ud + ad - 0.5 * yakin - 0.25 * sure / M, f


def formasyon_kur(d: dict, b: int, ph_list: list, pl_list: list, A: np.ndarray):
    n, M = AYAR["PIVOT"], AYAR["MAX_BAR"]
    K = AYAR["MAX_PIVOT"]                       # pencere icindeki en son K tepe / dip
    hi = np.array([i for i in ph_list if b - M <= i <= b - n][-K:], dtype=int)
    li = np.array([i for i in pl_list if b - M <= i <= b - n][-K:], dtype=int)
    if len(hi) < 2 or len(li) < 2 or not (A[b] > 0):
        return None
    tol = AYAR["TOL_ATR"] * A[b]
    ust = cizgiler(hi, uclar(d, A, hi)[0], d["c"], b, tol, True, b - M)
    alt = cizgiler(li, uclar(d, A, li)[1], d["c"], b, tol, False, b - M)
    en_iyi = None
    for u in ust:
        for lo in alt:
            r = degerlendir(d, A, b, u, lo)
            if r and (en_iyi is None or r[0] > en_iyi[0]):
                en_iyi = r
    return en_iyi[1] if en_iyi else None


def hala_gecerli(d: dict, A: np.ndarray, b: int, f: dict) -> bool:
    """Aktif formasyon yeni mumlarla hala temiz bir ucgen mi (kapanislar icerde, salinimlar cizgilere degiyor)."""
    tol = AYAR["TOL_ATR"] * A[b]
    x0 = f["x0"]
    xs = np.arange(x0, b + 1)
    c = d["c"][x0:b + 1]
    if np.any(c - (f["u"]["p0"] + f["u"]["s"] * (xs - f["u"]["i0"])) > tol):
        return False
    if np.any((f["l"]["p0"] + f["l"]["s"] * (xs - f["l"]["i0"])) - c > tol):
        return False
    return salinim(d, A, x0, b, f["u"], f["l"], f["u"]["i0"] <= f["l"]["i0"])[0] == 0


def deger(f, x, taraf):
    s = f[taraf]
    return s["p0"] + s["s"] * (x - s["i0"])


# ───────────────────────── Donus formasyonlari ─────────────────────────
# Tum hesaplar 'tepe' yonunde yapilir; dip formasyonlarinda fiyatlar ters cevrilir (−fiyat).
def _bacak_temiz(ust: np.ndarray, alt: np.ndarray, xa: int, xb: int, asagi: bool, teta: float) -> bool:
    """xa'dan xb'ye giden bacakta teta kadar ters salinim yoksa True (uclar haric mumlar)."""
    if asagi:                       # tepeden dibe: o ana kadarki en dusuk dipten teta kadar yukselis olmamali
        m = np.inf
        for x in range(xa + 1, xb):
            if ust[x] > m + teta:
                return False
            m = min(m, alt[x])
    else:                           # dipten tepeye: o ana kadarki en yuksek tepeden teta kadar dusus olmamali
        m = -np.inf
        for x in range(xa + 1, xb):
            if alt[x] < m - teta:
                return False
            m = max(m, ust[x])
    return True


def _hazirla(d: dict, uT: np.ndarray, uD: np.ndarray, ters: bool):
    """Tepe yonunde calismak icin: ust = tepe uclari, alt = dip uclari, gercek = gercek fitil ucu, kap = kapanis."""
    if ters:
        return -uD, -uT, -d["l"], -d["c"]
    return uT, uD, d["h"], d["c"]


def _once_ok(ust, alt, x1: int, v1: float, yuk: float, K: int, Ab: float, oran: float) -> bool:
    """Formasyona guclu bir hareketle gelinmis mi: son K mumda daha yuksek tepe yok, yukselis >= oran x yukseklik."""
    a = max(0, x1 - K)
    if x1 - a < 5 or ust[a:x1].max() > v1 + 0.25 * Ab:
        return False
    return v1 - alt[a:x1 + 1].min() >= oran * yuk


def ikili(d: dict, A: np.ndarray, b: int, pivots: list, uT, uD, ters: bool):
    """Son pivot ikinci tepe (ikili tepe) / ikinci dip (ikili dip) mi. pivots: ayni tipteki pivot mumlari."""
    if len(pivots) < 2:
        return None
    k = DONUS
    ust, alt, gercek, kap = _hazirla(d, uT, uD, ters)
    Ab = A[b]
    x2 = pivots[-1]
    v2 = ust[x2]
    for x1 in reversed(pivots[:-1]):
        ara = x2 - x1
        if ara < k["MIN_ARA"]:
            continue
        if ara > k["MAX_ARA"]:
            break
        v1 = ust[x1]
        xt = x1 + int(np.argmin(alt[x1:x2 + 1]))
        vt = alt[xt]
        yuk = max(v1, v2) - vt
        if yuk < k["MIN_YUK_ATR"] * Ab or abs(v1 - v2) > min(k["ESIT"] * yuk, k["ESIT_ATR"] * Ab):
            continue
        tepe = max(v1, v2)
        if ust[x1 + 1:x2].max(initial=-np.inf) > tepe + 0.25 * Ab:          # arada daha yuksek tepe
            continue
        if gercek[x1:x2 + 1].max() > tepe + k["FITIL_ATR"] * Ab:              # uzun igne seviyeyi delmis
            continue
        if min(xt - x1, x2 - xt) < k["DENGE"] * max(xt - x1, x2 - xt):       # igne + yavas sonme degil
            continue
        if np.mean(kap[x1 + 1:x2] <= tepe - 0.5 * yuk) < k["DOLULUK"]:       # cukur tek igneyle olusmamis
            continue
        teta = k["TEMIZ"] * yuk
        if not (_bacak_temiz(ust, alt, x1, xt, True, teta) and _bacak_temiz(ust, alt, xt, x2, False, teta)):
            continue
        if tek_mum(d, A, x1, xt, v1 - vt) or tek_mum(d, A, xt, x2, v2 - vt):   # bacak tek mumla olusmamis
            continue
        if not _once_ok(ust, alt, x1, v1, yuk, max(ara, 20), Ab, k["ONCEKI"]):
            continue
        sg = -1.0 if ters else 1.0
        tT, tD = ("D", "T") if ters else ("T", "D")
        return dict(tur="ikili_dip" if ters else "ikili_tepe", ters=ters, yuk=yuk, genislik=ara, son_x=x2,
                    noktalar=[(x1, sg * v1, "1"), (xt, sg * vt, "boyun"), (x2, sg * v2, "2")],
                    capa=[(x1, tT), (xt, tD), (x2, tT)], boyun=dict(i0=xt, p0=sg * vt, s=0.0),
                    gecersiz=sg * tepe, yon="yukari" if ters else "asagi",
                    key=("ikili", ters, int(d["t"][x1]), int(d["t"][x2])))
    return None


def obo(d: dict, A: np.ndarray, b: int, pivots: list, uT, uD, ters: bool):
    """Son pivot sag omuz mu (omuz-bas-omuz; ters ise ters OBO)."""
    if len(pivots) < 3:
        return None
    k = DONUS
    ust, alt, gercek, kap = _hazirla(d, uT, uD, ters)
    Ab = A[b]
    xr = pivots[-1]
    vr = ust[xr]
    for ih in range(len(pivots) - 2, 0, -1):
        xh = pivots[ih]
        if xr - xh > k["MAX_GEN"]:
            break
        vh = ust[xh]
        if vh <= vr:
            continue
        for il in range(ih - 1, -1, -1):
            xl = pivots[il]
            gen = xr - xl
            if gen > k["MAX_GEN"]:
                break
            if gen < k["MIN_GEN"]:
                continue
            vl = ust[xl]
            if vl >= vh:
                break                                    # bastan yuksek tepe: daha geriye bakma
            x1 = xl + int(np.argmin(alt[xl:xh + 1])); v1 = alt[x1]
            x2 = xh + int(np.argmin(alt[xh:xr + 1])); v2 = alt[x2]
            if not (xl < x1 < xh < x2 < xr):
                continue
            s = (v2 - v1) / (x2 - x1)
            NL = lambda x: v1 + s * (x - x1)             # noqa: E731
            yuk = vh - NL(xh)
            if yuk < k["MIN_YUK_ATR"] * Ab:
                continue
            hL, hR = vl - NL(xl), vr - NL(xr)
            if vh - max(vl, vr) < max(k["BAS_FARK"] * yuk, 0.5 * Ab):
                continue
            if min(hL, hR) < k["OMUZ_MIN"] * yuk or abs(vl - vr) > k["OMUZ_SEVIYE"] * yuk:
                continue
            if abs(v2 - v1) > k["BOYUN_EGIM"] * yuk:
                continue
            dl, dr = xh - xl, xr - xh
            if min(dl, dr) / max(dl, dr) < k["ZAMAN_ORAN"]:
                continue
            xs = np.arange(x1 + 1, x2)
            if np.mean(kap[x1 + 1:x2] - NL(xs) >= 0.5 * yuk) < k["DOLULUK"]:   # bas tek igne degil
                continue
            if ust[xl + 1:xr].max(initial=-np.inf) > vh + 0.25 * Ab or gercek[xl:xr + 1].max() > vh + k["FITIL_ATR"] * Ab:
                continue
            to, tb = k["TEMIZ"] * min(hL, hR), k["TEMIZ"] * yuk      # omuz bacaklari / bas bacaklari
            if not (_bacak_temiz(ust, alt, xl, x1, True, to) and _bacak_temiz(ust, alt, x1, xh, False, tb)
                    and _bacak_temiz(ust, alt, xh, x2, True, tb) and _bacak_temiz(ust, alt, x2, xr, False, to)):
                continue
            if not _once_ok(ust, alt, xl, vl, yuk, max(gen // 2, 20), Ab, k["ONCEKI_OBO"]):
                continue
            if (tek_mum(d, A, xl, x1, vl - v1) or tek_mum(d, A, x1, xh, vh - v1) or tek_mum(d, A, xh, x2, vh - v2)
                    or tek_mum(d, A, x2, xr, vr - v2)):                    # hicbir bacak tek mumla olusmamis
                continue
            sg = -1.0 if ters else 1.0
            tT, tD = ("D", "T") if ters else ("T", "D")
            return dict(tur="ters_obo" if ters else "obo", ters=ters, yuk=yuk, genislik=gen, son_x=xr,
                        noktalar=[(xl, sg * vl, "sol omuz"), (x1, sg * v1, "boyun"), (xh, sg * vh, "baş"),
                                  (x2, sg * v2, "boyun"), (xr, sg * vr, "sağ omuz")],
                        capa=[(xl, tT), (x1, tD), (xh, tT), (x2, tD), (xr, tT)],
                        boyun=dict(i0=x1, p0=sg * v1, s=sg * s), gecersiz=sg * vr, yon="yukari" if ters else "asagi",
                        key=("obo", ters, int(d["t"][xl]), int(d["t"][xr])))
    return None


def boyun(f: dict, x) -> float:
    s = f["boyun"]
    return s["p0"] + s["s"] * (x - s["i0"])


def cakisir(c1: list, c2: list) -> bool:
    """Iki formasyon ayni yerden cizgi cikariyor mu: ayni tip nokta (tepe/dip) ve <= YAKIN mum."""
    for x1, t1 in c1:
        for x2, t2 in c2:
            if t1 == t2 and abs(x1 - x2) <= DONUS["YAKIN"]:
                return True
    return False


def ucgen_capa(f: dict) -> list:
    """Aktif ucgenin cizgilerinin gectigi tum noktalar (baslangic + dokunuslar)."""
    return [(x, "T" if t == "u" else "D") for x, t in f["noktalar"]]


def ucgen_bas(f: dict) -> list:
    """Ucgen cizgilerinin ciktigi noktalar; ucgen bitince bir daha hicbir formasyon buradan baslayamaz."""
    return [(f["u"]["i0"], "T"), (f["l"]["i0"], "D")]


def desen_adi(f: dict) -> str:
    return f"{f['tip']} daralan üçgen" if f.get("desen") == "ucgen" else DESEN_AD[f["tur"]]


def tara(d: dict):
    """Tum gecmisi mum mum isler. Donus: (aktif formasyonlar listesi, olaylar).
    Ucgen ve donus formasyonu (OBO / ikili) ayni anda olabilir ama ayni noktayi paylasamaz.
    Oncelik: omuz-bas-omuz > ucgen > ikili tepe/dip; cakisan dusuk oncelikli aktif formasyon devrilir.
    Biten formasyonun cizgi baslangiclari bir daha hicbir formasyonda kullanilmaz (ayni yerden iki cizgi cikmaz)."""
    n = AYAR["PIVOT"]
    N = len(d["c"])
    A = atr(d["h"], d["l"], d["c"])
    ph, pl = pivotlar(d["h"], d["l"], n)
    uT, uD = uclar(d, A, np.arange(N))
    ph_list, pl_list = [], []
    ucg = don = aday = None
    olaylar, kullanilmis, bozuk = [], [], set()
    ist = d.setdefault("_ist", {"kurulan": 0, "kirilim": 0, "apex": 0, "bozulan": 0, "omur": [],
                                "donus": 0, "devrilen": 0})

    def bitir_ucgen(b, sebep):
        nonlocal ucg
        olaylar.append(dict(tur="bitti", b=b, f=ucg, desen="ucgen", sebep=sebep, yon=""))
        kullanilmis.extend(ucgen_bas(ucg)); bozuk.add(ucg["key"]); ucg = None

    def bitir_don(b, sebep):
        nonlocal don
        olaylar.append(dict(tur="bitti", b=b, f=don, desen=don["tur"], sebep=sebep, yon=""))
        kullanilmis.extend(don["capa"]); don = None

    for b in range(n + 15, N):
        p = b - n
        yh, yl = bool(ph[p]), bool(pl[p])
        if yh:
            ph_list.append(p)
        if yl:
            pl_list.append(p)
        tol = AYAR["TOL_ATR"] * A[b]
        # 1) donus adayi: yeni tepe -> OBO / ikili tepe, yeni dip -> ters OBO / ikili dip
        for var, liste, ters in ((yh, ph_list, False), (yl, pl_list, True)):
            if var:
                c = obo(d, A, b, liste, uT, uD, ters) or ikili(d, A, b, liste, uT, uD, ters)
                if c and not cakisir(c["capa"], kullanilmis):
                    aday = c
        # 2) ucgen: her yeni pivotta yeniden kur
        if yh or yl:
            f = formasyon_kur(d, b, ph_list, pl_list, A)
            yeni_mi = f is not None and not (ucg and ucg["key"] == f["key"])
            if f and yeni_mi and (f["key"] in bozuk or cakisir(ucgen_bas(f), kullanilmis)):
                f = None
            if f and don and cakisir(ucgen_capa(f), don["capa"]):
                if ONCELIK[don["tur"]] >= ONCELIK["ucgen"]:
                    f = None
                else:                                    # ucgen ikili tepe/dibi devirir
                    olaylar.append(dict(tur="bitti", b=b, f=don, desen=don["tur"], sebep="devrildi", yon=""))
                    don = None; ist["devrilen"] += 1
            if f:
                if ucg and ucg["key"] == f["key"]:
                    f["bayrak"], f["dogum"] = ucg["bayrak"], ucg["dogum"]
                else:
                    f["bayrak"], f["dogum"] = set(), b
                    ist["kurulan"] += 1
                f["desen"] = "ucgen"
                ucg = f
            elif ucg and not hala_gecerli(d, A, b, ucg):  # salinim cizgiden koptu: artik ucgen degil
                ist["bozulan"] += 1
                bitir_ucgen(b, "bozuldu")
        # 3) donus adayi onaylandi mi: son noktadan yeterince uzaklasti, boyun henuz kirilmadi
        if aday and b - aday["son_x"] > AYAR["MAX_OMUR"]:    # cok bekleyen aday (TradingView gecmis siniri)
            aday = None
        if aday and not (don and ONCELIK[don["tur"]] >= ONCELIK[aday["tur"]]):
            sx = aday["son_x"]
            son_p = aday["noktalar"][-1][1]
            kap = d["c"][sx:b + 1]
            nl_b = boyun(aday, b)
            if not aday["ters"]:
                uzak = son_p - d["l"][sx:b + 1].min()
                bozuk_mu = kap.max() > aday["gecersiz"] + tol or d["c"][b] < nl_b - tol
            else:
                uzak = d["h"][sx:b + 1].max() - son_p
                bozuk_mu = kap.min() < aday["gecersiz"] - tol or d["c"][b] > nl_b + tol
            if bozuk_mu:                                 # onaylanmadan bozuldu ya da boyun zaten kirilmis (gec)
                aday = None
            elif uzak >= max(DONUS["ONAY_ATR"] * A[b], DONUS["ONAY"] * aday["yuk"]):
                if ucg and cakisir(aday["capa"], ucgen_capa(ucg)):
                    if ONCELIK[aday["tur"]] > ONCELIK["ucgen"]:   # OBO ucgeni devirir
                        olaylar.append(dict(tur="bitti", b=b, f=ucg, desen="ucgen", sebep="devrildi", yon=""))
                        ucg = None; ist["devrilen"] += 1
                    else:
                        aday = None
                if aday:
                    if don:
                        olaylar.append(dict(tur="bitti", b=b, f=don, desen=don["tur"], sebep="devrildi", yon=""))
                        ist["devrilen"] += 1
                    don = dict(aday, bayrak=set(), dogum=b, desen=aday["tur"])
                    aday = None
                    ist["donus"] += 1
        # 4) donus olaylari
        if don:
            nl, c = boyun(don, b), d["c"][b]
            asagi = not don["ters"]
            if (asagi and c > don["gecersiz"] + tol) or (not asagi and c < don["gecersiz"] - tol):
                bitir_don(b, "bozuldu")
            elif b - don["son_x"] > max(15, DONUS["OMUR"] * don["genislik"]):
                bitir_don(b, "sure")
            elif (asagi and c < nl - tol) or (not asagi and c > nl + tol):
                olaylar.append(dict(tur="kirilim", yon=don["yon"], b=b, f=don, seviye=nl, desen=don["tur"],
                                    hedef=nl - don["yuk"] if asagi else nl + don["yuk"], gecersiz=don["gecersiz"]))
                kullanilmis.extend(don["capa"]); don = None
            elif "boyun" not in don["bayrak"] and abs(c - nl) <= AYAR["YAKIN_ATR"] * A[b]:
                don["bayrak"].add("boyun")
                olaylar.append(dict(tur="yakin", yon="boyun", b=b, f=don, seviye=nl, desen=don["tur"]))
        # 5) ucgen olaylari
        if ucg:
            if b >= ucg["apex"] or b - ucg["x0"] > AYAR["MAX_OMUR"]:
                ist["apex"] += 1; ist["omur"].append(b - ucg.get("dogum", b))
                bitir_ucgen(b, "apex")
            else:
                up, lw, c = deger(ucg, b, "u"), deger(ucg, b, "l"), d["c"][b]
                if c > up + tol or c < lw - tol:         # anlamli kirilim: cizginin 0.3 ATR disinda kapanis
                    yon = "yukari" if c > up else "asagi"
                    seviye = up if c > up else lw
                    olaylar.append(dict(tur="kirilim", yon=yon, b=b, f=ucg, seviye=seviye, desen="ucgen",
                                        hedef=seviye + ucg["w0"] if yon == "yukari" else seviye - ucg["w0"],
                                        gecersiz=lw if yon == "yukari" else up))
                    ist["kirilim"] += 1; ist["omur"].append(b - ucg.get("dogum", b))
                    kullanilmis.extend(ucgen_bas(ucg)); bozuk.add(ucg["key"]); ucg = None
                else:
                    for taraf, mesafe in (("ust", up - c), ("alt", c - lw)):
                        if mesafe <= AYAR["YAKIN_ATR"] * A[b] and taraf not in ucg["bayrak"]:
                            ucg["bayrak"].add(taraf)
                            olaylar.append(dict(tur="yakin", yon=taraf, b=b, f=ucg, desen="ucgen",
                                                seviye=up if taraf == "ust" else lw))
    aktifler = []
    b = N - 1
    if ucg:
        aktifler.append(dict(ucg, up=deger(ucg, b, "u"), lw=deger(ucg, b, "l"), atr=A[b],
                             olgunluk=(b - ucg["x0"]) / (ucg["apex"] - ucg["x0"])))
    if don:
        nl = boyun(don, b)
        aktifler.append(dict(don, boyun_son=nl, atr=A[b], hedef=nl - don["yuk"] if not don["ters"] else nl + don["yuk"]))
    return aktifler, olaylar


def kirilima_uzaklik(a: dict, c: float) -> float:
    """Aktif formasyonun kirilim cizgisine uzakligi (ATR cinsinden)."""
    if a["desen"] == "ucgen":
        return min(a["up"] - c, c - a["lw"]) / a["atr"]
    return abs(c - a["boyun_son"]) / a["atr"]


# ───────────────────────── Grafik ─────────────────────────
def _mumlar(ax, d: dict, bas: int, bit: int, plt):
    for i in range(bas, bit + 1):
        o, h, l, c = d["o"][i], d["h"][i], d["l"][i], d["c"][i]
        renk = "#26a69a" if c >= o else "#ef5350"
        ax.vlines(i, l, h, color=renk, linewidth=0.8)
        ax.add_patch(plt.Rectangle((i - 0.32, min(o, c)), 0.64, max(abs(c - o), (h - l) * 0.01), color=renk))


def _bitir_grafik(fig, ax, plt) -> bytes:
    ax.tick_params(colors="#b2b5be", labelsize=8)
    ax.set_xticks([])
    for s in ax.spines.values():
        s.set_color("#2a2e39")
    ax.grid(color="#2a2e39", linewidth=0.5)
    buf = io.BytesIO()
    fig.tight_layout()
    fig.savefig(buf, format="png", facecolor=fig.get_facecolor())
    plt.close(fig)
    return buf.getvalue()


def grafik(sym_ad: str, aralik_ad: str, d: dict, f: dict, olay: dict | None = None) -> bytes:
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    N = len(d["c"])
    son = olay["b"] if olay else N - 1
    kirildi = bool(olay and olay["tur"] == "kirilim")
    bit = min(N - 1, son + (8 if kirildi else 0))
    fig, ax = plt.subplots(figsize=(9, 4.6), dpi=110)
    fig.patch.set_facecolor("#131722"); ax.set_facecolor("#131722")
    t = datetime.fromtimestamp(d["t"][son], tz=timezone.utc).strftime("%d.%m.%Y %H:%M")
    if f.get("desen", "ucgen") == "ucgen":
        bas = max(0, f["x0"] - 25)
        _mumlar(ax, d, bas, bit, plt)
        # kesik uzanti tepe noktasina (apex) kadar gitmez: iki cizgi tek noktada bulusmasin
        uc = son + min(0.6 * (f["apex"] - son), 0.35 * (f["apex"] - f["x0"]))
        for taraf, renk in (("u", "#ff9800"), ("l", "#2196f3")):
            x0 = f[taraf]["i0"]
            ax.plot([x0, son], [deger(f, x0, taraf), deger(f, son, taraf)], color=renk, linewidth=1.8)
            ax.plot([son, uc], [deger(f, son, taraf), deger(f, uc, taraf)], color=renk, linewidth=1.2, linestyle="--")
        for x, taraf in f.get("noktalar", []):                 # cizgiye dokunan salinimlar
            if bas <= x <= son:
                ax.plot(x, deger(f, x, taraf), "o", color="#ff9800" if taraf == "u" else "#2196f3", markersize=4.5,
                        markeredgecolor="white", markeredgewidth=0.6, zorder=5)
        sag = max(bit, uc)
        baslik = f"{f['tip']} daralan üçgen"
        yukari = olay["yon"] == "yukari" if kirildi else True
    else:
        tepe = not f["ters"]
        renk = "#ef5350" if tepe else "#26a69a"
        nk = f["noktalar"]
        bas = max(0, nk[0][0] - 20)
        _mumlar(ax, d, bas, bit, plt)
        uz = son + max(3, int(0.15 * f["genislik"]))
        if f["tur"] in ("ikili_tepe", "ikili_dip"):
            (x1, p1, _), (xt, pt, _), (x2, p2, _) = nk
            ax.plot([x1, x2], [p1, p2], color=renk, linewidth=1.8)          # iki tepeyi (dibi) birlestiren tek cizgi
            ax.plot([xt, son], [pt, pt], color="#ffd54f", linewidth=1.6)     # boyun cizgisi
            ax.plot([son, uz], [pt, pt], color="#ffd54f", linewidth=1.0, linestyle="--")
            etiket = ("1. tepe", "2. tepe") if tepe else ("1. dip", "2. dip")
            for (x, p_, _), e in zip((nk[0], nk[2]), etiket):
                ax.annotate(e, (x, p_), xytext=(0, 9 if tepe else -14), textcoords="offset points", ha="center",
                            color=renk, fontsize=8)
            x_boyun = xt
        else:
            x_b1 = nk[1][0]                                              # boyun ilk noktadan baslar
            ax.plot([x_b1, son], [boyun(f, x_b1), boyun(f, son)], color="#ffd54f", linewidth=1.6)
            ax.plot([son, uz], [boyun(f, son), boyun(f, uz)], color="#ffd54f", linewidth=1.0, linestyle="--")
            for (x, p_, rol) in (nk[0], nk[2], nk[4]):
                ax.plot(x, p_, "o", color=renk, markersize=5, markeredgecolor="white", markeredgewidth=0.6, zorder=5)
                ax.annotate(rol.capitalize(), (x, p_), xytext=(0, 9 if tepe else -14), textcoords="offset points",
                            ha="center", color=renk, fontsize=8)
            x_boyun = x_b1
        ax.annotate("Boyun", (x_boyun, boyun(f, x_boyun)), xytext=(2, -12 if tepe else 6), textcoords="offset points",
                    color="#ffd54f", fontsize=8)
        sag = max(bit, uz)
        baslik = DESEN_AD[f["tur"]]
        yukari = not tepe
    if kirildi:
        renk_h = "#4caf50" if olay["yon"] == "yukari" else "#f44336"
        ax.plot([olay["b"], sag], [olay["hedef"], olay["hedef"]], color=renk_h, linestyle=":", linewidth=1.2)
        ax.annotate("hedef", (sag, olay["hedef"]), xytext=(-28, 3), textcoords="offset points", color=renk_h, fontsize=8)
        ax.annotate("KIRILIM", (olay["b"], d["c"][olay["b"]]), color="white", fontsize=9,
                    xytext=(5, 12 if yukari else -16), textcoords="offset points")
    ax.set_xlim(bas - 1, sag + 2)
    # dikey eksen formasyona odaklansin: soldaki bosluktaki asiri mumlar formasyonu ezmesin
    x_f = f["x0"] if f.get("desen", "ucgen") == "ucgen" else f["noktalar"][0][0]
    alt_y, ust_y = d["l"][x_f:bit + 1].min(), d["h"][x_f:bit + 1].max()
    if kirildi:
        alt_y, ust_y = min(alt_y, olay["hedef"]), max(ust_y, olay["hedef"])
    pay = 0.06 * (ust_y - alt_y)
    ax.set_ylim(alt_y - pay, ust_y + pay)
    ax.set_title(f"{sym_ad}  {aralik_ad}  —  {baslik}  ({t} UTC)", color="white", fontsize=10)
    return _bitir_grafik(fig, ax, plt)


# ───────────────────────── Telegram ─────────────────────────
def tg(metod: str, data: dict, files: dict | None = None):
    token, chat = os.environ.get("TELEGRAM_BOT_TOKEN"), os.environ.get("TELEGRAM_CHAT_ID")
    if not token or not chat:
        print("[telegram yok]", data.get("text") or data.get("caption") or "")
        return
    data = dict(data, chat_id=chat)
    for deneme in range(3):
        try:
            r = requests.post(f"https://api.telegram.org/bot{token}/{metod}", data=data, files=files, timeout=40)
            if r.ok:
                return
            print("telegram hatasi:", r.status_code, r.text[:200])
            if r.status_code == 429:
                time.sleep(int(r.json().get("parameters", {}).get("retry_after", 5)) + 1)
        except Exception as exc:  # noqa: BLE001
            print("telegram hatasi:", exc)
            time.sleep(2)


def metin_gonder(mesaj: str):
    parca, buf = [], ""
    for satir in mesaj.split("\n"):
        if len(buf) + len(satir) + 1 > 3900:
            parca.append(buf); buf = ""
        buf += satir + "\n"
    if buf.strip():
        parca.append(buf)
    for p in parca:
        tg("sendMessage", dict(text=p, disable_web_page_preview="true"))
        time.sleep(0.5)


# ───────────────────────── Yardimcilar ─────────────────────────
def fiyat(x: float) -> str:
    if x >= 1000:
        return f"{x:,.0f}".replace(",", ".")
    if x >= 1:
        return f"{x:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")
    return f"{x:.4g}".replace(".", ",")


def tv(piyasa: str, sym: str, borsa: str, aralik: str) -> tuple[str, str]:
    if piyasa == "KRIPTO":
        t = f"BINANCE:{sym}"
    elif piyasa == "BIST":
        t = f"BIST:{sym}"
    else:
        ex = {"NMS": "NASDAQ", "NGM": "NASDAQ", "NCM": "NASDAQ", "NasdaqGS": "NASDAQ", "NasdaqGM": "NASDAQ",
              "NYQ": "NYSE", "NYSE": "NYSE", "PCX": "AMEX", "ASE": "AMEX", "NYSEArca": "AMEX", "BTS": "CBOE"}
        t = f"{ex.get(borsa, 'NASDAQ')}:{sym}"
    return t, f"https://www.tradingview.com/chart/?symbol={t}&interval={'240' if aralik == '4h' else 'D'}"


def gorunen(piyasa, sym):
    return sym[:-4] if piyasa == "KRIPTO" else sym


# ───────────────────────── Ana akis ─────────────────────────
def isler(gunlukler: bool) -> list:
    out = []
    kripto = kripto_listesi()
    out += [("KRIPTO", s, "4h") for s in kripto]
    if gunlukler:
        out += [("KRIPTO", s, "1d") for s in kripto]
        out += [("BIST", s, "1d") for s in dict.fromkeys(BIST)]
        out += [("ABD", s, "1d") for s in ABD]
    return out


def veri_al(is_):
    piyasa, sym, aralik = is_
    if piyasa == "KRIPTO":
        return binance(sym, aralik)
    return yahoo(sym + ".IS" if piyasa == "BIST" else sym)


def _yuzde(x: float, c: float) -> str:
    return f"{(x / c - 1) * 100:+.1f}%"


def olay_metni(o: dict, d: dict, ad: str, aralik_ad: str, link: str) -> str:
    f = o["f"]
    c = d["c"][o["b"]]
    if o["desen"] == "ucgen":
        if o["tur"] == "kirilim":
            bas = "🚀 YUKARI KIRILIM" if o["yon"] == "yukari" else "🔻 AŞAĞI KIRILIM"
            return (f"{bas} — {ad} ({aralik_ad})\n{f['tip']} daralan üçgen, {f['dok']} dokunuş\n"
                    f"Kapanış: {fiyat(c)}  |  Kırılan seviye: {fiyat(o['seviye'])}\n"
                    f"Hedef (ölçülen hareket): {fiyat(o['hedef'])} ({_yuzde(o['hedef'], c)})\n"
                    f"Geçersizlik: {fiyat(o['gecersiz'])} ({_yuzde(o['gecersiz'], c)})\n{link}")
        taraf = "ÜST (direnç)" if o["yon"] == "ust" else "ALT (destek)"
        return (f"🔺 KIRILIMA YAKIN — {ad} ({aralik_ad})\n{f['tip']} daralan üçgen, {f['dok']} dokunuş\n"
                f"Fiyat {taraf} çizgisine yaklaştı: kapanış {fiyat(c)}, çizgi {fiyat(o['seviye'])} "
                f"({_yuzde(o['seviye'], c)})\n{link}")
    desen = DESEN_AD[o["desen"]]
    yukari = f["yon"] == "yukari"
    if o["tur"] == "kirilim":
        bas = "🚀" if yukari else "🔻"
        return (f"{bas} {desen.upper()} ONAYLANDI — {ad} ({aralik_ad})\n"
                f"Boyun çizgisi {'yukarı' if yukari else 'aşağı'} kırıldı: kapanış {fiyat(c)}, boyun {fiyat(o['seviye'])}\n"
                f"Hedef (ölçülen hareket): {fiyat(o['hedef'])} ({_yuzde(o['hedef'], c)})\n"
                f"Geçersizlik: {fiyat(o['gecersiz'])} ({_yuzde(o['gecersiz'], c)})\n{link}")
    hedef = o["seviye"] + f["yuk"] if yukari else o["seviye"] - f["yuk"]
    return (f"⚠️ BOYUN ÇİZGİSİNE YAKIN — {ad} ({aralik_ad})\n{desen} (henüz onaylanmadı)\n"
            f"Kapanış {fiyat(c)}, boyun {fiyat(o['seviye'])} ({_yuzde(o['seviye'], c)})\n"
            f"Boyun {'yukarı' if yukari else 'aşağı'} kırılırsa hedef: {fiyat(hedef)} ({_yuzde(hedef, c)})\n{link}")


def calistir(gunlukler: bool, ozet: bool, onizleme: bool):
    t0 = time.time()
    liste = isler(gunlukler)
    with ThreadPoolExecutor(max_workers=6) as ex:
        veriler = list(ex.map(veri_al, liste))
    sonuc = []
    for (piyasa, sym, aralik), d in zip(liste, veriler):
        if d is None:
            continue
        aktifler, olaylar = tara(d)
        sonuc.append(dict(piyasa=piyasa, sym=sym, aralik=aralik, d=d, aktifler=aktifler, olaylar=olaylar))
    print(f"{len(liste)} grafik, {len(sonuc)} veri, {time.time() - t0:.0f} sn")
    if onizleme:
        return onizle(sonuc)

    durum = {}
    if os.path.exists(DURUM_DOSYASI):
        try:
            durum = json.load(open(DURUM_DOSYASI, encoding="utf-8"))
        except Exception:  # noqa: BLE001
            durum = {}
    simdi = time.time()
    yeni_olaylar = []
    for r in sonuc:
        N = len(r["d"]["c"])
        for o in r["olaylar"]:
            if o["tur"] == "bitti" or o["b"] < N - 2:   # sadece son 2 kapanmis mum (kacirilan calistirmaya karsi)
                continue
            anahtar = f"{r['piyasa']}|{r['sym']}|{r['aralik']}|{o['f']['key']}|{o['tur']}|{o['yon']}"
            if anahtar in durum:
                continue
            durum[anahtar] = simdi
            yeni_olaylar.append((r, o))
    # olay mesajlari (grafikli)
    sira = {"kirilim": 0, "yakin": 1}
    yeni_olaylar.sort(key=lambda x: (sira[x[1]["tur"]], x[0]["aralik"] != "1d"))
    for k, (r, o) in enumerate(yeni_olaylar):
        f, d = o["f"], r["d"]
        ad = gorunen(r["piyasa"], r["sym"])
        _, link = tv(r["piyasa"], r["sym"], d.get("borsa", ""), r["aralik"])
        aralik_ad = "4 saatlik" if r["aralik"] == "4h" else "Günlük"
        metin = olay_metni(o, d, ad, aralik_ad, link)
        if k < 15:
            try:
                png = grafik(ad, aralik_ad, d, f, o)
                tg("sendPhoto", dict(caption=metin[:1020]), files={"photo": ("formasyon.png", png)})
            except Exception as exc:  # noqa: BLE001
                print("grafik hatasi:", exc)
                metin_gonder(metin)
        else:
            metin_gonder(metin)
        time.sleep(0.6)

    if ozet:
        ozet_gonder(sonuc)
    # durum dosyasi: 60 gunden eski kayitlari sil
    durum = {k: v for k, v in durum.items() if simdi - v < 60 * 86400}
    json.dump(durum, open(DURUM_DOSYASI, "w", encoding="utf-8"))
    print(f"yeni olay: {len(yeni_olaylar)}")


def ozet_gonder(sonuc: list):
    aktifler = [(r, a) for r in sonuc for a in r["aktifler"]]
    tv_liste, satirlar = [], []
    for piyasa in ("KRIPTO", "BIST", "ABD"):
        for aralik in ("4h", "1d"):
            grup = [(r, a) for r, a in aktifler if r["piyasa"] == piyasa and r["aralik"] == aralik]
            if not grup:
                continue
            grup.sort(key=lambda ra: kirilima_uzaklik(ra[1], ra[0]["d"]["c"][-1]))
            ad_ = {"KRIPTO": "Kripto", "BIST": "BIST", "ABD": "ABD"}[piyasa] + (" 4s" if aralik == "4h" else " günlük")
            satirlar.append(f"\n▪️ {ad_} ({len(grup)})")
            for r, a in grup:
                c = r["d"]["c"][-1]
                t, link = tv(r["piyasa"], r["sym"], r["d"].get("borsa", ""), aralik)
                tv_liste.append(t)
                if a["desen"] == "ucgen":
                    satirlar.append(f"• {gorunen(piyasa, r['sym'])} — {a['tip']} üçgen, üst {fiyat(a['up'])} "
                                    f"({_yuzde(a['up'], c)}), alt {fiyat(a['lw'])} ({_yuzde(a['lw'], c)}), "
                                    f"olgunluk %{a['olgunluk'] * 100:.0f}\n  {link}")
                else:
                    satirlar.append(f"• {gorunen(piyasa, r['sym'])} — {DESEN_AD[a['desen']]}, boyun {fiyat(a['boyun_son'])} "
                                    f"({_yuzde(a['boyun_son'], c)}), hedef {fiyat(a['hedef'])} "
                                    f"({_yuzde(a['hedef'], c)})\n  {link}")
    say = {}
    for _, a in aktifler:
        say[a["desen"]] = say.get(a["desen"], 0) + 1
    kisa = {"ucgen": "üçgen", "ikili_tepe": "ikili tepe", "ikili_dip": "ikili dip", "obo": "OBO", "ters_obo": "ters OBO"}
    dagilim = ", ".join(f"{kisa[k]} {v}" for k, v in sorted(say.items(), key=lambda kv: -kv[1]))
    bas = (f"📐 FORMASYON ÖZETİ — {datetime.now(timezone.utc).strftime('%d.%m.%Y')}\n"
           f"Şu an {len(aktifler)} aktif formasyon ({dagilim}). Kırılım çizgisine en yakın olan önce:"
           if aktifler else f"📐 FORMASYON ÖZETİ — {datetime.now(timezone.utc).strftime('%d.%m.%Y')}")
    metin_gonder(bas + "\n" + "\n".join(satirlar) if aktifler else bas + "\nŞu an aktif formasyon yok.")
    with open(LISTE_DOSYASI, "w", encoding="utf-8") as fh:
        fh.write(",".join(dict.fromkeys(tv_liste)))
    # kirilim cizgisine en yakin 10 formasyonun grafik albumu
    yakin = sorted(aktifler, key=lambda ra: kirilima_uzaklik(ra[1], ra[0]["d"]["c"][-1]))[:10]
    if len(yakin) >= 2:
        media, files = [], {}
        for k, (r, a) in enumerate(yakin):
            ad = gorunen(r["piyasa"], r["sym"])
            try:
                files[f"f{k}"] = (f"f{k}.png", grafik(ad, "4 saatlik" if r["aralik"] == "4h" else "Günlük", r["d"], a))
                media.append(dict(type="photo", media=f"attach://f{k}", caption=f"{ad} — {desen_adi(a)}"))
            except Exception as exc:  # noqa: BLE001
                print("grafik hatasi:", exc)
        if len(media) >= 2:
            tg("sendMediaGroup", dict(media=json.dumps(media)), files=files)


def onizle(sonuc: list):
    """Gozle kontrol: grafikleri onizleme/ klasorune cizer ve formasyon sayilarini yazar."""
    os.makedirs("onizleme", exist_ok=True)
    # ham mum verisi (yerelde gelistirme / gozle kontrol icin)
    np.savez_compressed("onizleme/veri.npz", **{
        f"{r['piyasa']}__{r['sym']}__{r['aralik']}":
            np.column_stack([r["d"][k] for k in ("t", "o", "h", "l", "c", "v")]) for r in sonuc})
    aktifler = sorted(((r, a) for r in sonuc for a in r["aktifler"]),
                      key=lambda ra: (ra[1]["desen"], ra[0]["piyasa"], ra[0]["aralik"], ra[0]["sym"]))
    adim = max(1, len(aktifler) // 24)
    for r, a in aktifler[::adim][:24]:
        ad = gorunen(r["piyasa"], r["sym"])
        open(f"onizleme/aktif_{a['desen']}_{r['piyasa']}_{r['aralik']}_{ad}.png", "wb").write(
            grafik(ad, r["aralik"], r["d"], a))
    # her desenden birkac gecmis kirilim ornegi
    ornek, say_kir, say_akt = {}, {}, {}
    for _, a in aktifler:
        say_akt[a["desen"]] = say_akt.get(a["desen"], 0) + 1
    for r in sonuc:
        d = r["d"]
        for o in r["olaylar"]:
            if o["tur"] != "kirilim":
                continue
            say_kir[o["desen"]] = say_kir.get(o["desen"], 0) + 1
            if ornek.get(o["desen"], 0) < 4 and o["b"] < len(d["c"]) - 10:
                ornek[o["desen"]] = ornek.get(o["desen"], 0) + 1
                ad = gorunen(r["piyasa"], r["sym"])
                open(f"onizleme/kirilim_{o['desen']}_{r['piyasa']}_{r['aralik']}_{ad}.png", "wb").write(
                    grafik(ad, r["aralik"], d, o["f"], o))
    satir = (f"{len(sonuc)} grafik | aktif {say_akt} | gecmis kirilim {say_kir} | "
             f"devrilen {sum(r['d']['_ist']['devrilen'] for r in sonuc)}")
    print(satir)
    if os.environ.get("GITHUB_ACTIONS") == "true":
        print("::notice::" + satir.replace("%", "%25"))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--ozet", action="store_true")
    ap.add_argument("--onizleme", action="store_true")
    a = ap.parse_args()
    saat = datetime.now(timezone.utc).hour
    gunluk_saat = saat < 4                      # 00 UTC calistirmasi (gec kalirsa 03:59'a kadar)
    gunlukler = a.ozet or a.onizleme or gunluk_saat
    calistir(gunlukler=gunlukler, ozet=a.ozet or gunluk_saat, onizleme=a.onizleme)


if __name__ == "__main__":
    main()
