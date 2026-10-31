$ErrorActionPreference = 'Stop'
Push-Location $PSScriptRoot
try {
    if (-not (Test-Path '.venv\Scripts\python.exe')) {
        python -m venv .venv
        if ($LASTEXITCODE -ne 0) { throw 'Python virtual environment creation failed.' }
    }
    & '.\.venv\Scripts\python.exe' -m pip install -r requirements.txt
    if ($LASTEXITCODE -ne 0) { throw 'Dependency installation failed.' }
    if (-not (Test-Path '.env')) { Copy-Item '.env.example' '.env' }
    $MissingModels = @('diabetes', 'heart', 'kidney') | Where-Object { -not (Test-Path "models\$_.json") }
    if ($MissingModels.Count -gt 0) {
        $ExistingModels = Get-ChildItem 'models' -Filter '*.json'
        if ($ExistingModels.Count -gt 0) {
            throw 'Partial model set found. Train missing modules explicitly; setup will not overwrite existing models.'
        }
        & '.\.venv\Scripts\python.exe' -m app.train --demo
        if ($LASTEXITCODE -ne 0) { throw 'Demo model training failed.' }
    }
    Write-Host 'No certificate installation is required for private VS Code tunnel mode.'
    Write-Host 'Start setup: .\.venv\Scripts\python.exe -m app.serve --private-tunnel'
    Write-Host 'Forward port 8000 in VS Code, keep it PRIVATE, then restart with --tunnel-origin (see README).'
    Write-Host 'Use fictional data only; the HTTPS tunnel routes traffic through Microsoft.'
}
finally { Pop-Location }
