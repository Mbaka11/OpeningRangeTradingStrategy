# Deployment Guide

---

# 🆕 FIRST TIME SETUP

_Only do this once when setting up a new VM._

## Step 1: Build Image (Cloud Shell)

```bash
cd OpeningRangeTradingStrategy
gcloud builds submit --tag gcr.io/onyx-seeker-479417-d5/my-bot-image .
```

## Step 2: SSH into VM

```bash
gcloud compute ssh openingrange-bot --zone us-central1-a
```

## Step 3: Create `.env` file

```bash
export TERM=xterm
nano .env
```

Paste this template:

```env
# Trading
OANDA_ACCOUNT_ID=101-001-YOUR-ID
OANDA_API_TOKEN=your_token
OANDA_ENV=practice
OANDA_INSTRUMENT=NAS100_USD
OANDA_TIMEZONE=America/New_York

# Twitter
TWITTER_API_KEY=xxx
TWITTER_API_SECRET=xxx
TWITTER_ACCESS_TOKEN=xxx
TWITTER_ACCESS_SECRET=xxx

# Logging
LOG_LEVEL=INFO
```

Save: `Ctrl+O`, Exit: `Ctrl+X`

## Step 4: Authenticate Docker

```bash
TOKEN=$(curl -s -H "Metadata-Flavor: Google" "http://metadata.google.internal/computeMetadata/v1/instance/service-accounts/default/token" | grep -o '"access_token":"[^"]*"' | cut -d'"' -f4)
mkdir -p $(pwd)/.docker-temp
sudo docker --config $(pwd)/.docker-temp login -u oauth2accesstoken -p "$TOKEN" https://gcr.io
```

## Step 5: Pull & Run

```bash
# Pull image
sudo docker --config $(pwd)/.docker-temp pull gcr.io/onyx-seeker-479417-d5/my-bot-image:latest

# Create logs folder
mkdir -p $(pwd)/logs/trading

# Start container
sudo docker run -d \
  --name trading-bot \
  --restart always \
  --env-file .env \
  -v $(pwd)/logs/trading:/app/logs/trading \
  gcr.io/onyx-seeker-479417-d5/my-bot-image:latest

# Verify it's running
sudo docker logs -f trading-bot
```

---

# 🔄 UPDATING (Routine Deploy)

_Do this every time you push code changes._

## Step 1: Build New Image (Cloud Shell)

```bash
cd OpeningRangeTradingStrategy
gcloud builds submit --tag gcr.io/onyx-seeker-479417-d5/my-bot-image .
```

## Step 2: Update on VM

```bash
# SSH into VM
gcloud compute ssh openingrange-bot --zone us-central1-a

# Authenticate Docker
TOKEN=$(curl -s -H "Metadata-Flavor: Google" "http://metadata.google.internal/computeMetadata/v1/instance/service-accounts/default/token" | grep -o '"access_token":"[^"]*"' | cut -d'"' -f4)
mkdir -p $(pwd)/.docker-temp
sudo docker --config $(pwd)/.docker-temp login -u oauth2accesstoken -p "$TOKEN" https://gcr.io

# Pull latest image
sudo docker --config $(pwd)/.docker-temp pull gcr.io/onyx-seeker-479417-d5/my-bot-image:latest

# Stop & remove old container
sudo docker stop trading-bot
sudo docker rm trading-bot

# Start new container
sudo docker run -d \
  --name trading-bot \
  --restart always \
  --env-file .env \
  -v $(pwd)/logs/trading:/app/logs/trading \
  gcr.io/onyx-seeker-479417-d5/my-bot-image:latest

# Verify it's running
sudo docker logs -f trading-bot
```

---

# 📋 Reference

## Common Commands

| Action               | Command                                      |
| -------------------- | -------------------------------------------- |
| View logs            | `sudo docker logs -f trading-bot`            |
| Stop bot             | `sudo docker stop trading-bot`               |
| Start bot            | `sudo docker start trading-bot`              |
| Restart bot          | `sudo docker restart trading-bot`            |
| Check status         | `sudo docker ps`                             |
| Shell into container | `sudo docker exec -it trading-bot /bin/bash` |

## Troubleshooting

| Issue                       | Fix                                       |
| --------------------------- | ----------------------------------------- |
| Container exits immediately | `sudo docker logs trading-bot`            |
| Twitter 403                 | Check API permissions in Developer Portal |
| OANDA error                 | Verify `.env` credentials                 |
| Module not found            | Rebuild image: `gcloud builds submit ...` |
