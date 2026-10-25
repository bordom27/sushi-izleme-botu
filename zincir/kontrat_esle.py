"""Binance USDT-M vadeli coinlerini CoinGecko uzerinden zincir/kontrat adresleriyle esler (anahtarsiz).
Cikti: arastirma_cikti/zincir/kontratlar.csv (symbol, base, cg_id, piyasa_degeri, zincir, adres)"""
import os, re, sys, time
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import pandas as pd, requests
import veri

OUT = "arastirma_cikti/zincir"
CG = "https://api.coingecko.com/api/v3"
PLAT = {"binance-smart-chain": "bsc", "ethereum": "eth", "base": "base", "arbitrum-one": "arb", "solana": "sol"}


def cg(path, params=None):
    for d in range(8):
        r = requests.get(CG + path, params=params, headers=veri.HEADERS, timeout=60)
        if r.status_code == 429:
            time.sleep(20 + 10 * d); continue
        r.raise_for_status(); return r.json()
    raise RuntimeError("coingecko " + path)


def temiz(base):
    return re.sub(r"^(1000000|1000|1M)", "", base).lower()


def main():
    os.makedirs(OUT, exist_ok=True)
    info = veri._get("/fapi/v1/exchangeInfo", {}, veri.FAPI_URLS)
    m = pd.DataFrame([{"symbol": s["symbol"], "base": s["baseAsset"]} for s in info["symbols"]
                      if s.get("contractType") == "PERPETUAL" and s.get("quoteAsset") == "USDT" and s.get("status") == "TRADING"])
    m["sym"] = m.base.map(temiz)
    liste = cg("/coins/list", {"include_platform": "true"})
    aday = {}
    for c in liste:
        aday.setdefault(c["symbol"].lower(), []).append(c)
    ids = sorted({c["id"] for s in m.sym for c in aday.get(s, [])})
    mc = {}
    for k in range(0, len(ids), 250):
        for x in cg("/coins/markets", {"vs_currency": "usd", "ids": ",".join(ids[k:k + 250]), "per_page": 250}):
            mc[x["id"]] = x.get("market_cap") or 0
        time.sleep(6)
    rows = []
    for _, r in m.iterrows():
        cs = aday.get(r.sym, [])
        if not cs:
            rows.append({"symbol": r.symbol, "base": r.base, "cg_id": None}); continue
        c = max(cs, key=lambda c: mc.get(c["id"], 0))         # ayni sembollu sahte tokenlar: en buyuk piyasa degeri
        pl = {PLAT[k]: v for k, v in (c.get("platforms") or {}).items() if k in PLAT and v}
        if not pl:
            rows.append({"symbol": r.symbol, "base": r.base, "cg_id": c["id"], "piyasa_degeri": mc.get(c["id"], 0)})
        for z, a in pl.items():
            rows.append({"symbol": r.symbol, "base": r.base, "cg_id": c["id"], "piyasa_degeri": mc.get(c["id"], 0),
                         "zincir": z, "adres": a.lower() if z != "sol" else a})
    out = pd.DataFrame(rows)
    out.to_csv(f"{OUT}/kontratlar.csv", index=False)
    print("vadeli coin", len(m), "| eslesen", out.dropna(subset=["zincir"]).symbol.nunique())
    print(out.dropna(subset=["zincir"]).zincir.value_counts().to_string())
    print(out[out.symbol == "IRYSUSDT"].to_string())


if __name__ == "__main__":
    main()
