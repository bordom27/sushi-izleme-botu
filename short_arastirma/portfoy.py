import numpy as np, pandas as pd


def portfoy(tr, K=10, risk=0.005, oncelik=None, bas="2020-01-01"):
    """Ayni anda en fazla K acik islem; sinyal sirasi giris zamani (ayni anda: oncelik kolonu buyuk once)."""
    t = tr[tr.giris >= bas].copy()
    t["_o"] = t[oncelik] if oncelik else 0.0
    t = t.sort_values(["giris", "_o"], ascending=[True, False])
    acik = []  # cikis zamanlari
    alinan = []
    for r in t.itertuples():
        acik = [c for c in acik if c > r.giris]
        if len(acik) >= K:
            continue
        acik.append(r.cikis)
        alinan.append(r.Index)
    a = t.loc[alinan].sort_values("cikis")
    # sabit risk (bilesik degil): getiri = risk * R, cikista realize
    gun = (a.set_index("cikis").R * risk).resample("1D").sum()
    gun = gun.reindex(pd.date_range(bas, gun.index.max(), freq="1D"), fill_value=0.0)
    eq = (1 + gun).cumprod()
    yil = (eq.index[-1] - eq.index[0]).days / 365
    cagr = eq.iloc[-1] ** (1 / yil) - 1
    dd = (1 - eq / eq.cummax()).max()
    ay = (1 + gun).resample("ME").prod() - 1
    sharpe = ay.mean() / ay.std() * np.sqrt(12) if ay.std() > 0 else np.nan
    yy = a.groupby(a.giris.dt.year).agg(n=("R", "size"), w=("R", lambda x: (x > 0).mean() * 100), R=("R", "sum"))
    yg = (1 + gun).groupby(gun.index.year).prod() - 1
    return {"alinan": len(a), "isabet": round((a.R > 0).mean() * 100, 1), "R": round(a.R.sum(), 1),
            "yillik%": round(cagr * 100, 1), "maxDD%": round(dd * 100, 1), "sharpe": round(sharpe, 2),
            "yillar": " ".join(f"{y}:{int(r.n)}/%{r.w:.0f}/{yg.get(y, 0)*100:+.0f}%" for y, r in yy.iterrows()),
            "C_R": round(a[a.giris >= "2026-03-01"].R.sum(), 1)}, a
