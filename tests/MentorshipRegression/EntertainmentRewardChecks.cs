using System.Buffers.Binary;
using System.Collections;
using System.Reflection;
using System.Text;
using Microsoft.Data.Sqlite;
using OpenNanaimo.Adapter.Models;
using OpenNanaimo.Adapter.Services;

internal static partial class Program
{
    private static async Task CheckEntertainmentRewardsAsync()
    {
        Check(EntertainmentRewardPolicy.Pool.Count == 400
            && EntertainmentRewardPolicy.Pool.SequenceEqual(Enumerable.Range(13000001, 420).Select(i => (uint)i)
                .Where(code => !CardCatalog.IsGoldPowder(code))),
            "uniform entertainment pool excludes all twenty gold-powder cards and event or lucky cards");
        for (var i = 0; i < 420; i++)
            Check(EntertainmentRewardPolicy.IsBasicCard(13000001u + (uint)i)
                == !CardCatalog.IsGoldPowder(13000001u + (uint)i), "entertainment card eligibility " + (i + 1));
        await CheckEntertainmentRoomRewardsAsync();
        await CheckEntertainmentPetBoardGateAsync();
        await using var f = await Fixture.CreateAsync();
        await f.ExecuteAsync("UPDATE Characters SET PetVariant=1,EquippedPetItemCode=15000001 WHERE Id=$id; "
            + "INSERT INTO CharacterItems(CharacterId,ItemCode,Quantity,PetCurrentStage,PetMaximumStage,PetLevel,PetExperience,UpdatedAt) "
            + "VALUES($id,15000001,1,1,2,0,0,'test') ON CONFLICT(CharacterId,ItemCode) DO UPDATE SET "
            + "Quantity=1,PetCurrentStage=1,PetMaximumStage=2,PetLevel=0,PetExperience=0", ("$id", Character(f.Teacher).Id));
        Set(f.Teacher, "Character", (await f.Database.GetCharacterByIdAsync(Character(f.Teacher).Id))!);
        var soloPetReward = EntertainmentRewardPolicy.GetPetExperience(PetProgression.GetState(Character(f.Teacher), 15000001), 0, 1);
        var host = Activator.CreateInstance(SessionType, nonPublic: true)!;
        foreach (var property in new[] { "AccountId", "Username", "Character", "ChannelId", "RemoteIp" })
            Set(host, property, Get(f.Teacher, property));
        Set(host, "OnlineTracked", true);
        Set(host, "AuxiliaryGameSession", true);
        Set(host, "ArenaGameType", (byte)1);
        var active = typeof(NetworkAdapterService).GetField("_activeArenaSessions", PrivateInstance)!.GetValue(f.Service)!;
        active.GetType().GetMethod("TryAdd")!.Invoke(active, [Id(host), host]);
        Task<byte[]?> Send(ushort opcode, byte[] bytes) => Dispatch(f, host, opcode, bytes, "ArenaAdapter");
        var lobby = await Send(0xCF0B, []);
        Check(lobby is { Length: 20 } && BinaryPrimitives.ReadUInt32LittleEndian(lobby.AsSpan(8)) == Character(host).Id
            && BinaryPrimitives.ReadUInt32LittleEndian(lobby.AsSpan(16)) == 0,
            "new lobby keeps its UID separate from the zero personal record");
        var create = new byte[44]; Encoding.ASCII.GetBytes("Score policy").CopyTo(create, 0);
        BinaryPrimitives.WriteUInt16LittleEndian(create.AsSpan(24), 100);
        var created = (await Send(0xCF6C, create))!;
        Check(BinaryPrimitives.ReadUInt32LittleEndian(created.AsSpan(16)) == 0
            && created.AsSpan(20, 24).ToArray().All(value => value == 0),
            "a game without a registered record creates GAME INFO zero with no invented holder");
        var rooms = (IDictionary)typeof(NetworkAdapterService).GetField("_entertainmentRooms", PrivateInstance)!.GetValue(f.Service)!;
        var room = rooms[Get(host, "EntertainmentRoomId")!]!;
        var waiting = await Send(0xCF6E, []);
        Check(waiting is { Length: 88 } && BinaryPrimitives.ReadUInt16LittleEndian(waiting.AsSpan(32)) == 1500,
            "CF6F publishes the actual target score, not the character level: " + (waiting is null ? "null" : Convert.ToHexString(waiting)));
        await Send(0xCFE5, []);
        Check(await Send(0xD005, [10, 0, 1, 0]) is null, "preload combo cannot score or grant a card");
        await Send(0xCF7F, []);
        var scores = (IDictionary)Get(room, "ScoresBySession")!;
        var cards = (IList)((IDictionary)Get(room, "RewardCardsBySession")!)[Id(host)]!;
        for (byte combo = 1; combo <= 14; combo++)
            Check(await Send(0xD005, [10, 0, combo, 0]) is not null, "sequential combo progression accepted");
        Check((uint)scores[Id(host)]! == 1400 && cards.Count == 0,
            "actual score uses point values, not the fourteen successful selections");
        Check(await Send(0xD005, [10, 0, 14, 0]) is null
            && await Send(0xD005, [10, 0, 16, 0]) is null
            && (uint)scores[Id(host)]! == 1400, "duplicate and skipped combos cannot grant score");
        await Send(0xD005, [10, 0, 15, 0]);
        Check((uint)scores[Id(host)]! == 1500 && cards.Count == 1, "exact target crossing awards one basic card");
        var notifications = ((IList)Get(host, "PendingSessionBroadcasts")!).Cast<object>().Where(item =>
            (ushort)Get(item, "Opcode")! == 0xD008).ToArray();
        var scoreFrame = (byte[])Get(notifications[^1], "Payload")!;
        Check(scoreFrame.Length == 12 && BinaryPrimitives.ReadUInt16LittleEndian(scoreFrame.AsSpan(4)) == 1500,
            "request-driven D008 carries actual score separately from D006 combo");
        Check(await Send(0xD005, [20, 0, 0, 0]) is not null && (uint)scores[Id(host)]! == 1500,
            "combo reset preserves score and rewards");
        Check(await Send(0xD005, [20, 0, 0, 0]) is null, "duplicate combo reset is rejected");
        await Send(0xD005, [10, 0, 1, 0]);
        var spoof = new byte[4];
        BinaryPrimitives.WriteUInt16LittleEndian(spoof, WireIdentityAllocator.GetSceneEntityId(Character(host).Id));
        BinaryPrimitives.WriteUInt16LittleEndian(spoof.AsSpan(2), 27);
        Check(await Send(0xCF83, spoof) is null && (uint)scores[Id(host)]! == 1600,
            "unproven auxiliary value cannot overwrite actual score with a counter");
        Set(room, "LuckyPoints", (ushort)900);
        var lucky = await Send(0xD007, [0, 2, 2, 10]);
        Check(lucky is not null && BinaryPrimitives.ReadUInt16LittleEndian(lucky.AsSpan(12)) == 2812
            && BinaryPrimitives.ReadUInt16LittleEndian(lucky.AsSpan(14)) == 112 && cards.Count == 2,
            "lucky crossing awards a basic card independently of target thresholds");
        Check(await Send(0xD007, [0, 2, 2, 10]) is null && cards.Count == 2,
            "completed board retry cannot duplicate score or either award");
        await Send(0xD007, [1, 2, 2, 10]);
        Set(room, "LuckyPoints", (ushort)900);
        await Send(0xD007, [2, 2, 2, 10]);
        Check((uint)scores[Id(host)]! == 4236 && cards.Count == 4,
            "a second lucky crossing and a second target each grant one card");
        await Send(0xD007, [3, 3, 3, 0]);
        Check((uint)scores[Id(host)]! == 4558 && cards.Count == 5,
            "third target crossing retains all five prizes beyond preview capacity");
        var prizes = cards.Cast<uint>().ToArray();
        Check(prizes.All(EntertainmentRewardPolicy.IsBasicCard), "all earned prizes use the native basic preview domain");
        Set(room, "StartedUtc", DateTime.UtcNow.AddSeconds(-105));
        InvokeMentorship<object>(f.Service, "CollectEntertainmentDeadlines", DateTime.UtcNow);
        var result = await Send(0xCF85, []);
        Check(result is { Length: 80 } && BinaryPrimitives.ReadUInt32LittleEndian(result.AsSpan(24)) == 4558
            && Enumerable.Range(0, 3).All(i => BinaryPrimitives.ReadUInt32LittleEndian(result.AsSpan(56 + 4 * i)) == prizes[i]),
            "CF86 freezes actual score and the first three native basic preview identities");
        Check(await f.ScalarAsync("SELECT COUNT(*) FROM EntertainmentCardReceipts") == 5
            && await f.ScalarAsync("SELECT SUM(Quantity) FROM CharacterCards") == 5,
            "all five prize receipts and inventory grants commit together");
        Check(await f.ScalarAsync("SELECT SUM(PetExperience) FROM ActivityRewardReceipts") == soloPetReward,
            "single-player settlement receives the ten-percent pet award");
        lobby = await Send(0xCF0B, []);
        Check(BinaryPrimitives.ReadUInt32LittleEndian(lobby!.AsSpan(16)) == 4558
            && await f.Database.GetEntertainmentBestScoreAsync(Character(host).Id, 1) == 4558
            && await f.Database.GetEntertainmentBestScoreAsync(Character(host).Id, 2) == 0,
            "lobby personal record uses the committed point score and isolates game types");
        await Send(0xCF85, []);
        Check(await f.ScalarAsync("SELECT COUNT(*) FROM EntertainmentCardReceipts") == 5
            && await f.ScalarAsync("SELECT SUM(Quantity) FROM CharacterCards") == 5,
            "result retry cannot duplicate a basic card grant");
        Check(await Send(0xD005, [10, 0, 2, 0]) is null && await Send(0xD007, [4, 2, 2, 10]) is null,
            "frozen round rejects further scoring and rewards");
        await Send(0xCFE5, []);
        Check((uint)scores[Id(host)]! == 0 && ((IList)((IDictionary)Get(room, "RewardCardsBySession")!)[Id(host)]!).Count == 0
            && (ushort)((IDictionary)Get(room, "CombosBySession")!)[Id(host)]! == 0,
            "new round resets scores, combos, target awards and prizes");
        var nextCards = (IList)((IDictionary)Get(room, "RewardCardsBySession")!)[Id(host)]!;
        void AddScore(uint amount) => typeof(NetworkAdapterService).GetMethod("AddEntertainmentScoreLocked",
            BindingFlags.Static | BindingFlags.NonPublic)!.Invoke(null, [room, host, amount]);
        AddScore(6000u);
        Check(nextCards.Count == 4, "one large score increment grants every crossed target");
        AddScore(uint.MaxValue);
        var capCount = nextCards.Count;
        AddScore(100u);
        Check((uint)scores[Id(host)]! == ushort.MaxValue && capCount == 43 && nextCards.Count == capCount,
            "score saturation is overflow safe and cannot repeat a threshold grant");

        var recreated = (await Send(0xCF6C, create))!;
        Check(BinaryPrimitives.ReadUInt32LittleEndian(recreated.AsSpan(16)) == 4558
            && Encoding.ASCII.GetString(recreated, 20, 7) == "Teacher",
            "recreated GAME INFO reads the saved actual score rather than a round's selection count or UID");
        Set(host, "ArenaGameType", (byte)2);
        var unplayedGame = (await Send(0xCF6C, create))!;
        Check(BinaryPrimitives.ReadUInt32LittleEndian(unplayedGame.AsSpan(16)) == 0
            && unplayedGame.AsSpan(20, 24).ToArray().All(value => value == 0),
            "GAME INFO highest record isolates an unplayed entertainment type");
        Set(host, "ArenaGameType", (byte)1);

        var actor = Actor(f.Teacher);
        async Task<CharacterRecord?> Grant(string key, uint[] grantCards, int score = 1000,
            int memberCount = 1, int place = 0) => await f.Database.ApplyDungeonRewardAsync(
            actor.AccountId, actor.CharacterId, actor.SessionId, 0, 0, 0, 0, score, 0, 0, 0, 0,
            completed: false, activitySettlementKey: key, entertainmentCards: grantCards,
            entertainmentGameType: 1, entertainmentPlace: place, entertainmentMemberCount: memberCount,
            entertainmentSuccessfulBoards: 3);
        foreach (var memberCount in new[] { int.MinValue, -1, 0, 7, int.MaxValue })
            Check(await Grant("entertainment:invalid-population", [], memberCount: memberCount) is null,
                "database rejects invalid entertainment population " + memberCount);
        for (var memberCount = 1; memberCount <= 6; memberCount++)
            foreach (var place in new[] { -1, memberCount })
                Check(await Grant("entertainment:invalid-placement", [], memberCount: memberCount, place: place) is null,
                    "database rejects out-of-room entertainment placement " + memberCount + "/" + place);
        Check(await f.ScalarAsync("SELECT COUNT(*) FROM ActivityRewardReceipts") == 1,
            "invalid entertainment population and placement cannot commit an activity receipt");
        Check(await Grant("entertainment:invalid", [22000011]) is null
            && await Grant("entertainment:invalid", [50000001]) is null,
            "database rejects lucky and event rewards without committing an activity receipt");
        foreach (var code in Enumerable.Range(13000201, 10).Concat(Enumerable.Range(13000411, 10)))
            Check(await Grant("entertainment:dust", [(uint)code], 9000) is null,
                "gold-powder entertainment grant rolls back " + code);
        Check(await f.Database.GetEntertainmentBestScoreAsync(actor.CharacterId, 1) == 4558,
            "rejected card reward cannot commit a higher personal record");
        await f.ExecuteAsync("CREATE TRIGGER fail_entertainment_card BEFORE INSERT ON EntertainmentCardReceipts WHEN NEW.Sequence = 1 BEGIN SELECT RAISE(ABORT, 'injected card failure'); END");
        var failed = false;
        try { await Grant("entertainment:rollback", [13000001, 13000001], 9000); }
        catch (SqliteException) { failed = true; }
        Check(failed && await f.ScalarAsync("SELECT COUNT(*) FROM EntertainmentCardReceipts") == 5
            && await f.ScalarAsync("SELECT COUNT(*) FROM ActivityRewardReceipts") == 1,
            "mid-grant failure rolls back cards, pet reward and settlement receipt");
        Check(await f.Database.GetEntertainmentBestScoreAsync(actor.CharacterId, 1) == 4558,
            "mid-grant failure also rolls back the higher personal record");
        await f.ExecuteAsync("DROP TRIGGER fail_entertainment_card");
        await Grant("entertainment:rollback", [13000001, 13000001]);
        await Grant("entertainment:rollback", [13000001, 13000001]);
        Check(await f.ScalarAsync("SELECT SUM(Quantity) FROM CharacterCards") == 7
            && await f.ScalarAsync("SELECT COUNT(*) FROM EntertainmentCardReceipts") == 7,
            "duplicate random card identities each grant one copy and retry is idempotent");
        await f.ExecuteAsync("INSERT INTO EntertainmentLuckyCardReceipts VALUES(" + actor.CharacterId
            + ", 'historical', 0, 22000011, 'before')");
        Check(await f.Database.GetEntertainmentBestScoreAsync(actor.CharacterId, 1) == 4558,
            "lower scores preserve the best entertainment result");
        await Grant("entertainment:new-best", [], 8000);
        await Grant("entertainment:new-best", [], 60000);
        Check(await f.Database.GetEntertainmentBestScoreAsync(actor.CharacterId, 1) == 8000
            && await f.Database.GetEntertainmentBestScoreAsync(Character(f.Student).Id, 1) == 0,
            "new higher record commits once and cannot leak across characters or change on receipt retry");
        var reopened = new DatabaseService(f.Root);
        await reopened.InitializeAsync();
        Check(await f.ScalarAsync("SELECT COUNT(*) FROM EntertainmentLuckyCardReceipts") == 1
            && await f.ScalarAsync("SELECT COUNT(*) FROM EntertainmentCardReceipts") == 7,
            "database reopen preserves historical lucky receipts and new basic receipts");
        Check(await reopened.GetEntertainmentBestScoreAsync(actor.CharacterId, 1) == 8000,
            "database reopen preserves the best entertainment result");
        await f.ExecuteAsync("INSERT INTO CharacterCards(CharacterId,CardCode,Quantity,UpdatedAt) VALUES($id,13000201,2,'historical')", ("$id", actor.CharacterId));
        await reopened.InitializeAsync();
        Check(await f.ScalarAsync("SELECT Quantity FROM CharacterCards WHERE CardCode=13000201") == 2,
            "pool exclusion does not remove historically owned gold-powder cards");
    }

