from __future__ import annotations

import io
import time
from datetime import date, timedelta
from pathlib import Path

import pandas as pd

from bsp.ingest._common import (
    CSV_DIR,
    RAW_DIR,
    UA,
    append_fetch_log,
    ensure_dirs,
    write_csv_guarded,
)

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


# First fortnight NSDL served us (2018-09-15). The 2017-01 to 2018-08 report pages are blocked ("Request Rejected") from
# the cloud sandbox and the Codespace, so re-runs must not keep requesting them. If those pages ever become reachable
# (check with ``python -m bsp.ingest.fpi --probe <period>``), move this start earlier; the collector merges into the
# existing CSV and never shrinks it. Nothing before this date is estimated or filled.
FPI_START = date(2018, 9, 15)


def _fortnight_ends(start: date = FPI_START):
    current = date(start.year, start.month, 1)
    while current <= date.today():
        fifteenth = date(current.year, current.month, 15)
        next_month = date(current.year + (current.month == 12), (current.month % 12) + 1, 1)
        for period_end in (fifteenth, next_month - timedelta(days=1)):
            if start <= period_end < date.today():
                yield period_end
        current = next_month


BLOCK_MARKERS = ("request rejected", "the requested url was rejected", "your support id is")
MAX_CONSECUTIVE_BLOCKS = 5  # stop hammering a site that is refusing us
COLUMNS = ["period_end", "nsdl_sector", "equity_net_cr", "debt_net_cr", "equity_aum_cr", "source_url", "source", "fetched_at"]


def fpi_url(period_end: date) -> str:
    """URL of the fortnightly report, e.g. ``.../FIIInvestSector_September152018.html`` (month name, day, year)."""
    return FPI_URL.format(month=MONTHS[period_end.month - 1], day=period_end.day, year=period_end.year)


def is_blocked_page(html: str) -> bool:
    """True for the NSDL / web-firewall "Request Rejected" error page, which arrives with HTTP 200.

    Such a page must never be cached or parsed as a report. A real report is a page that holds a table and
    none of the firewall's phrases.
    """
    lowered = html.lower()
    return any(marker in lowered for marker in BLOCK_MARKERS) or "<table" not in lowered


def purge_poisoned_cache(raw_dir: Path) -> list[str]:
    """Delete cached pages that are really "Request Rejected" errors (written by an earlier version)."""
    removed = []
    for path in sorted(raw_dir.glob("*.html")):
        if is_blocked_page(path.read_text(encoding="utf-8", errors="ignore")):
            path.unlink()
            removed.append(path.stem)
    return removed


def fetch_report(period_end: date, raw_dir: Path, get=None) -> tuple[str, str | None]:
    """Return (status, html). status: cached | fetched | blocked | not_found | error.

    Only a genuine report is ever written to the cache; a blocked or error page is never saved, so the next
    run asks NSDL again.
    """
    path = raw_dir / f"{period_end.isoformat()}.html"
    if path.exists():
        return "cached", path.read_text(encoding="utf-8")
    import requests

    getter = get or requests.get
    try:
        response = getter(fpi_url(period_end), headers=UA, timeout=60)
    except Exception as exc:  # network failures are not data
        return f"error: {exc}"[:120], None
    if response.status_code == 404:
        return "not_found", None
    if response.status_code != 200:
        return ("blocked" if response.status_code in (403, 429) else f"error: HTTP {response.status_code}"), None
    if is_blocked_page(response.text):
        return "blocked", None
    path.write_text(response.text, encoding="utf-8")
    return "fetched", response.text


def _merge_with_existing(fresh: pd.DataFrame, path: Path) -> pd.DataFrame:
    """Keep every period already in the CSV that this run did not (re)build, so a blocked run never shrinks it."""
    if not path.exists():
        return fresh
    try:
        old = pd.read_csv(path)
    except pd.errors.EmptyDataError:
        return fresh
    old = old[~old["period_end"].isin(fresh["period_end"].unique())] if len(fresh) else old
    merged = pd.concat([old, fresh], ignore_index=True)
    return merged.sort_values(["period_end", "nsdl_sector"]).reset_index(drop=True)


