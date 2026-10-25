# Secret-scan check (FR-17)

Probe: a throwaway branch `throwaway/secret-scan-test` added `scripts/secret_scan_probe.env` containing a randomly
generated, fake `GROQ_API_KEY=gsk_<52 random characters>` and was opened as draft
[PR #2](https://github.com/akshitaaa11/arth-drishti/pull/2) (a push alone does not trigger `secret-scan.yml`, which
runs on pull requests and on pushes to `main`).

| Item | Result |
| --- | --- |
| Workflow / job | `Secret Scan` / `gitleaks`, [run 40178642431](https://github.com/akshitaaa11/arth-drishti/actions/runs/40178642431/job/121124720964) |
| Outcome | **failure**: `leaks found: 1` (9 commits scanned) |
| Finding | `RuleID: generic-api-key`, file `scripts/secret_scan_probe.env`, line 1, commit `703e495`, entropy 5.15 |
| Same PR, other checks | `tests` passed (the probe does not affect the test job), so only the scan blocks the leak |
| Cleanup | PR #2 closed without merging; local branch deleted. **Deleting the remote branch failed (HTTP 403 from the sandbox git proxy), so `throwaway/secret-scan-test` must be deleted by hand** (`git push origin --delete throwaway/secret-scan-test` or GitHub > Branches). The key was random and never valid. |

Earlier fix: the first scan on `main` failed for an unrelated reason (shallow checkout: gitleaks could not find the
parent commit). `secret-scan.yml` now checks out full history (`fetch-depth: 0`).
