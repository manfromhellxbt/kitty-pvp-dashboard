// Kitty PVP Dashboard - Data Fetcher
// Collects data from OpenSea API v2 + Blockscout (Robinhood chain)

const OPENSEA_KEY = process.env.OPENSEA_API_KEY || "";
const BLOCKSCOUT = "https://robinhoodchain.blockscout.com/api/v2";

const COLLECTIONS = [
  {
    slug: "robinhood-kitties",
    name: "Robinhood Kitties",
    address: "0x979364e11831c9508771a226245b6e97fb9a45d1",
    openseaUrl: "https://opensea.io/collection/robinhood-kitties",
  },
  {
    slug: "robinhood-kitties11",
    name: "Robinhood Kitties 11",
    address: "0xAe42D5511886590538160A3cbDb91388cf1e76A3",
    openseaUrl: "https://opensea.io/collection/robinhood-kitties11",
  },
];

const TOP_HOLDERS_LIMIT = 15; // fetch portfolio for top 15 holders per collection

export interface Holder {
  address: string;
  nftCount: number;
  isContract: boolean;
}

export interface HolderWithPortfolio extends Holder {
  tokenValueUsd?: number;
  nftValueUsd?: number;
  totalValueUsd?: number;
  pnlAbsolute?: number;
  pnlPercentage?: number;
}

interface CollectionStats {
  volume: number;
  sales: number;
  numOwners: number;
  floorPrice: number;
  floorPriceSymbol: string;
  intervals: { interval: string; volume: number; sales: number }[];
}

interface ListingsInfo {
  count: number;
  totalVolumeEth: number;
  floorFromListings: number;
  medianPriceEth: number;
  top5: { tokenId: string; priceEth: number }[];
}

export interface CollectionData {
  slug: string;
  name: string;
  openseaUrl: string;
  totalSupply: number;
  holdersCount: number;
  uniqueHolders: number;
  stats: CollectionStats;
  listings: ListingsInfo;
  topHolders: HolderWithPortfolio[];
  contractAddress: string;
  blockscoutUrl: string;
  lastUpdatedISO: string;
}

export interface DashboardData {
  generatedAt: string;
  ethPriceUsd: number;
  collections: CollectionData[];
}

async function fetchJSON(url: string, headers: Record<string, string> = {}): Promise<any> {
  const resp = await fetch(url, {
    headers: { "User-Agent": "kitty-dashboard/1.0", ...headers },
    // Keep ISR-friendly caching; page revalidate = 21600s
    next: { revalidate: 21600 },
  } as RequestInit);
  if (!resp.ok) {
    throw new Error(`HTTP ${resp.status} for ${url.split("?")[0]}`);
  }
  return resp.json();
}

// Fetch holders count + top holders from Blockscout.
// Holders endpoint already returns sorted by balance desc, so first pages = whales.
async function fetchTokenHoldersInfo(contractAddress: string): Promise<{ count: number; top: Holder[] }> {
  // Token metadata (holders_count)
  let count = 0;
  try {
    const token = await fetchJSON(`${BLOCKSCOUT}/tokens/${contractAddress}`);
    count = parseInt(token.holders_count || "0", 10) || 0;
  } catch (e: any) {
    console.error(`[kitty] token info failed ${contractAddress}:`, e?.message || e);
  }

  const top: Holder[] = [];
  const seen = new Set<string>();
  let nextParams: Record<string, any> | null = null;
  const baseUrl = `${BLOCKSCOUT}/tokens/${contractAddress}/holders`;

  // 2 pages × 50 = 100 holders max — more than enough for top 15 whales
  for (let i = 0; i < 2; i++) {
    const url = nextParams
      ? `${baseUrl}?${new URLSearchParams(Object.entries(nextParams).map(([k, v]) => [k, String(v)]))}`
      : baseUrl;
    try {
      const data = await fetchJSON(url);
      const items = data.items || [];
      for (const item of items) {
        const addr = (item.address?.hash || "").toLowerCase();
        if (!addr || seen.has(addr)) continue;
        seen.add(addr);
        top.push({
          address: addr,
          nftCount: parseInt(item.value || "0", 10),
          isContract: !!item.address?.is_contract,
        });
      }
      nextParams = data.next_page_params;
      if (!nextParams) break;
    } catch (e: any) {
      console.error(`[kitty] holders page ${i} failed ${contractAddress}:`, e?.message || e);
      break;
    }
  }

  top.sort((a, b) => b.nftCount - a.nftCount);
  if (!count) count = top.length;
  return { count, top };
}

// Fetch portfolio for a single holder (money on wallet + NFT value)
async function fetchPortfolio(address: string, ethPrice: number): Promise<Partial<HolderWithPortfolio>> {
  try {
    const url = `https://api.opensea.io/api/v2/account/${address}/portfolio?chains=robinhood`;
    const data = await fetchJSON(url, { "x-api-key": OPENSEA_KEY });
    return {
      tokenValueUsd: parseFloat(data.token_value_usd || "0"),
      nftValueUsd: parseFloat(data.nft_value_usd || "0"),
      totalValueUsd: parseFloat(data.total_value_usd || "0"),
      pnlAbsolute: parseFloat((data.pnl_absolute || "").replace("+", "")) || 0,
      pnlPercentage: parseFloat((data.pnl_percentage || "").replace("+", "")) || 0,
    };
  } catch {
    return {};
  }
}

