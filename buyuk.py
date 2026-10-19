"""
Buyuk adim arastirmasi (GitHub Actions'ta calisir):
  liste      : v6.6 4s islem listesi + giris anindaki piyasa ozellikleri (teshis icin)
  tf-<iv>    : ayni v6.6 sistemi baska zaman diliminde (1h, 2h, 6h, 8h, 12h, 1d)
  zar        : Zarattini/Pagani/Barbon (2025) tarzi gunluk trend sistemi (Donchian toplulugu,
               kanal ortasi iz suren stop, volatilite hedefli boyut), coklu varyasyon
Cikti: arastirma_cikti/buyuk_*.csv
"""
from __future__ import annotations

import multiprocessing as mp
import sys
import time

import numpy as np
import pandas as pd

import arastirma as A
import veri
from coin_listesi import COINLER

OUT = "arastirma_cikti"
GEN30 = ["BTCUSDT", "ETHUSDT", "SOLUSDT", "XRPUSDT", "BNBUSDT", "DOGEUSDT", "ADAUSDT", "TRXUSDT", "LINKUSDT",
         "AVAXUSDT", "SUIUSDT", "LTCUSDT", "NEARUSDT", "DOTUSDT", "UNIUSDT", "AAVEUSDT", "BCHUSDT", "ZECUSDT",
         "PEPEUSDT", "ENAUSDT", "TIAUSDT", "FILUSDT", "INJUSDT", "WLDUSDT", "TAOUSDT", "ARBUSDT", "OPUSDT",
         "APTUSDT", "HBARUSDT", "XLMUSDT"]
DON = [("A", "2024-07-01", "2025-06-30 23:59"), ("B", "2025-07-01", "2026-02-28 23:59"), ("C", "2026-03-01", None)]


def evren():
    tick = veri._get("/api/v3/ticker/24hr", {})
    haric = set(COINLER) | A.STOK_HARIC | {"USDCUSDT", "FDUSDUSDT", "TUSDUSDT", "DAIUSDT", "EURUSDT", "USDPUSDT",
                                           "RLUSDUSDT", "USD1USDT", "PYUSDUSDT", "AEURUSDT", "XUSDUSDT", "BFUSDUSDT",
                                           "WBTCUSDT", "WBETHUSDT", "BNSOLUSDT", "EURIUSDT", "USDEUSDT"}
    aday = [d for d in tick if d["symbol"].endswith("USDT") and d["symbol"] not in haric
            and not any(x in d["symbol"] for x in ("UP", "DOWN", "BULL", "BEAR"))]
    aday.sort(key=lambda d: float(d["quoteVolume"]), reverse=True)
    return list(COINLER) + [d["symbol"] for d in aday[:70]]


def genislik(data: dict, n=6, R=80) -> pd.Series:
    ku = {}
    for s_ in GEN30:
        if s_ not in data:
            continue
        df = data[s_][0]
        ix = pd.to_datetime(df["open_time"])
        h_ = df["high"].to_numpy(float); c_ = df["close"].to_numpy(float)
        hh = pd.Series(h_).rolling(R).max().shift(1).to_numpy()
        ok = np.arange(len(c_)) >= R
        ku[s_] = pd.Series(np.where(ok, (c_ > hh).astype(float), np.nan), index=ix)
    KU = pd.DataFrame(ku).fillna(0)
    return (KU.rolling(n, min_periods=1).max() > 0).sum(axis=1)


def b66(data):
    return dict(A._B3, ters_s=genislik(data), ters_max=0, vol_mult=2.5, use_fib=False,
                tp1_r=0.9, break_buf_atr=0.05, bc_atr=0.1, time_stop_min_r=0.8)


def ozet(tr, ad):
    row = {"ayar": ad}
    for dk, b_, e_ in DON:
        for kk, vv in A.metrik(tr, b_, e_).items():
            row[f"{dk}_{kk}"] = vv
    return row


