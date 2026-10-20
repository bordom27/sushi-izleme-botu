import json, requests as rq
for url in ("https://fapi.binance.com/fapi/v1/exchangeInfo", "https://www.binance.com/fapi/v1/exchangeInfo"):
    try:
        j = rq.get(url, timeout=30).json()
        p = sorted(x["symbol"] for x in j["symbols"] if x.get("contractType") == "PERPETUAL" and x.get("quoteAsset") == "USDT" and x.get("status") == "TRADING")
        if p:
            json.dump(p, open("arastirma_cikti/vadeli_liste.json", "w")); print(len(p)); break
    except Exception as e:
        print(url, e)
