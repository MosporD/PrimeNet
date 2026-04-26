using System.Runtime.InteropServices;
using System.Text;
using System.Text.Json;

namespace NemoCsHarness;

[ComImport]
[Guid("09E19780-4288-11D4-8135-00C04F03E74B")]
[InterfaceType(ComInterfaceType.InterfaceIsIUnknown)]
internal interface IDecoder
{
    void SetEventString([MarshalAs(UnmanagedType.BStr)] string eventString);
    void SetEventData(ref byte pData, int length);
    void SetMessageData(ref byte pData, int length);
    void GetMessageData(ref byte pBuffer, int bufferSize, out int pLength);
    void SetProperty(int propId, [MarshalAs(UnmanagedType.Struct)] object value);
    void GetProperty(int propId, [MarshalAs(UnmanagedType.Struct)] out object pValue);
    void GetDecodedString([MarshalAs(UnmanagedType.BStr)] out string pString);
    void GetValueByIndex(int index, out int pId, [MarshalAs(UnmanagedType.Struct)] out object pValue);
    void GetValueById(int id, [MarshalAs(UnmanagedType.Struct)] out object pValue);
    void GetElementByIndex(int index, ref byte pBuffer, int bufferSizeInBits, out int pLengthInBits);
    void GetElementById(int id, ref byte pBuffer, int bufferSizeInBits, out int pLengthInBits);
}

internal static class Program
{
    private static readonly string[] ProgIds =
    {
        "Layer2.L2Decoder.1",
        "Layer3.L3Decoder.1",
        "LayerRM.LRMDecoder.1",
        "LayerRRC.RRCDecoder.1",
        "LayerRRLP.RRLPDecoder.1",
        "LayerRTP.RTPDecoder.1",
        "LayerSNP.SNPDecoder.1",
    };

    private static readonly int[] PropertyIds = { -1, 0, 1, 2, 3, 4, 5, 7, 8, 9, 10, 20, 30, 40, 50, 100, 200 };
    private static readonly object[] PropertyValues = { "", 0, 1, true, false, "LTE", "NR", "UMTS", "GSM" };
    private static readonly int[] ChunkSizes = { 24, 32, 48, 64, 96, 128, 192, 256, 384, 512 };

    private static int Main(string[] args)
    {
        var nmfsPath = args.Length > 0
            ? args[0]
            : @"C:\Users\malek.mohammad\OneDrive - Zain Jordan\Desktop\Drive Tests\DT Folder\04 pre\04 pre.1.nmfs";
        var outPath = args.Length > 1
            ? args[1]
            : @"C:\Users\malek.mohammad\Project\Cursor version\Project\uploads\drive_test_viewer\nemo_cs_harness_report.json";

        if (!File.Exists(nmfsPath))
        {
            Console.WriteLine($"NMFS not found: {nmfsPath}");
            return 1;
        }

        var bytes = File.ReadAllBytes(nmfsPath);
        var eventStrings = ExtractEventStrings(bytes, 25);
        var chunks = BuildChunks(bytes, 240);
        var results = new List<object>();

        foreach (var progId in ProgIds)
        {
            var entry = RunDecoder(progId, bytes, eventStrings, chunks);
            results.Add(entry);
            var hits = (entry.Hits as List<object>)?.Count ?? 0;
            Console.WriteLine($"{progId} | create={entry.CreateSuccess} | hits={hits}");
        }

        Directory.CreateDirectory(Path.GetDirectoryName(outPath)!);
        var payload = new
        {
            generated_at_utc = DateTime.UtcNow.ToString("O"),
            nmfs_path = nmfsPath,
            nmfs_size = bytes.Length,
            event_string_count = eventStrings.Count,
            chunk_count = chunks.Count,
            results,
        };
        File.WriteAllText(outPath, JsonSerializer.Serialize(payload, new JsonSerializerOptions { WriteIndented = true }));
        Console.WriteLine($"written: {outPath}");
        return 0;
    }

