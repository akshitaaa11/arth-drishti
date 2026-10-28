import { Note, Num, Status, Takeaway, useFetch } from "../components/Common";

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
      <h1>6. Promise vs reality: is the money being spent?</h1>
      <Status state={state}>
        {(d) => (
          <>
            <Takeaway text={d.takeaway} />
            <p className="muted">{d.definition}</p>
            <h2>Ministries: average gap between actual and budgeted spending (most under-spent first)</h2>
            <div className="tablewrap">
              <table data-testid="league">
                <thead>
                  <tr>
                    <th>Ministry</th>
                    <th className="n">Average gap</th>
                    <th className="n">Years</th>
                  </tr>
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
            <h2>Sectors: 3-year execution credibility (latest budget year with a value)</h2>
            <div className="tablewrap">
              <table>
                <thead>
                  <tr>
                    <th>Sector</th>
                    <th>Budget year</th>
                    <th className="n">Credibility</th>
                    <th className="n">Years used</th>
                  </tr>
                </thead>
                <tbody>
                  {d.sectors.map((s) => (
                    <tr key={s.sector_id}>
                      <td>{s.sector_name}</td>
                      <td>{s.budget_year}</td>
                      <td className="n"><Num value={`${s.credibility_pct.toFixed(1)}%`} source={s.source_ref} /></td>
                      <td className="n">{s.years_used}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
            <h2>Monthly execution line (CGA)</h2>
            <Note text={d.cga_monthly.note} />
          </>
        )}
      </Status>
    </>
  );
}
