"""Herkese acik EVM RPC uclarindan Transfer kayitlari, blok-zaman donusumu, balanceOf / kod sorgusu (anahtarsiz)."""
from __future__ import annotations

import time

import requests

RPC = {
    "bsc": ["https://bsc-rpc.publicnode.com", "https://bsc.drpc.org", "https://binance.llamarpc.com",
            "https://1rpc.io/bnb", "https://rpc-bsc.48.club", "https://bsc-mainnet.public.blastapi.io",
            "https://bsc-dataseed.bnbchain.org", "https://bsc-dataseed1.defibit.io"],
    "eth": ["https://ethereum-rpc.publicnode.com", "https://eth.drpc.org", "https://eth.llamarpc.com",
            "https://1rpc.io/eth", "https://eth-mainnet.public.blastapi.io"],
    "base": ["https://base-rpc.publicnode.com", "https://base.drpc.org", "https://mainnet.base.org"],
    "arb": ["https://arbitrum-one-rpc.publicnode.com", "https://arbitrum.drpc.org"],
}
TRANSFER = "0xddf252ad1be2c89b69c2b068fc378daa952ba7f163c4a11628f55a4df523b3ef"
_iyi = {}


ARALIK_KELIME = ("block range", "range", "too many results", "response size", "10000", "more than", "query returned")


def cagir(zincir: str, method: str, params: list, deneme: int = 0, uclar: list | None = None):
    """Uclari sirayla dener. Aralik hatasi TUM uclarda alinirsa AralikBuyuk; hiz limiti -> bekle, siradaki uc."""
    uclar = uclar or _sira.get(zincir) or RPC[zincir]
    deneme = deneme or max(6, 2 * len(uclar))
    son = None; aralik_say = 0
    for d in range(deneme):
        url = uclar[d % len(uclar)]
        try:
            r = requests.post(url, json={"jsonrpc": "2.0", "id": 1, "method": method, "params": params}, timeout=40)
            if r.status_code in (429, 403, 503):
                son = f"http {r.status_code}"; time.sleep(1 + d); continue
            j = r.json()
            if isinstance(j, list):
                j = j[0]
            if "error" in j:
                son = j["error"]; msg = str(son).lower()
                if any(k in msg for k in ARALIK_KELIME) and "rate" not in msg:
                    aralik_say += 1
                    if aralik_say >= len(uclar):
                        raise AralikBuyuk(str(son))
                    continue
                time.sleep(1 + d * 0.5); continue
            return j["result"]
        except AralikBuyuk:
            raise
        except Exception as exc:
            son = exc; time.sleep(1 + d * 0.5)
    if aralik_say:
        raise AralikBuyuk(str(son))
    raise RuntimeError(f"RPC basarisiz {zincir} {method}: {son}")


_sira = {}


def uclari_sec(zincir: str, kontrat: str, b1: int, aralik: int = 2000, log=print):
    """getLogs'u gercekten calistiran uclari bul (kendi limitleriyle), hizli olanlar once."""
    iyi = []
    for url in RPC[zincir]:
        t = time.time()
        try:
            r = requests.post(url, json={"jsonrpc": "2.0", "id": 1, "method": "eth_getLogs", "params": [
                {"address": kontrat, "topics": [TRANSFER], "fromBlock": hex(b1 - aralik), "toBlock": hex(b1)}]}, timeout=30)
            j = r.json()
            ok = isinstance(j, dict) and "result" in j
            log(f"  uc {url}: {'TAMAM ' + str(len(j['result'])) + ' kayit' if ok else str(j)[:120]} {time.time() - t:.1f}s")
            if ok:
                iyi.append((time.time() - t, url))
        except Exception as exc:
            log(f"  uc {url}: hata {str(exc)[:80]}")
    _sira[zincir] = [u for _, u in sorted(iyi)] or RPC[zincir]
    return _sira[zincir]


class AralikBuyuk(Exception):
    pass


