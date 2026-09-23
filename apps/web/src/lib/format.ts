export function formatPercent(value: number): string {
  return new Intl.NumberFormat("ja-JP", {
    style: "percent",
    maximumFractionDigits: 1,
  }).format(value);
}

