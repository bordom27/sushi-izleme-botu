"""
Short laboratuvari: tum USDT-M vadeli sozlesmelerin 4s verisi uzerinde short fikirleri (yerel calisir, veri_dok ciktisi ile).
Islem kurali (hepsi icin ortak): sinyal mumunun kapanisinda giris, stop fiyati ustte, hedef altta, zaman stopu.
Ayni mumda stop ve hedef birlikte degerse stop sayilir (kotumser). Maliyet: gidis-donus %0.2 (komisyon+kayma) + funding.
"""
from __future__ import annotations

import glob
import os

import numpy as np
import pandas as pd

DOK = os.environ.get("DOK", "arastirma_cikti/dok")
MALIYET = 0.002
MAKS_RISK = 0.5


def yukle():
    K = pd.concat([pd.read_csv(f) for f in sorted(glob.glob(f"{DOK}/k4h_*.csv.gz"))], ignore_index=True)
    F = pd.concat([pd.read_csv(f) for f in sorted(glob.glob(f"{DOK}/fund_*.csv.gz"))], ignore_index=True)
    meta = pd.read_csv(f"{DOK}/meta.csv")
    K["t"] = pd.to_datetime(K["t"], unit="s")      # veri_dok: us cozunurluklu datetime // 1e6 = saniye
    F["t"] = pd.to_datetime(F["t"], unit="ms")
    D = {}
    for s, g in K.groupby("symbol", sort=True):
        g = g.drop_duplicates("t").sort_values("t").set_index("t")[["o", "h", "l", "c", "v"]]
        g = g[g.v > 0]
        if len(g) < 200:
            continue
        D[s] = g
    FR = {s: g.set_index("t")["fr"].sort_index() for s, g in F.groupby("symbol")}
    return D, FR, meta


def ozellik(g: pd.DataFrame) -> pd.DataFrame:
    """Ortak gostergeler (sadece gecmis veri)."""
    o, h, l, c, v = (g[x] for x in "ohlcv")
    x = pd.DataFrame(index=g.index)
    tr = pd.concat([h - l, (h - c.shift()).abs(), (l - c.shift()).abs()], axis=1).max(axis=1)
    x["atr"] = tr.ewm(alpha=1 / 14, adjust=False).mean()
    x["qv"] = (c * v).rolling(180, min_periods=60).median() * 6           # gunluk dolar hacmi (30 gun medyan)
    x["yas"] = np.arange(len(g))
    x["vavg"] = v.rolling(20).mean().shift(1)
    return x


def btc_rejim(D):
    b = D["BTCUSDT"]["c"]
    gun = b.resample("1D").last().dropna()
    r = pd.DataFrame({"btc_ema50": gun.ewm(span=50, adjust=False).mean(), "btc_sma200": gun.rolling(200).mean(), "btc": gun})
    r["ayi50"] = r.btc < r.btc_ema50
    r["ayi200"] = r.btc < r.btc_sma200
    r["btc_r7"] = gun.pct_change(7)
    r = r.shift(1)     # dunun kapanisi (gun ici bilinir)
    return r


def sim(g: pd.DataFrame, giris_ix: np.ndarray, stop: np.ndarray, hedef: np.ndarray, maks_bar: int, fr: pd.Series | None,
        iz_atr: np.ndarray | None = None, iz_k: float = 0.0, iz_bas_r: float = 1.0):
    """Short islemleri. giris_ix: sinyal mum indeksleri (kapanista giris). Ayni anda tek pozisyon."""
    H, L, C = g.h.to_numpy(float), g.l.to_numpy(float), g.c.to_numpy(float)
    T = g.index
    n = len(C)
    out = []
    serbest = -1
    for k_, i in enumerate(giris_ix):
        if i <= serbest or i >= n - 1:
            continue
        e, s, tg = C[i], stop[k_], hedef[k_]
        if not (s > e) or (not np.isnan(tg) and tg >= e):
            continue
        risk = (s - e) / e
        if risk < 0.004 or risk > MAKS_RISK:
            continue
        cik, neden, j = np.nan, "", i
        s_ = s
        dip = e
        for j in range(i + 1, min(n, i + 1 + maks_bar)):
            if H[j] >= s_:
                cik, neden = max(s_, L[j] if L[j] > s_ else s_), "SL" if s_ >= s else "IZ"
                break
            if not np.isnan(tg) and L[j] <= tg:
                cik, neden = tg, "TP"
                break
            dip = min(dip, L[j])
            if iz_k > 0 and (e - dip) / e >= iz_bas_r * risk:
                s_ = min(s_, dip + iz_k * iz_atr[j])
        else:
            cik, neden = C[j], "ZAMAN"
        fon = 0.0
        if fr is not None and len(fr):
            fon = fr[(fr.index > T[i]) & (fr.index <= T[j])].sum()      # short funding alir (pozitifse)
        getiri = (e - cik) / e - MALIYET + fon
        out.append({"giris": T[i], "cikis": T[j], "e": e, "risk": risk, "R": getiri / risk, "neden": neden,
                    "bar": j - i, "fon": fon})
        serbest = j
    return out


