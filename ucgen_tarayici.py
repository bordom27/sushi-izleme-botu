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
  * BUYUK UCGEN (once aranir, elle cizen gibi; 50-300 mum): cizgi mumlarin kenarindan gecer (hicbir fitil ucu
    cizgiyi 0.3 ATR'den fazla delmez, ani cokus ignesi haric; yeni bir dip/tepe delerse cizgi yeniden cizilir),
    kirilimdan hemen onceki son dokunus onay beklemez (gecici pivot), ara dalga en az ortaya kadar gelmeli,
    ucgene giris hareketi >= taban (buyuk hareketin icini degil ardindaki sikismayi ciz), ikinci cizgi ucgen
    %25 daralmadan baslar, en buyuk yapi secilir. Kirilim icin kapanis max(0.3 ATR, tabanin %5'i) disinda.
  * Kirilim her mumda cizgiler yeniden cizilmeden ONCE denetlenir.
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

AYAR = dict(PIVOT=5, SAG=2, MAX_BAR=150, MIN_BAR=20, MAX_PIVOT=12, TOL_ATR=0.3, YATAY=0.10,
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
            TEK_MUM=0.5, TEK_MUM_ORT=2.0,  # bir bacagi tek mum yapamaz: govde > max(bacagin yarisi, 2 x ortalama mum) ise ret
            UC_KONTROL=False,   # cizgi tum mumlarin uclarina (fitil / igne ise govde) gore: hicbir uc tol'den fazla tasmaz
            BEKLEYEN=False,     # son (henuz donusu onaylanmamis) dip / tepe cizgiye degiyorsa dokunus sayilir
            DENGE_APEX=None,    # sonra baslayan cizgi, baslangic -> apex yolunun bu kadarindan once baslamali
            ONCEKI=0.0,         # formasyona giris hareketi >= ONCEKI x taban (ucgen bir hareketten sonra olusur)
            ALTERNE=0)          # dokunuslar ust / alt arasinda en az bu kadar yer degistirmeli
# Tespit log fiyatla yapilir: log grafikte cizgiler duz, olculer yuzdesel (buyuk hareketlerde dogru oran).
# Fiyat gosterilirken exp alinir. Olculen hareket hedefi de oransaldir: hedef = kirilim seviyesi x (taban orani).
LOG = True


def log_veri(d: dict) -> dict:
    """Mum verisini tespit uzayina cevirir (LOG ise o/h/l/c'nin dogal logaritmasi). Diger alanlar aynen kalir."""
    if not LOG or d.get("log"):
        return d
    e = dict(d)
    for k in ("o", "h", "l", "c"):
        e[k] = np.log(np.maximum(np.asarray(d[k], float), 1e-12))
    e["log"] = True
    return e


# Buyuk ucgen: formasyonu ana donus noktalari belirler (elle cizen gibi). Once buyuk ucgen aranir, bulunursa
# icindeki kucuk ucgenler gosterilmez. Farklar: cizgi mumlarin kenarindan gecer (hicbir fitil ucu cizgiyi delmez,
# ani cokus ignesi haric), ara dalgalar cizgiye degmek zorunda degil, son dokunus onay beklemeden sayilir,
# ucgen guclu bir hareketin ardindan baslar, uzun pencere ve buyuklugu one alan puan.
BUYUK = dict(AYAR, BUYUK=True, MAX_BAR=300, MIN_BAR=50, MAX_PIVOT=24,
             FITIL_GOVDE=1.5,               # fitil ucu: fitil <= max(1 ATR, govdenin 1,5 kati); daha uzunsa
             #                                (ani cokus / igne mumu) govde ucu: tek igne cizgi kurmasin, H'yi sisirmesin
             KABUL_ATR=99.0, KABUL_GEN=0.50,  # ara dalgalar cizgilere degmek zorunda degil, ortaya kadar gelmesi yeter
             TEK_MUM=99.0,                  # tek buyuk mumla gelen bacak da sayilir (ucu cizgiyle dogrulanir)
             DENGE=0.50,                    # destek / direnc sonradan olusabilir (alcalan ucgende yatay dip)
             DENGE_APEX=0.25,               # ... ama ucgen %25'ten fazla daralmadan once
             UC_KONTROL=True, BEKLEYEN=True,
             ONCEKI=1.0,                    # girisi >= taban: buyuk hareketin icini degil, ardindaki sikismayi ciz
             PUAN_W0=10.0,                  # puan: taban (log) x 10 + dokunus: once en buyuk yapi
             KIRILIM_H=0.05)                # kirilim: kapanis cizginin max(0.3 ATR, tabanin %5'i) disinda
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


def uclar(d: dict, A: np.ndarray, idx, P: dict | None = None):
    """Cizgilerin dayanacagi mum uclari. Fitil govdeden FITIL_ATR*ATR'den kisaysa fitilin ucu, daha uzunsa
    govdenin ucu kullanilir: cizgi gorunen tepeye/dibe deger, tek bir igne cizgiyi bozmaz, cizgi fitilin
    ortasindan da gecmez."""
    o, c, h, l, a = d["o"][idx], d["c"][idx], d["h"][idx], d["l"][idx], A[idx]
    gu, ga = np.maximum(o, c), np.minimum(o, c)
    P = P or AYAR
    sinir = P["FITIL_ATR"] * a
    if P.get("FITIL_GOVDE"):                    # buyuk ucgen: guclu mumun uzun fitili de uc (elle cizen gibi)
        sinir = np.maximum(sinir, P["FITIL_GOVDE"] * (gu - ga))
    return np.where(h - gu <= sinir, h, gu), np.where(ga - l <= sinir, l, ga)


def tum_uclar(d: dict, A: np.ndarray, P: dict):
    """Tum mumlarin cizgi uclari (P'ye gore), d icinde onbellekli."""
    k = "_uc_b" if P.get("BUYUK") else "_uc_k"
    if k not in d or len(d[k][0]) != len(d["c"]):
        d[k] = uclar(d, A, np.arange(len(d["c"])), P)
    return d[k]


def tek_mum(d: dict, A: np.ndarray, xa: int, xb: int, genlik: float, P: dict | None = None) -> bool:
    """xa'dan xb'ye giden bacagi tek bir mum mu yapmis (igne / haber mumu)? Govdesi hem bacagin yarisindan
    hem bacaktaki ortalama mumun 2 katindan buyuk mum varsa True: boyle bir 'formasyon' uydurmadir."""
    if xb <= xa:
        return False
    govde = np.abs(d["c"][xa + 1:xb + 1] - d["o"][xa + 1:xb + 1])
    aralik = (d["h"][xa + 1:xb + 1] - d["l"][xa + 1:xb + 1]).mean()   # bacaktaki ortalama mum boyu
    P = P or AYAR
    return bool(govde.max() > max(P["TEK_MUM"] * abs(genlik), P["TEK_MUM_ORT"] * aralik))


def cizgiler(idx: np.ndarray, P: np.ndarray, c: np.ndarray, b: int, tol: float, ust: bool, xmin: int,
             uc: np.ndarray | None = None) -> list:
    """Her baslangic pivotu icin o pivottan ve bir sonraki pivottan gecen, sonraki hicbir pivotun ve
    kapanisin tolerans disina tasmadigi EN SIKI cizgi (fiyata en cok yaslanan). 'serbest': cizgi geriye
    uzatildiginda kapanislarin ve pivotlarin icinde kaldigi en eski mum.
    uc verilirse (elle cizen gibi) aradaki hicbir mumun ucu da cizgiyi tol'den fazla asamaz: cizgi fiyatin
    kenarindan gecer, mumlarin icinden degil."""
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
            cz = p0 + s * (xs - i0)
            if np.any(sg * (c[i0:b + 1] - cz) > tol):
                continue
            if uc is not None and np.any(sg * (uc[i0:b + 1] - cz) > tol):
                continue
            x = i0 - 1
            while x >= xmin and sg * (c[x] - (p0 + s * (x - i0))) <= tol and \
                    (uc is None or sg * (uc[x] - (p0 + s * (x - i0))) <= tol):
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


def salinim(d: dict, A: np.ndarray, x0: int, b: int, u: dict, lo: dict, ust_bas: bool, P: dict | None = None):
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
    P = P or AYAR
    a = A[x0:b + 1]
    hu, lu = uclar(d, A, xs, P)
    hp, lp = (hu - Lv) / W, (lu - Lv) / W                      # 0 = alt cizgi, 1 = ust cizgi
    td = np.minimum(P["DOKUNUS_ATR"] * a, P["DOKUNUS_GEN"] * W) / W
    tk = np.minimum(P["KABUL_ATR"] * a, P["KABUL_GEN"] * W) / W
    T = P["SALINIM"]
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
                if ax == donus[-1]:                            # onceki tepeyle ayni mum (tek mum tum genislik)
                    pass
                elif aday <= td[ax]:
                    ad += 1; noktalar.append((x0 + ax, "l"))
                elif aday > tk[ax]:
                    ihlal += 1
                else:
                    yakin += 1
                if tek_mum(d, A, x0 + donus[-1], x0 + ax, lu[ax] - p_onc, P):
                    ihlal += 1
                donus.append(ax); p_onc = lu[ax]
                arar_dip, aday, ax = False, hp[x], x
        else:
            if hp[x] > aday:
                aday, ax = hp[x], x
            elif lp[x] <= aday - T:                            # tepe onaylandi
                if ax == donus[-1]:
                    pass
                elif 1 - aday <= td[ax]:
                    ud += 1; noktalar.append((x0 + ax, "u"))
                elif 1 - aday > tk[ax]:
                    ihlal += 1
                else:
                    yakin += 1
                if tek_mum(d, A, x0 + donus[-1], x0 + ax, hu[ax] - p_onc, P):
                    ihlal += 1
                donus.append(ax); p_onc = hu[ax]
                arar_dip, aday, ax = True, lp[x], x
    if np.diff(donus + [len(xs) - 1]).max() > P["MAX_BACAK"] * (len(xs) - 1):
        ihlal += 1
    if P.get("BEKLEYEN") and ax != donus[-1] and ax <= len(xs) - 1 - P["SAG"]:
        if arar_dip and aday <= td[ax]:                        # son dip cizgide, donus henuz T kadar degil
            ad += 1; noktalar.append((x0 + ax, "l"))
        elif not arar_dip and 1 - aday <= td[ax]:
            ud += 1; noktalar.append((x0 + ax, "u"))
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


def degerlendir(d: dict, A: np.ndarray, b: int, u: dict, lo: dict, P: dict | None = None):
    """Iki cizgi gecerli bir daralan ucgen olusturuyorsa (skor, formasyon) doner."""
    P = P or AYAR
    M = P["MAX_BAR"]
    x0 = min(u["i0"], lo["i0"])
    sure = b - x0
    if not (P["MIN_BAR"] <= sure <= M):
        return None
    if abs(u["i0"] - lo["i0"]) > P["DENGE"] * sure or u["serbest"] > x0 or lo["serbest"] > x0:
        return None
    if abs(u["i0"] - lo["i0"]) < P["PIVOT"]:         # iki cizgi ayni yerden (ayni mumdan) cikmasin
        return None
    if abs(u["i0"] - lo["i0"]) < 3:                     # iki cizgi ayni yerden cikmasin
        return None
    U = lambda x: u["p0"] + u["s"] * (x - u["i0"])     # noqa: E731
    L = lambda x: lo["p0"] + lo["s"] * (x - lo["i0"])  # noqa: E731
    w0, wb = U(x0) - L(x0), U(b) - L(b)
    if w0 <= 0 or wb <= 0 or wb / w0 > P["DARALMA"] or w0 < P["MIN_YUKSEKLIK_ATR"] * A[b]:
        return None
    tip = tip_bul((U(b) - U(x0)) / w0, (L(b) - L(x0)) / w0)
    if not tip:
        return None
    # baslangic genisligi gercek fiyatla desteklenmeli: sonra baslayan cizgi geriye uzatildiginda formasyonun
    # en yuksek / en dusuk fiyatini TASMA*genislikten fazla asmamali (bos alana uzanan ucgen olmasin)
    if U(x0) > d["h"][x0:b + 1].max() + P["TASMA"] * w0 or L(x0) < d["l"][x0:b + 1].min() - P["TASMA"] * w0:
        return None
    if P.get("DENGE_APEX") and abs(u["i0"] - lo["i0"]) > P["DENGE_APEX"] * w0 / (w0 - wb) * sure:
        return None                                    # ikinci cizgi ucgen epey daraldiktan sonra basliyor
    if P.get("ONCEKI"):                                # giris hareketi: ucgen bir hareketin ardindaki sikisma
        a0 = max(0, x0 - max(P["MIN_BAR"], sure // 2))
        if a0 >= x0:
            return None
        if u["i0"] <= lo["i0"]:
            giris = U(x0) - d["l"][a0:x0].min()
        else:
            giris = d["h"][a0:x0].max() - L(x0)
        if giris < P["ONCEKI"] * w0:
            return None
    ihlal, ud, ad, yakin, noktalar = salinim(d, A, x0, b, u, lo, u["i0"] <= lo["i0"], P)
    if ihlal or ud < P["MIN_DOKUNUS"] or ad < P["MIN_DOKUNUS"]:
        return None
    apex = x0 + w0 / (w0 - wb) * sure
    if P.get("ALTERNE"):
        yer = [s for _, s in noktalar]
        if sum(1 for a_, b_ in zip(yer, yer[1:]) if a_ != b_) < P["ALTERNE"]:
            return None
    f = dict(u=dict(i0=u["i0"], p0=u["p0"], s=u["s"], dok=ud), l=dict(i0=lo["i0"], p0=lo["p0"], s=lo["s"], dok=ad),
             x0=x0, w0=w0, apex=apex, tip=tip, dok=ud + ad, noktalar=noktalar, buyuk=bool(P.get("BUYUK")),
             key=(int(d["t"][u["i0"]]), int(d["t"][lo["i0"]]))
             + ((round(u["s"], 6), round(lo["s"], 6)) if P.get("BUYUK") else ()))
    # buyuk ucgende anahtar cizgilerin egimini de icerir: kirilim sonrasi fiyat geri donup yeni bir tepe / dip
    # olusturursa ayni baslangic noktalarindan yeniden cizilen (elle cizen gibi duzeltilen) ucgen yeni sayilir
    if P.get("BUYUK"):                     # buyuk ucgen: en buyuk yapi (taban orani), sonra dokunus ve sure
        return P["PUAN_W0"] * w0 + ud + ad - 0.25 * yakin + sure / M, f
    # en cok dokunus; esitlikte yakin gecen salinimi az olan ve daha derli toplu (kisa) formasyon
    return ud + ad - 0.5 * yakin - 0.25 * sure / M, f


def formasyon_kur(d: dict, b: int, ph_list: list, pl_list: list, A: np.ndarray, P: dict | None = None):
    P = P or AYAR
    n, M = P["PIVOT"], P["MAX_BAR"]
    K = P["MAX_PIVOT"]                          # pencere icindeki en son K tepe / dip
    hi = np.array([i for i in ph_list if b - M <= i <= b - P["SAG"]][-K:], dtype=int)
    li = np.array([i for i in pl_list if b - M <= i <= b - P["SAG"]][-K:], dtype=int)
    if len(hi) < 2 or len(li) < 2 or not (A[b] > 0):
        return None
    tol = P["TOL_ATR"] * A[b]
    ucu, ucl = tum_uclar(d, A, P) if P.get("UC_KONTROL") else (None, None)
    ust = cizgiler(hi, uclar(d, A, hi, P)[0], d["c"], b, tol, True, max(0, b - M), ucu)
    alt = cizgiler(li, uclar(d, A, li, P)[1], d["c"], b, tol, False, max(0, b - M), ucl)
    en_iyi = None
    for u in ust:
        for lo in alt:
            r = degerlendir(d, A, b, u, lo, P)
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
    P = BUYUK if f.get("buyuk") else AYAR
    if P.get("UC_KONTROL"):                            # yeni bir dip / tepe cizgiyi deldiyse cizgi yeniden cizilir
        ucu, ucl = tum_uclar(d, A, P)
        if np.any(ucu[x0:b + 1] - (f["u"]["p0"] + f["u"]["s"] * (xs - f["u"]["i0"])) > tol) or \
                np.any((f["l"]["p0"] + f["l"]["s"] * (xs - f["l"]["i0"])) - ucl[x0:b + 1] > tol):
            return False
    return salinim(d, A, x0, b, f["u"], f["l"], f["u"]["i0"] <= f["l"]["i0"], P)[0] == 0


def kirilim_payi(f: dict, Ab: float) -> float:
    """Kirilim sayilmasi icin kapanisin cizginin ne kadar disinda olmasi gerekir: 0.3 ATR. Buyuk ucgende ayrica
    tabanin %5'i: buyuk yapida kucuk bir sarkma kirilim sayilmaz, cizgi yeni dibe / tepeye gore yeniden oturur."""
    t = AYAR["TOL_ATR"] * Ab
    return max(t, BUYUK["KIRILIM_H"] * f["w0"]) if f.get("buyuk") else t


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
    return f"{ucgen_adi(f)} daralan üçgen" if f.get("desen") == "ucgen" else DESEN_AD[f["tur"]]


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
    kirik = {}                      # buyuk ucgen cizgi baslangiclari -> onceki kirilim yonu (ayni ucgen tekrar kirilirsa)
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

    def ucgen_olaylari(b):
        """Aktif ucgen: apex / omur sonu, kirilim (kapanis cizginin pay disinda), cizgiye yaklasma."""
        nonlocal ucg
        if not ucg:
            return
        if b >= ucg["apex"] or b - ucg["x0"] > AYAR["MAX_OMUR"]:
            ist["apex"] += 1; ist["omur"].append(b - ucg.get("dogum", b))
            bitir_ucgen(b, "apex")
            return
        up, lw, c = deger(ucg, b, "u"), deger(ucg, b, "l"), d["c"][b]
        pay = kirilim_payi(ucg, A[b])
        if c > up + pay or c < lw - pay:                 # anlamli kirilim: cizginin 0.3 ATR disinda kapanis
            yon = "yukari" if c > up else "asagi"
            seviye = up if c > up else lw
            olaylar.append(dict(tur="kirilim", yon=yon, b=b, f=ucg, seviye=seviye, desen="ucgen",
                                hedef=seviye + ucg["w0"] if yon == "yukari" else seviye - ucg["w0"],
                                gecersiz=lw if yon == "yukari" else up,
                                tekrar=kirik.get(ucg["key"][:2]) if ucg.get("buyuk") else None))
            kirik[ucg["key"][:2]] = yon
            ist["kirilim"] += 1; ist["omur"].append(b - ucg.get("dogum", b))
            kullanilmis.extend(ucgen_bas(ucg)); bozuk.add(ucg["key"]); ucg = None
            return
        for taraf, mesafe in (("ust", up - c), ("alt", c - lw)):
            if mesafe <= AYAR["YAKIN_ATR"] * A[b] and taraf not in ucg["bayrak"]:
                ucg["bayrak"].add(taraf)
                olaylar.append(dict(tur="yakin", yon=taraf, b=b, f=ucg, desen="ucgen",
                                    seviye=up if taraf == "ust" else lw))

    def donus_olaylari(b, tol):
        """Aktif donus formasyonu: gecersizlik, sure sonu, boyun kirilimi, boyuna yaklasma (mevcut boyuna gore)."""
        nonlocal don
        if not don:
            return
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
        # 2) kirilim / son: once mevcut cizgilere ve boyuna gore (yeni formasyon eskisinin kirilimini yutmasin)
        ucgen_olaylari(b)
        donus_olaylari(b, tol)
        # 3) ucgen: her yeni pivotta yeniden kur. Gecici pivot: son n mum icinde (en az SAG mum once), solundaki
        #    n mumun ve sonraki mumlarin en yuksegi / en dusugu (henuz n mumla onaylanmadi): kirilimdan hemen once
        #    gelen son dokunus (elle cizen kisinin gordugu) beklemeden cizgiye dahil olur.
        gth = [q for q in range(b - n + 1, b - AYAR["SAG"] + 1)
               if d["h"][q] > d["h"][q - n:q].max() and d["h"][q] >= d["h"][q + 1:b + 1].max()]
        gtl = [q for q in range(b - n + 1, b - AYAR["SAG"] + 1)
               if d["l"][q] < d["l"][q - n:q].min() and d["l"][q] <= d["l"][q + 1:b + 1].min()]
        gh = bool(gth) and gth[-1] == b - AYAR["SAG"]          # yeni gecici tepe / dip
        gl = bool(gtl) and gtl[-1] == b - AYAR["SAG"]
        if yh or yl or gh or gl:
            f = None
            for P in (BUYUK, AYAR):                 # once buyuk ucgen; yoksa kucuk
                if ucg and ucg.get("buyuk") and hala_gecerli(d, A, b, ucg):
                    f = ucg                         # buyuk ucgen suruyor: cizgileri sabit kalir, icindeki
                    break                           # kucuk ucgenlere gecilmez
                if P is BUYUK:                      # gecici pivotlar yalniz buyuk ucgende (son dokunus beklenmez)
                    f = formasyon_kur(d, b, ph_list + gth, pl_list + gtl, A, P)
                elif yh or yl:                      # kucuk ucgen yalniz onayli pivotla kurulur
                    f = formasyon_kur(d, b, ph_list, pl_list, A, P)
                else:                               # gecici pivot: kucuk ucgen degismeden surer
                    f = None
                    break
                yeni_mi = f is not None and not (ucg and ucg["key"] == f["key"])
                if f and yeni_mi and (f["key"] in bozuk or (not f["buyuk"] and cakisir(ucgen_bas(f), kullanilmis))):
                    f = None
                if f:
                    break
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
            elif ucg and (yh or yl or ucg.get("buyuk")) and not hala_gecerli(d, A, b, ucg):
                # salinim cizgiden koptu: artik ucgen degil
                ist["bozulan"] += 1
                bitir_ucgen(b, "bozuldu")
        # 4) donus adayi onaylandi mi: son noktadan yeterince uzaklasti, boyun henuz kirilmadi
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


def _bitir_grafik(fig, ax, plt, son_adim=None) -> bytes:
    ax.tick_params(colors="#b2b5be", labelsize=8)
    ax.set_xticks([])
    for s in ax.spines.values():
        s.set_color("#2a2e39")
    ax.grid(color="#2a2e39", linewidth=0.5)
    buf = io.BytesIO()
    fig.tight_layout()
    if son_adim:                                                # olculer kesinlesince (yerlesimden sonra) calisir
        son_adim()
    fig.savefig(buf, format="png", facecolor=fig.get_facecolor())
    plt.close(fig)
    return buf.getvalue()


# ───────────────────────── Gecmis isabet: guven derecesi ─────────────────────────
ISTATISTIK_DOSYA = os.path.join(os.path.dirname(os.path.abspath(__file__)), "formasyon_istatistik.json")
ZAMAN_AD = {"4h": "4 saatlik", "8h": "8 saatlik", "1d": "günlük", "3d": "3 günlük", "1w": "haftalık"}
PIYASA_AD = {"KRIPTO": "kripto", "BIST": "BIST", "ABD": "ABD hisseleri", "HEPSI": "tüm piyasalar"}
MIN_ORNEK = 30                                  # bundan az kirilimli sonuca guvenilmez
DERECE = ((0.40, "GÜÇLÜ", "#4caf50", "işlem alınabilir"),          # islem basina ortalama R'ye gore
          (0.15, "İYİ", "#9ccc65", "işlem alınabilir"),
          (0.00, "TEMKİNLİ", "#ffb74d", "küçük pozisyon, yarım hedefte kâr al"),
          (-99.0, "KAÇIN", "#ef5350", "işlem alma"))
try:
    with open(ISTATISTIK_DOSYA, encoding="utf-8") as _fh:
        _J = json.load(_fh)
        ISTATISTIK, KALITE_IST = _J.get("veri", {}), _J.get("kalite", {})
except Exception:  # noqa: BLE001
    ISTATISTIK, KALITE_IST = {}, {}
SEMBOL_DOSYA = os.path.join(os.path.dirname(os.path.abspath(__file__)), "sembol_istatistik.json")
try:
    with open(SEMBOL_DOSYA, encoding="utf-8") as _fh:
        SEMBOL_IST = json.load(_fh).get("veri", {})
except Exception:  # noqa: BLE001
    SEMBOL_IST = {}

# Kirilim kalitesi: gecmis ~8.000 kirilimda sonucu ayiran uc kontrol (ucgen ve OBO'da belirgin, ikilide zayif):
#   1) risk/odul >= 1,25 (giris kirilim kapanisi, stop gecersizlik, kar al hedef; gercek fiyatla)
#   2) EMA200 yonunde (yukari kirilimda kapanis EMA200 ustunde, asagi kirilimda altinda)
#   3) Bollinger genisligi >= 3,2 ATR: onceki 20 kapanisin 4 standart sapmasi (fiyat cizgiye hareketli geliyor).
#      Hacim (>= 1,5x) yerine: yukari kirilimlarda hacim ayirmiyordu, BB genisligi her zaman diliminde ayiriyor
#      (gunluk +0,49R / +0,16R). MACD, RSI, ADX, OBV, CMF, ROC, yillik konum, ATR daralmasi denendi, ayirmadi.
# Puan 3/3 'saglam', 2/3 'orta', 0-1/3 'zayif' diye gruplanir; ekranda bu formasyonun ayni gruptaki gecmis sonucu
# (derece) gosterilir. Yukari kirilimlarda belirgin ayirt ediyor, asagi kirilimlarda zayif.
KALITE = dict(RR=1.25, HACIM=1.5, HACIM_N=20, EMA=200, BB=3.2, BB_N=20)


def ema(x, n: int) -> np.ndarray:
    x = np.asarray(x, float)
    a, out = 2.0 / (n + 1), np.empty(len(x))
    out[0] = x[0]
    for i in range(1, len(x)):
        out[i] = a * x[i] + (1 - a) * out[i - 1]
    return out


def rr_fiyat(giris: float, gec: float, hedef: float, yukari: bool) -> float | None:
    """Risk/odul gercek fiyatla: odul = hedefe uzaklik, risk = gecersizlige uzaklik (tespit uzayi log ise exp)."""
    ex = math.exp if LOG else (lambda x: x)
    s = 1 if yukari else -1
    risk, odul = s * (ex(giris) - ex(gec)), s * (ex(hedef) - ex(giris))
    return odul / risk if risk > 0 and odul > 0 else None


def _ema200(d: dict) -> np.ndarray:
    e = d.get("_ema200")
    if e is None or len(e) != len(d["c"]):
        e = d["_ema200"] = ema(d["c"], KALITE["EMA"])
    return e


def trend_yonu(d: dict, b: int, yukari: bool) -> bool | None:
    """Kapanis EMA200'un kirilim yonunde mi (yeterli gecmis yoksa None)."""
    if b < KALITE["EMA"]:
        return None
    return bool((1 if yukari else -1) * (d["c"][b] - _ema200(d)[b]) >= 0)


def hacim_orani(d: dict, b: int) -> float | None:
    v = d.get("v")
    if v is None or len(v) != len(d["c"]) or b < 1:
        return None
    ort = float(np.mean(v[max(0, b - KALITE["HACIM_N"]):b]))
    return float(v[b]) / ort if ort > 0 else None


def bb_genislik(d: dict, b: int) -> float | None:
    """Onceki 20 kapanisin Bollinger genisligi (4 standart sapma) / ATR: kirilima hareketli mi gelindi."""
    n = KALITE["BB_N"]
    if b < n:
        return None
    a = atr(d["h"], d["l"], d["c"])[b] if "_atr" not in d or len(d["_atr"]) != len(d["c"]) else d["_atr"][b]
    return float(4 * np.std(d["c"][b - n:b]) / a) if a > 0 else None


def kirilim_kalitesi(d: dict, o: dict) -> dict:
    """Kirilim mumundaki uc kontrol (bkz. KALITE). Donus: puan 0-3, sev, rr, trend, hacim."""
    b, yuk = o["b"], o["yon"] == "yukari"
    rr = rr_fiyat(d["c"][b], o["gecersiz"], o["hedef"], yuk)
    if "_atr" not in d or len(d["_atr"]) != len(d["c"]):
        d["_atr"] = atr(d["h"], d["l"], d["c"])
    tr, bb = trend_yonu(d, b, yuk), bb_genislik(d, b)
    puan = int(rr is not None and rr >= KALITE["RR"]) + int(bool(tr)) + int(bb is not None and bb >= KALITE["BB"])
    return dict(puan=puan, sev="saglam" if puan == 3 else "orta" if puan == 2 else "zayif", rr=rr, trend=tr, bb=bb,
                hacim=hacim_orani(d, b))


def haftalik_trend(d: dict, b: int, yukari: bool) -> bool | None:
    """Gunluk grafikte: son kapanmis haftanin kapanisi haftalik EMA50'nin kirilim yonunde mi. Test (gunluk
    yukari kirilim): yonundeyse +0,38R, degilse +0,20R (asagi kirilimda -0,05R / -0,20R); 4s ve 3g'de fark yok."""
    hafta = (np.asarray(d["t"], float) // 1 + 3 * 86400) // (7 * 86400)    # pazartesi baslayan hafta numarasi
    h0 = hafta[b]
    son = {}
    for i in range(b + 1):
        if hafta[i] < h0:
            son[hafta[i]] = d["c"][i]                    # haftanin son kapanisi
    if len(son) < 52:
        return None
    wc = np.array([son[k] for k in sorted(son)])
    return bool((1 if yukari else -1) * (wc[-1] - ema(wc, 50)[-1]) > 0)


def _fiyat_r(x: float) -> str:
    """Gercek fiyati yazar (fiyat() ile ayni bicim)."""
    return fiyat(math.log(x) if LOG else x)


def degen_mum(d: dict, o: dict) -> int | None:
    """Yukari kirilimda: formasyon boyunca kirilan cizgiye degen (ucu cizgiye 0,3 ATR yakin, kapanisi gecmeyen) mum sayisi.
    Test (~3.600 yukari kirilim, gunluk+): <=10 mum kazanc orani %50 · +0,53R, 11+ mum %43 · +0,47R. Asagida fark yok."""
    if o["yon"] != "yukari" or o["tur"] != "kirilim":
        return None
    f, b = o["f"], o["b"]
    x0 = int(f["x0"]) if "x0" in f else int(min(n_[0] for n_ in f.get("noktalar", [(b, 0)])))
    A = d.get("_A")
    if A is None:
        A = d["_A"] = np.nan_to_num(atr(d["h"], d["l"], d["c"]))
    cz = (lambda i: deger(f, i, "u")) if o["desen"] == "ucgen" else (lambda i: boyun(f, i))
    n = 0
    for i in range(max(x0, 0), b):
        if d["h"][i] - cz(i) >= -0.3 * A[i] and d["c"][i] - cz(i) <= 0.3 * A[i]:
            n += 1
    return n


def eski_tepe(d: dict, o: dict) -> bool | None:
    """Yukari kirilimda: formasyondan onceki 250 mumda giris ile hedef arasinda kalan eski tepe var mi.
    Test (~3.600 yukari kirilim): varsa +0,62R, yoksa +0,30R; her zaman dilimi, piyasa ve iki donemde ayni yonde
    (fiyat eski zirvesine geri donuyor). Asagi kirilimda fark yok."""
    if o["yon"] != "yukari":
        return None
    f, b = o["f"], o["b"]
    x0 = int(f["x0"]) if "x0" in f else int(min(n_[0] for n_ in f.get("noktalar", [(b, 0)])))
    bas = max(0, b - 250)
    if x0 <= bas:
        return None
    ext = float(np.max(d["h"][bas:x0]))
    return bool(ext > d["c"][b] and ext < o["hedef"])


def kalite_gecmis(anahtar: str, aralik: str | None, sev: str) -> list | None:
    """Bu formasyonun bu kalitedeki gecmis kirilimlari (tum piyasalar): [hedef %, yarim %, R, n]."""
    if aralik == "8h" and not KALITE_IST.get(anahtar, {}).get("8h"):
        aralik = "1d"
    return KALITE_IST.get(anahtar, {}).get(aralik or "", {}).get(sev)


ZAMAN_KISA = {"4h": "4S", "8h": "8S", "1d": "G", "3d": "3G", "1w": "H"}


def sembol_gecmisi(piyasa: str | None, sym: str | None, aralik: str | None) -> dict | None:
    """Bu sembolde tum formasyonlarin zaman dilimine gore gecmis kirilimlari (ucgen_istatistik.py).
    Az ornekli sonuc genel ortalamaya cekilir (8 kirilim agirlik): tek tuk kirilim 'en iyi' secmesin."""
    x = SEMBOL_IST.get(f"{piyasa}:{sym}") if piyasa and sym else None
    if not x:
        return None
    satir = []
    for a in ("4h", "8h", "1d", "3d", "1w"):
        v = x.get(a)
        if not v:
            continue
        n, hedef, R, R0 = v
        satir.append(dict(aralik=a, n=n, hedef=hedef, R=R, Rc=(n * R + 8 * R0) / (n + 8), burasi=a == aralik))
    if not satir:
        return None
    en = max((s_ for s_ in satir if s_["n"] >= 3), key=lambda s_: s_["Rc"], default=None)
    return dict(satir=satir, en=en)


def _ilk_buyuk(s: str) -> str:
    return ("İ" + s[1:]) if s[:1] == "i" else s[:1].upper() + s[1:]


def _buyuk(s: str) -> str:
    return s.replace("i", "İ").upper()


def _r_yazi(x: float) -> str:
    return f"{x:+.2f}R".replace(".", ",").replace("-", "−")


def guven(anahtar: str, piyasa: str | None, aralik: str | None) -> dict | None:
    """Gecmis kirilimlara gore guven derecesi (ucgen_istatistik.py sonuclari, formasyon_istatistik.json).
    anahtar: ucgen_yukari / ucgen_asagi / ikili_dip / ikili_tepe / ters_obo / obo.
    Piyasada en az 30 kirilim yoksa tum piyasalarin sonucu kullanilir. 'en': bu formasyonun en karli zaman dilimi."""
    if not ISTATISTIK or aralik not in ZAMAN_AD:
        return None
    piyasa = piyasa if piyasa in PIYASA_AD else "HEPSI"
    if aralik == "8h" and piyasa in ("BIST", "ABD"):
        aralik = "1d"                                   # hisse seansi <= 8 saat: 8 saatlik mum = gunluk mum
    tablo = ISTATISTIK.get(anahtar, {})
    hucre = kaynak = None
    for p in (piyasa, "HEPSI"):
        x = tablo.get(p, {}).get(aralik)
        if x and x[3] >= MIN_ORNEK:
            hucre, kaynak = x, p
            break
    if hucre is None:
        hucre, kaynak = tablo.get("HEPSI", {}).get(aralik), "HEPSI"
        if not hucre:
            return None
    hedef, yarim, R, n = hucre
    if n < MIN_ORNEK:
        ad, renk, notu = "AZ ÖRNEK", "#9e9e9e", "geçmiş örnek az, güvenme"
    else:
        ad, renk, notu = next((a, r, t) for esik, a, r, t in DERECE if R >= esik)
    en = None
    for p in (piyasa, "HEPSI"):
        aday = [(v[2], a, v[0]) for a, v in tablo.get(p, {}).items() if v[3] >= MIN_ORNEK]
        if aday:
            R_en, a_en, h_en = max(aday)
            en = dict(aralik=a_en, hedef=h_en, R=R_en, burasi=a_en == aralik)
            break
    return dict(ad=ad, renk=renk, notu=notu, hedef=hedef, yarim=yarim, R=R, n=n, kaynak=kaynak, aralik=aralik, en=en)


def ucgen_anahtar(f: dict, yon: str) -> str:
    """Gecmis isabet tablosunda ucgenin satiri: buyuk ucgen ayri olculdu (yukari kirilimi kucuklerden iyi)."""
    return f"{'buyuk_' if f.get('buyuk') else ''}ucgen_{yon}"


def ucgen_adi(f: dict) -> str:
    return f"Büyük {f['tip'].lower()}" if f.get("buyuk") else f["tip"]


def en_iyi_yazi(g: dict | None) -> str:
    e = g and g.get("en")
    if not e:
        return "—"
    if e["R"] < 0:
        return "hiçbiri kârlı değil"
    return f"{ZAMAN_AD[e['aralik']]} %{e['hedef']} ({_r_yazi(e['R'])})" + (" ← bu grafik" if e["burasi"] else "")


def guven_metni(g: dict | None, yon: str = "") -> str:
    """Telegram mesaji icin tek satir."""
    if not g:
        return ""
    return (f"\n📊 {yon}{g['ad']} — geçmişte %{g['hedef']} hedefe ulaştı, işlem başına {_r_yazi(g['R'])} "
            f"({PIYASA_AD[g['kaynak']]}, {ZAMAN_AD[g['aralik']]}). {_ilk_buyuk(g['notu'])}. "
            f"En iyi zaman dilimi: {en_iyi_yazi(g)}")


BEYAZ, GRI = "#e0e3eb", "#9598a1"


def _ucgen_hesap(d: dict, f: dict, son: int) -> dict:
    """Ucgenin o mumdaki hesaplari: cizgi degerleri, kirilim esigi, olculen hareket hedefleri, olgunluk."""
    A = atr(d["h"], d["l"], d["c"])
    up, lw, w0 = deger(f, son, "u"), deger(f, son, "l"), f["w0"]
    return dict(tol=kirilim_payi(f, A[son]), up=up, lw=lw, gen=up - lw, w0=w0, c=d["c"][son],
                h_u=up + w0, h_a=lw - w0, olg=(son - f["x0"]) / (f["apex"] - f["x0"]) * 100,
                kalan=max(0.0, f["apex"] - son))


def _hedef_yazi(x: float, c: float) -> str:
    return f"{fiyat(x)} ({_yuzde(x, c)})" if LOG or x > 0 else "sıfırın altında (geçersiz)"


def _guven_satiri(g: dict | None, girinti: str = "") -> list:
    if not g:
        return []
    return [[(girinti, BEYAZ, None), (g["ad"], g["renk"], "bold"),
             (f": {g['notu']} · geçmiş %{g['hedef']} hedef, {_r_yazi(g['R'])}/işlem", BEYAZ, None)]]


def _kaynak_satiri(*gs, buyuk: bool = False) -> list:
    gs = [g for g in gs if g]
    if not gs:
        return []
    n = " / ".join(f"{g['n']:,}".replace(",", ".") for g in gs)
    return [[(f"Kaynak: {PIYASA_AD[gs[0]['kaynak']]} · {ZAMAN_AD[gs[0]['aralik']]} grafik · "
              f"{n} geçmiş {'büyük üçgen ' if buyuk else ''}kırılım", GRI, None)]]


def _isaret(ok) -> str:
    return "—" if ok is None else "✓" if ok else "✗"


def _sayi(x: float, nd: int = 1) -> str:
    return f"{x:.{nd}f}".replace(".", ",")


def kalite_yazi(d: dict, o: dict, anahtar: str, aralik: str | None) -> dict:
    """Kirilim mumundaki uc kontrol (puan, ayrinti) ve bu formasyonun ayni puandaki gecmis kirilimlarinin derecesi
    (gecmis: ad, renk, hedef %, R; 30'dan az ornekte None). Derece olculen R'den: puan her yerde ayni yonde
    calismiyor (asagi kirilimlarda zayif), o yuzden gosterilen yargi puanin degil gecmisin."""
    q = kirilim_kalitesi(d, o)
    rr = f"R/Ö {_sayi(q['rr'])} {_isaret(q['rr'] >= KALITE['RR'])}" if q["rr"] else "R/Ö — ✗"
    hc = f"BB {_sayi(q['bb'])} ATR {_isaret(q['bb'] >= KALITE['BB'])}" if q["bb"] is not None else "BB —"
    g = kalite_gecmis(anahtar, aralik, q["sev"])
    gec = None
    if g and g[3] >= MIN_ORNEK:
        ad, renk = next((a, r) for esik, a, r, _ in DERECE if g[2] >= esik)
        gec = dict(ad=ad, renk=renk, hedef=g[0], R=g[2], n=g[3])
    return dict(puan=f"{q['puan']}/3", ayr=f"{rr} · trend {_isaret(q['trend'])} · {hc}", gec=gec)


def _kalite_satiri(d: dict, o: dict, anahtar: str, aralik: str | None) -> list:
    k = kalite_yazi(d, o, anahtar, aralik)
    satir = [(f"Kırılım kalitesi {k['puan']}: {k['ayr']}", BEYAZ, None)]
    if k["gec"]:
        satir += [(" → bu durumda geçmiş ", BEYAZ, None), (k["gec"]["ad"], k["gec"]["renk"], "bold"),
                  (f" %{k['gec']['hedef']}, {_r_yazi(k['gec']['R'])}", BEYAZ, None)]
    L_ = [satir]
    if aralik == "1d":
        ht = haftalik_trend(d, o["b"], o["yon"] == "yukari")
        if ht is not None:
            L_.append([("Haftalık trend: ", BEYAZ, None), ("yönünde ✓" if ht else "ters", "#4caf50" if ht else GRI, "bold"),
                       (" (günlük geçmiş: yönünde +0,38R · değil +0,20R)" if o["yon"] == "yukari" else
                        " (günlük geçmiş: yönünde −0,05R · değil −0,20R)", BEYAZ, None)])
    et = eski_tepe(d, o)
    if et is None:
        return L_
    return L_ + [[("Hedef yolunda eski tepe: ", BEYAZ, None), ("var ✓" if et else "yok", "#4caf50" if et else GRI, "bold"),
                    (" (geçmişte var +0,62R · yok +0,30R)", BEYAZ, None)]]


def _kontrol_satiri(d: dict, son: int, yonler: list, onay: bool = False) -> list:
    """Aktif formasyon: saglam kirilim icin gerekenler. yonler: [(etiket, yukari)]; R/O hedef satirinda."""
    tr = " · ".join(f"{et}trend {_isaret(trend_yonu(d, son, yuk))}" for et, yuk in yonler)
    bb = bb_genislik(d, son)
    return [[(f"Sağlam {'onay' if onay else 'kırılım'} için: R/Ö ≥ {_sayi(KALITE['RR'], 2)} · {tr} · BB ≥ "
              f"{_sayi(KALITE['BB'])} ATR (şimdi {_sayi(bb) if bb is not None else '—'})", GRI, None)]]


def sembol_yazi(piyasa: str | None, sym: str | None, aralik: str | None) -> tuple | None:
    """(zaman dilimleri, sonuc): bu sembolde tum formasyonlarin zaman dilimine gore gecmis hedef orani."""
    g = sembol_gecmisi(piyasa, sym, aralik)
    if not g:
        return None
    ust = " · ".join(f"{ZAMAN_KISA[x['aralik']]} %{x['hedef']} ({x['n']})" for x in g["satir"])
    e = g["en"]
    if e is None:
        return ust, "örnek az", False
    if e["Rc"] < 0:
        return ust, "hiçbiri kârlı değil", False
    return ust, f"en iyi {ZAMAN_AD[e['aralik']]}" + (" ← bu grafik" if e["burasi"] else ""), True


def _sembol_satiri(piyasa: str | None, sym: str | None, aralik: str | None) -> list:
    x = sembol_yazi(piyasa, sym, aralik)
    if not x:
        return []
    ust, son, iyi = x
    return [[("Bu sembol: ", BEYAZ, None), (ust, BEYAZ, None), (f" → {son}", "#4caf50" if iyi else GRI, "bold")]]


def _ucgen_satirlari(f: dict, h: dict, olay: dict | None, piyasa: str | None, aralik: str | None,
                     d: dict | None = None, sym: str | None = None, son: int | None = None) -> list:
    """Ucgen kutusu: hesaplar + her kirilim yonunun gecmis guven derecesi ve en iyi zaman dilimi.
    Her satir (metin, renk, kalinlik) parcalarindan olusur."""
    c = h["c"]
    if olay and olay["tur"] == "kirilim":
        yuk = olay["yon"] == "yukari"
        esik = olay["seviye"] + (h["tol"] if yuk else -h["tol"])
        rr_v = rr_fiyat(c, olay["gecersiz"], olay["hedef"], yuk)
        rr = f"1 : {_sayi(rr_v)}" if rr_v else "—"
        g = guven(ucgen_anahtar(f, olay["yon"]), piyasa, aralik)
        L = [[(f"{ucgen_adi(f)} üçgen · {f['dok']} dokunuş · {H_AD} = {_h_yazi(h['w0'])}", BEYAZ, "bold")],
             [(f"{'▲ Yukarı' if yuk else '▼ Aşağı'} kırıldı: kapanış {fiyat(c)} · çizgi {fiyat(olay['seviye'])} · "
               f"eşik {fiyat(esik)}", BEYAZ, None)],
             [(f"Hedef = {fiyat(olay['seviye'])} {_hareket(yuk)} H = {_hedef_yazi(olay['hedef'], c)}",
               BEYAZ, None)],
             [(f"Geçersizlik ({'alt' if yuk else 'üst'} çizgi) {fiyat(olay['gecersiz'])} "
               f"({_yuzde(olay['gecersiz'], c)}) · risk/ödül {rr}", BEYAZ, None)]]
        L += _guven_satiri(g)
        if d is not None:
            L += _kalite_satiri(d, olay, ucgen_anahtar(f, olay["yon"]), aralik)
        if g:
            L.append([(f"En iyi zaman dilimi ({'yukarı' if yuk else 'aşağı'} kırılım): {en_iyi_yazi(g)}", BEYAZ, None)])
        L += _sembol_satiri(piyasa, sym, aralik)
        return L + _kaynak_satiri(g, buyuk=f.get("buyuk", False))
    rr_u = rr_fiyat(h["up"] + h["tol"], h["lw"], h["h_u"], True)
    rr_a = rr_fiyat(h["lw"] - h["tol"], h["up"], h["h_a"], False)
    rr_y = lambda x: f"R/Ö 1 : {_sayi(x)}" if x else "R/Ö —"   # noqa: E731
    gy, ga = guven(ucgen_anahtar(f, "yukari"), piyasa, aralik), guven(ucgen_anahtar(f, "asagi"), piyasa, aralik)
    L = [[(f"{ucgen_adi(f)} üçgen · {f['dok']} dokunuş · olgunluk %{h['olg']:.0f} · apex'e {h['kalan']:.0f} mum",
           BEYAZ, "bold")],
         [(f"{H_AD} = {_h_yazi(h['w0'])} · stop: karşı çizgi", BEYAZ, None)],
         [(f"▲ Üst {fiyat(h['up'])} ({_yuzde(h['up'], c)}) · kırılım: kapanış > {fiyat(h['up'] + h['tol'])}",
           BEYAZ, None)],
         [(f"    hedef = {fiyat(h['up'])} {_hareket(True)} H = {_hedef_yazi(h['h_u'], c)} · {rr_y(rr_u)}",
           BEYAZ, None)]]
    L += _guven_satiri(gy, "    ")
    L += [[(f"▼ Alt {fiyat(h['lw'])} ({_yuzde(h['lw'], c)}) · kırılım: kapanış < {fiyat(h['lw'] - h['tol'])}",
            BEYAZ, None)],
          [(f"    hedef = {fiyat(h['lw'])} {_hareket(False)} H = {_hedef_yazi(h['h_a'], c)} · {rr_y(rr_a)}",
            BEYAZ, None)]]
    L += _guven_satiri(ga, "    ")
    if gy and ga:
        L.append([(f"En iyi zaman dilimi: ▲ {en_iyi_yazi(gy)} · ▼ {en_iyi_yazi(ga)}", BEYAZ, None)])
    if d is not None and son is not None:
        if aralik == "1d":
            hu, ha = haftalik_trend(d, son, True), haftalik_trend(d, son, False)
            if hu is not None:
                L.append([("Haftalık trend: ", BEYAZ, None), ("▲ yönünde ✓" if hu else "▼ yönünde" if ha else "yatay", "#4caf50" if hu else GRI, "bold"),
                          (" (günlük ▲ kırılımda yönündeyse +0,38R · değilse +0,20R)", BEYAZ, None)])
        et = eski_tepe(d, dict(f=f, b=son, yon="yukari", hedef=h["h_u"]))
        if et is not None:
            L.append([("▲ Hedef yolunda eski tepe: ", BEYAZ, None), ("var ✓" if et else "yok", "#4caf50" if et else GRI, "bold"),
                      (" (geçmişte var +0,62R · yok +0,30R)", BEYAZ, None)])
        L += _kontrol_satiri(d, son, [("▲ ", True), ("▼ ", False)])
    L += _sembol_satiri(piyasa, sym, aralik)
    return L + _kaynak_satiri(gy, ga, buyuk=f.get("buyuk", False))


def _donus_satirlari(d: dict, f: dict, son: int, olay: dict | None, piyasa: str | None, aralik: str | None,
                     sym: str | None = None) -> list:
    """Ikili tepe/dip ve OBO kutusu: boyun, onay esigi, hedef (boyun +/- H), gecersizlik, risk/odul,
    gecmis guven derecesi ve en iyi zaman dilimi."""
    A = atr(d["h"], d["l"], d["c"])
    tol = AYAR["TOL_ATR"] * A[son]
    yukari = f["yon"] == "yukari"
    s = 1 if yukari else -1
    c = d["c"][son]
    kirildi = bool(olay and olay["tur"] == "kirilim")
    nl = olay["seviye"] if kirildi else boyun(f, son)
    hedef = olay["hedef"] if kirildi else nl + s * f["yuk"]
    esik = nl + s * tol
    gec = f["gecersiz"]
    giris = c if kirildi else esik
    rr_v = rr_fiyat(giris, gec, hedef, yukari)
    rr = f"1 : {_sayi(rr_v)}" if rr_v else "—"
    g = guven(f["tur"], piyasa, aralik)
    L = [[(f"{DESEN_AD[f['tur']]} · H ({'oran' if LOG else 'yükseklik'}) = {_h_yazi(f['yuk'])} · {'ONAYLANDI' if kirildi else 'onay bekliyor'}",
           BEYAZ, "bold")]]
    if kirildi:
        L.append([(f"Boyun {fiyat(nl)} {'yukarı' if yukari else 'aşağı'} kırıldı: kapanış {fiyat(c)} "
                   f"(eşik {fiyat(esik)})", BEYAZ, None)])
    else:
        L.append([(f"Boyun {fiyat(nl)} ({_yuzde(nl, c)}) · onay: kapanış {'>' if yukari else '<'} {fiyat(esik)}",
                   BEYAZ, None)])
    L += [[(f"Hedef = boyun {_hareket(yukari)} H = {_hedef_yazi(hedef, c)}", BEYAZ, None)],
          [(f"Geçersizlik {fiyat(gec)} ({_yuzde(gec, c)}) · risk/ödül {rr}", BEYAZ, None)]]
    L += _guven_satiri(g)
    if kirildi:
        L += _kalite_satiri(d, olay, f["tur"], aralik)
    if g:
        L.append([(f"En iyi zaman dilimi: {en_iyi_yazi(g)}", BEYAZ, None)])
    if not kirildi:
        L += _kontrol_satiri(d, son, [("", yukari)], onay=True)
    L += _sembol_satiri(piyasa, sym, aralik)
    return L + _kaynak_satiri(g)


def _kutu_yerlestir(fig, ax, satirlar: list, d: dict, f: dict, bas: int, bit: int, son: int, uc: float | None):
    """Hesap kutusunu (satir satir renkli) yerlestirir. Ucgende: ucgenin icinde mumlari en az ortecegi yere
    (son mumlar ve diger yazilar ozellikle korunur); ucgen dar gelirse hemen disindaki en bos yere.
    Donus formasyonunda (uc=None): grafikteki en bos yere. Hicbir yer uygun degilse grafigin ustunde bos bir
    serit acilir (dikey eksen genisletilir), kutu oraya konur: yazi ya da cizgi hicbir zaman ortulmez."""
    from matplotlib.offsetbox import AnnotationBbox, HPacker, TextArea, VPacker
    fs = 6.6
    cocuk = []
    for parcalar in satirlar:
        ta = [TextArea(t, textprops=dict(color=r_, fontsize=fs, fontweight=w or "normal")) for t, r_, w in parcalar]
        cocuk.append(ta[0] if len(ta) == 1 else HPacker(children=ta, align="baseline", pad=0, sep=0))
    ab = AnnotationBbox(VPacker(children=cocuk, align="left", pad=0, sep=2.2), (0, 0), xycoords="data",
                        box_alignment=(0, 0), pad=0.5, annotation_clip=False, zorder=8,
                        bboxprops=dict(boxstyle="round,pad=0.2", facecolor="#131722", edgecolor="#787b86", alpha=0.75))
    ab.set_in_layout(False)
    ax.add_artist(ab)
    r = fig.canvas.get_renderer()
    idx = np.arange(bas, bit + 1)
    H, L = d["h"][bas:bit + 1], d["l"][bas:bit + 1]
    agirlik = np.where(idx > son - 3, 10.0, np.where(idx > son - 10, 3.0, 1.0))   # son mumlar (fiyatin bugunku
    #                                                               yeri, kirilim bolgesi) ozellikle ortulmesin
    x_f = f["x0"] if uc is not None else f["noktalar"][0][0]

    def olc():
        (xa, xb), (ya, yb) = ax.get_xlim(), ax.get_ylim()
        ab.xy = ab.xybox = (xa, ya)
        ab.update_positions(r)
        pe = ab.patch.get_window_extent(r)
        cx, cy = ax.transData.transform((xa, ya))
        eb = ax.get_window_extent(renderer=r)
        sx, sy = eb.width / (xb - xa), eb.height / (yb - ya)        # piksel / mum, piksel / fiyat
        o = dict(xa=xa, xb=xb, ya=ya, yb=yb, bw=pe.width / sx, bh=pe.height / sy, hpx=pe.height, axpx=eb.height,
                 ox=(cx - pe.x0) / sx, oy=(cy - pe.y0) / sy, mx=6 / sx, my=6 / sy)
        ters = ax.transData.inverted()
        o["engel"] = []                                             # ortulmemesi gerekenler: yazilar, cizgiler
        for a in ax.texts:
            e = a.get_window_extent(renderer=r)
            (x1, y1), (x2, y2) = ters.transform([[e.x0, e.y0], [e.x1, e.y1]])
            o["engel"].append((x1, x2, y1, y2))
        for ln in ax.lines:
            if ln.get_gid() != "ucgen":
                xs, ys = np.asarray(ln.get_xdata(), float), np.asarray(ln.get_ydata(), float)
                o["engel"].append((xs.min() - o["mx"], xs.max() + o["mx"], ys.min() - o["my"], ys.max() + o["my"]))
        return o

    def maliyet(o, x1, y1):
        bw, bh = o["bw"], o["bh"]
        x2, y2 = x1 + bw, y1 + bh
        yatay = np.clip(np.minimum(idx + 0.4, x2) - np.maximum(idx - 0.4, x1), 0, None) / 0.8
        dikey = np.clip(np.minimum(H, y2) - np.maximum(L, y1), 0, None) / bh
        m = float((yatay * dikey * agirlik).sum()) / max(bw, 1.0)
        for ex1, ex2, ey1, ey2 in o["engel"]:
            if ex1 < x2 and x1 < ex2 and ey1 < y2 and y1 < ey2:
                m += 2.0
        return m

    def serbest(o, y_min):                                          # verilen yukseklikten yukarida en bos yer
        en = None
        orta = (x_f + son) / 2
        for x1 in np.arange(o["xa"] + 0.3, o["xb"] - o["bw"] - 0.3, max(0.5, o["bw"] / 10)):
            for y1 in np.linspace(max(y_min, o["ya"] + o["my"]), o["yb"] - o["my"] - o["bh"], 20):
                m = maliyet(o, x1, y1) + 0.05 * abs(x1 + o["bw"] / 2 - orta) / (o["xb"] - o["xa"])
                if en is None or m < en[0]:
                    en = (m, x1, y1)
        return en

    o = olc()
    bw, bh, mx, my = o["bw"], o["bh"], o["mx"], o["my"]
    xa, xb, ya, yb = o["xa"], o["xb"], o["ya"], o["yb"]
    en_iyi = None
    if uc is None:                                                  # donus formasyonu: en bos yer
        en_iyi = serbest(o, ya)
    else:
        x0 = f["x0"]
        x1 = x0 + max(0.8, 1.5 * mx)                                # tabandaki H cizgisinin hemen sagi
        while x1 + bw <= min(uc, xb - 0.3):                         # 1) ucgenin icinde
            x2 = x1 + bw
            alt = max(deger(f, x1, "l"), deger(f, x2, "l")) + my
            ust = min(deger(f, x1, "u"), deger(f, x2, "u")) - my
            if ust - alt >= bh:
                for y1 in np.linspace(alt, ust - bh, 12):
                    m = maliyet(o, x1, y1) + 0.03 * (x1 - x0) / max(1.0, son - x0)
                    if en_iyi is None or m < en_iyi[0]:
                        en_iyi = (m, x1, y1)
            x1 += max(0.5, bw / 12)
        if en_iyi is None or en_iyi[0] > 0.2:                       # 2) sigmadiysa / cok mum ortuyorsa: hemen disi
            for x1 in np.arange(xa + 0.3, xb - bw - 0.3, max(0.5, bw / 8)):
                x2 = x1 + bw
                ka, kb = max(x1, x0), min(x2, uc)
                for y1 in np.linspace(ya + my, yb - my - bh, 18):
                    y2 = y1 + bh
                    if ka < kb:                                     # ucgenle ayni dikey seritte: ustunde ya da altinda
                        ust_c = max(deger(f, ka, "u"), deger(f, kb, "u"))
                        alt_c = min(deger(f, ka, "l"), deger(f, kb, "l"))
                        if y1 >= ust_c + my:
                            bosluk = (y1 - ust_c) / (yb - ya)
                        elif y2 <= alt_c - my:
                            bosluk = (alt_c - y2) / (yb - ya)
                        else:
                            continue
                    else:
                        bosluk = (ka - kb) / (xb - xa)
                    m = 0.45 + maliyet(o, x1, y1) + 0.5 * bosluk
                    if en_iyi is None or m < en_iyi[0]:
                        en_iyi = (m, x1, y1)
    k = (o["hpx"] + 12) / o["axpx"]                                 # kutunun eksen yuksekligine orani
    if (en_iyi is None or en_iyi[0] >= 1.0) and k < 0.6:            # 3) uygun yer yok: ustte bos serit ac
        ax.set_ylim(ya, yb + (yb - ya) * k / (1 - k))
        o = olc()
        en_iyi = serbest(o, yb) or en_iyi
    if en_iyi is None:
        en_iyi = (0, o["xa"] + 0.5, o["yb"] - o["bh"] - o["my"])
    _, x1, y1 = en_iyi
    ab.xy = ab.xybox = (x1 + o["ox"], y1 + o["oy"])


def grafik(sym_ad: str, aralik_ad: str, d: dict, f: dict, olay: dict | None = None,
           piyasa: str | None = None, aralik: str | None = None, sym: str | None = None) -> bytes:
    """aralik: 4h / 8h / 1d / 3d / 1w (gecmis isabet tablosu icin), piyasa: KRIPTO / BIST / ABD,
    sym: ham sembol (sembolun gecmis basarisi icin)."""
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    N = len(d["c"])
    son = olay["b"] if olay else N - 1
    kirildi = bool(olay and olay["tur"] == "kirilim")
    ucgen = f.get("desen", "ucgen") == "ucgen"
    bit = min(N - 1, son + (8 if kirildi else 0))
    fig, ax = plt.subplots(figsize=(9, 4.6), dpi=140)
    fig.patch.set_facecolor("#131722"); ax.set_facecolor("#131722")
    t = datetime.fromtimestamp(d["t"][son], tz=timezone.utc).strftime("%d.%m.%Y %H:%M")
    if ucgen:
        bas = max(0, f["x0"] - 25)
        _mumlar(ax, d, bas, bit, plt)
        # kesik uzanti tepe noktasina (apex) kadar gitmez: iki cizgi tek noktada bulusmasin
        uc = son + min(0.6 * (f["apex"] - son), 0.35 * (f["apex"] - f["x0"]))
        for taraf, renk in (("u", "#ff9800"), ("l", "#2196f3")):
            x0 = f[taraf]["i0"]
            ax.plot([x0, son], [deger(f, x0, taraf), deger(f, son, taraf)], color=renk, linewidth=1.8, gid="ucgen")
            ax.plot([son, uc], [deger(f, son, taraf), deger(f, uc, taraf)], color=renk, linewidth=1.2, linestyle="--",
                    gid="ucgen")
        for x, taraf in f.get("noktalar", []):                 # cizgiye dokunan salinimlar
            if bas <= x <= son:
                ax.plot(x, deger(f, x, taraf), "o", color="#ff9800" if taraf == "u" else "#2196f3", markersize=4.5,
                        markeredgecolor="white", markeredgewidth=0.6, zorder=5, gid="ucgen")
        # H: ucgenin baslangic yuksekligi (olculen hareket) - tabanda noktali dikey cizgi
        x0 = f["x0"]
        y_a, y_u = deger(f, x0, "l"), deger(f, x0, "u")
        ax.plot([x0, x0], [y_a, y_u], color="#d1d4dc", linewidth=1.0, linestyle=":", zorder=4)
        ax.annotate("H", (x0, (y_a + y_u) / 2), xytext=(-4, 0), textcoords="offset points", ha="right", va="center",
                    color="#d1d4dc", fontsize=8, fontweight="bold")
        h = _ucgen_hesap(d, f, son)
        sag = max(bit, uc)
        satirlar = _ucgen_satirlari(f, h, olay if kirildi else None, piyasa, aralik, d, sym, son)
        son_adim = lambda: _kutu_yerlestir(fig, ax, satirlar, d, f, bas, bit, son, uc)  # noqa: E731
        baslik = f"{ucgen_adi(f)} daralan üçgen"
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
        satirlar = _donus_satirlari(d, f, son, olay, piyasa, aralik, sym)
        son_adim = lambda: _kutu_yerlestir(fig, ax, satirlar, d, f, bas, bit, son, None)  # noqa: E731
        baslik = DESEN_AD[f["tur"]]
        yukari = not tepe
    if kirildi:
        renk_h = "#4caf50" if olay["yon"] == "yukari" else "#f44336"
        ax.plot([olay["b"], sag], [olay["hedef"], olay["hedef"]], color=renk_h, linestyle=":", linewidth=1.2)
        ax.annotate(f"hedef {fiyat(olay['hedef'])}", (sag, olay["hedef"]), xytext=(-4, 3), textcoords="offset points",
                    ha="right", color=renk_h, fontsize=8)
        if ucgen:                                               # olculen hareket: kirilim mumundan H kadar
            ax.plot([olay["b"], olay["b"]], [olay["seviye"], olay["hedef"]], color=renk_h, linestyle=":", linewidth=1.0)
            ax.annotate("H", (olay["b"], (olay["seviye"] + olay["hedef"]) / 2), xytext=(-4, 0), textcoords="offset points",
                        ha="right", va="center", color=renk_h, fontsize=8, fontweight="bold")
        ax.annotate("KIRILIM", (olay["b"], d["c"][olay["b"]]), color="white", fontsize=9,
                    xytext=(5, 12 if yukari else -16), textcoords="offset points")
    ax.set_xlim(bas - 1, sag + 2)
    # dikey eksen formasyona odaklansin: soldaki bosluktaki asiri mumlar formasyonu ezmesin
    x_f = f["x0"] if ucgen else f["noktalar"][0][0]
    alt_y, ust_y = d["l"][x_f:bit + 1].min(), d["h"][x_f:bit + 1].max()
    if ucgen:                                                   # taban (H) tamamen gorunsun
        alt_y, ust_y = min(alt_y, deger(f, f["x0"], "l")), max(ust_y, deger(f, f["x0"], "u"))
    if kirildi:
        alt_y, ust_y = min(alt_y, olay["hedef"]), max(ust_y, olay["hedef"])
    disari = []
    if ucgen and not kirildi:                                   # iki yonun hedefi: olcege sigiyorsa cizgi, sigmiyorsa kenarda
        R, a0, u0 = ust_y - alt_y, alt_y, ust_y
        for seviye, renk, yuk in ((h["h_u"], "#4caf50", True), (h["h_a"], "#f44336", False)):
            if (LOG or seviye > 0) and a0 - 0.25 * R <= seviye <= u0 + 0.25 * R:
                ax.plot([son, sag], [seviye, seviye], color=renk, linestyle=":", linewidth=1.1)
                ax.annotate(f"hedef {'↑' if yuk else '↓'} {fiyat(seviye)} ({_yuzde(seviye, h['c'])})", (sag, seviye),
                            xytext=(-4, 3 if yuk else -10), textcoords="offset points", ha="right", color=renk,
                            fontsize=7.5)
                alt_y, ust_y = min(alt_y, seviye), max(ust_y, seviye)
            elif LOG or seviye > 0:
                disari.append((seviye, renk, yuk))
    pay = 0.06 * (ust_y - alt_y)
    ax.set_ylim(alt_y - pay, ust_y + pay)
    for seviye, renk, yuk in disari:
        ax.annotate(f"{'▲' if yuk else '▼'} hedef {fiyat(seviye)} ({_yuzde(seviye, h['c'])}) grafiğin "
                    f"{'üstünde' if yuk else 'altında'}", (1, 1 if yuk else 0), xycoords="axes fraction",
                    xytext=(-6, -5 if yuk else 5), textcoords="offset points", ha="right", va="top" if yuk else "bottom",
                    color=renk, fontsize=7.5)
    ax.set_title(f"{sym_ad}  {aralik_ad}  —  {baslik}  ({t} UTC)", color="white", fontsize=10)
    if LOG:
        _log_eksen(ax)
    return _bitir_grafik(fig, ax, plt, son_adim)


def _log_eksen(ax):
    """Dikey eksen log fiyatta cizilir; etiketler okunur fiyat seviyelerinde (1-1,2-1,5-2-2,5-3-4-5-6-8 x 10^k)."""
    from matplotlib.ticker import FixedLocator, FuncFormatter, MaxNLocator
    a, b = ax.get_ylim()
    pa, pb = math.exp(a), math.exp(b)
    adim = (b - a) / 7
    k0, k1 = math.floor(math.log10(pa)), math.ceil(math.log10(pb))
    aday = sorted(m * 10 ** k for k in range(k0 - 1, k1 + 1) for m in (1, 1.2, 1.5, 2, 2.5, 3, 4, 5, 6, 8)
                  if pa <= m * 10 ** k <= pb)
    secilen: list = []
    for p in aday:
        if not secilen or math.log(p) - math.log(secilen[-1]) >= 0.8 * adim:
            secilen.append(p)
    if len(secilen) < 4:                                        # dar aralik: duz adimlar (log ~ dogrusal)
        secilen = [p for p in MaxNLocator(6).tick_values(pa, pb) if pa <= p <= pb]
    ax.yaxis.set_major_locator(FixedLocator([math.log(p) for p in secilen]))
    ax.yaxis.set_major_formatter(FuncFormatter(lambda v, _: fiyat(v)))


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
    """Tespit uzayindaki bir seviyeyi fiyat olarak yazar (LOG ise exp alinir)."""
    if LOG:
        x = math.exp(x)
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
        return binance(sym, aralik, 1000 if aralik == "1d" else 400)   # gunlukte haftalik EMA50 icin ~3 yil
    return yahoo(sym + ".IS" if piyasa == "BIST" else sym)


def _yuzde(x: float, c: float) -> str:
    return f"{(math.exp(x - c) - 1 if LOG else x / c - 1) * 100:+.1f}%"


def _h_yazi(w: float) -> str:
    """Olculen hareket (H): LOG'da taban orani (x2,37), degilse fiyat farki."""
    return f"×{math.exp(w):.2f}".replace(".", ",") if LOG else fiyat(w)


def _hareket(yukari: bool) -> str:
    """Hedef formulundeki islem: LOG'da carpma / bolme, degilse arti / eksi."""
    return ("×" if yukari else "÷") if LOG else ("+" if yukari else "−")


H_AD = "H (taban oranı)" if LOG else "H (taban yüksekliği)"


def _ek_satirlar(o: dict, d: dict, anahtar: str, piyasa: str | None, aralik: str | None, sym: str | None) -> list:
    """Telegram mesajina: kirilim kalitesi (kirilimda) ve sembolun gecmis basarisi."""
    ek = []
    if o["tur"] == "kirilim":
        k = kalite_yazi(d, o, anahtar, aralik)
        g = k["gec"]
        ek.append(f"\n🔎 Kırılım kalitesi {k['puan']} ({k['ayr']})"
                  + (f" → bu durumda geçmiş {g['ad']}: %{g['hedef']}, {_r_yazi(g['R'])}" if g else ""))
        if o.get("tekrar"):
            sahte = o["tekrar"] != o["yon"]
            ek.append(f"\n🔁 2. kırılım: bu üçgen daha önce {'▲ yukarı' if o['tekrar'] == 'yukari' else '▼ aşağı'} kırılmıştı"
                      + (" (o kırılım sahte çıktı, çizgi yeniden çizildi)" if sahte else " (aynı yönde)"))
    if o["tur"] == "kirilim" and o["yon"] == "yukari":
        gr = math.exp(d["c"][o["b"]]) if LOG else float(d["c"][o["b"]])
        hr = math.exp(o["hedef"]) if LOG else float(o["hedef"])
        ek.append(f"\n💰 Plan: ½ sat {_fiyat_r(gr + 0.5 * (hr - gr))} (yolun yarısı) → stop girişe · kalan hedef "
                  f"{_fiyat_r(gr + 1.5 * (hr - gr))} (1,5×H)")
    if o["tur"] == "kirilim":
        if aralik == "1d":
            ht = haftalik_trend(d, o["b"], o["yon"] == "yukari")
            if ht is not None:
                ek.append(f"\n📅 Haftalık trend {'yönünde ✓' if ht else 'ters'}"
                          + (" (günlükte yönündeyse +0,38R, değilse +0,20R)" if o["yon"] == "yukari" else ""))
        et = eski_tepe(d, o)
        if et is not None:
            ek.append(f"\n⛰ Hedef yolunda eski tepe {'var ✓ (geçmişte +0,62R)' if et else 'yok (geçmişte +0,30R)'}")
        dm = degen_mum(d, o)
        if dm is not None:
            ek.append(f"\n✋ Çizgiye değen mum: {dm}" + (" ⚠ fazla (11+ geçmişte %43 kazanç)" if dm >= 11 else " ✓ (≤10 geçmişte %50 kazanç)"))
        if piyasa in ("KRIPTO", "BIST"):
            ho = hacim_orani(d, o["b"])
            if ho is not None:
                ek.append(f"\n📊 Hacim {ho:.1f}×".replace(".", ",")
                          + (" ✓ (≥1,5× geçmişte hedefe ulaşma ~10 puan yüksek)" if ho >= 1.5 else " (1,5× altı)"))
    x = sembol_yazi(piyasa, sym, aralik)
    if x:
        ek.append(f"\n📈 Bu sembol: {x[0]} → {x[1]}")
    return ek


def _mesaj(govde: str, ek: list, link: str) -> str:
    """Fotograf aciklamasi 1024 karakter: sigmazsa once sembol satiri, sonra kalite satiri duser (link kalir)."""
    while ek and len(govde + "".join(ek) + "\n" + link) > 1015:
        ek = ek[:-1]
    return govde + "".join(ek) + "\n" + link


def olay_metni(o: dict, d: dict, ad: str, aralik_ad: str, link: str, piyasa: str | None = None,
               aralik: str | None = None, sym: str | None = None) -> str:
    f = o["f"]
    c = d["c"][o["b"]]
    if o["desen"] == "ucgen":
        if o["tur"] == "kirilim":
            bas = "🚀 YUKARI KIRILIM" if o["yon"] == "yukari" else "🔻 AŞAĞI KIRILIM"
            g = guven(ucgen_anahtar(f, o["yon"]), piyasa, aralik)
            return _mesaj(f"{bas} — {ad} ({aralik_ad})\n{ucgen_adi(f)} daralan üçgen, {f['dok']} dokunuş\n"
                          f"Kapanış: {fiyat(c)}  |  Kırılan seviye: {fiyat(o['seviye'])}\n"
                          f"Hedef (ölçülen hareket): {fiyat(o['hedef'])} ({_yuzde(o['hedef'], c)})\n"
                          f"Geçersizlik: {fiyat(o['gecersiz'])} ({_yuzde(o['gecersiz'], c)}){guven_metni(g)}",
                          _ek_satirlar(o, d, ucgen_anahtar(f, o["yon"]), piyasa, aralik, sym), link)
        taraf = "ÜST (direnç)" if o["yon"] == "ust" else "ALT (destek)"
        g = guven(ucgen_anahtar(f, "yukari" if o["yon"] == "ust" else "asagi"), piyasa, aralik)
        return _mesaj(f"🔺 KIRILIMA YAKIN — {ad} ({aralik_ad})\n{ucgen_adi(f)} daralan üçgen, {f['dok']} dokunuş\n"
                      f"Fiyat {taraf} çizgisine yaklaştı: kapanış {fiyat(c)}, çizgi {fiyat(o['seviye'])} "
                      f"({_yuzde(o['seviye'], c)})"
                      f"{guven_metni(g, ('Yukarı' if o['yon'] == 'ust' else 'Aşağı') + ' kırılırsa: ')}\n"
                      f"Sağlam kırılım için: R/Ö ≥ {_sayi(KALITE['RR'], 2)}, BB genişliği ≥ {_sayi(KALITE['BB'])} ATR, "
                      f"EMA200 {dict([(True, 'yönünde ✓'), (False, 'ters ✗')]).get(trend_yonu(d, o['b'], o['yon'] == 'ust'), 'yok')}",
                      _ek_satirlar(o, d, "", piyasa, aralik, sym), link)
    desen = DESEN_AD[o["desen"]]
    yukari = f["yon"] == "yukari"
    g = guven(o["desen"], piyasa, aralik)
    if o["tur"] == "kirilim":
        bas = "🚀" if yukari else "🔻"
        return _mesaj(f"{bas} {_buyuk(desen)} ONAYLANDI — {ad} ({aralik_ad})\n"
                      f"Boyun çizgisi {'yukarı' if yukari else 'aşağı'} kırıldı: kapanış {fiyat(c)}, "
                      f"boyun {fiyat(o['seviye'])}\n"
                      f"Hedef (ölçülen hareket): {fiyat(o['hedef'])} ({_yuzde(o['hedef'], c)})\n"
                      f"Geçersizlik: {fiyat(o['gecersiz'])} ({_yuzde(o['gecersiz'], c)}){guven_metni(g)}",
                      _ek_satirlar(o, d, o["desen"], piyasa, aralik, sym), link)
    hedef = o["seviye"] + f["yuk"] if yukari else o["seviye"] - f["yuk"]
    rr_v = rr_fiyat(o["seviye"], f["gecersiz"], hedef, yukari)
    return _mesaj(f"⚠️ BOYUN ÇİZGİSİNE YAKIN — {ad} ({aralik_ad})\n{desen} (henüz onaylanmadı)\n"
                  f"Kapanış {fiyat(c)}, boyun {fiyat(o['seviye'])} ({_yuzde(o['seviye'], c)})\n"
                  f"Boyun {'yukarı' if yukari else 'aşağı'} kırılırsa hedef: {fiyat(hedef)} ({_yuzde(hedef, c)}), "
                  f"R/Ö {('1 : ' + _sayi(rr_v)) if rr_v else '—'}{guven_metni(g, 'Onaylanırsa: ')}",
                  _ek_satirlar(o, d, o["desen"], piyasa, aralik, sym), link)


def calistir(gunlukler: bool, ozet: bool, onizleme: bool):
    t0 = time.time()
    liste = isler(gunlukler)
    with ThreadPoolExecutor(max_workers=6) as ex:
        veriler = list(ex.map(veri_al, liste))
    sonuc = []
    for (piyasa, sym, aralik), d in zip(liste, veriler):
        if d is None:
            continue
        d = log_veri(d)
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
        metin = olay_metni(o, d, ad, aralik_ad, link, r["piyasa"], r["aralik"], r["sym"])
        if k < 15:
            try:
                png = grafik(ad, aralik_ad, d, f, o, r["piyasa"], r["aralik"], r["sym"])
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
                    gy, ga = guven(ucgen_anahtar(a, "yukari"), piyasa, aralik), guven(ucgen_anahtar(a, "asagi"), piyasa, aralik)
                    etiket = f" [▲ {gy['ad']} · ▼ {ga['ad']}]" if gy and ga else ""
                    satirlar.append(f"• {gorunen(piyasa, r['sym'])} — {ucgen_adi(a)} üçgen, üst {fiyat(a['up'])} "
                                    f"({_yuzde(a['up'], c)}), alt {fiyat(a['lw'])} ({_yuzde(a['lw'], c)}), "
                                    f"olgunluk %{a['olgunluk'] * 100:.0f}{etiket}\n  {link}")
                else:
                    g = guven(a["desen"], piyasa, aralik)
                    etiket = f" [{g['ad']}]" if g else ""
                    satirlar.append(f"• {gorunen(piyasa, r['sym'])} — {DESEN_AD[a['desen']]}, boyun {fiyat(a['boyun_son'])} "
                                    f"({_yuzde(a['boyun_son'], c)}), hedef {fiyat(a['hedef'])} "
                                    f"({_yuzde(a['hedef'], c)}){etiket}\n  {link}")
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
                files[f"f{k}"] = (f"f{k}.png", grafik(ad, "4 saatlik" if r["aralik"] == "4h" else "Günlük", r["d"], a,
                                                      piyasa=r["piyasa"], aralik=r["aralik"], sym=r["sym"]))
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
            np.column_stack([np.exp(r["d"][k]) if r["d"].get("log") and k in "ohlc" else r["d"][k]
                             for k in ("t", "o", "h", "l", "c", "v")]) for r in sonuc})
    aktifler = sorted(((r, a) for r in sonuc for a in r["aktifler"]),
                      key=lambda ra: (ra[1]["desen"], ra[0]["piyasa"], ra[0]["aralik"], ra[0]["sym"]))
    adim = max(1, len(aktifler) // 24)
    for r, a in aktifler[::adim][:24]:
        ad = gorunen(r["piyasa"], r["sym"])
        open(f"onizleme/aktif_{a['desen']}_{r['piyasa']}_{r['aralik']}_{ad}.png", "wb").write(
            grafik(ad, r["aralik"], r["d"], a, piyasa=r["piyasa"], aralik=r["aralik"], sym=r["sym"]))
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
                    grafik(ad, r["aralik"], d, o["f"], o, r["piyasa"], r["aralik"], r["sym"]))
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
