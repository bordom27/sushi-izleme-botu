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


# Piyasa uyumu filtresi (v6.4) icin bakilan 30 buyuk coin. Bunlardan biri son 24 saatte (6 mum)
# 80 mumluk tepesinin ustunde kapattiysa yeni short sinyali verilmez. TradingView gostergesiyle AYNI liste.
GENISLIK_COINLER = [
    "BTCUSDT", "ETHUSDT", "SOLUSDT", "XRPUSDT", "BNBUSDT", "DOGEUSDT", "ADAUSDT", "TRXUSDT", "LINKUSDT",
    "AVAXUSDT", "SUIUSDT", "LTCUSDT", "NEARUSDT", "DOTUSDT", "UNIUSDT", "AAVEUSDT", "BCHUSDT", "ZECUSDT",
    "PEPEUSDT", "ENAUSDT", "TIAUSDT", "FILUSDT", "INJUSDT", "WLDUSDT", "TAOUSDT", "ARBUSDT", "OPUSDT",
    "APTUSDT", "HBARUSDT", "XLMUSDT",
]
