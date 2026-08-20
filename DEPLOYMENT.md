# Free Deployment: Cloud Run Job + Cloud Scheduler

This is the recommended paper-trading deployment. The bot runs only for the New York market session, then exits, instead of keeping a VM online 24/7.

## What is deployed

- **Cloud Run Job** — starts on weekdays at **09:25 America/New_York**, builds the opening range, submits/manages the OANDA **practice** order, posts the consolidated X updates, closes at noon, posts the recap, and exits.
- **Cloud Scheduler** — invokes that one job every weekday.
- **Artifact Registry** — holds the Docker image.
- **Secret Manager** — holds one mounted `.env` secret. It is deliberately one secret to remain within the free active-secret allowance.
- **Cloud Logging** — receives container stdout. `LOG_TO_FILE=false` avoids ephemeral local log files in Cloud Run.

The job is configured for **1 vCPU**, **1 GiB RAM**, a **3-hour timeout**, one task, and **zero retries**. At roughly 2h35m on each weekday, this is intended to remain within Cloud Run's monthly free-job compute allowance. Check Billing after the first full month—providers can change free-tier terms.

> The deployment script refuses `OANDA_ENV=live`. It is intentionally for paper trading only.

## Prerequisites

1. A Google Cloud project with billing enabled. Free-tier usage still requires a billing account.
2. The Google Cloud CLI authenticated to that project:

   ```bash
   gcloud auth login
   gcloud auth application-default login
   gcloud projects list
   ```

3. This repository and a local `.env` copied from `.env.example` with all OANDA practice and X credentials.
4. An X API credit balance. The deployment does not bypass X API billing.

## One-command deployment

Run in **Google Cloud Shell** or from a machine with the Google Cloud CLI installed. From the repository root:

```bash
chmod +x scripts/deploy_cloud_run_job.sh
./scripts/deploy_cloud_run_job.sh YOUR_PROJECT_ID
```

Optional second argument chooses a Cloud Run region (default `us-central1`):

```bash
./scripts/deploy_cloud_run_job.sh YOUR_PROJECT_ID us-central1
```

The script:

1. Validates `.env` and confirms `OANDA_ENV=practice`.
2. Enables the required APIs.
3. Creates a Docker Artifact Registry repository and two least-privilege service accounts if needed.
4. Uploads `.env` as a **single** Secret Manager secret and grants only the runtime service account access.
5. Builds and pushes the Docker image.
6. Deploys/updates the Cloud Run job with `RUN_SINGLE_SESSION=true`, `LOG_TO_FILE=false`, and `--max-retries=0`.
7. Creates the timezone-aware weekday Scheduler trigger.

Never commit `.env` or paste its values into the terminal history.

## Verify deployment

```bash
PROJECT_ID=YOUR_PROJECT_ID
REGION=us-central1
JOB=opening-range-bot

# Inspect the job and weekday scheduler.
gcloud run jobs describe "$JOB" --project="$PROJECT_ID" --region="$REGION"
gcloud scheduler jobs describe opening-range-weekday-session \
  --project="$PROJECT_ID" --location="$REGION"

# Inspect completed scheduled executions and logs.
gcloud run jobs executions list --job="$JOB" --project="$PROJECT_ID" --region="$REGION"
gcloud logging read \
  'resource.type="cloud_run_job" AND resource.labels.job_name="opening-range-bot"' \
  --project="$PROJECT_ID" --limit=100 --format='value(textPayload)'
```

Do **not** manually execute the production job outside the intended session: it can submit a real order to the OANDA *practice* account and consume X API credits. Use the local replay workflow in `README.md` for safe testing.

## Update deployment

After code changes, run the same command again. It builds a new commit-tagged image and updates the existing job and scheduler:

```bash
./scripts/deploy_cloud_run_job.sh YOUR_PROJECT_ID
```

## Operational safeguards

- The bot is restricted to `OANDA_ENV=practice` by the deployment script.
- `RUN_SINGLE_SESSION=true` makes the Cloud Run Job exit immediately after the final recap.
- `--max-retries=0` prevents Cloud Run from retrying a failed task and accidentally duplicating paper orders/posts.
- Cloud Run filesystem state is ephemeral. Use Cloud Logging for operations; local `logs/` are not durable in this deployment.
- Keep X posting credits funded. A failed X post is logged but does not block OANDA risk management.
- Review the OANDA practice account and Cloud Logging after each of the first few runs before relying on unattended scheduling.
