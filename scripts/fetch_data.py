#!/usr/bin/env python3
"""
Kitty PVP Dashboard — data fetcher (runs on VPS via cron every 1h).
Collects data from OpenSea API v2 + Blockscout + Dune (Robinhood),
writes data.json for the static frontend.

NO secrets leave this script. Keys are read from env or config files.
The output data.json contains only aggregated public metrics.
"""
import json
import os
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timedelta, timezone

REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))


def _read_secret(env_name, *paths):
    val = os.environ.get(env_name)
    if val:
        return val.strip()
    for p in paths:
        try:
            return open(p).read().strip()
        except OSError:
            continue
    return None


OPENSEA_KEY = _read_secret("OPENSEA_API_KEY", "/opt/data/config/opensea_key.txt")
DUNE_KEY = _read_secret("DUNE_API_KEY", "/opt/data/config/dune_key.txt")
BLOCKSCOUT = "https://robinhoodchain.blockscout.com/api/v2"
OPENSEA = "https://api.opensea.io/api/v2"
DUNE_API = "https://api.dune.com/api/v1"
DUNE_TRANSFERS_Q = 8350208
DUNE_SALES_Q = 8350211
ETH_PRICE_FALLBACK = 1879.0
TOP_HOLDERS_LIMIT = 15
SALES_PAGE_LIMIT = 20
DUNE_SINCE_DEFAULT = "2025-01-01"
ZERO = "0x0000000000000000000000000000000000000000"
_sales_cache = {}

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
            if attempt + 1 >= retries:
                break
            wait = 8 * (attempt + 1) if "429" in str(e) else 1.5 * (attempt + 1)
            time.sleep(wait)
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


def payment_eth(event):
    p = event.get("payment") or {}
    qty = float(p.get("quantity") or 0)
    dec = int(p.get("decimals") or 18)
    return qty / (10 ** dec) if dec >= 0 else 0.0


def fetch_account_sales(address):
    """All OpenSea sale events for a wallet (any collection). Cached per run."""
    key = address.lower()
    if key in _sales_cache:
        return _sales_cache[key]
    evs = []
    nxt = None
    capped = False
    for page in range(SALES_PAGE_LIMIT):
        path = f"/events/accounts/{key}?event_type=sale&limit=50"
        if nxt:
            path += "&next=" + urllib.parse.quote(nxt)
        try:
            d = os_get(path)
        except Exception as e:
            print(f"[warn] sales {key[:10]} p{page}: {e}", file=sys.stderr)
            break
        chunk = d.get("asset_events") or []
        evs.extend(chunk)
        nxt = d.get("next")
        if not nxt or not chunk:
            break
        if page + 1 >= SALES_PAGE_LIMIT:
            capped = True
        time.sleep(0.25)
    _sales_cache[key] = (evs, capped)
    return evs, capped


def _hex(val):
    if val is None:
        return ""
    s = str(val).strip().lower()
    if s.startswith("\\x"):
        s = "0x" + s[2:]
    if s.startswith("0x"):
        return s
    if all(c in "0123456789abcdef" for c in s) and len(s) in (40, 64):
        return "0x" + s
    return s


def _token_id(val):
    if val is None:
        return ""
    return str(int(val)) if str(val).isdigit() else str(val)


def _num(val):
    if val is None or val == "":
        return 0.0
    try:
        return float(val)
    except (TypeError, ValueError):
        return 0.0


def sale_unit_price(row, eth_usd):
    n = _num(row.get("nfts_in_tx")) or 1.0
    priced = row.get("price_eth")
    if priced not in (None, ""):
        p = _num(priced)
        if p > 0:
            return p
    usdg = _num(row.get("usdg_from_buyer"))
    if usdg > 0 and eth_usd:
        return (usdg / eth_usd) / n
    return None


def dune_headers():
    if not DUNE_KEY:
        raise RuntimeError("DUNE_API_KEY missing")
    return {"X-DUNE-API-KEY": DUNE_KEY, "Content-Type": "application/json"}


def dune_execute(query_id, since_date, performance="medium"):
    body = json.dumps({
        "performance": performance,
        "query_parameters": {"since_date": since_date},
    }).encode()
    req = urllib.request.Request(
        f"{DUNE_API}/query/{query_id}/execute",
        data=body,
        headers=dune_headers(),
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=60) as r:
        return json.loads(r.read().decode())


