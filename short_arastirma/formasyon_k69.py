"""
K69 SHORT + Kirilim69 formasyon dedektorleri (6 Kas 2026).
Ayi formasyonlari (kirilim_v6.formasyon_ara ile ayni mantik, yon -1): CIFT TEPE, OBO, TREND KIRILIMI (yukselen dip cizgisi),
UCGEN (asagi), AYI BAYRAGI. Pivot 5 bar, ATR 14 (rma).
Soru: K69 SHORT sinyalinden once (destek kirilimindan 10 mum once -> sinyal mumu) ayni coinde ayi formasyonu kirildiysa isabet artiyor mu?
Ayrica formasyon kirilimi hacimli mi (>= 1.5x) ayrimi.
Kullanim: SP=... python short_arastirma/formasyon_k69.py
"""
from __future__ import annotations

import multiprocessing as mp
import os
import sys

import numpy as np
import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.chdir(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import short_lab as S                                                    # noqa: E402
import short_retest as SR                                                # noqa: E402
from kirilim_v6 import pivot                                             # noqa: E402
from short_arastirma.gelistir2 import tek_pozisyon                       # noqa: E402

SP = os.environ.get("SP", "/tmp")
D = None
FP = 5


def cizgi(p1, p2, x):
    (x1, y1), (x2, y2) = p1, p2
    return y1 + (y2 - y1) * (x - x1) / (x2 - x1)


def ayi_formasyonlari(g):
    x = SR.gostergeler(g)
    o, h, l, c, v, atr, va = (x[k] for k in ("o", "h", "l", "c", "v", "atr", "va"))
    n = len(c)
    ph, pl = pivot(h, FP, True), pivot(l, FP, False)
    fph, fpl, kul, out = [], [], set(), []
    for i in range(2, n):
        if not np.isnan(ph[i]):
            fph.append((i - FP, ph[i])); fph = fph[-10:]
        if not np.isnan(pl[i]):
            fpl.append((i - FP, pl[i])); fpl = fpl[-10:]
        a = atr[i]
        if not (a > 0):
            continue
        bul = []
        if len(fph) >= 2:                                                   # CIFT TEPE
            (b1, p1), (b2, p2) = fph[-2], fph[-1]
            if abs(p1 - p2) <= 0.6 * a and 8 <= b2 - b1 <= 60 and i - b2 <= 30:
                t = float(np.min(l[b1:b2 + 1]))
                if min(p1, p2) - t >= 2 * a and c[i] < t and c[i - 1] >= t:
                    bul.append(("CIFT TEPE", ("CT", b1, b2)))
        if len(fph) >= 3:                                                   # OBO
            (ba, pa), (bb, pb), (bc, pc) = fph[-3:]
            if pb > pa + 0.5 * a and pb > pc + 0.5 * a and abs(pa - pc) <= 1.5 * a \
                    and 5 <= bb - ba <= 50 and 5 <= bc - bb <= 50 and i - bc <= 25:
                k1 = ba + int(np.argmin(l[ba:bb + 1])); k2 = bb + int(np.argmin(l[bb:bc + 1]))
                if k2 > k1:
                    n0 = cizgi((k1, l[k1]), (k2, l[k2]), i); n1 = cizgi((k1, l[k1]), (k2, l[k2]), i - 1)
                    if c[i] < n0 and c[i - 1] >= n1:
                        bul.append(("OBO", ("OBO", ba, bb, bc)))
        ust = alt = None                                                    # TREND / UCGEN (asagi kirilim)
        if len(fph) >= 2:
            (b1, p1), (b2, p2) = fph[-2], fph[-1]
            if p2 < p1 - 0.3 * a and b2 - b1 >= 8 and i - b1 <= 120:
                seg = c[b2 + 1:i]; xs = np.arange(b2 + 1, i)
                if len(seg) == 0 or np.all(seg <= cizgi((b1, p1), (b2, p2), xs)):
                    ust = ((b1, p1), (b2, p2))
        if len(fpl) >= 2:
            (b1, p1), (b2, p2) = fpl[-2], fpl[-1]
            if p2 > p1 + 0.3 * a and b2 - b1 >= 8 and i - b1 <= 120:
                seg = c[b2 + 1:i]; xs = np.arange(b2 + 1, i)
                if len(seg) == 0 or np.all(seg >= cizgi((b1, p1), (b2, p2), xs)):
                    alt = ((b1, p1), (b2, p2))
        if alt is not None:
            v0 = cizgi(alt[0], alt[1], i); v1 = cizgi(alt[0], alt[1], i - 1)
            if c[i] < v0 - 0.1 * a and c[i - 1] >= v1:
                ucgen = ust is not None and max(ust[0][0], alt[0][0]) >= i - 80
                bul.append(("UCGEN" if ucgen else "TREND KIRILIMI", ("UC" if ucgen else "TR", -1, alt[0][0], alt[1][0])))
        if i >= 40:                                                         # AYI BAYRAGI
            w0 = i - 25
            lk = w0 + int(np.argmin(l[w0:i])); m = i - 1 - lk
            if 4 <= m <= 20:
                L_ = l[lk]; tepe = float(np.max(h[max(0, lk - 10):lk + 1])); itki = tepe - L_
                kons = float(np.max(h[lk + 1:i]))
                if itki >= 4 * a and kons <= L_ + 0.5 * itki and c[i] < L_ - 0.1 * a and c[i - 1] >= L_:
                    bul.append(("AYI BAYRAGI", ("BY", -1, lk)))
        for tip, key in bul:
            if key in kul:
                continue
            kul.add(key)
            out.append((i, tip, v[i] / va[i] if va[i] > 0 else np.nan))
    return out


def coin(s):
    g = D[s]
    f = ayi_formasyonlari(g)
    T = g.index
    return [{"symbol": s, "zaman": T[i], "ix": i, "tip": tip, "hacim": hv} for i, tip, hv in f]


if __name__ == "__main__":
    pk = os.path.join(SP, "formasyon_olay.pkl")
    if os.path.exists(pk):
        F = pd.read_pickle(pk)
    else:
        D, _, _ = S.yukle()
        with mp.get_context("fork").Pool(2) as hv:
            out = hv.map(coin, list(D))
        F = pd.DataFrame([x for o in out for x in o])
        F.to_pickle(pk)
    print("ayi formasyonu kirilimlari:", len(F), F.tip.value_counts().to_dict())

    t = pd.read_pickle(os.path.join(SP, "gelistir2_neden.pkl"))
    sert = t.risk.between(0.004, 0.25) & (t.kir_boy < 2.7) & (t.vor3 < 0.7)
    e1, e2 = sert & (t.kirmizi3 == 1), sert & (t.kirmizi3 <= 2)
    k1 = t.zaman.map(t[e1].groupby("zaman").size()).fillna(0)
    k2 = t.zaman.map(t[e2].groupby("zaman").size()).fillna(0)
    KUR = {"K69 ham (filtresiz)": e1, "CANLI kural": e1 & ((k1 >= 3) | (t.yildiz == 2)), "YENI kural": e2 & (k2 >= 6)}

    # her K69 dokunusu icin: kirilimdan 10 mum once -> sinyal mumu arasinda ayni coinde ayi formasyonu var mi
    Fg = {s: g for s, g in F.groupby("symbol")}
    H4 = pd.Timedelta(hours=4)
    tipler, hacimli = [], []
    for s, z, b in zip(t.symbol, t.zaman, t.bekle):
        g = Fg.get(s)
        if g is None:
            tipler.append(""); hacimli.append(False); continue
        bas = z - (b + 10) * H4
        w = g[(g.zaman >= bas) & (g.zaman <= z)]
        tipler.append(",".join(sorted(set(w.tip)))); hacimli.append(bool((w.hacim >= 1.5).any()))
    t["formasyon"] = tipler; t["form_hacimli"] = hacimli
    t["p"] = t.R * t.risk * 100                                              # islem basi % (kaldiracsiz, maliyet dahil)

    def sat(x, ad):
        x = tek_pozisyon(x).dropna(subset=["R"])
        if not len(x):
            return {"grup": ad, "n": 0}
        p = x.R * x.risk * 100
        o = {"grup": ad, "n": len(x), "isabet%": round((x.R > 0).mean() * 100, 1), "islem basi %": round(p.mean(), 2),
             "kazanc ort %": round(p[x.R > 0].mean(), 2) if (x.R > 0).any() else np.nan}
        for etk, m in (("<2025", x.zaman < "2025-01-01"), ("2025+", x.zaman >= "2025-01-01")):
            y = x[m]
            o[f"{etk} n/isb%"] = f"{len(y)}/{(y.R > 0).mean() * 100:.0f}" if len(y) else "-"
        return o

    rows = []
    for kad, m in KUR.items():
        b = t[m]
        rows.append(sat(b, f"{kad}: HEPSI"))
        rows.append(sat(b[b.formasyon != ""], f"{kad}: + ayi formasyonu VAR"))
        rows.append(sat(b[b.formasyon == ""], f"{kad}: formasyon YOK"))
        rows.append(sat(b[b.form_hacimli], f"{kad}: + hacimli formasyon (>=1.5x)"))
        for tip in ("CIFT TEPE", "OBO", "TREND KIRILIMI", "UCGEN", "AYI BAYRAGI"):
            rows.append(sat(b[b.formasyon.str.contains(tip)], f"{kad}:   sadece {tip}"))
    R = pd.DataFrame(rows)
    pd.set_option("display.width", 250, "display.max_colwidth", 60)
    print(R.to_string(index=False))
    R.to_csv("short_arastirma/kos_formasyon_k69.csv", index=False)
