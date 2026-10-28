import { useEffect, useRef, useState } from "react";
import { crore, post, signedPct } from "../api";
import { Note, Takeaway, tileColour, useFetch } from "../components/Common";

interface Presets {
  presets: { id: string; label: string }[];
  sectors: { sector_id: string; name: string; budget_lines: string[] }[];
}
interface SectorResult {
  sector_id: string;
  is_control: boolean;
  change_pct: number;
  be_actual_cr: number | null;
  be_scenario_cr: number | null;
  surprise_actual_pct: number | null;
  surprise_scenario_pct: number | null;
  expected_actual: number;
  expected_scenario: number;
  expected_change: number;
  rank_actual: number;
  rank_scenario: number;
  rank_change: number;
  reasons: string[];
}
interface Result {
  sectors: SectorResult[];
  takeaway: string;
  disclaimer: string;
  applied_changes_pct: Record<string, number>;
}

export default function WhatIf({ budgetId }: { budgetId: string }) {
  const presets = useFetch<Presets>("/simulate/presets");
  const [preset, setPreset] = useState("actual");
  const [changes, setChanges] = useState<Record<string, number>>({});
  const [result, setResult] = useState<Result | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const timer = useRef<number | undefined>(undefined);
  // This screen simulates unlocked full budgets only; a locked or interim budget falls back to the latest simulable one.
  const simBudget = presets.data?.presets.some((p) => p.id === `replay:${budgetId}`) ? budgetId : "FY2023-24";

  useEffect(() => {
    if (!presets.data) return;
    window.clearTimeout(timer.current);
    timer.current = window.setTimeout(() => {
      setBusy(true);
      post<Result>("/simulate", { budget_id: simBudget, changes, preset })
        .then((r) => {
          setResult(r);
          setError(null);
        })
        .catch((e: Error) => setError(e.message))
        .finally(() => setBusy(false));
    }, 350);
    return () => window.clearTimeout(timer.current);
  }, [presets.data, simBudget, changes, preset]);

  const applyPreset = (id: string) => {
    setPreset(id);
    setChanges({});
  };
  return (
    <>
      <h1>5. What-if simulator: what if the allocation were different?</h1>
      <p className="muted">
        Budget: {simBudget}. Move a slider to change a sector's allocation; the surprise and growth features are rebuilt and the Tier-1 LightGBM model re-scores all 15 sectors.
      </p>
      <Note text={result?.disclaimer} />
      <div className="controls">
        <label>
          Preset{" "}
          <select value={preset} onChange={(e) => applyPreset(e.target.value)} aria-label="Preset">
            {presets.data?.presets.map((p) => (
              <option key={p.id} value={p.id}>
                {p.label}
              </option>
            ))}
          </select>
        </label>
        <button className="btn" onClick={() => applyPreset("actual")}>
          Reset
        </button>
        {busy && <span className="muted">re-scoring...</span>}
      </div>
      {error && <p className="note" role="alert">{error}</p>}
      <Takeaway text={result?.takeaway} />
      <div className="grid cols-2">
        <div className="card">
          <h3>Allocation change per sector</h3>
          {presets.data?.sectors.map((s) => (
            <div className="slider-row" key={s.sector_id}>
              <label htmlFor={`sl-${s.sector_id}`} title={s.budget_lines.join(", ")}>
                {s.sector_id}
              </label>
              <input id={`sl-${s.sector_id}`} type="range" min={-50} max={100} step={5} value={Math.max(-50, Math.min(100, changes[s.sector_id] ?? result?.applied_changes_pct[s.sector_id] ?? 0))}
                onChange={(e) => setChanges({ ...changes, [s.sector_id]: Number(e.target.value) })} />
              <span className="muted">{(changes[s.sector_id] ?? result?.applied_changes_pct[s.sector_id] ?? 0).toFixed(0)}%</span>
            </div>
          ))}
        </div>
        <div className="card" data-testid="sim-grid">
          <h3>Re-ranked sectors (scenario)</h3>
          <p className="muted">Each tile shows the change in expected excess return against the actual budget; absolute levels are in the table and are in-sample.</p>
          <div className="grid" style={{ gridTemplateColumns: "repeat(auto-fill, minmax(150px, 1fr))" }}>
            {[...(result?.sectors ?? [])]
              .sort((a, b) => a.rank_scenario - b.rank_scenario)
              .map((s) => (
                <div key={s.sector_id} className="tile" style={{ background: tileColour(s.expected_change, 0.1), cursor: "default" }}>
                  <span className="rankbadge">#{s.rank_scenario}</span>
                  <div className="name">{s.sector_id}</div>
                  <div title="Change in the model's expected excess return against the actual budget">{s.expected_change >= 0 ? "+" : ""}{(s.expected_change * 100).toFixed(1)} pp</div>
                  <div className={s.rank_change > 0 ? "up" : s.rank_change < 0 ? "down" : "muted"}>
                    {s.rank_change > 0 ? `up ${s.rank_change}` : s.rank_change < 0 ? `down ${-s.rank_change}` : "no change"}
                  </div>
                </div>
              ))}
          </div>
        </div>
      </div>
      <h2>Difference against the actual budget</h2>
      <div className="tablewrap">
        <table data-testid="sim-diff">
          <thead>
            <tr>
              <th>Sector</th>
              <th className="n">Allocation change</th>
              <th className="n">New allocation</th>
              <th className="n">Surprise before</th>
              <th className="n">Surprise after</th>
              <th className="n">Expected excess before (in-sample)</th>
              <th className="n">after</th>
              <th className="n">Rank</th>
            </tr>
          </thead>
          <tbody>
            {result?.sectors.map((s) => (
              <tr key={s.sector_id}>
                <td>{s.sector_id}</td>
                <td className="n">{s.change_pct.toFixed(1)}%</td>
                <td className="n">{crore(s.be_scenario_cr)}</td>
                <td className="n">{s.surprise_actual_pct === null ? "n/a" : `${s.surprise_actual_pct.toFixed(1)}%`}</td>
                <td className="n">{s.surprise_scenario_pct === null ? "n/a" : `${s.surprise_scenario_pct.toFixed(1)}%`}</td>
                <td className="n">{signedPct(s.expected_actual)}</td>
                <td className="n">{signedPct(s.expected_scenario)}</td>
                <td className="n">{s.rank_actual} to {s.rank_scenario}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </>
  );
}
