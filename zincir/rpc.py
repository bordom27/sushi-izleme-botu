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