def rapor(tr: pd.DataFrame, ad: str, risk_pct=0.005):
    if tr is None or len(tr) == 0:
        return {"ad": ad, "n": 0}
    tr = tr.sort_values("cikis")
    y = tr.giris.dt.year
    row = {"ad": ad, "n": len(tr), "isabet": round((tr.R > 0).mean() * 100, 1), "R": round(tr.R.sum(), 1),
           "R/islem": round(tr.R.mean(), 3)}
    eq = tr.R.cumsum()
    row["maxDD_R"] = round((eq.cummax() - eq).max(), 1)
    for yy in range(2020, 2027):
        x = tr[y == yy]
        row[str(yy)] = f"{len(x)}/{(x.R > 0).mean() * 100:.0f}%/{x.R.sum():+.0f}" if len(x) else "-"
    egit = tr[tr.giris < "2024-01-01"]
    test = tr[tr.giris >= "2024-01-01"]
    row["egit_R/i"] = round(egit.R.mean(), 3) if len(egit) else np.nan
    row["test_R/i"] = round(test.R.mean(), 3) if len(test) else np.nan
    row["test_isabet"] = round((test.R > 0).mean() * 100, 1) if len(test) else np.nan
    row["C_R"] = round(tr[tr.giris >= "2026-03-01"].R.sum(), 1)
    return row


# ------------------------------------------------------------------ aileler
def _hedef(e, s, tR):
    return e - tR * (s - e) if tR > 0 else np.full_like(e, np.nan)


def aile_pompa(g, x, rej, N=18, P=0.5, tepe_yas=6, dusus=0.05, tR=1.0, maks=30, rejim=None, fr=None, fon_min=None, lik=10e6):
    """Pompa sonmesi: son N mumda en dusukten tepeye >= P yukselis, tepe son 'tepe_yas' mum icinde,
    kapanis onceki 2 mumun en dusugunun altinda ve tepeden en az 'dusus' asagida."""
    h, l, c = g.h, g.l, g.c
    tepe = h.rolling(N).max()
    taban = l.rolling(N).min()
    tepe_ix = h.rolling(tepe_yas).max() >= tepe          # tepe yakin zamanda
    kir = c < l.shift(1).rolling(2).min()
    sart = (tepe / taban - 1 >= P) & tepe_ix & kir & (c <= tepe * (1 - dusus)) & (x.qv >= lik) & (x.yas >= 120)
    if rejim:
        sart &= rej[rejim].reindex(g.index, method="ffill").fillna(False).astype(bool)
    if fon_min is not None and fr is not None and len(fr):
        f3 = fr.rolling(3).mean().reindex(g.index, method="ffill")
        sart &= f3 >= fon_min
    ix = np.flatnonzero(sart.to_numpy())
    e = c.to_numpy()[ix]
    s = tepe.to_numpy()[ix] * 1.005
    return sim(g, ix, s, _hedef(e, s, tR), maks, fr)


