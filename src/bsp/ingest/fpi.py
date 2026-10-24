from __future__ import annotations

import io
from datetime import date, timedelta

import pandas as pd

from bsp.ingest._common import CSV_DIR, RAW_DIR, UA, append_fetch_log, ensure_dirs

MONTHS = [
    "January", "February", "March", "April", "May", "June",
    "July", "August", "September", "October", "November", "December",
]
FPI_URL = "https://www.fpi.nsdl.co.in/web/StaticReports/Fortnightly_Sector_wise_FII_Investment_Data/FIIInvestSector_{month}{day}{year}.html"


def _flatten_columns(columns) -> list[str]:
    flattened: list[str] = []
    for column in columns:
        parts = [str(part).strip() for part in (column if isinstance(column, tuple) else [column]) if not str(part).startswith("Unnamed")]
        seen: list[str] = []
        for part in parts:
            if part not in seen:
                seen.append(part)
        flattened.append(" | ".join(seen))
    return flattened


def _find_column(rows: pd.DataFrame, period_end: date, metric: str, asset: str) -> int | None:
    month = period_end.strftime("%B")
    year = str(period_end.year)
    target = rows.iloc[0].fillna("").astype(str)
    label = rows.iloc[2].fillna("").astype(str)
    unit = rows.iloc[1].fillna("").astype(str)
    for idx in range(len(target)):
        text = str(target.iloc[idx]).strip()
        kind = str(label.iloc[idx]).strip()
        unit_text = str(unit.iloc[idx]).strip()
        if metric == "aum" and "AUC as on" in text and asset in kind and "IN INR Cr." in unit_text and month in text and year in text:
            return idx
        if metric == "net" and "Net Investment" in text and asset in kind and "IN INR Cr." in unit_text and month in text and year in text:
            return idx
    return None


def parse_fpi_html(html: str, period_end: date) -> pd.DataFrame:
    tables = pd.read_html(io.StringIO(html))
    if not tables:
        return pd.DataFrame()
    best = max(tables, key=lambda table: table.shape[1]).copy()
    header_rows = best.iloc[:3].copy()
    data = best.iloc[3:].copy().reset_index(drop=True)
    if data.empty:
        return pd.DataFrame()
    sector_col = 1
    aum_idx = _find_column(header_rows, period_end, "aum", "Equity")
    net_eq_idx = _find_column(header_rows, period_end, "net", "Equity")
    net_debt_idx = _find_column(header_rows, period_end, "net", "Debt")
    if aum_idx is None or net_eq_idx is None or net_debt_idx is None:
        return pd.DataFrame()

    rows: list[dict[str, object]] = []
    for row in data.itertuples(index=False):
        sector = str(row[sector_col]).strip()
        if not sector or sector.isdigit():
            continue
        equity_aum = pd.to_numeric(str(row[aum_idx]).replace(",", "").replace("(", "-").replace(")", ""), errors="coerce")
        equity_net = pd.to_numeric(str(row[net_eq_idx]).replace(",", "").replace("(", "-").replace(")", ""), errors="coerce")
        debt_net = pd.to_numeric(str(row[net_debt_idx]).replace(",", "").replace("(", "-").replace(")", ""), errors="coerce")
        if pd.isna(equity_aum) and pd.isna(equity_net) and pd.isna(debt_net):
            continue
        rows.append({
            "period_end": period_end.isoformat(),
            "nsdl_sector": sector,
            "equity_net_cr": float(equity_net) if pd.notna(equity_net) else None,
            "debt_net_cr": float(debt_net) if pd.notna(debt_net) else None,
            "equity_aum_cr": float(equity_aum) if pd.notna(equity_aum) else None,
        })
    return pd.DataFrame(rows)


def _fortnight_ends(first_year: int = 2017):
    current = date(first_year, 1, 1)
    while current <= date.today():
        fifteenth = date(current.year, current.month, 15)
        next_month = date(current.year + (current.month == 12), (current.month % 12) + 1, 1)
        for period_end in (fifteenth, next_month - timedelta(days=1)):
            if period_end < date.today():
                yield period_end
        current = next_month


def collect_fpi() -> pd.DataFrame:
    ensure_dirs()
    raw_dir = RAW_DIR / "nsdl_fpi"
    raw_dir.mkdir(parents=True, exist_ok=True)
    frames: list[pd.DataFrame] = []
    missing: list[str] = []

    for period_end in _fortnight_ends(2017):
        file_path = raw_dir / f"{period_end.isoformat()}.html"
        if not file_path.exists():
            url = FPI_URL.format(month=MONTHS[period_end.month - 1], day=period_end.day, year=period_end.year)
            try:
                import requests
                response = requests.get(url, headers=UA, timeout=60)
                if response.status_code == 200:
                    file_path.write_text(response.text, encoding="utf-8")
                else:
                    missing.append(period_end.isoformat())
                    continue
            except Exception:  # pragma: no cover - network can fail during collection.
                missing.append(period_end.isoformat())
                continue
        try:
            part = parse_fpi_html(file_path.read_text(encoding="utf-8"), period_end)
            if not part.empty:
                part["source_url"] = FPI_URL.format(month=MONTHS[period_end.month - 1], day=period_end.day, year=period_end.year)
                frames.append(part)
        except Exception as exc:  # pragma: no cover
            missing.append(f"{period_end.isoformat()}(parse: {exc})")

    if frames:
        flat = pd.concat(frames, ignore_index=True)
        flat["source"] = "NSDL FPI Monitor, fortnightly sector-wise"
        flat["fetched_at"] = pd.Timestamp.now(tz="UTC").isoformat(timespec="seconds")
        flat = flat[["period_end", "nsdl_sector", "equity_net_cr", "debt_net_cr", "equity_aum_cr", "source_url", "source", "fetched_at"]]
        flat.to_csv(CSV_DIR / "fpi_sector_fortnightly.csv", index=False)

        long = flat.rename(columns={"nsdl_sector": "sector", "equity_net_cr": "equity_net", "debt_net_cr": "debt_net", "equity_aum_cr": "equity_aum"})
        long = long.melt(id_vars=["period_end", "sector", "source_url", "source", "fetched_at"], var_name="column_header", value_name="value")
        long = long.dropna(subset=["value"]).copy()
        long.to_csv(CSV_DIR / "fpi_sector_fortnightly_long.csv", index=False)
    else:
        empty = pd.DataFrame(columns=["period_end", "nsdl_sector", "equity_net_cr", "debt_net_cr", "equity_aum_cr", "source_url", "source", "fetched_at"])
        empty.to_csv(CSV_DIR / "fpi_sector_fortnightly.csv", index=False)
        empty_long = pd.DataFrame(columns=["period_end", "sector", "column_header", "value", "source_url", "source", "fetched_at"])
        empty_long.to_csv(CSV_DIR / "fpi_sector_fortnightly_long.csv", index=False)

    append_fetch_log("fpi", "ok" if len(frames) else "empty", sum(len(frame) for frame in frames), ", ".join(missing)[:200])
    return pd.read_csv(CSV_DIR / "fpi_sector_fortnightly.csv") if (CSV_DIR / "fpi_sector_fortnightly.csv").exists() else pd.DataFrame()


if __name__ == "__main__":
    collect_fpi()
