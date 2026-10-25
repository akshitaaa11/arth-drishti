"""Rebuild point-in-time Nifty 500 membership by walking index-change press releases backwards.

Inputs (nothing is typed in from memory; every row is derived from a downloaded file):
  * the CURRENT Nifty 500 list from niftyindices.com, saved as
    ``data/raw/nifty500_constituents/ind_nifty500list_<date>.csv``;
  * one press release (PDF or text) per index change, saved under
    ``data/raw/nifty500_constituents/press_releases/<YYYY-MM-DD>*.pdf|txt`` where the date is the
    date the change takes effect. ``config/nifty500_press_releases.csv`` (effective_date,url) lists the
    releases to download; releases already present on disk are never re-downloaded.

Walk: start from today's members. For a change effective on D, a company *included* on D was not a
member before D (its interval starts on D); a company *excluded* on D was a member before D (its interval
ends on D-1). Members at the start of the walk have unknown earlier history, so coverage begins the
day before the oldest release and no earlier year is filled.

Outputs:
  * ``data/csv/nifty500_constituents.csv``: symbol, effective_from, effective_to, source, source_url, fetched_at
  * ``data/raw/nifty500_constituents/nifty500_history_intervals.csv``: the same rows (read by
    ``python -m bsp.ingest.constituents`` so the CSV can be rebuilt without re-running this script)
  * ``reports/nifty500_history_report.csv``: companies named in a release that could not be mapped to a
    symbol, and releases that could not be parsed. A release that yields no Nifty 500 section aborts the
    build unless ``--allow-unparsed`` is given.

Run on a laptop: niftyindices.com and NSE block cloud sandboxes.
"""

from __future__ import annotations

import argparse
import re
import sys
import time
from dataclasses import dataclass, field
from datetime import UTC, date, datetime, timedelta
from pathlib import Path

import pandas as pd
import requests

ROOT = Path(__file__).resolve().parents[2]
RAW_DIR = ROOT / "data" / "raw" / "nifty500_constituents"
RELEASE_DIR = RAW_DIR / "press_releases"
CSV_OUT = ROOT / "data" / "csv" / "nifty500_constituents.csv"
INTERVALS_RAW = RAW_DIR / "nifty500_history_intervals.csv"
RELEASE_LIST = ROOT / "config" / "nifty500_press_releases.csv"
ALIASES = ROOT / "config" / "nifty500_name_aliases.csv"
REPORT = ROOT / "reports" / "nifty500_history_report.csv"
CURRENT_URL = "https://www.niftyindices.com/IndexConstituent/ind_nifty500list.csv"
HEADERS = {"User-Agent": "ArthDrishti research-data downloader/1.0"}
COLUMNS = ["symbol", "effective_from", "effective_to", "source", "source_url", "fetched_at"]

_SECTION = re.compile(r"^\s*(?:index\s*[:\-]\s*)?nifty\s*500\s*(?:index)?\s*[:\-]?\s*$", re.I)
_OTHER_INDEX = re.compile(r"^\s*(?:index\s*[:\-]\s*)?(?:nifty|india vix|s&p)[\w &\-]*(?:index)?\s*[:\-]?\s*$", re.I)
_EXCL = re.compile(r"\b(exclu\w*|dropped|removed)\b", re.I)
_INCL = re.compile(r"\b(inclu\w*|added)\b", re.I)


@dataclass
class Change:
    effective: date
    included: list[str] = field(default_factory=list)
    excluded: list[str] = field(default_factory=list)
    source: str = ""
    source_url: str = ""


def normalise_name(name: str) -> str:
    """Case/punctuation/suffix-insensitive company-name key used to match releases to symbols."""
    text = re.sub(r"[^a-z0-9& ]", " ", str(name).lower().replace(".", ""))
    text = re.sub(r"\b(limited|ltd|the)\b", " ", text)
    return re.sub(r"\s+", " ", text).strip()


def parse_release_text(text: str, effective: date, source: str = "", source_url: str = "") -> Change | None:
    """Extract Nifty 500 inclusions/exclusions from release text; None when no Nifty 500 section exists.

    Layout assumed: a line naming ``Nifty 500`` opens a section; lines containing "Excluded"/"Included"
    switch the list; following non-empty lines are one company per line (optionally numbered) until another
    index heading. Anything else is ignored rather than guessed.
    """
    change = Change(effective=effective, source=source, source_url=source_url)
    in_section = False
    seen_section = False
    mode: str | None = None
    for raw_line in text.splitlines():
        line = raw_line.strip()
        if not line:
            continue
        if _SECTION.match(line):
            in_section, seen_section, mode = True, True, None
            continue
        if in_section and _OTHER_INDEX.match(line):
            in_section, mode = False, None
            continue
        if not in_section:
            continue
        if len(line.split()) <= 4 and _EXCL.search(line):
            mode = "excluded"
            continue
        if len(line.split()) <= 4 and _INCL.search(line):
            mode = "included"
            continue
        if mode is None:
            continue
        item = re.sub(r"^\s*\d+[\.\)]?\s*", "", line).strip()
        if not item or item.lower().startswith(("sr", "company", "symbol", "name")):
            continue
        (change.included if mode == "included" else change.excluded).append(item)
    return change if seen_section else None