def collect_fpi(get=None, start: date = FPI_START, pause: float = 0.5) -> pd.DataFrame:
    ensure_dirs()
    raw_dir = RAW_DIR / "nsdl_fpi"
    raw_dir.mkdir(parents=True, exist_ok=True)
    purged = purge_poisoned_cache(raw_dir)
    frames: list[pd.DataFrame] = []
    missing: list[str] = []
    blocked: list[str] = []
    consecutive_blocks = 0

    for period_end in _fortnight_ends(start):
        if consecutive_blocks >= MAX_CONSECUTIVE_BLOCKS:
            blocked.append(period_end.isoformat())  # not attempted: the site is refusing us
            continue
        status, html = fetch_report(period_end, raw_dir, get)
        if status == "fetched" and pause:
            time.sleep(pause)
        if status == "blocked":
            blocked.append(period_end.isoformat())
            consecutive_blocks += 1
            continue
        consecutive_blocks = 0
        if html is None:
            missing.append(f"{period_end.isoformat()}({status})")
            continue
        try:
            part = parse_fpi_html(html, period_end)
            if not part.empty:
                part["source_url"] = fpi_url(period_end)
                frames.append(part)
            else:
                missing.append(f"{period_end.isoformat()}(no rows)")
        except Exception as exc:
            missing.append(f"{period_end.isoformat()}(parse: {str(exc)[:60]})")

    path, long_path = CSV_DIR / "fpi_sector_fortnightly.csv", CSV_DIR / "fpi_sector_fortnightly_long.csv"
    if frames:
        fresh = pd.concat(frames, ignore_index=True)
        fresh["source"] = "NSDL FPI Monitor, fortnightly sector-wise"
        fresh["fetched_at"] = pd.Timestamp.now(tz="UTC").isoformat(timespec="seconds")
        flat = _merge_with_existing(fresh[COLUMNS], path)
        flat.to_csv(path, index=False)
        long = flat.rename(columns={"nsdl_sector": "sector", "equity_net_cr": "equity_net", "debt_net_cr": "debt_net", "equity_aum_cr": "equity_aum"})
        long = long.melt(id_vars=["period_end", "sector", "source_url", "source", "fetched_at"], var_name="column_header", value_name="value")
        long.dropna(subset=["value"]).to_csv(long_path, index=False)
    else:  # nothing new: the existing CSVs stay exactly as they are
        write_csv_guarded(pd.DataFrame(columns=COLUMNS), path)
        empty_long = pd.DataFrame(columns=["period_end", "sector", "column_header", "value", "source_url", "source", "fetched_at"])
        write_csv_guarded(empty_long, long_path)

    rows = sum(len(frame) for frame in frames)
    if blocked:
        status = "blocked"
        detail = f"{len(blocked)} period(s) blocked ('Request Rejected'/403), first {blocked[0]}, last {blocked[-1]}; existing CSV kept"
    elif missing:
        status, detail = "partial", ", ".join(missing)
    else:
        status, detail = "ok", ""
    if purged:
        detail = f"purged {len(purged)} poisoned cache file(s); " + detail
    append_fetch_log("fpi", status if frames or blocked or missing else "empty", rows, detail)
    return pd.read_csv(path) if path.exists() else pd.DataFrame()


def probe(url_or_period: str) -> None:
    """Diagnostic for a laptop/Codespace: show what NSDL returns for a period (YYYY-MM-DD) or a full URL, and save it
    under data/raw/nsdl_fpi/probe/ so the real naming pattern can be read off a genuine response."""
    import requests

    url = url_or_period if url_or_period.startswith("http") else fpi_url(date.fromisoformat(url_or_period))
    response = requests.get(url, headers=UA, timeout=60)
    out_dir = RAW_DIR / "nsdl_fpi" / "probe"
    out_dir.mkdir(parents=True, exist_ok=True)
    target = out_dir / (url.rsplit("/", 1)[-1] or "index.html")
    target.write_text(response.text, encoding="utf-8")
    print(f"{url}\n  HTTP {response.status_code}, {len(response.text)} bytes, "
          f"{'BLOCKED / not a report' if is_blocked_page(response.text) else 'looks like a report'}; saved {target}")


if __name__ == "__main__":
    import sys

    if len(sys.argv) >= 3 and sys.argv[1] == "--probe":
        probe(sys.argv[2])
    else:
        collect_fpi()
