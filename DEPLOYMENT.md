# Google Cloud Deployment Guide

This project runs on a Google Compute Engine VM (`openingrange-bot`) using Docker. The deployment workflow involves building the image in Cloud Shell and then pulling/restarting it on the VM.

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
OANDA_ACCOUNT_ID=101-001-YOUR-ID
OANDA_API_TOKEN=your_oanda_token
OANDA_ENV=practice
OANDA_INSTRUMENT=NAS100_USD
OANDA_TIMEZONE=America/New_York

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

# 3. Start the new version (Linking the .env file)
sudo docker run -d \
  --name trading-bot \
  --restart always \
  --env-file .env \
  gcr.io/onyx-seeker-479417-d5/my-bot-image:latest

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
