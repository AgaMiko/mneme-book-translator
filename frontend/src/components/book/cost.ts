import type { CostGuardState } from "@/lib/api/client";

export function usd(n: number): string {
  return n > 0 && n < 0.01 ? "under $0.01" : `$${n.toFixed(2)}`;
}

/** "$0.54 spent of ~$3.14", or null before anything was spent. */
export function costSummary(state: CostGuardState | undefined): string | null {
  if (!state || state.spent_usd === 0) return null;
  return state.estimate_usd > 0
    ? `${usd(state.spent_usd)} spent of ~${usd(state.estimate_usd)}`
    : `${usd(state.spent_usd)} spent`;
}