    private static async Task CheckEntertainmentRoomRewardsAsync()
    {
        Check(ShopCatalog.TryGetPetGrowthStage(2, 1, out var stageOne) && stageOne.ExperiencePerLevel == 6480
            && ShopCatalog.TryGetPetGrowthStage(2, 2, out var stageTwo) && stageTwo.ExperiencePerLevel == 8640,
            "wire pet stage directly selects the zero-based client growth row");
        var observedPet = new PetState(15000017, 1, 2, 0, 0, 0, 0, 0, -1);
        Check(EntertainmentRewardPolicy.GetPetExperience(observedPet, 0, 1) == 648
            && PetProgression.GetNativeClearReward(observedPet) == 648,
            "class-two stage-one clear grants ten percent of the client 6480 denominator, not 324");
        uint[][] percentages = [[10], [13, 10], [16, 13, 10], [19, 16, 13, 10],
            [22, 19, 16, 13, 10], [25, 22, 19, 16, 13, 10]];
        for (var memberCount = 1; memberCount <= 6; memberCount++)
        {
            Check(Enumerable.Range(0, memberCount)
                .Select(place => EntertainmentRewardPolicy.GetPetRewardPercent(place, memberCount))
                .SequenceEqual(percentages[memberCount - 1]), "pet reward percentages for population " + memberCount);
            Check(EntertainmentRewardPolicy.GetPetRewardPercent(-1, memberCount) == 0
                && EntertainmentRewardPolicy.GetPetRewardPercent(memberCount, memberCount) == 0,
                "out-of-room placements receive no experience " + memberCount);
        }
        foreach (var memberCount in new[] { int.MinValue, -1, 0, 7, int.MaxValue })
            Check(EntertainmentRewardPolicy.GetPetRewardPercent(0, memberCount) == 0,
                "invalid room population receives no experience " + memberCount);
        Check(EntertainmentRewardPolicy.GetPetExperience(default, 0, 1) == 0, "missing pet receives no experience");
        foreach (var pet in ShopCatalog.All.Where(item => item.Category == 15))
        for (byte stage = 1; stage <= 3; stage++)
        {
            var state = PetProgression.NormalizeState(new PetState(pet.ItemCode, stage, 3, 0, 0, 0, 0, 0, -1));
            if (!ShopCatalog.TryGetPetGrowthStage(pet.PetGrowthClass, state.CurrentStage, out var growth)) continue;
            for (var memberCount = 1; memberCount <= 6; memberCount++)
            for (var place = 0; place < memberCount; place++)
                Check(EntertainmentRewardPolicy.GetPetExperience(state, place, memberCount)
                    == (ulong)growth.ExperiencePerLevel * percentages[memberCount - 1][place] / 100,
                    "stage-based pet reward " + pet.ItemCode + "/" + state.CurrentStage + "/" + memberCount + "/" + place);
        }

        for (var memberCount = 1; memberCount <= 6; memberCount++)
            await CheckEntertainmentRoomRewardsAsync(memberCount);
    }

