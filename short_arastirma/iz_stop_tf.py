"""
K69 SHORT gunluk / haftalik mumda (25 Eki 2026) + cikis varyantlari (tam kapat vs TP1 sonrasi iz stop).

Sinyal: short_retest.sinyaller ile ayni kural, 4s veri gunluk/haftaliga yeniden ornekleniyor.
  Gunluk hacim (min 1M$, 5M$ sinirlari) zaman dilimine gore hesaplanir. Maks risk %25 -> %50 (ust zaman diliminde stop genis).
  Seviye uzunluklari iki ayarla denenir (mum sayisi).
Cikis: sinyal mumunun kapanisindan sonra 4 saatlik mumlarla simule edilir (TP1 mumunda sira sorunu yok sayilacak kadar kucuk).
  Zaman stopu 30 mum (zaman dilimi cinsinden). Hedef 0.5R / 0.4R (<5M$) ve ayrica 1.0R denenir.
Kullanim: python short_arastirma/iz_stop_tf.py
"""
from __future__ import annotations

import inspect
import multiprocessing as mp
import os
import sys

import numpy as np
import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.chdir(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import short_lab as S                    # noqa: E402
import short_retest as SR                # noqa: E402
from short_arastirma.iz_stop_test import islem, fon_top, MALIYET   # noqa: E402

SP = os.environ.get("SP", "/tmp")
TF = {"1d": ("1D", 6), "1w": ("W-MON", 42)}            # resample kurali, 4s mum sayisi
SEVIYE = {"1d": [(80, 160), (40, 80)], "1w": [(40, 80), (20, 40)]}
CIKIS = {
    "tam kapat": dict(p=1.0, be=False, k=0, tg2=None),
    "%50+BE+iz 1.0": dict(p=0.5, be=True, k=1.0, tg2=None),
    "%50+BE+iz 1.5": dict(p=0.5, be=True, k=1.5, tg2=None),
    "%50+BE+iz 2.0": dict(p=0.5, be=True, k=2.0, tg2=None),
    "%50+BE+iz 1.5+2.hedef 1.5R": dict(p=0.5, be=True, k=1.5, tg2=1.5),
}
HEDEF = {"0.5R": dict(hedef_r=0.5, hedef_r_sig=0.4), "1.0R": dict(hedef_r=1.0, hedef_r_sig=1.0)}

D = FR = None


def _sinyal_fn(tf):
    """short_retest.sinyaller'in zaman dilimine uyarlanmis kopyasi (hacim olcegi + maks risk)."""
    gun_basi = {"1d": 1, "1w": 7}[tf]
    pencere = {"1d": 30, "1w": 5}[tf]

    def gostergeler(g):
        x = SR.gostergeler(g)
        x["qv"] = (pd.Series(x["c"] * x["v"]).rolling(pencere, min_periods=max(3, pencere // 3)).median()
                   / gun_basi).to_numpy()
        return x

    kaynak = inspect.getsource(SR.sinyaller).replace("0.004 <= risk <= 0.25", "0.004 <= risk <= 0.5")
    ns = dict(vars(SR))
    ns["gostergeler"] = gostergeler
    exec(kaynak, ns)
    return ns["sinyaller"], gostergeler


def yeniden(g, kural):
    r = g.resample(kural, label="left", closed="left").agg({"o": "first", "h": "max", "l": "min", "c": "last", "v": "sum"})
    return r.dropna()


def coin(s):
    g4 = D[s]
    O4, H4, L4, C4 = (g4[x].to_numpy(float) for x in "ohlc")
    T4 = g4.index
    fr = FR.get(s)
    out = []
    for tf, (kural, k4) in TF.items():
        g = yeniden(g4, kural)
        if len(g) < 60:
            continue
        g = g.iloc[:-1]                                   # son (kapanmamis olabilecek) mumu at
        sinyaller, gost = _sinyal_fn(tf)
        atr = gost(g)["atr"]
        bar = pd.Timedelta(days=1 if tf == "1d" else 7)
        for sev in SEVIYE[tf]:
            for hn, hp in HEDEF.items():
                sig = sinyaller(g, dict(seviyeler=sev, **hp))
                for cn, cp in CIKIS.items():
                    serbest = pd.Timestamp(0)
                    for z in sig:
                        i = z["ix"]
                        if g.index[i] <= serbest:
                            continue
                        a0 = int(np.searchsorted(T4, g.index[i] + bar))
                        if a0 >= len(C4) - 1:
                            continue
                        e, st, hr = z["giris"], z["stop"], z["hedef_r"]
                        risk = (st - e) / e
                        parca, tp1 = islem(O4, H4, L4, C4, a0, e, st, hr, atr[i], 30 * k4, **cp)
                        R = sum(pay * ((e - f) / e - MALIYET + fon_top(fr, g.index[i], T4[jx])) for pay, f, jx in parca) / risk
                        cik = T4[max(x[2] for x in parca)]
                        out.append({"symbol": s, "tf": tf, "seviye": f"{sev[0]}/{sev[1]}", "hedef": hn, "cikis_tip": cn,
                                    "giris": g.index[i], "cikis": cik, "R": R, "tp1": tp1, "risk%": risk * 100,
                                    "yildiz": z["yildiz"]})
                        serbest = cik
    return out


def ozet(x):
    x = x.sort_values("cikis")
    r = x.R
    eq = r.cumsum()
    y = x.giris.dt.year
    yil = {f"R{yy % 100}": round(r[y == yy].sum(), 1) for yy in range(2021, 2027)}
    hafta = (x.giris.max() - x.giris.min()).days / 7 or 1
    return {"n": len(x), "sinyal/hafta": round(len(x) / hafta, 2), "isabet%": round((r > 0).mean() * 100, 1),
            "R/islem": round(r.mean(), 3), "toplam_R": round(r.sum(), 1), "maxDD_R": round((eq.cummax() - eq).max(), 1),
            "ort_risk%": round(x["risk%"].mean(), 1), **yil}


if __name__ == "__main__":
    D, FR, _ = S.yukle()
    with mp.get_context("fork").Pool(2) as hv:
        out = hv.map(coin, list(D))
    t = pd.DataFrame([x for l in out for x in l])
    t.to_pickle(os.path.join(SP, "iz_stop_tf.pkl"))
    rows = [{"tf": k[0], "seviye": k[1], "hedef": k[2], "cikis": k[3], **ozet(x)}
            for k, x in t.groupby(["tf", "seviye", "hedef", "cikis_tip"], sort=False)]
    tab = pd.DataFrame(rows)
    pd.set_option("display.width", 260, "display.max_columns", 40)
    print(tab.to_string(index=False))
    tab.to_csv("short_arastirma/kos_iz_stop_tf.csv", index=False)
