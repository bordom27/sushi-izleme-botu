"""
BUYUK AV - cok varlikli kirilim + trend takip sistemi (gunluk)
================================================================
Arastirma: 239 varlik (ABD hisse/ETF, BIST dolar bazli, kripto), 2005-2026, ~5.000 islem.
Bu dosya tarayicidaki arastirma motorunun birebir Python karsiligidir.

Kurallar (F1):
  GIRIS : kapanis, onceki 100 gunun en yuksek kapanisini ilk kez gecer
          + hacim >= 1.5 x onceki 50 gun ortalamasi
          + piyasa rejimi: ilgili endeks 200 gunluk ortalamanin ustunde
          + likidite: gunluk islem hacmi >= 1 milyon $ (ETF haric)
          -> ertesi gun acilista giris
  STOP  : giris - 2 x ATR(20)
  KAR   : +%50'de pozisyonun 1/3'u satilir, stop girise cekilir
  IZ    : stop, gorulen en yuksek fiyatin %25 altina tasinir (sadece yukari)
  ZAMAN : 40 islem gununde kar %5'in altindaysa ertesi acilista cik
  PORTFOY: islem basi %1 risk, en fazla 10 pozisyon, en fazla 2 kripto, pozisyon <= %20

Kullanim:
  python buyuk_av.py                 # gunluk tarama + Telegram raporu
  python buyuk_av.py --backtest      # 2005+ portfoy testi (arastirmayla karsilastirma)
  python buyuk_av.py --telegram-yok  # raporu sadece ekrana yazdir
"""
from __future__ import annotations

import argparse
import json
import math
import os
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone

import numpy as np
import requests

# ───────────────────────── Ayarlar ─────────────────────────
P = dict(N=100, VOL=1.5, STOP_K=2.0, TRAIL=0.25, PART_AT=0.5, PART_FR=1 / 3,
         TS_BARS=40, TS_MIN=0.05, LIKIDITE=1e6)
PORTFOY = dict(K=10, RISK=0.01, CAP=0.20, KRIPTO_MAX=2)
KAGIT_BASLANGIC = "2026-11-02"   # kagit portfoy bu tarihten itibaren bos baslar
COST = {"US": 0.001, "ETF": 0.001, "BIST": 0.002, "CR": 0.0015}
BENCH = {"US": "^GSPC", "ETF": "^GSPC", "BIST": "XU100.IS$", "CR": "BTC-USD"}
SPLIT = math.floor(datetime(2020, 1, 1, tzinfo=timezone.utc).timestamp() / 86400)

US = ("META GOOGL MSFT AMZN NVDA AAPL TSLA AMD NFLX ADBE CRM ORCL INTC CSCO IBM QCOM TXN AVGO MU AMAT LRCX "
      "KLAC JPM BAC WFC C GS MS V MA PYPL AXP JNJ PFE MRK ABBV LLY UNH AMGN GILD BMY CVS WMT COST LOW HD TGT "
      "NKE SBUX MCD KO PEP PG CL XOM CVX SLB COP OXY HAL CAT DE BA GE MMM HON FDX UPS LMT F GM RTX T VZ DIS "
      "CMCSA DUK FCX NEE NEM AAL DAL UAL CCL KSS M PM MO BKNG ISRG REGN VRTX DXCM ALGN ENPH FSLR LULU CMG ODFL "
      "DECK CPRT MNST TTWO ETSY EBAY ROKU ZM SHOP UBER CRWD PLTR NOW PANW SNOW FTNT ANET ULTA AXON TSCO BBY "
      "DLTR DG").split()
ETF = ("SPY QQQ IWM EFA EEM DIA EWZ EWJ FXI GLD SLV USO UNG TLT IEF HYG XLK XLE XLV XLF XLI XLU XLB XLP XLY "
       "SMH XBI URA GDX KRE XHB ITB").split()
CR = [s + "-USD" for s in ("ETH BTC BNB XRP ADA SOL LTC DOGE LINK DOT TRX XLM BCH AVAX ETC ATOM XMR NEAR FIL "
                            "AAVE VET ALGO ICP HBAR EOS XTZ ZEC DASH NEO").split()]
