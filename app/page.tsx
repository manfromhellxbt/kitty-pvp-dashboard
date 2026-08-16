import { fetchAllData, type DashboardData, type CollectionData, type HolderWithPortfolio } from "../lib/fetcher";

// ISR — regenerate every 6 hours (21600 seconds)
// First request after expiry regenerates in background; page stays served from cache.
export const revalidate = 21600;

function shortAddr(addr: string): string {
  return `${addr.slice(0, 6)}…${addr.slice(-4)}`;
}

function fmtUsd(n: number): string {
  if (n >= 1_000_000) return `$${(n / 1_000_000).toFixed(2)}M`;
  if (n >= 1_000) return `$${(n / 1_000).toFixed(1)}K`;
  return `$${n.toFixed(2)}`;
}

function fmtEth(n: number): string {
  if (n >= 1000) return `${n.toFixed(0)}`;
  if (n >= 1) return `${n.toFixed(2)}`;
  return `${n.toFixed(3)}`;
}

function fmtNum(n: number): string {
  if (n >= 1_000_000) return `${(n / 1_000_000).toFixed(1)}M`;
  if (n >= 1_000) return `${(n / 1_000).toFixed(1)}K`;
  return n.toLocaleString("en-US");
}

function pnlClass(n: number): string {
  return n >= 0 ? "pnl-up" : "pnl-down";
}

function pnlSign(n: number): string {
  return n >= 0 ? "+" : "";
}

function SummaryCard({ label, value, sub }: { label: string; value: string; sub?: string }) {
  return (
    <div className="summary-card">
      <div className="summary-label">{label}</div>
      <div className="summary-value">{value}</div>
      {sub && <div className="summary-sub">{sub}</div>}
    </div>
  );
}

function MetricCard({ label, value, children }: { label: string; value: string; children?: React.ReactNode }) {
  return (
    <div className="metric-card">
      <div className="metric-label">{label}</div>
      <div className="metric-value">{value}</div>
      {children && <div className="metric-sub">{children}</div>}
    </div>
  );
}

