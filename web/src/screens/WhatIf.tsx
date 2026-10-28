import { useEffect, useRef, useState } from "react";
import { crore, post, signedPct } from "../api";
import { Note, Takeaway, tileColour, useFetch } from "../components/Common";
import { Card, sectorLabel } from "../components/ui";

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
  const sliderBg = (v: number) => {
    const zero = (50 / 150) * 100;
    const val = ((v + 50) / 150) * 100;
    const [l, r, c] = v >= 0 ? [zero, val, "#2a55e8"] : [val, zero, "#ee4d86"];
    return `linear-gradient(90deg, transparent 0 ${l}%, ${c} ${l}% ${r}%, transparent ${r}% 100%), var(--card-2)`;
  };
  return (
    <>
      <div className="titlerow">
        <div>
          <h1>What-if simulator</h1>
          <p className="lead">Budget {simBudget}. Move a slider to change a sector's allocation: the surprise and growth features are rebuilt and the Tier-1 model re-scores all 15 sectors.</p>
        </div>
        <div className="ctrl">
          <select className="pillsel" value={preset} onChange={(e) => applyPreset(e.target.value)} aria-label="Preset">
            {presets.data?.presets.map((p) => (
              <option key={p.id} value={p.id}>
                {p.label}
              </option>
            ))}
          </select>
          <button className="btn" onClick={() => applyPreset("actual")}>Reset</button>
          {busy && <span className="muted">re-scoring...</span>}
        </div>
      </div>
      <Note text={result?.disclaimer} />
      {error && <p className="note" role="alert">{error}</p>}
      <Takeaway text={result?.takeaway} />
      <div className="bento">
        <Card className="s5" title="Allocation change per sector" caption="Percent change of each sector's budget estimate">
          {presets.data?.sectors.map((s) => {
            const v = Math.max(-50, Math.min(100, changes[s.sector_id] ?? result?.applied_changes_pct[s.sector_id] ?? 0));
            return (
              <div className="slider-row" key={s.sector_id}>
                <label htmlFor={`sl-${s.sector_id}`} title={s.budget_lines.join(", ")} style={{ textTransform: "capitalize" }}>
                  {sectorLabel(s.sector_id)}
                </label>
                <input id={`sl-${s.sector_id}`} type="range" min={-50} max={100} step={5} value={v} style={{ background: sliderBg(v) }} onChange={(e) => setChanges({ ...changes, [s.sector_id]: Number(e.target.value) })} />
                <span className="chip">{v > 0 ? "+" : ""}{v.toFixed(0)}%</span>
              </div>
            );
          })}
        </Card>
        <Card className="s7" title="Re-ranked sectors" caption="Change in expected excess return against the actual budget; absolute levels are in the table and are in-sample">
          <div data-testid="sim-grid" className="tilegrid" style={{ gridTemplateColumns: "repeat(auto-fill, minmax(150px, 1fr))" }}>
            {[...(result?.sectors ?? [])]
              .sort((a, b) => a.rank_scenario - b.rank_scenario)
              .map((s) => (
                <div key={s.sector_id} className="tile" style={{ background: tileColour(s.expected_change, 0.1), cursor: "default", padding: "14px 16px" }}>
                  <span className="rankbadge chip">#{s.rank_scenario}</span>
                  <div className="name" style={{ fontSize: 13 }}>{sectorLabel(s.sector_id)}</div>
                  <div className="big" style={{ fontSize: 24, marginTop: 10 }} title="Change in the model's expected excess return against the actual budget">{s.expected_change >= 0 ? "+" : ""}{(s.expected_change * 100).toFixed(1)}<small style={{ fontSize: 12, marginLeft: 3 }}>pp</small></div>
                  <div className={`sub ${s.rank_change > 0 ? "up" : s.rank_change < 0 ? "down" : ""}`}>
                    {s.rank_change > 0 ? `up ${s.rank_change}` : s.rank_change < 0 ? `down ${-s.rank_change}` : "no change"}
                  </div>
                </div>
              ))}
          </div>
        </Card>
        <Card className="s12" title="Difference against the actual budget">
          <div className="tablewrap">
            <table data-testid="sim-diff">
              <thead>
                <tr>
                  <th>Sector</th>
                  <th className="n">Allocation change</th>
                  <th className="n">New allocation</th>
                  <th className="n">Surprise before</th>
                  <th className="n">Surprise after</th>
                  <th className="n">Expected before (in-sample)</th>
                  <th className="n">after</th>
                  <th className="n">Rank</th>
                </tr>
              </thead>
              <tbody>
                {result?.sectors.map((s) => (
                  <tr key={s.sector_id}>
                    <td style={{ textTransform: "capitalize" }}>{sectorLabel(s.sector_id)}</td>
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
        </Card>
      </div>
    </>
  );
}
