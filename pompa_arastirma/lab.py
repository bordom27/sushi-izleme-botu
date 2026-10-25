"""
Pump/dump kural laboratuvari (4s, USDT-M vadeli, delist dahil, maliyet %0.2 + funding, ayni mumda stop+hedef -> stop).
  long_ates: pump ateslemesi aninda long (hacim patlamasi + guclu yesil mum)
  short_cokus: buyuk pump sonrasi tepeden donuste short
"""
import os, sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import numpy as np, pandas as pd
import short_lab as S

MALIYET = 0.002
BPD = 6          # gunde mum sayisi (4s=6, 1s=24)


_CACHE = {}


def temel(g):
    k = id(g)
    if k in _CACHE:
        return _CACHE[k]
    if len(_CACHE) > 4:
        _CACHE.clear()
    o, h, l, c, v = (g[k].to_numpy(float) for k in "ohlcv")
    pc = np.r_[np.nan, c[:-1]]
    tr = np.nanmax(np.vstack([h - l, np.abs(h - pc), np.abs(l - pc)]), axis=0)
    atr = pd.Series(tr).ewm(alpha=1 / 14, adjust=False).mean().to_numpy()
    V = pd.Series(v)
    vmed = V.rolling(30 * BPD, min_periods=10 * BPD).median().shift(1).to_numpy()
    qv = (pd.Series(c * v).rolling(30 * BPD, min_periods=10 * BPD).median() * BPD).to_numpy()
    _CACHE[k] = (o, h, l, c, v, atr, vmed, qv)
    return _CACHE[k]


def _tepe(h, N):
    from numpy.lib.stride_tricks import sliding_window_view as sw
    n = len(h); tepe = np.full(n, np.nan); tix = np.full(n, -1)
    if n >= N:
        w = sw(h, N)
        a = w.argmax(axis=1)
        tepe[N - 1:] = w[np.arange(len(w)), a]
        tix[N - 1:] = np.arange(len(w)) + a
    return tepe, tix


