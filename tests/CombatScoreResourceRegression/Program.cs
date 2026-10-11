using System.Buffers.Binary;
using OpenNanaimo.Adapter.Services;

var path = Path.Combine(AppContext.BaseDirectory, "资源", "数据", "dungeon_combat_catalog.bin");
var bytes = File.ReadAllBytes(path);
if (!bytes.AsSpan(0, 4).SequenceEqual("DCC7"u8)) throw new Exception("catalog signature");
int count = 0, at = 4;
var sizes = new[] { 28, 16, 34, 30 };
for (var section = 0; section < sizes.Length; section++)
{
    var records = BinaryPrimitives.ReadInt32LittleEndian(bytes.AsSpan(at)); at += 4;
    for (var i = 0; i < records; i++, at += sizes[section])
    {
        var r = bytes.AsSpan(at, sizes[section]);
        var hd = r[0]; var ep = r[1]; var dg = r[2]; var st = r[3]; var slot = r[4];
        var uid = BinaryPrimitives.ReadUInt16LittleEndian(r[5..]);
        bool ok;
        if (section == 0)
            ok = DungeonCombatCatalog.TryGet(hd, ep, dg, st, slot, uid, out var t)
                && t.Score == BinaryPrimitives.ReadInt32LittleEndian(r[20..]);
        else if (section == 1)
            ok = DungeonCombatCatalog.TryGetBoss(hd, ep, dg, st, slot, uid, out var boss)
                && boss.TotalScore == BinaryPrimitives.ReadInt32LittleEndian(r[11..])
                && boss.TotalScore == boss.Components.Values.Sum(v => v.Score);
        else if (section == 2)
            ok = DungeonCombatCatalog.TryGetBossComponent(hd, ep, dg, st, slot, uid,
                r[7], r[8], BinaryPrimitives.ReadInt32LittleEndian(r[9..]), out _, out var component)
                && component.Score == BinaryPrimitives.ReadInt32LittleEndian(r[26..]);
        else
            ok = DungeonCombatCatalog.TryGetRuntime(hd, ep, dg, st, slot, uid, out var resource, out var runtime)
                && resource == BinaryPrimitives.ReadUInt16LittleEndian(r[7..])
                && runtime.Score == BinaryPrimitives.ReadInt32LittleEndian(r[22..]);
        if (!ok) throw new Exception($"Managed score differs: section={section} record={i}");
        count++;
    }
}
if (at != bytes.Length) throw new Exception("trailing catalog");
foreach (var (ep, selector, expected) in new[] { (0, 16, 2), (12, 146, 12107), (23, 236, 20861) })
{
    if (!DungeonCombatCatalog.TryGetRuntime(0, (byte)ep, 0, 0, 0, (uint)selector, out _, out var t)
        || t.Score != expected) throw new Exception($"Scaled resource score regression: ep={ep}");
    count++;
}
Console.WriteLine($"COMBAT_RESOURCE_MANAGED_PASS records={count} scaled_remainder=12107 ep23_scaled=20861");

int ratingChecks = 0;
void CheckRating(int score, int maximum, int partySize, bool tookDamage, bool cleared, byte expected)
{
    var actual = DungeonRewardPolicy.CalculateRatingFromScore(score, maximum, cleared, partySize, tookDamage);
    if (actual != expected)
        throw new Exception($"Rating: score={score}/{maximum} party={partySize} damaged={tookDamage} cleared={cleared}: {actual}!={expected}");
    ratingChecks++;
}
foreach (var maximum in new[] { 1, 3, 101, 10_000, int.MaxValue })
foreach (var party in new[] { 1, 2, 3 })
foreach (var damaged in new[] { false, true })
{
    foreach (var bp in new[] { 0, 2_000, 3_000, 4_000, 5_000, 6_000, 8_000, 9_500, 10_000 })
    {
        var boundary = (int)((maximum * (long)bp + 9_999) / 10_000);
        foreach (var score in new[] { Math.Max(0, boundary - 1), boundary, Math.Min(int.MaxValue, (long)boundary + 1) }.Select(s => (int)s))
        {
            var percentage = score * 10_000L / maximum;
            var expected = !damaged && percentage >= (party > 1 ? 5_000 : 9_500) ? (byte)5
                : percentage >= (party > 1 ? 4_000 : 8_000) ? (byte)4
                : percentage >= (party > 1 ? 3_000 : 6_000) ? (byte)3
                : percentage >= (party > 1 ? 2_000 : 4_000) ? (byte)2 : (byte)1;
            CheckRating(score, maximum, party, damaged, true, expected);
            CheckRating(score, maximum, party, damaged, false, 0);
        }
    }
}
CheckRating(9_500, 10_000, 1, false, true, 5);
CheckRating(9_499, 10_000, 1, false, true, 4);
CheckRating(5_000, 10_000, 2, false, true, 5);
CheckRating(4_999, 10_000, 2, false, true, 4);
CheckRating(10_000, 10_000, 3, true, true, 4);
Console.WriteLine($"DUNGEON_RATING_MANAGED_PASS checks={ratingChecks} party=1/2/3 S=95%-or-50%+no-actual-HP-loss failed=F");
