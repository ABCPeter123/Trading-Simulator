import { useEffect, useMemo, useState } from "react";
import {
  Activity,
  ArrowDownLeft,
  ArrowRight,
  ArrowUpRight,
  BarChart3,
  CandlestickChart,
  Check,
  ChevronDown,
  CircleHelp,
  Clock3,
  Database,
  LineChart,
  RotateCcw,
  Search,
  ShieldCheck,
  Wallet,
  X,
} from "lucide-react";
import { PriceChart } from "./components/PriceChart";
import {
  ASSET_CLASSES,
  ASSETS,
  createDemoSeries,
  formatMoney,
  formatPrice,
  INITIAL_CASH,
} from "./data/demoMarket";
import type { Asset, AssetClass, ChartStyle, DemoAccount, DemoTrade, TimeRange, TradeSide } from "./types";

const STORAGE_KEY = "trade-simulator-demo-account-v1";
const RANGES: TimeRange[] = ["1D", "1W", "1M", "3M", "1Y"];
const DEFAULT_ACCOUNT: DemoAccount = { cash: INITIAL_CASH, trades: [] };

function getInitialAccount(): DemoAccount {
  try {
    const raw = localStorage.getItem(STORAGE_KEY);
    if (!raw) return DEFAULT_ACCOUNT;
    const value: unknown = JSON.parse(raw);
    if (
      typeof value === "object" && value !== null &&
      "cash" in value && typeof value.cash === "number" && Number.isFinite(value.cash) && value.cash >= 0 &&
      "trades" in value && Array.isArray(value.trades) &&
      value.trades.every((trade: unknown) =>
        typeof trade === "object" && trade !== null &&
        "assetId" in trade && typeof trade.assetId === "string" && ASSETS.some((asset) => asset.id === trade.assetId) &&
        "side" in trade && (trade.side === "buy" || trade.side === "sell") &&
        "quantity" in trade && typeof trade.quantity === "number" && Number.isFinite(trade.quantity) && trade.quantity > 0 &&
        "price" in trade && typeof trade.price === "number" && Number.isFinite(trade.price) && trade.price > 0 &&
        "id" in trade && typeof trade.id === "string" &&
        "createdAt" in trade && typeof trade.createdAt === "string"
      )
    ) {
      return value as DemoAccount;
    }
  } catch {
    // Fall back to a clean local demo if browser storage is unavailable.
  }
  return DEFAULT_ACCOUNT;
}

interface Position {
  asset: Asset;
  quantity: number;
  averageCost: number;
  marketValue: number;
  unrealizedPnl: number;
}

function positionsFromTrades(trades: DemoTrade[]): Position[] {
  const holdings = new Map<string, { quantity: number; averageCost: number }>();
  for (const trade of trades) {
    const prior = holdings.get(trade.assetId) ?? { quantity: 0, averageCost: 0 };
    if (trade.side === "buy") {
      const quantity = prior.quantity + trade.quantity;
      holdings.set(trade.assetId, {
        quantity,
        averageCost: ((prior.quantity * prior.averageCost) + trade.quantity * trade.price) / quantity,
      });
    } else {
      holdings.set(trade.assetId, {
        quantity: Math.max(0, prior.quantity - trade.quantity),
        averageCost: prior.averageCost,
      });
    }
  }
  return [...holdings.entries()].flatMap(([id, holding]) => {
    const asset = ASSETS.find((item) => item.id === id);
    if (!asset || holding.quantity < 1e-9) return [];
    return [{
      asset,
      quantity: holding.quantity,
      averageCost: holding.averageCost,
      marketValue: holding.quantity * asset.referencePrice,
      unrealizedPnl: holding.quantity * (asset.referencePrice - holding.averageCost),
    }];
  });
}

function numberString(number: number) {
  return Number(number.toFixed(8)).toLocaleString("en-US", { maximumFractionDigits: 8 });
}

