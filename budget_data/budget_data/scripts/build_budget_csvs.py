"""Build the clean budget CSVs and the 15-sector budget panel.

Inputs
    data/csv/prs_tables_raw.csv                      from scripts/parse_prs.py
    data/raw/web_transcribed/prs_2025-26_tables.txt  2025-26 PRS tables (web transcription)
    config/canonical_names.csv, config/sector_budget_lines.csv, config/budget_events.csv

Outputs (data/csv/)
    budget_ministries.csv, budget_schemes.csv, budget_fiscal.csv   long format, with source page
    sector_budget_panel.csv                                        one row per sector x budget
and reports/reconciliation.csv, reports/cross_edition_check.csv

Point-in-time rule: every feature for budget year t uses only numbers printed in the
budget-t document or earlier documents.
"""
from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
CSV, CFG, REP = ROOT / "data/csv", ROOT / "config", ROOT / "reports"
PRS_URL = "https://prsindia.org/budgets/parliament"
WEB_SRC = "https://prsindia.org/files/budget/budget_parliament/2025/Union_Budget_Analysis_2025-26.pdf"


def prev_fy(fy: str, k: int = 1) -> str:
    y = int(fy[:4]) - k
    return f"{y}-{str(y + 1)[2:]}"


def load_pdf_rows() -> pd.DataFrame:
    d = pd.read_csv(CSV / "prs_tables_raw.csv")
    # '% of GDP' rows belong to the deficit line printed just above them
    d = d.sort_index()
    names, prev = [], None
    for item in d.line_item:
        if item.strip().startswith("% of GDP"):
            names.append(f"{prev} (% of GDP)")
        else:
            names.append(item)
            prev = item
    d["line_item"] = names
    d["unit"] = np.where(d.line_item.str.contains("% of GDP"), "pct_of_gdp", "rs_crore")
    d["extraction_method"] = "pdftotext table parse"
    d["source_url"] = PRS_URL
    return d


def load_web_rows() -> pd.DataFrame:
    rows, cur = [], None
    stages = [("Actual", "2023-24"), ("BE", "2024-25"), ("RE", "2024-25"), ("BE", "2025-26")]
    for line in (ROOT / "data/raw/web_transcribed/prs_2025-26_tables.txt").read_text().splitlines():
        if not line.strip() or line.startswith("#"):
            continue
        if line.startswith("@table"):
            _, no, title, kind, page = line.split("|")
            cur = dict(table_no=int(no), table_title=title, table_kind=kind, source_page=int(page))
            continue
        name, *vals = line.split("|")
        for k, (v, (stage, fy)) in enumerate(zip(vals, stages)):
            rows.append({
                "budget_year": "2025-26", **cur, "line_item": name, "column_index": k + 1, "n_columns": 4,
                "stage": stage, "fiscal_year": fy, "raw_value": v,
                "amount_cr": None if v.strip() == "-" else float(v.replace(",", "")),
                "source_doc": "Union_Budget_Analysis_2025-26.pdf (not in team folder)",
                "unit": "pct_of_gdp" if "% of GDP" in name else "rs_crore",
                "extraction_method": "web transcription, cross-checked",
                "source_url": WEB_SRC,
                "source": "PRS Legislative Research, Union Budget Analysis",
            })
    return pd.DataFrame(rows)


def canonicalise(d: pd.DataFrame) -> pd.DataFrame:
    cmap = pd.read_csv(CFG / "canonical_names.csv")
    kind_to_type = {"ministry": "ministry", "scheme": "scheme", "subsidy": "subsidy"}
    d["line_type"] = d.table_kind.map(kind_to_type).fillna("fiscal")
    m = {(r.line_type, r.raw_name): (r.canonical_name, r.note) for r in cmap.itertuples()}
    canon, notes = [], []
    for lt, name in zip(d.line_type, d.line_item):
        c, n = m.get((lt, name), (name, ""))
        canon.append(c)
        notes.append("" if pd.isna(n) else n)
    d["canonical_name"] = canon
    d["name_note"] = notes
    # July 2024 full budget printed provisional 2023-24 actuals where other editions print RE
    prov = (d.budget_year == "2024-25") & (d.stage == "Actual") & (d.fiscal_year == "2023-24")
    d.loc[prov, "stage"] = "Actual_provisional"
    return d


def write_long(d: pd.DataFrame):
    cols = ["budget_year", "fiscal_year", "stage", "line_type", "line_item", "canonical_name", "amount_cr", "unit",
            "table_no", "table_title", "source_doc", "source_page", "source_url", "extraction_method", "name_note"]
    d = d.rename(columns={"budget_year": "budget_year"})
    out = {
        "budget_ministries.csv": d[d.line_type == "ministry"],
        "budget_schemes.csv": d[d.line_type == "scheme"],
        "budget_fiscal.csv": d[d.line_type.isin(["subsidy", "fiscal"])],
    }
    for fn, part in out.items():
        part = part.sort_values(["budget_year", "table_no", "column_index"] if "column_index" in part else ["budget_year"])
        part[cols].to_csv(CSV / fn, index=False)
        print(f"{fn}: {len(part)} rows")


