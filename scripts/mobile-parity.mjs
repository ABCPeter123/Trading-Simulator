/**
 * Browser smoke test for feature parity across desktop and phone viewports.
 * This uses deterministic mocked API payloads. No brokerage, secrets,
 * historical market feed, or running Python backend is required.
 */
import { chromium } from "playwright";

const base = "http://127.0.0.1:5173";
const first = Date.UTC(2024, 0, 1) / 1000;
const bars = Array.from({ length: 70 }, (_, i) => {
  const close = 100 + i * 0.3 + Math.sin(i / 4) * 2;
  return { time: first + i * 86400, open: close - 0.6, high: close + 1.4,
    low: close - 1.5, close, volume: 400000 + i * 600 };
});
const last = bars.at(-1);
const day = new Date(last.time * 1000).toISOString().slice(0, 10);
const instruments = ["aapl", "spy", "qqq"].map(id => ({
  id, symbol: id.toUpperCase(), name: id.toUpperCase() + " Example",
  asset_class: "Stocks", currency: "USD", tradable: true, decimals: 2,
}));
const single = {
  id: "parity-single", asset_id: "aapl", source: "test", period: "1Y",
  resolution: "1d", risk: {stop_loss_pct: 0, take_profit_pct: 0},
  current_bar: 69, history_start: 0, live_index: 69, view_index: 69,
  viewing_past: false, checkpoint_count: 70, total_bars: 100,
  finished: false, progress_pct: 69, bars, orders: [], fills: [], events: [],
  strategy: "", equity_curve: bars.map(b => ({time: b.time, value: 100000})),
  metrics: {
    cash: 100000, quantity: 0, average_cost: 0, equity: 100000,
    position_value: 0, unrealized_pnl: 0, realized_pnl: 0,
    return_pct: 0, buy_hold_pct: 0, max_drawdown_pct: 0,
    score: 0, xp: 0, level: 1, badges: [],
  },
  examples: [], updated_at: new Date().toISOString(),
  execution_notice: "Simulated orders only.",
};
const portfolio = {
  id: "parity-portfolio", asset_ids: ["spy", "qqq"], period: "1Y",
  resolution: "1d", sources: {spy: "test", qqq: "test"}, day,
  current_step: 69, history_start: 0, live_index: 69, view_index: 69,
  viewing_past: false, checkpoint_count: 70, total_steps: 100,
  progress_pct: 69, finished: false, bars: {spy: bars, qqq: bars},
  metrics: {
    cash: 100000, exposure: 0, equity: 100000, return_pct: 0,
    equal_weight_hold_pct: 0, max_drawdown_pct: 0,
    xp: 0, level: 1, score: 0, badges: [],
  },
  positions: ["spy", "qqq"].map(asset_id => ({
    asset_id, quantity: 0, average_cost: 0, last_price: last.close,
    mark_day: day, market_value: 0, unrealized_pnl: 0,
    realized_pnl: 0, has_bar_today: true,
  })),
  orders: [], fills: [], events: [], strategy: "",
  risk: {stop_loss_pct: 0, take_profit_pct: 0},
  curve: bars.map(b => ({day: new Date(b.time * 1000).toISOString().slice(0, 10), value: 100000})),
  execution_notice: "Simulated orders only.",
};
const curve = bars.map((b, i) => ({
  day: new Date(b.time * 1000).toISOString().slice(0, 10),
  equity: 100000 + i * 5, benchmark: 100000 + i * 8, cash: 90000,
  invested: 10000 + i * 5, return_pct: i * 0.005,
  benchmark_pct: i * 0.008, fee_total: 0, drawdown_pct: 0,
}));
const report = {
  start_day: curve[0].day, end_day: curve.at(-1).day, sessions: curve.length,
  curve, summary: {
    total_return_pct: 0.3, benchmark_return_pct: 0.5, excess_return_pct: -0.2,
    max_drawdown_pct: 0, current_equity: 100345, current_cash: 90000,
    current_invested: 10345, total_fees: 0, total_notional_traded: 0,
    fill_count: 0, winning_exits: 0, losing_exits: 0,
    profitable_exit_rate_pct: null, step_sharpe: null,
  },
  rolling: {"5":null,"20":null,"60":null,"126":null,"252":null},
  allocations: [], executions: [], methodology: "Test fixture.",
};
const json = (value) => JSON.stringify(value);

