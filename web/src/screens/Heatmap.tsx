import { useState } from "react";
import { pct, signedPct, type HeatmapResponse } from "../api";
import { InfoTip, sectorLabel } from "../components/ui";
import { Note, Num, Status, Takeaway, tileColour, useFetch, Whisker } from "../components/Common";

export const MODELS = ["tier1_blend", "tier1_stack", "lgbm_ranker", "bayes_hier"];

export default function Heatmap({ budgetId, openSector }: { budgetId: string; openSector: (id: string) => void }) {
  const [model, setModel] = useState("tier1_blend");
  const state = useFetch<HeatmapResponse>(`/budgets/${budgetId}/forecast?model=${model}`);
  return (
    <>
      <div className="titlerow">
        <div>
          <h1>Sector heat-map<span className="title-i"><InfoTip title="Sector heat-map">Fifteen sector cards ranked by the model's expected excess return over the Nifty 500 for the next 12 months. The capsule is the 80% interval, the white dot the expected value, and the tint shows how large the expectation is. P(beat) is the model's chance of beating the index; realised shows what actually happened (known only later). Click a card for its reasons.</InfoTip></span></h1>
          <p className="lead">Expected excess return over the Nifty 500 for the next 12 months. The capsule is the 80% interval, the white dot the expected value, the tint the size of the expectation.</p>
        </div>
        <div className="seg ctrl" role="tablist" aria-label="Model">
          {MODELS.map((m) => (
            <button key={m} role="tab" aria-selected={model === m} onClick={() => setModel(m)}>{m.replace("_", " ")}</button>
          ))}
        </div>
      </div>
      <Status state={state}>
        {(d) => (
          <>
            <Takeaway text={d.takeaway} />
            <Note text={d.note} />
            {d.sectors.length > 0 && (
              <>
                <p className="muted" style={{ margin: "0 0 14px" }}>
                  Out-of-sample walk-forward forecast for {d.budget_id}. {d.interval}. Realised excess return is shown for transparency (known only later).
                </p>
                <div className="tilegrid" data-testid="heatmap">
                  {d.sectors.map((s) => (
                    <div key={s.sector_id} className="tile" role="link" tabIndex={0} style={{ background: tileColour(s.expected_excess, 0.2) }} onClick={() => openSector(s.sector_id)}
                      onKeyDown={(e) => { if (e.key === "Enter") openSector(s.sector_id); }} aria-label={`${s.sector_id}, rank ${s.rank}, expected ${signedPct(s.expected_excess)}; open the deep-dive`}>
                      <span className="rankbadge chip">#{s.rank}{s.is_control ? " control" : ""}</span>
                      <div className="name">{sectorLabel(s.sector_id)}</div>
                      <div className="big"><Num value={signedPct(s.expected_excess)} source={s.source_ref} /></div>
                      <Whisker p10={s.p10} p90={s.p90} mark={s.expected_excess} />
                      <div className="sub">{signedPct(s.p10, 0)} to {signedPct(s.p90, 0)} · P(beat) {pct(s.p_beat, 0)}</div>
                      <div className="sub">realised {signedPct(s.realised_excess, 0)}</div>
                    </div>
                  ))}
                </div>
                <p className="muted" style={{ marginTop: 14 }}>IT Services is the control sector: the budget should not move it, so it is shown but not ranked among the 14.</p>
              </>
            )}
          </>
        )}
      </Status>
    </>
  );
}
