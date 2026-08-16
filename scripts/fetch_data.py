#!/usr/bin/env python3
"""
Kitty PVP Dashboard — data fetcher (runs on VPS via cron every 1h).
Collects data from OpenSea API v2 + Blockscout (Robinhood chain),
writes public/data.json for the static frontend.

NO secrets leave this script. OpenSea key is read from env or config file.
The output data.json contains only aggregated public metrics.
"""
import json
import os
import sys
import time
import urllib.parse
import urllib.request
from datetime import datetime, timezone

OPENSEA_KEY = os.environ.get("OPENSEA_API_KEY") or open("/opt/data/config/opensea_key.txt").read().strip()
BLOCKSCOUT = "https://robinhoodchain.blockscout.com/api/v2"
OPENSEA = "https://api.opensea.io/api/v2"
ETH_PRICE_FALLBACK = 1879.0
TOP_HOLDERS_LIMIT = 15

COLLECTIONS = [
    {
        "slug": "robinhood-kitties11",
        "name": "V1 Kitties",
        "address": "0xAe42D5511886590538160A3cbDb91388cf1e76A3",
        "opensea_url": "https://opensea.io/collection/robinhood-kitties11",
        "version": "V1",
    },
    {
        "slug": "robinhood-kitties",
        "name": "V2 Kitties",
        "address": "0x979364e11831c9508771a226245b6e97fb9a45d1",
        "opensea_url": "https://opensea.io/collection/robinhood-kitties",
        "version": "V2",
    },
]

UA = {"User-Agent": "kitty-dashboard/1.0"}


def fetch_json(url, headers=None, retries=3):
    h = dict(UA)
    if headers:
        h.update(headers)
    last = None
    for attempt in range(retries):
        try:
            req = urllib.request.Request(url, headers=h)
            with urllib.request.urlopen(req, timeout=30) as r:
                return json.loads(r.read().decode())
        except Exception as e:
            last = e
            if attempt + 1 < retries:
                time.sleep(1.5 * (attempt + 1))
    raise last


def os_get(path):
    return fetch_json(f"{OPENSEA}{path}", {"x-api-key": OPENSEA_KEY})


def bs_get(path):
    return fetch_json(f"{BLOCKSCOUT}{path}")


def fetch_eth_price():
    try:
        meta = os_get("/collections/robinhood-kitties")
        usd = float(meta.get("pricing_currencies", {}).get("listing_currency", {}).get("usd_price", "0") or "0")
        return usd or ETH_PRICE_FALLBACK
    except Exception as e:
        print(f"[warn] eth price: {e}", file=sys.stderr)
        return ETH_PRICE_FALLBACK


def fetch_token_holders_info(addr):
    """Returns (count, top_holders_list). Blockscout sorts holders by balance desc."""
    count = 0
    try:
        token = bs_get(f"/tokens/{addr}")
        count = int(token.get("holders_count", 0) or 0)
    except Exception as e:
        print(f"[warn] token info {addr[:10]}: {e}", file=sys.stderr)

    top = []
    seen = set()
    base = f"{BLOCKSCOUT}/tokens/{addr}/holders"
    opts = None
    for page in range(2):  # 2 pages × 50 = 100 holders max
        url = base if not opts else f"{base}?{urllib.parse.urlencode({k: str(v) for k, v in opts.items()})}"
        try:
            d = bs_get(url) if False else fetch_json(url)
        except Exception as e:
            print(f"[warn] holders page {page}: {e}", file=sys.stderr)
            break
        for item in d.get("items", []):
            a = (item.get("address") or {}).get("hash", "").lower()
            if not a or a in seen:
                continue
            seen.add(a)
            top.append({
                "address": a,
                "nftCount": int(item.get("value", "0") or 0),
                "isContract": bool((item.get("address") or {}).get("is_contract", False)),
            })
        opts = d.get("next_page_params")
        if not opts:
            break

    top.sort(key=lambda x: -x["nftCount"])
    if not count:
        count = len(top)
    return count, top


def fetch_portfolio(address):
    try:
        d = os_get(f"/account/{address}/portfolio")
        return {
            "tokenValueUsd": float(d.get("token_value_usd") or 0),
            "nftValueUsd": float(d.get("nft_value_usd") or 0),
            "totalValueUsd": float(d.get("total_value_usd") or 0),
        }
    except Exception as e:
        print(f"[warn] portfolio {address[:10]}: {e}", file=sys.stderr)
        return {}


def fetch_collection_meta(slug):
    try:
        return os_get(f"/collections/{slug}")
    except Exception as e:
        print(f"[warn] meta {slug}: {e}", file=sys.stderr)
        return {}


