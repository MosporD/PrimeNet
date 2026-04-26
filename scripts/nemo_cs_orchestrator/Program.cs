using System.Reflection;
using System.Text;
using System.Text.Json;
using System.Text.RegularExpressions;

namespace NemoCsOrchestrator;

internal static class Program
{
    private static readonly int[] PropertyIds = { -1, 0, 1, 2, 3, 4, 5, 7, 8, 9, 10, 20, 30, 40, 50, 100, 200 };
    private static readonly object[] PropertyValues = { "", 0, 1, 2, 64, 128, 256, 512, 768, true, false, "LTE", "NR", "UMTS", "GSM", "NEMO" };
    private static readonly int[] ChunkSizes = { 24, 32, 48, 64, 96, 128, 192, 256, 384, 512, 768, 1024 };

    private static int Main(string[] args)
    {
        var nmfsPath = args.Length > 0
            ? args[0]
            : @"C:\Users\malek.mohammad\OneDrive - Zain Jordan\Desktop\Drive Tests\DT Folder\04 pre\04 pre.1.nmfs";
        var asmPath = args.Length > 1
            ? args[1]
            : @"C:\Program Files (x86)\Anite\Nemo Outdoor\DecoderTrace2.dll";
        var outPath = args.Length > 2
            ? args[2]
            : @"C:\Users\malek.mohammad\Project\Cursor version\Project\uploads\drive_test_viewer\nemo_cs_orchestrator_report.json";

        if (!File.Exists(nmfsPath) || !File.Exists(asmPath))
        {
            Console.WriteLine("Required input missing.");
            return 1;
        }

        var bytes = File.ReadAllBytes(nmfsPath);
        var eventStrings = ExtractEventStrings(bytes, 40);
        var chunks = BuildChunks(bytes, 420);

        var report = new Report
        {
            GeneratedAtUtc = DateTime.UtcNow.ToString("O"),
            NmfsPath = nmfsPath,
            NmfsSize = bytes.Length,
            EventStringCount = eventStrings.Count,
            ChunkCount = chunks.Count,
        };

        try
        {
            var asm = Assembly.LoadFrom(asmPath);
            var decoderType = asm.GetType("Keysight.NWDI.DI.BinaryDecoder.Nemo.Outdoor.DecoderTrace2");
            if (decoderType is null)
            {
                report.Errors.Add("DecoderTrace2 type not found.");
                SaveReport(outPath, report);
                return 2;
            }

            var decoder = Activator.CreateInstance(decoderType, nonPublic: true);
            if (decoder is null)
            {
                report.Errors.Add("Failed to create DecoderTrace2 instance.");
                SaveReport(outPath, report);
                return 3;
            }

            var bf = BindingFlags.Public | BindingFlags.NonPublic | BindingFlags.Instance;
            var methods = decoderType.GetMethods(bf).ToList();
            report.MethodInventory = methods
                .Select(m => new MethodDesc
                {
                    Name = m.Name,
                    Params = m.GetParameters().Select(p => $"{p.ParameterType.Name} {p.Name}").ToList(),
                })
                .OrderBy(m => m.Name)
                .ToList();

            var mSetEventString = methods.FirstOrDefault(m => m.Name.Contains("SetEventString"));
            var mSetEventData = methods.FirstOrDefault(m => m.Name.Contains("SetEventData"));
            var mSetMessageData = methods.FirstOrDefault(m => m.Name.Contains("SetMessageData"));
            var mSetProperty = methods.FirstOrDefault(m => m.Name.Contains("SetProperty"));
            var mGetDecodedString = methods.FirstOrDefault(m => m.Name.Contains("GetDecodedString"));
            var mGetValueByIndex = methods.FirstOrDefault(m => m.Name.Contains("GetValueByIndex"));
            var mDecodeMessage = methods.FirstOrDefault(m => m.Name == "DecodeMessage");

            if (mSetEventString is null || mSetMessageData is null || mGetDecodedString is null)
            {
                report.Errors.Add("Core methods not found on DecoderTrace2.");
                SaveReport(outPath, report);
                return 4;
            }

            // Pass 1: textual events
            foreach (var ev in eventStrings)
            {
                TryInvoke(() =>
                {
                    var evArgs = new object?[] { ev };
                    mSetEventString.Invoke(decoder, evArgs);
                    var decoded = TryGetDecoded(mGetDecodedString, decoder);
                    if (!string.IsNullOrWhiteSpace(decoded))
                    {
                        report.Hits.Add(new Hit
                        {
                            Mode = "SetEventString",
                            Input = ev,
                            Decoded = decoded,
                        });
                    }
                }, report, $"SetEventString({ev})", swallow: true);
                if (report.Hits.Count >= 30) break;
            }

            // Pass 2: property + message data + decode
            foreach (var propId in PropertyIds)
            {
                foreach (var propValue in PropertyValues)
                {
                    if (mSetProperty is not null)
                    {
                        TryInvoke(() =>
                        {
                            var pArgs = new object?[] { propId, propValue };
                            mSetProperty.Invoke(decoder, pArgs);
                        }, report, $"SetProperty({propId},{propValue})", swallow: true);
                    }

                    foreach (var ch in chunks)
                    {
                        var arr = new byte[ch.Length];
                        Buffer.BlockCopy(bytes, ch.Offset, arr, 0, ch.Length);
                        var first = arr[0];

                        TryInvoke(() =>
                        {
                            var smArgs = new object?[] { first, ch.Length };
                            mSetMessageData.Invoke(decoder, smArgs);
                        }, report, $"SetMessageData(off={ch.Offset},len={ch.Length})", swallow: true);

                        if (mSetEventData is not null)
                        {
                            TryInvoke(() =>
                            {
                                var seArgs = new object?[] { first, ch.Length };
                                mSetEventData.Invoke(decoder, seArgs);
                            }, report, $"SetEventData(off={ch.Offset},len={ch.Length})", swallow: true);
                        }

                        object? decodedTuple = null;
                        if (mDecodeMessage is not null)
                        {
                            TryInvoke(() =>
                            {
                                var initialTuple = Tuple.Create(string.Empty, string.Empty);
                                var dmArgs = new object?[] { initialTuple };
                                mDecodeMessage.Invoke(decoder, dmArgs);
                                decodedTuple = dmArgs[0];
                            }, report, $"DecodeMessage(off={ch.Offset},len={ch.Length})", swallow: true);
                        }

                        var decoded = TryGetDecoded(mGetDecodedString, decoder, swallow: true, report: report);
                        var firstVal = TryGetFirstValue(mGetValueByIndex, decoder, report);
                        if (!string.IsNullOrWhiteSpace(decoded) || decodedTuple is not null || firstVal is not null)
                        {
                            report.Hits.Add(new Hit
                            {
                                Mode = "SetMessageData",
                                PropId = propId,
                                PropValue = propValue?.ToString(),
                                Offset = ch.Offset,
                                Length = ch.Length,
                                Decoded = decoded,
                                DecodedTuple = decodedTuple?.ToString(),
                                FirstValue = firstVal,
                            });
                            if (report.Hits.Count >= 30) break;
                        }
                    }
                    if (report.Hits.Count >= 30) break;
                }
                if (report.Hits.Count >= 30) break;
            }

            // Pass 3: targeted bootstrap using DecoderDefines constants discovered via reflection:
            // PROP_DIRECTION=2, PROP_MESSAGE_ID=5, PROP_DECODER_PROTOCOL=12, PROP_MESSAGE_DATA=13.
            var directions = new[] { 64, 128 };
            var protocols = new[] { 1, 2 };
            foreach (var protocol in protocols)
            {
                foreach (var direction in directions)
                {
                    foreach (var ch in chunks)
                    {
                        var arr = new byte[ch.Length];
                        Buffer.BlockCopy(bytes, ch.Offset, arr, 0, ch.Length);
                        var first = arr[0];
                        TryInvoke(() =>
                        {
                            if (mSetProperty is not null)
                            {
                                mSetProperty.Invoke(decoder, new object?[] { 12, protocol }); // PROP_DECODER_PROTOCOL
                                mSetProperty.Invoke(decoder, new object?[] { 2, direction }); // PROP_DIRECTION
                                mSetProperty.Invoke(decoder, new object?[] { 5, (int)first }); // PROP_MESSAGE_ID
                                mSetProperty.Invoke(decoder, new object?[] { 13, arr }); // PROP_MESSAGE_DATA
                            }
                        }, report, $"TargetedSetProperty(proto={protocol},dir={direction},off={ch.Offset})", swallow: true);

                        TryInvoke(() =>
                        {
                            var smArgs = new object?[] { first, ch.Length };
                            mSetMessageData.Invoke(decoder, smArgs);
                        }, report, $"TargetedSetMessageData(proto={protocol},dir={direction},off={ch.Offset})", swallow: true);

                        object? decodedTuple = null;
                        if (mDecodeMessage is not null)
                        {
                            TryInvoke(() =>
                            {
                                var initialTuple = Tuple.Create(string.Empty, string.Empty);
                                var dmArgs = new object?[] { initialTuple };
                                mDecodeMessage.Invoke(decoder, dmArgs);
                                decodedTuple = dmArgs[0];
                            }, report, $"TargetedDecodeMessage(proto={protocol},dir={direction},off={ch.Offset})", swallow: true);
                        }

                        var decoded = TryGetDecoded(mGetDecodedString, decoder, swallow: true, report: report);
                        var firstVal = TryGetFirstValue(mGetValueByIndex, decoder, report);
                        if (!string.IsNullOrWhiteSpace(decoded) || decodedTuple is not null || firstVal is not null)
                        {
                            report.Hits.Add(new Hit
                            {
                                Mode = "TargetedBootstrap",
                                PropId = 12,
                                PropValue = $"proto={protocol},dir={direction}",
                                Offset = ch.Offset,
                                Length = ch.Length,
                                Decoded = decoded,
                                DecodedTuple = decodedTuple?.ToString(),
                                FirstValue = firstVal,
                            });
                            if (report.Hits.Count >= 30) break;
                        }
                    }
                    if (report.Hits.Count >= 30) break;
                }
                if (report.Hits.Count >= 30) break;
            }
        }
        catch (Exception ex)
        {
            report.Errors.Add(ex.ToString());
        }

        SaveReport(outPath, report);
        Console.WriteLine($"hits={report.Hits.Count}");
        Console.WriteLine($"errors={report.Errors.Count}");
        Console.WriteLine($"written: {outPath}");
        return 0;
    }

