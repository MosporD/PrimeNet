param(
    [string]$Python32 = "",
    [string]$ProjectRoot = ""
)

$ErrorActionPreference = "Stop"

if (-not $ProjectRoot) {
    $ProjectRoot = Split-Path -Parent $PSScriptRoot
}

if (-not $Python32) {
    $candidates = @(
        "C:\Python311-32\python.exe",
        "C:\Python310-32\python.exe",
        "C:\Python39-32\python.exe",
        "C:\Program Files (x86)\Python311-32\python.exe",
        "C:\Program Files (x86)\Python310-32\python.exe",
        "C:\Program Files (x86)\Python39-32\python.exe"
    )
    foreach ($c in $candidates) {
        if (Test-Path $c) {
            $Python32 = $c
            break
        }
    }
}

if (-not $Python32 -or -not (Test-Path $Python32)) {
    Write-Host "32-bit Python not found. Provide it with -Python32 <path>." -ForegroundColor Yellow
    Write-Host "Example:" -ForegroundColor Yellow
    Write-Host "  .\scripts\run_nemo_com_probe_32.ps1 -Python32 `"C:\Python311-32\python.exe`"" -ForegroundColor Yellow
    exit 1
}

Write-Host "Using 32-bit Python: $Python32"
& $Python32 -c "import struct,sys;print('python',sys.version);print('pointer_bits',struct.calcsize('P')*8)"

$scriptPath = Join-Path $ProjectRoot "scripts\nemo_com_probe.py"
if (-not (Test-Path $scriptPath)) {
    Write-Host "nemo_com_probe.py not found at $scriptPath" -ForegroundColor Red
    exit 1
}

Push-Location $ProjectRoot
try {
    & $Python32 $scriptPath
} finally {
    Pop-Location
}

