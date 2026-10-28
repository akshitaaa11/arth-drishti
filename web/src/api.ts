export const DISCLAIMER = "Research tool, not investment advice.";

export async function get<T>(path: string): Promise<T> {
  const res = await fetch(path);
  if (!res.ok) {
    let detail = res.statusText;
    try {
      detail = (await res.json()).detail ?? detail;
    } catch {
      /* not JSON */
    }
    throw new Error(String(detail));
  }
  return res.json() as Promise<T>;
}

export async function post<T>(path: string, body: unknown): Promise<T> {
  const res = await fetch(path, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) });
  if (!res.ok) {
    let detail = res.statusText;
    try {
      detail = (await res.json()).detail ?? detail;
    } catch {
      /* not JSON */
    }
    throw new Error(String(detail));
  }
  return res.json() as Promise<T>;
}

export interface Budget {
  budget_id: string;
  fiscal_year: string;
  presented_on: string;
  budget_type: string;
  status: string;
  has_forecast: boolean;
  has_budget_lines: boolean;
  has_speech: boolean;
}
export interface BudgetsResponse {
  budgets: Budget[];
  latest_forecast_budget: string;
}
export interface SectorForecast {
  entity: string;
  sector_id: string;
  expected_excess: number;
  p10: number;
  p90: number;
  p_beat: number;
  rank: number;
  reasons: string[];
  realised_excess: number | null;
  is_control: boolean;
  interval_method: string;
  source_ref: string;
}
export interface HeatmapResponse {
  budget_id: string;
  model: string;
  status: string;
  note: string | null;
  sectors: SectorForecast[];
  takeaway: string | null;
  interval: string;
}

export const pct = (v: number | null | undefined, digits = 1): string => (v === null || v === undefined ? "n/a" : `${(v * 100).toFixed(digits)}%`);
export const signedPct = (v: number | null | undefined, digits = 1): string => (v === null || v === undefined ? "n/a" : `${v >= 0 ? "+" : ""}${(v * 100).toFixed(digits)}%`);
export const crore = (v: number | null | undefined): string => (v === null || v === undefined ? "n/a" : `Rs ${Math.round(v).toLocaleString("en-IN")} cr`);