def read_release(path: Path) -> str:
    if path.suffix.lower() == ".pdf":
        import pdfplumber

        with pdfplumber.open(path) as pdf:
            return "\n".join((page.extract_text() or "") for page in pdf.pages)
    return path.read_text(encoding="utf-8", errors="ignore")


def load_current(raw_dir: Path = RAW_DIR, fetch: bool = True) -> tuple[pd.DataFrame, str, str]:
    """Return (current list, source_url, fetched_at). Downloads once; falls back to the newest saved file."""
    raw_dir.mkdir(parents=True, exist_ok=True)
    if fetch:
        try:
            response = requests.get(CURRENT_URL, headers=HEADERS, timeout=60)
            response.raise_for_status()
            stamp = datetime.now(UTC)
            (raw_dir / f"ind_nifty500list_{stamp.date().isoformat()}.csv").write_bytes(response.content)
        except Exception as exc:
            print(f"[warn] could not download current list: {exc}", file=sys.stderr)
    files = sorted(raw_dir.glob("ind_nifty500list_*.csv"))
    if not files:
        raise SystemExit(
            "No current Nifty 500 list. Download "
            f"{CURRENT_URL} by hand and save it as {raw_dir}/ind_nifty500list_<YYYY-MM-DD>.csv"
        )
    latest = files[-1]
    frame = pd.read_csv(latest)
    fetched_at = datetime.fromtimestamp(latest.stat().st_mtime, UTC).isoformat(timespec="seconds")
    return frame, CURRENT_URL, fetched_at


def name_to_symbol_map(current: pd.DataFrame, aliases_path: Path = ALIASES) -> dict[str, str]:
    mapping = {normalise_name(n): str(s).strip() for n, s in zip(current["Company Name"], current["Symbol"])}
    mapping.update({normalise_name(s): str(s).strip() for s in current["Symbol"]})
    if aliases_path.exists():
        alias = pd.read_csv(aliases_path)
        mapping.update({normalise_name(n): str(s).strip() for n, s in zip(alias["company_name"], alias["symbol"])})
    return mapping


def build_intervals(
    current_symbols: set[str],
    changes: list[Change],
    name_map: dict[str, str],
    current_source_url: str,
    current_fetched_at: str,
) -> tuple[pd.DataFrame, list[dict[str, str]]]:
    """Membership intervals with ``effective_from``/``effective_to`` (inclusive; blank to = still a member)."""
    if not changes:
        raise ValueError("no parsed press releases; cannot rebuild history")
    ordered = sorted(changes, key=lambda c: c.effective, reverse=True)
    coverage_start = ordered[-1].effective - timedelta(days=1)
    stamp = datetime.now(UTC).isoformat(timespec="seconds")
    unmapped: list[dict[str, str]] = []

    def sym_of(name: str, change: Change) -> str | None:
        sym = name_map.get(normalise_name(name))
        if sym is None:
            unmapped.append({"effective_date": change.effective.isoformat(), "name": name, "reason": "no symbol match"})
        return sym

    # state[sym] = {"to": date | None} for the interval currently being extended backwards
    state: dict[str, dict[str, object]] = {
        s: {"to": None, "source": current_source_url, "source_url": current_source_url, "fetched_at": current_fetched_at}
        for s in current_symbols
    }
    out: list[dict[str, object]] = []
    for change in ordered:
        for name in change.included:
            sym = sym_of(name, change)
            if sym is None:
                continue
            interval = state.pop(sym, None)
            if interval is None:
                unmapped.append({"effective_date": change.effective.isoformat(), "name": name,
                                 "reason": "included but not a member afterwards"})
                continue
            out.append({"symbol": sym, "effective_from": change.effective, "effective_to": interval["to"],
                        "source": change.source, "source_url": change.source_url, "fetched_at": stamp})
        for name in change.excluded:
            sym = sym_of(name, change)
            if sym is None:
                continue
            if sym in state:
                unmapped.append({"effective_date": change.effective.isoformat(), "name": name,
                                 "reason": "excluded but already a member afterwards"})
                continue
            state[sym] = {"to": change.effective - timedelta(days=1), "source": change.source,
                          "source_url": change.source_url, "fetched_at": stamp}
    for sym, interval in state.items():  # members at coverage start: earlier history unknown
        out.append({"symbol": sym, "effective_from": coverage_start, "effective_to": interval["to"],
                    "source": interval["source"], "source_url": interval["source_url"],
                    "fetched_at": interval["fetched_at"]})
    frame = pd.DataFrame(out, columns=COLUMNS).sort_values(["symbol", "effective_from"]).reset_index(drop=True)
    return frame, unmapped


