using System.Buffers.Binary;
using System.Collections;
using System.Reflection;
using Microsoft.Data.Sqlite;
using OpenNanaimo.Adapter.Models;
using OpenNanaimo.Adapter.Services;

internal static partial class Program
{
    private const BindingFlags Private = BindingFlags.Instance | BindingFlags.NonPublic;
    private static readonly Type Session = typeof(NetworkAdapterService).GetNestedType("ConnectionSession", BindingFlags.NonPublic)!;
    private static object? Get(object target, string key) => target.GetType().GetProperty(key)!.GetValue(target);
    private static void Set(object target, string key, object? value) => target.GetType().GetProperty(key)!.SetValue(target, value);
    private static string Id(object actor) => (string)Get(actor, "SessionId")!;
    private static CharacterRecord Character(object actor) => (CharacterRecord)Get(actor, "Character")!;
    private static object? Invoke(NetworkAdapterService service, string method, params object?[] args) =>
        typeof(NetworkAdapterService).GetMethod(method, Private)!.Invoke(service, args);

    private static async Task CheckLifecycleAsync()
    {
        var root = Path.GetFullPath(Path.Combine(AppContext.BaseDirectory, "cases", Guid.NewGuid().ToString("N")));
        Directory.CreateDirectory(root);
        File.WriteAllBytes(Path.Combine(root, "game.db"), []);
        var database = new DatabaseService(root);
        await database.InitializeAsync();
        await using var service = new NetworkAdapterService(database, _ => { }, root);
        try
        {
            var members = new List<object>();
            var worlds = new List<object>();
            for (var i = 0; i < 4; i++)
            {
                var account = await database.OpenLocalAccountAsync("arena" + i);
                await database.CreateLocalCharacterAsync(account, "Arena" + i, 0);
                var character = (await database.GetCharacterAsync(account))!;
                var world = Activator.CreateInstance(Session, true)!;
                Check(await database.BeginWorldSessionAsync(character.AccountId, character.Id, Id(world), 1, "127.0.0.1"),
                    "arena reward owner is authenticated");
                Set(world, "AccountId", character.AccountId); Set(world, "Character", character);
                Set(world, "OnlineTracked", true); Set(world, "ChannelId", 1); Set(world, "TownSceneActive", true);
                var presenceType = typeof(NetworkAdapterService).GetNestedType("WorldPresence", BindingFlags.NonPublic)!;
                var presence = Activator.CreateInstance(presenceType, BindingFlags.Instance | BindingFlags.Public | BindingFlags.NonPublic,
                    null, [world, Id(world), character.AccountId, character.Id, "arena" + i, character.Name, "127.0.0.1", 1,
                        DateTime.UtcNow, DateTime.UtcNow, (Action<string>)(_ => { })], null)!;
                var active = typeof(NetworkAdapterService).GetField("_activeWorldSessions", Private)!.GetValue(service)!;
                active.GetType().GetMethod("TryAdd")!.Invoke(active, [Id(world), presence]);
                worlds.Add(world);
                var member = Activator.CreateInstance(Session, true)!;
                Set(member, "AccountId", character.AccountId); Set(member, "Character", character);
                Set(member, "OnlineTracked", true); Set(member, "AuxiliaryGameSession", true);
                Set(member, "ArenaGameType", (byte)4); Set(member, "ChannelId", 1);
                members.Add(member);
            }
            Task<byte[]?> Send(object member, ushort op, byte[] bytes) => (Task<byte[]?>)Invoke(service,
                "HandleNativeFrameAsync", NativeDungeonClient.Frame(op, bytes), op, "ArenaAdapter",
                "127.0.0.1:30000", "127.0.0.1", member, CancellationToken.None)!;
            var room = Invoke(service, "CreateArenaRoom", members[0],
                new ArenaCreateRequest(new byte[44], "Arena", "", 0, 0, 0, 0, 0, 0))!;
            for (var i = 1; i < 4; i++)
            {
                object?[] join = [members[i], checked((ushort)(int)Get(room, "Id")!), "", null];
                Check((bool)Invoke(service, "TryJoinArenaRoom", join)!, "arena four-member roster joins");
            }
            void Prepare()
            {
                Set(room, "GameDataPayload", ArenaProtocol.BuildGameData(0, 0));
                for (var i = 0; i < 4; i++)
                {
                    Set(members[i], "ArenaReady", true); Set(members[i], "ArenaTeamCode", (byte)(i < 2 ? 1 : 2));
                    Set(members[i], "P2PInfoRegistered", true); Set(members[i], "ArenaP2PProtocolConfirmed", true);
                }
                object?[] start = [members[0], ""];
                Check((bool)Invoke(service, "TryStartArenaRoom", start)!, "arena starts a fresh round epoch");
            }
            Prepare();
            ushort Find(string resource) => Enumerable.Range(0, 2000).Select(i => (ushort)i).First(i =>
                ArenaTargetCatalog.TryGet(0, 0, i, out var row) && row.Resource == resource && row.Ordinal == 0);
            async Task<byte[]> Hit(ushort uid)
            {
                var request = new byte[12]; BinaryPrimitives.WriteUInt32LittleEndian(request.AsSpan(8), uid);
                return (await Send(members[0], 0xD00D, request))!;
            }
            var ballUid = Find("ssky_pvp_bbm_ball100.mmo");
            Check((await Hit(ballUid))[26] != 200, "large arena ball survives the first hit with authored 8000 HP");
            foreach (var resource in new[] { "ar00_dg00_st00_obj00.mmo", "ani_mon_om_pig_01_02.mmo", "ani_mon_om_pig_01_03.mmo" })
            {
                var uid = Find(resource);
                var terminalCount = 0;
                for (var i = 0; i < 100; i++) if ((await Hit(uid))[26] == 200) terminalCount++;
                Check(terminalCount == 1, "each copper-pig deform stage terminates exactly once: " + resource);
            }
            var finalUid = Find("ani_mon_om_pig_01_04.mmo");
            Check((await Hit(finalUid))[26] != 200 && (await Hit(finalUid))[26] != 200,
                "final type4 copper-pig obstacle remains in the scene");
            var unknown = new byte[12]; BinaryPrimitives.WriteUInt32LittleEndian(unknown.AsSpan(8), ushort.MaxValue);
            Check(await Send(members[0], 0xD00D, unknown) is null, "unknown arena target cannot be cleared by a UID fallback");
            Check(((IDictionary)Get(room, "ScoreBySession")!).Values.Cast<int>().All(score => score == 0),
                "obstacle damage does not invent star score");
            byte[] Pickup(ushort category, ushort uid, uint value)
            {
                var b = new byte[8]; BinaryPrimitives.WriteUInt16LittleEndian(b, category);
                BinaryPrimitives.WriteUInt16LittleEndian(b.AsSpan(2), uid); BinaryPrimitives.WriteUInt32LittleEndian(b.AsSpan(4), value);
                return b;
            }
            Check(await Send(members[0], 0xD034, Pickup(30, 10, 500)) is not null, "first star pickup accrues score");
            Check(await Send(members[0], 0xD034, Pickup(30, 10, 500)) is null
                && await Send(members[2], 0xD034, Pickup(30, 10, 500)) is null, "duplicate and cross-member pickup cannot double-claim");
            await Send(members[0], 0xD034, Pickup(30, 11, 100));
            await Send(members[2], 0xD034, Pickup(30, 12, 500));
            await Send(members[3], 0xD034, Pickup(30, 13, 500));
            Check(await Send(members[0], 0xD034, Pickup(30, 14, uint.MaxValue)) is null, "unbounded star denomination is rejected");
            var item = await Send(members[0], 0xD034, Pickup(40, 15, 17));
            Check(item is not null && BinaryPrimitives.ReadUInt16LittleEndian(item.AsSpan(20)) == 17,
                "arena item carrier uses its native type WORD rather than the star-value DWORD");
            var use = new byte[8]; BinaryPrimitives.WriteUInt16LittleEndian(use, 10);
            BinaryPrimitives.WriteUInt16LittleEndian(use.AsSpan(2), WireIdentityAllocator.GetSceneEntityId(Character(members[0]).Id));
            BinaryPrimitives.WriteUInt16LittleEndian(use.AsSpan(4), 15);
            var used = await Send(members[0], 0xD014, use);
            Check(used is not null && BinaryPrimitives.ReadUInt16LittleEndian(used.AsSpan(6)) == 0xD035,
                "D014 self item use emits D035 without damaging an opponent");
            Check(await Send(members[0], 0xD014, use) is null, "an owned arena item is consumed once");
            var hp = (IDictionary)Get(room, "CurrentHpBySession")!;
            var coincident = new byte[8]; BinaryPrimitives.WriteUInt16LittleEndian(coincident, 10);
            BinaryPrimitives.WriteUInt16LittleEndian(coincident.AsSpan(2), WireIdentityAllocator.GetSceneEntityId(Character(members[2]).Id));
            BinaryPrimitives.WriteUInt16LittleEndian(coincident.AsSpan(6), WireIdentityAllocator.GetSceneEntityId(Character(members[0]).Id));
            var coincidentHit = await Send(members[2], 0xD014, coincident);
            Check(coincidentHit is not null && BinaryPrimitives.ReadUInt16LittleEndian(coincidentHit.AsSpan(6)) == 0xD015,
                "a projectile code matching the victim UID does not consume an item when its attacker is declared");
            var ambiguous = new byte[8]; BinaryPrimitives.WriteUInt16LittleEndian(ambiguous, 20);
            Check(await Send(members[2], 0xD014, ambiguous) is null,
                "a four-player collision with no declared source cannot choose an arbitrary opponent");
            hp[Id(members[2])] = (ushort)1;
            var attack = new byte[8]; BinaryPrimitives.WriteUInt16LittleEndian(attack, 20);
            BinaryPrimitives.WriteUInt16LittleEndian(attack.AsSpan(2), 247);
            BinaryPrimitives.WriteUInt16LittleEndian(attack.AsSpan(6), WireIdentityAllocator.GetSceneEntityId(Character(members[0]).Id));
            var lethal = await Send(members[2], 0xD014, attack);
            Check(lethal is not null && lethal[18] == 200 && (ushort)hp[Id(members[2])]! > 0,
                "timed PvP death emits terminal damage and restores an attackable HP ledger");
            Check(BinaryPrimitives.ReadUInt16LittleEndian(lethal!.AsSpan(20)) == 0
                && BinaryPrimitives.ReadUInt16LittleEndian(lethal.AsSpan(22)) == 0,
                "lethal and nonlethal hits cannot transfer stars without an authoritative score transaction");
            var expBefore = members.Select(m => Character(m).Experience).ToArray();
            Check(await Send(members[0], 0xCF89, new byte[4]) is null, "results require an accepted terminal boundary");
            foreach (var member in members) Check(await Send(member, 0xCF97, []) is not null, "each member receives one terminal acknowledgement");
            Check(await Send(members[0], 0xCF97, []) is null, "duplicate terminal request cannot reopen the result phase");
            Check(await Send(members[1], 0xD034, Pickup(30, 20, 500)) is null, "terminal boundary freezes late star pickups");
            var falseScore = new byte[4]; BinaryPrimitives.WriteUInt32LittleEndian(falseScore, uint.MaxValue);
            var results = await Task.WhenAll(Send(members[0], 0xCF89, falseScore), Send(members[2], 0xCF89, falseScore));
            Check(results[0] is not null && results[0]!.AsSpan(8).SequenceEqual(results[1]!.AsSpan(8)),
                "concurrent result requests share the same frozen settlement");
            var result = results[0]!;
            var scores = new uint[] { 600, 0, 500, 500 };
            for (var i = 0; i < 4; i++)
            {
                var at = 12 + 56 * i;
                Check(BinaryPrimitives.ReadUInt16LittleEndian(result.AsSpan(at + 2)) == (i < 2 ? 0 : 1),
                    "winning team uses aggregate stars instead of the highest individual score");
                Check(BinaryPrimitives.ReadUInt32LittleEndian(result.AsSpan(at + 12)) == scores[i]
                    && BinaryPrimitives.ReadUInt32LittleEndian(result.AsSpan(at + 16)) == scores[i] / 4,
                    "CF8A keeps displayed stars separate from actual awarded experience");
                var saved = (await database.GetCharacterByIdAsync(Character(members[i]).Id))!;
                Check(saved.Experience == expBefore[i] + scores[i] / 4, "arena experience is persisted exactly once per participant");
            }
            var repeated = await Send(members[0], 0xCF89, falseScore);
            Check(repeated!.AsSpan(8).SequenceEqual(result.AsSpan(8)), "repeated result request returns immutable rows");
            var reset = await Send(members[2], 0xCF8B, [0, 0, 1, 0]);
            Check(reset is not null && !(bool)Get(room, "Started")!, "one result action resets the shared round");
            foreach (var member in members.Where(m => !ReferenceEquals(m, members[2])))
                Check(((IList)Get(members[2], "PendingSessionBroadcasts")!).Cast<object>().Any(b =>
                    (ushort)Get(b, "Opcode")! == 0xCF8C && ReferenceEquals(Get(b, "Target"), member)),
                    "shared reset reaches every other arena member");
            Check((await Send(members[3], 0xCF89, falseScore))!.AsSpan(8).SequenceEqual(result.AsSpan(8)),
                "delayed result survives another member's reset action");
            Check(await Send(members[2], 0xCF8B, [0, 0, 1, 0]) is not null, "reset retransmission acknowledges the same epoch");
            Prepare();
            Check(((IDictionary)Get(room, "TargetHpByUid")!).Count == 0 && ((IDictionary)Get(room, "ArenaItems")!).Count == 0,
                "new round clears obstacle and item state");
            Check((await Hit(ballUid))[26] != 200, "second round restores the authored ball lifecycle");
            Check(await Send(members[0], 0xCF8B, [0, 0, 1, 0]) is null, "old reset cannot cancel the new active round");
            await Send(members[0], 0xD034, Pickup(30, 10, 500));
            await Send(members[0], 0xD034, Pickup(30, 11, 100));
            await Send(members[2], 0xD034, Pickup(30, 12, 500));
            await Send(members[3], 0xD034, Pickup(30, 13, 500));
            foreach (var member in members) await Send(member, 0xCF97, []);
            Invoke(service, "RemoveArenaRoomMember", members[3], null);
            var presences = typeof(NetworkAdapterService).GetField("_activeWorldSessions", Private)!.GetValue(service)!;
            var removePresence = presences.GetType().GetMethods().Single(m => m.Name == "TryRemove"
                && m.GetParameters().Length == 2 && m.GetParameters()[0].ParameterType == typeof(string));
            removePresence.Invoke(presences, [Id(worlds[3]), null]);
            var afterLeave = await Send(members[0], 0xCF89, falseScore);
            Check(afterLeave is not null && afterLeave.Length == 12 + 4 * 56,
                "world disconnect after terminal freeze cannot block remaining result recipients");
            Check(BinaryPrimitives.ReadUInt16LittleEndian(afterLeave!.AsSpan(12 + 2 * 56 + 2)) == 1
                && BinaryPrimitives.ReadUInt32LittleEndian(afterLeave.AsSpan(12 + 3 * 56 + 12)) == 500,
                "departed member retains the frozen team and star contribution");
            await Send(members[0], 0xCF8B, [0, 0, 1, 0]);
            Prepare();
            foreach (var member in members.Take(3)) await Send(member, 0xCF97, []);
            var tied = await Send(members[0], 0xCF89, falseScore);
            Check(tied is not null && Enumerable.Range(0, 3).All(i =>
                BinaryPrimitives.ReadUInt16LittleEndian(tied.AsSpan(12 + 56 * i + 2)) == 0),
                "a tied team score does not invent a winning side");
            Console.WriteLine("ARENA_LIFECYCLE_PASS targets-items-team-score-rewards-reset-second-round");
        }
        finally
        {
            SqliteConnection.ClearAllPools();
            var parent = Path.GetFullPath(Path.Combine(AppContext.BaseDirectory, "cases")) + Path.DirectorySeparatorChar;
            if (!root.StartsWith(parent, StringComparison.OrdinalIgnoreCase)) throw new InvalidOperationException("Unsafe test path.");
            Directory.Delete(root, true);
        }
    }
}
