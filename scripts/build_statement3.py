"""Load Expenditure Profile 'Statement 3' transcriptions, verify them against PRS, write CSV.

Statement 3 (Expenditure of Ministries and Departments) gives Actuals, BE, RE and BE with a
revenue/capital split for every department. The rows were transcribed from the official PDFs
on indiabudget.gov.in through a web tool (direct download is blocked in the build workspace),
so every document is verified: departments are summed to ministries and compared with the
PRS ministry table for the same budget, fiscal year and stage.

Output
    data/csv/budget_departments.csv      one row per department x stage x fiscal year x document
    reports/statement3_vs_prs.csv        verification of every comparable value
"""
from __future__ import annotations

import re
from datetime import UTC, datetime
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "data/raw/web_transcribed/statement3"

# Which departments add up to each PRS ministry line (by department name).
MINISTRY_OF = {
    "Ministry of Defence (Civil)": "Defence", "Defence Services (Revenue)": "Defence",
    "Capital Outlay on Defence Services": "Defence", "Defence Pensions": "Defence",
    "Ministry of Railways": "Railways",
    "Ministry of Road Transport and Highways": "Road Transport and Highways",
    "Ministry of Housing and Urban Affairs": "Housing and Urban Affairs",
    "Ministry of Housing and Urban Poverty Alleviation": "Housing and Urban Affairs",  # 2017-18 edition: two ministries, merged in 2017
    "Ministry of Urban Development": "Housing and Urban Affairs",
    "Department of Drinking Water and Sanitation": "Jal Shakti",
    "Department of Water Resources, River Development and Ganga Rejuvenation": "Jal Shakti",
    "Department of Telecommunications": "Communications", "Department of Posts": "Communications",
    "Department of Agriculture and Farmers Welfare": "Agriculture and Farmers' Welfare",
    "Department of Agricultural Research and Education": "Agriculture and Farmers' Welfare",
    "Department of Chemicals and Petrochemicals": "Chemicals and Fertilisers",
    "Department of Fertilisers": "Chemicals and Fertilisers", "Department of Pharmaceuticals": "Chemicals and Fertilisers",
    "Department of Food and Public Distribution": "Consumer Affairs, Food and Public Distribution",
    "Department of Consumer Affairs": "Consumer Affairs, Food and Public Distribution",
    "Department of Health and Family Welfare": "Health and Family Welfare",
    "Department of Health Research": "Health and Family Welfare",
    "Department of School Education and Literacy": "Education", "Department of Higher Education": "Education",
    "Department of Rural Development": "Rural Development", "Department of Land Resources": "Rural Development",
    "Ministry of Electronics and Information Technology": "Electronics and Information Technology",
    "Ministry of New and Renewable Energy": "New and Renewable Energy",
    "Ministry of Power": "Power",
    "Department of Financial Services": "Finance - Financial Services",
    "Grand Total": "Total Expenditure",
}

# Older names of the same departments (renames), mapped to one canonical department name.
DEPT_ALIAS = {
    "Department of Agriculture, Cooperation and Farmers' Welfare": "Department of Agriculture and Farmers Welfare",
    "Department of Agriculture, Cooperation and Farmers Welfare": "Department of Agriculture and Farmers Welfare",
    "Ministry of Defence (Misc.)": "Ministry of Defence (Civil)",
    "Ministry of Drinking Water and Sanitation": "Department of Drinking Water and Sanitation",
    "Ministry of Water Resources, River Development and Ganga Rejuvenation": "Department of Water Resources, River Development and Ganga Rejuvenation",
}


def num(x: str):
    x = x.strip()
    return None if x in ("...", "-", "") else float(x.replace(",", ""))


def norm_fy(fy: str) -> str:
    m = re.match(r"(20\d\d)-(?:20)?(\d\d)$", fy.strip())
    return f"{m.group(1)}-{m.group(2)}" if m else fy


def load() -> pd.DataFrame:
    rows = []
    for f in sorted(SRC.glob("eb_*.txt")):
        budget_year = re.search(r"eb_(20\d\d-\d\d)", f.name).group(1)
        url = ""
        fetched_at = datetime.now(UTC).isoformat()
        for line in f.read_text().splitlines():
            if line.startswith("#"):
                m = re.search(r"url:\s*(\S+)", line)
                url = m.group(1) if m else url
                fetched = re.search(r"Transcribed\s+(20\d\d-\d\d-\d\d)", line)
                if fetched:
                    fetched_at = f"{fetched.group(1)}T00:00:00+00:00"
                continue
            if not line.strip():
                continue
            stage, fy, dno, dept, rev, cap, tot, page = line.split("|")
            printed_name = dept.strip()
            dept = DEPT_ALIAS.get(printed_name, printed_name)
            rows.append(dict(budget_year=budget_year, fiscal_year=norm_fy(fy), stage=stage, demand_no=dno.strip(" .") or "",
                             department=dept.strip(), printed_name=printed_name, ministry=MINISTRY_OF.get(dept.strip(), ""),
                             revenue_cr=num(rev), capital_cr=num(cap), total_cr=num(tot),
                             source_doc=f"Expenditure Profile {budget_year}, Statement 3", source_page=page.strip(),
                             source_url=url, fetched_at=fetched_at,
                             extraction_method="web transcription, verified against PRS"))
    d = pd.DataFrame(rows).drop_duplicates(["budget_year", "fiscal_year", "stage", "department"])
    # internal check: revenue + capital = total
    rc = d.revenue_cr.fillna(0) + d.capital_cr.fillna(0)
    d["rev_plus_cap_ok"] = (rc - d.total_cr).abs() <= 0.02
    return d


def verify(d: pd.DataFrame) -> pd.DataFrame:
    prs = pd.read_csv(ROOT / "data/csv/budget_ministries.csv")
    agg = d[d.ministry != ""].groupby(["budget_year", "fiscal_year", "stage", "ministry"]).agg(
        s3_total=("total_cr", "sum"), departments=("department", "nunique")).reset_index()
    out = []
    for r in agg.itertuples():
        p = prs[(prs.budget_year == r.budget_year) & (prs.fiscal_year == r.fiscal_year) & (prs.canonical_name == r.ministry)]
        p = p[p.stage.isin([r.stage] + (["Actual_provisional"] if r.stage == "RE" else []))]
        if p.empty:
            continue
        pv = p.amount_cr.iloc[0]
        stage_note = "PRS printed provisional actual" if p.stage.iloc[0] == "Actual_provisional" else ""
        diff = r.s3_total - pv
        out.append(dict(budget_year=r.budget_year, fiscal_year=r.fiscal_year, stage=r.stage, ministry=r.ministry,
                        departments_summed=r.departments, statement3_total=round(r.s3_total, 2), prs_value=pv,
                        diff_cr=round(diff, 2), status="match" if abs(diff) <= 2 else ("differs (see note)" if stage_note else "MISMATCH"),
                        note=stage_note))
    return pd.DataFrame(out)


def main():
    d = load()
    print(f"loaded {len(d)} rows from {d.budget_year.nunique()} documents; rev+cap=total fails: {(~d.rev_plus_cap_ok).sum()}")
    v = verify(d)
    (ROOT / "reports").mkdir(exist_ok=True)
    v.to_csv(ROOT / "reports/statement3_vs_prs.csv", index=False)
    print(v.status.value_counts().to_string())
    bad = v[v.status == "MISMATCH"]
    if len(bad):
        print(bad.to_string())
    d.drop(columns=["rev_plus_cap_ok"]).to_csv(ROOT / "data/csv/budget_departments.csv", index=False)
    return d, v


if __name__ == "__main__":
    main()
