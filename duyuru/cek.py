"""
Binance duyuru arsivi (GitHub Actions'ta calisir): listeleme, vadeli acilis, izleme/tohum etiketi, delist vb.
Kaynak: binance.com CMS genel API (anahtarsiz). Cikti: arastirma_cikti/duyuru/duyurular.csv (id, katalog, baslik, zaman_ms)
"""
import os, sys, time
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import pandas as pd, requests
import veri

OUT = "arastirma_cikti/duyuru"
URL = "https://www.binance.com/bapi/composite/v1/public/cms/article/list/query"
KATALOG = {48: "yeni_listeleme", 161: "delist", 49: "son_haberler", 93: "etkinlik", 157: "bakim", 51: "api"}
SINIR = pd.Timestamp("2020-06-01").value // 10**6


def sayfa(kat, no):
    for d in range(6):
        try:
            r = requests.get(URL, params={"type": 1, "catalogId": kat, "pageNo": no, "pageSize": 50},
                             headers=dict(veri.HEADERS, **{"lang": "en", "clienttype": "web"}), timeout=30)
            if r.status_code == 429:
                time.sleep(10 + 10 * d); continue
            r.raise_for_status()
            j = r.json()
            cs = (j.get("data") or {}).get("catalogs") or []
            return cs[0].get("articles", []) if cs else []
        except Exception as exc:
            print("  tekrar", kat, no, str(exc)[:100], flush=True); time.sleep(3 + 3 * d)
    raise RuntimeError(f"sayfa alinamadi {kat} {no}")


def main():
    os.makedirs(OUT, exist_ok=True)
    rows = []
    for kat, ad in KATALOG.items():
        no = 1
        while True:
            a = sayfa(kat, no)
            if not a:
                break
            for x in a:
                rows.append({"id": x.get("id"), "kod": x.get("code"), "katalog": ad, "baslik": x.get("title"),
                             "zaman_ms": x.get("releaseDate")})
            en_eski = min(x.get("releaseDate") or 0 for x in a)
            print(ad, "sayfa", no, len(a), pd.to_datetime(en_eski, unit="ms"), flush=True)
            if en_eski < SINIR or no >= 300:
                break
            no += 1
            time.sleep(0.6)
    df = pd.DataFrame(rows).drop_duplicates(["id", "katalog"])
    df["zaman"] = pd.to_datetime(df.zaman_ms, unit="ms")
    df.sort_values("zaman").to_csv(f"{OUT}/duyurular.csv", index=False)
    print("toplam", len(df), df.groupby("katalog").size().to_dict(), df.zaman.min(), df.zaman.max())


if __name__ == "__main__":
    main()