// Fetch collection stats from OpenSea (works without key, but we pass it anyway)
async function fetchCollectionStats(slug: string, ethPrice: number): Promise<CollectionStats> {
  const data = await fetchJSON(`https://api.opensea.io/api/v2/collections/${slug}/stats`, {
    "x-api-key": OPENSEA_KEY,
  });
  return {
    volume: data.total?.volume || 0,
    sales: data.total?.sales || 0,
    numOwners: data.total?.num_owners || 0,
    floorPrice: data.total?.floor_price || 0,
    floorPriceSymbol: data.total?.floor_price_symbol || "ETH",
    intervals: (data.intervals || []).map((i: any) => ({
      interval: i.interval,
      volume: i.volume,
      sales: i.sales,
    })),
  };
}

// Fetch collection metadata (total_supply, name)
async function fetchCollectionMeta(slug: string): Promise<any> {
  return fetchJSON(`https://api.opensea.io/api/v2/collections/${slug}`, {
    "x-api-key": OPENSEA_KEY,
  });
}

// Count active listings via pagination through "best" endpoint
async function fetchListings(slug: string): Promise<ListingsInfo> {
  const prices: number[] = [];
  const tokenIds: string[] = [];
  const seenTokens = new Set<string>();
  let next: string | null = null;

  for (let i = 0; i < 50; i++) {
    const base = `https://api.opensea.io/api/v2/listings/collection/${slug}/best?limit=100`;
    const url = next ? `${base}&next=${encodeURIComponent(next)}` : base;
    const data = await fetchJSON(url, { "x-api-key": OPENSEA_KEY });
    const listings = data.listings || [];
    for (const l of listings) {
      const val = parseFloat(l.price?.current?.value || "0") / 1e18;
      const tokenId = l.asset?.identifier || "";
      prices.push(val);
      if (!seenTokens.has(tokenId)) {
        seenTokens.add(tokenId);
        tokenIds.push(tokenId);
      }
    }
    next = data.next;
    if (!next || listings.length === 0 || i >= 48) break;
  }

  const sortedPrices = [...prices].filter((p) => p > 0 && p < 100).sort((a, b) => a - b); // drop absurd listings > 100 ETH
  const median = sortedPrices.length
    ? sortedPrices[Math.floor(sortedPrices.length / 2)]
    : 0;
  const floor = sortedPrices.length ? sortedPrices[0] : 0;
  const top5: { tokenId: string; priceEth: number }[] = [];
  for (let i = 0; i < Math.min(5, tokenIds.length); i++) {
    top5.push({ tokenId: tokenIds[i], priceEth: sortedPrices[i] || 0 });
  }

  // Sum only sane listings (under 100 ETH) for volume figure
  const sanePrices = prices.filter((p) => p > 0 && p < 100);

  return {
    count: seenTokens.size, // unique listed tokens
    totalVolumeEth: sanePrices.reduce((s, p) => s + p, 0),
    floorFromListings: floor,
    medianPriceEth: median,
    top5,
  };
}

const ETH_PRICE_FALLBACK = 1879.0;

export async function fetchAllData(): Promise<DashboardData> {
  const ethPrice = await fetchEthPrice();
  const collections: CollectionData[] = [];

  for (const col of COLLECTIONS) {
    // Fetch holders, meta, stats, listings in parallel where possible
    const metaPromise = fetchCollectionMeta(col.slug).catch((e) => {
      console.error(`[kitty] meta failed ${col.slug}:`, e?.message || e);
      return {};
    });
    const statsPromise = fetchCollectionStats(col.slug, ethPrice).catch((e) => {
      console.error(`[kitty] stats failed ${col.slug}:`, e?.message || e);
      return {
        volume: 0, sales: 0, numOwners: 0, floorPrice: 0, floorPriceSymbol: "ETH", intervals: [],
      };
    });
    const holdersPromise = fetchTokenHoldersInfo(col.address).catch((e) => {
      console.error(`[kitty] holders failed ${col.slug}:`, e?.message || e);
      return { count: 0, top: [] as Holder[] };
    });

    const [meta, stats, holdersInfo] = await Promise.all([metaPromise, statsPromise, holdersPromise]);
    const holders = holdersInfo.top;
    const uniqueHolders = holdersInfo.count || stats.numOwners || holders.length;
    if (holders.length === 0) console.error(`[kitty] no holders for ${col.slug}`);

    // Fetch portfolio for top holders
    const topSlice = holders.slice(0, TOP_HOLDERS_LIMIT);
    const portfolios = await Promise.all(
      topSlice.map((h) => fetchPortfolio(h.address, ethPrice))
    );
    const topHolders: HolderWithPortfolio[] = topSlice.map((h, idx) => ({
      ...h,
      ...portfolios[idx],
    }));

    // Listings (rate-limited if many pages; bounded)
    const listings = await fetchListings(col.slug).catch((e) => {
      console.error(`[kitty] listings failed for ${col.slug}:`, e);
      return { count: 0, totalVolumeEth: 0, floorFromListings: 0, medianPriceEth: 0, top5: [] };
    });

    collections.push({
      slug: col.slug,
      name: meta.name || col.name,
      openseaUrl: col.openseaUrl,
      totalSupply: meta.total_supply || 0,
      holdersCount: stats.numOwners,
      uniqueHolders,
      stats,
      listings,
      topHolders,
      contractAddress: col.address,
      blockscoutUrl: `https://robinhoodchain.blockscout.com/token/${col.address}?tab=holders`,
      lastUpdatedISO: new Date().toISOString(),
    });
  }

  return { generatedAt: new Date().toISOString(), ethPriceUsd: ethPrice, collections };
}

async function fetchEthPrice(): Promise<number> {
  try {
    const data = await fetchCollectionMeta("robinhood-kitties");
    const usd = parseFloat(data?.pricing_currencies?.listing_currency?.usd_price || "");
    return usd || ETH_PRICE_FALLBACK;
  } catch {
    return ETH_PRICE_FALLBACK;
  }
}