def aile_tuzak(g, x, rej, R=80, m=6, tR=1.5, maks=30, rejim=None, fr=None, hacimli=False, lik=10e6):
    """Boga tuzagi: son m mum icinde 80 mumluk tepenin ustune kapanis oldu, simdi o seviyenin altina geri kapandi."""
    h, c, v = g.h.to_numpy(float), g.c.to_numpy(float), g.v.to_numpy(float)
    hh = g.h.rolling(R).max().shift(1).to_numpy()
    va = x.vavg.to_numpy()
    q = x.qv.to_numpy()
    rj = rej[rejim].reindex(g.index, method="ffill").fillna(False).to_numpy(bool) if rejim else np.ones(len(c), bool)
    ix, st = [], []
    son_k, seviye, tepe = -10**9, np.nan, np.nan
    for i in range(R + 1, len(c)):
        if c[i] > hh[i] and (not hacimli or v[i] >= 2 * va[i]):
            if i - son_k > m:
                seviye = hh[i]; tepe = h[i]
            son_k = i
            tepe = max(tepe, h[i])
            continue
        if i - son_k <= m and not np.isnan(seviye):
            tepe = max(tepe, h[i])
            if c[i] < seviye and q[i] >= lik and rj[i]:
                ix.append(i); st.append(tepe * 1.003)
                seviye = np.nan
    ix = np.array(ix, int); st = np.array(st, float)
    e = c[ix] if len(ix) else np.array([])
    return sim(g, ix, st, _hedef(e, st, tR), maks, fr)


def aile_kirilim(g, x, rej, R=80, vm=2.0, stop_atr=1.5, tR=2.0, maks=30, rejim="ayi50", fr=None, lik=10e6, iz_k=0.0):
    """Destek kirilimi: kapanis 80 mumluk dibin altinda, hacim >= vm x ortalama, BTC rejim filtresi."""
    c = g.c
    ll = g.l.rolling(R).min().shift(1)
    sart = (c < ll - 0.05 * x.atr) & (g.v >= vm * x.vavg) & (x.qv >= lik) & (x.yas >= 120)
    if rejim:
        sart &= rej[rejim].reindex(g.index, method="ffill").fillna(False).astype(bool)
    ix = np.flatnonzero(sart.to_numpy())
    e = c.to_numpy()[ix]
    s = e + stop_atr * x.atr.to_numpy()[ix]
    return sim(g, ix, s, _hedef(e, s, tR), maks, fr, iz_atr=x.atr.to_numpy(), iz_k=iz_k)


def aile_listeleme(g, onboard, gun=3, maks_gun=30, stop_k=1.0, fr=None):
    """Yeni listeleme: listelemeden 'gun' gun sonra kapanista short, stop = o ana kadarki en yuksek x (1+stop_k)."""
    if onboard is None or g.index[0] < pd.Timestamp("2020-01-01") or (g.index[0] - onboard) > pd.Timedelta(days=2):
        return []
    i = 6 * gun
    if i >= len(g) - 1:
        return []
    tepe = g.h.iloc[: i + 1].max()
    s = np.array([max(tepe, g.c.iloc[i] * (1 + stop_k))])
    return sim(g, np.array([i]), s, np.array([np.nan]), 6 * maks_gun, fr)


def gunluk(g):
    d = g.resample("1D").agg({"o": "first", "h": "max", "l": "min", "c": "last", "v": "sum"}).dropna()
    return d


def sepet_secim(DG: dict, rej, LB=30, K=5, lik=20e6, rejim="ayi50", min_yas=120, bazli="ham"):
    """Her gun kapanisinda: likit coinler arasinda son LB gun getirisi en dusuk K coin (rejim uygunsa)."""
    C = pd.DataFrame({s: d.c for s, d in DG.items()}).sort_index()
    QV = pd.DataFrame({s: (d.c * d.v).rolling(30, min_periods=10).median() for s, d in DG.items()}).reindex(C.index)
    yas = C.notna().cumsum()
    r = C.pct_change(LB)
    if bazli == "btc":
        r = r.sub(C["BTCUSDT"].pct_change(LB), axis=0)
    uygun = (QV >= lik) & (yas >= min_yas) & r.notna()
    uygun["BTCUSDT"] = False
    sira = r.where(uygun).rank(axis=1, ascending=True)
    sec = sira <= K
    if rejim:
        rj = rej[rejim].shift(-1).reindex(C.index).fillna(False).astype(bool)   # rej zaten 1 gun kaydirildi; bugunun kapanisi
        sec = sec & rj.to_numpy()[:, None]
    return sec


