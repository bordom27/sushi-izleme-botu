"""
K69 SHORT: TP1 sonrasi kismi kapanis + iz suren stop testi (25 Eki 2026).

Girisler canli kuralla ayni (short_retest.sinyaller). Cikis varyantlari:
  p      : TP1'de (0.5R; <5M$ coinde 0.4R) kapatilan pay. p=1.0 -> mevcut kural (tamamen kapat).
  be     : TP1 sonrasi kalan payin stopu girise (basabas) cekilir mi
  k      : TP1 sonrasi iz mesafesi (giris anindaki ATR x k), en dusuk dibin ustunden; 0 = iz yok
  tg2    : kalan pay icin ikinci hedef (R cinsinden), None = yok
  maks   : zaman stopu (4s mum), kalan pay icin de gecerli
Kurallar: ayni mumda stop+hedef -> stop (kotumser). Gap: stop seviyesinin ustunde acilirsa acilistan cikis.
Yeni stop seviyesi bir sonraki mumdan itibaren gecerli (4s modu). 1s modu: 2024+ icin ayni girisler 1 saatlik
mumlarla simule edilir (TP1 mumunda once hangisi oldu sorusunu cozer, iz her saat guncellenir).
Maliyet gidis-donus %0.2 + funding (short alir/oder).  Bir coinde ayni anda tek pozisyon.
Kullanim: python short_arastirma/iz_stop_test.py
"""
from __future__ import annotations

import glob
import multiprocessing as mp
import os
import sys