function App() {
  const [assetClass, setAssetClass] = useState<AssetClass>("Stocks");
  const [selectedId, setSelectedId] = useState("aapl");
  const [search, setSearch] = useState("");
  const [range, setRange] = useState<TimeRange>("1M");
  const [chartStyle, setChartStyle] = useState<ChartStyle>("candles");
  const [side, setSide] = useState<TradeSide>("buy");
  const [quantity, setQuantity] = useState("1");
  const [account, setAccount] = useState<DemoAccount>(getInitialAccount);
  const [notice, setNotice] = useState("");
  const [formError, setFormError] = useState("");
  const [activePanel, setActivePanel] = useState<"positions" | "history">("positions");

  const selectedAsset = ASSETS.find((asset) => asset.id === selectedId) ?? ASSETS[0];
  const market = useMemo(() => createDemoSeries(selectedAsset, range), [selectedAsset, range]);
  const watchlist = ASSETS.filter(
    (asset) =>
      asset.assetClass === assetClass &&
      `${asset.symbol} ${asset.name}`.toLowerCase().includes(search.trim().toLowerCase()),
  );
  const snapshots = useMemo(
    () => Object.fromEntries(ASSETS.map((asset) => [asset.id, createDemoSeries(asset, "1D").changePct])),
    [],
  );
  const positions = useMemo(() => positionsFromTrades(account.trades), [account.trades]);
  const exposure = positions.reduce((sum, position) => sum + position.marketValue, 0);
  const equity = account.cash + exposure;
  const unrealizedPnl = positions.reduce((sum, position) => sum + position.unrealizedPnl, 0);
  const heldQuantity = positions.find((position) => position.asset.id === selectedId)?.quantity ?? 0;
  const bid = selectedAsset.referencePrice * (1 - selectedAsset.spreadBps / 20_000);
  const ask = selectedAsset.referencePrice * (1 + selectedAsset.spreadBps / 20_000);
  const fill = side === "buy" ? ask : bid;
  const parsedQuantity = Number(quantity);
  const estimatedCost = Number.isFinite(parsedQuantity) && parsedQuantity > 0 ? parsedQuantity * fill : 0;
  const stepsRequireWhole = selectedAsset.assetClass === "Futures" || selectedAsset.assetClass === "Options";

  useEffect(() => {
    try {
      localStorage.setItem(STORAGE_KEY, JSON.stringify(account));
    } catch {
      // Trading UI remains usable if storage is disabled.
    }
  }, [account]);

  function changeAssetClass(next: AssetClass) {
    setAssetClass(next);
    setSearch("");
    setSelectedId(ASSETS.find((asset) => asset.assetClass === next)?.id ?? "aapl");
    setQuantity("1");
    setFormError("");
  }

  function selectAsset(asset: Asset) {
    setSelectedId(asset.id);
    setQuantity("1");
    setFormError("");
  }

  function placeDemoOrder(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setFormError("");
    if (!Number.isFinite(parsedQuantity) || parsedQuantity <= 0 || (stepsRequireWhole && !Number.isInteger(parsedQuantity))) {
      setFormError(stepsRequireWhole ? "Enter a positive whole number of demo contracts." : "Enter a valid positive quantity.");
      return;
    }
    if (side === "buy" && estimatedCost > account.cash + 1e-8) {
      setFormError("Insufficient demo cash for this order.");
      return;
    }
    if (side === "sell" && parsedQuantity > heldQuantity + 1e-8) {
      setFormError("You can only sell demo units you already hold.");
      return;
    }
    const trade: DemoTrade = {
      id: crypto.randomUUID(),
      assetId: selectedAsset.id,
      side,
      quantity: parsedQuantity,
      price: fill,
      createdAt: new Date().toISOString(),
    };
    setAccount((current) => ({
      cash: Math.max(0, current.cash + (side === "buy" ? -estimatedCost : estimatedCost)),
      trades: [...current.trades, trade],
    }));
    setNotice(`Demo ${side} filled: ${numberString(parsedQuantity)} ${selectedAsset.symbol} @ ${formatPrice(fill, selectedAsset.decimals)}.`);
    setActivePanel("positions");
  }

  function resetDemo() {
    if (!window.confirm("Reset your demo portfolio and clear all saved demo trades in this browser?")) return;
    setAccount({ cash: INITIAL_CASH, trades: [] });
    setNotice("Demo portfolio reset to $100,000.");
    setFormError("");
  }

  return (
    <div className="app-shell">
      <header className="topbar">
        <div className="brand">
          <span className="brand-mark"><BarChart3 size={21} strokeWidth={2.5} /></span>
          <div className="brand-name">TRADING<span>SIM</span><small>TERMINAL</small></div>
        </div>
        <div className="topbar-divider" />
        <div className="topnav">
          <span className="nav-active"><Activity size={15} /> Workspace</span>
          <button type="button" onClick={() => document.getElementById("portfolio-panel")?.scrollIntoView({ behavior: "smooth" })}><Wallet size={15} /> Portfolio</button>
        </div>
        <div className="topbar-right">
          <span className="local-status"><span className="local-dot" /> LOCAL MODE</span>
          <span className="topbar-balance"><span>ACCOUNT EQUITY</span><strong>{formatMoney(equity)}</strong></span>
          <button type="button" className="reset-button" onClick={resetDemo} title="Reset demo portfolio"><RotateCcw size={15} /><span>Reset</span></button>
        </div>
      </header>

      <div className="notice-strip">
        <div><Database size={14} /><strong>SANDBOX DATA</strong><span>All charts, quotes, spreads, and fills are synthetic. No live feed connected.</span></div>
        <span className="notice-right">LOCAL DEMONSTRATION · USD</span>
      </div>

      <main className="workspace">
        <aside className="watchlist-panel">
          <div className="watchlist-heading">
            <div><span className="eyebrow">MARKET EXPLORER</span><h2>Watchlist</h2></div>
            <span className="subtle-counter">{ASSETS.length} assets</span>
          </div>
          <label className="search-field">
            <Search size={16} />
            <input type="search" value={search} onChange={(e) => setSearch(e.target.value)} placeholder="Search symbols..." aria-label="Search symbols" />
            <span>⌕</span>
          </label>
          <div className="category-tabs" role="tablist" aria-label="Asset classes">
            {ASSET_CLASSES.map((group) =>
              <button key={group} role="tab" aria-selected={assetClass === group} className={assetClass === group ? "category-active" : ""} onClick={() => changeAssetClass(group)}>{group}</button>,
            )}
          </div>
          <div className="watchlist-table-label"><span>SYMBOL / NAME</span><span>LAST / CHANGE</span></div>
          <div className="watchlist-items">
            {watchlist.length === 0 ? <div className="watch-empty">No symbols match your search.</div> : watchlist.map((asset) => {
              const change = snapshots[asset.id];
              return (
                <button type="button" key={asset.id} className={`asset-item ${selectedId === asset.id ? "asset-selected" : ""}`} onClick={() => selectAsset(asset)}>
                  <span className="asset-icon" style={{ "--asset-accent": asset.accent } as React.CSSProperties}>{asset.symbol.slice(0, 1)}</span>
                  <span className="asset-details"><strong>{asset.symbol}</strong><small>{asset.name}</small></span>
                  <span className="asset-quote"><strong>{formatPrice(asset.referencePrice, asset.decimals)}</strong><small className={change >= 0 ? "positive" : "negative"}>{change >= 0 ? "+" : ""}{change.toFixed(2)}%</small></span>
                </button>
              );
            })}
          </div>
          <div className="sidebar-bottom">
            <div className="sidebar-info-icon"><ShieldCheck size={18} /></div>
            <div><strong>Safe simulation</strong><span>No real orders or financial accounts.</span></div>
          </div>
        </aside>

        <section className="center-column">
          <div className="instrument-header">
            <div className="instrument-title">
              <div className="symbol-logo" style={{ "--asset-accent": selectedAsset.accent } as React.CSSProperties}>{selectedAsset.symbol[0]}</div>
              <div>
                <div className="instrument-name"><h1>{selectedAsset.symbol}</h1><span className="market-badge">{selectedAsset.assetClass}</span></div>
                <p>{selectedAsset.name} <span>·</span> {selectedAsset.exchange}</p>
              </div>
            </div>
            <div className="instrument-price">
              <strong>{formatPrice(selectedAsset.referencePrice, selectedAsset.decimals)} <small>USD</small></strong>
              <span className={market.changePct >= 0 ? "positive" : "negative"}>
                {market.change >= 0 ? <ArrowUpRight size={14} /> : <ArrowDownLeft size={14} />}
                {market.change >= 0 ? "+" : ""}{formatPrice(market.change, selectedAsset.decimals)} ({market.changePct >= 0 ? "+" : ""}{market.changePct.toFixed(2)}%)
                <small> / SIMULATED {range}</small>
              </span>
            </div>
          </div>

          <div className="market-stats">
            <div><span>DEMO BID</span><strong>{formatPrice(bid, selectedAsset.decimals)}</strong></div>
            <div><span>DEMO ASK</span><strong>{formatPrice(ask, selectedAsset.decimals)}</strong></div>
            <div><span>RANGE HIGH</span><strong>{formatPrice(market.high, selectedAsset.decimals)}</strong></div>
            <div><span>RANGE LOW</span><strong>{formatPrice(market.low, selectedAsset.decimals)}</strong></div>
            <div className="market-stats-source"><span className="muted-dot" /> OFFLINE SAMPLE</div>
          </div>

          <section className="chart-card" aria-label="Price chart">
            <div className="chart-toolbar">
              <div className="chart-toolbar-label"><CandlestickChart size={17} /><strong>Price chart</strong><span className="demo-pill">DEMO OHLCV</span></div>
              <div className="chart-actions">
                <div className="timeframe-control" aria-label="Chart timeframe">
                  {RANGES.map((period) => <button type="button" key={period} className={range === period ? "control-active" : ""} aria-pressed={range === period} onClick={() => setRange(period)}>{period}</button>)}
                </div>
                <div className="toolbar-separator" />
                <div className="style-control">
                  <button type="button" className={chartStyle === "candles" ? "control-active" : ""} aria-label="Candlestick chart" title="Candlesticks" onClick={() => setChartStyle("candles")}><CandlestickChart size={17} /></button>
                  <button type="button" className={chartStyle === "line" ? "control-active" : ""} aria-label="Line chart" title="Line chart" onClick={() => setChartStyle("line")}><LineChart size={17} /></button>
                </div>
              </div>
            </div>
            <div className="chart-body">
              <PriceChart asset={selectedAsset} range={range} style={chartStyle} />
            </div>
            <div className="chart-footer"><span><span className="legend-dot up-dot" /> Up <span className="legend-dot down-dot" /> Down <span className="legend-volume" /> Volume</span><span>Illustrative data · <a href="https://www.tradingview.com/lightweight-charts/" target="_blank" rel="noreferrer">Charts by TradingView</a></span></div>
          </section>

          <section className="portfolio-card" id="portfolio-panel">
            <div className="section-heading">
              <div><span className="eyebrow">YOUR ACCOUNT</span><h2>Portfolio overview</h2></div>
              <span className="sim-account"><span className="local-dot" /> PAPER ACCOUNT</span>
            </div>
            <div className="portfolio-metrics">
              <div><span>NET LIQUIDATION</span><strong>{formatMoney(equity)}</strong><small>Cash + marked demo positions</small></div>
              <div><span>AVAILABLE CASH</span><strong>{formatMoney(account.cash)}</strong><small>USD buying power</small></div>
              <div><span>MARKET EXPOSURE</span><strong>{formatMoney(exposure)}</strong><small>{positions.length} open symbols</small></div>
              <div><span>UNREALIZED P&L</span><strong className={unrealizedPnl >= 0 ? "positive" : "negative"}>{unrealizedPnl >= 0 ? "+" : "-"}{formatMoney(Math.abs(unrealizedPnl))}</strong><small>At synthetic reference prices</small></div>
            </div>
            <div className="portfolio-tab-row">
              <div className="portfolio-tabs" role="tablist" aria-label="Portfolio view">
                <button type="button" role="tab" aria-selected={activePanel === "positions"} className={activePanel === "positions" ? "portfolio-tab-active" : ""} onClick={() => setActivePanel("positions")}>Positions <span>{positions.length}</span></button>
                <button type="button" role="tab" aria-selected={activePanel === "history"} className={activePanel === "history" ? "portfolio-tab-active" : ""} onClick={() => setActivePanel("history")}>Order history <span>{account.trades.length}</span></button>
              </div>
            </div>
            <div className="table-scroll">
              {activePanel === "positions" ? (
                positions.length ? <table className="data-table">
                  <thead><tr><th>ASSET</th><th>QTY</th><th>AVG COST</th><th>MARKET VALUE</th><th>UNREALIZED P&L</th></tr></thead>
                  <tbody>{positions.map((position) => <tr key={position.asset.id}>
                    <td><strong>{position.asset.symbol}</strong><small>{position.asset.assetClass}</small></td>
                    <td>{numberString(position.quantity)}</td>
                    <td>{formatPrice(position.averageCost, position.asset.decimals)}</td>
                    <td>{formatMoney(position.marketValue)}</td>
                    <td className={position.unrealizedPnl >= 0 ? "positive" : "negative"}>{position.unrealizedPnl >= 0 ? "+" : "-"}{formatMoney(Math.abs(position.unrealizedPnl))}</td>
                  </tr>)}</tbody>
                </table> : <div className="empty-state"><Wallet size={25} /><strong>No open positions</strong><span>Choose a symbol and place a demo buy to get started.</span></div>
              ) : (
                account.trades.length ? <table className="data-table">
                  <thead><tr><th>TIME</th><th>SYMBOL</th><th>SIDE</th><th>QTY</th><th>FILL PRICE</th></tr></thead>
                  <tbody>{[...account.trades].reverse().map((trade) => {
                    const asset = ASSETS.find((item) => item.id === trade.assetId)!;
                    return <tr key={trade.id}>
                      <td>{new Date(trade.createdAt).toLocaleString()}</td>
                      <td><strong>{asset.symbol}</strong></td>
                      <td className={trade.side === "buy" ? "positive" : "negative"}>{trade.side.toUpperCase()}</td>
                      <td>{numberString(trade.quantity)}</td>
                      <td>{formatPrice(trade.price, asset.decimals)}</td>
                    </tr>;
                  })}</tbody>
                </table> : <div className="empty-state"><Clock3 size={25} /><strong>No trades recorded</strong><span>Executed demo market orders will appear here.</span></div>
              )}
            </div>
          </section>
        </section>

        <aside className="ticket-column">
          <section className="ticket-card">
            <div className="ticket-heading"><div><span className="eyebrow">TRADE EXECUTION</span><h2>Order ticket</h2></div><span className="ticket-icon"><ArrowRight size={18} /></span></div>
            <div className="ticket-security">
              <span className="ticket-security-symbol">{selectedAsset.symbol}</span><span className="ticket-security-class">{selectedAsset.assetClass} <ChevronDown size={12} /></span>
            </div>
            <div className="side-switch">
              <button type="button" className={side === "buy" ? "buy-active" : ""} onClick={() => { setSide("buy"); setFormError(""); }}>Buy / Long</button>
              <button type="button" className={side === "sell" ? "sell-active" : ""} onClick={() => { setSide("sell"); setFormError(""); }}>Sell / Close</button>
            </div>
            <form onSubmit={placeDemoOrder}>
              <div className="field-head"><label htmlFor="order-type">Order type</label><CircleHelp size={14} /></div>
              <select id="order-type" value="market" onChange={() => {}} aria-label="Order type">
                <option value="market">Market (demo instant fill)</option>
              </select>
              <div className="field-head"><label htmlFor="order-quantity">Quantity {stepsRequireWhole ? "(contracts)" : "(units)"}</label><span className="field-hint">Held: {numberString(heldQuantity)}</span></div>
              <div className="quantity-field"><input id="order-quantity" type="number" inputMode="decimal" step={stepsRequireWhole ? "1" : "any"} min={stepsRequireWhole ? "1" : "0.00000001"} value={quantity} onChange={(e) => { setQuantity(e.target.value); setFormError(""); }} required /><span>{stepsRequireWhole ? "CONTRACTS" : "UNITS"}</span></div>
              <div className="ticket-summary">
                <div><span>Reference price</span><strong>{formatPrice(selectedAsset.referencePrice, selectedAsset.decimals)}</strong></div>
                <div><span>{side === "buy" ? "Est. ask fill" : "Est. bid fill"}</span><strong>{formatPrice(fill, selectedAsset.decimals)}</strong></div>
                <div><span>Illustrative spread</span><strong>{selectedAsset.spreadBps} bps</strong></div>
                <div className="ticket-total"><span>Est. order value</span><strong>{formatMoney(estimatedCost)}</strong></div>
              </div>
              {formError && <p className="form-error" role="alert">{formError}</p>}
              <button className={`submit-order ${side === "sell" ? "submit-sell" : ""}`} type="submit">{side === "buy" ? <ArrowUpRight size={19} /> : <ArrowDownLeft size={19} />} Place demo {side}</button>
            </form>
            <div className="ticket-footnote"><ShieldCheck size={15} /><span>Long-only toy ledger. No contract multipliers, commissions, or actual exchange fills.</span></div>
          </section>
          <section className="account-card">
            <div className="account-heading"><span>SIMULATION STATUS</span><span className="account-status"><span className="local-dot" /> ACTIVE</span></div>
            <div className="account-item"><Database size={17} /><div><strong>Market data</strong><span>Deterministic sample candles</span></div><span className="offline-tag">OFFLINE</span></div>
            <div className="account-item"><Clock3 size={17} /><div><strong>Session</strong><span>Frozen historical sample</span></div></div>
            <div className="account-item"><Check size={17} /><div><strong>Order engine</strong><span>Basic browser simulation</span></div></div>
          </section>
          <div className="build-note"><span className="build-dot" /> Trading Simulator <span>v0.1 · FOUNDATION</span></div>
        </aside>
      </main>
      {notice && <div className="toast" role="status"><Check size={17} /><span>{notice}</span><button type="button" onClick={() => setNotice("")} aria-label="Dismiss message"><X size={16} /></button></div>}
    </div>
  );
}

export default App;
