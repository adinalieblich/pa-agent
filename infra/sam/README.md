# PA-Agent — AWS Lambda deployment

Permanent infrastructure for the Layer-1 voice → Notion pipeline. Replaces
the local FastAPI server + ngrok tunnel with API Gateway + Lambda, and
moves the nag worker from a long-running loop to an EventBridge schedule.

## What gets deployed

| Resource | Purpose |
|---|---|
| `pa-agent-webhook-prod` (Lambda) | Mangum-wrapped FastAPI app. Handles `/capture`, `/api/*`. |
| `pa-agent-nag-prod` (Lambda) | One nag-worker tick. EventBridge fires every 5 min. |
| `pa-agent-api-prod` (HTTP API) | Permanent public URL. Replaces ngrok. |
| `pa-agent-nag-state-prod-<acct>` (S3) | Persists `page_id → last_notified_at` map. |
| `/pa-agent/prod/*` (SSM SecureString) | Secrets — Anthropic key, Notion key, ntfy topic, webhook secret. |
| CloudWatch log groups | 14-day retention by default. |

All within AWS free tier for personal-volume use.

## Prerequisites

- AWS CLI configured (`aws configure` done, credentials present).
- AWS SAM CLI installed (`sam --version`). If missing on Windows:
  ```powershell
  winget install Amazon.SAM-CLI
  ```
- Docker Desktop running (SAM uses it to build Python dependencies in a
  Lambda-compatible container).
- A populated `.env` in the repo root (used once to seed SSM).

## First-time deploy (run in order)

From this directory (`infra/sam`):

```powershell
# 1. Push secrets from .env into SSM Parameter Store.
.\seed_parameters.ps1

# 2. Build + deploy the stack.
.\deploy.ps1 -FirstRun
```

The deploy prints an output called **CaptureUrl** — paste that into the iOS
Shortcut to replace the ngrok URL. From that point your phone hits Lambda
directly and the laptop can be off.

## Updating after a code change

```powershell
.\deploy.ps1
```

(No SSM re-seed needed unless `.env` values changed — and if they did, re-run
`seed_parameters.ps1` first.)

## Rotating a secret

Update the SSM parameter directly — no redeploy needed since `_bootstrap.py`
fetches at every cold start.

```powershell
aws ssm put-parameter `
  --name /pa-agent/prod/anthropic-api-key `
  --type SecureString `
  --value "sk-ant-NEW..." `
  --overwrite `
  --region ap-southeast-2
```

Force a cold start by updating any Lambda env var (e.g. bump a no-op tag).

## Tearing down

```powershell
sam delete --stack-name pa-agent --region ap-southeast-2
```

This deletes the stack but **keeps the SSM parameters** (so you don't accidentally
lose secrets). To clean those too:

```powershell
aws ssm get-parameters-by-path --path /pa-agent/prod/ --recursive `
  --query "Parameters[].Name" --output text --region ap-southeast-2 `
  | ForEach-Object { aws ssm delete-parameter --name $_ --region ap-southeast-2 }
```

## How the bridge works

`src/lambda_handlers/_bootstrap.py` runs at cold start in both Lambdas. It
calls `ssm:GetParametersByPath` for `/pa-agent/<env>/*`, decrypts SecureString
values, and writes each into `os.environ` with the conventional name
(`/pa-agent/prod/anthropic-api-key` → `ANTHROPIC_API_KEY`).

After that, `src/config.py` and everything downstream loads the same way
it does locally — no Lambda-specific code in the app layer.

## Cost notes

Steady-state monthly cost for personal use (≤100 webhook calls/day +
288 nag ticks/day at this config):

- Lambda: $0 (free tier covers ~1M invocations/mo)
- HTTP API: $0 (1M req/mo free for 12 months, then ~$0.30)
- EventBridge: $0 (scheduled rules are essentially free)
- S3: <$0.01 (one tiny JSON object, gets read/written 288 times/day)
- CloudWatch logs: $0 (under 5GB free tier with 14-day retention)
- SSM Parameter Store: $0 (Standard tier free for ≤10k params)
- Data transfer out: ~$0 (small JSON payloads)

**Expect $0/month** for the first year. Year 2 add ~$0.30/month for HTTP API.
