import { Fragment, useState } from "react";
import { crore, pct, signedPct } from "../api";
import { Note, Num, Status, Takeaway, useFetch } from "../components/Common";

interface Stock {
  symbol: string;
  sector_id: string;
  rank: number;
  expected_excess: number;
  p10: number;
  p90: number;
  p_beat: number;
  liquidity_cr: number | null;
  risk: string | null;
  reasons: string[];
  source_ref: string;
  features_ref: string | null;
}
interface Resp {
  stocks: Stock[];
  note: string | null;
  survivorship: string;
  order_win_flag: string;
  takeaway: string | null;
}

export default function Watchlist({ budgetId, sectors }: { budgetId: string; sectors: string[] }) {
  const [sector, setSector] = useState("");
  const [risk, setRisk] = useState("");
  const [open, setOpen] = useState<string | null>(null);
  const qs = `budget_id=${budgetId}${sector ? `&sector=${sector}` : ""}${risk ? `&risk=${risk}` : ""}`;
  const state = useFetch<Resp>(`/stocks?${qs}`);
  return (
    <>
      <h1>4. Stock watchlist: which stocks within it?</h1>
      <div className="controls">
        <label>
          Sector{" "}
          <select value={sector} onChange={(e) => setSector(e.target.value)} aria-label="Sector filter">
            <option value="">all</option>
            {sectors.map((s) => (
              <option key={s}>{s}</option>
            ))}
          </select>
        </label>
        <label>
          Risk (90-day volatility tercile){" "}
          <select value={risk} onChange={(e) => setRisk(e.target.value)} aria-label="Risk filter">
            <option value="">all</option>
            <option>low</option>
            <option>medium</option>
            <option>high</option>
          </select>
        </label>
      </div>
      <Status state={state}>
        {(d) => (
          <>
            <Takeaway text={d.takeaway} />
            <Note text={d.note} />
            <p className="muted">{d.survivorship} Order-win flag: {d.order_win_flag}.</p>
            <div className="tablewrap">
              <table data-testid="watchlist">
                <thead>
                  <tr>
                    <th className="n">Rank</th>
                    <th>Stock</th>
                    <th>Sector</th>
                    <th className="n">Expected excess</th>
                    <th className="n">80% interval</th>
                    <th className="n">P(beat)</th>
                    <th className="n">Liquidity</th>
                    <th>Risk</th>
                    <th>Order win</th>
                  </tr>
                </thead>
                <tbody>
                  {d.stocks.slice(0, 60).map((s) => (
                    <Fragment key={s.symbol}>
                      <tr onClick={() => setOpen(open === s.symbol ? null : s.symbol)} style={{ cursor: "pointer" }}>
                        <td className="n">{s.rank}</td>
                        <td><strong>{s.symbol}</strong></td>
                        <td>{s.sector_id}</td>
                        <td className="n"><Num value={signedPct(s.expected_excess)} source={s.source_ref} /></td>
                        <td className="n">{signedPct(s.p10, 0)} to {signedPct(s.p90, 0)}</td>
                        <td className="n">{pct(s.p_beat, 0)}</td>
                        <td className="n"><Num value={crore(s.liquidity_cr)} source={s.features_ref} /></td>
                        <td>{s.risk}</td>
                        <td className="muted">n/a</td>
                      </tr>
                      {open === s.symbol && (
                        <tr>
                          <td colSpan={9}>
                            <ul>
                              {s.reasons.map((r) => (
                                <li key={r}>{r}</li>
                              ))}
                            </ul>
                          </td>
                        </tr>
                      )}
                    </Fragment>
                  ))}
                </tbody>
              </table>
            </div>
            <p className="muted">Showing the top 60 of {d.stocks.length} stocks. Click a row for its three reasons.</p>
          </>
        )}
      </Status>
    </>
  );
}
