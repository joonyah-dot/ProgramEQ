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

function Read-Metrics {
    param([Parameter(Mandatory = $true)][string]$Path)

    if (-not (Test-Path $Path)) {
        throw "Missing metrics output: $Path"
    }

    return Get-Content -Raw -Path $Path | ConvertFrom-Json
}

function Write-ImpulseWav {
    param(
        [Parameter(Mandatory = $true)][string]$Path,
        [Parameter(Mandatory = $true)][int]$SampleRate,
        [Parameter(Mandatory = $true)][double]$Seconds,
        [Parameter(Mandatory = $true)][int]$Channels
    )

    $numSamples = [int][Math]::Round($SampleRate * $Seconds)
    $bitsPerSample = 16
    $bytesPerSample = $bitsPerSample / 8
    $blockAlign = $Channels * $bytesPerSample
    $byteRate = $SampleRate * $blockAlign
    $dataSize = $numSamples * $blockAlign

    $parentDir = Split-Path -Parent $Path
    New-Item -ItemType Directory -Force -Path $parentDir | Out-Null

    $stream = [System.IO.File]::Open($Path, [System.IO.FileMode]::Create, [System.IO.FileAccess]::Write, [System.IO.FileShare]::Read)
    try {
        $writer = New-Object System.IO.BinaryWriter($stream)
        try {
            $writer.Write([System.Text.Encoding]::ASCII.GetBytes("RIFF"))
            $writer.Write([int](36 + $dataSize))
            $writer.Write([System.Text.Encoding]::ASCII.GetBytes("WAVE"))
            $writer.Write([System.Text.Encoding]::ASCII.GetBytes("fmt "))
            $writer.Write([int]16)
            $writer.Write([int16]1)
            $writer.Write([int16]$Channels)
            $writer.Write([int]$SampleRate)
            $writer.Write([int]$byteRate)
            $writer.Write([int16]$blockAlign)
            $writer.Write([int16]$bitsPerSample)
            $writer.Write([System.Text.Encoding]::ASCII.GetBytes("data"))
            $writer.Write([int]$dataSize)

            for ($sampleIndex = 0; $sampleIndex -lt $numSamples; ++$sampleIndex) {
                $sampleValue = if ($sampleIndex -eq 0) { [int16]29490 } else { [int16]0 }
                for ($channelIndex = 0; $channelIndex -lt $Channels; ++$channelIndex) {
                    $writer.Write($sampleValue)
                }
            }
        }
        finally {
            $writer.Dispose()
        }
    }
    finally {
        $stream.Dispose()
    }
}

$repoRoot = Resolve-Path (Join-Path $PSScriptRoot "..")
Push-Location $repoRoot

