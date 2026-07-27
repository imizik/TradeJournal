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
if ($privateDatabaseUrl -and -not $ingressDatabaseUrl) {
  Write-Error (
    "Private DATABASE_URL is configured, but TRADINGVIEW_DATABASE_URL is " +
    "blank. Set it in backend\.env.tradingview to the same logical database."
  )
  exit 1
}

wt `
  new-tab --title "Frontend" cmd /k "cd /d `"$root\frontend`" && set NEXT_PUBLIC_API_URL=http://localhost:8080&& npm run dev" `
  ";" `
  new-tab --title "Backend" cmd /k "cd /d `"$root\backend`" && set FRONTEND_PUBLIC_URL=http://localhost:3000&& uvicorn app.main:app --reload --host 127.0.0.1 --port 8080" `
  ";" `
  new-tab --title "TradingView Ingress" cmd /k "cd /d `"$root\backend`" && uvicorn app.tradingview_ingress:app --reload --no-access-log --host 127.0.0.1 --port 8090"
