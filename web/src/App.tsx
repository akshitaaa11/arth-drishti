import { useEffect, useState } from "react";
import { DISCLAIMER, type BudgetsResponse } from "./api";
import { SourceProvider, useFetch } from "./components/Common";
import Backtest from "./screens/Backtest";
import Copilot from "./screens/Copilot";
import DeepDive from "./screens/DeepDive";
import Heatmap from "./screens/Heatmap";
import Overview from "./screens/Overview";
import PromiseScreen from "./screens/Promise";
import Watchlist from "./screens/Watchlist";
import WhatIf from "./screens/WhatIf";

const SCREENS = [
  ["overview", "1 Budget overview"],
  ["heatmap", "2 Sector heat-map"],
  ["sector", "3 Sector deep-dive"],
  ["stocks", "4 Stock watchlist"],
  ["whatif", "5 What-if"],
  ["promise", "6 Promise vs reality"],
  ["backtest", "7 Backtest and evidence"],
  ["copilot", "8 Copilot"],
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
  return (
    <SourceProvider>
      <div className="shell">
        <header className="top">
          <span className="brand">Arth Drishti</span>
          <label>
            Budget{" "}
            <select aria-label="Budget" value={budgetId ?? ""} onChange={(e) => setBudgetId(e.target.value)}>
              {budgets.data?.budgets
                .filter((b) => b.budget_type === "full")
                .map((b) => (
                  <option key={b.budget_id} value={b.budget_id}>
                    {b.budget_id}
                    {b.has_forecast ? "" : b.status === "holdout_locked" ? " (hold-out, locked)" : b.status === "live_sealed" ? " (live, sealed)" : ""}
                  </option>
                ))}
            </select>
          </label>
          <span className="spacer" />
          <button className="btn" onClick={cycleTheme} aria-label="Theme">Theme: {theme}</button>
          <nav className="tabs" aria-label="Screens">
            {SCREENS.map(([id, label]) => (
              <a key={id} href={`#/${id}`} aria-current={screen === id ? "page" : undefined}>
                {label}
              </a>
            ))}
          </nav>
        </header>
        <main>
          {budgets.error && <p className="note" role="alert">Cannot reach the API: {budgets.error}</p>}
          {budgetId && chosen && (
            <>
              {screen === "overview" && <Overview budgetId={budgetId} />}
              {screen === "heatmap" && <Heatmap budgetId={budgetId} openSector={(s) => go(`/sector/${s}`)} />}
              {screen === "sector" && <DeepDive budgetId={budgetId} sectorId={sectorId} setSector={(s) => go(`/sector/${s}`)} sectors={SECTORS} />}
              {screen === "stocks" && <Watchlist budgetId={budgetId} sectors={SECTORS} />}
              {screen === "whatif" && <WhatIf budgetId={budgetId} />}
              {screen === "promise" && <PromiseScreen />}
              {screen === "backtest" && <Backtest />}
              {screen === "copilot" && <Copilot />}
            </>
          )}
        </main>
        <a className="fab" href="#/copilot" aria-label="Open the Budget Copilot">Ask Copilot</a>
        <footer className="foot">{DISCLAIMER}</footer>
      </div>
    </SourceProvider>
  );
}
