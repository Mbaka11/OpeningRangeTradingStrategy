#!/usr/bin/env bash
# Deploy the paper-trading bot as a Cloud Run Job plus a weekday Cloud Scheduler trigger.
# Run this in Google Cloud Shell from the repository root:
#   ./scripts/deploy_cloud_run_job.sh YOUR_PROJECT_ID
set -euo pipefail

# Cloud Shell exposes gcloud on PATH. The fallback supports a just-installed
# Windows SDK in the current shell before its PATH refreshes.
if ! command -v gcloud >/dev/null 2>&1; then
  windows_sdk=""
  if [[ -n "${LOCALAPPDATA:-}" ]] && command -v cygpath >/dev/null 2>&1; then
    windows_sdk="$(cygpath -u "${LOCALAPPDATA}")/Google/Cloud SDK/google-cloud-sdk/bin"
  fi
  windows_root="$(dirname "${windows_sdk}")"
  windows_python="${windows_root}/platform/bundledpython/python.exe"
  windows_gcloud_py="${windows_root}/lib/gcloud.py"
  if [[ -f "${windows_python}" && -f "${windows_gcloud_py}" ]]; then
    windows_python="$(cygpath -w "${windows_python}")"
    windows_gcloud_py="$(cygpath -w "${windows_gcloud_py}")"
    # Run the SDK implementation directly: Bash cannot reliably invoke a
    # Windows .cmd wrapper whose installation path contains spaces.
    gcloud() { MSYS_NO_PATHCONV=1 "${windows_python}" "${windows_gcloud_py}" "$@"; }
  fi
fi
if ! command -v gcloud >/dev/null 2>&1; then
  echo "Google Cloud CLI (gcloud) is required. Install it or run in Cloud Shell." >&2
  exit 1
fi

PROJECT_ID="${1:?Usage: $0 PROJECT_ID [REGION]}"
REGION="${2:-us-central1}"
JOB_NAME="opening-range-bot"
SCHEDULER_JOB="opening-range-weekday-session"
RUNTIME_SA_NAME="opening-range-runtime"
SCHEDULER_SA_NAME="opening-range-scheduler"
SECRET_NAME="opening-range-env"
REPOSITORY="opening-range"
IMAGE_NAME="opening-range-bot"
TAG="$(git rev-parse --short HEAD 2>/dev/null || date +%Y%m%d%H%M%S)"
RUNTIME_SA="${RUNTIME_SA_NAME}@${PROJECT_ID}.iam.gserviceaccount.com"
SCHEDULER_SA="${SCHEDULER_SA_NAME}@${PROJECT_ID}.iam.gserviceaccount.com"
IMAGE="${REGION}-docker.pkg.dev/${PROJECT_ID}/${REPOSITORY}/${IMAGE_NAME}:${TAG}"

required_vars=(
  OANDA_ACCOUNT_ID
  OANDA_API_TOKEN
  OANDA_ENV
  OANDA_INSTRUMENT
  OANDA_TIMEZONE
  TWITTER_API_KEY
  TWITTER_API_SECRET
  TWITTER_ACCESS_TOKEN
  TWITTER_ACCESS_SECRET
)

if [[ ! -f .env ]]; then
  echo "Missing .env. Copy .env.example and fill in paper-trading/X credentials first." >&2
  exit 1
fi

for variable in "${required_vars[@]}"; do
  if ! grep -Eq "^${variable}=.+" .env; then
    echo "Missing a non-empty ${variable} in .env." >&2
    exit 1
  fi
done

if ! grep -Eq '^OANDA_ENV=practice([[:space:]]*(#.*)?)?$' .env; then
  echo "Refusing deployment: Cloud Run free deployment must use OANDA_ENV=practice." >&2
  exit 1
fi

gcloud config set project "${PROJECT_ID}"
gcloud services enable \
  run.googleapis.com \
  cloudscheduler.googleapis.com \
  cloudbuild.googleapis.com \
  artifactregistry.googleapis.com \
  secretmanager.googleapis.com