    private static async Task CheckEntertainmentPetBoardGateAsync()
    {
        await using var f = await Fixture.CreateAsync();
        foreach (var world in new[] { f.Teacher, f.Student })
        {
            await f.ExecuteAsync("UPDATE Characters SET PetVariant=1,EquippedPetItemCode=15000017,PetLevel=0,PetExperience=0 WHERE Id=$id; "
                + "INSERT INTO CharacterItems(CharacterId,ItemCode,Quantity,PetCurrentStage,PetMaximumStage,PetLevel,PetExperience,UpdatedAt) "
                + "VALUES($id,15000017,1,1,2,0,0,'test') ON CONFLICT(CharacterId,ItemCode) DO UPDATE SET "
                + "Quantity=1,PetCurrentStage=1,PetMaximumStage=2,PetLevel=0,PetExperience=0", ("$id", Character(world).Id));
            Set(world, "Character", (await f.Database.GetCharacterByIdAsync(Character(world).Id))!);
        }
        object Auxiliary(object world)
        {
            var member = Activator.CreateInstance(SessionType, nonPublic: true)!;
            foreach (var property in new[] { "AccountId", "Username", "Character", "ChannelId", "RemoteIp" })
                Set(member, property, Get(world, property));
            Set(member, "OnlineTracked", true);
            Set(member, "AuxiliaryGameSession", true);
            Set(member, "ArenaGameType", (byte)1);
            return member;
        }
        var host = Auxiliary(f.Teacher);
        Task<byte[]?> Send(object member, ushort opcode, byte[] data) => Dispatch(f, member, opcode, data, "ArenaAdapter");
        var create = new byte[44]; Encoding.ASCII.GetBytes("Board gate").CopyTo(create, 0);
        BinaryPrimitives.WriteUInt16LittleEndian(create.AsSpan(24), 100);
        await Send(host, 0xCF6C, create);
        var rooms = (IDictionary)typeof(NetworkAdapterService).GetField("_entertainmentRooms", PrivateInstance)!.GetValue(f.Service)!;
        var room = rooms[Get(host, "EntertainmentRoomId")!]!;
        var successCounts = new[] { 0, 0, 0, 1, 2, 3, 4, 0 };
        for (var scenario = 0; scenario < successCounts.Length; scenario++)
        {
            var before = (await f.Database.GetCharacterByIdAsync(Character(host).Id))!;
            var petBefore = PetProgression.GetState(before, before.EquippedPetItemCode);
            Check(await Send(host, 0xCFE5, []) is not null, "board gate starts a fresh round " + scenario);
            Check(((IDictionary)Get(room, "SuccessfulBoardsBySession")!).Count == 0,
                "successful-board eligibility resets at the round boundary " + scenario);
            Check(await Send(host, 0xD007, [0, 1, 1, 22]) is null,
                "preload completion cannot unlock pet experience " + scenario);
            await Send(host, 0xCF7F, []);
            for (byte board = 0; board < successCounts[scenario]; board++)
                Check(await Send(host, 0xD007, [board, 1, 1, 22]) is not null, "distinct successful board accepted " + scenario + "/" + board);
            if (scenario == 1)
                Check(await Send(host, 0xD007, [0, 0, 0, 22]) is not null, "zero-type completion is not a successful board");
            if (scenario == 2)
                Check(await Send(host, 0xD007, [0, 2, 1, 22]) is not null, "mismatched completion types do not count as success");
            if (scenario == 4)
            {
                Check(await Send(host, 0xD007, [1, 1, 1, 22]) is null, "duplicate success cannot make two boards into three");
                Check(await Send(host, 0xD007, [2, 1, 0, 22]) is not null, "timeout board report remains valid but ineligible");
                Check(await Send(host, 0xD007, [2, 1, 1, 22]) is null, "failed board retry cannot be relabelled as success");
            }
            if (scenario == 7)
                for (byte combo = 1; combo <= 15; combo++)
                    Check(await Send(host, 0xD005, [10, 0, combo, 0]) is not null, "hits can score without completing a board " + combo);
            var successes = (IDictionary)Get(room, "SuccessfulBoardsBySession")!;
            Check((successes.Contains(Id(host)) ? (int)successes[Id(host)]! : 0) == successCounts[scenario],
                "only distinct nonzero matching completion reports count " + scenario);
            foreach (var lives in new uint[] { 2, 1, 0 })
            {
                var report = new byte[4]; BinaryPrimitives.WriteUInt32LittleEndian(report, lives);
                Check(await Send(host, 0xD003, report) is not null, "miss consumes a chance without completing a board " + scenario + "/" + lives);
            }
            InvokeMentorship<object>(f.Service, "CollectEntertainmentDeadlines", DateTime.UtcNow);
            Check(await Send(host, 0xD007, [5, 1, 1, 22]) is null, "late completion cannot alter frozen eligibility " + scenario);
            var result = await Send(host, 0xCF85, []);
            Check(result is { Length: 80 }, "ineligible rounds still return a complete result " + scenario);
            var reward = successCounts[scenario] >= 3 ? EntertainmentRewardPolicy.GetPetExperience(petBefore, 0, 1) : 0;
            Check(reward == (successCounts[scenario] >= 3 ? 648u : 0u),
                "observed solo pet receives a literal ten-percent reward only after three boards " + scenario);
            var expected = PetProgression.AddExperience(petBefore, reward).State;
            var saved = (await f.Database.GetCharacterByIdAsync(before.Id))!;
            Check(PetProgression.GetState(saved, saved.EquippedPetItemCode) == expected
                && BinaryPrimitives.ReadUInt32LittleEndian(result!.AsSpan(44)) == expected.Experience,
                "three-board threshold controls persisted pet and result experience " + scenario);
            Check(await f.ScalarAsync("SELECT PetExperience FROM ActivityRewardReceipts WHERE CharacterId=" + before.Id + " ORDER BY rowid DESC LIMIT 1") == reward,
                "settlement receipt records the gated reward " + scenario);
            Check((await Send(host, 0xCF85, []))!.AsSpan(8).SequenceEqual(result!.AsSpan(8)),
                "result retry preserves zero or granted pet reward " + scenario);
            Check(await f.ScalarAsync("SELECT COUNT(*) FROM ActivityRewardReceipts") == scenario + 1,
                "eligibility does not bypass settlement idempotency " + scenario);
        }
        Check(await f.ScalarAsync("SELECT SUM(Quantity) FROM CharacterCards") >= 1,
            "scoring card rewards remain independent of the pet completion gate");

        var actor = Actor(f.Teacher);
        var unchanged = (await f.Database.GetCharacterByIdAsync(actor.CharacterId))!;
        Check(await f.Database.ApplyDungeonRewardAsync(actor.AccountId, actor.CharacterId, actor.SessionId,
            0, 0, 0, 0, 0, 0, 0, 9999, 0, completed: false,
            activitySettlementKey: "entertainment:no-completion", entertainmentGameType: 1) is not null,
            "database omission of completion proof defaults to a zero pet award");
        var noProof = (await f.Database.GetCharacterByIdAsync(actor.CharacterId))!;
        Check(PetProgression.GetState(noProof, noProof.EquippedPetItemCode)
            == PetProgression.GetState(unchanged, unchanged.EquippedPetItemCode),
            "caller-supplied pet reward cannot bypass the database completion gate");

        var guest = Auxiliary(f.Student);
        BinaryPrimitives.WriteUInt16LittleEndian(create.AsSpan(24), 200);
        await Send(host, 0xCF6C, create);
        room = rooms[Get(host, "EntertainmentRoomId")!]!;
        var enter = new byte[12]; BinaryPrimitives.WriteUInt16LittleEndian(enter, 20);
        BinaryPrimitives.WriteUInt16LittleEndian(enter.AsSpan(2), checked((ushort)(int)Get(host, "EntertainmentRoomId")!));
        await Send(guest, 0xCF75, enter); Set(guest, "EntertainmentReady", true);
        await Send(host, 0xCFE5, []); await Send(host, 0xCF7F, []); await Send(guest, 0xCF7F, []);
        var guestBefore = (await f.Database.GetCharacterByIdAsync(Character(guest).Id))!;
        for (byte combo = 1; combo <= 15; combo++) await Send(host, 0xD005, [10, 0, combo, 0]);
        for (byte board = 0; board < 3; board++) await Send(guest, 0xD007, [board, 1, 1, 22]);
        await Send(host, 0xD003, new byte[4]); await Send(guest, 0xD003, new byte[4]);
        InvokeMentorship<object>(f.Service, "CollectEntertainmentDeadlines", DateTime.UtcNow);
        var mixed = await Send(host, 0xCF85, []);
        Check(mixed is { Length: 144 } && BinaryPrimitives.ReadUInt16LittleEndian(mixed.AsSpan(16)) == Character(host).Id,
            "ineligible high scorer retains original rank and room population");
        Check(await f.ScalarAsync("SELECT PetExperience FROM ActivityRewardReceipts WHERE CharacterId=" + actor.CharacterId + " ORDER BY rowid DESC LIMIT 1") == 0,
            "another member's three successful boards cannot qualify the first-place member");
        Check(await f.ScalarAsync("SELECT PetExperience FROM ActivityRewardReceipts WHERE CharacterId=" + guestBefore.Id + " ORDER BY rowid DESC LIMIT 1")
            == EntertainmentRewardPolicy.GetPetExperience(PetProgression.GetState(guestBefore, guestBefore.EquippedPetItemCode), 1, 2),
            "qualified second place retains the original two-player ten-percent award");
    }

