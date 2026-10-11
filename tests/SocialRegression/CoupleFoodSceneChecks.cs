using System.Buffers.Binary;
using Microsoft.Data.Sqlite;
using OpenNanaimo.Adapter.Models;
using OpenNanaimo.Adapter.Services;

internal static partial class Program
{
    private static async Task PrepareFoodPairAsync(Fixture f, uint ring)
    {
        await f.Database.GrantInventoryItemToAccountAsync(Character(f.First).AccountId, ring, 1);
        Check((await f.Database.CreateCoupleRelationAsync(Character(f.First).AccountId,
            Character(f.First).Id, SessionId(f.First), Character(f.Second).Id, ring,
            Token, SessionId(f.Second))).Success, "food pair relation " + ring);
        var invitation = new byte[24];
        BinaryPrimitives.WriteUInt16LittleEndian(invitation.AsSpan(16), WireIdentityAllocator.GetSceneEntityId(Character(f.First).Id));
        BinaryPrimitives.WriteUInt16LittleEndian(invitation.AsSpan(22), WireIdentityAllocator.GetSceneEntityId(Character(f.Second).Id));
        await Dispatch(f, f.First, 0xC4E0, invitation);
        var answer = new byte[4]; answer[0] = 1;
        BinaryPrimitives.WriteUInt16LittleEndian(answer.AsSpan(2), WireIdentityAllocator.GetSceneEntityId(Character(f.First).Id));
        await Dispatch(f, f.Second, 0xC4E1, answer);
        Check((int)Get(f.First, "PartyId")! > 0 && Equals(Get(f.First, "PartyId"), Get(f.Second, "PartyId")), "food pair authenticated party");
        foreach (var session in new[] { f.First, f.Second, f.Third })
        {
            foreach (var code in new uint[] { 14000001, 14000002 })
                await f.Database.GrantInventoryItemToAccountAsync(Character(session).AccountId, code, 20);
            await FoodSqlAsync(f, $"UPDATE Characters SET MaxHp=10000,MaxMp=10000,CurrentHp=100,CurrentMp=100 WHERE Id={Character(session).Id}");
            Set(session, "Character", (await f.Database.GetCharacterByIdAsync(Character(session).Id))!);
            Set(session, "NonCombatResourceSnapshot", NetworkAdapterService.ResolveInventoryVitals(Character(session)));
        }
    }

    private static async Task FoodSqlAsync(Fixture f, string sql)
    {
        await using var connection = new SqliteConnection(new SqliteConnectionStringBuilder { DataSource = Path.Combine(f.Root, "game.db") }.ToString());
        await connection.OpenAsync(); await using var command = connection.CreateCommand();
        command.CommandText = sql; await command.ExecuteNonQueryAsync();
    }

    private static async Task InjureFoodPairAsync(Fixture f)
    {
        foreach (var session in new[] { f.First, f.Second })
        {
            await FoodSqlAsync(f, $"UPDATE Characters SET CurrentHp=100,CurrentMp=100 WHERE Id={Character(session).Id}");
            Character(session).CurrentHp = 100; Character(session).CurrentMp = 100;
            Set(session, "NonCombatResourceSnapshot", NetworkAdapterService.ResolveInventoryVitals(Character(session)));
        }
    }

    private static async Task<byte[]> FoodRequestAsync(Fixture f, object session, uint code)
    {
        var inventory = (await Dispatch(f, session, 0xC42F, []))!;
        var row = Enumerable.Range(0, BinaryPrimitives.ReadUInt16LittleEndian(inventory.AsSpan(10)))
            .First(i => BinaryPrimitives.ReadUInt32LittleEndian(inventory.AsSpan(12 + i * 8)) == code);
        var payload = new byte[8]; BinaryPrimitives.WriteUInt32LittleEndian(payload, code);
        BinaryPrimitives.WriteUInt16LittleEndian(payload.AsSpan(4), BinaryPrimitives.ReadUInt16LittleEndian(inventory.AsSpan(16 + row * 8)));
        return payload;
    }