def _cik(yon, i, e, st, tg, h, l, c, maks, T, fr, iz=None):
    """yon=+1 long, -1 short. Donus: (R, neden, j). iz: (bas_R, geri_R) kar kilitleyen iz stop (sadece long)."""
    n = len(c); risk = abs(st - e)
    s_ = st; en_iyi = e
    for j in range(i + 1, min(n, i + 1 + maks)):
        if yon > 0:
            if l[j] <= s_:
                cik, ne = s_, "STOP"; break
            if tg is not None and h[j] >= tg:
                cik, ne = tg, "HEDEF"; break
            if iz is not None:
                en_iyi = max(en_iyi, h[j])
                if en_iyi - e >= iz[0] * risk:
                    s_ = max(s_, en_iyi - iz[1] * risk)
        else:
            if h[j] >= s_:
                cik, ne = s_, "STOP"; break
            if tg is not None and l[j] <= tg:
                cik, ne = tg, "HEDEF"; break
    else:
        j = min(n - 1, i + maks); cik, ne = c[j], "ZAMAN"
    fz = 0.0
    if fr is not None and len(fr):
        dt = pd.Timedelta(hours=24 // BPD)
        t0 = T[i] + dt; t1 = T[j] + dt
        fz = fr[(fr.index > t0) & (fr.index <= t1)].sum()
    getiri = yon * (cik - e) / e - MALIYET - yon * fz          # long funding oder, short alir
    return getiri / (risk / e), ne, j


def long_ates(g, fr=None, r1=0.12, vx=5.0, fitil=0.3, maks_r42=1.0, stop="mum", tR=2.0, maks=18, iz=None, lik=1e6):
    o, h, l, c, v, atr, vmed, qv = temel(g)
    T = g.index; n = len(c); pc = np.r_[np.nan, c[:-1]]
    w7 = 7 * BPD
    r42 = c / np.r_[np.full(w7, np.nan), c[:-w7]] - 1
    ust = (h - c) / np.maximum(h - l, 1e-12)
    m = (c / pc - 1 >= r1) & (v >= vx * vmed) & (ust <= fitil) & (qv >= lik) & ~(r42 > maks_r42)
    out = []; serbest = -1
    for i in np.flatnonzero(m):
        if i <= serbest or i >= n - 1 or i < 10 * BPD:
            continue
        e = c[i]
        st = l[i] if stop == "mum" else (o[i] + l[i]) / 2 if stop == "orta" else e - stop * atr[i]
        if not (st < e) or (e - st) / e < 0.01 or (e - st) / e > 0.5:
            continue
        tg = None if tR is None else e + tR * (e - st)
        R, ne, j = _cik(+1, i, e, st, tg, h, l, c, maks, T, fr, iz)
        out.append({"zaman": T[i], "R": R, "neden": ne, "sure": j - i, "risk": (e - st) / e, "r1": c[i] / pc[i] - 1,
                    "vx": v[i] / vmed[i], "qv": qv[i], "yas": i})
        serbest = j
    return out


def short_cokus(g, fr=None, P=1.0, N=18, dusus=0.15, maks_tepe=12, stop_k=0.3, tR=1.0, maks=30, kirmizi=True, lik=1e6,
                hedef_geri=None):
    """Son N mumda dibe gore P kadar pump; tepe (en yuksek high) sonrasi maks_tepe mum icinde kapanis tepeden 'dusus' kadar
    asagida ve mum kirmizi -> short. Stop: tepe + stop_k*ATR. Hedef: tR*risk (veya hedef_geri: pump boyunun o kadari geri)."""
    o, h, l, c, v, atr, vmed, qv = temel(g)
    T = g.index; n = len(c)
    dip = pd.Series(l).rolling(42).min().shift(N).to_numpy()            # pump oncesi dip (N mum once biten 7 gun)
    tepe, tix = _tepe(h, N)
    ix = np.arange(n); once = ix - tix
    with np.errstate(invalid="ignore", divide="ignore"):
        m = (tepe / dip - 1 >= P) & (qv >= lik) & (once >= 1) & (once <= maks_tepe) & (c <= tepe * (1 - dusus)) & (ix >= 250)
    if kirmizi:
        m &= c < o
    out = []; serbest = -1
    for i in np.flatnonzero(m):
        if i <= serbest or i >= n - 1:
            continue
        ti = tix[i]
        e = c[i]; st = tepe[i] + stop_k * atr[i]
        risk = (st - e) / e
        if risk < 0.01 or risk > 0.6:
            continue
        tg = e - tR * (st - e) if hedef_geri is None else e - hedef_geri * (tepe[i] - dip[i])
        if tg <= 0:
            tg = e * 0.3
        R, ne, j = _cik(-1, i, e, st, tg, h, l, c, maks, T, fr)
        out.append({"zaman": T[i], "R": R, "neden": ne, "sure": j - i, "risk": risk, "pump": tepe[i] / dip[i] - 1,
                    "tepeden": 1 - c[i] / tepe[i], "qv": qv[i], "yas": i, "tepe_once": i - ti})
        serbest = max(j, i + N)            # ayni pump icin tekrar girme
    return out


def ozet(t):
    if len(t) == 0:
        return {"n": 0}
    t = t.copy(); t["kaz"] = t.R > 0
    eg = t[t.zaman < "2025-01-01"]; ts = t[t.zaman >= "2025-01-01"]; s12 = t[t.zaman >= "2025-10-22"]
    return {"n": len(t), "isb": t.kaz.mean(), "R": t.R.mean(), "topR": t.R.sum(),
            "n_eg": len(eg), "isb_eg": eg.kaz.mean(), "R_eg": eg.R.mean(),
            "n_ts": len(ts), "isb_ts": ts.kaz.mean(), "R_ts": ts.R.mean(),
            "s12_haftada": len(s12) / 52.1, "isb_s12": s12.kaz.mean(), "R_s12": s12.R.mean()}
