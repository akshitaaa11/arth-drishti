import { useEffect, useState } from "react";
import { Bar, BarChart, CartesianGrid, Legend, Line, LineChart, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
import { DISCLAIMER, get, post } from "../api";
import { Num } from "../components/Common";

interface Citation {
  id: string;
  label: string;
  source_ref: string | null;
  screen: string | null;
}
interface Chart {
  type: "line" | "bar" | "table";
  title: string;
  x?: string[];
  series?: { name: string; values: (number | null)[] }[];
  columns?: string[];
  rows?: (string | number)[][];
}
interface Answer {
  question: string;
  answer: string;
  citations: Citation[];
  chart: Chart | null;
  tools_used: string[];
  mode: string;
  refusal: string | null;
  verified: boolean;
  model: string | null;
  cached: boolean;
  disclaimer: string | null;
  note: string | null;
}
interface Status {
  model_available: boolean;
  primary_model: string | null;
  backup_model: string | null;
  mode: string;
  notes: string[];
}

const EXAMPLES = [
  "How much was the Defence ministry's budget estimate for 2019-20?",
  "Compare the Railways allocation from 2018-19 to 2021-22",
  "What does the model expect for Railways in FY2023-24?",
  "Why is Defence ranked where it is?",
  "What if the Railways allocation is cut by 20%?",
  "How does the project avoid look-ahead leakage?",
];
const COLOURS = ["var(--s1)", "var(--s2)", "var(--s3)", "var(--s4)"];
const MODE_TEXT: Record<string, string> = {
  llm: "Written by the language model from tool results; every number checked",
  offline: "Built by the rule-based writer from tool results (no model was used); every number checked",
  template: "The model's draft failed the number check, so the checked template text is shown",
  refusal: "Refused by the guardrails",
  fallback: "Could not verify the numbers, so no figures are shown",
};

function ChartView({ chart }: { chart: Chart }) {
  if (chart.type === "table")
    return (
      <div className="tablewrap">
        <table>
          <caption>{chart.title}</caption>
          <thead>
            <tr>{chart.columns?.map((c) => <th key={c}>{c}</th>)}</tr>
          </thead>
          <tbody>
            {chart.rows?.map((r, i) => (
              <tr key={i}>{r.map((v, j) => <td key={j} className={typeof v === "number" ? "n" : undefined}>{typeof v === "number" ? v.toLocaleString("en-IN") : v}</td>)}</tr>
            ))}
          </tbody>
        </table>
      </div>
    );
  const data = (chart.x ?? []).map((x, i) => Object.fromEntries([["x", x], ...(chart.series ?? []).map((s) => [s.name, s.values[i]])]));
  const Chart = chart.type === "line" ? LineChart : BarChart;
  return (
    <figure>
      <figcaption><strong>{chart.title}</strong></figcaption>
      <div className="chartbox" role="img" aria-label={chart.title}>
        <ResponsiveContainer>
          <Chart data={data}>
            <CartesianGrid stroke="var(--border)" />
            <XAxis dataKey="x" stroke="var(--text-2)" />
            <YAxis stroke="var(--text-2)" />
            <Tooltip />
            <Legend />
            {chart.series?.map((s, i) =>
              chart.type === "line" ? (
                <Line key={s.name} dataKey={s.name} stroke={COLOURS[i % 4]} strokeWidth={2} isAnimationActive={false} connectNulls />
              ) : (
                <Bar key={s.name} dataKey={s.name} fill={COLOURS[i % 4]} isAnimationActive={false} />
              ),
            )}
          </Chart>
        </ResponsiveContainer>
      </div>
    </figure>
  );
}

export default function Copilot() {
  const [q, setQ] = useState("");
  const [busy, setBusy] = useState(false);
  const [answer, setAnswer] = useState<Answer | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [status, setStatus] = useState<Status | null>(null);

  useEffect(() => {
    get<Status>("/copilot/status").then(setStatus).catch(() => undefined);
  }, []);

  async function ask(text: string) {
    if (!text.trim()) return;
    setBusy(true);
    setError(null);
    setAnswer(null); // single turn: nothing from the previous question is kept or sent
    try {
      setAnswer(await post<Answer>("/copilot/ask", { question: text }));
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(false);
    }
  }

  return (
    <>
      <h1>8. Budget Copilot</h1>
      <p className="note" role="note">
        Ask about budget allocations, sector or stock forecasts, event studies and what-if scenarios. Answers use only the project's data and models, cite their sources, and every
        number is checked against them. One question at a time: it does not remember earlier questions. {DISCLAIMER}
      </p>
      {status && status.mode === "offline" && <p role="status">No language model is configured on this server, so answers come from the rule-based writer over the same tools.</p>}
      <form onSubmit={(e) => { e.preventDefault(); void ask(q); }}>
        <label htmlFor="copilot-q">Your question</label>
        <div style={{ display: "flex", gap: 8, flexWrap: "wrap", marginTop: 4 }}>
          <input id="copilot-q" value={q} maxLength={600} onChange={(e) => setQ(e.target.value)} placeholder="e.g. How much was the Defence budget estimate for 2019-20?" style={{ flex: "1 1 280px", minWidth: 0 }} />
          <button type="submit" disabled={busy || !q.trim()}>{busy ? "Thinking..." : "Ask"}</button>
        </div>
      </form>
      <p>
        Try:{" "}
        {EXAMPLES.map((ex) => (
          <button key={ex} type="button" className="linklike" style={{ marginRight: 8 }} onClick={() => { setQ(ex); void ask(ex); }}>{ex}</button>
        ))}
      </p>
      {error && <p role="alert">Could not get an answer: {error}</p>}
      {answer && (
        <section aria-live="polite" data-testid="copilot-answer">
          <p style={{ whiteSpace: "pre-wrap" }}>{answer.answer.replace(/\[C\d+\]/g, "")}</p>
          {answer.citations.length > 0 && (
            <p>
              Sources:{" "}
              {answer.citations.map((c) =>
                c.source_ref ? (
                  <span key={c.id} style={{ marginRight: 10 }}><Num value={`[${c.id}] ${c.label}`} source={c.source_ref} /></span>
                ) : c.screen ? (
                  <a key={c.id} href={c.screen} style={{ marginRight: 10 }}>[{c.id}] {c.label}</a>
                ) : (
                  <span key={c.id} style={{ marginRight: 10 }}>[{c.id}] {c.label}</span>
                ),
              )}
            </p>
          )}
          {answer.chart && <ChartView chart={answer.chart} />}
          <p className="note" style={{ background: "transparent", color: "var(--text-2)", padding: 0 }}>
            {MODE_TEXT[answer.mode] ?? answer.mode}
            {answer.model ? ` (${answer.model})` : ""}
            {answer.cached ? ", cached" : ""}. Tools used: {answer.tools_used.length ? answer.tools_used.join(", ") : "none"}.
            {answer.note ? ` ${answer.note}` : ""}
          </p>
        </section>
      )}
    </>
  );
}