def dune_results(execution_id, timeout=240):
    deadline = time.time() + timeout
    offset = 0
    rows = []
    meta = {}
    while time.time() < deadline:
        url = f"{DUNE_API}/execution/{execution_id}/results?limit=32000&offset={offset}"
        req = urllib.request.Request(url, headers=dune_headers())
        try:
            with urllib.request.urlopen(req, timeout=60) as r:
                data = json.loads(r.read().decode())
        except urllib.error.HTTPError as e:
            if e.code in (404, 425):
                time.sleep(2)
                continue
            raise
        state = (data.get("state") or "").upper()
        if "PENDING" in state or "EXECUTING" in state:
            time.sleep(2)
            continue
        if "FAILED" in state or "CANCEL" in state:
            raise RuntimeError(f"dune {execution_id} {state}: {data.get('error') or data}")
        chunk = ((data.get("result") or {}).get("rows")) or data.get("rows") or []
        rows.extend(chunk)
        meta = data.get("result_metadata") or data.get("resultMetadata") or {}
        nxt = data.get("next_offset")
        if nxt is None or not chunk:
            return rows, meta
        offset = nxt
    raise TimeoutError(f"dune execution {execution_id} timed out")


def dune_cache_path():
    return os.path.join(REPO_ROOT, ".cache", "dune_kitties.json")


def load_dune_cache():
    path = dune_cache_path()
    try:
        with open(path) as f:
            return json.load(f)
    except Exception:
        return {"transfers": [], "sales": [], "since": None}


def save_dune_cache(cache):
    path = dune_cache_path()
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = path + ".tmp"
    with open(tmp, "w") as f:
        json.dump(cache, f)
    os.replace(tmp, path)


def _row_key_transfer(r):
    return (
        _hex(r.get("tx_hash")),
        int(r.get("evt_index") or 0),
        _hex(r.get("contract_address")),
        _token_id(r.get("token_id")),
    )


def _row_key_sale(r):
    return (
        _hex(r.get("tx_hash")),
        _hex(r.get("contract_address")),
        _token_id(r.get("token_id")),
        _hex(r.get("buyer")),
    )


def merge_rows(old, new, keyfn):
    idx = {keyfn(r): r for r in old}
    for r in new:
        idx[keyfn(r)] = r
    return list(idx.values())


def fetch_dune_events():
    """Full history on first run, then overlap the last 2 days."""
    if not DUNE_KEY:
        raise RuntimeError("DUNE_API_KEY missing")
    cache = load_dune_cache()
    if cache.get("transfers"):
        since = (datetime.now(timezone.utc) - timedelta(days=2)).strftime("%Y-%m-%d")
    else:
        since = DUNE_SINCE_DEFAULT
    print(f"[info] dune fetch since {since} (cache transfers={len(cache.get('transfers') or [])})", file=sys.stderr)
    t_ex = dune_execute(DUNE_TRANSFERS_Q, since)
    s_ex = dune_execute(DUNE_SALES_Q, since)
    transfers, _ = dune_results(t_ex["execution_id"])
    sales, _ = dune_results(s_ex["execution_id"])
    cache["transfers"] = merge_rows(cache.get("transfers") or [], transfers, _row_key_transfer)
    cache["sales"] = merge_rows(cache.get("sales") or [], sales, _row_key_sale)
    cache["since"] = since
    cache["updatedAt"] = datetime.now(timezone.utc).isoformat()
    save_dune_cache(cache)
    print(
        f"[info] dune cache transfers={len(cache['transfers'])} sales={len(cache['sales'])}",
        file=sys.stderr,
    )
    return cache


