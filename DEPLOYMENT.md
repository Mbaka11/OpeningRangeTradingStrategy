# Google Cloud Deployment Guide

This project runs on a Google Compute Engine VM (`openingrange-bot`) using Docker. The deployment workflow involves building the image in Cloud Shell and then pulling/restarting it on the VM.

## Repository Structure (Post-Refactor)

```
services/
├── trading/          # Opening Range bot (main service)
│   └── run_bot.py    # Entry: python -m services.trading.run_bot
└── govtrades/        # Congress trades monitor (future)
    └── main.py       # Entry: python -m services.govtrades.main

shared/               # Cross-service utilities
├── logging_utils.py  # Shared logger
└── notifier.py       # Twitter/X posting
```

## 1. One-Time Setup (Configuration)

_Do this only if you created a new VM or need to change your API keys._

1. **SSH into the VM:**

```bash
gcloud compute ssh openingrange-bot --zone us-central1-a
```

2. **Create/Update the `.env` file:**
   _This file stays on the server and is not in the git repo._

```bash
export TERM=xterm   # Fixes the "Error opening terminal" issue
nano .env
```

3. **Paste your configuration:**

```env
# Trading Service
OANDA_ACCOUNT_ID=101-001-YOUR-ID
OANDA_API_TOKEN=your_oanda_token
OANDA_ENV=practice
OANDA_INSTRUMENT=NAS100_USD
OANDA_TIMEZONE=America/New_York

# Twitter/X (shared)
TWITTER_API_KEY=your_key
TWITTER_API_SECRET=your_secret
TWITTER_ACCESS_TOKEN=your_token
TWITTER_ACCESS_SECRET=your_token_secret

# GovTrades (future)
# DATABASE_URL=postgresql://...
# LLM_API_KEY=...
```

_(Press `Ctrl+O` to Save, `Ctrl+X` to Exit)_

---

## 2. Routine Deployment Cycle

_Follow these steps every time you modify the code._

### Phase A: Build & Push (In Cloud Shell)

1. Navigate to your project folder:

```bash
cd OpeningRangeTradingStrategy
```

2. Build and upload the new Docker image:

```bash
gcloud builds submit --tag gcr.io/onyx-seeker-479417-d5/my-bot-image .
```

### Phase B: Update the Bot (In the VM)

1. **SSH into the VM:**

```bash
gcloud compute ssh openingrange-bot --zone us-central1-a
```

2. **Authenticate Docker:**
   _Required because the VM runs Container-Optimized OS with read-only root._

```bash
# 1. Generate Auth Token
TOKEN=$(curl -s -H "Metadata-Flavor: Google" "http://metadata.google.internal/computeMetadata/v1/instance/service-accounts/default/token" | grep -o '"access_token":"[^" ]*"' | cut -d'"' -f4)

# 2. Create Temp Config Folder
mkdir -p $(pwd)/.docker-temp

# 3. Login
sudo docker --config $(pwd)/.docker-temp login -u oauth2accesstoken -p "$TOKEN" https://gcr.io
```

3. **Pull the Latest Image:**

```bash
sudo docker --config $(pwd)/.docker-temp pull gcr.io/onyx-seeker-479417-d5/my-bot-image:latest
```

4. **Restart the Container:**

```bash
# 1. Find the running container ID
sudo docker ps

# 2. Stop and Remove the old container (Replace <ID> with actual ID)
sudo docker stop <ID>
sudo docker rm <ID>

# 3. Create logs directory (to persist data across updates)
mkdir -p $(pwd)/logs

# 4. Start the Trading Bot (default service)
sudo docker run -d \
  --name trading-bot \
  --restart always \
  --env-file .env \
  -v $(pwd)/logs:/app/services/trading/logs \
  gcr.io/onyx-seeker-479417-d5/my-bot-image:latest

# OR: Start GovTrades Service (future)
# sudo docker run -d \
#   --name govtrades-bot \
#   --restart always \
#   --env-file .env \
#   -v $(pwd)/logs:/app/services/govtrades/logs \
#   gcr.io/onyx-seeker-479417-d5/my-bot-image:latest \
#   python -m services.govtrades.main
```

---

## 3. Monitoring & Logs

To check if the bot is running correctly:

- **View live logs:**

```bash
sudo docker logs -f trading-bot
```

_(Press `Ctrl+C` to exit)_

- **Check status:**

```bash
sudo docker ps
```

- **Verify account connection (inside container):**

```bash
sudo docker exec trading-bot python scripts/verify_account.py
```

- **List accounts:**

```bash
sudo docker exec trading-bot python scripts/list_accounts.py
```

---

## 4. Running Multiple Services

To run both Trading and GovTrades services simultaneously:

```bash
# Trading bot (default)
sudo docker run -d \
  --name trading-bot \
  --restart always \
  --env-file .env \
  -v $(pwd)/logs/trading:/app/services/trading/logs \
  gcr.io/onyx-seeker-479417-d5/my-bot-image:latest

# GovTrades bot (separate container)
sudo docker run -d \
  --name govtrades-bot \
  --restart always \
  --env-file .env \
  -v $(pwd)/logs/govtrades:/app/services/govtrades/logs \
  gcr.io/onyx-seeker-479417-d5/my-bot-image:latest \
  python -m services.govtrades.main
```

---

## 5. Troubleshooting

| Issue                       | Solution                                      |
| --------------------------- | --------------------------------------------- |
| `ModuleNotFoundError`       | Ensure `PYTHONPATH=/app` is set in Dockerfile |
| Twitter 403                 | Check API permissions in Developer Portal     |
| OANDA connection fails      | Verify token and account ID in `.env`         |
| Container exits immediately | Check logs: `sudo docker logs trading-bot`    |
