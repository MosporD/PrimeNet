$ErrorActionPreference = "Stop"

$asmPath = "C:\Program Files (x86)\Anite\Nemo Outdoor\DecoderTrace.dll"
if (!(Test-Path $asmPath)) {
    Write-Error "DecoderTrace.dll not found: $asmPath"
    exit 1
}

$asm = [Reflection.Assembly]::LoadFrom($asmPath)
$types = $asm.GetTypes() | Where-Object {
    $_.FullName -match "Decoder|Trace|Protocol|Nemo|Binary"
}

foreach ($t in $types) {
    Write-Output ("TYPE " + $t.FullName + " | IsInterface=" + $t.IsInterface + " | IsClass=" + $t.IsClass + " | GUID=" + $t.GUID)
    $ctors = $t.GetConstructors([Reflection.BindingFlags] "Public,NonPublic,Instance")
    foreach ($c in $ctors) {
        Write-Output ("  CTOR " + $c.ToString())
    }
    $methods = $t.GetMethods([Reflection.BindingFlags] "Public,NonPublic,Instance,DeclaredOnly")
    foreach ($m in $methods) {
        $params = ($m.GetParameters() | ForEach-Object {
            $_.ParameterType.Name + " " + $_.Name
        }) -join ", "
        Write-Output ("  " + $m.ReturnType.Name + " " + $m.Name + "(" + $params + ")")
    }
}