def fetch_collection_stats(slug):
    try:
        d = os_get(f"/collections/{slug}/stats")
        t = d.get("total", {})
        return {
            "volume": t.get("volume", 0),
            "sales": t.get("sales", 0),
            "numOwners": t.get("num_owners", 0),
            "floorPrice": t.get("floor_price", 0),
            "floorPriceSymbol": t.get("floor_price_symbol", "ETH"),
            "intervals": [
                {"interval": i.get("interval"), "volume": i.get("volume", 0), "sales": i.get("sales", 0)}
                for i in (d.get("intervals") or [])
            ],
        }
    except Exception as e:
        print(f"[warn] stats {slug}: {e}", file=sys.stderr)
        return {"volume": 0, "sales": 0, "numOwners": 0, "floorPrice": 0, "floorPriceSymbol": "ETH", "intervals": []}


def fetch_listings(slug):
    prices = []
    token_ids = []
    seen_tokens = set()
    nxt = None
    base = f"{OPENSEA}/listings/collection/{slug}/best?limit=100"
    for page in range(50):
        url = base if not nxt else f"{base}&next={urllib.parse.quote(nxt)}"
        try:
            d = os_get(url.replace(f"{OPENSEA}/listings", "/listings"))
        except Exception as e:
            print(f"[warn] listings page {page}: {e}", file=sys.stderr)
            break
        listings = d.get("listings", [])
        for l in listings:
            val = float((l.get("price") or {}).get("current", {}).get("value", "0") or 0) / 1e18
            prices.append(val)
            tid = ((l.get("asset") or {}).get("identifier") or "")
            if tid not in seen_tokens:
                seen_tokens.add(tid)
                token_ids.append(tid)
        nxt = d.get("next")
        if not nxt or not listings or page >= 48:
            break

    sane = sorted([p for p in prices if 0 < p < 100])
    median = sane[len(sane) // 2] if sane else 0
    floor = sane[0] if sane else 0
    total_vol = sum(sane)
    return {
        "count": len(seen_tokens),
        "totalVolumeEth": round(total_vol, 4),
        "floorFromListings": round(floor, 4),
        "medianPriceEth": round(median, 4),
    }


def load_prev_top(slug):
    path = os.path.join(os.path.dirname(__file__), "..", "data.json")
    try:
        prev = json.load(open(path))
    except Exception:
        return []
    for c in prev.get("collections") or []:
        if c.get("slug") == slug:
            return [
                {"address": h["address"], "nftCount": h.get("nftCount", 0), "isContract": h.get("isContract", False)}
                for h in (c.get("top_holders") or [])
                if h.get("address")
            ]
    return []


def fetch_all():
    eth_price = fetch_eth_price()
    collections = []
    for col in COLLECTIONS:
        print(f"[info] fetching {col['slug']}...", file=sys.stderr)
        meta = fetch_collection_meta(col["slug"])
        stats = fetch_collection_stats(col["slug"])
        holders_count, top_holders = fetch_token_holders_info(col["address"])
        if not top_holders:
            prev = load_prev_top(col["slug"])
            if prev:
                print(f"[warn] holders empty for {col['slug']}, reusing {len(prev)} previous addresses", file=sys.stderr)
                top_holders = prev
        # Prefer OpenSea num_owners if Blockscout holders_count failed (0 or only top pages)
        if not holders_count or holders_count < len(top_holders):
            holders_count = stats.get("numOwners") or holders_count or len(top_holders)

        # portfolio for top holders
        top_slice = top_holders[:TOP_HOLDERS_LIMIT]
        for h in top_slice:
            h.update(fetch_portfolio(h["address"]))

        listings = fetch_listings(col["slug"])

        collections.append({
            "slug": col["slug"],
            "name": col["name"],
            "version": col["version"],
            "opensea_url": col["opensea_url"],
            "total_supply": meta.get("total_supply") or 0,
            "unique_holders": holders_count or stats["numOwners"] or len(top_holders),
            "stats": stats,
            "listings": listings,
            "top_holders": top_slice,
            "contract_address": col["address"],
            "blockscout_url": f"https://robinhoodchain.blockscout.com/token/{col['address']}?tab=holders",
            "last_updated_iso": datetime.now(timezone.utc).isoformat(),
        })

    return {
        "generatedAt": datetime.now(timezone.utc).isoformat(),
        "ethPriceUsd": eth_price,
        "collections": collections,
    }


def main():
    # Write data.json next to index.html (repo root) for GitHub Pages
    out_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
    os.makedirs(out_dir, exist_ok=True)
    data = fetch_all()
    out_path = os.path.join(out_dir, "data.json")
    with open(out_path, "w") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)
    print(f"[ok] wrote {out_path} ({len(data['collections'])} collections)", file=sys.stderr)
    for c in data["collections"]:
        print(
            f"  {c['version']} {c['name']} ({c['slug']}): {c['unique_holders']} holders, "
            f"floor Ξ{c['stats']['floorPrice']}, listings {c['listings']['count']}",
            file=sys.stderr,
        )


if __name__ == "__main__":
    main()
