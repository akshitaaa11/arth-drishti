import { useState } from "react";
import { ResponsiveContainer, Tooltip, Treemap } from "recharts";
import { crore } from "../api";
import { Note, Num, Status, Takeaway, useFetch } from "../components/Common";
import { AskBar, Card, ColumnChart, DotMatrix, HBars, Insight } from "../components/ui";

interface Amount {
  fiscal_year: string;
  amount_cr: number | null;
  source_ref: string;
}
interface Line {
  line_item: string;
  actual?: Amount;
  re?: Amount;
  be?: Amount;
}
interface LinesResponse {
  available: boolean;
  note: string | null;
  items: Line[];
  takeaway: string | null;
  fiscal_year: string;
}
interface Demand {
  ministry: string;
  stage: string;
  revenue_cr: number;
  capital_cr: number;
  total_cr: number;
  source_ref: string;
}
interface DemandResponse {
  available: boolean;
  note: string | null;
  items: Demand[];
  takeaway: string | null;
}

const KINDS = [
  ["ministry", "Ministries"],
  ["scheme", "Schemes"],
  ["fiscal", "Fiscal totals"],
] as const;
const lakh = (v: number, d = 2) => `${(v / 1e5).toFixed(d)}L`;
const TM = ["#cfe0ff", "#e2ebff", "#bcd3ff", "#eaf0ff", "#d6e4ff"];

function TreeCell(props: { x?: number; y?: number; width?: number; height?: number; name?: string; index?: number; size?: number }) {
  const { x = 0, y = 0, width = 0, height = 0, name = "", index = 0, size = 0 } = props;
  if (width < 4 || height < 4) return null;
  return (
    <g>
      <rect x={x + 2} y={y + 2} width={Math.max(width - 4, 0)} height={Math.max(height - 4, 0)} rx={14} fill={TM[index % TM.length]} />
      {width > 90 && height > 48 && (
        <>
          <text x={x + 14} y={y + 26} fontSize={12} fill="#37445f">{name.length > Math.floor(width / 7.5) ? `${name.slice(0, Math.floor(width / 7.5) - 1)}…` : name}</text>
          <text x={x + 14} y={y + 50} fontSize={20} fill="#10285f" fontWeight={400}>{lakh(size)}</text>
        </>
      )}
    </g>
  );
}

