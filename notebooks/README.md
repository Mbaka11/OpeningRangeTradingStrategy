# Private exit-study dashboard

[`06_exit_comparison.ipynb`](06_exit_comparison.ipynb) is a **blank-output template**, not a published backtest result. It turns the ignored private `exit_study.json` from [research step 3](../research/step3-exit-study.md) into charts of (1) sample coverage and exclusions, (2) paired differences by day, (3) modeled cost stress, (4) one clean trade-day example, and (5) the uncertainty sample-size gate. Each chart is labeled as hypothetical; none chooses a winner or changes the bot.

1. From the project root **activate the project's virtual environment** (on Windows Git Bash, `source venv/Scripts/activate`; PowerShell: `.\\venv\\Scripts\\Activate.ps1`; Unix: `source venv/bin/activate`). The system Python on this machine has an incompatible NumPy/Matplotlib installation. Install `requirements.txt` in the environment if needed. First run the **offline** exit-study script if you don't already have the private report:

   ```bash
   python scripts/research/run_exit_study.py --folder 2026-08-20_2026-09-24
   ```

2. Copy the template to an **ignored private** filename and run that copy (in Git Bash/macOS/Linux; in PowerShell use `Copy-Item`):

   ```bash
   cp notebooks/06_exit_comparison.ipynb notebooks/06_exit_comparison.local.ipynb
   python -m jupyter lab notebooks/06_exit_comparison.local.ipynb
   ```

3. Run the notebook cells top-to-bottom. Change `FOLDER_NAME` for a different **existing audited** private export, `COST_CASE` for the alternate assumption, or `EXAMPLE_DAY` for a clean eligible trade. It only reads the report and public versioned experiment protocol—**no `.env`, OANDA/Cloud/X requests or orders**. The generated charts and any executed outputs belong only in your local `.local.ipynb` file; **do not commit, share, export or upload that file**. `git check-ignore notebooks/06_exit_comparison.local.ipynb` should confirm it's ignored. Git tests reject cached execution outputs in the template.

The templates in notebooks 02–05 refer to absent 2020–2024 source CSVs and earlier cached historical rankings were invalidated; do **not** treat them as proof of a current optimum. See [steps 1–3](../research/README.md) for the full research status and remaining data gates.
