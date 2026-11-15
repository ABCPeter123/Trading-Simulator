import type { MarketBar } from "./api";
import type { Asset, TradeSide } from "./types";

export interface ReplayFill {
  side: TradeSide; quantity: number; price: number; fee: number; time: number;
}
export interface PendingReplayOrder { side: TradeSide; quantity: number }
export interface ReplayAccount {
  cash: number; quantity: number; averageCost: number; realizedPnl: number;
  fills: ReplayFill[]; pending: PendingReplayOrder | null;
}
export const NEW_REPLAY: ReplayAccount = {
  cash: 100_000, quantity: 0, averageCost: 0, realizedPnl: 0, fills: [], pending: null,
};
export const replayStartIndex = (length: number) => Math.min(length - 2, Math.max(25, Math.floor(length * 0.3)));

export function replayFee(asset: Asset, qty: number, price: number) {
  const notional = qty * price;
  if (asset.assetClass === "Crypto") return Math.round(notional * 0.006 * 100) / 100;
  if (asset.assetClass === "Forex") return Math.round(notional * 0.0002 * 100) / 100;
  return Math.round(Math.max(1, qty * 0.005) * 100) / 100;
}
export function replayFillPrice(asset: Asset, side: TradeSide, opening: number) {
  const impact = asset.spreadBps / 20000 + 2 / 10000;
  return opening * (side === "buy" ? 1 + impact : 1 - impact);
}
/** Orders queued after bar N closes fill at bar N+1 OPEN, not N close. */
export function advanceReplay(account: ReplayAccount, nextBar: MarketBar, asset: Asset): {account: ReplayAccount; message?: string} {
  if (!account.pending) return {account};
  const {side, quantity} = account.pending;
  const price = replayFillPrice(asset, side, nextBar.open);
  const fee = replayFee(asset, quantity, price);
  const value = price * quantity;
  const pending = null;
  if (side === "buy" && value + fee > account.cash + 0.000001) {
    return {account: {...account, pending}, message: "Replay buy rejected at next open: insufficient cash."};
  }
  if (side === "sell" && quantity > account.quantity + 0.000001) {
    return {account: {...account, pending}, message: "Replay sell rejected at next open: insufficient holdings."};
  }
  const nextQuantity = account.quantity + (side === "buy" ? quantity : -quantity);
  const cash = account.cash + (side === "buy" ? -value - fee : value - fee);
  const averageCost = side === "buy"
    ? (account.quantity * account.averageCost + value + fee) / nextQuantity
    : nextQuantity < 1e-9 ? 0 : account.averageCost;
  const realizedPnl = account.realizedPnl + (side === "sell" ? quantity * (price - account.averageCost) - fee : 0);
  const fill: ReplayFill = {side, quantity, price, fee, time: nextBar.time};
  return {
    account: {
      ...account, cash, quantity: Math.max(0, nextQuantity),
      averageCost, realizedPnl, fills: [fill, ...account.fills], pending,
    },
    message: `Replay ${side} filled at the next bar open: ${quantity} × ${price.toFixed(asset.decimals)} (fee $ ${fee.toFixed(2)}).`,
  };
}