    private static async Task CheckFoodUseAsync(Fixture f, object source, object partner, uint code, ushort opcode, string scene, uint ring)
    {
        var request = await FoodRequestAsync(f, source, code);
        var sourceBefore = (await f.Database.GetCharacterByIdAsync(Character(source).Id))!;
        var partnerBefore = (await f.Database.GetCharacterByIdAsync(Character(partner).Id))!;
        Broadcasts(source).Clear();
        var result = await Dispatch(f, source, opcode, request);
        var frames = SplitInventoryFrames(result!);
        Check(frames[0].Op == (opcode == 0xC43D ? 0xC43E : 0xC46E)
            && BinaryPrimitives.ReadUInt32LittleEndian(frames[0].Bytes.AsSpan(8)) == (opcode == 0xC43D ? 200u : 1u), scene + " food receipt");
        ShopCatalog.TryGet(code, out var item);
        foreach (var (session, before) in new[] { (source, sourceBefore), (partner, partnerBefore) })
        {
            var after = (await f.Database.GetCharacterByIdAsync(before.Id))!;
            Check(after.CurrentHp == Math.Min(10000, before.CurrentHp + CoupleBenefitPolicy.ScaleRecovery(item.QuickHpRestore, ring))
                && after.CurrentMp == Math.Min(10000, before.CurrentMp + CoupleBenefitPolicy.ScaleRecovery(item.QuickMpRestore, ring))
                && Character(session).CurrentHp == after.CurrentHp && Character(session).CurrentMp == after.CurrentMp,
                scene + " both ledgers recover once " + before.Name + $" before={before.CurrentHp}/{before.CurrentMp} after={after.CurrentHp}/{after.CurrentMp} live={Character(session).CurrentHp}/{Character(session).CurrentMp}");
        }
        var sourceAfter = (await f.Database.GetCharacterByIdAsync(sourceBefore.Id))!;
        var partnerAfter = (await f.Database.GetCharacterByIdAsync(partnerBefore.Id))!;
        Check(sourceAfter.Items.Single(i => i.ItemCode == code).Quantity == sourceBefore.Items.Single(i => i.ItemCode == code).Quantity - 1
            && partnerAfter.Items.Single(i => i.ItemCode == code).Quantity == partnerBefore.Items.Single(i => i.ItemCode == code).Quantity,
            scene + " only source inventory debited");
        var notices = CoupleNoticesFor(source, partner);
        var inRoom = Get(source, "NativeDungeon") is not null || (int)Get(source, "DungeonRoomId")! != 0;
        var ready = Get(source, "NativeDungeon") is not null
            ? (bool)typeof(NetworkAdapterService).GetMethod("IsNativeReadyRoomInventory", System.Reflection.BindingFlags.Static | System.Reflection.BindingFlags.NonPublic)!.Invoke(null, [source])!
            : inRoom && Get(Get(Invoke<object>(f.Service, "GetDungeonRoom", source), "Battle")!, "State")!.ToString() == "Prepared";
        var partnerUid = Get(partner, "NativeCheckpoint") is NativeDungeonState state
            ? (ushort)state.Get(4) : WireIdentityAllocator.GetSceneEntityId(Character(partner).Id);
        if (!inRoom)
        {
            var absolute = (byte[])Get(notices.Single(n => (ushort)Get(n, "Opcode")! == 0xD8FF), "Payload")!;
            Check(BinaryPrimitives.ReadUInt16LittleEndian(absolute.AsSpan(12)) == partnerAfter.CurrentHp
                && BinaryPrimitives.ReadUInt16LittleEndian(absolute.AsSpan(14)) == partnerAfter.CurrentMp,
                scene + " partner receives owned town absolute HP/MP");
        }
        else
        {
            var carrier = ready ? (ushort)0xCF72 : (ushort)0xCF94;
            var payload = (byte[])Get(notices.Single(n => (ushort)Get(n, "Opcode")! == carrier
                && BinaryPrimitives.ReadUInt16LittleEndian((byte[])Get(n, "Payload")!) == partnerUid), "Payload")!;
            Check(notices.All(n => (ushort)Get(n, "Opcode")! != 0xD8FF) && frames.All(row => row.Op != 0xD8FF),
                scene + " no discarded dungeon D8FF");
            if (ready)
                Check(payload.Length == 108 && BinaryPrimitives.ReadUInt16LittleEndian(payload.AsSpan(6)) == partnerAfter.CurrentHp
                    && BinaryPrimitives.ReadUInt16LittleEndian(payload.AsSpan(8)) == partnerAfter.CurrentMp,
                    scene + " ready-room actor receives complete absolute resources");
            else
            {
                Check(payload.Length == 16 && BinaryPrimitives.ReadUInt16LittleEndian(payload.AsSpan(2)) == ushort.MaxValue
                    && BinaryPrimitives.ReadUInt16LittleEndian(payload.AsSpan(8)) == partnerAfter.CurrentHp - partnerBefore.CurrentHp
                    && BinaryPrimitives.ReadUInt16LittleEndian(payload.AsSpan(10)) == partnerAfter.CurrentMp - partnerBefore.CurrentMp
                    && payload.AsSpan(12).IndexOfAnyExcept((byte)0) < 0, scene + " no-debit CF94 matches committed gains");
                Check(frames.All(row => row.Op != 0xCF72) && notices.All(n => (ushort)Get(n, "Opcode")! != 0xCF72),
                    scene + " recovery does not rebuild quickbar protection arrays");
            }
            if (opcode == 0xC43D)
                Check(frames.Single(row => row.Op == 0xC43F).Bytes.AsSpan(8).IndexOfAnyExcept((byte)0) < 0,
                    scene + " inventory completion does not duplicate actor recovery");
        }
        Check(CoupleNoticesFor(source, f.Third).Length == 0 && Character(f.Third).CurrentHp == 100, scene + " ordinary teammate untouched");
        var repeated = await Dispatch(f, source, opcode, request);
        Check(BinaryPrimitives.ReadUInt32LittleEndian(repeated!.AsSpan(8)) == 0
            && (await f.Database.GetCharacterByIdAsync(sourceBefore.Id))!.Items.Single(i => i.ItemCode == code).Quantity == sourceAfter.Items.Single(i => i.ItemCode == code).Quantity,
            scene + " consumed instance replay rejected");
    }