export default function Overview({ budgetId, ask }: { budgetId: string; ask: (q: string) => void }) {
  const [kind, setKind] = useState<"ministry" | "scheme" | "fiscal">("ministry");
  const lines = useFetch<LinesResponse>(`/budgets/${budgetId}/lines?kind=${kind}`);
  const demand = useFetch<DemandResponse>(`/budgets/${budgetId}/lines?kind=demand`);
  return (
    <>
      <div className="titlerow">
        <div>
          <h1>Overview</h1>
          <p className="lead">What this budget did with the money, and what the models make of it. Click any number to open the source row.</p>
        </div>
        <div className="seg ctrl" role="tablist" aria-label="Line type">
          {KINDS.map(([k, label]) => (
            <button key={k} role="tab" aria-selected={kind === k} onClick={() => setKind(k)}>
              {label}
            </button>
          ))}
        </div>
      </div>
      <Status state={lines}>
        {(d) => {
          const real = d.items.filter((i) => (i.be?.amount_cr ?? 0) > 0 && !/^(total|other)/i.test(i.line_item));
          const ranked = [...real].sort((a, b) => (b.be!.amount_cr as number) - (a.be!.amount_cr as number));
          const top = ranked.slice(0, 5);
          const totalLine = d.items.find((i) => /^total expenditure/i.test(i.line_item) && i.be?.amount_cr);
          const listedSum = real.reduce((a, i) => a + (i.be!.amount_cr as number), 0);
          const total = totalLine?.be?.amount_cr ?? listedSum;
          const withRe = real.filter((i) => i.re?.amount_cr);
          const beSum = withRe.reduce((a, i) => a + (i.be!.amount_cr as number), 0);
          const reSum = withRe.reduce((a, i) => a + (i.re!.amount_cr as number), 0);
          const growth = reSum ? beSum / reSum - 1 : null;
          const reYear = d.items.find((i) => i.re)?.re?.fiscal_year;
          const acYear = d.items.find((i) => i.actual)?.actual?.fiscal_year;
          const shareTop = top[0] ? (top[0].be!.amount_cr as number) / (totalLine?.be?.amount_cr ?? listedSum) : 0;
          const otherLine = d.items.find((i) => /^other/i.test(i.line_item) && i.be?.amount_cr);
          return (
            <>
              <Takeaway text={d.takeaway} />
              <Note text={d.note} />
              {d.available && top.length > 0 && (
                <div className="bento">
                  <Card className="s8" title={`Budget estimate by line, ${d.fiscal_year}`} caption={`${KINDS.find((k) => k[0] === kind)?.[1]}: the five largest, Rs lakh crore`} style={{ paddingBottom: 132 }}>
                    <ColumnChart
                      ariaLabel="Largest budget lines"
                      items={top.map((i) => ({
                        label: i.line_item,
                        value: i.be!.amount_cr as number,
                        display: lakh(i.be!.amount_cr as number),
                        tip: (
                          <>
                            <b>BE {crore(i.be!.amount_cr)}</b>
                            {i.re?.amount_cr ? ` | RE ${crore(i.re.amount_cr)}` : ""}
                            {i.actual?.amount_cr ? ` | Actual ${crore(i.actual.amount_cr)}` : ""}
                          </>
                        ),
                      }))}
                      yFmt={(v) => lakh(v, 1)}
                    />
                    <AskBar tag={top[0].line_item.toLowerCase()} fallback={`How much was the ${top[0].line_item} budget estimate for ${d.fiscal_year}?`} onAsk={ask} />
                  </Card>
                  <Card className="s4" title="Total budget estimate" caption={totalLine ? "Total expenditure line, PRS Budget at a Glance" : "Sum of the lines listed"}>
                    <div className="num-xl" style={{ marginTop: 18, whiteSpace: "nowrap" }}>
                      <small>Rs</small>
                      <Num value={(total / 1e5).toFixed(2)} source={totalLine?.be?.source_ref} />
                      <small style={{ marginLeft: 6 }}>lakh cr</small>
                    </div>
                    <div className="kpi-sub">
                      {growth !== null && <span className={`chip ${growth >= 0 ? "up" : "down"}`}>{growth >= 0 ? "▲" : "▼"} {Math.abs(growth * 100).toFixed(1)}%</span>}
                      <span>{growth !== null ? `against the revised estimate of ${reYear}` : ""}</span>
                    </div>
                    <div style={{ marginTop: 26 }}>
                      <HBars rows={ranked.slice(0, 3).map((i) => ({ label: i.line_item, value: i.be!.amount_cr as number, display: crore(i.be!.amount_cr) }))} />
                    </div>
                  </Card>
                  <Card className="s8" title="Where the money goes" caption="Area is the budget estimate; every tile opens in the table below">
                    <div className="chartbox" data-testid="treemap" style={{ height: 280 }}>
                      <ResponsiveContainer>
                        <Treemap data={ranked.slice(0, 14).map((i) => ({ name: i.line_item, size: i.be!.amount_cr as number }))} dataKey="size" isAnimationActive={false} content={<TreeCell />}>
                          <Tooltip formatter={(v) => crore(Number(v))} />
                        </Treemap>
                      </ResponsiveContainer>
                    </div>
                  </Card>
                  <Insight
                    className="s4"
                    tag="Budget insight"
                    big={`${(shareTop * 100).toFixed(0)}%`}
                    title={top[0] ? `${top[0].line_item} is the largest named line: ${crore(top[0].be!.amount_cr)}.` : ""}
                    text={`Share of ${totalLine ? "total expenditure" : "the listed lines"} in the ${d.fiscal_year} budget estimate${otherLine ? `; the PRS table also groups ${crore(otherLine.be!.amount_cr)} under "Other Ministries"` : ""}. Actuals are from ${acYear ?? "earlier years"}; revised estimates from ${reYear ?? "the previous year"}.`}
                  />
                  <Card className="s12" title="Actual, revised and budget estimates" caption="Rs crore; each figure opens its PRS page">
                    <div className="tablewrap">
                      <table>
                        <thead>
                          <tr>
                            <th>Line</th>
                            <th className="n">Actual ({acYear ?? ""})</th>
                            <th className="n">RE ({reYear ?? ""})</th>
                            <th className="n">BE ({d.fiscal_year})</th>
                          </tr>
                        </thead>
                        <tbody>
                          {d.items.map((i) => (
                            <tr key={i.line_item}>
                              <td>{i.line_item}</td>
                              {([i.actual, i.re, i.be] as (Amount | undefined)[]).map((a, k) => (
                                <td key={k} className="n">
                                  {a && a.amount_cr !== null ? <Num value={Math.round(a.amount_cr).toLocaleString("en-IN")} source={a.source_ref} /> : "-"}
                                </td>
                              ))}
                            </tr>
                          ))}
                        </tbody>
                      </table>
                    </div>
                  </Card>
                </div>
              )}
            </>
          );
        }}
      </Status>
      <Status state={demand}>
        {(d) => {
          if (!d.available) return <Note text={d.note} />;
          const rows = d.items.filter((i) => i.stage === "BE" && !/^total/i.test(i.ministry)).sort((a, b) => b.total_cr - a.total_cr).slice(0, 12);
          const capShare = rows.reduce((a, r) => a + r.capital_cr, 0) / (rows.reduce((a, r) => a + r.total_cr, 0) || 1);
          const max = Math.max(...rows.map((r) => r.total_cr), 1);
          return (
            <div className="bento" style={{ marginTop: 14 }}>
              <Card className="s6" title="Capital vs revenue spending" caption="Demands for grants, budget estimate; blue is revenue, pink is capital">
                <div data-testid="capex-chart" style={{ marginTop: 8 }}>
                  {rows.slice(0, 7).map((r) => (
                    <div className="hrow" key={r.ministry} style={{ margin: "12px 0" }}>
                      <div className="t"><span>{r.ministry}</span><b><Num value={crore(r.total_cr)} source={r.source_ref} /></b></div>
                      <div className="htrack" style={{ width: `${(r.total_cr / max) * 100}%`, minWidth: 40 }}>
                        <div className="split">
                          <div className="h-blue" style={{ width: `${(r.revenue_cr / r.total_cr) * 100}%` }} />
                          <div className="h-pink" style={{ width: `${(r.capital_cr / r.total_cr) * 100}%` }} />
                        </div>
                      </div>
                    </div>
                  ))}
                </div>
              </Card>
              <Card className="s6" title="Capital share by ministry" caption="One column per ministry (largest first); each dot is 10% of its grant that is capital spending">
                <div className="num-l" style={{ margin: "10px 0 4px" }}>{(capShare * 100).toFixed(0)}%</div>
                <div className="cap">of these ministries' combined grants is capital spending</div>
                <div style={{ marginTop: 14 }}>
                  <DotMatrix tone="blue" cols={rows.map((r) => ({ filled: Math.round((r.capital_cr / r.total_cr) * 10), tip: `${r.ministry}: ${((r.capital_cr / r.total_cr) * 100).toFixed(0)}% capital` }))} />
                </div>
              </Card>
              <div className="s12"><Takeaway text={d.takeaway} /></div>
            </div>
          );
        }}
      </Status>
    </>
  );
}