function mockResponse(path) {
  if (path === "/api/instruments") return instruments;
  if (path === "/api/arcade/runs") return [{id:single.id,asset_id:"aapl",updated_at:single.updated_at}];
  if (path === "/api/arcade/parity-single") return single;
  if (path === "/api/portfolio-seasons") return [{
    id: portfolio.id, asset_ids: portfolio.asset_ids, period: "1Y", updated_at: single.updated_at,
  }];
  if (path === "/api/portfolio-seasons/parity-portfolio") return portfolio;
  if (path.endsWith("/analytics")) return report;
  if (path === "/api/strategies") return [];
  if (path === "/api/ai/status") return {
    provider: "off", model: "", ready: false, configured: false,
    remote: false, description: "Disabled in regression test.",
  };
  if (path === "/api/account") return {
    cash: 100000, equity: 100000, positions: [], fills: [], unrealized_pnl: 0,
  };
  if (path.startsWith("/api/market/")) return {
    asset_id: path.split("/").at(-1), source: "test", currency: "USD", bars,
  };
  if (path.startsWith("/api/quotes/")) return {
    asset_id: path.split("/").at(-1), source: "test",
    price: last.close, timestamp: last.time, bid: last.close - 0.01,
    ask: last.close + 0.01, fresh: true, tradable: true,
    spread_bps: 5, block_reason: null,
  };
  return null;
}

const sections = [
  ["Historical Replay", ".arc-hero", ".port-chart-wrap"],
  ["Market Data & Paper", ".market-desk", ".market-desk"],
  ["Orders & Positions", ".arc-trade-card", ".port-trade"],
  ["Strategy & AI", ".sl-library", ".sl-library"],
  ["Performance Analytics", ".an-dashboard", ".an-dashboard"],
  ["Scenario Research", ".forecast-panel", ".forecast-panel"],
  ["Trade History", ".arc-history", ".port-history"],
];

async function visible(page, selector, where) {
  try {
    await page.locator(selector).first().waitFor({state:"visible",timeout:10000});
  } catch (e) {
    throw new Error(where + ": missing or hidden " + selector + ": " + e.message);
  }
}

async function chartVisible(page, selector, where) {
  try {
    await page.waitForFunction(sel => {
      const element = document.querySelector(sel);
      if (!element) return false;
      const rect = element.getBoundingClientRect();
      const canvas = element.querySelector("canvas");
      const plot = canvas?.getBoundingClientRect();
      return rect.width >= 50 && rect.height >= 40 &&
        canvas && canvas.width > 0 && canvas.height > 0 &&
        plot && plot.width > 0 && plot.height > 0;
    },selector,{timeout:10000});
  } catch (error) {
    throw new Error(where + ": graph canvas is blank or incorrectly sized (" +
      selector + "): " + error.message);
  }
}

