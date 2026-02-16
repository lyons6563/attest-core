# Ensure Postgres for Decision Engine (Windows + Docker)
# Idempotent: stop/remove existing container, recreate, then ALWAYS run 000_base_schema.sql
# and 001_audit_hardening.sql against the same container/database the app uses. Safe to re-run.
# Run from project root: .\scripts\ensure-postgres.ps1

$ErrorActionPreference = "Stop"
$ProjectRoot = $PSScriptRoot + "\.."
$BaseSchemaFile = Join-Path $ProjectRoot "migrations\000_base_schema.sql"
$AuditMigrationFile = Join-Path $ProjectRoot "migrations\001_audit_hardening.sql"
$ContainerName = "decision-engine-db"
$DbName = "decision_engine"
$PortHost = "55432"
$PortContainer = "5432"

function Exit-Fail {
    param([string]$Message)
    Write-Host ""
    Write-Host "FAIL - $Message" -ForegroundColor Red
    Write-Host "  Fix the issue above, then run: .\scripts\ensure-postgres.ps1" -ForegroundColor Yellow
    exit 1
}

function Exit-Ready {
    Write-Host ""
    Write-Host "READY - Decision Engine database is set up. Start the app with:" -ForegroundColor Green
    Write-Host "  uvicorn app.main:app --reload" -ForegroundColor White
    Write-Host ""
    exit 0
}

# Step 1: Docker must be running
Write-Host "Step 1: Checking Docker..." -ForegroundColor Cyan
try {
    $null = docker info 2>&1
    if ($LASTEXITCODE -ne 0) { throw "Docker not running" }
} catch {
    Exit-Fail "Docker is not running. Start Docker Desktop from the Start menu, wait until it is running, then run this script again."
}
Write-Host "  Docker is running." -ForegroundColor Green

# Step 2: Stop and remove existing container (idempotent: same result every run)
Write-Host ""
Write-Host "Step 2: Ensuring container '$ContainerName' (stop and remove if exists)..." -ForegroundColor Cyan
$existing = docker ps -a --filter "name=^${ContainerName}$" --format "{{.Names}}"
if ($existing) {
    docker stop $ContainerName 2>&1 | Out-Null
    docker rm $ContainerName 2>&1 | Out-Null
    if ($LASTEXITCODE -ne 0) {
        Exit-Fail "Could not remove existing container. Try: docker stop $ContainerName; docker rm $ContainerName"
    }
    Write-Host "  Removed existing container." -ForegroundColor Yellow
}
Write-Host "  Creating container with port $PortHost`:${PortContainer}..." -ForegroundColor Yellow
docker run -d `
    --name $ContainerName `
    -p "${PortHost}:${PortContainer}" `
    -e POSTGRES_USER=postgres `
    -e POSTGRES_PASSWORD=postgres `
    -e POSTGRES_DB=$DbName `
    postgres:15
if ($LASTEXITCODE -ne 0) {
    Exit-Fail "Could not create container. Check Docker Desktop and try again."
}
Write-Host "  Container created and started." -ForegroundColor Green

# Step 3: Wait until Postgres accepts SQL connections (retry loop)
# The container can be "running" before Postgres inside it is ready to accept connections.
# Running migrations before pg_isready succeeds can cause connection errors or partial runs.
# So we poll pg_isready until it returns success, with a bounded timeout; only then do we run migrations.
Write-Host ""
Write-Host "Step 3: Waiting for Postgres to accept connections..." -ForegroundColor Cyan
$maxWaitSeconds = 60
$attempt = 0
$ready = $false
while ($attempt -lt $maxWaitSeconds) {
    $attempt++
    & docker exec $ContainerName pg_isready -U postgres -d $DbName 2>&1 | Out-Null
    if ($LASTEXITCODE -eq 0) {
        $ready = $true
        break
    }
    Start-Sleep -Seconds 1
}
if (-not $ready) {
    Exit-Fail "Postgres did not accept connections within ${maxWaitSeconds} seconds. The container may still be initializing. Check Docker: docker logs $ContainerName"
}
Write-Host "  Postgres is ready (accepted connection after ${attempt}s)." -ForegroundColor Green

# Step 4: ALWAYS run base schema (idempotent: CREATE TABLE IF NOT EXISTS)
# Step 5: ALWAYS run audit hardening (idempotent: ADD COLUMN IF NOT EXISTS)
# Both run against the SAME container ($ContainerName) and database ($DbName) the app uses (127.0.0.1:$PortHost / $DbName).
if (-not (Test-Path $BaseSchemaFile)) {
    Exit-Fail "Base schema file not found: $BaseSchemaFile"
}
Write-Host ""
Write-Host "Step 4: Running base schema (000_base_schema.sql)..." -ForegroundColor Cyan
Get-Content $BaseSchemaFile -Raw -Encoding UTF8 | docker exec -i $ContainerName psql -U postgres -d $DbName --set ON_ERROR_STOP=on
if ($LASTEXITCODE -ne 0) {
    Exit-Fail "Base schema migration failed. Check the SQL file: migrations\000_base_schema.sql"
}
Write-Host "  SUCCESS: 000_base_schema.sql applied (container=$ContainerName, database=$DbName)." -ForegroundColor Green

if (-not (Test-Path $AuditMigrationFile)) {
    Exit-Fail "Audit migration file not found: $AuditMigrationFile"
}
Write-Host ""
Write-Host "Step 5: Running audit hardening (001_audit_hardening.sql)..." -ForegroundColor Cyan
Get-Content $AuditMigrationFile -Raw -Encoding UTF8 | docker exec -i $ContainerName psql -U postgres -d $DbName --set ON_ERROR_STOP=on
if ($LASTEXITCODE -ne 0) {
    Exit-Fail "Audit hardening migration failed. Check: migrations\001_audit_hardening.sql"
}
Write-Host "  SUCCESS: 001_audit_hardening.sql applied (container=$ContainerName, database=$DbName)." -ForegroundColor Green
Write-Host "  Migrated DB: host=127.0.0.1 port=$PortHost dbname=$DbName" -ForegroundColor Gray

# Step 6: Verify required columns on custody_events
Write-Host ""
Write-Host "Step 6: Verifying schema (custody_events columns)..." -ForegroundColor Cyan
$expectedColumns = @("actor_id", "session_id", "source_system", "system_suggestion", "options_presented", "human_selection", "decision_timestamp")
$query = "SELECT column_name FROM information_schema.columns WHERE table_schema = 'public' AND table_name = 'custody_events' AND column_name = ANY(ARRAY['" + ($expectedColumns -join "','") + "']);"
$result = docker exec $ContainerName psql -U postgres -d $DbName -t -A -c $query 2>&1
if ($LASTEXITCODE -ne 0) {
    Exit-Fail "Could not verify custody_events. Table may not exist."
}
$found = ($result -split "`n" | ForEach-Object { $_.Trim() } | Where-Object { $_ -ne "" })
$missing = $expectedColumns | Where-Object { $_ -notin $found }
if ($missing.Count -gt 0) {
    Exit-Fail "Missing columns on custody_events: $($missing -join ', '). Re-run this script."
}
Write-Host "  All required columns exist." -ForegroundColor Green

Write-Host ""
Write-Host "Database: 127.0.0.1:${PortHost} / $DbName" -ForegroundColor Gray
Exit-Ready