try {
    $buildDir = "build"
    $config = "Release"
    $trueBypassThresholdDbfs = -120.0
    $eqDifferenceThresholdDbfs = -90.0

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

    $generatedDir = Join-Path $repoRoot "tests/_generated"
    $artifactsRoot = Join-Path $repoRoot "artifacts"
    New-Item -ItemType Directory -Force -Path $generatedDir | Out-Null
    New-Item -ItemType Directory -Force -Path $artifactsRoot | Out-Null

    $timestamp = Get-Date -Format "yyyyMMdd_HHmmss"
    $runOutDir = Join-Path $artifactsRoot "bypass_semantics_$timestamp"
    $trueBypassOutDir = Join-Path $runOutDir "true_bypass_on"
    $eqInOnOutDir = Join-Path $runOutDir "eq_in_on"
    $eqInOffOutDir = Join-Path $runOutDir "eq_in_off"
    $trueBypassAnalyzeDir = Join-Path $runOutDir "analyze_true_bypass"
    $eqCompareAnalyzeDir = Join-Path $runOutDir "analyze_eq_in_compare"
    New-Item -ItemType Directory -Force -Path $trueBypassOutDir | Out-Null
    New-Item -ItemType Directory -Force -Path $eqInOnOutDir | Out-Null
    New-Item -ItemType Directory -Force -Path $eqInOffOutDir | Out-Null
    New-Item -ItemType Directory -Force -Path $trueBypassAnalyzeDir | Out-Null
    New-Item -ItemType Directory -Force -Path $eqCompareAnalyzeDir | Out-Null

    $trueBypassCase = Join-Path $repoRoot "tests/cases/true_bypass_on.json"
    $eqInOffCase = Join-Path $repoRoot "tests/cases/eq_in_off_lf_boost_set.json"
    $eqInOnCase = Join-Path $repoRoot "tests/cases/fr_pultec_lf_boost_60hz_100pct.json"

    $dryImpulse = Join-Path $generatedDir "impulse.wav"
    Invoke-Step "Generate impulse WAV" {
        Write-ImpulseWav -Path $dryImpulse -SampleRate 48000 -Seconds 2.0 -Channels 2
    }

    $trueBypassWet = Join-Path $trueBypassOutDir "wet.wav"
    $eqInOnWet = Join-Path $eqInOnOutDir "wet.wav"
    $eqInOffWet = Join-Path $eqInOffOutDir "wet.wav"

    Invoke-Step "Render true bypass case" {
        & $harness.FullName render --plugin $plugin.FullName --in $dryImpulse --outdir $trueBypassOutDir --sr 48000 --bs 256 --ch 2 --case $trueBypassCase
    }

    Invoke-Step "Analyze true bypass null" {
        & $harness.FullName analyze --dry $dryImpulse --wet $trueBypassWet --outdir $trueBypassAnalyzeDir --auto-align --null
    }

    Invoke-Step "Render EQ IN on case" {
        & $harness.FullName render --plugin $plugin.FullName --in $dryImpulse --outdir $eqInOnOutDir --sr 48000 --bs 256 --ch 2 --case $eqInOnCase
    }

    Invoke-Step "Render EQ IN off case" {
        & $harness.FullName render --plugin $plugin.FullName --in $dryImpulse --outdir $eqInOffOutDir --sr 48000 --bs 256 --ch 2 --case $eqInOffCase
    }

    Invoke-Step "Analyze EQ IN on/off difference" {
        & $harness.FullName analyze --dry $eqInOffWet --wet $eqInOnWet --outdir $eqCompareAnalyzeDir --auto-align --null
    }

    $trueBypassMetrics = Read-Metrics -Path (Join-Path $trueBypassAnalyzeDir "metrics.json")
    $eqCompareMetrics = Read-Metrics -Path (Join-Path $eqCompareAnalyzeDir "metrics.json")

    if ($null -eq $trueBypassMetrics.deltaRmsDbfs) {
        throw "True bypass metrics missing deltaRmsDbfs"
    }
    if ($null -eq $eqCompareMetrics.deltaRmsDbfs) {
        throw "EQ compare metrics missing deltaRmsDbfs"
    }

    $trueBypassDeltaRmsDbfs = [double]$trueBypassMetrics.deltaRmsDbfs
    $eqCompareDeltaRmsDbfs = [double]$eqCompareMetrics.deltaRmsDbfs

    Write-Host ("True bypass null RMS: {0:F2} dBFS" -f $trueBypassDeltaRmsDbfs)
    Write-Host ("EQ IN on/off delta RMS: {0:F2} dBFS" -f $eqCompareDeltaRmsDbfs)

    if ($trueBypassDeltaRmsDbfs -gt $trueBypassThresholdDbfs) {
        throw ("FAIL: true bypass did not null deeply enough ({0:F2} dBFS > {1:F2} dBFS)." -f $trueBypassDeltaRmsDbfs, $trueBypassThresholdDbfs)
    }

    if ($eqCompareDeltaRmsDbfs -le $eqDifferenceThresholdDbfs) {
        throw ("FAIL: EQ IN on/off renders were too similar ({0:F2} dBFS <= {1:F2} dBFS)." -f $eqCompareDeltaRmsDbfs, $eqDifferenceThresholdDbfs)
    }

    Write-Host "PASS: bypass semantics checks succeeded."
    Write-Host "Output  : $runOutDir"
}
catch {
    Write-Error $_
    exit 1
}
finally {
    Pop-Location
}
