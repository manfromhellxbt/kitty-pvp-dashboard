# Kitty PVP Dashboard

Live analytics for two Robinhood Kitties NFT collections:

- [robinhood-kitties](https://opensea.io/collection/robinhood-kitties)
- [robinhood-kitties11](https://opensea.io/collection/robinhood-kitties11)

## Metrics

- Unique holders (Blockscout Robinhood)
- Top whales: wallet cash + NFT portfolio value (OpenSea portfolio API)
- Sales volume + sales count (OpenSea stats)
- Active listings count + listing volume
- Floor price

## Stack

- Next.js 14 (App Router) + ISR `revalidate = 21600` (6 hours)
- OpenSea API v2 + Blockscout Robinhood

## Env

```
OPENSEA_API_KEY=...
```

## Local

```bash
npm i
cp .env.example .env.local   # set key
npm run dev
```