def direnc_olaylari(g, x, L=120, p=3, band=0.3, yak=0.25, maks=30, tRs=(0.5, 0.75, 1.0, 1.5, 2.0), stop_buf=0.3,
                    fr=None, lik=10e6, aralik=6):
    """Guclu dirence (onceki pivot tepeler) yaklasip altinda kapanan mumlar: genis sinyal + ozellikler + coklu hedef sonucu.
    Direnc: son L mum icindeki (en yeni 'p'+3 mum haric) en yuksek pivot tepe; 'dokunus' = o seviyenin band*ATR yakinindaki pivot sayisi.
    Sinyal: mumun tepesi direncin yak*ATR yakininda/ustunde, kapanis direncin altinda ve kirmizi mum."""
    o, h, l, c, v = (g[k].to_numpy(float) for k in "ohlcv")
    atr = x.atr.to_numpy(); va = x.vavg.to_numpy(); q = x.qv.to_numpy()
    n = len(c)
    hs = pd.Series(h)
    piv = (hs == hs.rolling(2 * p + 1, center=True).max()).to_numpy()   # i'de pivot; i+p'de bilinir
    ema200 = pd.Series(c).ewm(span=200, adjust=False).mean().to_numpy()
    ema50 = pd.Series(c).ewm(span=50, adjust=False).mean().to_numpy()
    T = g.index
    fon = fr.reindex(T, method="ffill").to_numpy() if fr is not None and len(fr) else np.full(n, np.nan)
    rows = []
    son = -10**9
    piv_ix = np.flatnonzero(piv)
    for i in range(L + 10, n - 1):
        if q[i] < lik or i - son < aralik:
            continue
        a = atr[i]
        if not (a > 0):
            continue
        # bilinen pivotlar: indeks <= i - p, ve [i-L, i-p-3] araliginda (en yeni tepeler haric)
        lo_, hi_ = i - L, i - p - 3
        k0, k1 = np.searchsorted(piv_ix, lo_), np.searchsorted(piv_ix, hi_, side="right")
        pv = piv_ix[k0:k1]
        if len(pv) == 0:
            continue
        R = h[pv].max()
        if np.nanmax(c[pv[0]:i]) > R:      # direnc kapanisla kirilmis olmamali (araliktaki kapanislar)
            continue
        if not (h[i] >= R - yak * a and c[i] < R and c[i] < o[i]):
            continue
        dokunus = int(((h[pv] >= R - band * a)).sum())
        st = max(R, h[i]) + stop_buf * a
        e = c[i]
        risk = (st - e) / e
        if risk < 0.004 or risk > 0.25:
            continue
        # sonuc: her hedef icin
        Hj = h[i + 1:i + 1 + maks]; Lj = l[i + 1:i + 1 + maks]; Cj = c[i + 1:i + 1 + maks]
        stop_bar = np.flatnonzero(Hj >= st)
        sb = stop_bar[0] if len(stop_bar) else 10**9
        row = {"giris": T[i], "e": e, "risk": risk, "R_lev": R, "dokunus": dokunus,
               "vor3": v[i - 2:i + 1].mean() / va[i] if va[i] > 0 else np.nan,
               "vor6": v[i - 5:i + 1].mean() / va[i] if va[i] > 0 else np.nan,
               "vsig": v[i] / va[i] if va[i] > 0 else np.nan,
               "ema200": c[i] / ema200[i] - 1, "ema50": c[i] / ema50[i] - 1,
               "ralli": (h[i] - l[i - 12:i + 1].min()) / a, "fitil": (h[i] - max(o[i], c[i])) / max(h[i] - l[i], 1e-12),
               "atrp": a / c[i], "fon": fon[i], "yas_piv": i - pv[np.argmax(h[pv])], "qv": q[i]}
        for tR in tRs:
            tg = e - tR * (st - e)
            tb = np.flatnonzero(Lj <= tg)
            tb_ = tb[0] if len(tb) else 10**9
            if sb <= tb_ and sb < 10**9:
                j = sb; cik = st
            elif tb_ < 10**9:
                j = tb_; cik = tg
            else:
                j = len(Cj) - 1; cik = Cj[-1] if len(Cj) else e
            fz = 0.0
            if fr is not None and len(fr):
                fz = fr[(fr.index > T[i]) & (fr.index <= T[min(n - 1, i + 1 + j)])].sum()
            row[f"R{tR}"] = ((e - cik) / e - MALIYET + fz) / risk
            row[f"c{tR}"] = T[min(n - 1, i + 1 + j)]
        rows.append(row)
        son = i
    return rows


