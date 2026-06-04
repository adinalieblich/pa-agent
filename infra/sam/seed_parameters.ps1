<#
.SYNOPSIS
    Seed SSM Parameter Store with secrets from a local .env file.

.DESCRIPTION
    One-time setup. Reads the .env file in the repo root, writes each known
    secret to SSM under /pa-agent/<env>/<key-name> as a SecureString (or
    String for non-secret IDs). The Lambda handlers fetch these at cold
    start via src/lambda_handlers/_bootstrap.py.

    Idempotent: re-running overwrites existing values.

.PARAMETER EnvName
    Deployment environment. Default: prod.

.PARAMETER EnvFile
    Path to the .env file. Default: ..\..\.env relative to this script.

.PARAMETER Region
    AWS region. Default: ap-southeast-2.
#>

[CmdletBinding()]
param(
    [string]$EnvName = "prod",
    [string]$EnvFile = (Join-Path $PSScriptRoot "..\..\.env"),
    [string]$Region = "ap-southeast-2"
)

$ErrorActionPreference = "Stop"

# Locate aws.exe (winget install puts it here on Windows).
$awsExe = "aws"
$wingetPath = "C:\Program Files\Amazon\AWSCLIV2\aws.exe"
if (Test-Path $wingetPath) {
    $awsExe = $wingetPath
}

if (-not (Test-Path $EnvFile)) {
    Write-Error ".env file not found at: $EnvFile"
    exit 1
}

# Which keys are SecureString vs String.
$SecretKeys = @(
    "ANTHROPIC_API_KEY",
    "NOTION_API_KEY",
    "WEBHOOK_SHARED_SECRET",
    "NTFY_TOPIC",
    "VAPID_PRIVATE_KEY"
)

$StringKeys = @(
    "NOTION_TASKS_DS_ID",
    "NOTION_PROJECTS_DS_ID",
    "NOTION_JOBS_DS_ID",
    "NOTION_BRAIN_DUMP_PAGE_ID",
    "VAPID_PUBLIC_KEY",
    "VAPID_SUBJECT",
    "PA_LOCAL_TZ"
)

$KnownKeys = $SecretKeys + $StringKeys

# Parse .env into a hashtable. Format KEY=VALUE per line. Hash-starting lines skipped.
$envValues = @{}
Get-Content $EnvFile | ForEach-Object {
    $line = $_.Trim()
    if ($line -eq "" -or $line.StartsWith("#")) { return }
    if ($line -match "^([A-Z_][A-Z0-9_]*)=(.*)$") {
        $k = $matches[1]
        $v = $matches[2]
        # Strip surrounding quotes if present.
        if ($v -match '^"(.*)"$' -or $v -match "^'(.*)'$") {
            $v = $matches[1]
        }
        $envValues[$k] = $v
    }
}

Write-Host "Seeding SSM parameters under /pa-agent/$EnvName/ in $Region" -ForegroundColor Cyan
Write-Host ""

$success = 0
$skipped = 0

foreach ($key in $KnownKeys) {
    $val = $envValues[$key]
    if ([string]::IsNullOrWhiteSpace($val)) {
        Write-Host "  - $key  (skipped: not set in .env)" -ForegroundColor DarkGray
        $skipped++
        continue
    }

    # SSM parameter naming: lowercase + hyphens, matches _bootstrap.py expectation.
    $leaf = $key.ToLower().Replace("_", "-")
    $paramName = "/pa-agent/$EnvName/$leaf"
    $isSecret = $SecretKeys -contains $key
    if ($isSecret) {
        $paramType = "SecureString"
        $marker = "[SECRET]"
    } else {
        $paramType = "String"
        $marker = "[plain] "
    }

    $args = @(
        "ssm", "put-parameter",
        "--name", $paramName,
        "--type", $paramType,
        "--overwrite",
        "--region", $Region,
        "--description", "PA-Agent $key",
        "--value", $val
    )

    & $awsExe @args | Out-Null
    if ($LASTEXITCODE -eq 0) {
        Write-Host "  $marker $paramName  ($paramType)" -ForegroundColor Green
        $success++
    } else {
        Write-Host "  FAIL $paramName  (aws ssm put-parameter failed)" -ForegroundColor Red
    }
}

Write-Host ""
Write-Host "Wrote $success parameters, skipped $skipped." -ForegroundColor Cyan

Write-Host ""
Write-Host "Current parameters in this prefix:" -ForegroundColor Cyan
& $awsExe ssm get-parameters-by-path --path "/pa-agent/$EnvName/" --recursive --region $Region --query "Parameters[].[Name,Type]" --output table
