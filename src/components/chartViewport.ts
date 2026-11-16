/** Chart windows are views over complete loaded history, not truncated datasets. */
export function minBarSpacingFor(pixelWidth: number, count: number): number {
  // The library defaults to 0.5 px/bar. That silently prevents fitContent()
  // from including a multi-year history on phone-size canvases.
  if (!Number.isFinite(count) || count <= 0) return 0.5;
  const usableWidth=Math.max(1,pixelWidth-85);
  return Math.max(0.001,Math.min(0.5,usableWidth/(count+4)));
}

export function isEntireRangeVisible(
  range: {from:number;to:number}|null, count: number,
): boolean {
  return count>0&&range!==null&&range.from<=0.5&&range.to>=count-1.5;
}

