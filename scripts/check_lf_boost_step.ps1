param(
    [switch]$Fresh,
    [Parameter(ValueFromRemainingArguments = $true)]
    [string[]]$ExtraArgs
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

$remainingArgs = @($ExtraArgs | Where-Object { $_ -and $_ -ne "." })

if ($remainingArgs -contains "--fresh" -or $remainingArgs -contains "-fresh" -or $remainingArgs -contains "fresh") {
    $Fresh = $true
    $remainingArgs = @($remainingArgs | Where-Object { $_ -ne "--fresh" -and $_ -ne "-fresh" -and $_ -ne "fresh" })
}

if ($remainingArgs.Count -gt 0) {
    throw "Unknown arguments: $($remainingArgs -join ', '). Supported: -Fresh or --fresh"
}

function Invoke-Step {
    param(
        [Parameter(Mandatory = $true)][string]$Name,
        [Parameter(Mandatory = $true)][scriptblock]$Action
    )

    Write-Host "==> $Name"
    & $Action
    if ($LASTEXITCODE -ne 0) {
        throw "Step failed: $Name (exit code $LASTEXITCODE)"
    }
}

function Invoke-ConfigureWithFallback {
    param(
        [Parameter(Mandatory = $true)][string]$BuildDir,
        [Parameter(Mandatory = $true)][bool]$ForceFresh
    )

    $buildPath = Join-Path (Get-Location) $BuildDir
    if ($ForceFresh -and (Test-Path $buildPath)) {
        Write-Host "==> Fresh build requested; removing '$buildPath'"
        Remove-Item -Recurse -Force $buildPath
    }

    Write-Host "==> Configure CMake"
    cmake -S . -B $BuildDir
    if ($LASTEXITCODE -eq 0) {
        return
    }

    if (-not (Test-Path $buildPath)) {
        throw "Step failed: Configure CMake (exit code $LASTEXITCODE)"
    }

    Write-Warning "Initial configure failed. Retrying once with a fresh '$BuildDir' directory."
    Remove-Item -Recurse -Force $buildPath
    cmake -S . -B $BuildDir
    if ($LASTEXITCODE -ne 0) {
        throw "Step failed: Configure CMake retry (exit code $LASTEXITCODE)"
    }
}

$repoRoot = Resolve-Path (Join-Path $PSScriptRoot "..")
Push-Location $repoRoot

try {
    $buildDir = "build"
    $config = "Release"
    $windowMs = 1.0
    $maxBoundaryExcessDb = 1.0

    Invoke-ConfigureWithFallback -BuildDir $buildDir -ForceFresh $Fresh.IsPresent
    Invoke-Step "Build Release" { cmake --build $buildDir --config $config }

    $harness = Get-ChildItem -Path $buildDir -Recurse -File -Filter "vst3_harness.exe" |
        Sort-Object LastWriteTime -Descending |
        Select-Object -First 1
    if ($null -eq $harness) {
        throw "Could not find vst3_harness.exe under '$buildDir'."
    }

    $plugin = Get-ChildItem -Path $buildDir -Recurse -Directory -Filter "*.vst3" |
        Sort-Object LastWriteTime -Descending |
        Select-Object -First 1
    if ($null -eq $plugin) {
        throw "Could not find a built .vst3 plugin directory under '$buildDir'."
    }

    $caseLow = Join-Path $repoRoot "tests/cases/lf_boost_step_0pct.json"
    $caseHigh = Join-Path $repoRoot "tests/cases/lf_boost_step_100pct.json"
    $sineInput = Join-Path $repoRoot "tests/_generated/sine1k.wav"
    $generatedDir = Join-Path $repoRoot "tests/_generated"
    $artifactsRoot = Join-Path $repoRoot "artifacts"
    New-Item -ItemType Directory -Force -Path $generatedDir | Out-Null
    New-Item -ItemType Directory -Force -Path $artifactsRoot | Out-Null

    $timestamp = Get-Date -Format "yyyyMMdd_HHmmss"
    $runOutDir = Join-Path $artifactsRoot "lf_boost_step_$timestamp"
    $lowOutDir = Join-Path $runOutDir "lf_boost_0pct"
    $highOutDir = Join-Path $runOutDir "lf_boost_100pct"
    New-Item -ItemType Directory -Force -Path $lowOutDir | Out-Null
    New-Item -ItemType Directory -Force -Path $highOutDir | Out-Null

    Invoke-Step "Generate test WAVs" {
        python scripts/gen_test_wavs.py --outdir $generatedDir --sr 48000 --seconds 2.0 --channels 2
    }

    Invoke-Step "Render LF boost 0%" {
        & $harness.FullName render --plugin $plugin.FullName --in $sineInput --outdir $lowOutDir --sr 48000 --bs 256 --ch 2 --case $caseLow
    }

    Invoke-Step "Render LF boost 100%" {
        & $harness.FullName render --plugin $plugin.FullName --in $sineInput --outdir $highOutDir --sr 48000 --bs 256 --ch 2 --case $caseHigh
    }

    $resultJson = Join-Path $runOutDir "step_metrics.json"
    Invoke-Step "Check boundary RMS" {
        python scripts/check_step_boundary.py `
            --low (Join-Path $lowOutDir "wet.wav") `
            --high (Join-Path $highOutDir "wet.wav") `
            --window-ms $windowMs `
            --max-boundary-excess-db $maxBoundaryExcessDb `
            --out $resultJson
    }

    Write-Host ""
    Write-Host "LF boost step check completed successfully."
    Write-Host "Harness : $($harness.FullName)"
    Write-Host "Plugin  : $($plugin.FullName)"
    Write-Host "Output  : $runOutDir"
}
catch {
    Write-Error $_
    exit 1
}
finally {
    Pop-Location
}
