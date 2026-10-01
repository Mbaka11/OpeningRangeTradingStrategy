# Private research dashboards (blank tracked templates)

- [`06_exit_comparison.ipynb`](06_exit_comparison.ipynb) explains the **26-session recent practice** [step-3 study](../research/step3-exit-study.md): coverage, daily paired differences, modeled cost stress, one trade-day example and why the uncertainty gate was closed.
- [`07_historical_rolling_diagnostics.ipynb`](07_historical_rolling_diagnostics.ipynb) explains the **2020–2024 OANDA-feed** [step-5 retrospective diagnostics](../research/step5-rolling-diagnostics.md): five-year coverage, fixed chronological checks, two modeled cost cases, post-hoc ambiguity sensitivity, quoted spread and **descriptive-only** week resampling. Prior years have been viewed; **not an untouched holdout or a rule recommendation**.

Both tracked templates have **zero saved execution outputs**. Executed notebooks and charts can contain sensitive hypothetical dollar research, so always run **only an ignored local copy**. No notebook makes OANDA/Cloud/X requests, reads `.env`, submits orders or changes the live bot.

## Open your own private copies

1. From the repository root **activate the project's virtual environment** (Windows Git Bash: `source venv/Scripts/activate`; PowerShell: `.\\venv\\Scripts\\Activate.ps1`; Unix: `source venv/bin/activate`). The system Python on this machine has incompatible NumPy/Matplotlib; use the project environment and install `requirements.txt` in it if needed.
2. After you have the already-computed **ignored** reports, create local copies **without overwriting any existing private work** (Git Bash/macOS/Linux: `cp -n`; PowerShell: check `Test-Path` before `Copy-Item`):

   ```bash
   # Recent practice report, if needed, OFFLINE:
   python scripts/research/run_exit_study.py --folder 2026-08-20_2026-09-24
   cp -n notebooks/06_exit_comparison.ipynb notebooks/06_exit_comparison.local.ipynb

   # Five-year retrospective report, if needed, OFFLINE from saved history:
   python scripts/research/run_historical_exit_study.py
   cp -n notebooks/07_historical_rolling_diagnostics.ipynb notebooks/07_historical_rolling_verified.local.ipynb

   python -m jupyter lab notebooks/07_historical_rolling_verified.local.ipynb
   ```

The offline [step-6 execution/cost audit](../research/step6-execution-audit.md) is a separate diagnostic (`python scripts/research/audit_historical_execution.py`), not a new performance experiment or altered notebook-07 sample. It writes only an ignored private report and does not update the older study or charts.

3. Run the *local copy* top-to-bottom, or open the already locally rendered `.local.ipynb` file. For notebook 06 you may change `FOLDER_NAME`, `COST_CASE` or `EXAMPLE_DAY`; for notebook 07, change `COST_CASE` to the other declared assumption. A private report already exists on this checkout—offline scripts refuse to overwrite it without explicit `--replace-private`; normally just open the local notebook instead.

`git check-ignore notebooks/07_historical_rolling_verified.local.ipynb` must confirm the executed copy is ignored. Notebook 07 re-audits saved quote, baseline, protocol and simulator-code hashes locally before plotting; an earlier `07_historical_rolling_diagnostics.local.ipynb` copy made before this stricter freshness check may still be on disk—prefer the **verified** copy, and do not overwrite other private work. **Do not commit/share/export/upload screenshots, private quote data, executed notebooks or broker history.** The tests reject cached results in the tracked templates. `.gcloudignore` excludes all `.ipynb` files and `data/`, and `.dockerignore` excludes notebooks/data. Old notebooks 02–05 refer to the **missing original NSXUSD CSVs** and cached historical rankings were invalidated; do not treat them as proof of an optimum.
