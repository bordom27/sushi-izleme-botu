"""Botun izledigi coinler - v6 testinde kullanilan 46 coinlik liste (4 saatlik grafik).

Coin secimi bilerek YAPILMADI: gecmiste iyi giden coinleri secmek gelecekte
ise yaramadi (test: IS'te kazandiranlar OOS'ta +0.025R, elenenler +0.21R/islem).
Liste genis ve likit tutulur. Eklemek / cikarmak icin buraya yazman yeterli.

D grubu (Ekim 2026): gecmis basariya gore DEGIL, kurala gore eklendi -> Binance spot USDT,
24s hacim >= ~2.4M$, en az ~6 ay gecmis, stablecoin / tokenize hisse / altin haric.
Test (v6.3): bu 56 coin egitim +12.5R, test +19.9R (islem basi 0.10R; ilk 46'da 0.15R).
Hacmi daha dusuk katmanlarda test kazanci sifira yaklastigi icin daha fazlasi eklenmedi.
"""

COINLER = [
    # A
    "JSTUSDT", "CRVUSDT", "FILUSDT", "DOTUSDT", "ZECUSDT", "TRXUSDT", "PAXGUSDT", "DEXEUSDT",
    # C (ilk 15)
    "SOLUSDT", "BNBUSDT", "ADAUSDT", "AVAXUSDT", "LINKUSDT", "DOGEUSDT", "LTCUSDT", "ATOMUSDT",
    "NEARUSDT", "UNIUSDT", "AAVEUSDT", "INJUSDT", "OPUSDT", "ARBUSDT", "SUIUSDT",
    # B
    "ZILUSDT", "JTOUSDT", "ETHUSDT", "XLMUSDT", "SUSHIUSDT", "BTCUSDT", "PLUMEUSDT", "ACEUSDT",
    # C (kalan)
    "APTUSDT", "TIAUSDT", "SEIUSDT", "RUNEUSDT", "POLUSDT", "FETUSDT", "RENDERUSDT", "WIFUSDT",
    "PEPEUSDT", "ENAUSDT", "HBARUSDT", "ALGOUSDT", "VETUSDT", "ICPUSDT", "ETCUSDT",
    # D (Ekim 2026, hacim kuraliyla)
    "XRPUSDT", "WLDUSDT", "STRKUSDT", "TAOUSDT", "PUMPUSDT", "ZROUSDT", "SANDUSDT", "QNTUSDT",
    "EPICUSDT", "ONDOUSDT", "GTCUSDT", "PROMUSDT", "AMPUSDT", "ERAUSDT", "TONUSDT", "TRUMPUSDT",
    "RADUSDT", "ASTERUSDT", "EIGENUSDT", "PYTHUSDT", "BCHUSDT", "BATUSDT", "CAKEUSDT", "AUSDT",
    "ZKUSDT", "ALTUSDT", "NIGHTUSDT", "WUSDT", "NFPUSDT", "AVAUSDT", "XPLUSDT", "MINAUSDT",
    "LSKUSDT", "DUSKUSDT", "NILUSDT", "RSRUSDT", "MUBARAKUSDT", "STRAXUSDT", "KMNOUSDT", "NMRUSDT",
    "ETHFIUSDT", "BERAUSDT", "AXLUSDT", "PENGUUSDT", "WALUSDT", "DASHUSDT", "AUDIOUSDT", "RAYUSDT",
    "LDOUSDT", "STXUSDT", "ZAMAUSDT", "NXPCUSDT", "SUSDT", "RLCUSDT", "VIRTUALUSDT", "KITEUSDT",
]
# Guven etiketi (son 24 saatte ayni yonde kac sinyal) bu 102 coinlik cekirdekle olculdu; esikler buna gore.
CEKIRDEK = list(COINLER)

# E (20 Ekim 2026, kurala gore): hacim sirasinda listenin ardindaki ilk 100 coin icinden Binance vadelide (USDT-M)
# kontrati olan ve en az 6 aylik gecmisi olan 58 coin. Test (2020+): 315 islem, isabet %56, +41R, A/B/C donemlerinin
# ucunde de karda (islem basi +0.13R; cekirdekte +0.2R). Gecmis basariya gore secilmedi.
COINLER += [
    "PHAUSDT", "WLFIUSDT", "BMTUSDT", "ENSOUSDT", "BEAMXUSDT", "MORPHOUSDT", "IOUSDT", "COMPUSDT",
    "OPENUSDT", "PENDLEUSDT", "BONKUSDT", "REZUSDT", "VELODROMEUSDT", "IOSTUSDT", "ARUSDT", "THETAUSDT",
    "METISUSDT", "FFUSDT", "ZENUSDT", "SKYUSDT", "KATUSDT", "SOPHUSDT", "PNUTUSDT", "METUSDT",
    "SOLVUSDT", "IDUSDT", "CFXUSDT", "KERNELUSDT", "SENTUSDT", "GALAUSDT", "MOVRUSDT", "GIGGLEUSDT",
    "KAIAUSDT", "CVXUSDT", "MAGICUSDT", "OGNUSDT", "JASMYUSDT", "AXSUSDT", "BOMEUSDT", "SAGAUSDT",
    "SLPUSDT", "RVNUSDT", "BLURUSDT", "BIOUSDT", "ARKMUSDT", "ORDIUSDT", "LUMIAUSDT", "ENSUSDT",
    "NEIROUSDT", "ROSEUSDT", "APEUSDT", "LITUSDT", "HEIUSDT", "ONTUSDT", "FLOKIUSDT", "CFGUSDT",
    "OPNUSDT", "TUTUSDT",
]

# Vadelide farkli adla islem gorenler (fiyat x1000) ve vadeli kontrati olmayanlar (Ekim 2026)
VADELI_AD = {"PEPEUSDT": "1000PEPEUSDT", "BONKUSDT": "1000BONKUSDT", "FLOKIUSDT": "1000FLOKIUSDT"}
VADELI_YOK = {"EPICUSDT", "AMPUSDT", "TONUSDT", "RADUSDT", "NFPUSDT", "STRAXUSDT", "AUDIOUSDT", "RAYUSDT"}


# Piyasa uyumu filtresi (v6.4) icin bakilan 30 buyuk coin. Bunlardan biri son 24 saatte (6 mum)
# 80 mumluk tepesinin ustunde kapattiysa yeni short sinyali verilmez. TradingView gostergesiyle AYNI liste.
GENISLIK_COINLER = [
    "BTCUSDT", "ETHUSDT", "SOLUSDT", "XRPUSDT", "BNBUSDT", "DOGEUSDT", "ADAUSDT", "TRXUSDT", "LINKUSDT",
    "AVAXUSDT", "SUIUSDT", "LTCUSDT", "NEARUSDT", "DOTUSDT", "UNIUSDT", "AAVEUSDT", "BCHUSDT", "ZECUSDT",
    "PEPEUSDT", "ENAUSDT", "TIAUSDT", "FILUSDT", "INJUSDT", "WLDUSDT", "TAOUSDT", "ARBUSDT", "OPUSDT",
    "APTUSDT", "HBARUSDT", "XLMUSDT",
]
