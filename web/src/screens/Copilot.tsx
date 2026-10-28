import { useEffect, useRef, useState } from "react";
import { Bar, BarChart, CartesianGrid, Legend, Line, LineChart, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
import { get, post } from "../api";
import { Num } from "../components/Common";
import { Card, InfoTip, useAi } from "../components/ui";

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
const COLOURS = ["#2a55e8", "#ee4d86", "#12a150", "#f2872f"];
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
          <caption style={{ textAlign: "left", padding: "0 0 8px", color: "var(--ink-2)" }}>{chart.title}</caption>
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
    <figure style={{ margin: 0 }}>
      <figcaption style={{ fontWeight: 500, marginBottom: 6 }}>{chart.title}</figcaption>
      <div className="chartbox" role="img" aria-label={chart.title}>
        <ResponsiveContainer>
          <Chart data={data}>
            <CartesianGrid stroke="var(--line)" vertical={false} />
            <XAxis dataKey="x" stroke="var(--ink-3)" tickLine={false} axisLine={false} />
            <YAxis stroke="var(--ink-3)" tickLine={false} axisLine={false} />
            <Tooltip contentStyle={{ borderRadius: 14, border: "none", boxShadow: "0 8px 24px rgba(0,0,0,.15)" }} />
            <Legend />
            {chart.series?.map((s, i) =>
              chart.type === "line" ? (
                <Line key={s.name} dataKey={s.name} stroke={COLOURS[i % 4]} strokeWidth={2.4} isAnimationActive={false} connectNulls />
              ) : (
                <Bar key={s.name} dataKey={s.name} fill={COLOURS[i % 4]} radius={[6, 6, 0, 0]} isAnimationActive={false} />
              ),
            )}
          </Chart>
        </ResponsiveContainer>
      </div>
    </figure>
  );
}

export default function Copilot({ initialQuestion }: { initialQuestion?: string }) {
  const [q, setQ] = useState(initialQuestion ?? "");
  const [busy, setBusy] = useState(false);
  const [answer, setAnswer] = useState<Answer | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [status, setStatus] = useState<Status | null>(null);
  const asked = useRef<string | undefined>(undefined);
  const ai = useAi();

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
  useEffect(() => {
    if (initialQuestion && asked.current !== initialQuestion) {
      asked.current = initialQuestion;
      setQ(initialQuestion);
      void ask(initialQuestion);
    }
  }, [initialQuestion]);

  return (
    <>
      <div className="titlerow">
        <div>
          <h1>Budget Copilot</h1>
          <p className="lead">Ask about budget numbers, sector and stock forecasts, event studies and what-if scenarios. One question at a time; it does not remember earlier ones. Research tool, not investment advice.</p>
        </div>
        {status && (
          <span className="ctrl">
            <span className={`chip ${status.mode === "llm" ? "up" : ""}`}>{status.mode === "llm" ? `AI on: ${status.primary_model}` : "AI off: rule-based answers"}</span>
            <InfoTip title={status.mode === "llm" ? "AI answers are on" : "AI answers are off"}>
              {status.mode === "llm"
                ? `Your question goes to ${status.primary_model} (backup ${status.backup_model}) together with read-only data tools. The model picks the tools, the server runs them, and the model writes the answer only from what they return. Every number is then checked against the tool results.`
                : "AI answers are not enabled on this server, so replies are built by a fixed rule-based writer from the same data tools and the same number checks. The site owner enables the AI by setting a Groq key on the server; visitors never enter a key."}
            </InfoTip>
          </span>
        )}
      </div>
      <div className="bento">
        <Card className="s12" title="Ask a question" info="Ask in plain English about budget numbers, sector or stock forecasts, event studies, what-ifs or how the models were built. Answers come only from read-only tools over the project's data; every number is checked against a tool result, buy/sell and personal-advice questions are refused, and text inside documents is treated as data, never instructions. One question at a time: there is no memory between questions." style={{ minHeight: 420 }}>
          <form onSubmit={(e) => { e.preventDefault(); void ask(q); }}>
            <label htmlFor="copilot-q" className="cap">Your question</label>
            <div style={{ display: "flex", gap: 8, flexWrap: "wrap", marginTop: 6 }}>
              <input id="copilot-q" value={q} maxLength={600} onChange={(e) => setQ(e.target.value)} placeholder="e.g. How much was the Defence budget estimate for 2019-20?"
                style={{ flex: "1 1 280px", minWidth: 0, border: "1px solid var(--line)", background: "var(--card-2)", borderRadius: 14, padding: "12px 16px", outline: "none" }} />
              <button type="submit" disabled={busy || !q.trim()} className="btn" style={{ background: "var(--dark-pill)", color: "var(--on-dark)", padding: "12px 22px" }}>{busy ? "Thinking..." : "Ask"}</button>
            </div>
          </form>
          <p className="cap" style={{ marginTop: 10 }}>Answers use read-only data tools, every number is checked, and buy or sell questions are refused.{ai.on ? " Powered by Groq." : ""}</p>
          {status && !ai.on && <p className="cap" style={{ marginTop: 6 }}>AI-written answers are not enabled on this server right now, so replies come from the built-in writer over the same data and the same number checks.</p>}
          <p style={{ marginTop: 14, lineHeight: 2 }}>
            <span className="cap">Try: </span>
            {EXAMPLES.map((ex) => (
              <button key={ex} type="button" className="linklike" style={{ marginRight: 14 }} onClick={() => { setQ(ex); void ask(ex); }}>{ex}</button>
            ))}
          </p>
          {error && <p role="alert" className="err" style={{ marginTop: 12 }}>Could not get an answer: {error}</p>}
          {answer && (
            <section aria-live="polite" data-testid="copilot-answer" style={{ marginTop: 18 }}>
              <div className="chat-q" style={{ marginLeft: "auto", width: "fit-content" }}>{answer.question}</div>
              <p style={{ whiteSpace: "pre-wrap", margin: "16px 0", fontSize: 15, lineHeight: 1.7 }}>{answer.answer.replace(/\[C\d+\]/g, "").replace(/\s+\./g, ".")}</p>
              {answer.citations.length > 0 && (
                <p>
                  {answer.citations.map((c) =>
                    c.source_ref ? (
                      <span key={c.id} className="srcchip"><em>{c.id.slice(1)}</em><Num value={c.label} source={c.source_ref} /></span>
                    ) : c.screen ? (
                      <a key={c.id} className="srcchip" href={c.screen}><em>{c.id.slice(1)}</em>{c.label}</a>
                    ) : (
                      <span key={c.id} className="srcchip"><em>{c.id.slice(1)}</em>{c.label}</span>
                    ),
                  )}
                </p>
              )}
              {answer.chart && <div style={{ marginTop: 14 }}><ChartView chart={answer.chart} /></div>}
              <p className="cap" style={{ marginTop: 12 }}>
                {MODE_TEXT[answer.mode] ?? answer.mode}
                {answer.model ? ` (${answer.model})` : ""}
                {answer.cached ? ", cached" : ""}. Tools used: {answer.tools_used.length ? answer.tools_used.join(", ") : "none"}.
                {answer.note ? ` ${answer.note}` : ""}
              </p>
            </section>
          )}
        </Card>
      </div>
    </>
  );
}
