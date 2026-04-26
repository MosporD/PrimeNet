$ErrorActionPreference = "Stop"

$asmPath = "C:\Program Files (x86)\Anite\Nemo Outdoor\DecoderTrace2.dll"
if (!(Test-Path $asmPath)) {
    Write-Error "DecoderTrace2.dll not found: $asmPath"
    exit 1
}

$asm = [Reflection.Assembly]::LoadFrom($asmPath)
$t = $asm.GetType("DecoderTraceLib.DecoderProtocol")
if ($null -eq $t) {
    Write-Error "Type DecoderTraceLib.DecoderProtocol not found."
    exit 1
}

Write-Output ("TYPE " + $t.FullName + " | GUID " + $t.GUID)
$ctors = $t.GetConstructors([Reflection.BindingFlags] "Public,NonPublic,Instance")
foreach ($c in $ctors) {
    Write-Output ("CTOR " + $c.ToString())
}

try {
    $obj = [Activator]::CreateInstance($t, $true)
    Write-Output ("OBJECT " + $obj.GetType().FullName)
    $methods = $obj.GetType().GetMethods([Reflection.BindingFlags] "Public,NonPublic,Instance,DeclaredOnly")
    foreach ($m in $methods) {
        $params = ($m.GetParameters() | ForEach-Object {
            $_.ParameterType.Name + " " + $_.Name
        }) -join ", "
        Write-Output ("  " + $m.ReturnType.Name + " " + $m.Name + "(" + $params + ")")
    }
} catch {
    Write-Output ("CREATE ERROR " + $_.Exception.Message)
}

