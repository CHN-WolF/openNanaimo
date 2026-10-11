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

int l7Checks = 0;
for (byte stage = 0; stage < 2; stage++)
for (byte slot = 0; slot < 9; slot++)
{
    ushort resourceUid = stage == 0 ? (ushort)59 : (ushort)62;
    if (!DungeonCombatCatalog.TryGet(0, 100, 6, stage, slot, resourceUid, out var barrel)
        || !DungeonCombatCatalog.IsL7ExplosiveBarrel(0, 100, 6, stage, resourceUid, barrel)
        || DungeonCombatCatalog.IsL7ExplosiveBarrel(0, 100, 7, stage, resourceUid, barrel)
        || DungeonCombatCatalog.IsL7ExplosiveBarrel(0, 100, 6, stage, (ushort)(resourceUid + 1), barrel))
        throw new Exception($"L7 barrel identity failed: stage={stage} slot={slot}");
    var bosses = DungeonCombatCatalog.GetBosses(0, 100, 6, stage, slot);
    if (bosses.Count != 1 || bosses[0].Value.TotalHp != (stage == 0 ? 3_060_000 : 4_289_329))
        throw new Exception($"L7 Korean boss generation failed: stage={stage} slot={slot}");
    l7Checks++;
}
Console.WriteLine($"L7_MANAGED_CATALOG_PASS slots={l7Checks} barrel_alias=stage0-and-stage1");

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

using (var contacts = System.Text.Json.JsonDocument.Parse(typeof(BossContactCatalog).Assembly
    .GetManifestResourceStream("OpenNanaimo.Adapter.BossContacts.json")!))
{
    var root = contacts.RootElement;
    var resources = root.GetProperty("resources").EnumerateArray().ToDictionary(
        r => r.GetProperty("resource").GetString()!, r => r.GetProperty("rows"));
    var checkedContacts = 0;
    foreach (var scope in root.GetProperty("scopes").EnumerateArray())
    {
        var key = scope.GetProperty("key").EnumerateArray().Select(v => v.GetByte()).ToArray();
        foreach (var part in scope.GetProperty("parts").EnumerateArray())
        {
            var rows = resources[part[2].GetString()!];
            for (var ordinal = 0; ordinal < rows.GetArrayLength(); ordinal++)
            {
                var descriptor = (uint)(part[0].GetByte() | part[1].GetByte() << 8 | ordinal << 16);
                if (BossContactCatalog.Resolve(key[0], key[1], key[2], key[3], key[4], descriptor) != rows[ordinal][2].GetUInt16())
                    throw new Exception("Managed Boss contact identity differs.");
                checkedContacts++;
            }
        }
    }
    if (checkedContacts != 28209 || BossContactCatalog.Count != checkedContacts
        || BossContactCatalog.Resolve(0,100,6,1,1,2u<<16) != 2003
        || BossContactCatalog.Resolve(0,100,6,1,1,1u<<16) != 0
        || BossContactCatalog.Resolve(0,100,6,1,1,0xFFFF0000) != 0)
        throw new Exception("Managed Boss contact coverage differs.");
    Console.WriteLine($"BOSS_CONTACT_MANAGED_PASS rows={checkedContacts}");
}

{
    const System.Reflection.BindingFlags privateStatic = System.Reflection.BindingFlags.NonPublic | System.Reflection.BindingFlags.Static;
    var service = typeof(NetworkAdapterService);
    object Create(string name, params object?[] args) => Activator.CreateInstance(
        service.GetNestedType(name, System.Reflection.BindingFlags.NonPublic)!, args)!;
    void Set(object value, string name, object? member) => value.GetType().GetProperty(name)!.SetValue(value, member);
    object Get(object value, string name) => value.GetType().GetProperty(name)!.GetValue(value)!;
    var room = Create("DungeonRoom");
    var battle = Create("DungeonBattleInstance", (byte)0, (byte)100, (byte)6, (byte)1, (byte)0);
    Set(room, "Battle", battle); Set(room, "SelectedMapIndex", (ushort)1);
    if (!BossContactCatalog.TryResolve(0,100,6,1,1,2u<<16, out var uid, out var attack) || attack != 2003
        || !DungeonCombatCatalog.TryGetBoss(0,100,6,1,1,uid, out var template))
        throw new Exception("Boss contact owner identity differs.");
    var boss = Create("DungeonBossState", template);
    var bosses = (System.Collections.IDictionary)Get(battle, "Bosses"); bosses.Add(uid,boss);
    var character = new OpenNanaimo.Adapter.Models.CharacterRecord { Id = 11, Level = 1 };
    var resolver = service.GetMethod("ResolveDungeonBossPartCollisionDamage",privateStatic)!;
    ushort Resolve(uint descriptor) => (ushort)resolver.Invoke(null,[room,descriptor,character])!;
    var energy = (int)Get(boss,"CurrentEnergy");
    if (Resolve(2u<<16)!=2003 || Resolve(1u<<16)!=0 || Resolve(0xFFFF0000)!=0
        || Resolve((2u<<16)|1)!=0 || (int)Get(boss,"CurrentEnergy")!=energy)
        throw new Exception("Boss contact must preserve component life and exact active mode.");
    character.DefenseFlat=2000;if(Resolve(2u<<16)!=3)throw new Exception("Boss contact defense differs.");
    character.DefenseFlat=3000;if(Resolve(2u<<16)!=1)throw new Exception("Boss contact positive floor differs.");
    var skills=(System.Collections.IDictionary)Get(battle,"ActiveSkills");
    var active=Create("DungeonActiveSkillState");
    Set(active,"SkillCode",52000008u);Set(active,"ActiveUntilTick",Environment.TickCount64+100000);
    skills.Add(character.Id,active);if(Resolve(2u<<16)!=0)throw new Exception("Meat protection differs.");
    skills.Clear();character.DefenseFlat=0;
    var components=(System.Collections.IDictionary)Get(boss,"Components");
    foreach(System.Collections.DictionaryEntry entry in components)
        if(((DungeonBossComponentKey)entry.Key).ParentIndex==0)Set(entry.Value!,"CurrentHp",0);
    if(Resolve(2u<<16)!=0)throw new Exception("Retired mode must retain zero damage.");
    foreach(System.Collections.DictionaryEntry entry in components)Set(entry.Value!,"CurrentHp",0);
    if(Resolve(2u<<16)!=0)throw new Exception("Terminal Boss must retain zero damage.");
    Console.WriteLine("BOSS_CONTACT_MANAGED_LIFECYCLE_PASS identity defense protection mode terminal attachment");
}
