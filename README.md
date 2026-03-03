# Deployment Incident Orchestration

An agentic orchestration system for monitoring, diagnosing, and remediating errors in Next.js server deployments.

## Overview

This system uses LangGraph to coordinate multiple AI agents across monitoring, diagnosis, remediation, and communication workflows. It's designed to automate incident response while maintaining human oversight.

## Architecture

- **Orchestration**: LangGraph graphs coordinating multi-agent workflows
- **Agents**: Specialized agents for monitoring, diagnosis, remediation, and communication
- **Tools**: Integration with Docker, Redis, logs, and notification systems  
- **Persistence**: State management and checkpoint storage
- **Evaluation**: Metrics and benchmarking for agent performance

See [docs/architecture.md](docs/architecture.md) for detailed architecture documentation.

## Quick Start

### Installation

```bash
pip install -e .
```

### Configuration

Copy `.env.example` to `.env` and configure your environment variables.

### Running the System

This repository provides both an API service and a background worker that can be run
standalone (see `app/main.py` and `app/worker.py`). In production you will typically
run the Python orchestrator alongside the Next.js application and Redis instance.

#### Docker compose

Below is an example snippet you can add to the existing `docker-compose.yml` for the
Next.js app. It mounts the same `./logs` directory so the orchestrator can inspect
error events, and it shares the Redis network for streaming incidents:

```yaml
  orchestrator:
    build:
      context: ./agents-orchestration
      dockerfile: Dockerfile
    container_name: orchestrator
    environment:
      - REDIS_URL=redis://redis:6379
      - REDIS_CHANNEL=deployment-incidents
      - REDIS_LOG_STREAM=app-logs  # match the stream used by the web service
      - LOG_DIR=/app/logs   # mounted volume, same path as web container
    volumes:
      - ./logs:/app/logs    # share log directory from web service
    depends_on:
      - redis
    # you can optionally expose ports for the REST API
    ports:
      - "8000:8000"
```

Once the service is running, the orchestrator will periodically poll the log
files and push any detected errors into the Redis stream.  The logging subsystem
mirrors the Next.js service:

- log records are emitted as one-JSON-object‑per‑line in ``./logs/app-YYYY-MM-DD.log``
  (daily rotation).
- every record is also sent to the Redis stream named by ``REDIS_LOG_STREAM``
  (default ``app-logs``) under a field called ``data``.
- the monitoring agent reads from the filesystem first and falls back to the
  same Redis stream when the directory is empty.

You can also hit the `/monitor/run` endpoint manually or list recent incidents via
`/incidents`.

#### Local development

```bash
# create environment, install dependencies
python -m venv .venv
source .venv/bin/activate  # or .\.venv\Scripts\activate on Windows
pip install -r requirements.txt
pip install -e .

# set environment variables (see .env.example)

# start API
uvicorn app.main:app --reload

# in another shell run background worker
python -m app.worker
```




## License

MIT