# ------------------------------------------------------------------ Zarattini tarzi gunluk trend
def zar_sim(G: dict, LB=(5, 10, 20, 30, 60, 90, 150, 250, 360), top=20, hedef_vol=0.25, max_kaldirac=2.0,
            toplam_tavan=None, komisyon=0.001, bas="2024-07-01", sadece=None, bolen="top"):
    """G: sembol -> gunluk df. Gunluk getiri serisi dondurur (kapanista islem)."""
    kapan = pd.DataFrame({s: g.set_index("open_time")["close"] for s, g in G.items()}).sort_index()
    hacim = pd.DataFrame({s: g.set_index("open_time")["close"] * g.set_index("open_time")["volume"] for s, g in G.items()}).reindex(kapan.index)
    if sadece:
        kapan = kapan[[c for c in kapan.columns if c in sadece]]
        hacim = hacim[kapan.columns]
    ret = kapan.pct_change()
    sig = ret.rolling(90, min_periods=60).std() * np.sqrt(365)
    likid = hacim.rolling(30, min_periods=20).median()
    yas = kapan.notna().cumsum()
    uygun = (yas >= 365)
    rank = likid.where(uygun).rank(axis=1, ascending=False)
    secili = rank <= top
    # sinyaller
    toplam = pd.DataFrame(0.0, index=kapan.index, columns=kapan.columns)
    for L in LB:
        mx = kapan.rolling(L, min_periods=L).max()
        mn = kapan.rolling(L, min_periods=L).min()
        brk = kapan > mx.shift(1)
        orta = (mx + mn) / 2
        C = kapan.to_numpy(); B = brk.to_numpy(); O = orta.to_numpy()
        poz = np.zeros_like(C); stop = np.full(C.shape[1], np.nan); icinde = np.zeros(C.shape[1], bool)
        for t in range(C.shape[0]):
            for j in range(C.shape[1]):
                if np.isnan(C[t, j]):
                    icinde[j] = False
                    continue
                if icinde[j]:
                    if C[t, j] < stop[j]:
                        icinde[j] = False
                    else:
                        if not np.isnan(O[t, j]):
                            stop[j] = max(stop[j], O[t, j])
                elif B[t, j]:
                    icinde[j] = True
                    stop[j] = O[t, j]
                poz[t, j] = 1.0 if icinde[j] else 0.0
        toplam += poz
    sinyal = toplam / len(LB)
    olcek = (hedef_vol / sig).clip(upper=max_kaldirac)
    w = (sinyal * olcek).where(secili, 0.0).fillna(0.0)
    if bolen == "aktif":   # sermaye sadece trendde olan coinler arasinda bolunur
        n_ = (w > 0).sum(axis=1).clip(lower=1)
        w = w.div(n_, axis=0)
    else:
        w = w / top
    if toplam_tavan:
        s_ = w.sum(axis=1)
        w = w.div(np.maximum(s_ / toplam_tavan, 1.0), axis=0)
    gun_get = (w.shift(1) * ret).sum(axis=1)
    maliyet = w.diff().abs().sum(axis=1) * komisyon
    net = (gun_get - maliyet)
    net = net[net.index >= pd.Timestamp(bas) - pd.Timedelta(days=1)]
    maruz = w.sum(axis=1)
    return net, maruz


def zar_metrik(net: pd.Series, bas, bit=None):
    r = net[(net.index >= pd.Timestamp(bas)) & ((net.index <= pd.Timestamp(bit)) if bit else True)]
    if r.empty:
        return dict(getiri=np.nan, sharpe=np.nan, maxdd=np.nan)
    eq = (1 + r).cumprod()
    dd = (eq / eq.cummax() - 1).min()
    sh = r.mean() / r.std() * np.sqrt(365) if r.std() > 0 else np.nan
    return dict(getiri=round(100 * (eq.iloc[-1] - 1), 1), sharpe=round(sh, 2), maxdd=round(100 * dd, 1))


