import { Note, Num, Status, Takeaway, useFetch } from "../components/Common";
import { Card, HBars } from "../components/ui";

interface Resp {
  sectors: { sector_id: string; sector_name: string; budget_year: string; credibility_pct: number; years_used: number; source_ref: string }[];
  ministries: { ministry: string; mean_gap_pct: number; n_years: number; source_ref: string }[];
  cga_monthly: { available: boolean; note: string };
  takeaway: string | null;
  definition: string;
}

export default function PromiseScreen() {
  const state = useFetch<Resp>("/credibility");
  return (
    <>
      <div className="titlerow">
        <div>
          <h1>Promise vs reality</h1>
          <p className="lead">Is the money being spent? The gap between what a budget promised and what the next accounts show.</p>
        </div>
      </div>
      <Status state={state}>
        {(d) => {
          const mins = d.ministries.filter((m) => !/^(total|other)/i.test(m.ministry)).slice(0, 10);
          const secs = [...d.sectors].sort((a, b) => a.credibility_pct - b.credibility_pct);
          return (
            <>
              <Takeaway text={d.takeaway} />
              <p className="muted" style={{ margin: "0 0 14px" }}>{d.definition}</p>
              <div className="bento">
                <Card className="s6" title="Ministries" info="Average gap between what a ministry actually spent and what the budget estimated, across the years we have. Negative means under-spent. Source: two PRS budget editions per year." caption="Average gap between actual and budgeted spending, most under-spent first">
                  <HBars signed rows={mins.map((m) => ({ label: m.ministry, value: m.mean_gap_pct, display: <Num value={`${m.mean_gap_pct.toFixed(1)}%`} source={m.source_ref} /> }))} />
                </Card>
                <Card className="s6" title="Sectors" info="The same idea per market sector, as a 3-year average built from the sector's ministries and schemes. Negative means the sector tended to receive less than the budget promised." caption="3-year execution credibility, latest budget year with a value">
                  <HBars signed rows={secs.map((s) => ({ label: s.sector_name, value: s.credibility_pct, display: <Num value={`${s.credibility_pct.toFixed(1)}%`} source={s.source_ref} /> }))} />
                </Card>
                <Card className="s12" title="All ministries" info="The complete league table behind the bars: average gap and the number of years it is based on." caption="Average gap and number of years">
                  <div className="tablewrap">
                    <table data-testid="league">
                      <thead>
                        <tr><th>Ministry</th><th className="n">Average gap</th><th className="n">Years</th></tr>
                      </thead>
                      <tbody>
                        {d.ministries.map((m) => (
                          <tr key={m.ministry}>
                            <td>{m.ministry}</td>
                            <td className="n"><Num value={`${m.mean_gap_pct.toFixed(1)}%`} source={m.source_ref} /></td>
                            <td className="n">{m.n_years}</td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  </div>
                </Card>
                <Card className="s12" title="Monthly execution line (CGA)" info="The Controller General of Accounts publishes monthly spending against the budget. That feed is not built yet, so this box only says so.">
                  <Note text={d.cga_monthly.note} />
                </Card>
              </div>
            </>
          );
        }}
      </Status>
    </>
  );
}