BIST = [s + ".IS" for s in ("THYAO ASELS GARAN AKBNK YKBNK ISCTR KCHOL SISE SAHOL EREGL TUPRS KRDMD BIMAS PETKM "
                             "MGROS TCELL TTKOM FROTO TOASO PGSUS VESTL ARCLK TAVHL EKGYO ENKAI HEKTS SASA ALARK "
                             "DOHOL GUBRF ULKER AEFES CCOLA OTKAR TTRAK SOKM VAKBN HALKB AKSEN TKFEN ZOREN ECILC "
                             "NTHOL ALBRK SKBNK CIMSA BRSAN AKSA DEVA LOGO NETAS IHLAS KARSN GSDHO OYAKC "
                             "BAGFS").split()]
GRUP = {**{t: "US" for t in US}, **{t: "ETF" for t in ETF}, **{t: "CR" for t in CR}, **{t: "BIST" for t in BIST}}
EK = ["^GSPC", "XU100.IS", "USDTRY=X"]


# ───────────────────────── Veri ─────────────────────────
def yahoo(t: str, oturum: requests.Session) -> dict | None:
    for deneme in range(4):
        host = "query1" if deneme % 2 == 0 else "query2"
        try:
            r = oturum.get(f"https://{host}.finance.yahoo.com/v8/finance/chart/{requests.utils.quote(t)}",
                           params=dict(period1=946684800, period2=9999999999, interval="1d", events="split,div"),
                           timeout=30)
            if r.status_code != 200:
                time.sleep(1.5 * (deneme + 1))
                continue
            x = r.json()["chart"]["result"][0]
            q = x["indicators"]["quote"][0]
            adj = (x["indicators"].get("adjclose") or [{}])[0].get("adjclose")
            T, O, H, L, C, V = [], [], [], [], [], []
            for i, ts in enumerate(x["timestamp"]):
                c, o, h, l = q["close"][i], q["open"][i], q["high"][i], q["low"][i]
                if c is None or o is None or h is None or l is None:
                    continue
                f = adj[i] / c if adj and adj[i] is not None else 1.0
                T.append(ts // 86400); O.append(o * f); H.append(h * f); L.append(l * f); C.append(c * f)
                V.append(q["volume"][i] or 0)
            return dict(T=np.array(T, dtype=np.int64), O=np.array(O), H=np.array(H), L=np.array(L),
                        C=np.array(C), V=np.array(V, dtype=float))
        except Exception as exc:  # noqa: BLE001
            print(f"  {t}: {exc}")
            time.sleep(1.5 * (deneme + 1))
    return None


def veri_cek(son_gun_haric: bool) -> dict:
    oturum = requests.Session()
    oturum.headers["User-Agent"] = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                                    "(KHTML, like Gecko) Chrome/126.0 Safari/537.36")
    hepsi = list(GRUP) + EK
    D = {}
    with ThreadPoolExecutor(max_workers=6) as ex:
        for t, d in zip(hepsi, ex.map(lambda s: yahoo(s, oturum), hepsi)):
            if d is not None and len(d["C"]) > 200:
                D[t] = d
    if son_gun_haric:  # canli: henuz kapanmamis (bugunun UTC) mumunu at
        bugun = int(time.time() // 86400)
        for t, d in D.items():
            m = d["T"] < bugun
            D[t] = {k: v[m] for k, v in d.items()}
    # BIST -> dolar bazi (USDTRY kapanisi, eksik gunde son kur)
    fx = D.get("USDTRY=X")
    if fx is not None:
        fm = dict(zip(fx["T"].tolist(), fx["C"].tolist()))
        for t in [s for s in D if s.endswith(".IS")]:
            d = D[t]
            n = {k: [] for k in ("T", "O", "H", "L", "C", "V", "FX")}
            son = None
            for i in range(len(d["T"])):
                r = fm.get(int(d["T"][i]), son)
                if r is None:
                    continue
                son = r
                n["T"].append(d["T"][i]); n["O"].append(d["O"][i] / r); n["H"].append(d["H"][i] / r)
                n["L"].append(d["L"][i] / r); n["C"].append(d["C"][i] / r); n["V"].append(d["V"][i] * d["C"][i] / r)
                n["FX"].append(r)
            D[t + "$"] = {k: np.array(v, dtype=np.int64 if k == "T" else float) for k, v in n.items()}
    return D


# ───────────────────────── Gostergeler (arastirma motoruyla birebir) ─────────────────────────
def sma(a: np.ndarray, n: int) -> np.ndarray:
    out = np.full(len(a), np.nan)
    if len(a) >= n:
        cs = np.cumsum(np.insert(a, 0, 0.0))
        out[n - 1:] = (cs[n:] - cs[:-n]) / n
    return out


def atr_wilder(H, L, C, n=20) -> np.ndarray:
    out = np.full(len(C), np.nan)
    v = math.nan
    for i in range(1, len(C)):
        tr = max(H[i] - L[i], abs(H[i] - C[i - 1]), abs(L[i] - C[i - 1]))
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


def hi_prev(a: np.ndarray, n: int) -> np.ndarray:
    """i'deki deger: a[i-n .. i-1] en buyugu (bugun haric)."""
    out = np.full(len(a), np.nan)
    from collections import deque
    dq: deque = deque()
    for i in range(len(a)):
        if i >= n:
            out[i] = a[dq[0]]
        while dq and a[dq[-1]] <= a[i]:
            dq.pop()
        dq.append(i)
        if dq[0] <= i - n:
            dq.popleft()
    return out


def bench_hazirla(D: dict) -> dict:
    B = {}
    for t in set(BENCH.values()):
        if t in D:
            d = D[t]
            B[t] = dict(C=d["C"], ma=sma(d["C"], 200), idx={int(x): i for i, x in enumerate(d["T"])})
    return B


def bench_at(b: dict, gun: int) -> int:
    for k in range(6):
        j = b["idx"].get(gun - k)
        if j is not None:
            return j
    return -1


# ───────────────────────── Tek varlik simulasyonu ─────────────────────────
def sim(t: str, g: str, D: dict, B: dict) -> tuple[list, dict | None, dict | None]:
    """Islemler + son bardaki durum (acik pozisyon / bekleyen sinyal)."""
    d = D[t]
    T, O, H, L, C, V = d["T"], d["O"], d["H"], d["L"], d["C"], d["V"]
    n = len(C)
    A = atr_wilder(H, L, C, 20)
    volMA = sma(V, 50)
    hiN = hi_prev(C, P["N"])
    bad = np.zeros(n, dtype=bool)
    bad[1:] = (C[1:] / C[:-1] > 2.5) | (C[1:] / C[:-1] < 0.4)
    b = B.get(BENCH[g])
    cost = COST[g]
    trades, pos, last_bad = [], None, -10 ** 9
    bekleyen = None

    def kapat(p, i, px, neden, acik=False):
        xp = px * (1 - cost)
        value = p["realized"] + p["frac"] * xp
        pnl = value - p["ec"]
        trades.append(dict(t=t, g=g, d=int(T[p["i0"]]), dx=int(T[i]), i0=p["i0"], ix=i, test=int(T[p["i0"]]) >= SPLIT,
                           R=pnl / (p["entry"] - p["st0"]), ret=pnl / p["ec"], bars=i - p["i0"], ec=p["ec"], fv=value,
                           pd=p["pd"], pv=p["pv"], rp=(p["entry"] - p["st0"]) / p["entry"], mom=p["mom"],
                           entry=p["entry"], st0=p["st0"], stop=p["stop"], hh=p["hh"], partDone=p["partDone"],
                           partGun=p["partGun"], exitNext=p["exitNext"], stops=p["stops"], neden=neden,
                           cikis=px, open=acik))

    for i in range(260, n):
        if bad[i]:
            last_bad = i
            pos = None
            continue
        if pos is not None:
            px, neden = None, None
            if pos["exitNext"]:
                px, neden = O[i], "zaman"
            elif O[i] <= pos["stop"]:
                px, neden = O[i], "stop"
            elif L[i] <= pos["stop"]:
                px, neden = pos["stop"], "stop"
            if px is None and not pos["partDone"]:
                tgt = pos["entry"] * (1 + P["PART_AT"])
                if H[i] >= tgt:
                    ppx = max(O[i], tgt)
                    pos["realized"] += pos["frac"] * P["PART_FR"] * (ppx * (1 - cost))
                    pos["frac"] *= (1 - P["PART_FR"])
                    pos["partDone"] = True
                    pos["partGun"] = int(T[i])
                    pos["stop"] = max(pos["stop"], pos["entry"])
            if px is not None:
                kapat(pos, i, px, neden)
                pos = None
                continue
            pos["hh"] = max(pos["hh"], H[i])
            pos["bars"] += 1
            pos["pd"].append(int(T[i]))
            pos["pv"].append(pos["realized"] + pos["frac"] * C[i] * (1 - cost))
            s = pos["hh"] * (1 - P["TRAIL"])
            if s > pos["stop"]:
                pos["stop"] = s
            if pos["bars"] >= P["TS_BARS"] and C[i] < pos["entry"] * (1 + P["TS_MIN"]):
                pos["exitNext"] = True
            pos["stops"].append(pos["stop"])
            if i == n - 1:
                kapat(pos, i, C[i], "acik", acik=True)
                pos = None
            continue
        if i - last_bad < 20:
            continue
        # sinyal (kapanista)
        if not (C[i] > hiN[i] and C[i - 1] <= hiN[i - 1]):
            continue
        if not (V[i] > P["VOL"] * volMA[i - 1]):
            continue
        if b is None:
            continue
        j = bench_at(b, int(T[i]))
        if j < 210 or not (b["C"][j] > b["ma"][j]):
            continue
        ciro = volMA[i] if g in ("BIST", "CR") else C[i] * volMA[i]
        if g != "ETF" and not (ciro >= P["LIKIDITE"]):
            continue
        if i + 1 >= n:   # son bar: yarin acilista giris bekleniyor
            bekleyen = dict(t=t, g=g, gun=int(T[i]), kapanis=C[i], stop_tahmin=C[i] - P["STOP_K"] * A[i],
                            atr=A[i], mom=C[i] / C[max(0, i - 126)], hacim_kat=V[i] / volMA[i - 1])
            break
        e = O[i + 1]
        st = e - P["STOP_K"] * A[i]
        if not (st < e):
            continue
        pos = dict(i0=i + 1, entry=e, ec=e * (1 + cost), stop=st, st0=st, hh=e, frac=1.0, realized=0.0, bars=0,
                   partDone=False, partGun=None, exitNext=False, pd=[], pv=[], stops=[],
                   mom=C[i] / C[max(0, i - 126)])
    return trades, bekleyen


def hepsini_sim(D: dict) -> tuple[list, list]:
    B = bench_hazirla(D)
    tum, bekleyenler = [], []
    for t, g in GRUP.items():
        key = t + "$" if g == "BIST" else t
        if key not in D:
            continue
        tr, bk = sim(key, g, D, B)
        tum.extend(tr)
        if bk:
            bekleyenler.append(bk)
    return tum, bekleyenler


# ───────────────────────── Portfoy ─────────────────────────
def portfoy(trades: list, bas: str, bit: str | None = None) -> dict:
    s = math.floor(datetime.fromisoformat(bas).replace(tzinfo=timezone.utc).timestamp() / 86400)
    e = math.floor(datetime.fromisoformat(bit).replace(tzinfo=timezone.utc).timestamp() / 86400) if bit else 10 ** 9
    tr = sorted([x for x in trades if s <= x["d"] < e], key=lambda x: (x["d"], -x["mom"]))
    gunler = set()
    for x in tr:
        gunler.add(x["d"]); gunler.add(x["dx"]); gunler.update(z for z in x["pd"] if z < e)
    grid = sorted(z for z in gunler if s <= z < e)
    starts: dict = {}
    for x in tr:
        starts.setdefault(x["d"], []).append(x)
    cash, acik, eq, peak, mdd = 1.0, [], 1.0, 1.0, 0.0
    alinan, atlanan, egri, kapananlar = [], 0, [], []
    for d in grid:
        kalan = []
        for p in acik:
            if p["x"]["dx"] <= d and not p["x"]["open"]:
                cash += p["q"] * p["x"]["fv"]
                kapananlar.append(p)
            else:
                kalan.append(p)
        acik = kalan
        mv = 0.0
        for p in acik:
            pd = p["x"]["pd"]
            while p["k"] < len(pd) and pd[p["k"]] <= d:
                p["k"] += 1
            mv += p["q"] * (p["x"]["pv"][p["k"] - 1] if p["k"] > 0 else p["x"]["ec"])
        eq = cash + mv
        for x in starts.get(d, []):
            if len(acik) >= PORTFOY["K"]:
                atlanan += 1; continue
            if x["g"] == "CR" and sum(1 for p in acik if p["x"]["g"] == "CR") >= PORTFOY["KRIPTO_MAX"]:
                atlanan += 1; continue
            if any(p["x"]["t"] == x["t"] for p in acik):
                atlanan += 1; continue
            size = min(PORTFOY["RISK"] * eq / (x["rp"] + 0.003), PORTFOY["CAP"] * eq, cash)
            if size < 0.002 * eq:
                atlanan += 1; continue
            cash -= size
            p = dict(x=x, q=size / x["ec"], k=0, agirlik=size / eq)
            acik.append(p); alinan.append(p)
        peak = max(peak, eq)
        mdd = max(mdd, 1 - eq / peak)
        egri.append((d, eq))
    yil = (grid[-1] - grid[0]) / 365.25 if len(grid) > 1 else 0
    cagr = eq ** (1 / yil) - 1 if yil > 0 else 0.0
    return dict(cagr=cagr, mdd=mdd, eq=eq, alinan=alinan, atlanan=atlanan, acik=acik, kapananlar=kapananlar,
                egri=egri, cash=cash)


# ───────────────────────── Rapor ─────────────────────────
def tarih(gun: int) -> str:
    return datetime.fromtimestamp(gun * 86400, tz=timezone.utc).strftime("%d.%m.%Y")


def ad(t: str) -> str:
    return t.replace("$", "").replace(".IS", "").replace("-USD", "")


def tv_link(t: str, g: str) -> str:
    s = ad(t)
    sym = f"BIST:{s}" if g == "BIST" else f"BINANCE:{s}USDT" if g == "CR" else s
    return f"https://www.tradingview.com/chart/?symbol={sym}&interval=D"


def yerel(D: dict, t: str, fiyat: float, gun_index: int | None = None) -> str:
    """BIST icin TL'ye cevir (son kur), digerleri dolar."""
    if t.endswith("$"):
        fx = D[t]["FX"][gun_index if gun_index is not None else -1]
        v = fiyat * fx
        return f"{v:,.2f} TL".replace(",", "X").replace(".", ",").replace("X", ".")
    if fiyat >= 100:
        return f"{fiyat:,.2f} $"
    if fiyat >= 1:
        return f"{fiyat:.2f} $"
    return f"{fiyat:.4g} $"


def rejim_satiri(D: dict, B: dict) -> str:
    parca = []
    for etiket, t in (("ABD", "^GSPC"), ("BIST", "XU100.IS$"), ("Kripto", "BTC-USD")):
        b = B.get(t)
        if not b:
            continue
        ok = b["C"][-1] > b["ma"][-1]
        parca.append(f"{etiket} {'🟢' if ok else '🔴'}")
    return "Piyasa rejimi: " + "  ".join(parca)


def rapor(D: dict, trades: list, bekleyenler: list) -> str:
    B = bench_hazirla(D)
    son_gun = max(int(d["T"][-1]) for t, d in D.items() if t in ("^GSPC", "BTC-USD", "XU100.IS$"))
    pf = portfoy(trades, KAGIT_BASLANGIC)
    acik = [p for p in pf["acik"] if p["x"]["open"]]
    satirlar = [f"🎯 BÜYÜK AV — {tarih(son_gun)} kapanışı", rejim_satiri(D, B)]

    # 1) Bugun acilista alinacaklar
    yer = PORTFOY["K"] - len(acik)
    kripto_yer = PORTFOY["KRIPTO_MAX"] - sum(1 for p in acik if p["x"]["g"] == "CR")
    bekleyenler = sorted([b for b in bekleyenler if b["gun"] == son_gun], key=lambda b: -b["mom"])
    if bekleyenler:
        blok = [f"🟢 YENİ SİNYAL — bir sonraki açılışta AL ({len(bekleyenler)})"]
        for b in bekleyenler:
            stop_pct = (b["stop_tahmin"] / b["kapanis"] - 1) * 100
            agirlik = min(PORTFOY["RISK"] / (-stop_pct / 100 + 0.003), PORTFOY["CAP"]) * 100
            uygun = yer > 0 and (b["g"] != "CR" or kripto_yer > 0)
            if uygun:
                yer -= 1
                if b["g"] == "CR":
                    kripto_yer -= 1
            not_ = "" if uygun else "  ⚪ portföy dolu, atla"
            blok.append(f"• {ad(b['t'])} — kapanış {yerel(D, b['t'], b['kapanis'])}, stop ≈ "
                        f"{yerel(D, b['t'], b['stop_tahmin'])} ({stop_pct:.1f}%), pozisyon ≈ sermayenin "
                        f"%{agirlik:.0f}'i{not_}\n  {tv_link(b['t'], b['g'])}")
        satirlar.append("\n".join(blok))

    # 2) Acik pozisyonlar: bugun yapilacaklar
    yapilacak, durum = [], []
    for p in sorted(acik, key=lambda p: p["x"]["d"]):
        x = p["x"]
        t = x["t"]
        son = D[t]["C"][-1]
        kar = (son / x["entry"] - 1) * 100
        stops = x["stops"]
        onceki = stops[-2] if len(stops) >= 2 else x["st0"]
        taze = int(D[t]["T"][-1]) == son_gun
        if not taze:
            pass
        elif x["exitNext"]:
            yapilacak.append(f"🟠 {ad(t)}: 40 günde %5 kâra ulaşmadı → bir sonraki açılışta SAT")
        elif stops and stops[-1] > onceki + 1e-12:
            yapilacak.append(f"⬆️ {ad(t)}: stopu {yerel(D, t, onceki)} → {yerel(D, t, stops[-1])} seviyesine çek")
        if taze and x["partGun"] == x["dx"]:
            yapilacak.append(f"🏁 {ad(t)}: +%50'ye ulaştı, 1/3 satıldı, stop girişe çekildi")
        hedef = "✓ alındı" if x["partDone"] else yerel(D, t, x["entry"] * (1 + P["PART_AT"]))
        durum.append(f"• {ad(t)}: giriş {yerel(D, t, x['entry'], x['i0'])} ({tarih(x['d'])}), son {yerel(D, t, son)}, "
                     f"{kar:+.1f}%, stop {yerel(D, t, x['stop'])}, +%50 hedef {hedef}")
    # 3) Dun kapananlar
    for p in pf["kapananlar"]:
        x = p["x"]
        if x["dx"] == son_gun:
            neden = "stop oldu" if x["neden"] == "stop" else "zaman stopuyla çıkıldı"
            yapilacak.append(f"🔴 {ad(x['t'])}: {neden} — {yerel(D, x['t'], x['cikis'], x['ix'])}, "
                             f"girişe göre {(x['cikis'] / x['entry'] - 1) * 100:+.1f}%")
    if yapilacak:
        satirlar.append("📋 YAPILACAKLAR\n" + "\n".join(yapilacak))
    if durum:
        satirlar.append(f"📂 KÂĞIT PORTFÖY ({len(acik)}/{PORTFOY['K']} pozisyon)\n" + "\n".join(durum))
    else:
        satirlar.append(f"📂 KÂĞIT PORTFÖY: açık pozisyon yok ({KAGIT_BASLANGIC} itibarıyla takipte)")
    satirlar.append(f"💼 Kâğıt portföy değeri: {pf['eq'] * 100:.1f} (başlangıç 100)")
    if not bekleyenler and not yapilacak:
        satirlar.append("Bugün yapılacak işlem yok.")
    return "\n\n".join(satirlar)


def send_telegram(mesaj: str):
    token, chat_id = os.environ.get("TELEGRAM_BOT_TOKEN"), os.environ.get("TELEGRAM_CHAT_ID")
    print("-" * 60 + "\n" + mesaj)
    if not token or not chat_id:
        return
    parcalar, buf = [], ""
    for blok in mesaj.split("\n\n"):
        if buf and len(buf) + len(blok) + 2 > 3900:
            parcalar.append(buf); buf = ""
        buf = (buf + "\n\n" + blok) if buf else blok
    if buf:
        parcalar.append(buf)
    for parca in [p[i:i + 3900] for p in parcalar for i in range(0, len(p), 3900)]:
        for deneme in range(3):
            try:
                r = requests.post(f"https://api.telegram.org/bot{token}/sendMessage",
                                  data=dict(chat_id=chat_id, text=parca, disable_web_page_preview="true"), timeout=15)
                if r.ok:
                    break
                print("Telegram hatasi:", r.status_code, r.text)
                time.sleep(3 + 3 * deneme)
            except Exception as exc:  # noqa: BLE001
                print("Telegram hatasi:", exc); time.sleep(2)
        time.sleep(0.4)


# ───────────────────────── Ana ─────────────────────────
def notu(satir: str):
    """Ekrana yaz; GitHub Actions'ta ayrica ozet notu olarak goster."""
    print(satir)
    if os.environ.get("GITHUB_ACTIONS") == "true":
        print("::notice::" + satir.replace("%", "%25").replace("\n", "%0A"))


def backtest(D: dict, trades: list):
    ana = [x for x in trades if not x["open"]] + [x for x in trades if x["open"]]
    sumR = sum(x["R"] for x in ana)
    notu(f"varlik: {sum(1 for t in GRUP if (t + '$' if GRUP[t] == 'BIST' else t) in D)}  islem: {len(ana)}  toplam R: {sumR:.1f}")
    for t in ("AAPL", "NVDA", "THYAO.IS$", "ASELS.IS$", "BTC-USD", "ETH-USD", "GLD", "SPY", "XOM"):
        z = [x for x in ana if x["t"] == t]
        notu(f"  {t}: {len(z)}/{sum(x['R'] for x in z):.2f}")
    pf = []
    for bas, bit in (("2005-01-01", None), ("2005-01-01", "2020-01-01"), ("2020-01-01", None)):
        r = portfoy(trades, bas, bit)
        pf.append(f"portfoy {bas}..{bit or 'bugun'}: CAGR %{r['cagr'] * 100:.1f}  maxDD %{r['mdd'] * 100:.1f}  "
                  f"alinan {len(r['alinan'])}  carpan x{r['eq']:.2f}")
    notu(" | ".join(pf))
    notu("arastirma referansi: islem 4939, toplam R 3849.3, 2005+ CAGR %19.0 / DD %24.8 / alinan 640")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--backtest", action="store_true")
    ap.add_argument("--telegram-yok", action="store_true")
    a = ap.parse_args()
    t0 = time.time()
    D = veri_cek(son_gun_haric=not a.backtest)
    eksik = [t for t in list(GRUP) + EK if (t + "$" if t.endswith(".IS") else t) not in D and t not in D]
    notu(f"veri: {len(D)} seri, eksik {len(eksik)}: {' '.join(eksik[:20])}  ({time.time() - t0:.0f} sn)")
    trades, bekleyenler = hepsini_sim(D)
    if a.backtest:
        backtest(D, trades)
        return
    if len(eksik) > 40:
        send_telegram(f"⚠️ Büyük Av: veri alınamadı ({len(eksik)} varlık eksik). Rapor atlandı.")
        sys.exit(1)
    mesaj = rapor(D, trades, bekleyenler)
    if a.telegram_yok:
        print(mesaj)
    else:
        send_telegram(mesaj)


if __name__ == "__main__":
    main()
