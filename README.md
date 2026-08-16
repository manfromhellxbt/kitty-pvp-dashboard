# Kitty PVP Dashboard

Live analytics dashboard for **Robinhood Kitties** NFT collections on the Robinhood L2 chain.

🌐 **Live:** https://manfromhellxbt.github.io/kitty-pvp-dashboard/

## Collections
- [robinhood-kitties](https://opensea.io/collection/robinhood-kitties)
- [robinhood-kitties11](https://opensea.io/collection/robinhood-kitties11)

## Metrics shown
- Comparison table V1 vs V2 (holders, supply, uniqueness, floor, median listing, volume/sales total + 24h/7d/30d, listings)
- Unique holders (total count)
- Top 15 whales — wallet cash + NFT portfolio value
- Sales volume + sales count (total, 24h, 7d)
- Active listings count + listing volume
- Floor price

## Architecture

```
[VPS — private]                    [GitHub Pages — public, free]
┌──────────────────────┐            ┌──────────────────────────┐
│ scripts/fetch_data.py │            │ index.html               │
│ + OPENSEA_API_KEY    │─commit──→  │ public/data.json         │
│ cron every 6h        │   every 6h │ (aggregated public data)  │
└──────────────────────┘            └──────────────────────────┘
```

- **Frontend:** static `index.html`, reads `data.json` via fetch. No build step.
- **Data pipeline:** Python script on a VPS fetches from OpenSea API v2 + Blockscout every 6h, commits `data.json` to this repo. GitHub Pages auto-deploys.
- **Secrets:** the OpenSea API key lives ONLY on the VPS (`/opt/data/config/opensea_key.txt`). It is never committed to this repo.
- The data in `data.json` is aggregated from public on-chain sources — anyone can see the same on Blockscout/OpenSea.

## Local dev

```bash
# serve locally
python3 -m http.server 8000
# open http://localhost:8000
```

## Refresh data

```bash
export OPENSEA_API_KEY=...
python3 scripts/fetch_data.py     # writes public/data.json
git add public/data.json && git commit -m "update data" && git push
```
