import { useState } from "react";
import { Bar, BarChart, CartesianGrid, ResponsiveContainer, Tooltip, Treemap, XAxis, YAxis, Legend } from "recharts";
import { crore } from "../api";
import { Note, Num, Status, Takeaway, useFetch } from "../components/Common";

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

export default function Overview({ budgetId }: { budgetId: string }) {
  const [kind, setKind] = useState<"ministry" | "scheme" | "fiscal">("ministry");
  const lines = useFetch<LinesResponse>(`/budgets/${budgetId}/lines?kind=${kind}`);
  const demand = useFetch<DemandResponse>(`/budgets/${budgetId}/lines?kind=demand`);
  return (
    <>
      <h1>1. Budget overview: what did this budget do with the money?</h1>
      <div className="controls" role="tablist" aria-label="Line type">
        {KINDS.map(([k, label]) => (
          <button key={k} role="tab" aria-selected={kind === k} className="btn" onClick={() => setKind(k)} style={kind === k ? { borderColor: "var(--accent)" } : undefined}>
            {label}
          </button>
        ))}
      </div>
      <Status state={lines}>
        {(d) => (
          <>
            <Takeaway text={d.takeaway} />
            <Note text={d.note} />
            {d.available && (
              <>
                <h2>Budget estimate by line (treemap, Rs crore)</h2>
                <div className="chartbox" data-testid="treemap">
                  <ResponsiveContainer>
                    <Treemap
                      data={d.items.filter((i) => (i.be?.amount_cr ?? 0) > 0).map((i) => ({ name: i.line_item, size: i.be!.amount_cr as number }))}
                      dataKey="size"
                      stroke="var(--surface)"
                      fill="var(--s1)"
                      isAnimationActive={false}
                    >
                      <Tooltip formatter={(v) => crore(Number(v))} />
                    </Treemap>
                  </ResponsiveContainer>
                </div>
                <h2>Actual, revised and budget estimates</h2>
                <div className="tablewrap">
                  <table>
                    <thead>
                      <tr>
                        <th>Line</th>
                        <th className="n">Actual ({d.items.find((i) => i.actual)?.actual?.fiscal_year ?? ""})</th>
                        <th className="n">RE ({d.items.find((i) => i.re)?.re?.fiscal_year ?? ""})</th>
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
              </>
            )}
          </>
        )}
      </Status>
      <h2>Capital vs revenue spending by ministry (demands for grants, BE)</h2>
      <Status state={demand}>
        {(d) => {
          const rows = d.items
            .filter((i) => i.stage === "BE")
            .sort((a, b) => b.total_cr - a.total_cr)
            .slice(0, 12);
          return !d.available ? (
            <Note text={d.note} />
          ) : (
            <>
              <Takeaway text={d.takeaway} />
              <div className="chartbox" data-testid="capex-chart">
                <ResponsiveContainer>
                  <BarChart data={rows} layout="vertical" margin={{ left: 60 }}>
                    <CartesianGrid stroke="var(--border)" />
                    <XAxis type="number" stroke="var(--text-2)" tickFormatter={(v) => `${Math.round(Number(v) / 1000)}k`} />
                    <YAxis type="category" dataKey="ministry" width={110} stroke="var(--text-2)" tick={{ fontSize: 11 }} />
                    <Tooltip formatter={(v) => crore(Number(v))} />
                    <Legend />
                    <Bar dataKey="revenue_cr" name="Revenue" stackId="a" fill="var(--s1)" isAnimationActive={false} />
                    <Bar dataKey="capital_cr" name="Capital" stackId="a" fill="var(--s2)" isAnimationActive={false} />
                  </BarChart>
                </ResponsiveContainer>
              </div>
            </>
          );
        }}
      </Status>
    </>
  );
}
