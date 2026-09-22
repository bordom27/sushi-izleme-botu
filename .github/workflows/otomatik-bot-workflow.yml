name: Otomatik Alim-Satim Botu (Testnet)

on:
  schedule:
    - cron: "0 * * * *"   # saatte bir calisir
  workflow_dispatch: {}     # "Run workflow" ile elle de tetiklenebilir

jobs:
  otomatik-bot:
    runs-on: ubuntu-latest
    timeout-minutes: 15
    steps:
      - name: Repoyu al
        uses: actions/checkout@v4

      - name: Python kur
        uses: actions/setup-python@v5
        with:
          python-version: "3.11"

      - name: Kutuphaneleri kur
        run: pip install python-binance pandas numpy requests

      - name: Botu calistir
        env:
          BINANCE_TESTNET_API_KEY: ${{ secrets.BINANCE_TESTNET_API_KEY }}
          BINANCE_TESTNET_API_SECRET: ${{ secrets.BINANCE_TESTNET_API_SECRET }}
          TELEGRAM_BOT_TOKEN: ${{ secrets.TELEGRAM_BOT_TOKEN }}
          TELEGRAM_CHAT_ID: ${{ secrets.TELEGRAM_CHAT_ID }}
        run: python otomatik_bot_testnet.py

      - name: Pozisyon durumunu (state) repoya kaydet
        run: |
          git config user.name "otomatik-bot"
          git config user.email "otomatik-bot@users.noreply.github.com"
          git add otomatik_bot_state.json
          git diff --staged --quiet || git commit -m "Bot state guncellendi [otomatik]"
          git push
