"""
DARALAN UCGEN TARAYICI
======================
Kripto (Binance, 4 saatlik + gunluk), BIST ve ABD hisseleri/ETF'ler (gunluk) icinde daralan ucgen
formasyonlarini bulur; fiyat kirilim seviyesine yaklasinca ve kirilim olunca Telegram'a grafikli mesaj atar.

Ucgen tanimi (TradingView gostergesi "Daralan Ucgen Avcisi" ile birebir ayni):
  * Pivot tepe/dip: solunda ve saginda PIVOT kadar mumdan yuksek/alcak mum (PIVOT mum sonra kesinlesir).
  * Ust cizgi: son pivot tepelerden (en fazla 4) gecen, tepelerin tolerans disinda ustune cikmadigi ve
    kapanislarin uzerine cikmadigi en uzun dizi. Alt cizgi diplerle ayni sekilde.
  * Iki taraf birbirinin icine gecmeli (tepe-dip-tepe-dip sirasi), cizgiler yaklasmali (genislik <= %85),
    baslangic yuksekligi >= 3 ATR, sure 20-150 mum, tepe noktasi (apex) gecilmemis olmali.
  * Tip: ust alcalan + alt yukselen = SIMETRIK, ust yatay + alt yukselen = YUKSELEN,
    ust alcalan + alt yatay = ALCALAN. (Kama ve yatay kanal sayilmaz.)
Olaylar:
  * KIRILIMA YAKIN: kapanis, ust (ya da alt) cizgiye 0.75 ATR'den yakin.
  * KIRILIM: kapanis cizginin disinda. Hedef = kirilim seviyesi +/- baslangic yuksekligi (olculen hareket).

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

AYAR = dict(PIVOT=5, MAX_BAR=150, MIN_BAR=20, MAX_PIVOT=4, TOL_ATR=0.3, YATAY=0.15,
            MIN_YUKSEKLIK_ATR=3.0, DARALMA=0.85, YAKIN_ATR=0.75)
DURUM_DOSYASI = "ucgen_state.json"
LISTE_DOSYASI = "ucgen_izleme_listesi.txt"
MIN_KRIPTO_HACIM = 3e6        # 24 saatlik islem hacmi (USDT)

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
    return secilen


def binance(sym: str, aralik: str, adet: int = 400) -> dict | None:
    v = _get("https://data-api.binance.vision/api/v3/klines", dict(symbol=sym, interval=aralik, limit=adet))
    if not v:
        return None
    simdi = time.time() * 1000
    v = [k for k in v if k[6] < simdi]   # sadece kapanmis mumlar
    if len(v) < 120:
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
            if len(sat) < 120:
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


def cizgi(piv: list, c: np.ndarray, b: int, tol: float, ust: bool):
    """Pivot listesinden (sondan) en uzun gecerli cizgiyi bulur."""
    for k in range(min(len(piv), AYAR["MAX_PIVOT"]), 1, -1):
        seq = piv[-k:]
        (i0, p0), (i1, p1) = seq[0], seq[-1]
        s = (p1 - p0) / (i1 - i0)
        ok, dok = True, 0
        for i, p in seq:
            d = p - (p0 + s * (i - i0))
            if (ust and d > tol) or (not ust and d < -tol):
                ok = False
                break
            if abs(d) <= tol:
                dok += 1
        if not ok:
            continue
        xs = np.arange(i0, b)
        hat = p0 + s * (xs - i0)
        if ust and np.any(c[i0:b] > hat + tol):
            continue
        if not ust and np.any(c[i0:b] < hat - tol):
            continue
        return dict(i0=i0, p0=p0, s=s, dok=dok, k=k)
    return None


def formasyon_kur(d, b, ph_list, pl_list, A):
    n, M = AYAR["PIVOT"], AYAR["MAX_BAR"]
    o, c = d["o"], d["c"]
    # pivot fiyati: fitil gövdeden 1 ATR'den uzunsa gövde + 1 ATR'ye kirpilir (tek iğne cizgiyi bozmasin)
    hs = [(i, min(d["h"][i], max(o[i], c[i]) + A[i])) for i in ph_list if b - M <= i <= b - n]
    ls = [(i, max(d["l"][i], min(o[i], c[i]) - A[i])) for i in pl_list if b - M <= i <= b - n]
    if len(hs) < 2 or len(ls) < 2 or not (A[b] > 0):
        return None
    tol = AYAR["TOL_ATR"] * A[b]
    u = cizgi(hs, d["c"], b, tol, True)
    lo = cizgi(ls, d["c"], b, tol, False)
    if not u or not lo:
        return None
    ui1, li1 = hs[-1][0], ls[-1][0]
    if not (u["i0"] < li1 and lo["i0"] < ui1):        # taraflar ic ice gecmeli
        return None
    x0 = min(u["i0"], lo["i0"])
    if max(u["i0"], lo["i0"]) - x0 > 0.5 * (b - x0):   # iki cizgi de formasyonun ilk yarisinda baslamali
        return None
    U = lambda x: u["p0"] + u["s"] * (x - u["i0"])     # noqa: E731
    L = lambda x: lo["p0"] + lo["s"] * (x - lo["i0"])  # noqa: E731
    w0, wb = U(x0) - L(x0), U(b) - L(b)
    sure = b - x0
    if w0 <= 0 or wb <= 0 or wb / w0 > AYAR["DARALMA"]:
        return None
    if w0 < AYAR["MIN_YUKSEKLIK_ATR"] * A[b] or not (AYAR["MIN_BAR"] <= sure <= AYAR["MAX_BAR"]):
        return None
    du, dl = (U(b) - U(x0)) / w0, (L(b) - L(x0)) / w0
    y = AYAR["YATAY"]
    if du < -y and dl > y:
        tip = "Simetrik"
    elif abs(du) <= y and dl > y:
        tip = "Yükselen"
    elif du < -y and abs(dl) <= y:
        tip = "Alçalan"
    else:
        return None
    apex = x0 + w0 / (w0 - wb) * sure
    return dict(u=u, l=lo, x0=x0, w0=w0, apex=apex, tip=tip, dok=u["dok"] + lo["dok"],
                key=(int(d["t"][u["i0"]]), int(d["t"][lo["i0"]])))


def deger(f, x, taraf):
    s = f[taraf]
    return s["p0"] + s["s"] * (x - s["i0"])


def tara(d: dict):
    """Tum gecmisi mum mum isler: aktif formasyon (son mumda) + olay listesi."""
    n = AYAR["PIVOT"]
    N = len(d["c"])
    A = atr(d["h"], d["l"], d["c"])
    ph, pl = pivotlar(d["h"], d["l"], n)
    ph_list, pl_list = [], []
    aktif, olaylar, bozuk = None, [], set()
    for b in range(n + 15, N):
        p = b - n
        yeni_pivot = False
        if ph[p]:
            ph_list.append(p); yeni_pivot = True
        if pl[p]:
            pl_list.append(p); yeni_pivot = True
        if yeni_pivot:
            f = formasyon_kur(d, b, ph_list, pl_list, A)
            if f and f["key"] not in bozuk:
                if aktif and aktif["key"] == f["key"]:
                    f["bayrak"] = aktif["bayrak"]
                else:
                    f["bayrak"] = set()
                aktif = f
        if not aktif:
            continue
        if b >= aktif["apex"]:
            bozuk.add(aktif["key"]); aktif = None
            continue
        up, lw, c = deger(aktif, b, "u"), deger(aktif, b, "l"), d["c"][b]
        if c > up or c < lw:
            yon = "yukari" if c > up else "asagi"
            seviye = up if c > up else lw
            olaylar.append(dict(tur="kirilim", yon=yon, b=b, f=aktif, seviye=seviye,
                                hedef=seviye + aktif["w0"] if yon == "yukari" else seviye - aktif["w0"],
                                gecersiz=lw if yon == "yukari" else up))
            bozuk.add(aktif["key"]); aktif = None
            continue
        for taraf, mesafe in (("ust", up - c), ("alt", c - lw)):
            if mesafe <= AYAR["YAKIN_ATR"] * A[b] and taraf not in aktif["bayrak"]:
                aktif["bayrak"].add(taraf)
                olaylar.append(dict(tur="yakin", yon=taraf, b=b, f=aktif, seviye=up if taraf == "ust" else lw))
    if aktif:
        b = N - 1
        aktif = dict(aktif, up=deger(aktif, b, "u"), lw=deger(aktif, b, "l"),
                     olgunluk=(b - aktif["x0"]) / (aktif["apex"] - aktif["x0"]), atr=A[b])
    return aktif, olaylar


# ───────────────────────── Grafik ─────────────────────────
def grafik(sym_ad: str, aralik_ad: str, d: dict, f: dict, olay: dict | None = None) -> bytes:
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    N = len(d["c"])
    son = olay["b"] if olay else N - 1
    bas = max(0, f["x0"] - 25)
    bit = min(N - 1, son + (8 if olay and olay["tur"] == "kirilim" else 0))
    xs = np.arange(bas, bit + 1)
    fig, ax = plt.subplots(figsize=(9, 4.6), dpi=110)
    fig.patch.set_facecolor("#131722"); ax.set_facecolor("#131722")
    for i in xs:
        o, h, l, c = d["o"][i], d["h"][i], d["l"][i], d["c"][i]
        renk = "#26a69a" if c >= o else "#ef5350"
        ax.vlines(i, l, h, color=renk, linewidth=0.8)
        ax.add_patch(plt.Rectangle((i - 0.32, min(o, c)), 0.64, max(abs(c - o), (h - l) * 0.01), color=renk))
    uc = min(f["apex"], son + 0.35 * (f["apex"] - f["x0"]))
    for taraf, renk in (("u", "#ff9800"), ("l", "#2196f3")):
        x0 = f[taraf]["i0"]
        ax.plot([x0, son], [deger(f, x0, taraf), deger(f, son, taraf)], color=renk, linewidth=1.8)
        ax.plot([son, uc], [deger(f, son, taraf), deger(f, uc, taraf)], color=renk, linewidth=1.2, linestyle="--")
    ax.set_xlim(bas - 1, max(bit, uc) + 2)
    if olay and olay["tur"] == "kirilim":
        ax.axhline(olay["hedef"], color="#4caf50" if olay["yon"] == "yukari" else "#f44336", linestyle=":", linewidth=1)
        ax.annotate("KIRILIM", (olay["b"], d["c"][olay["b"]]), color="white", fontsize=9,
                    xytext=(5, 12 if olay["yon"] == "yukari" else -16), textcoords="offset points")
    t = datetime.fromtimestamp(d["t"][son], tz=timezone.utc).strftime("%d.%m.%Y %H:%M")
    ax.set_title(f"{sym_ad}  {aralik_ad}  —  {f['tip']} daralan üçgen  ({t} UTC)", color="white", fontsize=10)
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


def calistir(gunlukler: bool, ozet: bool, onizleme: bool):
    t0 = time.time()
    liste = isler(gunlukler)
    with ThreadPoolExecutor(max_workers=6) as ex:
        veriler = list(ex.map(veri_al, liste))
    sonuc = []
    for (piyasa, sym, aralik), d in zip(liste, veriler):
        if d is None:
            continue
        aktif, olaylar = tara(d)
        sonuc.append(dict(piyasa=piyasa, sym=sym, aralik=aralik, d=d, aktif=aktif, olaylar=olaylar))
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
            if o["b"] < N - 2:          # sadece son 2 kapanmis mum (kacirilan calistirmaya karsi)
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
        c = d["c"][o["b"]]
        if o["tur"] == "kirilim":
            bas = "🚀 YUKARI KIRILIM" if o["yon"] == "yukari" else "🔻 AŞAĞI KIRILIM"
            metin = (f"{bas} — {ad} ({aralik_ad})\n{f['tip']} üçgen, {f['dok']} dokunuş\n"
                     f"Kapanış: {fiyat(c)}  |  Kırılan seviye: {fiyat(o['seviye'])}\n"
                     f"Hedef (ölçülen hareket): {fiyat(o['hedef'])} ({(o['hedef'] / c - 1) * 100:+.1f}%)\n"
                     f"Geçersizlik: {fiyat(o['gecersiz'])} ({(o['gecersiz'] / c - 1) * 100:+.1f}%)\n{link}")
        else:
            taraf = "ÜST (direnç)" if o["yon"] == "ust" else "ALT (destek)"
            metin = (f"🔺 KIRILIMA YAKIN — {ad} ({aralik_ad})\n{f['tip']} üçgen, {f['dok']} dokunuş\n"
                     f"Fiyat {taraf} çizgisine yaklaştı: kapanış {fiyat(c)}, çizgi {fiyat(o['seviye'])} "
                     f"({(o['seviye'] / c - 1) * 100:+.1f}%)\n{link}")
        if k < 15:
            try:
                png = grafik(ad, aralik_ad, d, f, o)
                tg("sendPhoto", dict(caption=metin[:1020]), files={"photo": ("ucgen.png", png)})
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
    aktifler = [r for r in sonuc if r["aktif"]]
    tv_liste, satirlar = [], []
    for piyasa in ("KRIPTO", "BIST", "ABD"):
        for aralik in ("4h", "1d"):
            grup = [r for r in aktifler if r["piyasa"] == piyasa and r["aralik"] == aralik]
            if not grup:
                continue
            grup.sort(key=lambda r: min(r["aktif"]["up"] - r["d"]["c"][-1], r["d"]["c"][-1] - r["aktif"]["lw"])
                      / r["aktif"]["atr"])
            ad_ = {"KRIPTO": "Kripto", "BIST": "BIST", "ABD": "ABD"}[piyasa] + (" 4s" if aralik == "4h" else " günlük")
            satirlar.append(f"\n▪️ {ad_} ({len(grup)})")
            for r in grup:
                a, c = r["aktif"], r["d"]["c"][-1]
                t, link = tv(r["piyasa"], r["sym"], r["d"].get("borsa", ""), aralik)
                tv_liste.append(t)
                du, dl = (a["up"] / c - 1) * 100, (a["lw"] / c - 1) * 100
                satirlar.append(f"• {gorunen(piyasa, r['sym'])} — {a['tip']}, üst {fiyat(a['up'])} ({du:+.1f}%), "
                                f"alt {fiyat(a['lw'])} ({dl:+.1f}%), olgunluk %{a['olgunluk'] * 100:.0f}\n  {link}")
    bas = (f"📐 DARALAN ÜÇGEN ÖZETİ — {datetime.now(timezone.utc).strftime('%d.%m.%Y')}\n"
           f"Şu an üçgen içinde olan {len(aktifler)} grafik (kırılım çizgisine en yakın olan önce):")
    metin_gonder(bas + "\n" + "\n".join(satirlar) if aktifler else bas + "\nŞu an üçgen içinde grafik yok.")
    with open(LISTE_DOSYASI, "w", encoding="utf-8") as fh:
        fh.write(",".join(dict.fromkeys(tv_liste)))
    # en yakin 10 grafik albumu
    yakin = sorted(aktifler, key=lambda r: min(r["aktif"]["up"] - r["d"]["c"][-1], r["d"]["c"][-1] - r["aktif"]["lw"])
                   / r["aktif"]["atr"])[:10]
    if len(yakin) >= 2:
        media, files = [], {}
        for k, r in enumerate(yakin):
            ad = gorunen(r["piyasa"], r["sym"])
            try:
                files[f"f{k}"] = (f"f{k}.png", grafik(ad, "4 saatlik" if r["aralik"] == "4h" else "Günlük", r["d"], r["aktif"]))
                media.append(dict(type="photo", media=f"attach://f{k}", caption=f"{ad} — {r['aktif']['tip']}"))
            except Exception as exc:  # noqa: BLE001
                print("grafik hatasi:", exc)
        if len(media) >= 2:
            tg("sendMediaGroup", dict(media=json.dumps(media)), files=files)


def onizle(sonuc: list):
    """Gozle kontrol: grafikleri onizleme/ klasorune cizer ve tarihsel kirilim istatistigini yazar."""
    os.makedirs("onizleme", exist_ok=True)
    aktifler = [r for r in sonuc if r["aktif"]]
    tipler = {}
    for r in aktifler:
        tipler[r["aktif"]["tip"]] = tipler.get(r["aktif"]["tip"], 0) + 1
    secim = sorted(aktifler, key=lambda r: (r["piyasa"], r["aralik"], r["sym"]))
    adim = max(1, len(secim) // 24)
    for r in secim[::adim][:24]:
        ad = gorunen(r["piyasa"], r["sym"])
        open(f"onizleme/aktif_{r['piyasa']}_{r['aralik']}_{ad}.png", "wb").write(
            grafik(ad, r["aralik"], r["d"], r["aktif"]))
    # tarihsel kirilimlar: hedefe ulasma / gecersizlik
    istat = {"yukari": [0, 0, 0], "asagi": [0, 0, 0]}   # adet, hedef, gecersiz
    ornek = 0
    for r in sonuc:
        d = r["d"]
        for o in r["olaylar"]:
            if o["tur"] != "kirilim" or o["b"] > len(d["c"]) - 30:
                continue
            s = istat[o["yon"]]
            s[0] += 1
            ileri = range(o["b"] + 1, min(len(d["c"]), o["b"] + 60))
            for i in ileri:
                if o["yon"] == "yukari":
                    if d["l"][i] <= o["gecersiz"]:
                        s[2] += 1; break
                    if d["h"][i] >= o["hedef"]:
                        s[1] += 1; break
                else:
                    if d["h"][i] >= o["gecersiz"]:
                        s[2] += 1; break
                    if d["l"][i] <= o["hedef"]:
                        s[1] += 1; break
            if ornek < 12 and o["b"] < len(d["c"]) - 10:
                ornek += 1
                ad = gorunen(r["piyasa"], r["sym"])
                open(f"onizleme/kirilim_{r['piyasa']}_{r['aralik']}_{ad}_{ornek}.png", "wb").write(
                    grafik(ad, r["aralik"], d, o["f"], o))
    sayim = {}
    for r in sonuc:
        k = r["piyasa"] + "-" + r["aralik"]
        sayim[k] = sayim.get(k, 0) + 1
    akt = {}
    for r in aktifler:
        k = r["piyasa"] + "-" + r["aralik"]
        akt[k] = akt.get(k, 0) + 1
    satir = (f"veri {sayim} | aktif {akt} | "
             f"aktif ucgen: {len(aktifler)} / {len(sonuc)} grafik, tipler {tipler} | "
             f"tarihsel kirilim: yukari {istat['yukari'][0]} (hedef {istat['yukari'][1]}, gecersiz {istat['yukari'][2]}), "
             f"asagi {istat['asagi'][0]} (hedef {istat['asagi'][1]}, gecersiz {istat['asagi'][2]})")
    print(satir)
    if os.environ.get("GITHUB_ACTIONS") == "true":
        print("::notice::" + satir)


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
