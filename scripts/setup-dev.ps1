# ==============================================================================
# AGENTOPS DEVELOPMENT ARCHITECTURE SETUP UTILITY
# Windows OS target bootstrap script for configuring active workspaces.
# ==============================================================================

Write-Host "==========================================================" -ForegroundColor Cyan
Write-Host "      AGENTOPS COGNITIVE MONOREPO INITIALIZER             " -ForegroundColor Cyan
Write-Host "==========================================================" -ForegroundColor Cyan
Write-Host "Bootstrapping principal developer tools..." -ForegroundColor Gray

# 1. Verification of system dependencies
Write-Host "`n[step 1] Verifying Node.js and NPM installations..." -ForegroundColor Yellow
if (Get-Command node -ErrorAction SilentlyContinue) {
    $nodeVersion = node --version
    Write-Host "  Found Node: $nodeVersion" -ForegroundColor Green
} else {
    Write-Warning "  Node.js was not detected in PATH variables. Please install Node v20+."
}

Write-Host "`n[step 2] Checking Python 3 and Poetry environment handlers..." -ForegroundColor Yellow
if (Get-Command python -ErrorAction SilentlyContinue) {
    $pyVersion = python --version
    Write-Host "  Found Python: $pyVersion" -ForegroundColor Green
} else {
    Write-Warning "  Python executable was not found. Please install Python 3.11."
}

if (Get-Command poetry -ErrorAction SilentlyContinue) {
    Write-Host "  Poetry dependencies manager active." -ForegroundColor Green
} else {
    Write-Host "  Poetry not detected. Installing global poetry wrapper..." -ForegroundColor Gray
    (Invoke-WebRequest -Uri https://install.python-poetry.org -UseBasicParsing).Content | python -
}

# 2. Local variables bootstrapping
Write-Host "`n[step 3] Creating developer environment file (.env)..." -ForegroundColor Yellow
if (-not (Test-Path ".env")) {
    Copy-Item ".env.example" ".env"
    Write-Host "  Successfully cloned .env from example template." -ForegroundColor Green
} else {
    Write-Host "  Active .env config detected. Preserving existing overrides." -ForegroundColor Gray
}

# 3. Installing dependencies
Write-Host "`n[step 4] Building root JavaScript workspace node_modules..." -ForegroundColor Yellow
npm install

Write-Host "`n[step 5] Installing Python applications dependencies via Poetry..." -ForegroundColor Yellow
Write-Host "  Synchronizing api-gateway..." -ForegroundColor Gray
Push-Location apps/api-gateway
poetry install
Pop-Location

Write-Host "  Synchronizing agent-runtime..." -ForegroundColor Gray
Push-Location apps/agent-runtime
poetry install
Pop-Location

Write-Host "`n==========================================================" -ForegroundColor Cyan
Write-Host "   AGENTOPS SCRIPTS COMPLETED. MONOREPO STACK ACTIVE      " -ForegroundColor Cyan
Write-Host "   To trigger local stack containers run:                 " -ForegroundColor Green
Write-Host "     docker compose up -d                                 " -ForegroundColor Green
Write-Host "   To launch developer server nodes run:                 " -ForegroundColor Green
Write-Host "     npm run dev                                          " -ForegroundColor Green
Write-Host "==========================================================" -ForegroundColor Cyan
