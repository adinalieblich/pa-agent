# GitHub Actions deploy

## What this does

Every push to `main` that touches code (not docs/scripts) auto-deploys to AWS Lambda. You can also trigger manually from the **Actions** tab → **Deploy to AWS Lambda** → **Run workflow**.

Typical run: ~4–6 minutes (npm install + SAM build + deploy).

## One-time setup (you do this in GitHub web UI)

1. Open your repo: https://github.com/yourname/voice-assistant
2. Click **Settings** (top tab)
3. Left sidebar → **Secrets and variables** → **Actions**
4. Click **New repository secret** and add THREE secrets:

| Name | Value |
|---|---|
| `AWS_ACCESS_KEY_ID` | From your `Downloads/pa-agent-deploy_credentials.csv` (Access key ID column) |
| `AWS_SECRET_ACCESS_KEY` | From the same CSV (Secret access key column) |

Region is hardcoded to `ap-southeast-2` in the workflow — no secret needed.

5. That's it. The next push to `main` deploys automatically.

## How to drive this from your phone

1. Open **claude.ai/code** in Safari on iPhone, sign in
2. Connect this GitHub repo (one-time OAuth)
3. Tell Claude what to build
4. Claude commits + pushes to a branch
5. (If pushed to a branch, open the PR and click merge — one tap)
6. GitHub Actions deploys to AWS in ~5 min
7. Refresh the PWA on your phone to see the change

## Files

- `deploy.yml` — the actual workflow. Triggers on push to main + manual.

## Troubleshooting

- **Deploy fails with "InvalidClientTokenId"** → AWS secrets are wrong. Re-paste from CSV.
- **No changes detected** → That's fine; the `--no-fail-on-empty-changeset` flag handles it.
- **Build fails on `npm ci`** → `package-lock.json` is out of sync; run `npm install` locally and commit the new lock.
- **SAM deploy times out** → AWS region might be wrong; check `ap-southeast-2` in the workflow.
