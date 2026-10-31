"""
Binance duyuru olay testi (1 saatlik vadeli veri 2024-01..2026-10, maliyet %0.2 + funding).
Giris: duyurudan sonraki ilk tam saatin acilisi (gercekci gecikme <= 60 dk). 'kacan' = duyuru oncesi saat acilisindan girise hareket.
"""
import glob, sys
import numpy as np, pandas as pd

MALIYET = 0.002
H = [1, 4, 12, 24, 72, 168, 336]


def yukle():
    K = pd.concat([pd.read_csv(f) for f in sorted(glob.glob("arastirma_cikti/dok1h/k1h_*.csv.gz"))], ignore_index=True)
    u = "s" if K.t.max() < 1e11 else "ms" if K.t.max() < 1e14 else "us"
    K["t"] = pd.to_datetime(K.t, unit=u)
    K["t"] = K.t.astype("datetime64[s]")
    D = {s: g.drop_duplicates("t").sort_values("t").set_index("t")[["o", "h", "l", "c"]] for s, g in K.groupby("symbol")}
    F = pd.concat([pd.read_csv(f) for f in glob.glob("arastirma_cikti/dok/fund_*.csv.gz")], ignore_index=True)
    F["t"] = pd.to_datetime(F.t, unit="ms")
    FR = {s: g.set_index("t").fr.sort_index() for s, g in F.groupby("symbol")}
    return D, FR


def olcum(D, FR, O):
    btc = D["BTCUSDT"]
    rows = []
    for _, e in O.iterrows():
        g = D.get(e.symbol)
        if g is None:
            continue
        a = pd.Timestamp(e.zaman).floor("s").as_unit("s")
        T = g.index
        i0 = T.searchsorted(a.floor("h") + pd.Timedelta(hours=1))
        if e.tur == "vadeli_acilis":
            i0 = T.searchsorted(a)                         # sozlesme acilisindan sonraki ilk mum
            if i0 >= len(T) or T[i0] - a > pd.Timedelta(days=3):
                continue
        else:
            if i0 >= len(T) or i0 < 48 or T[i0] - a > pd.Timedelta(hours=2):
                continue
        o, h, l, c = (g[k].to_numpy(float) for k in "ohlc")
        e0 = o[i0]
        r = {"zaman": a, "tur": e.tur, "symbol": e.symbol, "giris_t": T[i0], "giris": e0,
             "kacan": e0 / o[i0 - 1] - 1 if e.tur != "vadeli_acilis" else np.nan,
             "once7g": e0 / c[max(0, i0 - 168)] - 1 if e.tur != "vadeli_acilis" else np.nan}
        bi = btc.index.searchsorted(T[i0])
        for k in H:
            j = i0 + k - 1
            if j < len(c) and T[j] - T[i0] < pd.Timedelta(hours=k + 6):
                r[f"r{k}"] = c[j] / e0 - 1
                bj = bi + k - 1
                r[f"x{k}"] = r[f"r{k}"] - (btc.c.iloc[bj] / btc.o.iloc[bi] - 1 if bj < len(btc) else np.nan)
        for k in (24, 72):
            r[f"maks{k}"] = h[i0:i0 + k].max() / e0 - 1
            r[f"min{k}"] = l[i0:i0 + k].min() / e0 - 1
        rows.append(r)
    return pd.DataFrame(rows)


def islem(D, FR, ev, yon, tut, stop, giris_gecikme=0):
    """yon -1 short / +1 long; giris olay giris mumundan giris_gecikme saat sonra; stop: girise gore oran; tut: saat."""
    out = []
    for _, e in ev.iterrows():
        g = D[e.symbol]; T = g.index
        i = T.searchsorted(e.giris_t) + giris_gecikme
        if i >= len(T) - 1:
            continue
        o, h, l, c = (g[k].to_numpy(float) for k in "ohlc")
        p = o[i]; st = p * (1 - yon * stop)
        cik, j = None, min(len(c) - 1, i + tut - 1)
        for jj in range(i, min(len(c), i + tut)):
            if (yon < 0 and h[jj] >= st) or (yon > 0 and l[jj] <= st):
                cik, j = st, jj; break
        if cik is None:
            cik = c[j]
        fr = FR.get(e.symbol)
        fz = fr[(fr.index > T[i]) & (fr.index <= T[j])].sum() if fr is not None else 0.0
        out.append({"zaman": e.zaman, "symbol": e.symbol, "R": yon * (cik / p - 1) - MALIYET - yon * fz})
    return pd.DataFrame(out)


if __name__ == "__main__":
    D, FR = yukle()
    O = pd.read_csv("arastirma_cikti/duyuru/olaylar.csv", parse_dates=["zaman"]).dropna(subset=["symbol"])
    O = O[(O.zaman >= "2024-01-15") & (O.zaman <= "2026-10-08")]
    M = olcum(D, FR, O)
    M.to_pickle("/tmp/claude-0/-home-claude/13e3c372-aa7b-58c8-a204-e85020633022/scratchpad/duyuru_olcum.pkl")
    pd.set_option("display.width", 250)
    kol = ["kacan"] + [f"r{k}" for k in H]
    print("MEDYAN GETIRI (girise gore) ve olay sayisi")
    t = M.groupby("tur")[kol].median().mul(100).round(1)
    t.insert(0, "n", M.groupby("tur").size())
    print(t.to_string())
    print("\nBTC'ye gore fazla getiri (medyan, %)")
    print(M.groupby("tur")[[f"x{k}" for k in H]].median().mul(100).round(1).to_string())
    print("\nYUKSELME ORANI (getiri > 0)")
    print(M.groupby("tur")[[f"r{k}" for k in H]].apply(lambda x: (x > 0).mean()).round(2).to_string())
    print("\nOrtalama (aykiri etkisi) %")
    print(M.groupby("tur")[[f"r{k}" for k in H]].mean().mul(100).round(1).to_string())
