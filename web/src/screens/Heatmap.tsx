import { useState } from "react";
import { pct, signedPct, type HeatmapResponse } from "../api";
import { Note, Num, Status, Takeaway, tileColour, useFetch, Whisker } from "../components/Common";

export const MODELS = ["tier1_blend", "tier1_stack", "lgbm_ranker", "bayes_hier"];

export default function Heatmap({ budgetId, openSector }: { budgetId: string; openSector: (id: string) => void }) {
  const [model, setModel] = useState("tier1_blend");
  const state = useFetch<HeatmapResponse>(`/budgets/${budgetId}/forecast?model=${model}`);
  return (
    <>
      <h1>2. Sector heat-map: which sectors should outperform?</h1>
      <div className="controls">
        <label>
          Model{" "}
          <select value={model} onChange={(e) => setModel(e.target.value)} aria-label="Model">
            {MODELS.map((m) => (
              <option key={m}>{m}</option>
            ))}
          </select>
        </label>
        <span className="muted">Expected excess return over the Nifty 500, next 12 months; whisker = 80% interval; shaded by expected value.</span>
      </div>
      <Status state={state}>
        {(d) => (
          <>
            <Takeaway text={d.takeaway} />
            <Note text={d.note} />
            {d.sectors.length > 0 && (
              <>
                <p className="muted">
                  Out-of-sample walk-forward forecast for {d.budget_id}. {d.interval}. Realised excess return shown for transparency (known only later).
                </p>
                <div className="grid cols-3" data-testid="heatmap">
                  {d.sectors.map((s) => (
                    <div key={s.sector_id} className="tile" role="link" tabIndex={0} style={{ background: tileColour(s.expected_excess) }} onClick={() => openSector(s.sector_id)}
                      onKeyDown={(e) => { if (e.key === "Enter") openSector(s.sector_id); }} aria-label={`${s.sector_id}, rank ${s.rank}, expected ${signedPct(s.expected_excess)}; open the deep-dive`}>
                      <span className="rankbadge">#{s.rank}{s.is_control ? " control" : ""}</span>
                      <div className="name">{s.sector_id}</div>
                      <div className="big"><Num value={signedPct(s.expected_excess)} source={s.source_ref} /></div>
                      <Whisker p10={s.p10} p90={s.p90} mark={s.expected_excess} />
                      <div className="muted">
                        {signedPct(s.p10, 0)} to {signedPct(s.p90, 0)} | P(beat) {pct(s.p_beat, 0)}
                      </div>
                      <div className="muted">realised {signedPct(s.realised_excess, 0)}</div>
                    </div>
                  ))}
                </div>
                <p className="muted">IT Services is the control sector: the budget should not move it, so it is shown but not ranked among the 14.</p>
              </>
            )}
          </>
        )}
      </Status>
    </>
  );
}