    private static async Task CheckEntertainmentRoomRewardsAsync(int memberCount)
    {
        await using var f = await Fixture.CreateAsync();
        var members = new List<object>();
        var expectedPetRewards = new List<uint>();
        var expectedPetStates = new List<PetState>();
        for (var place = 0; place < memberCount; place++)
        {
            var world = await f.CreateSessionAsync("entertainment-six-" + place, "Enter" + place, 25, 1);
            var petCode = 15000001u;
            ShopCatalog.TryGet(15, petCode, out var pet);
            byte stage = place % 2 == 0 ? (byte)1 : (byte)2;
            ShopCatalog.TryGetPetGrowthStage(pet.PetGrowthClass, stage, out var growth);
            var experience = growth.ExperiencePerLevel - 1;
            var level = place == 0 ? growth.MaximumLevel - 1 : 0;
            await f.ExecuteAsync("UPDATE Characters SET PetVariant=1,EquippedPetItemCode=$pet,PetLevel=$level,PetExperience=$exp WHERE Id=$id; "
                + "INSERT INTO CharacterItems(CharacterId,ItemCode,Quantity,PetCurrentStage,PetMaximumStage,PetLevel,PetExperience,UpdatedAt) "
                + "VALUES($id,$pet,1,$stage,2,$level,$exp,'test') ON CONFLICT(CharacterId,ItemCode) DO UPDATE SET "
                + "Quantity=1,PetCurrentStage=$stage,PetMaximumStage=2,PetLevel=$level,PetExperience=$exp",
                ("$id", Character(world).Id), ("$pet", petCode), ("$stage", stage), ("$level", level), ("$exp", experience));
            Set(world, "Character", (await f.Database.GetCharacterByIdAsync(Character(world).Id))!);
            var state = PetProgression.GetState(Character(world), petCode);
            var reward = EntertainmentRewardPolicy.GetPetExperience(state, place, memberCount);
            expectedPetRewards.Add(reward);
            expectedPetStates.Add(PetProgression.AddExperience(state, reward).State);
            var auxiliary = Activator.CreateInstance(SessionType, nonPublic: true)!;
            foreach (var property in new[] { "AccountId", "Username", "Character", "ChannelId", "RemoteIp" })
                Set(auxiliary, property, Get(world, property));
            Set(auxiliary, "OnlineTracked", true); Set(auxiliary, "AuxiliaryGameSession", true); Set(auxiliary, "ArenaGameType", (byte)1);
            members.Add(auxiliary);
        }
        Task<byte[]?> Send(object member, ushort opcode, byte[] data) => Dispatch(f, member, opcode, data, "ArenaAdapter");
        var create = new byte[44]; Encoding.ASCII.GetBytes("Six places").CopyTo(create, 0);
        BinaryPrimitives.WriteUInt16LittleEndian(create.AsSpan(24), 200);
        BinaryPrimitives.WriteUInt16LittleEndian(create.AsSpan(30), 3);
        var host = members[0];
        await Send(host, 0xCF6C, create);
        var roomId = checked((ushort)(int)Get(host, "EntertainmentRoomId")!);
        for (var place = 0; place < memberCount; place++)
        {
            if (place > 0)
            {
                var enter = new byte[12]; BinaryPrimitives.WriteUInt16LittleEndian(enter, 20);
                BinaryPrimitives.WriteUInt16LittleEndian(enter.AsSpan(2), roomId);
                Check((await Send(members[place], 0xCF75, enter))![8] == 10, "ranked room accepts member " + place);
                Set(members[place], "EntertainmentReady", true);
            }
            var listing = await Send(host, 0xCF0F, [0, 0, 100, 100]);
            Check(listing is { Length: 52 } && BinaryPrimitives.ReadUInt16LittleEndian(listing.AsSpan(38)) == place + 1,
                "CF10 publishes actual population instead of selected difficulty " + (place + 1));
        }
        await Send(host, 0xCFE5, []);
        foreach (var member in members) await Send(member, 0xCF7F, []);
        var rooms = (IDictionary)typeof(NetworkAdapterService).GetField("_entertainmentRooms", PrivateInstance)!.GetValue(f.Service)!;
        var room = rooms[(int)roomId]!;
        var scores = new uint[] { 4000, 3000, 2000, 1000, 900, 800 };
        for (var place = 0; place < memberCount; place++)
        {
            Set(room, "LuckyPoints", (ushort)0);
            for (byte board = 0; board < 3; board++)
                Check(await Send(members[place], 0xD007, [board, 1, 1, 22]) is not null,
                    "ranked member clears the required board " + place + "/" + board);
            typeof(NetworkAdapterService).GetMethod("AddEntertainmentScoreLocked", BindingFlags.Static | BindingFlags.NonPublic)!
                .Invoke(null, [room, members[place], scores[place] - 300]);
        }
        Set(room, "StartedUtc", DateTime.UtcNow.AddSeconds(-105));
        InvokeMentorship<object>(f.Service, "CollectEntertainmentDeadlines", DateTime.UtcNow);
        // A changed persisted stage must outrank the auxiliary connection's stale pet snapshot.
        if (memberCount >= 5)
        {
            var changedId = Character(members[4]).Id;
            await f.ExecuteAsync("UPDATE CharacterItems SET PetCurrentStage=2,PetLevel=0,PetExperience=0 WHERE CharacterId=$id AND ItemCode=15000001", ("$id", changedId));
            var changedPet = PetProgression.GetState((await f.Database.GetCharacterByIdAsync(changedId))!, 15000001);
            expectedPetRewards[4] = EntertainmentRewardPolicy.GetPetExperience(changedPet, 4, memberCount);
            expectedPetStates[4] = PetProgression.AddExperience(changedPet, expectedPetRewards[4]).State;
        }
        var result = await Send(host, 0xCF85, []);
        Check(result?.Length == 16 + 64 * memberCount, "frozen result rows have complete field coverage " + memberCount);
        for (var place = 0; place < memberCount; place++)
        {
            var saved = (await f.Database.GetCharacterByIdAsync(Character(members[place]).Id))!;
            var expected = expectedPetStates[place];
            var pet = PetProgression.GetState(saved, saved.EquippedPetItemCode);
            Check(pet == expected && BinaryPrimitives.ReadUInt32LittleEndian(result!.AsSpan(16 + 64 * place + 28)) == expected.Experience,
                "ranked award grows the persisted pet and CF86 carrier " + place);
            Check(await f.ScalarAsync("SELECT PetExperience FROM ActivityRewardReceipts WHERE CharacterId=" + saved.Id) == expectedPetRewards[place],
                "receipt records the stage percentage amount " + place);
            Check(await f.Database.GetEntertainmentBestScoreAsync(saved.Id, 1) == scores[place], "personal best belongs to member " + place);
            Check((await Send(members[place], 0xCF85, []))!.AsSpan(8).SequenceEqual(result!.AsSpan(8)), "result retry preserves rank and rewards " + place);
        }
        Check(expectedPetStates[0].CurrentStage == 2 && await f.ScalarAsync("SELECT COUNT(*) FROM ActivityRewardReceipts") == memberCount,
            "stage rollover and ranked settlement remain single-commit " + memberCount);
        if (memberCount > 1)
        {
            await Send(members[^1], 0xCF73, []);
            var afterLeave = await Send(host, 0xCF0F, [0, 0, 100, 100]);
            Check(BinaryPrimitives.ReadUInt16LittleEndian(afterLeave!.AsSpan(38)) == memberCount - 1,
                "leaving removes one actual displayed member " + memberCount);
        }
    }
}
