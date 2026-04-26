$ErrorActionPreference = "Stop"

$nmfsPath = "C:\Users\malek.mohammad\OneDrive - Zain Jordan\Desktop\Drive Tests\DT Folder\04 pre\04 pre.1.nmfs"
if (!(Test-Path $nmfsPath)) {
    Write-Error "NMFS file not found: $nmfsPath"
    exit 1
}

$asmPath = "C:\Program Files (x86)\Anite\Nemo Outdoor\DecoderTrace2.dll"
if (!(Test-Path $asmPath)) {
    Write-Error "DecoderTrace2.dll not found: $asmPath"
    exit 1
}

$asm = [Reflection.Assembly]::LoadFrom($asmPath)
$decoderClass = $asm.GetType("Keysight.NWDI.DI.BinaryDecoder.Nemo.Outdoor.DecoderTrace2")
if ($null -eq $decoderClass) {
    Write-Error "DecoderTrace2 class not found."
    exit 1
}

$obj = [Activator]::CreateInstance($decoderClass, $true)
$bf = [Reflection.BindingFlags] "Public,NonPublic,Instance"

$setEventString = $obj.GetType().GetMethod("DecoderTraceLib.IDecoder.SetEventString", $bf)
$getDecodedString = $obj.GetType().GetMethod("DecoderTraceLib.IDecoder.GetDecodedString", $bf)

if ($null -eq $setEventString -or $null -eq $getDecodedString) {
    Write-Error "Required decoder methods not found."
    exit 1
}

$bytes = [System.IO.File]::ReadAllBytes($nmfsPath)
$ascii = [System.Text.Encoding]::ASCII.GetString($bytes)
$matches = [Regex]::Matches($ascii, "#[A-Z]{2},,,[ -~]{0,200}")

Write-Output ("HEADER_EVENT_COUNT " + $matches.Count)
$take = [Math]::Min(25, $matches.Count)
for ($i = 0; $i -lt $take; $i++) {
    $line = $matches[$i].Value
    $clean = $line -replace "[`r`n]+", ""
    $eventString = $clean.TrimStart("#")
    try {
        $null = $setEventString.Invoke($obj, @($eventString))
        $decodedRef = ""
        $args = @([ref]$decodedRef)
        $null = $getDecodedString.Invoke($obj, $args)
        $decoded = [string]$args[0].Value
        Write-Output ("EVENT " + $clean)
        Write-Output ("DECODED " + $decoded)
    } catch {
        Write-Output ("EVENT " + $clean)
        Write-Output ("DECODE_ERROR " + $_.Exception.Message)
    }
}