async function verifyMode(page, mode, viewport) {
  const selector = mode === "single" ? ".arc-layout" : ".port-layout";
  await visible(page, selector + '[data-tab="overview"]', viewport + " " + mode);
  const nav = page.locator(selector + " .ts-tab-strip").first();
  if (await nav.locator("button").count() !== sections.length) {
    throw new Error(viewport + " " + mode + ": not all seven workspace tabs rendered");
  }
  if (viewport < 741) {
    await visible(page, selector + " .ts-mobile-section select", "mobile workspace picker");
  }
  for (const [name, singleTarget, portfolioTarget] of sections) {
    const button = nav.getByRole("button",{name,exact:true});
    await button.click();
    const target = mode === "single" ? singleTarget : portfolioTarget;
    await visible(page, target, viewport + " " + mode + " " + name);
    if (name === "Historical Replay") {
      await chartVisible(page, selector+" .arc-chart-wrap .chart-canvas",
        viewport+" "+mode+" historical price graph");
    }
    if (name === "Performance Analytics") {
      await chartVisible(page, selector+" .an-chart-canvas",
        viewport+" "+mode+" equity and benchmark graph");
    }
    const active = await page.locator(selector).getAttribute("data-tab");
    const expected = ({
      "Historical Replay":"overview","Market Data & Paper":"market",
      "Orders & Positions":"execution","Strategy & AI":"strategy",
      "Performance Analytics":"analytics","Scenario Research":"scenarios",
      "Trade History":"history",
    })[name];
    if (active !== expected) throw new Error(name + ": incorrect workspace tab " + active);

    if (name === "Market Data & Paper") {
      const tabs = page.locator(".terminal-workspace-tabs");
      if (await tabs.locator("button").count() !== 3) {
        throw new Error("Market & Paper subviews inaccessible: " + viewport);
      }
      for (const [label, target] of [
        ["Market & Charts", ".chart-card"],
        ["Account & Orders", ".ticket-card"],
        ["Backtest Research", ".strategy-card"],
      ]) {
        await tabs.getByRole("button",{name:label,exact:true}).click();
        await visible(page,target,viewport + " " + label);
        if (label === "Market & Charts") {
          await chartVisible(page, ".market-desk .chart-card .chart-canvas",
            viewport + " market price graph");
        }
        if (label === "Account & Orders") {
          const symbolSelect = page.locator(".terminal-order-asset-picker select");
          await visible(page, ".terminal-order-asset-picker select",
            viewport + " direct paper order symbol selection");
          await symbolSelect.selectOption("spy");
        }
      }
    }
    const overflow = await page.evaluate(() =>
      document.documentElement.scrollWidth - document.documentElement.clientWidth);
    if (overflow > 3) {
      throw new Error(viewport + " " + mode + " " + name +
        ": root horizontally overflows by " + overflow + "px");
    }
  }
}

const browser = await chromium.launch({headless:true,args:["--no-sandbox"]});
try {
  for (const width of [320,390,768,1440]) {
    const context = await browser.newContext({viewport:{width,height:850},locale:"en-US"});
    await context.route("**/api/**", async route => {
      const path = new URL(route.request().url()).pathname;
      const response = mockResponse(path);
      await route.fulfill({
        status: response === null ? 404 : 200,
        contentType: "application/json",
        body: json(response === null ? {detail:"not mocked"} : response),
      });
    });
    const page = await context.newPage();
    page.on("pageerror", error => {
      throw new Error(width + "px unhandled page error: " + error.message);
    });
    await page.goto(base,{waitUntil:"domcontentloaded"});
    await verifyMode(page,"single",width);
    await page.locator(".sim-mode-tabs").getByRole("button",{name:"Portfolio Simulator",exact:true}).click();
    await verifyMode(page,"portfolio",width);
    const intervalPicker=page.locator(".port-interval-bar select");
    await visible(page,".port-interval-bar select",width+" portfolio interval controls");
    const values=await intervalPicker.locator("option").evaluateAll(nodes=>nodes.map(el=>el.value));
    if(JSON.stringify(values)!==JSON.stringify(["1m","5m","15m","1h","1d"]))
      throw new Error(width+"px portfolio replay intervals differ from desktop");
    await intervalPicker.selectOption("1m");
    await visible(page,".port-setup",width+" change interval opens setup");
    const newInterval=await page.locator(".port-settings select").first().inputValue();
    if(newInterval!=="1m")throw new Error("New portfolio session lost selected interval");
    await page.getByRole("button",{name:"Return to current session"}).click();
    await visible(page,".port-layout",width+" saved portfolio session preserved");
    await page.locator(".ts-lang-switch").getByRole("button",{name:"中文"}).click();
    if (await page.locator("html").getAttribute("lang") !== "zh-CN")
      throw new Error(width + "px Chinese locale not applied");
    const chineseTab = await page.locator(".port-layout .ts-tab-strip button").first().textContent();
    if (chineseTab?.includes("Historical Replay"))
      throw new Error(width + "px workspace navigation was not translated");
    await context.close();
    process.stdout.write("Feature parity passed at " + width + "px (both modes, all workspaces).\n");
  }
} finally {
  await browser.close();
}
