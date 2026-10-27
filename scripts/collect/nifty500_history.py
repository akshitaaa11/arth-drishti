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
  * ``reports/nifty500_history_report.csv``: releases that could not be read, and symbols that do not line up
    with today's list (fix renamed symbols in ``config/nifty500_symbol_aliases.csv``: old_symbol,current_symbol).
    A listed release that yields no Nifty 500 changes aborts the build with exit code 1.

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
ALIASES = ROOT / "config" / "nifty500_symbol_aliases.csv"
REPORT = ROOT / "reports" / "nifty500_history_report.csv"
CURRENT_URL = "https://www.niftyindices.com/IndexConstituent/ind_nifty500list.csv"
HEADERS = {"User-Agent": "ArthDrishti research-data downloader/1.0"}
COLUMNS = ["symbol", "effective_from", "effective_to", "source", "source_url", "fetched_at"]

# A numbered / lettered sub-heading such as "1) Nifty 500", "2) NIFTY 500 Index", "A. Replacement on account of ...".
_HEADING = re.compile(r"^\s*(?:\d{1,3}|[A-Za-z]|[ivxIVX]{1,4})\s*[\)\.]\s+(?P<text>\S.*)$")
# An un-numbered heading line that is only an index name ("Nifty 500", "NIFTY 500 Index").
_BARE_INDEX = re.compile(r"^\s*nifty\s?[\w&:\- ]*$", re.I)
_BLOCK = re.compile(
    r"following\s+(?:company|companies|scrips?|stocks?|securit(?:y|ies))\s+(?:is|are)\s+(?:being\s+|to\s+be\s+)?"
    r"(?P<kind>excluded|included)", re.I)
_ROW = re.compile(r"^\s*(?P<serial>\d{1,3})\s+(?P<name>.*[A-Za-z].*?)\s+(?P<symbol>(?=[A-Z0-9&.\-]*[A-Z])[A-Z0-9][A-Z0-9&.\-]*)\s*$")
_ROW_START = re.compile(r"^\s*\d{1,3}\s+\S")
_EFFECTIVE = re.compile(r"effective\s+from\s+(?P<date>[A-Z][a-z]+\s+\d{1,2},\s*\d{4})")
_NIFTY_500 = re.compile(r"^NIFTY ?500$")

Entry = tuple[str, str]  # (company name as printed, NSE symbol as printed)


@dataclass
class Change:
    effective: date
    included: list[Entry] = field(default_factory=list)
    excluded: list[Entry] = field(default_factory=list)
    source: str = ""
    source_url: str = ""

    @property
    def n_changes(self) -> int:
        return len(self.included) + len(self.excluded)


def is_nifty_500_heading(text: str) -> bool:
    """True for "Nifty 500", "NIFTY 500", "NIFTY 500 Index", "Nifty500"; False for "Nifty500 Equal Weight" etc."""
    cleaned = re.sub(r"\bindex\b", "", text, flags=re.I).strip(" :-\t")
    return bool(_NIFTY_500.match(re.sub(r"\s+", " ", cleaned).upper()))


def parse_effective_date(text: str) -> date | None:
    """First "effective from <Month D, YYYY>" in the release (later ones describe other, later changes)."""
    match = _EFFECTIVE.search(text)
    if not match:
        return None
    return datetime.strptime(re.sub(r"\s+", " ", match.group("date")).replace(" ,", ","), "%B %d, %Y").date()


def parse_release_text(text: str, effective: date | None = None, source: str = "", source_url: str = "") -> Change | None:
    """Nifty 500 inclusions and exclusions of one press release; None when it has no Nifty 500 section.

    Only the "Nifty 500" sub-heading counts. Any other numbered/lettered heading (``2) Nifty Smallcap 250``,
    ``B. Replacements ...``, ``1) Nifty500 Equal Weight``) closes the section, and lines such as "The above
    replacements will also be applicable to Nifty500 Equal Weight ..." are ordinary text, not headings.
    The effective date is read from the release; ``effective`` (from the file name) is cross-checked.
    Raises ValueError when a table row cannot be read or serial numbers skip, so a lost row is never silent.
    """
    printed = parse_effective_date(text)
    if printed is not None and effective is not None and printed != effective:
        raise ValueError(f"{source or 'release'}: text says effective {printed}, but it was filed as {effective}")
    resolved = printed or effective
    if resolved is None:
        raise ValueError(f"{source or 'release'}: no 'effective from <date>' in the text and no date supplied")
    change = Change(effective=resolved, source=source, source_url=source_url)
    in_section = seen_section = False
    kind: str | None = None
    last_serial = 0
    for raw_line in text.splitlines():
        line = raw_line.strip()
        if not line:
            continue
        heading = _HEADING.match(line)
        heading_text = heading.group("text") if heading else (line if _BARE_INDEX.match(line) else None)
        if heading_text is not None:
            in_section = is_nifty_500_heading(heading_text)
            seen_section = seen_section or in_section
            kind, last_serial = None, 0
            continue
        if not in_section:
            continue
        block = _BLOCK.search(line)
        if block:
            kind, last_serial = block.group("kind").lower(), 0
            continue
        if kind is None or not _ROW_START.match(line):
            continue
        row = _ROW.match(line)
        if not row:
            raise ValueError(f"{source or 'release'}: cannot read table row {line!r} in the Nifty 500 section")
        serial = int(row.group("serial"))
        if serial != last_serial + 1:
            raise ValueError(f"{source or 'release'}: serial {serial} after {last_serial} in the Nifty 500 "
                             f"{kind} list - a row was lost or split")
        last_serial = serial
        entry = (row.group("name").replace("*", "").strip(), row.group("symbol"))
        (change.included if kind == "included" else change.excluded).append(entry)
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


