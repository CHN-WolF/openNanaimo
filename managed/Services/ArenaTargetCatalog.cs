using System.Text.Json;

namespace OpenNanaimo.Adapter.Services;

internal readonly record struct ArenaTargetDefinition(byte Type, int Hp, int Contact, int Defense,
    string Resource, int Ordinal)
{
    public bool CanTakeDamage => Hp > 0 && Type != 4;
}

internal static class ArenaTargetCatalog
{
    private static readonly Lazy<Dictionary<(ushort Stage, ushort Slot), ArenaTargetDefinition[]>> Data = new(Load);

    internal static bool TryGet(ushort stage, ushort slot, uint selector, out ArenaTargetDefinition target)
    {
        target = default;
        if (!Data.Value.TryGetValue((stage, slot), out var rows) || selector >= rows.Length) return false;
        target = rows[selector];
        return true;
    }

    private static Dictionary<(ushort, ushort), ArenaTargetDefinition[]> Load()
    {
        using var stream = typeof(ArenaTargetCatalog).Assembly.GetManifestResourceStream(
            "OpenNanaimo.Adapter.ArenaTargets.json") ?? throw new InvalidDataException("Arena target catalog missing.");
        using var document = JsonDocument.Parse(stream);
        var root = document.RootElement;
        if (root.GetProperty("schema").GetInt32() != 1) throw new InvalidDataException("Arena target catalog schema.");
        var names = root.GetProperty("resources").EnumerateArray().Select(n => n.GetString()!).ToArray();
        var result = new Dictionary<(ushort, ushort), ArenaTargetDefinition[]>();
        foreach (var profile in root.GetProperty("profiles").EnumerateArray())
        {
            var rows = profile.GetProperty("rows").EnumerateArray().Select(row => new ArenaTargetDefinition(
                row[0].GetByte(), row[1].GetInt32(), row[2].GetInt32(), row[3].GetInt32(),
                names[row[4].GetInt32()], row[5].GetInt32())).ToArray();
            result.Add((profile.GetProperty("stage").GetUInt16(), profile.GetProperty("slot").GetUInt16()), rows);
        }
        return result;
    }
}