if ! gcloud artifacts repositories describe "${REPOSITORY}" --location="${REGION}" >/dev/null 2>&1; then
  gcloud artifacts repositories create "${REPOSITORY}" \
    --repository-format=docker \
    --location="${REGION}" \
    --description="OpeningRangeBotImages"
fi

if ! gcloud iam service-accounts describe "${RUNTIME_SA}" >/dev/null 2>&1; then
  gcloud iam service-accounts create "${RUNTIME_SA_NAME}" \
    --display-name="Opening Range Cloud Run runtime"
fi
if ! gcloud iam service-accounts describe "${SCHEDULER_SA}" >/dev/null 2>&1; then
  gcloud iam service-accounts create "${SCHEDULER_SA_NAME}" \
    --display-name="Opening Range Cloud Scheduler invoker"
fi

if ! gcloud secrets describe "${SECRET_NAME}" >/dev/null 2>&1; then
  gcloud secrets create "${SECRET_NAME}" \
    --replication-policy="automatic" \
    --labels="app=opening-range-bot"
fi
# A single mounted dotenv secret keeps this within Secret Manager's free active-secret allowance.
gcloud secrets versions add "${SECRET_NAME}" --data-file=.env >/dev/null
gcloud secrets add-iam-policy-binding "${SECRET_NAME}" \
  --member="serviceAccount:${RUNTIME_SA}" \
  --role="roles/secretmanager.secretAccessor" >/dev/null

gcloud builds submit --tag="${IMAGE}" .

# A previous deployment may contain a stale secret volume after a secret-path
# change. Clear it before applying the single /secrets/.env mount below.
if gcloud run jobs describe "${JOB_NAME}" --region="${REGION}" >/dev/null 2>&1; then
  gcloud run jobs update "${JOB_NAME}" --region="${REGION}" --clear-secrets >/dev/null
fi

gcloud run jobs deploy "${JOB_NAME}" \
  --image="${IMAGE}" \
  --region="${REGION}" \
  --service-account="${RUNTIME_SA}" \
  --set-secrets="/secrets/.env=${SECRET_NAME}:latest" \
  --set-env-vars="DOTENV_PATH=/secrets/.env,RUN_SINGLE_SESSION=true,LOG_TO_FILE=false" \
  --cpu=1 \
  --memory=1Gi \
  --tasks=1 \
  --max-retries=0 \
  --task-timeout=3h

gcloud run jobs add-iam-policy-binding "${JOB_NAME}" \
  --region="${REGION}" \
  --member="serviceAccount:${SCHEDULER_SA}" \
  --role="roles/run.invoker" >/dev/null

# Recreate the scheduler job so schedule and auth cannot drift between deployments.
if gcloud scheduler jobs describe "${SCHEDULER_JOB}" --location="${REGION}" >/dev/null 2>&1; then
  gcloud scheduler jobs delete "${SCHEDULER_JOB}" --location="${REGION}" --quiet
fi

gcloud scheduler jobs create http "${SCHEDULER_JOB}" \
  --location="${REGION}" \
  --schedule="25 9 * * 1-5" \
  --time-zone="America/New_York" \
  --http-method=POST \
  --uri="https://run.googleapis.com/v2/projects/${PROJECT_ID}/locations/${REGION}/jobs/${JOB_NAME}:run" \
  --oauth-service-account-email="${SCHEDULER_SA}" \
  --oauth-token-scope="https://www.googleapis.com/auth/cloud-platform" \
  --message-body="{}"

cat <<EOF

Deployment complete.

Job:       ${JOB_NAME}
Region:    ${REGION}
Image:     ${IMAGE}
Schedule:  weekdays at 09:25 America/New_York

Verify the deployed configuration and then inspect scheduled executions:
  gcloud run jobs describe ${JOB_NAME} --region=${REGION}
  gcloud run jobs executions list --job=${JOB_NAME} --region=${REGION}
  gcloud logging read 'resource.type="cloud_run_job" AND resource.labels.job_name="${JOB_NAME}"' --limit=100 --format='value(textPayload)'
EOF