def reconcile(d: pd.DataFrame):
    """Ministries (+ Other) must add up to Total Expenditure within 0.5% (FR-4)."""
    rec = []
    m = d[d.line_type == "ministry"]
    for (by, k), g in m.groupby(["budget_year", "column_index"]):
        total = g[g.canonical_name == "Total Expenditure"].amount_cr.sum()
        has_other = (g.canonical_name == "Other Ministries").any()
        parts = g[g.canonical_name != "Total Expenditure"].amount_cr.sum()
        status = "pass" if has_other and abs(parts - total) <= 0.005 * total else ("no 'Other' row: cannot reconcile" if not has_other else "FAIL")
        rec.append(dict(budget_year=by, stage=g.stage.iloc[0], fiscal_year=g.fiscal_year.iloc[0], sum_of_rows=parts,
                        total_expenditure=total, diff=parts - total if has_other else None, status=status))
    # subsidies: rows add to Total
    s = d[d.line_type == "subsidy"]
    for (by, k), g in s.groupby(["budget_year", "column_index"]):
        total = g[g.canonical_name == "Total"].amount_cr.sum()
        parts = g[~g.canonical_name.isin(["Total", "of which allocation to Price Stabilisation Fund"])].amount_cr.sum()
        status = "pass" if abs(parts - total) <= 0.005 * total else "FAIL (printed total does not equal rows)"
        rec.append(dict(budget_year=by, stage=g.stage.iloc[0], fiscal_year=g.fiscal_year.iloc[0], sum_of_rows=parts,
                        total_expenditure=total, diff=parts - total, status=status, table="subsidies"))
    r = pd.DataFrame(rec)
    r["table"] = r.get("table").fillna("ministries")
    r.to_csv(REP / "reconciliation.csv", index=False)
    print(r.status.value_counts().to_string())


def cross_edition(d: pd.DataFrame):
    """The same (line, fiscal year, stage) printed in two editions should match."""
    x = d[d.unit == "rs_crore"].dropna(subset=["amount_cr"])
    g = x.groupby(["line_type", "canonical_name", "fiscal_year", "stage"])
    rows = []
    for key, grp in g:
        if grp.budget_year.nunique() < 2:
            continue
        vals = grp.groupby("budget_year").amount_cr.first()
        spread = vals.max() - vals.min()
        rows.append(dict(zip(["line_type", "canonical_name", "fiscal_year", "stage"], key),
                         editions=";".join(vals.index), values=";".join(f"{v:.0f}" for v in vals),
                         max_diff_cr=spread, pct_diff=spread / vals.abs().max() * 100 if vals.abs().max() else 0))
    c = pd.DataFrame(rows).sort_values("pct_diff", ascending=False)
    c.to_csv(REP / "cross_edition_check.csv", index=False)
    print(f"cross-edition pairs: {len(c)}, identical: {(c.max_diff_cr <= 1).sum()}, differ >1 cr: {(c.max_diff_cr > 1).sum()}")


