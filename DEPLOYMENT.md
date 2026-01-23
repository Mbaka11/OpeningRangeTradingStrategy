# Google Cloud Deployment Guide

This project runs on a Google Compute Engine VM (`openingrange-bot`) using Docker. The deployment workflow involves building the image in Cloud Shell and then pulling/restarting it on the VM.

## Repository Structure

```
services/
├── trading/            # Opening Range bot
│   └── run_bot.py        # Entry: python -m services.trading.run_bot
└── govtrades/          # Congress trades monitor (future)
    └── main.py           # Entry: python -m services.govtrades.main

shared/                 # Cross-service utilities
├── logging_utils.py      # Shared logger
└── notifier.py           # Twitter/X posting

config/
├── trading/            # Trading service configuration
│   ├── instruments.yml
│   └── strategy.yml
└── govtrades/          # GovTrades configuration (future)

data/
├── trading/            # Trading data
│   ├── historical/       # Backtest CSVs
│   └── replay/           # Paper trading replays
└── govtrades/          # GovTrades cache (future)

logs/
├── trading/            # Trading bot logs
└── govtrades/          # GovTrades logs (future)
```

---

## 1. One-Time Setup (Configuration)

_Do this only if you created a new VM or need to change your API keys._

### SSH into the VM

```bash
gcloud compute ssh openingrange-bot --zone us-central1-a
```

### Create/Update the `.env` file

```bash
export TERM=xterm   # Fixes the "Error opening terminal" issue
nano .env
```

### Paste your configuration

```env
# === Trading Service ===
OANDA_ACCOUNT_ID=101-001-YOUR-ID
OANDA_API_TOKEN=your_oanda_token
OANDA_ENV=practice
OANDA_INSTRUMENT=NAS100_USD
OANDA_TIMEZONE=America/New_York

# === Twitter/X (shared) ===
TWITTER_API_KEY=your_key
TWITTER_API_SECRET=your_secret
TWITTER_ACCESS_TOKEN=your_token
TWITTER_ACCESS_SECRET=your_token_secret

# === GovTrades (future) ===
# DATABASE_URL=postgresql://...
# LLM_API_KEY=...

# === Logging ===
LOG_LEVEL=INFO
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
   _(Required because the VM runs Container-Optimized OS with read-only root)_

```bash
# Generate Auth Token
TOKEN=$(curl -s -H "Metadata-Flavor: Google" \
  "http://metadata.google.internal/computeMetadata/v1/instance/service-accounts/default/token" \
  | grep -o '"access_token":"[^"]*"' | cut -d'"' -f4)

# Create Temp Config Folder
mkdir -p $(pwd)/.docker-temp

# Login
sudo docker --config $(pwd)/.docker-temp login \
  -u oauth2accesstoken -p "$TOKEN" https://gcr.io
```

3. **Pull the Latest Image:**

```bash
sudo docker --config $(pwd)/.docker-temp pull \
  gcr.io/onyx-seeker-479417-d5/my-bot-image:latest
```

4. **Restart the Container:**

```bash
# Find the running container ID
sudo docker ps

# Stop and Remove the old container (Replace <ID> with actual ID)
sudo docker stop <ID>
sudo docker rm <ID>

# Create logs directories
mkdir -p $(pwd)/logs/trading
mkdir -p $(pwd)/logs/govtrades

# Start the Trading Bot
sudo docker run -d \
  --name trading-bot \
  --restart always \
  --env-file .env \
  -v $(pwd)/logs/trading:/app/logs/trading \
  gcr.io/onyx-seeker-479417-d5/my-bot-image:latest
```

---

## 3. Monitoring & Logs

### View live logs

```bash
sudo docker logs -f trading-bot
```

_(Press `Ctrl+C` to exit)_

### Check status

```bash
sudo docker ps
```

### Verify account connection

```bash
sudo docker exec trading-bot python scripts/trading/verify_account.py
```

### List accounts

```bash
sudo docker exec trading-bot python scripts/trading/list_accounts.py
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
  -v $(pwd)/logs/trading:/app/logs/trading \
  gcr.io/onyx-seeker-479417-d5/my-bot-image:latest

# GovTrades bot (separate container)
sudo docker run -d \
  --name govtrades-bot \
  --restart always \
  --env-file .env \
  -v $(pwd)/logs/govtrades:/app/logs/govtrades \
  gcr.io/onyx-seeker-479417-d5/my-bot-image:latest \
  python -m services.govtrades.main
```

---

## 5. Docker Commands Reference

| Action               | Command                                 |
| -------------------- | --------------------------------------- |
| List containers      | `sudo docker ps -a`                     |
| View logs            | `sudo docker logs -f <name>`            |
| Stop container       | `sudo docker stop <name>`               |
| Remove container     | `sudo docker rm <name>`                 |
| Shell into container | `sudo docker exec -it <name> /bin/bash` |
| Prune old images     | `sudo docker image prune -a`            |

---

## 6. Troubleshooting

| Issue                       | Solution                                      |
| --------------------------- | --------------------------------------------- |
| `ModuleNotFoundError`       | Ensure `PYTHONPATH=/app` is set in Dockerfile |
| Twitter 403                 | Check API permissions in Developer Portal     |
| OANDA connection fails      | Verify token and account ID in `.env`         |
| Container exits immediately | Check logs: `sudo docker logs <name>`         |
| Config not found            | Ensure config files are in `config/trading/`  |
| Data files not found        | Check paths use `data/trading/historical/`    |

---

## 7. File Path Reference

| Old Path                    | New Path                            |
| --------------------------- | ----------------------------------- |
| `config/instruments.yml`    | `config/trading/instruments.yml`    |
| `config/strategy.yml`       | `config/trading/strategy.yml`       |
| `data/raw/*.csv`            | `data/trading/historical/*.csv`     |
| `data/raw/replay_*.csv`     | `data/trading/replay/*.csv`         |
| `scripts/verify_account.py` | `scripts/trading/verify_account.py` |
| `src/or_core.py`            | `services/trading/or_core.py`       |
| `logs/*.log`                | `logs/trading/*.log`                |
