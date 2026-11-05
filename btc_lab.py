"""
BTC laboratuvari: tum veri kaynaklarindan 1 saatlik ozellik tablosu + islem simulasyonu.
Kilitli donem: KILIT tarihinden sonrasi hicbir secimde kullanilmaz (sadece en sonda bir kez).
"""
from __future__ import annotations

import os

import numpy as np
import pandas as pd

D = "arastirma_cikti/btc"
KILIT = pd.Timestamp("2025-07-01")
EGIT_BIT = pd.Timestamp("2024-01-01")       # egitim: < 2024, dogrulama: 2024-01 .. 2025-06
MALIYET = 0.001                              # gidis-donus komisyon + kayma (BTC vadeli, taker)


def oku(ad, **kw):
    p = f"{D}/{ad}.csv.gz"
    if not os.path.exists(p):
        return None
    df = pd.read_csv(p, **kw)
    df["t"] = pd.to_datetime(df["t"])
    return df


def ema(s, n):
    return s.ewm(span=n, adjust=False).mean()


def rsi(c, n=14):
    d = c.diff()
    u = d.clip(lower=0).ewm(alpha=1 / n, adjust=False).mean()
    dn = (-d.clip(upper=0)).ewm(alpha=1 / n, adjust=False).mean()
    return 100 - 100 / (1 + u / dn)


def atr(g, n=14):
    tr = pd.concat([g.h - g.l, (g.h - g.c.shift()).abs(), (g.l - g.c.shift()).abs()], axis=1).max(axis=1)
    return tr.ewm(alpha=1 / n, adjust=False).mean()


def tf_ozellik(g: pd.DataFrame, on: str) -> pd.DataFrame:
    """Bir zaman diliminin teknik ozellikleri (sadece o mum kapandiktan sonra bilinir)."""
    c, h, l, v = g.c, g.h, g.l, g.v
    a = atr(g)
    f = pd.DataFrame(index=g.index)
    f["atrp"] = a / c
    for n in (20, 50, 200):
        f[f"e{n}"] = c / ema(c, n) - 1
    f["e20_50"] = ema(c, 20) / ema(c, 50) - 1
    f["e50_eg"] = ema(c, 50).pct_change(5)
    f["rsi"] = rsi(c)
    m = ema(c, 12) - ema(c, 26)
    f["macd_h"] = (m - ema(m, 9)) / c
    ma, sd = c.rolling(20).mean(), c.rolling(20).std()
    f["bb_z"] = (c - ma) / sd
    f["bb_w"] = 4 * sd / ma
    f["bb_w_ort"] = f.bb_w / f.bb_w.rolling(120).mean()             # sikisma
    for n in (1, 3, 12, 48):
        f[f"r{n}"] = c.pct_change(n)
    for n in (20, 50, 100):
        hh, ll = h.rolling(n).max().shift(1), l.rolling(n).min().shift(1)
        f[f"poz{n}"] = (c - ll) / (hh - ll)                          # kanal icindeki yer 0..1
        f[f"kir_ust{n}"] = (c > hh).astype(int)
        f[f"kir_alt{n}"] = (c < ll).astype(int)
    f["hacim_or"] = v / v.rolling(20).mean().shift(1)
    if "tb" in g:
        f["taker_al"] = g.tb / g.v                                    # agresif alici payi
        f["taker_al_ort"] = f.taker_al.rolling(12).mean()
    if "n" in g:
        f["islem_or"] = g.n / g.n.rolling(20).mean().shift(1)
    rng = (h - l).replace(0, np.nan)
    f["govde"] = (c - g.o) / rng
    f["ust_fitil"] = (h - np.maximum(c, g.o)) / rng
    f["alt_fitil"] = (np.minimum(c, g.o) - l) / rng
    yut = (c > g.o) & (g.o.shift() > c.shift()) & (c > g.o.shift()) & (g.o < c.shift())
    yut_s = (c < g.o) & (g.o.shift() < c.shift()) & (c < g.o.shift()) & (g.o > c.shift())
    f["yutan"] = yut.astype(int) - yut_s.astype(int)
    f["ic_mum"] = ((h < h.shift()) & (l > l.shift())).astype(int)
    f.columns = [f"{on}_{x}" for x in f.columns]
    return f


def htf_hizala(f_htf: pd.DataFrame, sure: str, idx: pd.DatetimeIndex) -> pd.DataFrame:
    """Ust zaman dilimi ozelligini, mum KAPANDIKTAN sonra kullanilacak sekilde 1s ekseninde hizala."""
    k = f_htf.copy()
    k.index = k.index + pd.Timedelta(sure)                           # kapanis zamani
    return k.reindex(idx.union(k.index)).sort_index().ffill().reindex(idx)


