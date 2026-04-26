$ErrorActionPreference = "Stop"

$path = "C:\Program Files (x86)\Anite\Nemo Outdoor\DecoderTrace2.dll"
if (!(Test-Path $path)) {
    Write-Error "DecoderTrace2.dll not found: $path"
    exit 1
}

$asm = [Reflection.Assembly]::LoadFrom($path)
$types = $asm.GetTypes() | Where-Object {
    $_.FullName -match "Decoder|Trace|Nemo|Binary"
}

foreach ($t in $types) {
    Write-Output ("TYPE " + $t.FullName + " | GUID " + $t.GUID)
    $methods = $t.GetMethods([Reflection.BindingFlags] "Public,Instance,Static,DeclaredOnly")
    foreach ($m in $methods) {
        $params = ($m.GetParameters() | ForEach-Object {
            $_.ParameterType.Name + " " + $_.Name
        }) -join ", "
        Write-Output ("  " + $m.ReturnType.Name + " " + $m.Name + "(" + $params + ")")
    }
}

Write-Output "=== DecoderDefines Fields ==="
$defType = $asm.GetType("Keysight.NWDI.DI.BinaryDecoder.Nemo.Outdoor.DecoderDefines")
if ($null -ne $defType) {
    $fFlags = [Reflection.BindingFlags] "Public,NonPublic,Static,Instance"
    foreach ($f in $defType.GetFields($fFlags)) {
        $val = "(instance)"
        try {
            if ($f.IsStatic) {
                $val = $f.GetValue($null)
            }
        } catch {
            $val = "(error)"
        }
        Write-Output ("FIELD " + $f.FieldType.Name + " " + $f.Name + " = " + $val)
    }
}

Write-Output "=== Direct Class Instantiation Attempt ==="
$decoderClass = $asm.GetType("Keysight.NWDI.DI.BinaryDecoder.Nemo.Outdoor.DecoderTrace2")
if ($null -eq $decoderClass) {
    Write-Output "DecoderTrace2 class not found."
    exit 0
}
Write-Output ("CLASS " + $decoderClass.FullName)
$ctors = $decoderClass.GetConstructors([Reflection.BindingFlags] "Public,NonPublic,Instance")
foreach ($c in $ctors) {
    Write-Output ("  CTOR " + $c.ToString())
}
try {
    $obj = [Activator]::CreateInstance($decoderClass, $true)
    Write-Output ("DIRECT OBJECT " + $obj.GetType().FullName)
    $im = $obj.GetType().GetMethods([Reflection.BindingFlags] "Public,NonPublic,Instance,DeclaredOnly")
    foreach ($m in $im) {
        $params = ($m.GetParameters() | ForEach-Object {
            $_.ParameterType.Name + " " + $_.Name
        }) -join ", "
        Write-Output ("  " + $m.ReturnType.Name + " " + $m.Name + "(" + $params + ")")
    }
} catch {
    Write-Output ("DIRECT CREATE ERROR " + $_.Exception.Message)
}

Write-Output "=== DecodeMessage Signature ==="
$decodeMsg = $decoderClass.GetMethod("DecodeMessage", [Reflection.BindingFlags] "Public,NonPublic,Instance")
if ($null -eq $decodeMsg) {
    Write-Output "DecodeMessage not found."
} else {
    Write-Output ("RETURN " + $decodeMsg.ReturnType.FullName)
    foreach ($p in $decodeMsg.GetParameters()) {
        Write-Output ("PARAM " + $p.Name + " : " + $p.ParameterType.FullName + " | IsByRef=" + $p.ParameterType.IsByRef)
    }
}

