# Nemo Decoder Reverse-Engineering (32-bit COM)

The Nemo layer decoders (`LayerRRC.dll`, `LayerRM.dll`, `Layer3.dll`, etc.) are COM in-proc servers registered in a 32-bit stack.

If you call them from 64-bit Python, you typically get:
- `0x80040154` (`Class not registered`) for decoder CLSIDs

## 1) Install/locate 32-bit Python

Any modern 32-bit Python is fine (3.9+ recommended).

Example path:
- `C:\Python311-32\python.exe`

## 2) Run the provided launcher

From project root:

```powershell
.\scripts\run_nemo_com_probe_32.ps1 -Python32 "C:\Python311-32\python.exe"
```

or let it auto-detect common 32-bit Python paths:

```powershell
.\scripts\run_nemo_com_probe_32.ps1
```

## 3) Output report

The probe writes:

- `uploads/drive_test_viewer/nemo_com_probe_report.json`

This report shows which decoder COM classes instantiate successfully under 32-bit runtime.

## 4) Next stage after successful instantiation

After we confirm 32-bit COM activation works for decoder classes:

1. enumerate interface/type-info (if exposed),
2. discover callable methods,
3. attempt safe NMFS-open / decode pipeline calls,
4. map output records to KPI series.

## Safety

- This process is read-only to Nemo installation.
- No Nemo binaries/configs are modified.

