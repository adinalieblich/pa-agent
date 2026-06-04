<#
.SYNOPSIS
    Build + deploy the PA-Agent SAM stack.

.DESCRIPTION
    Pipeline:
      1. Build pwa-v2 (npm run build) -> pwa-v2/dist
      2. sam build (packages Python + the static dirs)
      3. Strip bloat from the Lambda zip (node_modules, source files, docs)
      4. sam deploy
      5. Print stack outputs.

    Step 3 is needed because SAM packages the whole CodeUri as-is, including
    pwa-v2/node_modules (~47 MB) and the *.docx / *.md spec files we don't
    need at runtime.

.PARAMETER FirstRun
    Skip the change-set confirmation prompt.

.PARAMETER SkipFrontend
    Don't rebuild pwa-v2 (e.g. when iterating on backend-only changes).
#>

[CmdletBinding()]
param(
    [switch]$FirstRun,
    [switch]$SkipFrontend
)

$ErrorActionPreference = "Stop"

$repoRoot = Resolve-Path (Join-Path $PSScriptRoot "..\..")
$pwaV2 = Join-Path $repoRoot "pwa-v2"
$samDir = $PSScriptRoot

Push-Location $samDir
try {

    if (-not $SkipFrontend) {
        Write-Host "==> Building pwa-v2" -ForegroundColor Cyan
        Push-Location $pwaV2
        try {
            if (-not (Test-Path "node_modules")) {
                Write-Host "    (first run - npm install)"
                npm install
                if ($LASTEXITCODE -ne 0) { throw "npm install failed" }
            }
            npm run build
            if ($LASTEXITCODE -ne 0) { throw "npm run build failed" }
        } finally {
            Pop-Location
        }
    }

    Write-Host ""
    Write-Host "==> sam build" -ForegroundColor Cyan
    sam build
    if ($LASTEXITCODE -ne 0) { throw "sam build failed" }

    Write-Host ""
    Write-Host "==> Trimming Lambda package (removing bloat)" -ForegroundColor Cyan
    $buildDirs = Get-ChildItem ".aws-sam\build" -Directory -ErrorAction SilentlyContinue `
        | Where-Object { $_.Name -in @("WebhookFunction", "NagTickFunction") }

    $trimPatterns = @(
        "pwa-v2\node_modules",
        "pwa-v2\src",
        "pwa-v2\package.json",
        "pwa-v2\package-lock.json",
        "pwa-v2\vite.config.js",
        "pwa-v2\index.html",
        "pwa-v2\public",
        "CLAUDE_CODE_INSTRUCTIONS.md",
        "PA-AGENT-API.docx",
        "PA_AGENT_SPEC.md",
        "PA_AGENT_SPEC_v3.md",
        "files.zip",
        "PA-AGENT-API*",
        "~`$*",
        "tests",
        "logs",
        ".venv",
        ".git"
    )

    foreach ($bd in $buildDirs) {
        foreach ($pat in $trimPatterns) {
            $matches = Get-ChildItem -Path $bd.FullName -Filter $pat -Force -ErrorAction SilentlyContinue
            foreach ($m in $matches) {
                Remove-Item -Recurse -Force $m.FullName -ErrorAction SilentlyContinue
            }
            # Also handle path-like patterns (e.g. pwa-v2\node_modules)
            if ($pat -like "*\*") {
                $p = Join-Path $bd.FullName $pat
                if (Test-Path $p) {
                    Remove-Item -Recurse -Force $p -ErrorAction SilentlyContinue
                }
            }
        }
        $sizeMb = [math]::Round(((Get-ChildItem -Recurse -File $bd.FullName | Measure-Object Length -Sum).Sum / 1MB), 1)
        Write-Host "    $($bd.Name) trimmed to ${sizeMb} MB" -ForegroundColor Green
    }

    Write-Host ""
    Write-Host "==> sam deploy" -ForegroundColor Cyan
    if ($FirstRun) {
        sam deploy --no-confirm-changeset
    } else {
        sam deploy
    }
    if ($LASTEXITCODE -ne 0) { throw "sam deploy failed" }

    Write-Host ""
    Write-Host "==> Deploy complete." -ForegroundColor Green
    sam list stack-outputs --output table
}
finally {
    Pop-Location
}