def download_releases(release_list: Path = RELEASE_LIST, release_dir: Path = RELEASE_DIR) -> list[str]:
    """Download releases listed in config/nifty500_press_releases.csv that are not on disk yet."""
    release_dir.mkdir(parents=True, exist_ok=True)
    problems: list[str] = []
    if not release_list.exists():
        return problems
    for row in pd.read_csv(release_list).itertuples(index=False):
        suffix = ".pdf" if str(row.url).lower().endswith(".pdf") else ".txt"
        target = release_dir / f"{row.effective_date}{suffix}"
        if any(release_dir.glob(f"{row.effective_date}*")):
            continue
        try:
            response = requests.get(str(row.url), headers=HEADERS, timeout=60)
            response.raise_for_status()
            target.write_bytes(response.content)
            time.sleep(2)  # polite rate limit
        except Exception as exc:
            problems.append(f"{row.effective_date}: could not download {row.url} ({exc})")
    return problems


def release_urls(release_list: Path = RELEASE_LIST) -> dict[str, str]:
    if not release_list.exists():
        return {}
    frame = pd.read_csv(release_list)
    return {str(d): str(u) for d, u in zip(frame["effective_date"], frame["url"])}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--no-download", action="store_true", help="use files already under data/raw only")
    parser.add_argument("--allow-unparsed", action="store_true", help="skip releases with no Nifty 500 section")
    args = parser.parse_args(argv)

    report: list[dict[str, str]] = []
    if not args.no_download:
        report += [{"effective_date": "", "name": "", "reason": p} for p in download_releases()]
    current, current_url, fetched_at = load_current(fetch=not args.no_download)
    name_map = name_to_symbol_map(current)
    urls = release_urls()

    changes: list[Change] = []
    for path in sorted(RELEASE_DIR.glob("*")):
        if path.suffix.lower() not in {".pdf", ".txt"}:
            continue
        match = re.match(r"(\d{4}-\d{2}-\d{2})", path.name)
        if not match:
            report.append({"effective_date": "", "name": path.name, "reason": "file name must start with YYYY-MM-DD"})
            continue
        effective = date.fromisoformat(match.group(1))
        change = parse_release_text(read_release(path), effective, source=path.name,
                                    source_url=urls.get(match.group(1), str(path.relative_to(ROOT))))
        if change is None:
            report.append({"effective_date": effective.isoformat(), "name": path.name,
                           "reason": "no Nifty 500 section found; inspect the file"})
            continue
        changes.append(change)

    REPORT.parent.mkdir(parents=True, exist_ok=True)
    unparsed = [r for r in report if "no Nifty 500 section" in r["reason"] or "file name" in r["reason"]]
    if not changes:
        pd.DataFrame(report, columns=["effective_date", "name", "reason"]).to_csv(REPORT, index=False)
        print("No press releases parsed. Save index-change releases as data/raw/nifty500_constituents/"
              "press_releases/<YYYY-MM-DD>.pdf (list their URLs in config/nifty500_press_releases.csv).")
        return 1
    if unparsed and not args.allow_unparsed:
        pd.DataFrame(report, columns=["effective_date", "name", "reason"]).to_csv(REPORT, index=False)
        print(f"{len(unparsed)} release(s) could not be parsed; see {REPORT}. Re-run with --allow-unparsed to skip them.")
        return 1

    intervals, unmapped = build_intervals(set(current["Symbol"].astype(str).str.strip()), changes, name_map,
                                          current_url, fetched_at)
    report += unmapped
    pd.DataFrame(report, columns=["effective_date", "name", "reason"]).to_csv(REPORT, index=False)
    RAW_DIR.mkdir(parents=True, exist_ok=True)
    intervals.to_csv(INTERVALS_RAW, index=False)
    intervals.to_csv(CSV_OUT, index=False)
    print(f"Wrote {len(intervals)} intervals for {intervals['symbol'].nunique()} symbols; "
          f"coverage starts {intervals['effective_from'].min()}; {len(unmapped)} unmapped names (see {REPORT}).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
