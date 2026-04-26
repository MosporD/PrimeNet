$ErrorActionPreference = "Stop"

$clsid = "{1FA1AEE5-4509-4B0C-9718-9E34C4240750}" # DecoderProtocol Class
$type = [type]::GetTypeFromCLSID($clsid)
if ($null -eq $type) {
    Write-Error "Unable to resolve COM type for CLSID $clsid"
    exit 1
}

$obj = [Activator]::CreateInstance($type)
Write-Output ("OBJECT TYPE " + $obj.GetType().FullName)

$methods = $obj.GetType().GetMethods([Reflection.BindingFlags] "Public,Instance")
foreach ($m in $methods) {
    $params = ($m.GetParameters() | ForEach-Object {
        $_.ParameterType.Name + " " + $_.Name
    }) -join ", "
    Write-Output ("  " + $m.ReturnType.Name + " " + $m.Name + "(" + $params + ")")
}

$asmPath = "C:\Program Files (x86)\Anite\Nemo Outdoor\DecoderTrace2.dll"
if (Test-Path $asmPath) {
    $asm = [Reflection.Assembly]::LoadFrom($asmPath)
    $idecoderType = $asm.GetType("DecoderTraceLib.IDecoder")
    if ($null -ne $idecoderType) {
        try {
            $unk = [Runtime.InteropServices.Marshal]::GetIUnknownForObject($obj)
            $typed = [Runtime.InteropServices.Marshal]::GetTypedObjectForIUnknown($unk, $idecoderType)
            Write-Output ("TYPED WRAPPER " + $typed.GetType().FullName)
            $tm = $typed.GetType().GetMethods([Reflection.BindingFlags] "Public,Instance,DeclaredOnly")
            foreach ($m in $tm) {
                $params = ($m.GetParameters() | ForEach-Object {
                    $_.ParameterType.Name + " " + $_.Name
                }) -join ", "
                Write-Output ("  " + $m.ReturnType.Name + " " + $m.Name + "(" + $params + ")")
            }
            [Runtime.InteropServices.Marshal]::Release($unk) | Out-Null
        } catch {
            Write-Output ("WRAP ERROR " + $_.Exception.Message)
        }
    } else {
        Write-Output "IDecoder interface type not found in DecoderTrace2.dll"
    }
}

