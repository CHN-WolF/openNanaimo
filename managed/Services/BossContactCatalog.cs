using System.Text.Json;

namespace OpenNanaimo.Adapter.Services;

internal static class BossContactCatalog
{
    private readonly record struct Key(byte Hd, byte Episode, byte Dungeon, byte Stage,
        byte Slot, byte Mode, byte Child, ushort Ordinal);
    private readonly record struct Entry(ushort BossUid, ushort Attack);
    private static readonly Lazy<IReadOnlyDictionary<Key, Entry>> Data = new(Load);
    internal static int Count => Data.Value.Count;

    internal static ushort Resolve(byte hd, byte episode, byte dungeon, byte stage,
        ushort slot, uint descriptor)
        => TryResolve(hd, episode, dungeon, stage, slot, descriptor, out _, out var attack) ? attack : (ushort)0;

    internal static bool TryResolve(byte hd, byte episode, byte dungeon, byte stage,
        ushort slot, uint descriptor, out ushort bossUid, out ushort attack)
    {
        bossUid = attack = 0;
        if (slot > 8) return false;
        if (hd == 0 && episode == 100 && dungeon <= 7)
        {
            episode = (byte)(16 + dungeon);
            dungeon = dungeon == 6 && stage == 1 ? (byte)1 : (byte)0;
        }
        if (!Data.Value.TryGetValue(new Key(hd, episode, dungeon, stage, (byte)slot,
            (byte)descriptor, (byte)(descriptor >> 8), (ushort)(descriptor >> 16)), out var value)) return false;
        bossUid = value.BossUid; attack = value.Attack;
        return true;
    }

    private static IReadOnlyDictionary<Key, Entry> Load()
    {
        using var stream = typeof(BossContactCatalog).Assembly.GetManifestResourceStream(
            "OpenNanaimo.Adapter.BossContacts.json")
            ?? throw new InvalidDataException("Boss contact catalog is required.");
        using var document = JsonDocument.Parse(stream);
        var root = document.RootElement;
        if (root.GetProperty("schema").GetInt32() != 1)
            throw new InvalidDataException("Boss contact schema differs.");
        var resources = root.GetProperty("resources").EnumerateArray().ToDictionary(
            r => r.GetProperty("resource").GetString()!,
            r => r.GetProperty("rows").EnumerateArray().Select(v => v[2].GetUInt16()).ToArray());
        var result = new Dictionary<Key, Entry>();
        foreach (var scope in root.GetProperty("scopes").EnumerateArray())
        {
            var k = scope.GetProperty("key").EnumerateArray().Select(v => v.GetByte()).ToArray();
            foreach (var part in scope.GetProperty("parts").EnumerateArray())
            {
                var attacks = resources[part[2].GetString()!];
                for (var ordinal = 0; ordinal < attacks.Length; ordinal++)
                    result.Add(new Key(k[0], k[1], k[2], k[3], k[4], part[0].GetByte(),
                        part[1].GetByte(), checked((ushort)ordinal)), new Entry(scope.GetProperty("boss_uid").GetUInt16(), attacks[ordinal]));
            }
        }
        return result;
    }
}