def main():
    mod = sys.argv[1]
    A.DATA["btc_d"] = veri.mumlar_onbellekli("BTCUSDT", "1d", "2019-06-01")
    liste = evren()
    if mod == "liste" or mod.startswith("tf-"):
        iv = "4h" if mod == "liste" else mod.split("-", 1)[1]
        A.DATA["btc_" + iv] = veri.mumlar_onbellekli("BTCUSDT", iv, A.VERI_BAS)
        A.DATA[iv] = A.yukle(liste, iv)
        prm = b66(A.DATA[iv])
        senaryo = [("v6.6", prm)]
        if iv != "4h":
            # cubuk sayisina bagli ayarlari 4 saate gore olcekle (ayni takvim suresi)
            sa = {"1h": 1, "2h": 2, "6h": 6, "8h": 8, "12h": 12, "1d": 24}[iv]
            f = 4 / sa
            senaryo.append(("v6.6 takvim olcekli", dict(prm, resistance_len=max(20, int(round(80 * f))),
                                                       time_stop_bars=max(5, int(round(20 * f))),
                                                       ters_s=genislik(A.DATA[iv], n=max(1, int(round(6 * f))), R=max(20, int(round(80 * f)))))))
        rows = []
        with mp.Pool(4) as hv:
            for ad, p in senaryo:
                tr = A.calistir(p, liste, iv, hv)
                rows.append(ozet(tr, f"{iv} {ad}"))
                if len(tr):
                    tr["tf"] = iv; tr["senaryo"] = ad
                    tr.drop(columns=[c for c in tr.columns if tr[c].dtype == object and c not in
                                     ("symbol", "tip", "kalite", "neden", "tf", "senaryo")], errors="ignore") \
                        .to_csv(f"{OUT}/buyuk_islem_{iv}_{ad.replace(' ', '_')}.csv.gz", index=False, compression="gzip")
                print(rows[-1], flush=True)
        pd.DataFrame(rows).to_csv(f"{OUT}/buyuk_{mod}.csv", index=False)
        if mod == "liste":
            # teshis icin gunluk kapanislar (BTC + evren)
            kap = {s: g[1].set_index("open_time")["close"] for s, g in A.DATA["4h"].items()}
            pd.DataFrame(kap).to_csv(f"{OUT}/buyuk_gunluk_kapanis.csv.gz", compression="gzip")
    elif mod == "btcf":
        iv = "4h"
        A.DATA["btc_4h"] = veri.mumlar_onbellekli("BTCUSDT", "4h", A.VERI_BAS)
        A.DATA[iv] = A.yukle(liste, iv)
        p = b66(A.DATA[iv])
        senaryo = [("SU ANKI v6.6", p),
                   ("BTC EMA50 filtresi kapali (iki yon)", dict(p, use_mkt=False)),
                   ("BTC EMA50 filtresi sadece long'da kapali", dict(p, mkt_long=False)),
                   ("BTC EMA50 filtresi sadece short'ta kapali", dict(p, mkt_short=False)),
                   ("long icin BTC>EMA200 kapali", dict(p, long_sart="Kapali")),
                   ("long'da tum BTC filtreleri kapali", dict(p, mkt_long=False, long_sart="Kapali")),
                   ("tum BTC filtreleri kapali", dict(p, use_mkt=False, long_sart="Kapali")),
                   ("tum BTC filtreleri + short genislik kapali", dict(p, use_mkt=False, long_sart="Kapali", ters_max=-1)),
                   ("BTC filtresi yerine coin kendi EMA200'u (long)", dict(p, mkt_long=False, long_sart="Coin > EMA200"))]
        rows = []
        with mp.Pool(4) as hv:
            for ad, prm in senaryo:
                tr = A.calistir(prm, liste, iv, hv)
                rows.append(ozet(tr, ad)); print(rows[-1], flush=True)
        pd.DataFrame(rows).to_csv(f"{OUT}/buyuk_btcf.csv", index=False)
    elif mod.startswith("uzun"):
        # buyuk orneklem: 2020'den bugune (2021 boga, 2022 ayi, 2023 toparlanma dahil)
        A.VERI_BAS = "2019-09-01"
        A.IS_BAS = "2020-01-01"
        iv = "4h"
        A.DATA["btc_4h"] = veri.mumlar_onbellekli("BTCUSDT", "4h", A.VERI_BAS)
        A.DATA[iv] = A.yukle(liste, iv)
        print("coin", len(A.DATA[iv]), flush=True)
        p = b66(A.DATA[iv])
        S = [("v6.6", p),
             ("v6.5 (eski ince ayar)", dict(p, tp1_r=0.8, break_buf_atr=0.1, bc_atr=0.15, time_stop_min_r=0.5)),
             ("RSI ust siniri yok", dict(p, def_rsi_max=101.0, use_auto_params=False)),
             ("RSI ust 75", dict(p, def_rsi_max=75.0, use_auto_params=False)),
             ("tum BTC filtreleri kapali", dict(p, use_mkt=False, long_sart="Kapali")),
             ("BTC EMA50 sadece short'ta kapali", dict(p, mkt_short=False)),
             ("short genislik filtresi kapali", dict(p, ters_max=-1)),
             ("hacim 2.0x", dict(p, vol_mult=2.0)),
             ("hacim 3.0x", dict(p, vol_mult=3.0)),
             ("coklu kanal 240", dict(p, ek_R=240)),
             ("fib giris filtresi acik", dict(p, use_fib=True)),
             ("basarisiz kirilim cikisi yok", dict(p, basarisiz_cikis=False)),
             ("TP1'de %70 kapat", dict(p, tp1_pct=70.0)),
             ("direnc 60 mum", dict(p, resistance_len=60)),
             ("direnc 120 mum", dict(p, resistance_len=120)),
             ("min yer 0.8R", dict(p, min_room_r=0.8))]
        K = 4
        parca = int(mod.split("-")[1])
        senaryo = S[:1] + S[1 + parca::K]
        DON2 = [("Y2020", "2020-01-01", "2020-12-31 23:59"), ("Y2021", "2021-01-01", "2021-12-31 23:59"),
                ("Y2022", "2022-01-01", "2022-12-31 23:59"), ("Y2023", "2023-01-01", "2023-12-31 23:59"),
                ("Y24a", "2024-01-01", "2024-06-30 23:59")] + DON + [("TUM", "2020-01-01", None)]
        rows = []
        with mp.Pool(4) as hv:
            for ad, prm in senaryo:
                tr = A.calistir(prm, liste, iv, hv)
                row = {"ayar": ad}
                for dk, b_, e_ in DON2:
                    for kk, vv in A.metrik(tr, b_, e_).items():
                        row[f"{dk}_{kk}"] = vv
                rows.append(row); print(row, flush=True)
                if ad == "v6.6" and parca == 0 and len(tr):
                    tr.drop(columns=[c for c in tr.columns if tr[c].dtype == object and c not in
                                     ("symbol", "tip", "kalite", "neden")], errors="ignore") \
                        .to_csv(f"{OUT}/buyuk_uzun_islem_v66.csv.gz", index=False, compression="gzip")
        pd.DataFrame(rows).to_csv(f"{OUT}/buyuk_{mod}.csv", index=False)
        # coinlerin veri baslangici (orneklemin hangi yilda kac coin icerdigi)
        bas = {s_: str(d[0]["open_time"].iloc[0])[:10] for s_, d in A.DATA[iv].items()}
        pd.Series(bas).to_csv(f"{OUT}/buyuk_uzun_coin_baslangic.csv")
    elif mod == "zar-gercek":
        import zarattini as Z
        G = {}
        for s_ in liste:
            try:
                g = veri.mumlar_onbellekli(s_, "1d", "2019-06-01")
                if len(g) > 400:
                    G[s_] = g[["open_time", "close", "volume"]].copy()
            except Exception as exc:
                print("veri yok", s_, exc, flush=True)
            time.sleep(0.05)
        kap, hac = Z.tablolar(G)
        w = Z.hedef_agirlik(kap, hac)
        DONZ = [("Y2020", "2020-01-01", "2020-12-31"), ("Y2021", "2021-01-01", "2021-12-31"),
                ("Y2022", "2022-01-01", "2022-12-31"), ("Y2023", "2023-01-01", "2023-12-31"),
                ("Y24a", "2024-01-01", "2024-06-30")] + DON + [("TUM", "2020-01-01", None)]
        sen = [("ideal: kapanista, her gun tam uyum", 0, 0.0, 0.0, 0.001),
               ("1 gun gecikme", 1, 0.0, 0.0, 0.001),
               ("1 gun gecikme + bant %0.5", 1, 0.005, 0.0, 0.001),
               ("1 gun gecikme + bant %1", 1, 0.01, 0.0, 0.001),
               ("1 gun gecikme + bant %2", 1, 0.02, 0.0, 0.001),
               ("1 gun gecikme + bant %0.5 veya %25", 1, 0.005, 0.25, 0.001),
               ("1 gun gecikme + bant %1 veya %33", 1, 0.01, 0.33, 0.001),
               ("1 gun gecikme + bant %1 veya %50", 1, 0.01, 0.5, 0.001),
               ("1 gun gecikme + bant %1 veya %33, komisyon %0.2", 1, 0.01, 0.33, 0.002)]
        rows = []
        for ad, gc, b_, o_, kom in sen:
            H = Z.bantli(w, b_, o_)
            r = Z.getiri(H, kap, gecikme=gc, komisyon=kom)
            d_ = (H.diff().abs() > 1e-12)
            d_ = d_[d_.index >= "2020-01-01"]
            row = {"ayar": ad, "islem_gunu_orani": round(float((d_.sum(axis=1) > 0).mean()), 2),
                   "gunluk_ort_degisiklik": round(float(d_.sum(axis=1).mean()), 2),
                   "ort_maruziyet": round(float(H[H.index >= "2020-01-01"].sum(axis=1).mean()), 3),
                   "max_maruziyet": round(float(H[H.index >= "2020-01-01"].sum(axis=1).max()), 3),
                   "ort_coin": round(float((H[H.index >= "2020-01-01"] > 0).sum(axis=1).mean()), 1)}
            for dk, bb, ee in DONZ:
                for kk, vv in zar_metrik(r, bb, ee).items():
                    row[f"{dk}_{kk}"] = vv
            rows.append(row); print(row, flush=True)
        pd.DataFrame(rows).to_csv(f"{OUT}/buyuk_zar_gercek.csv", index=False)
        w.iloc[-5:].T.round(4).to_csv(f"{OUT}/buyuk_zar_son_agirlik.csv")
    elif mod == "zar-short":
        import zarattini as Z
        G = {}
        for s_ in liste:
            try:
                g = veri.mumlar_onbellekli(s_, "1d", "2019-06-01")
                if len(g) > 400:
                    G[s_] = g[["open_time", "close", "volume"]].copy()
            except Exception as exc:
                print("veri yok", s_, exc, flush=True)
            time.sleep(0.05)
        kap, hac = Z.tablolar(G)
        wL = Z.hedef_agirlik(kap, hac)
        wS = Z.hedef_agirlik(-kap, hac)        # ayna: dusus kirilimi + kanal ortasi stop (short)
        DONZ = [("Y2020", "2020-01-01", "2020-12-31"), ("Y2021", "2021-01-01", "2021-12-31"),
                ("Y2022", "2022-01-01", "2022-12-31"), ("Y2023", "2023-01-01", "2023-12-31"),
                ("Y24a", "2024-01-01", "2024-06-30")] + DON + [("TUM", "2020-01-01", None)]
        rows, ser = [], {}
        for ad, w in (("sadece LONG (simdiki)", wL), ("sadece SHORT", -wS), ("LONG + SHORT", wL - wS)):
            H = Z.bantli(w.abs(), 0.01, 0.33) * np.sign(w)
            r = Z.getiri(H, kap, gecikme=1, komisyon=0.001)
            row = {"ayar": ad}
            for dk, bb, ee in DONZ:
                for kk, vv in zar_metrik(r, bb, ee).items():
                    row[f"{dk}_{kk}"] = vv
            rows.append(row); ser[ad] = r; print(row, flush=True)
        pd.DataFrame(rows).to_csv(f"{OUT}/buyuk_zar_short.csv", index=False)
        pd.DataFrame(ser).to_csv(f"{OUT}/buyuk_zar_short_gunluk.csv.gz", compression="gzip")
    elif mod.startswith("zar"):
        G = {}
        for s in liste:
            try:
                g = veri.mumlar_onbellekli(s, "1d", "2019-06-01")
                if len(g) > 400:
                    G[s] = g[["open_time", "close", "volume"]].copy()
            except Exception as exc:
                print("veri yok", s, exc, flush=True)
            time.sleep(0.05)
        print("coin", len(G), flush=True)
        senaryo = [
            ("Zarattini temel (top20, vol %25, kaldirac<=2)", {}),
            ("kaldiracsiz (toplam pozisyon <= %100)", dict(toplam_tavan=1.0)),
            ("top10", dict(top=10)),
            ("top30", dict(top=30)),
            ("vol hedef %40", dict(hedef_vol=0.40)),
            ("vol hedef %40 kaldiracsiz", dict(hedef_vol=0.40, toplam_tavan=1.0)),
            ("kisa lookback (5-60)", dict(LB=(5, 10, 20, 30, 60))),
            ("uzun lookback (60-360)", dict(LB=(60, 90, 150, 250, 360))),
            ("sadece BTC+ETH", dict(top=2, sadece=["BTCUSDT", "ETHUSDT"])),
            ("tam yatirim: sermaye trenddeki coinlere bolunur (kaldiracsiz)", dict(bolen="aktif", toplam_tavan=1.0)),
            ("UZUN 2020+: Zarattini temel", dict(bas="2020-01-01")),
            ("UZUN 2020+: top10", dict(bas="2020-01-01", top=10)),
            ("tam yatirim, vol hedefsiz (esit agirlik, kaldiracsiz)", dict(bolen="aktif", toplam_tavan=1.0, hedef_vol=10.0, max_kaldirac=1.0)),
        ]
        DONZ = DON + [("T", "2024-07-01", None)]
        cikti = "buyuk_zar"
        if mod == "zar-uzun":
            senaryo = [x for x in senaryo if x[0].startswith("UZUN")]
            DONZ = [("Y2020", "2020-01-01", "2020-12-31"), ("Y2021", "2021-01-01", "2021-12-31"),
                    ("Y2022", "2022-01-01", "2022-12-31"), ("Y2023", "2023-01-01", "2023-12-31"),
                    ("Y24a", "2024-01-01", "2024-06-30")] + DON + [("TUM", "2020-01-01", None)]
            cikti = "buyuk_zar_uzun"
        rows, seriler = [], {}
        for ad, kw in senaryo:
            net, maruz = zar_sim(G, **kw)
            row = {"ayar": ad, "ort_maruziyet": round(maruz[maruz.index >= DONZ[0][1]].mean(), 2)}
            for dk, b_, e_ in DONZ:
                for kk, vv in zar_metrik(net, b_, e_).items():
                    row[f"{dk}_{kk}"] = vv
            rows.append(row); seriler[ad] = net
            print(row, flush=True)
        btc = A.DATA["btc_d"].set_index("open_time")["close"].pct_change()
        row = {"ayar": "BTC al-tut"}
        for dk, b_, e_ in DONZ:
            for kk, vv in zar_metrik(btc, b_, e_).items():
                row[f"{dk}_{kk}"] = vv
        rows.append(row); seriler["BTC"] = btc
        pd.DataFrame(rows).to_csv(f"{OUT}/{cikti}.csv", index=False)
        if mod == "zar-uzun":
            pd.DataFrame(seriler).to_csv(f"{OUT}/{cikti}_gunluk.csv.gz", compression="gzip")
            return
        pd.DataFrame(seriler).to_csv(f"{OUT}/buyuk_zar_gunluk.csv.gz", compression="gzip")


if __name__ == "__main__":
    main()