import numpy as np
import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.chdir(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import short_lab as S          # noqa: E402
import short_retest as SR      # noqa: E402

MALIYET = 0.002
SP = os.environ.get("SP", "/tmp")

VARYANT = {"MEVCUT (tam kapat)": dict(p=1.0, be=False, k=0, tg2=None)}
for p in (0.5, 0.33):
    for be in (True, False):
        for k in (0, 1.0, 1.5, 2.0):
            if not be and k == 0:
                continue        # ne BE ne iz: kalan pay sadece orijinal stop/zaman stopu
            VARYANT[f"%{int(p*100)} kapat, {'BE' if be else 'BEsiz'}, iz {k if k else '-'}"] = dict(p=p, be=be, k=k, tg2=None)
    VARYANT[f"%{int(p*100)} kapat, BEsiz, iz yok"] = dict(p=p, be=False, k=0, tg2=None)
    for tg2 in (1.0, 1.5):
        VARYANT[f"%{int(p*100)} kapat, BE, iz 1.5, 2.hedef {tg2}R"] = dict(p=p, be=True, k=1.5, tg2=tg2)

D = FR = D1 = None


def islem(O, H, L, C, i0, e, st, hr, atr0, maks, p, be, k, tg2):
    """i0: girisi izleyen ilk mumun indeksi. Donus: (parcalar [(pay, cikis_fiyati, cikis_ix)], tp1_alindi)."""
    n = len(C)
    risk = st - e
    tg = e - hr * risk
    son = min(n - 1, i0 + maks - 1)
    j = i0
    while j <= son:                                  # TP1 oncesi
        if H[j] >= st:
            return [(1.0, max(st, O[j]), j)], False
        if L[j] <= tg:
            break
        j += 1
    else:
        return [(1.0, C[son], son)], False
    parca = [(p, min(tg, O[j]), j)]
    if p >= 1.0:
        return parca, True
    q = 1 - p
    s2 = e if be else st
    dip = L[j]
    hedef2 = e - tg2 * risk if tg2 else -np.inf
    if L[j] <= hedef2:                               # ayni mumda 2. hedef de geldiyse
        return parca + [(q, hedef2, j)], True
    if k > 0:
        s2 = min(s2, dip + k * atr0)
    j += 1
    while j <= son:
        if H[j] >= s2:
            return parca + [(q, max(s2, O[j]), j)], True
        if L[j] <= hedef2:
            return parca + [(q, min(hedef2, O[j]), j)], True
        dip = min(dip, L[j])
        if k > 0:
            s2 = min(s2, dip + k * atr0)
        j += 1
    return parca + [(q, C[son], son)], True


def fon_top(fr, t0, t1):
    if fr is None or not len(fr):
        return 0.0
    return float(fr[(fr.index > t0) & (fr.index <= t1)].sum())


def coin(s):
    g = D[s]
    sig = SR.sinyaller(g)
    if not sig:
        return []
    O, H, L, C = (g[x].to_numpy(float) for x in "ohlc")
    atr = SR.gostergeler(g)["atr"]
    T = g.index
    fr = FR.get(s)
    g1 = D1.get(s)
    if g1 is not None:
        O1, H1, L1, C1 = (g1[x].to_numpy(float) for x in "ohlc")
        T1 = g1.index
    out = []
    for ad, v in VARYANT.items():
        serbest = pd.Timestamp(0)
        for z in sig:
            i = z["ix"]
            if T[i] <= serbest or i >= len(C) - 1:
                continue
            e, st, hr = z["giris"], z["stop"], z["hedef_r"]
            risk = (st - e) / e
            r4 = islem(O, H, L, C, i + 1, e, st, hr, atr[i], 30, **v)
            parca, tp1 = r4
            t_son = T[max(x[2] for x in parca)]
            R = sum(pay * ((e - f) / e - MALIYET + fon_top(fr, T[i], T[jx])) for pay, f, jx in parca) / risk
            row = {"symbol": s, "var": ad, "giris": T[i], "cikis": t_son, "R": R, "tp1": tp1,
                   "q": z["gunluk_hacim"], "yildiz": z["yildiz"], "R1h": np.nan}
            # 1 saatlik dogrulama (giris mumu kapanisindan sonra)
            if g1 is not None and T[i] >= T1[0]:
                a0 = int(np.searchsorted(T1, T[i] + pd.Timedelta(hours=4)))
                if a0 < len(C1) - 1 and T1[a0] == T[i] + pd.Timedelta(hours=4):
                    parca1, tp11 = islem(O1, H1, L1, C1, a0, e, st, hr, atr[i], 120, **v)
                    row["R1h"] = sum(pay * ((e - f) / e - MALIYET + fon_top(fr, T[i], T1[jx]))
                                     for pay, f, jx in parca1) / risk
                    row["tp1_1h"] = tp11
                    t_son = max(t_son, T1[max(x[2] for x in parca1)])
            out.append(row)
            serbest = t_son
    return out


def yukle_1h():
    fs = sorted(glob.glob("arastirma_cikti/dok1h/k1h_*.csv.gz"))
    K = pd.concat([pd.read_csv(f) for f in fs], ignore_index=True)
    K["t"] = pd.to_datetime(K["t"], unit="s")
    return {s: g.drop_duplicates("t").sort_values("t").set_index("t")[["o", "h", "l", "c", "v"]]
            for s, g in K.groupby("symbol", sort=True)}


def ozet(t, kol="R"):
    t = t.dropna(subset=[kol]).sort_values("cikis")
    if not len(t):
        return {}
    r = t[kol]
    eq = r.cumsum()
    son12 = t[t.giris >= t.giris.max() - pd.Timedelta(days=365)][kol]
    test = t[t.giris >= "2024-01-01"][kol]
    return {"n": len(t), "isabet%": round((r > 0).mean() * 100, 1), "R/islem": round(r.mean(), 3),
            "toplam_R": round(r.sum(), 1), "maxDD_R": round((eq.cummax() - eq).max(), 1),
            "2024+ isabet%": round((test > 0).mean() * 100, 1), "2024+ R/i": round(test.mean(), 3),
            "son12ay isabet%": round((son12 > 0).mean() * 100, 1), "son12ay R": round(son12.sum(), 1)}


if __name__ == "__main__":
    D, FR, _ = S.yukle()
    D1 = yukle_1h()
    with mp.get_context("fork").Pool(2) as hv:
        out = hv.map(coin, list(D))
    t = pd.DataFrame([x for l in out for x in l])
    t.to_pickle(os.path.join(SP, "iz_stop.pkl"))
    rows = []
    for ad in VARYANT:
        x = t[t["var"] == ad]
        a = ozet(x)
        b = ozet(x[x.giris >= "2024-01-01"], "R1h")
        rows.append({"varyant": ad, **a, "1s(2024+) isabet%": b.get("isabet%"), "1s(2024+) R/i": b.get("R/islem"),
                     "1s(2024+) maxDD": b.get("maxDD_R")})
    tab = pd.DataFrame(rows)
    pd.set_option("display.width", 250, "display.max_columns", 30, "display.max_colwidth", 40)
    print(tab.to_string(index=False))
    tab.to_csv("short_arastirma/kos_iz_stop.csv", index=False)
