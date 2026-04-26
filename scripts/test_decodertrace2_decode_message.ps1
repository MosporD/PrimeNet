$ErrorActionPreference = "Stop"

$asmPath = "C:\Program Files (x86)\Anite\Nemo Outdoor\DecoderTrace2.dll"
$nmfsPath = "C:\Users\malek.mohammad\OneDrive - Zain Jordan\Desktop\Drive Tests\DT Folder\04 pre\04 pre.1.nmfs"

if (!(Test-Path $asmPath) -or !(Test-Path $nmfsPath)) {
    Write-Error "Required file missing."
    exit 1
}

$asm = [Reflection.Assembly]::LoadFrom($asmPath)
$t = $asm.GetType("Keysight.NWDI.DI.BinaryDecoder.Nemo.Outdoor.DecoderTrace2")
$obj = [Activator]::CreateInstance($t, $true)
$bf = [Reflection.BindingFlags] "Public,NonPublic,Instance"

$mSetMessageData = $obj.GetType().GetMethod("DecoderTraceLib.IDecoder.SetMessageData", $bf)
$mDecodeMessage = $obj.GetType().GetMethod("DecodeMessage", $bf)

if ($null -eq $mSetMessageData -or $null -eq $mDecodeMessage) {
    Write-Error "Methods missing"
    exit 1
}

$bytes = [System.IO.File]::ReadAllBytes($nmfsPath)
$offsets = @(0, 512, 2048, 8192, 16384, 24576)
$lengths = @(32, 64, 128, 256, 512)

foreach ($off in $offsets) {
    foreach ($len in $lengths) {
        if ($off + $len -gt $bytes.Length) { continue }
        $arr = New-Object byte[] $len
        [Array]::Copy($bytes, $off, $arr, 0, $len)
        try {
            $null = $mSetMessageData.Invoke($obj, @($arr, $len))
            $msg = $null
            $args = @([ref]$msg)
            $null = $mDecodeMessage.Invoke($obj, $args)
            $out = $args[0].Value
            Write-Output ("off=$off len=$len decoded_tuple=" + ($out -ne $null))
            if ($out -ne $null) {
                Write-Output ("  tuple_type=" + $out.GetType().FullName)
                Write-Output ("  tuple_value=" + $out.ToString())
            }
        } catch {
            Write-Output ("off=$off len=$len err=" + $_.Exception.Message)
        }
    }
}

