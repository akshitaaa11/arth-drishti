import { useEffect, useState } from "react";
import { DISCLAIMER, type BudgetsResponse } from "./api";
import { SourceProvider, useFetch } from "./components/Common";
import { AiContext, Icon } from "./components/ui";
import Backtest from "./screens/Backtest";
import Copilot from "./screens/Copilot";
import DeepDive from "./screens/DeepDive";
import Heatmap from "./screens/Heatmap";
import Overview from "./screens/Overview";
import PromiseScreen from "./screens/Promise";
import Watchlist from "./screens/Watchlist";
import WhatIf from "./screens/WhatIf";

const SCREENS = [
  ["overview", "Overview"],
  ["heatmap", "Heat-map"],
  ["sector", "Sectors"],
  ["stocks", "Stocks"],
  ["whatif", "What-if"],
  ["promise", "Promise"],
  ["backtest", "Backtest"],
  ["copilot", "Copilot"],
] as const;

function useHash(): [string[], (h: string) => void] {
  const read = () => window.location.hash.replace(/^#\/?/, "").split("/").filter(Boolean);
  const [parts, setParts] = useState(read());
  useEffect(() => {
    const on = () => setParts(read());
    window.addEventListener("hashchange", on);
    return () => window.removeEventListener("hashchange", on);
  }, []);
  return [parts, (h: string) => (window.location.hash = h)];
}

function useTheme(): [string, () => void] {
  const [theme, setTheme] = useState<string>(() => {
    try {
      return localStorage.getItem("theme") ?? "system";
    } catch {
      return "system";
    }
  });
  useEffect(() => {
    const root = document.documentElement;
    if (theme === "system") root.removeAttribute("data-theme");
    else root.setAttribute("data-theme", theme);
    try {
      localStorage.setItem("theme", theme);
    } catch {
      /* storage unavailable */
    }
  }, [theme]);
  return [theme, () => setTheme(theme === "light" ? "dark" : theme === "dark" ? "system" : "light")];
}

export default function App() {
  const [parts, go] = useHash();
  const [theme, cycleTheme] = useTheme();
  const budgets = useFetch<BudgetsResponse>("/budgets");
  const aiStatus = useFetch<{ mode: string; primary_model: string | null }>("/copilot/status");
  const ai = { on: aiStatus.data?.mode === "llm", model: aiStatus.data?.primary_model ?? null };
  const sectorList = useFetch<{ sectors: { sector_id: string }[] }>("/sectors");
  const SECTORS = sectorList.data?.sectors.map((s) => s.sector_id) ?? [];
  const screen = parts[0] ?? "overview";
  const [budgetId, setBudgetId] = useState<string | null>(null);
  const [sectorId, setSectorId] = useState("defence");
  useEffect(() => {
    if (budgets.data && !budgetId) setBudgetId(budgets.data.latest_forecast_budget);
  }, [budgets.data, budgetId]);
  useEffect(() => {
    if (parts[0] === "sector" && parts[1]) setSectorId(parts[1]);
  }, [parts]);

  const chosen = budgets.data?.budgets.find((b) => b.budget_id === budgetId);
  const ask = (q: string) => go(`/copilot/${encodeURIComponent(q)}`);
  return (
    <SourceProvider>
      <AiContext.Provider value={ai}>
      <div className="stage">
        <div className="frame">
          <header className="top">
            <a className="brand" href="#/overview" aria-label="Arth Drishti home">
              <span className="mark"><i /></span>
              arth drishti
            </a>
            <nav className="tabs" aria-label="Screens">
              {SCREENS.map(([id, label]) => (
                <a key={id} href={`#/${id}`} aria-current={screen === id ? "page" : undefined}>
                  {label}
                  {id === "copilot" && ai.on && <i className="aidot" title={`AI on: ${ai.model}`} />}
                </a>
              ))}
            </nav>
            <div className="actions">
              <select className="pillsel" aria-label="Budget" value={budgetId ?? ""} onChange={(e) => setBudgetId(e.target.value)}>
                {budgets.data?.budgets
                  .filter((b) => b.budget_type === "full")
                  .map((b) => (
                    <option key={b.budget_id} value={b.budget_id}>
                      {b.budget_id}
                      {b.has_forecast ? "" : b.status === "holdout_locked" ? " (hold-out, locked)" : b.status === "live_sealed" ? " (live, sealed)" : ""}
                    </option>
                  ))}
              </select>
              <button className="circle" onClick={cycleTheme} aria-label="Theme" title={`Theme: ${theme} (click to change)`}>
                <Icon name={theme === "dark" ? "moon" : "sun"} />
              </button>
            </div>
          </header>
          <main>
            {budgets.error && <p className="note" role="alert">Cannot reach the API: {budgets.error}</p>}
            {budgetId && chosen && (
              <>
                {screen === "overview" && <Overview budgetId={budgetId} ask={ask} />}
                {screen === "heatmap" && <Heatmap budgetId={budgetId} openSector={(s) => go(`/sector/${s}`)} />}
                {screen === "sector" && <DeepDive budgetId={budgetId} sectorId={sectorId} setSector={(s) => go(`/sector/${s}`)} sectors={SECTORS} ask={ask} />}
                {screen === "stocks" && <Watchlist budgetId={budgetId} sectors={SECTORS} />}
                {screen === "whatif" && <WhatIf budgetId={budgetId} />}
                {screen === "promise" && <PromiseScreen />}
                {screen === "backtest" && <Backtest />}
                {screen === "copilot" && <Copilot initialQuestion={parts[1] ? decodeURIComponent(parts[1]) : undefined} />}
              </>
            )}
          </main>
          <a className="fab" href="#/copilot" aria-label="Open the Budget Copilot"><Icon name="spark" />Ask Copilot</a>
          <footer className="foot">{DISCLAIMER}</footer>
        </div>
      </div>
      </AiContext.Provider>
    </SourceProvider>
  );
}