function WhalesTable({ holders, ethPrice }: { holders: HolderWithPortfolio[]; ethPrice: number }) {
  return (
    <div className="whales-section">
      <div className="whales-header">
        <div className="whales-title">Топ холдеры (киты)</div>
        <div className="whales-note">портфолио через OpenSea · chain: robinhood</div>
      </div>
      <table className="table">
        <thead>
          <tr>
            <th>#</th>
            <th>Адрес</th>
            <th style={{ textAlign: "right" }}>NFT</th>
            <th style={{ textAlign: "right" }}>Наличные ($)</th>
            <th style={{ textAlign: "right" }}>NFT ($)</th>
            <th style={{ textAlign: "right" }}>Всего ($)</th>
            <th style={{ textAlign: "right" }}>P&L день</th>
          </tr>
        </thead>
        <tbody>
          {holders.map((h, i) => (
            <tr key={h.address}>
              <td style={{ color: "var(--text-quaternary)", fontFamily: "JetBrains Mono, monospace" }}>{i + 1}</td>
              <td className="addr-cell">
                <a href={`https://robinhoodchain.blockscout.com/address/${h.address}`} target="_blank" rel="noopener">
                  {shortAddr(h.address)}
                  {h.isContract && <span className="contract-tag" style={{ marginLeft: 6 }}>contract</span>}
                </a>
              </td>
              <td className="num-cell">{h.nftCount}</td>
              <td className="num-cell">{h.tokenValueUsd ? fmtUsd(h.tokenValueUsd) : "—"}</td>
              <td className="num-cell">{h.nftValueUsd ? fmtUsd(h.nftValueUsd) : "—"}</td>
              <td className="num-cell" style={{ fontWeight: 500 }}>
                {h.totalValueUsd ? fmtUsd(h.totalValueUsd) : "—"}
              </td>
              <td className={`num-cell ${pnlClass(h.pnlAbsolute || 0)}`}>
                {h.pnlAbsolute !== undefined ? `${pnlSign(h.pnlAbsolute)}${fmtUsd(h.pnlAbsolute)}` : "—"}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function CollectionBlock({ col, ethPrice }: { col: CollectionData; ethPrice: number }) {
  const floorUsd = col.stats.floorPrice * ethPrice;
  const listedPct = col.totalSupply ? (col.listings.count / col.totalSupply) * 100 : 0;
  const oneDay = col.stats.intervals.find((i) => i.interval === "one_day");
  const sevenDay = col.stats.intervals.find((i) => i.interval === "seven_day");

  return (
    <section className="collection-section">
      <div className="collection-header">
        <div className="collection-title">
          <a href={col.openseaUrl} target="_blank" rel="noopener">{col.name}</a>
          <span className="collection-badge mono">{col.slug}</span>
        </div>
        <div className="header-meta">
          <span>supply {fmtNum(col.totalSupply)}</span>
          <span>·</span>
          <span>{col.uniqueHolders} holders</span>
        </div>
      </div>

      <div className="card-grid">
        <MetricCard label="Уникальные холдеры" value={fmtNum(col.uniqueHolders)}>
          <span>supply {fmtNum(col.totalSupply)}</span>
          <span>·</span>
          <span>{((col.uniqueHolders / Math.max(col.totalSupply, 1)) * 100).toFixed(1)}% уникальных</span>
        </MetricCard>

        <MetricCard label="Флор коллекции" value={`Ξ ${fmtEth(col.stats.floorPrice)}`}>
          <span>≈ {fmtUsd(floorUsd)}</span>
          <span>·</span>
          <span>{col.stats.floorPriceSymbol}</span>
        </MetricCard>

        <MetricCard label="Объём продаж (всего)" value={`Ξ ${fmtEth(col.stats.volume)}`}>
          <span>≈ {fmtUsd(col.stats.volume * ethPrice)}</span>
        </MetricCard>

        <MetricCard label="Продажи (кол-во)" value={fmtNum(col.stats.sales)}>
          {oneDay && <span className="delta-up">24ч: {oneDay.sales}</span>}
          {sevenDay && <span>7д: {sevenDay.sales}</span>}
        </MetricCard>

        <MetricCard label="Листинги (активные)" value={fmtNum(col.listings.count)}>
          <span>{listedPct.toFixed(1)}% supply</span>
          <span>·</span>
          <span>медиана Ξ {fmtEth(col.listings.medianPriceEth)}</span>
        </MetricCard>

        <MetricCard label="Объём листингов" value={`Ξ ${fmtEth(col.listings.totalVolumeEth)}`}>
          <span>≈ {fmtUsd(col.listings.totalVolumeEth * ethPrice)}</span>
        </MetricCard>
      </div>

      <WhalesTable holders={col.topHolders} ethPrice={ethPrice} />
    </section>
  );
}

export default async function Page() {
  let data: DashboardData;
  try {
    data = await fetchAllData();
  } catch (e: any) {
    return (
      <div className="container" style={{ paddingTop: 80, textAlign: "center" }}>
        <h1 style={{ fontSize: 20, marginBottom: 12 }}>Ошибка сбора данных</h1>
        <p style={{ color: "var(--text-tertiary)", fontSize: 14 }}>{e?.message || "unknown"}</p>
      </div>
    );
  }

  const [a, b] = data.collections;
  if (!a || !b) {
    return (
      <div className="container" style={{ paddingTop: 80, textAlign: "center" }}>
        <h1 style={{ fontSize: 20, marginBottom: 12 }}>Недостаточно данных</h1>
        <p style={{ color: "var(--text-tertiary)", fontSize: 14 }}>
          Загружено коллекций: {data.collections.length}
        </p>
      </div>
    );
  }

  const totalHolders = (a?.uniqueHolders || 0) + (b?.uniqueHolders || 0);
  const totalVolume = (a?.stats.volume || 0) + (b?.stats.volume || 0);
  const totalSales = (a?.stats.sales || 0) + (b?.stats.sales || 0);
  const totalListings = (a?.listings.count || 0) + (b?.listings.count || 0);

  const updatedDate = new Date(data.generatedAt);
  const updatedStr = updatedDate.toLocaleString("ru-RU", { timeZone: "Europe/Moscow" });

  return (
    <div>
      <header className="header">
        <div className="container header-inner">
          <div className="logo">
            <span className="logo-icon">🐱</span>
            Kitty PVP Dashboard
          </div>
          <div className="header-meta">
            <span><span className="live-dot" />обновлено {updatedStr} МСК</span>
            <span>·</span>
            <span>ETH ≈ {fmtUsd(data.ethPriceUsd)}</span>
            <span>·</span>
            <span> Robinhood chain</span>
          </div>
        </div>
      </header>

      <main className="container" style={{ paddingTop: 32 }}>
        <div className="summary">
          <SummaryCard label="Всего холдеров" value={fmtNum(totalHolders)} sub="2 коллекции" />
          <SummaryCard label="Объём продаж" value={`Ξ ${fmtEth(totalVolume)}`} sub={`≈ ${fmtUsd(totalVolume * data.ethPriceUsd)}`} />
          <SummaryCard label="Всего продаж" value={fmtNum(totalSales)} sub="транзакций" />
          <SummaryCard label="Активных листингов" value={fmtNum(totalListings)} sub="на OpenSea" />
        </div>

        {/* Comparison table */}
        <div className="comparison">
          <div className="comparison-title">Сравнение коллекций</div>
          <table className="compare-table">
            <thead>
              <tr>
                <th>Метрика</th>
                <th>{a?.name || "A"}</th>
                <th>{b?.name || "B"}</th>
              </tr>
            </thead>
            <tbody>
              <tr>
                <td>Уникальные холдеры</td>
                <td className={a.uniqueHolders > b.uniqueHolders ? "winner" : ""}>{fmtNum(a.uniqueHolders)}</td>
                <td className={b.uniqueHolders > a.uniqueHolders ? "winner" : ""}>{fmtNum(b.uniqueHolders)}</td>
              </tr>
              <tr>
                <td>Флор (ETH)</td>
                <td className={a.stats.floorPrice > b.stats.floorPrice ? "winner" : ""}>Ξ {fmtEth(a.stats.floorPrice)}</td>
                <td className={b.stats.floorPrice > a.stats.floorPrice ? "winner" : ""}>Ξ {fmtEth(b.stats.floorPrice)}</td>
              </tr>
              <tr>
                <td>Объём продаж (ETH)</td>
                <td className={a.stats.volume > b.stats.volume ? "winner" : ""}>Ξ {fmtEth(a.stats.volume)}</td>
                <td className={b.stats.volume > a.stats.volume ? "winner" : ""}>Ξ {fmtEth(b.stats.volume)}</td>
              </tr>
              <tr>
                <td>Продаж (кол-во)</td>
                <td className={a.stats.sales > b.stats.sales ? "winner" : ""}>{fmtNum(a.stats.sales)}</td>
                <td className={b.stats.sales > a.stats.sales ? "winner" : ""}>{fmtNum(b.stats.sales)}</td>
              </tr>
              <tr>
                <td>Активных листингов</td>
                <td className={a.listings.count > b.listings.count ? "winner" : ""}>{fmtNum(a.listings.count)}</td>
                <td className={b.listings.count > a.listings.count ? "winner" : ""}>{fmtNum(b.listings.count)}</td>
              </tr>
              <tr>
                <td>Объём листингов (ETH)</td>
                <td className={a.listings.totalVolumeEth > b.listings.totalVolumeEth ? "winner" : ""}>Ξ {fmtEth(a.listings.totalVolumeEth)}</td>
                <td className={b.listings.totalVolumeEth > a.listings.totalVolumeEth ? "winner" : ""}>Ξ {fmtEth(b.listings.totalVolumeEth)}</td>
              </tr>
            </tbody>
          </table>
        </div>

        {data.collections.map((col) => (
          <CollectionBlock key={col.slug} col={col} ethPrice={data.ethPriceUsd} />
        ))}
      </main>

      <footer className="footer">
        <div className="container" style={{ display: "flex", justifyContent: "space-between", width: "100%", flexWrap: "wrap", gap: 12 }}>
          <span>Данные: OpenSea API v2 · Blockscout Robinhood ·刷新every 6h (ISR)</span>
          <span>
            <a href="https://github.com/manfromhellxbt/kitty-pvp-dashboard" target="_blank" rel="noopener">GitHub</a>
            {" · "}
            <a href="https://opensea.io/collection/robinhood-kitties" target="_blank" rel="noopener">OpenSea</a>
            {" · "}
            <a href="https://robinhoodchain.blockscout.com" target="_blank" rel="noopener">Blockscout</a>
          </span>
        </div>
      </footer>
    </div>
  );
}