def load_symbol_aliases(path: Path = ALIASES) -> dict[str, str]:
    """old symbol -> current symbol, for companies renamed since a release was printed (config file, by hand)."""
    if not path.exists():
        return {}
    frame = pd.read_csv(path, skipinitialspace=True)
    return {str(a).strip(): str(b).strip() for a, b in zip(frame["old_symbol"], frame["current_symbol"])}


def build_intervals(
    current_symbols: set[str],
    changes: list[Change],
    aliases: dict[str, str],
    current_source_url: str,
    current_fetched_at: str,
) -> tuple[pd.DataFrame, list[dict[str, str]]]:
    """Membership intervals with ``effective_from``/``effective_to`` (inclusive; blank to = still a member).

    Symbols are taken exactly as printed in each release, mapped through ``aliases`` (old -> current symbol).
    """
    if not changes:
        raise ValueError("no parsed press releases; cannot rebuild history")
    ordered = sorted(changes, key=lambda c: c.effective, reverse=True)
    coverage_start = ordered[-1].effective - timedelta(days=1)
    stamp = datetime.now(UTC).isoformat(timespec="seconds")
    problems: list[dict[str, str]] = []

    # state[symbol]: the membership interval currently being extended backwards in time
    state: dict[str, dict[str, object]] = {
        s: {"to": None, "source": current_source_url, "source_url": current_source_url, "fetched_at": current_fetched_at}
        for s in current_symbols
    }
    out: list[dict[str, object]] = []
    for change in ordered:
        for name, printed in change.included:
            sym = aliases.get(printed, printed)
            interval = state.pop(sym, None)
            if interval is None:
                problems.append({"effective_date": change.effective.isoformat(), "name": f"{name} ({printed})",
                                 "reason": "included in the release but not a member afterwards "
                                           "(later exclusion, or the symbol changed: add it to the alias file)"})
                continue
            out.append({"symbol": sym, "effective_from": change.effective, "effective_to": interval["to"],
                        "source": change.source, "source_url": change.source_url, "fetched_at": stamp})
        for name, printed in change.excluded:
            sym = aliases.get(printed, printed)
            if sym in state:
                problems.append({"effective_date": change.effective.isoformat(), "name": f"{name} ({printed})",
                                 "reason": "excluded in the release but already a member afterwards"})
                continue
            state[sym] = {"to": change.effective - timedelta(days=1), "source": change.source,
                          "source_url": change.source_url, "fetched_at": stamp}
    for sym, interval in state.items():  # members at coverage start: earlier history unknown
        out.append({"symbol": sym, "effective_from": coverage_start, "effective_to": interval["to"],
                    "source": interval["source"], "source_url": interval["source_url"],
                    "fetched_at": interval["fetched_at"]})
    frame = pd.DataFrame(out, columns=COLUMNS).sort_values(["symbol", "effective_from"]).reset_index(drop=True)
    return frame, problems


def listed_releases(release_list: Path = RELEASE_LIST) -> dict[str, str]:
    """effective date (ISO) -> url, from config/nifty500_press_releases.csv (whitespace around cells is ignored)."""
    if not release_list.exists():
        return {}
    frame = pd.read_csv(release_list, skipinitialspace=True)
    return {str(d).strip(): str(u).strip() for d, u in zip(frame["effective_date"], frame["url"])}


def find_release_file(release_dir: Path, effective: str) -> Path | None:
    for path in sorted(release_dir.glob("*")):
        if path.suffix.lower() in {".pdf", ".txt"} and path.name.strip().startswith(effective):
            return path
    return None


