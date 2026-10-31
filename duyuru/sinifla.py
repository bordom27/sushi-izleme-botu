"""Duyuru basliklarini olay turlerine ayir ve vadeli sembole esle. Cikti: arastirma_cikti/duyuru/olaylar.csv"""
import re
import pandas as pd

D = pd.read_csv("arastirma_cikti/duyuru/duyurular.csv", parse_dates=["zaman"])
META = pd.read_csv("arastirma_cikti/dok/meta.csv")
BASE = {}
for s, b in zip(META.symbol, META.base):
    BASE.setdefault(b.upper(), s)
    for on in ("1000000", "1000", "1M"):
        if b.upper().startswith(on):
            BASE.setdefault(b.upper()[len(on):], s)


def liste(s):
    s = re.split(r"\s+on\s+\d{4}-|\s*\(\d{4}-|,?\s+and\s+[Rr]emove|,\s*[Rr]emove|\s+[Ww]ith\s+|\s+[Ff]rom\s+", s)[0]
    parca = re.split(r",|&|\band\b", s)
    out = []
    for p in parca:
        m = re.search(r"\(([A-Za-z0-9$]+)\)", p)
        t = (m.group(1) if m else p).strip().strip(".").upper()
        if re.fullmatch(r"[A-Z0-9]{2,15}", t):
            out.append(t)
    return out


def sinifla(b):
    bl = b.lower()
    if "monitoring tag to include" in bl or ("add" in bl and "monitoring tag" in bl and "remove the monitoring" not in bl):
        return "izleme", liste(re.split(r"(?i)include|monitoring tag (?:to|for)", b)[-1])
    if re.search(r"(?i)binance futures will (?:close all positions and )?delist (?:usd.?-m )?([A-Z0-9]+USDT)", b):
        return "vadeli_delist", re.findall(r"\b([A-Z0-9]{2,20})USDT\b", b)
    if re.search(r"(?i)^binance will delist|will delist (?!.*margin)", b) and "futures" not in bl and "margin" not in bl and "alpha" not in bl:
        return "spot_delist", liste(re.split(r"(?i)delist", b)[-1])
    if re.search(r"(?i)futures will launch", b) and "pre-market" not in bl and "tradfi" not in bl and "pre-ipo" not in bl:
        return "vadeli_acilis", re.findall(r"\b([A-Z0-9]{2,20})USDT\b", b)
    if re.search(r"(?i)binance will list|will list .*\(", b) and "futures" not in bl:
        return "spot_listeleme", re.findall(r"\(([A-Za-z0-9$]{2,15})\)", re.split(r"(?i)will list", b)[-1])
    if "hodler airdrops" in bl and "introducing" in bl:
        return "hodler", re.findall(r"\(([A-Za-z0-9]{2,15})\)", b)[:1]
    if "remove the seed tag" in bl or "remove seed tag" in bl:
        return "tohum_kaldir", liste(re.split(r"(?i)seed tag for", b)[-1])
    return None, []


rows = []
for _, r in D[D.katalog.isin(["yeni_listeleme", "delist", "son_haberler"])].iterrows():
    tur, tik = sinifla(str(r.baslik))
    if not tur:
        continue
    for t in dict.fromkeys(x.upper() for x in tik):
        rows.append({"zaman": r.zaman, "tur": tur, "ticker": t, "symbol": BASE.get(t), "baslik": r.baslik})
O = pd.DataFrame(rows).drop_duplicates(["zaman", "tur", "ticker"])
O.to_csv("arastirma_cikti/duyuru/olaylar.csv", index=False)
if __name__ == "__main__":
    O2 = O[O.zaman >= "2021-01-01"]
    print(O2.groupby("tur").agg(olay=("ticker", "size"), vadelisi_var=("symbol", lambda s: s.notna().sum())).to_string())
    pd.set_option("display.width", 220); pd.set_option("display.max_colwidth", 110)
    for t in O2.tur.unique():
        print("\n", t); print(O2[O2.tur == t].sample(min(4, (O2.tur == t).sum()), random_state=2)[["zaman", "ticker", "symbol", "baslik"]].to_string(index=False))