def blok_no(zincir: str) -> int:
    return int(cagir(zincir, "eth_blockNumber", []), 16)


def blok_zaman(zincir: str, b: int) -> int:
    return int(cagir(zincir, "eth_getBlockByNumber", [hex(b), False])["timestamp"], 16)


def zamandan_blok(zincir: str, ts: int) -> int:
    lo, hi = 1, blok_no(zincir)
    if blok_zaman(zincir, hi) <= ts:
        return hi
    # tahminle daralt, sonra ikili arama
    while hi - lo > 1:
        mid = (lo + hi) // 2
        if blok_zaman(zincir, mid) <= ts:
            lo = mid
        else:
            hi = mid
    return lo


def transferler(zincir: str, kontrat: str, b0: int, b1: int, adim: int = 2000, log=print):
    """[b0, b1] arasindaki ERC20 Transfer kayitlari: (blok, tx, log_ix, from, to, deger_ham)."""
    out = []
    b = b0
    while b <= b1:
        e = min(b1, b + adim - 1)
        try:
            res = cagir(zincir, "eth_getLogs", [{"address": kontrat, "topics": [TRANSFER], "fromBlock": hex(b), "toBlock": hex(e)}])
        except (AralikBuyuk, RuntimeError) as exc:
            if adim > 20:
                adim = max(20, adim // 2)
                continue
            raise
        for x in res:
            t = x["topics"]
            if len(t) < 3:
                continue
            out.append((int(x["blockNumber"], 16), x["transactionHash"], int(x["logIndex"], 16),
                        "0x" + t[1][-40:], "0x" + t[2][-40:], int(x["data"], 16) if x["data"] not in ("0x", "") else 0))
        if (e - b0) // 100000 != (b - 1 - b0) // 100000:
            log(f"  {len(out)} transfer, blok {e - b0}/{b1 - b0}")
        b = e + 1
        if len(res) < 2000 and adim < 2000:
            adim = min(2000, adim * 2)
    return out


def bakiye(zincir: str, kontrat: str, adres: str, blok="latest") -> int:
    data = "0x70a08231" + adres[2:].rjust(64, "0")
    r = cagir(zincir, "eth_call", [{"to": kontrat, "data": data}, blok if blok == "latest" else hex(blok)])
    return int(r, 16) if r and r != "0x" else 0


def kontrat_mi(zincir: str, adres: str) -> bool:
    return cagir(zincir, "eth_getCode", [adres, "latest"]) not in ("0x", "0x0", None)


def ondalik(zincir: str, kontrat: str) -> int:
    try:
        return int(cagir(zincir, "eth_call", [{"to": kontrat, "data": "0x313ce567"}, "latest"]), 16)
    except Exception:
        return 18


# ---- Blockscout (anahtarsiz, gecmis kayitlar + etiketler): eth / base / arb ----
import os as _os

BS = {"eth": "https://eth.blockscout.com", "base": "https://base.blockscout.com", "arb": "https://arbitrum.blockscout.com"}
if _os.environ.get("NODEREAL_KEY"):
    RPC["bsc"].insert(0, f"https://bsc-mainnet.nodereal.io/v1/{_os.environ['NODEREAL_KEY']}")


_bs_son = [0.0]


ES_ZINCIR = {"eth": 1, "bsc": 56, "base": 8453, "arb": 42161}


def es_var(zincir):
    return bool(_os.environ.get("ETHERSCAN_KEY")) and zincir in ES_ZINCIR


def _bs(zincir, path, params=None, deneme=12):
    """path == '/api' ve ETHERSCAN_KEY varsa ayni sorgu Etherscan V2'ye gider (etherscan uyumlu format)."""
    son = None
    if path == "/api" and es_var(zincir):
        params = dict(params or {}, chainid=ES_ZINCIR[zincir], apikey=_os.environ["ETHERSCAN_KEY"])
        if params.get("module") == "logs":
            params.update(page=1, offset=1000)
        url0 = "https://api.etherscan.io/v2/api"
    else:
        url0 = BS[zincir] + path
    for d in range(deneme):
        bekle = (0.3 if url0.startswith("https://api.etherscan") else 0.7) - (time.time() - _bs_son[0])   # etherscan ~3/sn
        if bekle > 0:
            time.sleep(bekle)
        _bs_son[0] = time.time()
        try:
            r = requests.get(url0, params=params, timeout=60, headers={"accept": "application/json"})
            if r.status_code == 429:
                time.sleep(min(120, 5 * 2 ** min(d, 5))); son = 429; continue
            r.raise_for_status()
            j = r.json()
            if url0.startswith("https://api.etherscan") and str(j.get("message", "")).upper().startswith("NOTOK"):
                if "rate" in str(j.get("result", "")).lower():
                    time.sleep(2 + d); son = j; continue
                if "no records" not in str(j.get("result", "")).lower():
                    raise RuntimeError(str(j.get("result")))
            return j
        except Exception as exc:
            son = exc; time.sleep(2 + d)
    raise RuntimeError(f"blockscout/etherscan {zincir} {path}: {son}")


def bs_zamandan_blok(zincir, ts):
    j = _bs(zincir, "/api", {"module": "block", "action": "getblocknobytime", "timestamp": ts, "closest": "before"})
    r = j["result"]
    return int(r["blockNumber"] if isinstance(r, dict) else r)


def _h(x):
    return int(x, 16) if x and x not in ("0x", "0X") else 0


def bs_transferler(zincir, kontrat, b0, b1, log=print, maks=None):
    """Blockscout logs API (sayfa basi en fazla 1000 kayit): (blok, tx, log_ix, from, to, deger_ham, ts)."""
    out, b, adim = [], b0, 20000
    while b <= b1:
        e = min(b1, b + adim - 1)
        j = _bs(zincir, "/api", {"module": "logs", "action": "getLogs", "fromBlock": b, "toBlock": e,
                                 "address": kontrat, "topic0": TRANSFER})
        res = j.get("result") or []
        if isinstance(res, str):
            res = []
        if len(res) >= 1000 and adim > 1:
            adim = max(1, adim // 4); continue
        for x in res:
            t = [y for y in x["topics"] if y]
            if len(t) < 3:
                continue
            out.append((_h(x["blockNumber"]), x["transactionHash"], _h(x.get("logIndex")),
                        "0x" + t[1][-40:], "0x" + t[2][-40:], _h(x.get("data")), _h(x["timeStamp"])))
        if (e - b0) // 200000 != (b - 1 - b0) // 200000:
            log(f"  {len(out)} transfer, blok {e - b0}/{b1 - b0}")
        b = e + 1
        if maks and len(out) >= maks:
            break
        if len(res) < 300:
            adim = min(200000, adim * 2)
    return out


def bs_adres(zincir, adres):
    """Blockscout adres bilgisi: (kontrat_mi, isim/etiket)."""
    try:
        j = _bs(zincir, f"/api/v2/addresses/{adres}", deneme=3)
    except Exception:
        return None, ""
    tags = [t.get("label") or t.get("display_name") or "" for t in (j.get("public_tags") or [])]
    md = j.get("metadata") or {}
    tags += [t.get("name", "") for t in (md.get("tags") or [])]
    ad = j.get("name") or ""
    return bool(j.get("is_contract")), ", ".join([x for x in [ad] + tags if x])[:80]


def bs_holderlar(zincir, kontrat, sayfa=4):
    out, params = [], None
    for _ in range(sayfa):
        j = _bs(zincir, f"/api/v2/tokens/{kontrat}/holders", params)
        for x in j.get("items", []):
            a = x["address"]
            out.append({"adres": a["hash"].lower(), "deger": int(x["value"]), "kontrat": a.get("is_contract"),
                        "isim": (a.get("name") or "") + " " + ",".join(t.get("label", "") for t in (a.get("public_tags") or []))})
        params = j.get("next_page_params")
        if not params:
            break
    return out