    private static string? TryGetDecoded(MethodInfo method, object target, bool swallow = false, Report? report = null)
    {
        try
        {
            var args = new object?[] { null };
            method.Invoke(target, args);
            return args[0]?.ToString();
        }
        catch (Exception ex)
        {
            if (!swallow) throw;
            if (report is not null && report.Errors.Count < 300) report.Errors.Add($"GetDecodedString: {ex.Message}");
            return null;
        }
    }

    private static string? TryGetFirstValue(MethodInfo? method, object target, Report report)
    {
        if (method is null) return null;
        try
        {
            var args = new object?[] { 0, 0, null };
            method.Invoke(target, args);
            var id = args[1]?.ToString();
            var value = args[2]?.ToString();
            if (!string.IsNullOrWhiteSpace(id) || !string.IsNullOrWhiteSpace(value))
                return $"id={id}, value={value}";
        }
        catch (Exception ex)
        {
            if (report.Errors.Count < 300) report.Errors.Add($"GetValueByIndex: {ex.Message}");
        }
        return null;
    }

    private static void TryInvoke(Action action, Report report, string label, bool swallow = false)
    {
        try
        {
            action();
        }
        catch (Exception ex)
        {
            if (!swallow) throw;
            if (report.Errors.Count < 300) report.Errors.Add($"{label}: {ex.Message}");
        }
    }