    private static DecoderResult RunDecoder(string progId, byte[] bytes, List<string> eventStrings, List<(int Offset, int Len)> chunks)
    {
        var result = new DecoderResult { ProgId = progId };
        IDecoder? decoder = null;
        object? comObj = null;
        IntPtr unk = IntPtr.Zero;
        IntPtr iface = IntPtr.Zero;
        try
        {
            var t = Type.GetTypeFromProgID(progId, throwOnError: false);
            if (t is null)
            {
                result.Errors.Add("ProgID not registered");
                return result;
            }

            comObj = Activator.CreateInstance(t);
            result.CreateSuccess = comObj is not null;
            if (comObj is null)
            {
                result.Errors.Add("CreateInstance returned null");
                return result;
            }

            unk = Marshal.GetIUnknownForObject(comObj);
            var iid = new Guid("09E19780-4288-11D4-8135-00C04F03E74B");
            var hr = Marshal.QueryInterface(unk, ref iid, out iface);
            if (hr != 0 || iface == IntPtr.Zero)
            {
                result.Errors.Add($"QueryInterface failed hr=0x{hr:X8}");
                return result;
            }
            decoder = (IDecoder)Marshal.GetTypedObjectForIUnknown(iface, typeof(IDecoder));
            result.InterfaceBound = true;

            foreach (var ev in eventStrings)
            {
                try
                {
                    decoder.SetEventString(ev);
                    decoder.GetDecodedString(out var decoded);
                    if (!string.IsNullOrWhiteSpace(decoded))
                    {
                        result.Hits.Add(new { mode = "SetEventString", input = ev, decoded });
                        if (result.Hits.Count >= 20) break;
                    }
                }
                catch
                {
                    // ignore known "Not implemented" noise
                }
            }

            foreach (var propId in PropertyIds)
            {
                foreach (var propValue in PropertyValues)
                {
                    try { decoder.SetProperty(propId, propValue); } catch { }
                    foreach (var ch in chunks)
                    {
                        try
                        {
                            var arr = new byte[ch.Len];
                            Buffer.BlockCopy(bytes, ch.Offset, arr, 0, ch.Len);
                            decoder.SetMessageData(ref arr[0], ch.Len);
                            decoder.GetDecodedString(out var decoded);

                            int id = 0;
                            object val = "";
                            try { decoder.GetValueByIndex(0, out id, out val); } catch { }

                            if (!string.IsNullOrWhiteSpace(decoded) || (val is not null && val.ToString() != string.Empty))
                            {
                                result.Hits.Add(new
                                {
                                    mode = "SetMessageData",
                                    prop_id = propId,
                                    prop_value = propValue.ToString(),
                                    offset = ch.Offset,
                                    length = ch.Len,
                                    decoded,
                                    first_value = new { id, value = val?.ToString() },
                                });
                                if (result.Hits.Count >= 20) return result;
                            }
                        }
                        catch
                        {
                            // ignore to continue fuzzing
                        }
                    }
                }
            }
        }
        catch (Exception ex)
        {
            result.Errors.Add(ex.Message);
        }
        finally
        {
            if (iface != IntPtr.Zero) Marshal.Release(iface);
            if (unk != IntPtr.Zero) Marshal.Release(unk);
            if (comObj is not null) Marshal.ReleaseComObject(comObj);
        }
        return result;
    }

    private static List<string> ExtractEventStrings(byte[] bytes, int take)
    {
        var txt = Encoding.ASCII.GetString(bytes);
        var rx = new System.Text.RegularExpressions.Regex("#[A-Z]{2},,,[ -~]{0,220}");
        var outList = new List<string>();
        foreach (System.Text.RegularExpressions.Match m in rx.Matches(txt))
        {
            var s = m.Value.Replace("\r", "").Replace("\n", "").TrimStart('#');
            if (string.IsNullOrWhiteSpace(s) || outList.Contains(s)) continue;
            outList.Add(s);
            if (outList.Count >= take) break;
        }
        return outList;
    }

    private static List<(int Offset, int Len)> BuildChunks(byte[] bytes, int maxChunks)
    {
        var list = new List<(int Offset, int Len)>();
        foreach (var len in ChunkSizes)
        {
            var step = Math.Max(256, len * 8);
            for (var off = 0; off + len < Math.Min(bytes.Length, 48000); off += step)
            {
                list.Add((off, len));
                if (list.Count >= maxChunks) return list;
            }
        }
        return list;
    }

    private sealed class DecoderResult
    {
        public string ProgId { get; set; } = "";
        public bool CreateSuccess { get; set; }
        public bool InterfaceBound { get; set; }
        public List<object> Hits { get; } = new();
        public List<string> Errors { get; } = new();
    }
}