    private static async Task CheckCoupleFoodScenesAsync()
    {
        foreach (var ring in new uint[] { 43000001, 43000002, 43000003 })
        {
            await using var f = await Fixture.CreateAsync(); await PrepareFoodPairAsync(f, ring);
            await CheckFoodUseAsync(f, f.First, f.Second, 14000001, 0xC43D, "town HP", ring);
            await CheckFoodUseAsync(f, f.Second, f.First, 14000002, 0xC46D, "town MP reverse", ring);
            var requests = await Task.WhenAll(FoodRequestAsync(f, f.First, 14000001), FoodRequestAsync(f, f.Second, 14000002));
            var hpBefore = Character(f.First).CurrentHp; var mpBefore = Character(f.First).CurrentMp;
            await Task.WhenAll(Dispatch(f, f.First, 0xC46D, requests[0]), Dispatch(f, f.Second, 0xC46D, requests[1]));
            foreach (var member in new[] { f.First, f.Second })
                Check(Character(member).CurrentHp == hpBefore + CoupleBenefitPolicy.ScaleRecovery(300, ring)
                    && Character(member).CurrentMp == mpBefore + CoupleBenefitPolicy.ScaleRecovery(30, ring),
                    "simultaneous opposite food uses preserve both resource changes " + ring);

            var isolatedRequest = await FoodRequestAsync(f, f.First, 14000002);
            var partyId = (int)Get(f.Second, "PartyId")!;
            Set(f.Second, "PartyId", 0); Broadcasts(f.First).Clear();
            var partnerHp = Character(f.Second).CurrentHp; var partnerMp = Character(f.Second).CurrentMp;
            await Dispatch(f, f.First, 0xC43D, isolatedRequest);
            Check(Character(f.Second).CurrentHp == partnerHp && Character(f.Second).CurrentMp == partnerMp
                && CoupleNoticesFor(f.First, f.Second).Length == 0, "town partner outside the party receives no recovery");
            Set(f.Second, "PartyId", partyId);
            var creation = new byte[44]; BinaryPrimitives.WriteUInt16LittleEndian(creation.AsSpan(24), 100);
            await Dispatch(f, f.First, 0xCF6C, creation);
            var room = Invoke<object>(f.Service, "GetDungeonRoom", f.First);
            var entry = new byte[12]; BinaryPrimitives.WriteUInt16LittleEndian(entry.AsSpan(2), checked((ushort)(int)Get(room, "Id")!));
            await Dispatch(f, f.Second, 0xCF75, entry);
            await InjureFoodPairAsync(f);
            await CheckFoodUseAsync(f, f.First, f.Second, 14000002, 0xC43D, "ready MP", ring);
            await CheckFoodUseAsync(f, f.Second, f.First, 14000001, 0xC46D, "ready HP reverse", ring);
            await Dispatch(f, f.Second, 0xCF7D, new byte[] { 1, 0, 0, 0 });
            await Dispatch(f, f.First, 0xCF7F, []);
            await InjureFoodPairAsync(f);
            await CheckFoodUseAsync(f, f.First, f.Second, 14000001, 0xC46D, "active HP", ring);
            await CheckFoodUseAsync(f, f.Second, f.First, 14000002, 0xC43D, "active MP reverse", ring);
            var battle = Get(room, "Battle")!;
            Set(battle, "State", Enum.Parse(Get(battle, "State")!.GetType(), "Settled"));
            Set(battle, "SettlementStarted", true);
            await CheckFoodUseAsync(f, f.First, f.Second, 14000002, 0xC46D, "settlement MP", ring);
            await CheckFoodUseAsync(f, f.Second, f.First, 14000001, 0xC43D, "settlement HP reverse", ring);

            var request = await FoodRequestAsync(f, f.First, 14000001);
            var before = (await f.Database.GetCharacterByIdAsync(Character(f.First).Id))!;
            await FoodSqlAsync(f, $"CREATE TRIGGER RejectPartnerFood BEFORE UPDATE OF CurrentHp ON Characters WHEN NEW.Id={Character(f.Second).Id} BEGIN SELECT RAISE(ABORT,'partner recovery'); END;");
            var failed = false;
            try { await Dispatch(f, f.First, 0xC43D, request); } catch (SqliteException) { failed = true; }
            await FoodSqlAsync(f, "DROP TRIGGER RejectPartnerFood;");
            var after = (await f.Database.GetCharacterByIdAsync(before.Id))!;
            Check(failed && after.CurrentHp == before.CurrentHp
                && after.Items.Single(i => i.ItemCode == 14000001).Quantity == before.Items.Single(i => i.ItemCode == 14000001).Quantity,
                "partner SQL failure rolls source recovery and debit back");
            Set(room, "HasPendingTransition", true);
            Check(BinaryPrimitives.ReadUInt32LittleEndian((await Dispatch(f, f.First, 0xC43D, request))!.AsSpan(8)) == 0,
                "loading transition cannot consume food");
            Set(room, "HasPendingTransition", false);
            ((HashSet<long>)Get(battle, "DeadCharacters")!).Add(Character(f.Second).Id);
            var deadPartnerHp = Character(f.Second).CurrentHp;
            var deadPartnerMp = Character(f.Second).CurrentMp;
            Broadcasts(f.First).Clear();
            await Dispatch(f, f.First, 0xC43D, request);
            Check(Character(f.Second).CurrentHp == deadPartnerHp && Character(f.Second).CurrentMp == deadPartnerMp
                && CoupleNoticesFor(f.First, f.Second).All(notice =>
                    BinaryPrimitives.ReadUInt16LittleEndian((byte[])Get(notice, "Payload")!) != WireIdentityAllocator.GetSceneEntityId(Character(f.Second).Id)),
                "dead partner only observes the source recovery and is not revived by food");
        }
    }