    private static List<string> ExtractEventStrings(byte[] bytes, int max)
    {
        var txt = Encoding.ASCII.GetString(bytes);
        var matches = Regex.Matches(txt, "#[A-Z]{2},,,[ -~]{0,220}");
        var list = new List<string>();
        foreach (Match m in matches)
        {
            var s = m.Value.Replace("\r", "").Replace("\n", "").TrimStart('#');
            if (string.IsNullOrWhiteSpace(s) || list.Contains(s)) continue;
            list.Add(s);
            if (list.Count >= max) break;
        }
        return list;
    }

    private static List<Chunk> BuildChunks(byte[] bytes, int max)
    {
        var list = new List<Chunk>();
        foreach (var len in ChunkSizes)
        {
            var step = Math.Max(256, len * 6);
            for (var off = 0; off + len < Math.Min(bytes.Length, 80000); off += step)
            {
                list.Add(new Chunk { Offset = off, Length = len });
                if (list.Count >= max) return list;
            }
        }
        return list;
    }

    private static void SaveReport(string path, Report report)
    {
        Directory.CreateDirectory(Path.GetDirectoryName(path)!);
        File.WriteAllText(path, JsonSerializer.Serialize(report, new JsonSerializerOptions { WriteIndented = true }));
    }

    private sealed class Chunk
    {
        public int Offset { get; set; }
        public int Length { get; set; }
    }

    private sealed class MethodDesc
    {
        public string Name { get; set; } = "";
        public List<string> Params { get; set; } = new();
    }

    private sealed class Hit
    {
        public string Mode { get; set; } = "";
        public string? Input { get; set; }
        public int? PropId { get; set; }
        public string? PropValue { get; set; }
        public int? Offset { get; set; }
        public int? Length { get; set; }
        public string? Decoded { get; set; }
        public string? DecodedTuple { get; set; }
        public string? FirstValue { get; set; }
    }

    private sealed class Report
    {
        public string GeneratedAtUtc { get; set; } = "";
        public string NmfsPath { get; set; } = "";
        public int NmfsSize { get; set; }
        public int EventStringCount { get; set; }
        public int ChunkCount { get; set; }
        public List<MethodDesc> MethodInventory { get; set; } = new();
        public List<Hit> Hits { get; set; } = new();
        public List<string> Errors { get; set; } = new();
    }
}