def tablo() -> pd.DataFrame:
    g1 = oku("perp_1h").set_index("t")
    idx = g1.index
    X = [tf_ozellik(g1, "h1")]
    # 1s ozellikler mum kapanisinda bilinir: 1s mumun acilisi t, kapanisi t+1h -> karar zamani t+1h
    X[0].index = X[0].index + pd.Timedelta("1h")
    karar = idx + pd.Timedelta("1h")
    X = [X[0].reindex(karar)]
    for ad, sure in (("perp_15m", "15min"), ("perp_4h", "4h"), ("perp_1d", "1D")):
        g = oku(ad)
        if g is None:
            continue
        g = g.set_index("t")
        on = {"perp_15m": "m15", "perp_4h": "h4", "perp_1d": "d1"}[ad]
        f = tf_ozellik(g, on)
        if on == "m15":
            f = f[[c for c in f.columns if any(k in c for k in ("_r1", "_r3", "_rsi", "_hacim_or", "_taker_al", "_bb_z"))]]
        X.append(htf_hizala(f, sure, karar))
    # haftalik ve aylik: en uzun gunluk gecmisten (spot 2017+), mum kapandiktan sonra kullanilir
    uz = oku("spot_1d_uzun")
    if uz is not None:
        uz = uz.set_index("t")[["o", "h", "l", "c", "v"]]
        agg = {"o": "first", "h": "max", "l": "min", "c": "last", "v": "sum"}
        w = uz.resample("W-MON", label="left", closed="left").agg(agg).dropna()
        fw = tf_ozellik(w, "w1")
        fw.index = fw.index + pd.Timedelta("7D")
        X.append(fw.reindex(karar.union(fw.index)).sort_index().ffill().reindex(karar))
        mo = uz.resample("MS").agg(agg).dropna()
        fm = tf_ozellik(mo, "mo1")
        fm.index = fm.index + pd.offsets.MonthBegin(1)
        X.append(fm.reindex(karar.union(fm.index)).sort_index().ffill().reindex(karar))
    F = pd.concat(X, axis=1)
    # spot-vadeli farki, ETH
    sp = oku("spot_1h")
    if sp is not None:
        sp = sp.set_index("t").c
        sp.index = sp.index + pd.Timedelta("1h")
        F["baz"] = (g1.c.set_axis(karar) / sp.reindex(karar) - 1)
    eth = oku("eth_perp_1h")
    if eth is not None:
        e = eth.set_index("t").c
        e.index = e.index + pd.Timedelta("1h")
        oran = e.reindex(karar) / g1.c.set_axis(karar)
        F["ethbtc_r24"] = oran.pct_change(24)
        F["ethbtc_r168"] = oran.pct_change(168)
    # coinbase primi (ABD alicilari / balina izi)
    cb = oku("coinbase_1h")
    if cb is not None:
        cbc = cb.set_index("t").c
        cbc.index = cbc.index + pd.Timedelta("1h")
        prem = cbc.reindex(karar) / sp.reindex(karar) - 1 if sp is not None else None
        if prem is not None:
            F["cb_prem"] = prem
            F["cb_prem_24"] = prem.rolling(24).mean()
            F["cb_prem_d"] = prem - prem.rolling(168).mean()
    # funding
    fu = oku("funding")
    if fu is not None:
        fr = fu.set_index("t").fr
        F["fund"] = fr.reindex(karar.union(fr.index)).sort_index().ffill().reindex(karar)
        F["fund_ort7"] = fr.rolling(21).mean().reindex(karar.union(fr.index)).sort_index().ffill().reindex(karar)
    # metrikler (5 dk): OI, top trader, hesap L/S, taker oran
    me = oku("metrics_5m")
    if me is not None:
        me = me.set_index("t").sort_index()
        me.index = me.index + pd.Timedelta("5min")
        sec = {c: c for c in me.columns if c not in ("t",)}
        m1 = me.resample("1h", label="right", closed="right").last()[list(sec)]
        m1 = m1.reindex(karar).ffill(limit=3)
        oi = m1.get("sum_open_interest_value", m1.get("sum_open_interest"))
        if oi is not None:
            F["oi_d24"] = oi.pct_change(24)
            F["oi_d4"] = oi.pct_change(4)
        for c in ("count_toptrader_long_short_ratio", "sum_toptrader_long_short_ratio", "count_long_short_ratio",
                  "sum_taker_long_short_vol_ratio"):
            if c in m1:
                F[c] = m1[c]
                F[c + "_d24"] = m1[c] - m1[c].rolling(24).mean()
    # korku endeksi (gunluk, 00:00 UTC'de yayinlanir -> o gun kullanilabilir)
    fg = oku("fng")
    if fg is not None:
        s = fg.set_index("t").fng
        s.index = s.index + pd.Timedelta("1h")
        F["fng"] = s.reindex(karar.union(s.index)).sort_index().ffill().reindex(karar)
        F["fng_d7"] = F.fng - F.fng.rolling(168).mean()
    st = oku("stablecoin")
    if st is not None:
        s = st.set_index("t").stable_usd
        s.index = s.index + pd.Timedelta("1D")
        s = s.reindex(karar.union(s.index)).sort_index().ffill().reindex(karar)
        F["stable_d30"] = s.pct_change(720)
    mk = oku("makro")
    if mk is not None:
        mk = mk.set_index("t").sort_index()
        mk.index = mk.index + pd.Timedelta("1D") + pd.Timedelta("21h")   # ABD kapanisi, ertesi gun bilinir (temkinli)
        mk = mk.reindex(karar.union(mk.index)).sort_index().ffill().reindex(karar)
        for c in mk.columns:
            if c in ("VIXCLS", "DGS10", "T10Y2Y", "DFF"):
                F[f"mk_{c}"] = mk[c]
                F[f"mk_{c}_d5"] = mk[c] - mk[c].shift(24 * 7)
            else:
                F[f"mk_{c}_r5"] = mk[c].pct_change(24 * 7)
                F[f"mk_{c}_e50"] = mk[c] / mk[c].rolling(24 * 70, min_periods=24 * 30).mean() - 1
    hb = oku("haber_gdelt")
    if hb is not None and len(hb):
        try:
            tc = [c for c in hb.columns if c.lower().startswith("date")][0]
            hb["t"] = pd.to_datetime(hb[tc])
            ton = hb[hb["mod"] == "timelinetone"].groupby("t").Value.mean()
            hac = hb[hb["mod"] == "timelinevolraw"].groupby("t").Value.sum()
            for ad, s in (("haber_ton", ton), ("haber_hacim", hac)):
                s.index = s.index + pd.Timedelta("1D")
                s = s.reindex(karar.union(s.index)).sort_index().ffill().reindex(karar)
                F[ad] = s
            F["haber_hacim_or"] = F.haber_hacim / F.haber_hacim.rolling(24 * 30).mean()
            F["haber_ton_d7"] = F.haber_ton - F.haber_ton.rolling(24 * 7).mean()
        except Exception as exc:
            print("haber hatasi", exc)
    def gunluk_ekle(s, gecikme="1D"):
        s = s.copy()
        s.index = s.index + pd.Timedelta(gecikme)
        s = s[~s.index.duplicated(keep="last")]
        return s.reindex(karar.union(s.index)).sort_index().ffill().reindex(karar)

    dv = oku("dvol")
    if dv is not None:
        s = dv.set_index("t").dvol
        s.index = s.index + pd.Timedelta("1h")
        s = s[~s.index.duplicated(keep="last")].reindex(karar).ffill(limit=6)
        F["dvol"] = s
        F["dvol_d7"] = s - s.rolling(168).mean()
        if "h1_atrp" in F:
            F["dvol_rv"] = s / (F.h1_atrp * 100 * np.sqrt(24 * 365))       # opsiyon beklentisi / gerceklesen oynaklik
    zc = oku("zincir")
    if zc is not None:
        zc = zc.set_index("t").sort_index()
        if "hash_rate" in zc:
            hr = zc.hash_rate
            F["hash_ribbon"] = gunluk_ekle(hr.rolling(30).mean() / hr.rolling(60).mean() - 1)
        for c in ("n_transactions", "n_unique_addresses", "transaction_fees_usd", "miners_revenue", "estimated_transaction_volume_usd"):
            if c in zc:
                F[f"z_{c}_d"] = gunluk_ekle(zc[c].rolling(7).mean() / zc[c].rolling(90).mean() - 1)
    km = oku("kimchi")
    if km is not None and sp is not None:
        km = km.set_index("t").sort_index()
        spd = sp.copy(); spd.index = spd.index - pd.Timedelta("1h")
        spd = spd.resample("1D").last()
        prem = km.krw_btc / km.usdkrw / spd.reindex(km.index) - 1
        F["kimchi"] = gunluk_ekle(prem)
        F["kimchi_d"] = gunluk_ekle(prem - prem.rolling(30).mean())
    bd = oku("btcdom_1h")
    if bd is not None:
        b = bd.set_index("t").c
        b.index = b.index + pd.Timedelta("1h")
        b = b[~b.index.duplicated()].reindex(karar).ffill(limit=3)
        F["btcdom_r24"] = b.pct_change(24)
        F["btcdom_r168"] = b.pct_change(168)
    pz = oku("piyasalar")
    if pz is not None:
        pz = pz.set_index("t").sort_index()
        pz = pz[~pz.index.duplicated(keep="last")]
        for a in ("altin", "dxy", "mstr", "cme"):
            if f"{a}_c" in pz:
                c_ = pz[f"{a}_c"].dropna()
                F[f"y_{a}_r5"] = gunluk_ekle(c_.pct_change(5), "1D21h")
        if "cme_c" in pz:
            # CME boslugu: son CME kapanisina gore fiyat farki (hafta sonu BTC hareketi)
            cme = pz.cme_c.dropna()
            F["cme_bosluk"] = g1.c.set_axis(karar) / gunluk_ekle(cme, "21h") - 1
    # takvim
    F["saat"] = karar.hour
    F["gun"] = karar.dayofweek
    F["hafta_sonu"] = (karar.dayofweek >= 5).astype(int)
    F["ay_sonu"] = (karar.days_in_month - karar.day <= 1).astype(int)
    # petrol
    pt = oku("petrol")
    if pt is not None:
        pt = pt.set_index("t").sort_index()
        pt = pt[~pt.index.duplicated(keep="last")]
        for c in ("wti", "brent"):
            if c in pt:
                s = pt[c].dropna()
                F[f"petrol_{c}_r5"] = gunluk_ekle(s.pct_change(5), "1D21h")
                F[f"petrol_{c}_r20"] = gunluk_ekle(s.pct_change(20), "1D21h")
                F[f"petrol_{c}_e50"] = gunluk_ekle(s / s.rolling(50).mean() - 1, "1D21h")
    # ETF akislari (gunluk, ABD kapanisindan sonra aciklanir)
    ef = oku("etf_akis")
    if ef is not None and "Total" in ef:
        s = ef.set_index("t").Total.astype(float)
        F["etf_akis"] = gunluk_ekle(s, "1D21h").fillna(0)
        F["etf_akis5"] = gunluk_ekle(s.rolling(5).sum(), "1D21h").fillna(0)
    # zincir ustu (Coin Metrics community)
    cm = oku("coinmetrics")
    if cm is not None:
        cm = cm.set_index("t").sort_index()
        for c in cm.columns:
            s = pd.to_numeric(cm[c], errors="coerce")
            if s.notna().sum() < 500:
                continue
            if any(k in c for k in ("MVRV", "NVT", "SER", "Vty")):
                F[f"cm_{c}"] = gunluk_ekle(s)
            else:
                F[f"cm_{c}_d"] = gunluk_ekle(s.rolling(7).mean() / s.rolling(90).mean() - 1)
    # likidasyonlar (COIN-M arsivi; 2023-06 .. 2024-10 arasi)
    lq = oku("likidasyon_cm")
    if lq is not None:
        lq = lq.set_index("t").sort_index()
        lq.index = lq.index + pd.Timedelta("1h")
        for c in lq.columns:
            F[f"{c}_24"] = lq[c].reindex(karar).fillna(0).rolling(24).sum().where(karar >= lq.index.min()).where(karar <= lq.index.max() + pd.Timedelta("1D"))
    # FOMC (karar gunu ABD saatiyle aksam; o gun ve +-gun mesafesi)
    fo = oku("fomc")
    if fo is not None:
        fd = sorted(fo.t)
        F["fomc_gun_once"] = [min([(d - t.normalize()).days for d in fd if d >= t.normalize()], default=99) for t in karar]
        F["fomc_gun_sonra"] = [min([(t.normalize() - d).days for d in fd if d < t.normalize()], default=99) for t in karar]
    # CFTC: CME kurumsal pozisyonlar (Sali verisi, Cuma aksami yayinlanir -> +3.5 gun gecikme)
    cf = oku("cftc")
    if cf is not None:
        cf = cf[cf.cftc_contract_market_code.astype(str) == "133741"].set_index("t").sort_index()
        for grup in ("asset_mgr", "lev_money", "dealer"):
            l_ = [c for c in cf.columns if c.startswith(grup) and "long" in c]
            s_ = [c for c in cf.columns if c.startswith(grup) and "short" in c]
            if l_ and s_:
                net = (cf[l_[0]] - cf[s_[0]]) / cf.open_interest_all
                F[f"cftc_{grup}_net"] = gunluk_ekle(net, "3D20h")
                F[f"cftc_{grup}_net_d"] = gunluk_ekle(net.diff(), "3D20h")
    # Hyperliquid basarili cuzdanlar: her an, O ANA KADAR kumulatif kari pozitif olan cuzdanlarin net BTC pozisyonu
    hf = oku("hl_fills")
    if hf is not None and len(hf):
        hf = hf.sort_values("t")
        hf["isaret"] = np.where(hf.side.astype(str).str.upper().isin(["B", "BUY"]), 1.0, -1.0)
        hf["poz"] = hf.startPosition + hf.isaret * hf.sz
        saat = hf.t.dt.ceil("1h")
        poz = hf.assign(s=saat).groupby(["s", "adres"]).poz.last().unstack()
        pnl = hf.assign(s=saat).groupby(["s", "adres"]).closedPnl.sum().unstack().fillna(0).cumsum()
        ix = karar[karar >= poz.index.min()]
        poz = poz.reindex(poz.index.union(ix)).sort_index().ffill().reindex(ix).fillna(0)
        pnl = pnl.reindex(pnl.index.union(ix)).sort_index().ffill().reindex(ix).fillna(0)
        basarili = pnl > 0
        notional = poz.abs().where(basarili).sum(axis=1)
        F["hl_net"] = (poz.where(basarili).sum(axis=1) / notional.replace(0, np.nan)).reindex(karar)
        aktif = (poz.abs() > 0) & basarili
        F["hl_long_oran"] = ((poz > 0) & basarili).sum(axis=1).div(aktif.sum(axis=1).replace(0, np.nan)).reindex(karar)
        F["hl_net_d24"] = F.hl_net - F.hl_net.shift(24)
    # ABD secimleri (baskanlik ve ara secim; Kasim'in ilk pazartesisinden sonraki sali)
    secim = {pd.Timestamp("2016-11-08"): 1, pd.Timestamp("2018-11-06"): 0, pd.Timestamp("2020-11-03"): 1,
             pd.Timestamp("2022-11-08"): 0, pd.Timestamp("2024-11-05"): 1, pd.Timestamp("2026-11-03"): 0}
    st_ = sorted(secim)
    F["secim_gun_sonra"] = [(t - max([s for s in st_ if s <= t], default=pd.Timestamp("2014-11-04"))).days for t in karar]
    F["secim_gun_once"] = [(min([s for s in st_ if s > t], default=pd.Timestamp("2028-11-07")) - t).days for t in karar]
    F["son_secim_baskanlik"] = [secim.get(max([s for s in st_ if s <= t], default=st_[0]), 0) for t in karar]
    halv = [pd.Timestamp("2020-05-11"), pd.Timestamp("2024-04-20")]
    F["halving_gun"] = [(t - max([h for h in halv if h <= t], default=pd.Timestamp("2016-07-09"))).days for t in karar]
    F.index.name = "karar"
    return F


