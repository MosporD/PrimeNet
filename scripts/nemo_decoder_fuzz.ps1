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
    Write-Error "DecoderTrace2 class not found"
    exit 1
}

$progIds = @(
    "Layer2.L2Decoder.1",
    "Layer3.L3Decoder.1",
    "LayerRM.LRMDecoder.1",
    "LayerRRC.RRCDecoder.1",
    "LayerRRLP.RRLPDecoder.1",
    "LayerRTP.RTPDecoder.1",
    "LayerSNP.SNPDecoder.1"
)

$bytes = [System.IO.File]::ReadAllBytes($nmfsPath)
$ascii = [System.Text.Encoding]::ASCII.GetString($bytes)
$eventMatches = [Regex]::Matches($ascii, "#[A-Z]{2},,,[ -~]{0,220}")
$eventStrings = @()
foreach ($m in $eventMatches) {
    $s = ($m.Value -replace "[`r`n]+", "").TrimStart("#")
    if ($s -and -not $eventStrings.Contains($s)) {
        $eventStrings += $s
    }
    if ($eventStrings.Count -ge 25) { break }
}

# Sample binary slices for SetMessageData/SetEventData
$sliceDefs = @()
$lens = @(24, 32, 48, 64, 96, 128, 192, 256, 384, 512)
foreach ($len in $lens) {
    $step = [Math]::Max(256, $len * 8)
    for ($off = 0; $off -lt [Math]::Min($bytes.Length - $len, 48000); $off += $step) {
        $sliceDefs += @{ offset = $off; length = $len }
        if ($sliceDefs.Count -ge 220) { break }
    }
    if ($sliceDefs.Count -ge 220) { break }
}

$propertyIds = @(-1, 0, 1, 2, 3, 4, 5, 7, 8, 9, 10, 20, 30, 40, 50, 100, 200)
$propertyValues = @("", 0, 1, $true, $false, "LTE", "NR", "UMTS", "GSM")

$report = [ordered]@{
    generated_at_utc = [DateTime]::UtcNow.ToString("o")
    nmfs_path = $nmfsPath
    nmfs_size = $bytes.Length
    event_string_count = $eventStrings.Count
    binary_slice_count = $sliceDefs.Count
    results = @()
}

foreach ($progid in $progIds) {
    $entry = [ordered]@{
        progid = $progid
        create_success = $false
        non_error_decodes = @()
        decode_errors = @()
    }
    try {
        $comType = [type]::GetTypeFromProgID($progid)
        if ($null -eq $comType) {
            throw "ProgID not registered"
        }
        $comObj = [Activator]::CreateInstance($comType)
        $entry.create_success = $true

        $mSetEventString = $comObj.GetType().GetMethod("SetEventString")
        $mSetEventData = $comObj.GetType().GetMethod("SetEventData")
        $mSetMessageData = $comObj.GetType().GetMethod("SetMessageData")
        $mSetProperty = $comObj.GetType().GetMethod("SetProperty")
        $mGetDecodedString = $comObj.GetType().GetMethod("GetDecodedString")
        $mGetValueByIndex = $comObj.GetType().GetMethod("GetValueByIndex")

        # Pass 1: textual event strings
        foreach ($ev in $eventStrings) {
            try {
                if ($mSetEventString) { $null = $mSetEventString.Invoke($comObj, @($ev)) }
                $decoded = ""
                if ($mGetDecodedString) {
                    $args = @([ref]$decoded)
                    $null = $mGetDecodedString.Invoke($comObj, $args)
                    $decoded = [string]$args[0].Value
                }
                if ($decoded -and $decoded.Trim().Length -gt 0) {
                    $entry.non_error_decodes += [ordered]@{
                        mode = "SetEventString"
                        input = $ev
                        decoded = $decoded
                    }
                    if ($entry.non_error_decodes.Count -ge 20) { break }
                }
            } catch {
                $entry.decode_errors += "SetEventString($ev): $($_.Exception.Message)"
                if ($entry.decode_errors.Count -gt 80) { break }
            }
        }

        # Pass 2: property priming + binary slices
        foreach ($propId in $propertyIds) {
            foreach ($pv in $propertyValues) {
                try {
                    if ($mSetProperty) {
                        $null = $mSetProperty.Invoke($comObj, @($propId, $pv))
                    }
                } catch {
                    # Ignore property setup failures.
                }

                foreach ($sl in $sliceDefs) {
                    $off = [int]$sl.offset
                    $len = [int]$sl.length
                    $arr = New-Object byte[] $len
                    [Array]::Copy($bytes, $off, $arr, 0, $len)
                    try {
                        if ($mSetMessageData) {
                            $null = $mSetMessageData.Invoke($comObj, @($arr, $len))
                        } elseif ($mSetEventData) {
                            $null = $mSetEventData.Invoke($comObj, @($arr, $len))
                        } else {
                            continue
                        }

                        $decoded = ""
                        if ($mGetDecodedString) {
                            $args = @([ref]$decoded)
                            $null = $mGetDecodedString.Invoke($comObj, $args)
                            $decoded = [string]$args[0].Value
                        }

                        $firstVal = $null
                        if ($mGetValueByIndex) {
                            try {
                                $idRef = 0
                                $valRef = $null
                                $gArgs = @(0, [ref]$idRef, [ref]$valRef)
                                $null = $mGetValueByIndex.Invoke($comObj, $gArgs)
                                $firstVal = [ordered]@{ id = $gArgs[1].Value; value = $gArgs[2].Value }
                            } catch {}
                        }

                        if (($decoded -and $decoded.Trim().Length -gt 0) -or $firstVal) {
                            $entry.non_error_decodes += [ordered]@{
                                mode = "SetMessageData"
                                prop_id = $propId
                                prop_value = "$pv"
                                offset = $off
                                length = $len
                                decoded = $decoded
                                first_value = $firstVal
                            }
                            if ($entry.non_error_decodes.Count -ge 20) { break }
                        }
                    } catch {
                        if ($entry.decode_errors.Count -lt 120) {
                            $entry.decode_errors += "SetMessageData(propId=$propId,off=$off,len=$len): $($_.Exception.Message)"
                        }
                    }
                }
                if ($entry.non_error_decodes.Count -ge 20) { break }
            }
            if ($entry.non_error_decodes.Count -ge 20) { break }
        }
    } catch {
        $entry.decode_errors += "Create/Init failed: $($_.Exception.Message)"
    }

    $report.results += $entry
    Write-Output ("PROGID " + $progid + " | create=" + $entry.create_success + " | hits=" + $entry.non_error_decodes.Count)
}

$outPath = "C:\Users\malek.mohammad\Project\Cursor version\Project\uploads\drive_test_viewer\nemo_decoder_fuzz_report.json"
$json = $report | ConvertTo-Json -Depth 8
[System.IO.File]::WriteAllText($outPath, $json)
Write-Output ("written: " + $outPath)