def holder_trade_pnl_dune(address, contract, nft_count, floor_eth, eth_usd, dune):
    """Per-token cost basis from on-chain transfers + Seaport sales."""
    addr = _hex(address)
    contract = _hex(contract)
    xfers = [
        t for t in dune.get("transfers") or []
        if _hex(t.get("contract_address")) == contract
        and (_hex(t.get("from_address")) == addr or _hex(t.get("to_address")) == addr)
    ]
    xfers.sort(key=lambda t: (int(t.get("block_number") or 0), int(t.get("evt_index") or 0)))
    sale_idx = {}
    for s in dune.get("sales") or []:
        if _hex(s.get("contract_address")) != contract:
            continue
        sale_idx[(_hex(s.get("tx_hash")), _token_id(s.get("token_id")))] = s

    lots = {}
    buy_prices = []
    sell_legs = []
    transfer_in = transfer_out = mints = 0
    priced_buys = priced_sells = 0

    for t in xfers:
        tid = _token_id(t.get("token_id"))
        tx = _hex(t.get("tx_hash"))
        sale = sale_idx.get((tx, tid))
        is_sale = sale is not None
        price = sale_unit_price(sale, eth_usd) if sale else None
        incoming = _hex(t.get("to_address")) == addr
        outgoing = _hex(t.get("from_address")) == addr
        is_mint = bool(t.get("is_mint")) or _hex(t.get("from_address")) == ZERO

        if incoming:
            if is_mint:
                mints += 1
                lots[tid] = {"cost": None, "via": "mint"}
            elif is_sale:
                buy_prices.append(price)
                if price:
                    priced_buys += 1
                lots[tid] = {"cost": price, "via": "buy"}
            else:
                transfer_in += 1
                lots[tid] = {"cost": None, "via": "transfer"}
        if outgoing:
            prev = lots.pop(tid, None)
            if is_sale:
                sell_legs.append({"price": price, "cost": (prev or {}).get("cost")})
                if price:
                    priced_sells += 1
            else:
                transfer_out += 1

    spent = sum(p for p in buy_prices if p)
    sold_eth = sum(s["price"] for s in sell_legs if s["price"])
    held_costs = [v["cost"] for v in lots.values() if v.get("cost")]
    hist_avg = (spent / priced_buys) if priced_buys else None
    avg_buy = (sum(held_costs) / len(held_costs)) if held_costs else hist_avg

    realized = 0.0
    realized_n = 0
    for s in sell_legs:
        if s["price"] is not None and s["cost"] is not None:
            realized += s["price"] - s["cost"]
            realized_n += 1
    unrealized = sum(floor_eth - c for c in held_costs) if floor_eth else 0.0
    pnl = None
    if held_costs or realized_n:
        pnl = realized + unrealized

    vs_floor = dd = None
    if avg_buy and avg_buy > 0 and floor_eth:
        vs_floor = (floor_eth - avg_buy) / avg_buy * 100.0
        dd = vs_floor if vs_floor < 0 else 0.0

    return {
        "buyCount": len(buy_prices),
        "sellCount": len(sell_legs),
        "transferCount": transfer_in,
        "mintCount": mints,
        "spentEth": round(spent, 6),
        "soldEth": round(sold_eth, 6),
        "avgBuyEth": round(avg_buy, 6) if avg_buy is not None else None,
        "avgSellEth": round(sold_eth / priced_sells, 6) if priced_sells else None,
        "pnlEth": round(pnl, 6) if pnl is not None else None,
        "vsFloorPct": round(vs_floor, 1) if vs_floor is not None else None,
        "drawdownPct": round(dd, 1) if dd is not None else None,
        "pricedHeld": len(held_costs),
        "pricedBuys": priced_buys,
        "source": "dune",
        "capped": False,
        "coverage": round((len(held_costs) / nft_count), 2) if nft_count else 0.0,
    }


def holder_trade_pnl_opensea(address, contract, nft_count, floor_eth):
    """Fallback: OpenSea trades only. Transfers/mints have no cost basis."""
    sales, capped = fetch_account_sales(address)
    contract = (contract or "").lower()
    addr = address.lower()
    buys = sells = 0
    spent = sold = 0.0
    for e in sales:
        nft = e.get("nft") or {}
        if (nft.get("contract") or "").lower() != contract:
            continue
        eth = payment_eth(e)
        if (e.get("buyer") or "").lower() == addr:
            buys += 1
            spent += eth
        if (e.get("seller") or "").lower() == addr:
            sells += 1
            sold += eth
    avg_buy = (spent / buys) if buys else None
    avg_sell = (sold / sells) if sells else None
    vs_floor = pnl = dd = None
    if avg_buy and avg_buy > 0:
        vs_floor = (floor_eth - avg_buy) / avg_buy * 100.0
        dd = vs_floor if vs_floor < 0 else 0.0
        pnl = nft_count * (floor_eth - avg_buy) + (sold - avg_buy * sells)
    coverage = (buys / nft_count) if nft_count else 0.0
    return {
        "buyCount": buys,
        "sellCount": sells,
        "transferCount": max(0, (nft_count or 0) + sells - buys),
        "spentEth": round(spent, 6),
        "soldEth": round(sold, 6),
        "avgBuyEth": round(avg_buy, 6) if avg_buy is not None else None,
        "avgSellEth": round(avg_sell, 6) if avg_sell is not None else None,
        "pnlEth": round(pnl, 6) if pnl is not None else None,
        "vsFloorPct": round(vs_floor, 1) if vs_floor is not None else None,
        "drawdownPct": round(dd, 1) if dd is not None else None,
        "coverage": round(coverage, 2),
        "capped": capped,
        "source": "opensea",
    }


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
    if not OPENSEA_KEY:
        raise RuntimeError("OPENSEA_API_KEY missing")
    eth_price = fetch_eth_price()
    dune = None
    try:
        dune = fetch_dune_events()
    except Exception as e:
        print(f"[warn] dune unavailable, falling back to OpenSea trades: {e}", file=sys.stderr)
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

        # portfolio + trade PnL for top holders
        top_slice = top_holders[:TOP_HOLDERS_LIMIT]
        floor = float((stats or {}).get("floorPrice") or 0)
        for h in top_slice:
            h.update(fetch_portfolio(h["address"]))
            if dune:
                h["pnl"] = holder_trade_pnl_dune(
                    h["address"], col["address"], h.get("nftCount") or 0, floor, eth_price, dune
                )
            else:
                h["pnl"] = holder_trade_pnl_opensea(
                    h["address"], col["address"], h.get("nftCount") or 0, floor
                )

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