    private static async Task CheckNativeCoupleFoodScenesAsync()
    {
        await using var f = await Fixture.CreateAsync(); const uint ring = 43000002;
        await PrepareFoodPairAsync(f, ring);
        var bridge = Path.GetFullPath(Environment.GetEnvironmentVariable("NANAIMO_COUPLE_BRIDGE") ?? "adapter_runtime/nanaimo_gameplay_bridge.exe");
        await using var pool = new NativeDungeonPool(bridge, Path.Combine(f.Root, "food-workers"));
        await using var reserved = await pool.AcquireAsync("reserved-primary", Token);
        await using var firstLease = await pool.AcquireAsync("food-pair", Token);
        await using var secondLease = await pool.AcquireAsync("food-pair", Token);
        await using var first = new NativeDungeonClient(_ => Task.CompletedTask, firstLease.Port);
        await using var second = new NativeDungeonClient(_ => Task.CompletedTask, secondLease.Port);
        try
        {
            foreach (var (session, worker, lease) in new[] { (f.First, first, firstLease), (f.Second, second, secondLease) })
            {
                await worker.ConnectAsync(Token);
                var state = NativeDungeonState.Create(Character(session), [], []);
                CoupleBenefitPolicy.WriteNativeRing(state, ring);
                Set(session, "NativeCheckpoint", await worker.ExchangeAsync(null, state, Token));
                Set(session, "NativeDungeon", worker); Set(session, "NativeLease", lease);
                Set(session, "NativeDungeonSelectionValid", true); Set(session, "NativeForwarding", true);
                Set(session, "NativeBattleEpoch", 1L); Set(session, "NativeBattleResources", BattleResourceSnapshot.Capture(state, 1));
                var creation = new byte[44]; BinaryPrimitives.WriteUInt16LittleEndian(creation.AsSpan(24), 100);
                await worker.ExchangeCapturedAsync(NativeDungeonClient.Frame(0xCF6C, creation), null, Token);
            }
            f.Service.NativeDungeonEnabled = true;
            foreach (var scene in new[] { "ready", "active", "settlement" })
            {
                foreach (var session in new[] { f.First, f.Second })
                {
                    Set(session, "NativeCoupleStartRequested", scene != "ready");
                    Set(session, "NativeCoupleIdentityPublished", scene != "ready");
                    Set(session, "NativeDungeonSettlementAwaitingAction", scene == "settlement");
                    var resources = (BattleResourceSnapshot)Get(session, "NativeBattleResources")!;
                    Set(session, "NativeBattleResources", resources with { SettlementFrozen = scene == "settlement" });
                }
                await CheckFoodUseAsync(f, f.First, f.Second, 14000001, 0xC43D, "native " + scene + " HP", ring);
                await CheckFoodUseAsync(f, f.Second, f.First, 14000002, 0xC46D, "native " + scene + " MP reverse", ring);
                foreach (var (session, worker) in new[] { (f.First, first), (f.Second, second) })
                {
                    var checkpoint = await worker.ExchangeAsync(null, null, Token);
                    Check(checkpoint.Get(20) == Character(session).CurrentHp && checkpoint.Get(28) == Character(session).CurrentMp,
                        "native " + scene + " worker keeps restored absolute resources");
                    Check(((BattleResourceSnapshot)Get(session, "NativeBattleResources")!).SettlementFrozen == (scene == "settlement"),
                        "native " + scene + " food preserves settlement barrier");
                }
            }
            Set(f.Second, "NativeDungeonDeathLatched", true);
            var request = await FoodRequestAsync(f, f.Second, 14000001);
            Check(BinaryPrimitives.ReadUInt32LittleEndian((await Dispatch(f, f.Second, 0xC46D, request))!.AsSpan(8)) == 0,
                "native dead source cannot bypass paid revival with food");
        }
        finally
        {
            foreach (var session in new[] { f.First, f.Second })
            {
                Set(session, "NativeDungeon", null); Set(session, "NativeLease", null);
                Set(session, "NativeCheckpoint", null); Set(session, "NativeForwarding", false);
            }
        }
    }
}
