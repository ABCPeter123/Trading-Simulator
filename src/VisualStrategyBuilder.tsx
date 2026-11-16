import { useI18n } from "./i18n";
import { useState } from "react";
import { Plus, WandSparkles } from "lucide-react";

interface Props { onAdd: (rule: string) => void }
const EXPRS = ["PRICE","SMA","RSI","NUMBER"] as const;
type Expression = typeof EXPRS[number];

export default function VisualStrategyBuilder({onAdd}: Props) {
  const {t} = useI18n();
  const [left, setLeft] = useState<Expression>("SMA");
  const [right, setRight] = useState<Expression>("SMA");
  const [leftValue, setLeftValue] = useState("10");
  const [rightValue, setRightValue] = useState("30");
  const [op, setOp] = useState("CROSSES ABOVE");
  const [side, setSide] = useState("BUY");
  const [percent, setPercent] = useState("25");
  const [error, setError] = useState("");

  function expression(kind: Expression, raw: string): string | null {
    if (kind === "PRICE") return "PRICE";
    const number = Number(raw);
    if (!Number.isFinite(number)) return null;
    if (kind === "NUMBER") return number >= 0 && number <= 1_000_000_000 ? String(number) : null;
    return Number.isInteger(number) && number >= 2 && number <= 100 ? `${kind}(${number})` : null;
  }

  function addRule() {
    const first = expression(left, leftValue);
    const second = expression(right, rightValue);
    const pct = Number(percent);
    if (!first || !second || !Number.isFinite(pct) || pct <= 0 || pct > 100) {
      setError("Indicator periods must be 2-100. Trade percentage must be 0-100.");
      return;
    }
    setError("");
    onAdd(`WHEN ${first} ${op} ${second} ${side} ${pct}%`);
  }

  return <div className="arc-visual-builder">
    <div className="arc-visual-head"><WandSparkles size={16}/><strong>{t("Build a rule visually")}</strong><span>{t("No code required")}</span></div>
    <div className="arc-visual-grid">
      <label>WHEN
        <select aria-label={t("Left indicator")} value={left} onChange={e=>setLeft(e.target.value as Expression)}>{EXPRS.map(v=><option key={v}>{v}</option>)}</select>
      </label>
      {left!=="PRICE"&&<label>{left==="NUMBER"?"Price threshold":"Lookback period"}
        <input aria-label={t("Left indicator value")} type="number" value={leftValue} onChange={e=>setLeftValue(e.target.value)}/>
      </label>}
      <label>CONDITION
        <select aria-label={t("Strategy condition")} value={op} onChange={e=>setOp(e.target.value)}>{["CROSSES ABOVE","CROSSES BELOW","ABOVE","BELOW"].map(v=><option key={v}>{v}</option>)}</select>
      </label>
      <label>COMPARED TO
        <select aria-label={t("Right indicator")} value={right} onChange={e=>setRight(e.target.value as Expression)}>{EXPRS.map(v=><option key={v}>{v}</option>)}</select>
      </label>
      {right!=="PRICE"&&<label>{right==="NUMBER"?"Price threshold":"Lookback period"}
        <input aria-label={t("Right indicator value")} type="number" value={rightValue} onChange={e=>setRightValue(e.target.value)}/>
      </label>}
      <label>THEN
        <select aria-label={t("Trade action")} value={side} onChange={e=>setSide(e.target.value)}><option value="BUY">{t("BUY")}</option><option value="SELL">{t("SELL")}</option></select>
      </label>
      <label>POSITION SIZE %
        <input aria-label={t("Strategy percent")} type="number" min="0.01" max="100" step="any" value={percent} onChange={e=>setPercent(e.target.value)}/>
      </label>
    </div>
    {error&&<div className="arc-error" role="alert">{error}</div>}
    <button type="button" className="arc-visual-add" onClick={addRule}><Plus size={16}/> {t("Add rule to strategy")}</button>
  </div>;
}