def fiyat_1h():
    g = oku("perp_1h").set_index("t")
    return g


def sonuc(g: pd.DataFrame, yon: int, stop_atr: float, hedef_r: float, maks: int):
    """Her karar mumu icin: o kapanista yon'de girilse (stop = stop_atr*ATR, hedef = hedef_r*risk) sonuc R'si.
    Ayni mumda stop ve hedef ise stop sayilir. Vektor dondurur (karar zamanina hizali)."""
    o, h, l, c = (g[k].to_numpy(float) for k in "ohlc")
    a = atr(g).to_numpy()
    n = len(c)
    R = np.full(n, np.nan)
    for i in range(n - 1):
        e = c[i]
        r = stop_atr * a[i]
        if not r > 0:
            continue
        st = e - yon * r
        tg = e + yon * hedef_r * r
        sonucR = None
        for j in range(i + 1, min(n, i + 1 + maks)):
            if (yon == 1 and l[j] <= st) or (yon == -1 and h[j] >= st):
                sonucR = -1.0
                break
            if (yon == 1 and h[j] >= tg) or (yon == -1 and l[j] <= tg):
                sonucR = hedef_r
                break
        if sonucR is None:
            j = min(n - 1, i + maks)
            sonucR = yon * (c[j] - e) / r
        R[i] = sonucR - MALIYET * e / r
    return pd.Series(R, index=g.index + pd.Timedelta("1h"))