def statement3_rows(d: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Ministry-level rows built from Expenditure Profile Statement 3 departments.

    Added only where the PRS tables do not already print that (edition, year, stage, ministry).
    Also returns the department table with a 'Power + MNRE' aggregate for the capex share."""
    dep = pd.read_csv(CSV / "budget_departments.csv")
    dep = dep[dep.ministry.notna() & (dep.ministry != "") & (dep.ministry != "Total Expenditure")].copy()
    extra = dep[dep.ministry.isin(["Power", "New and Renewable Energy"])].copy()
    extra["ministry"] = "Power + MNRE"
    dep = pd.concat([dep, extra], ignore_index=True)
    dep["capital_cr"] = dep.capital_cr.fillna(0.0)
    agg = (dep.groupby(["budget_year", "fiscal_year", "stage", "ministry"])
              .agg(amount_cr=("total_cr", "sum"), capital_cr=("capital_cr", "sum"), source_page=("source_page", "first"),
                   source_doc=("source_doc", "first"), n=("department", "nunique")).reset_index())
    have = set(zip(d[d.line_type == "ministry"].budget_year, d[d.line_type == "ministry"].fiscal_year,
                   d[d.line_type == "ministry"].stage, d[d.line_type == "ministry"].canonical_name))
    keep = [(r.budget_year, r.fiscal_year, r.stage, r.ministry) not in have for r in agg.itertuples()]
    new = agg[keep].copy()
    new["canonical_name"] = new.ministry
    new["line_type"] = "ministry"
    new["source_doc"] = new.source_doc + " (department sum)"
    return new, agg


def value(d, by, lt, name, stage, fy):
    r = d[(d.budget_year == by) & (d.line_type == lt) & (d.canonical_name == name) & (d.stage == stage) & (d.fiscal_year == fy)]
    if r.empty:
        return None, None
    r = r.iloc[0]
    return r.amount_cr, f"{r.source_doc} p.{r.source_page}"


def sector_panel(d: pd.DataFrame):
    s3_new, s3_all = statement3_rows(d)
    d = pd.concat([d, s3_new], ignore_index=True)
    lines = pd.read_csv(CFG / "sector_budget_lines.csv")
    events = pd.read_csv(CFG / "budget_events.csv")
    years = sorted(d.budget_year.unique())
    out = []
    for sid, grp in lines.groupby("sector_id", sort=False):
        for t in years:
            # choose the primary line: ministry if printed in this edition, else fallback scheme/subsidy
            choice = None
            for role in ["primary", "fallback_primary"]:
                for r in grp[grp.role == role].itertuples():
                    be, _ = value(d, t, r.line_type, r.canonical_name, "BE", t)
                    if be is not None:
                        choice = r
                        break
                if choice:
                    break
            ev = events[(events.fiscal_year == t) & (~events.is_interim)]
            rec = dict(sector_id=sid, sector_name=grp.sector_name.iloc[0], budget_year=t,
                       budget_date=ev.presented_on.iloc[0] if len(ev) else "")
            if choice is None:
                rec.update(primary_line="", coverage="missing: line not in PRS tables for this year")
                out.append(rec)
                continue
            lt, name = choice.line_type, choice.canonical_name
            be_t, src = value(d, t, lt, name, "BE", t)
            be_prev, _ = value(d, t, lt, name, "BE", prev_fy(t))
            re_prev, _ = value(d, t, lt, name, "RE", prev_fy(t))
            re_basis = "RE"
            if re_prev is None:
                re_prev, _ = value(d, t, lt, name, "Actual_provisional", prev_fy(t))
                re_basis = "provisional actual" if re_prev is not None else ""
            act_t2, _ = value(d, t, lt, name, "Actual", prev_fy(t, 2))
            # credibility: Actual/BE - 1 for past years whose actuals were public by budget t (k = 2..4)
            gaps = []
            for k in (2, 3, 4):
                fy = prev_fy(t, k)
                eds = [e for e in years if e <= t and e >= fy]
                act = next((value(d, e, lt, name, "Actual", fy)[0] for e in eds if value(d, e, lt, name, "Actual", fy)[0] is not None), None)
                be = next((value(d, e, lt, name, "BE", fy)[0] for e in sorted(eds) if value(d, e, lt, name, "BE", fy)[0] is not None), None)
                if act is not None and be:
                    gaps.append(act / be - 1)
            cap = s3_all[(s3_all.budget_year == t) & (s3_all.fiscal_year == t) & (s3_all.stage == "BE") & (s3_all.ministry == name)]
            capex_share = round(cap.capital_cr.iloc[0] / cap.amount_cr.iloc[0] * 100, 2) if len(cap) and cap.amount_cr.iloc[0] else None
            rec.update(
                capex_share_be_pct=capex_share,
                primary_line=name, primary_line_type=lt,
                coverage="ministry" if choice.role == "primary" and lt == "ministry" else f"proxy: {choice.role} {lt}",
                be_current_cr=be_t, be_previous_cr=be_prev, re_previous_cr=re_prev, re_basis=re_basis,
                actual_two_years_back_cr=act_t2,
                surprise_vs_prev_re_pct=round((be_t / re_prev - 1) * 100, 2) if re_prev else None,
                growth_vs_prev_be_pct=round((be_t / be_prev - 1) * 100, 2) if be_prev else None,
                prev_year_re_to_be_ratio=round(re_prev / be_prev, 4) if (re_prev and be_prev and re_basis == "RE") else None,
                credibility_pct=round(float(np.mean(gaps)) * 100, 2) if gaps else None,
                credibility_years_used=len(gaps),
                source=src,
            )
            # supporting lines: their BE and surprise, as compact text
            sup = []
            for r in grp[grp.role.isin(["supporting", "fallback_primary", "primary"])].itertuples():
                if r.canonical_name == name:
                    continue
                b, _ = value(d, t, r.line_type, r.canonical_name, "BE", t)
                rp, _ = value(d, t, r.line_type, r.canonical_name, "RE", prev_fy(t))
                if b is not None:
                    s = f"{(b / rp - 1) * 100:+.1f}%" if rp else "n/a"
                    sup.append(f"{r.canonical_name}: BE {b:,.0f} (vs RE {s})")
            rec["supporting_lines"] = " | ".join(sup)
            out.append(rec)
    p = pd.DataFrame(out)
    p.to_csv(CSV / "sector_budget_panel.csv", index=False)
    print(f"sector_budget_panel.csv: {len(p)} rows, coverage:\n{p.coverage.value_counts().to_string()}")


def main():
    REP.mkdir(exist_ok=True)
    pdf = load_pdf_rows()
    web = load_web_rows()
    d = pd.concat([pdf, web], ignore_index=True)
    d = canonicalise(d)
    write_long(d)
    reconcile(d)
    cross_edition(d)
    sector_panel(d)


if __name__ == "__main__":
    main()