def download_releases(release_list: Path = RELEASE_LIST, release_dir: Path = RELEASE_DIR) -> list[str]:
    """Download listed releases that are not on disk yet (2 s between requests)."""
    release_dir.mkdir(parents=True, exist_ok=True)
    problems: list[str] = []
    for effective, url in listed_releases(release_list).items():
        if find_release_file(release_dir, effective) is not None:
            continue
        target = release_dir / f"{effective}{'.pdf' if url.lower().endswith('.pdf') else '.txt'}"
        try:
            response = requests.get(url, headers=HEADERS, timeout=60)
            response.raise_for_status()
            target.write_bytes(response.content)
            time.sleep(2)
        except Exception as exc:
            problems.append(f"{effective}: could not download {url} ({exc})")
    return problems


def parse_listed_releases(release_dir: Path, listed: dict[str, str]) -> tuple[list[Change], list[dict[str, str]]]:
    """Parse every listed release (plus any extra file in the folder), print per-release counts, collect failures."""
    changes: list[Change] = []
    report: list[dict[str, str]] = []
    files = {eff: find_release_file(release_dir, eff) for eff in listed}
    extras = [p for p in sorted(release_dir.glob("*")) if p.suffix.lower() in {".pdf", ".txt"}
              and p not in files.values()]
    jobs: list[tuple[str, Path | None, str]] = [(eff, path, listed[eff]) for eff, path in files.items()]
    for extra in extras:
        match = re.match(r"\s*(\d{4}-\d{2}-\d{2})", extra.name)
        jobs.append((match.group(1) if match else extra.name.strip(), extra, ""))
    for effective, path, url in sorted(jobs, key=lambda j: j[0]):
        if path is None:
            print(f"{effective}  MISSING FILE (listed but not downloaded)")
            report.append({"effective_date": effective, "name": "", "reason": "listed release has no file"})
            continue
        try:
            filed = date.fromisoformat(effective)
            change = parse_release_text(read_release(path), filed, source=path.name.strip(),
                                        source_url=url or str(path))
        except ValueError as exc:
            print(f"{effective}  ERROR {exc}")
            report.append({"effective_date": effective, "name": path.name.strip(), "reason": f"unreadable: {exc}"})
            continue
        if change is None or change.n_changes == 0:
            print(f"{effective}  excluded=0 included=0  <-- NO NIFTY 500 CHANGES FOUND in {path.name.strip()}")
            report.append({"effective_date": effective, "name": path.name.strip(),
                           "reason": "no Nifty 500 changes found" if change else "no Nifty 500 section found"})
            continue
        shown = ", ".join(s for _, s in change.excluded) + "  ->  " + ", ".join(s for _, s in change.included)
        print(f"{effective}  excluded={len(change.excluded)} included={len(change.included)}  {shown[:100]}")
        changes.append(change)
    return changes, report


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--no-download", action="store_true", help="use files already on disk only")
    parser.add_argument("--releases-dir", type=Path, default=RELEASE_DIR, help="folder holding the release files")
    args = parser.parse_args(argv)

    report: list[dict[str, str]] = []
    if not args.no_download:
        report += [{"effective_date": "", "name": "", "reason": p} for p in download_releases(release_dir=args.releases_dir)]
    listed = listed_releases()
    changes, failures = parse_listed_releases(args.releases_dir, listed)
    report += failures
    REPORT.parent.mkdir(parents=True, exist_ok=True)
    columns = ["effective_date", "name", "reason"]
    if failures or not changes:
        pd.DataFrame(report, columns=columns).to_csv(REPORT, index=False)
        print(f"{len(failures)} listed release(s) gave no Nifty 500 changes or could not be read; see {REPORT}. "
              "Nothing was written.", file=sys.stderr)
        return 1

    current, current_url, fetched_at = load_current(RAW_DIR, fetch=not args.no_download)
    intervals, problems = build_intervals(set(current["Symbol"].astype(str).str.strip()), changes,
                                          load_symbol_aliases(), current_url, fetched_at)
    report += problems
    pd.DataFrame(report, columns=columns).to_csv(REPORT, index=False)
    RAW_DIR.mkdir(parents=True, exist_ok=True)
    intervals.to_csv(INTERVALS_RAW, index=False)
    intervals.to_csv(CSV_OUT, index=False)
    print(f"Wrote {len(intervals)} intervals for {intervals['symbol'].nunique()} symbols; coverage starts "
          f"{intervals['effective_from'].min()}; {len(problems)} symbol problems (see {REPORT}).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