def retest_olaylari(g, x, R_=80, vm=1.5, min_bar=2, maks_bek=30, yak=0.2, maks=30, tRs=(0.5, 0.75, 1.0, 1.5, 2.0),
                    stop_buf=0.3, fr=None, lik=10e6, teyit=False):
    """Kirilan destek direnc olur: kapanis 80 mumluk dibin altina (hacimli) -> sonraki min_bar..maks_bek mum icinde
    fiyat o seviyeye geri yukselir (tepe seviyenin yak*ATR yakininda), seviyenin altinda kirmizi kapanir -> short."""
    o, h, l, c, v = (g[k].to_numpy(float) for k in "ohlcv")
    atr = x.atr.to_numpy(); va = x.vavg.to_numpy(); q = x.qv.to_numpy()
    ll = g.l.rolling(R_).min().shift(1).to_numpy()
    ema200 = pd.Series(c).ewm(span=200, adjust=False).mean().to_numpy()
    T = g.index; n = len(c)
    rows = []
    k = -1; sev = np.nan; dip = np.nan; kir_v = np.nan
    i = R_ + 1
    while i < n - 1:
        if np.isnan(sev):
            if c[i] < ll[i] - 0.05 * atr[i] and v[i] >= vm * va[i] and q[i] >= lik:
                k = i; sev = ll[i]; dip = l[i]; kir_v = v[i] / va[i]
            i += 1
            continue
        a = atr[i]
        if i - k > maks_bek or c[i] > sev + 0.5 * a:        # zaman doldu veya seviye geri alindi
            sev = np.nan
            continue
        dip = min(dip, l[i])
        if i - k >= min_bar and h[i] >= sev - yak * a and c[i] < sev and c[i] < o[i] and q[i] >= lik:
            st = max(sev, h[i]) + stop_buf * a
            sinyal_i = i
            if teyit:          # bir sonraki mum, ret mumunun dibinin altinda kapanirsa gir
                if i + 1 >= n - 1 or h[i + 1] >= st or not (c[i + 1] < l[i]):
                    sev = np.nan; i += 1; continue
                i = i + 1
            e = c[i]; risk = (st - e) / e
            if 0.004 <= risk <= 0.25:
                Hj = h[i + 1:i + 1 + maks]; Lj = l[i + 1:i + 1 + maks]; Cj = c[i + 1:i + 1 + maks]
                sbl = np.flatnonzero(Hj >= st); sb = sbl[0] if len(sbl) else 10**9
                si = sinyal_i
                row = {"giris": T[i], "e": e, "risk": risk, "bekle": si - k, "kir_v": kir_v,
                       "vor3": v[si - 2:si + 1].mean() / va[si], "vsig": v[si] / va[si],
                       "kirmizi3": int((c[si - 2:si + 1] < o[si - 2:si + 1]).sum()),
                       "sev": sev, "k_ix": k, "si_ix": si,
                       "derin": (sev - dip) / a, "ema200": c[i] / ema200[i] - 1, "atrp": a / c[i],
                       "fitil": (h[i] - max(o[i], c[i])) / max(h[i] - l[i], 1e-12), "qv": q[i],
                       "dip_hedef": (e - dip) / (st - e)}
                for tR in tRs:
                    tg = e - tR * (st - e)
                    tbl = np.flatnonzero(Lj <= tg); tb = tbl[0] if len(tbl) else 10**9
                    if sb <= tb and sb < 10**9:
                        j, cik = sb, st
                    elif tb < 10**9:
                        j, cik = tb, tg
                    else:
                        j, cik = len(Cj) - 1, (Cj[-1] if len(Cj) else e)
                    fz = fr[(fr.index > T[i]) & (fr.index <= T[min(n - 1, i + 1 + j)])].sum() if fr is not None and len(fr) else 0.0
                    row[f"R{tR}"] = ((e - cik) / e - MALIYET + fz) / risk
                    row[f"c{tR}"] = T[min(n - 1, i + 1 + j)]
                rows.append(row)
            sev = np.nan          # seviye basina tek retest islemi
        i += 1
    return rows
