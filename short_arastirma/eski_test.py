"""
K69 SHORT - eski donem testi (2013 -> 2019-08, spot veri). veri_eski.py ciktisi: arastirma_cikti/eski/*.csv.gz
Kaynak onceligi (ayni coin, ayni mum): Binance USDT > Binance BTC paritesi (BTCUSDT ile dolara) > Bitfinex USD > Poloniex.
BTC: Bitfinex BTCUSD (2013-2017) + Binance BTCUSDT (2017-08+).
Spot short: funding yok (margin faizi hesaba katilmadi), maliyet %0.2. Sinyaller 2019-09-01 oncesi (sonrasi vadeli veriyle olculdu).
Cikti: SP/eski_dokunus.pkl (gelistir2 ile ayni kolonlar) + ozet.
Kullanim: SP=... python short_arastirma/eski_test.py
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
import short_arastirma.gelistir2 as G                                    # noqa: E402

SP = os.environ.get("SP", "/tmp")
BITIS = pd.Timestamp("2019-09-01")


def yukle():
    parts = []
    for f in sorted(glob.glob("arastirma_cikti/eski/*.csv.gz")):
        d = pd.read_csv(f)
        kaynak = os.path.basename(f).split("_")[0].split(".")[0]
        d["kaynak"] = kaynak
        parts.append(d)
    K = pd.concat(parts, ignore_index=True)
    K["t"] = pd.to_datetime(K["t"], unit="s")
    # BTC/USD serisi: Binance BTCUSDT, oncesi Bitfinex
    bb = K[(K.kaynak == "binance") & (K.symbol == "BTCUSDT")].set_index("t").c
    bf = K[(K.kaynak == "bitfinex") & (K.symbol == "BTCUSDT")].set_index("t").c
    pb = K[(K.kaynak == "poloniex") & (K.symbol == "BTCUSDT")].set_index("t").c
    btc = pd.concat([bb, bf[~bf.index.isin(bb.index)], pb[~pb.index.isin(bb.index.union(bf.index))]]).sort_index()
    btc = btc[~btc.index.duplicated()]
    # BTC paritelerini dolara cevir
    m = K.quote == "BTC"
    k = K.t[m].map(btc)
    for c in "ohlc":
        K.loc[m, c] = K.loc[m, c] * k
    K = K[K[["o", "h", "l", "c"]].notna().all(axis=1)]
    K["sym"] = np.where(K.quote == "BTC", K.symbol.str.replace(r"BTC$", "USDT", regex=True), K.symbol)
    K = K[K.sym != "BTCUSDT"].copy() if False else K
    oncelik = {("binance", "USDT"): 0, ("binance", "BTC"): 1, ("bitfinex", "USD"): 2, ("poloniex", "USDT"): 3, ("poloniex", "BTC"): 4}
    K["onc"] = [oncelik.get((a, b), 9) for a, b in zip(K.kaynak, K.quote)]
    # BTC'nin kendisi BTC paritesinden gelemez
    K = K[~((K.sym == "BTCUSDT") & (K.quote == "BTC"))]
    D = {}
    for s, g in K.sort_values(["sym", "t", "onc"]).groupby("sym", sort=True):
        g = g.drop_duplicates("t").set_index("t")[["o", "h", "l", "c", "v"]].astype(float)
        g = g[(g.v > 0) & (g.index < BITIS + pd.Timedelta(days=40))]
        if len(g) < 250:
            continue
        D[s] = g
    return D, btc


if __name__ == "__main__":
    pk = os.path.join(SP, "eski_dokunus.pkl")
    D, btc = yukle()
    print("eski veri:", len(D), "coin;", min(g.index[0] for g in D.values()), "->", max(g.index[-1] for g in D.values()))
    yil = pd.Series({s: g.index[0].year for s, g in D.items()}).value_counts().sort_index()
    print("coinlerin ilk yili:", yil.to_dict())
    G.D, G.FR, G.BTC = D, {}, btc
    with mp.get_context("fork").Pool(2) as hv:
        out = hv.map(G.coin, list(D))
    t = pd.DataFrame([x for o in out for x in o])
    t = t[t.zaman < BITIS]
    t = t.sort_values("dokunus").drop_duplicates(["symbol", "zaman"], keep="last")
    t["yildiz"] = np.where(t.q >= 5e6, np.where(t.dokunus >= 3, 2, np.where(t.dokunus >= 2, 1, 0)), 0)
    t.to_pickle(pk)
    print("dokunus:", len(t))
