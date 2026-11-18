/** Reject blank, invalid, or out-of-range percentages before sending research jobs. */
export function validatedPercent(value: string, label: string, min: number, max: number): number {
  const trimmed = value.trim();
  const parsed = Number(trimmed);
  if (!trimmed || !Number.isFinite(parsed) || parsed < min || parsed > max) {
    throw new Error(`${label} must be between ${min}% and ${max}%.`);
  }
  return parsed;
}
