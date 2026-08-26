# Starts the frontend and private backend. Set
# TRADINGVIEW_INGRESS_ENABLED=true to also start the optional webhook ingress.
$root = $PSScriptRoot

function Get-DotEnvValue {
  param([string]$Path, [string]$Name)
  if (-not (Test-Path $Path)) { return "" }
  $line = Get-Content $Path |
    Where-Object { $_ -match "^\s*$([regex]::Escape($Name))\s*=" } |
    Select-Object -First 1
  if (-not $line) { return "" }
  return (($line -split "=", 2)[1].Trim()).Trim('"').Trim("'")
}

$tradingViewIngressValue = if ($env:TRADINGVIEW_INGRESS_ENABLED) {
  $env:TRADINGVIEW_INGRESS_ENABLED.Trim().ToLowerInvariant()
} else {
  "false"
}
if (@("1", "true", "yes", "on") -contains $tradingViewIngressValue) {
  $tradingViewIngressEnabled = $true
} elseif (@("", "0", "false", "no", "off") -contains $tradingViewIngressValue) {
  $tradingViewIngressEnabled = $false
} else {
  Write-Error "TRADINGVIEW_INGRESS_ENABLED must be true or false."
  exit 1
}

if ($tradingViewIngressEnabled) {
  $webhookToken = $env:TRADINGVIEW_WEBHOOK_TOKEN
  if (-not $webhookToken) {
    $webhookToken = Get-DotEnvValue `
      "$root\backend\.env.tradingview" `
      "TRADINGVIEW_WEBHOOK_TOKEN"
  }

  $privateDatabaseUrl = $env:DATABASE_URL
  if (-not $privateDatabaseUrl) {
    $privateDatabaseUrl = Get-DotEnvValue "$root\backend\.env" "DATABASE_URL"
  }
  if (-not $privateDatabaseUrl) {
    $privateDatabaseUrl = Get-DotEnvValue "$root\.env" "DATABASE_URL"
  }

  $ingressDatabaseUrl = $env:TRADINGVIEW_DATABASE_URL
  if (-not $ingressDatabaseUrl) {
    $ingressDatabaseUrl = $env:DATABASE_URL
  }
  if (-not $ingressDatabaseUrl) {
    $ingressDatabaseUrl = Get-DotEnvValue `
      "$root\backend\.env.tradingview" `
      "TRADINGVIEW_DATABASE_URL"
  }

  # Keep in sync with MIN_WEBHOOK_TOKEN_BYTES in
  # backend/app/routers/tradingview_webhook.py. Below this the ingress
  # fails closed and 503s every request, including /health.
  $minWebhookTokenBytes = 32

  if (-not $webhookToken) {
    Write-Error (
      "TradingView ingress is enabled, but TRADINGVIEW_WEBHOOK_TOKEN is " +
      "blank. Set it in backend\.env.tradingview."
    )
    exit 1
  }
  $webhookTokenBytes = [System.Text.Encoding]::UTF8.GetByteCount($webhookToken)
  if ($webhookTokenBytes -lt $minWebhookTokenBytes) {
    Write-Error (
      "TRADINGVIEW_WEBHOOK_TOKEN is only $webhookTokenBytes bytes; the " +
      "ingress requires at least $minWebhookTokenBytes and would 503 every " +
      "request. Generate one with: " +
      'python -c "import secrets; print(secrets.token_urlsafe(32))"'
    )
    exit 1
  }
  if ($privateDatabaseUrl -and -not $ingressDatabaseUrl) {
    Write-Error (
      "Private DATABASE_URL is configured, but TRADINGVIEW_DATABASE_URL is " +
      "blank. Set it in backend\.env.tradingview to the same logical database."
    )
    exit 1
  }
}

if ($tradingViewIngressEnabled) {
  wt `
    new-tab --title "Frontend" cmd /k "cd /d `"$root\frontend`" && set NEXT_PUBLIC_API_URL=http://localhost:8080&& npm run dev" `
    ";" `
    new-tab --title "Backend" cmd /k "cd /d `"$root\backend`" && set FRONTEND_PUBLIC_URL=http://localhost:3000&& uvicorn app.main:app --reload --host 127.0.0.1 --port 8080" `
    ";" `
    new-tab --title "TradingView Ingress" cmd /k "cd /d `"$root\backend`" && uvicorn app.tradingview_ingress:app --reload --no-access-log --host 127.0.0.1 --port 8090"
} else {
  wt `
    new-tab --title "Frontend" cmd /k "cd /d `"$root\frontend`" && set NEXT_PUBLIC_API_URL=http://localhost:8080&& npm run dev" `
    ";" `
    new-tab --title "Backend" cmd /k "cd /d `"$root\backend`" && set FRONTEND_PUBLIC_URL=http://localhost:3000&& uvicorn app.main:app --reload --host 127.0.0.1 --port 8080"
}
