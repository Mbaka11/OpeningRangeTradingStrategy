# Use an official Python runtime as a parent image
FROM python:3.10-slim

# Set environment variables
# PYTHONUNBUFFERED: Forces stdout/stderr to be flushed immediately (logs appear faster)
ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1
ENV PYTHONPATH=/app

# Set the working directory in the container
WORKDIR /app

# Install system dependencies (gcc needed for some python math libraries)
RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc \
    && rm -rf /var/lib/apt/lists/*

# Install Python dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy the rest of the application code
COPY . .

# Create logs directories for all services
RUN mkdir -p /app/logs/trading /app/logs/govtrades

# Default entrypoint - can be overridden with docker run command
# Usage:
#   Trading bot:    docker run <image>
#   GovTrades:      docker run <image> python -m services.govtrades.main
CMD ["python", "-m", "services.trading.run_bot"]