using System.Buffers.Binary;
using Microsoft.Data.Sqlite;
using OpenNanaimo.Adapter.Services;

internal static partial class Program
{
    private static void Put(NativeDungeonState state, int offset, uint value)
        => BinaryPrimitives.WriteUInt32LittleEndian(state.Bytes.AsSpan(offset, 4), value);

    private static async Task<(NativeDungeonState Before, NativeDungeonState After)> NativePair(
        Fixture f, Actor actor, uint hans = 0, uint cash = 0)
    {
        var character = (await f.Database.GetCharacterByIdAsync(actor.CharacterId))!;
        var before = NativeDungeonState.Create(character, [], []);
        await f.Database.RestoreNativeDungeonProgressAsync(actor.CharacterId, before, CancellationToken.None);
        var after = new NativeDungeonState(before.Bytes.ToArray());
        BinaryPrimitives.WriteUInt64LittleEndian(after.Bytes.AsSpan(32, 8), checked((ulong)before.GetBalance(32)) + hans);
        BinaryPrimitives.WriteUInt64LittleEndian(after.Bytes.AsSpan(40, 8), checked((ulong)before.GetBalance(40)) + cash);
        return (before, after);
    }

    private static Task<NativeDungeonApplyResult> ApplyProduction(
        Fixture f, Actor actor, (NativeDungeonState Before, NativeDungeonState After) state,
        NativeDungeonSettlementRecord result, string? commit = null, bool recovering = false,
        DatabaseService? database = null)
        => (database ?? f.Database).ApplyNativeDungeonDeltaAsync(actor.AccountId, actor.CharacterId,
            actor.SessionId, state.Before, state.After, CancellationToken.None,
            commit ?? Guid.NewGuid().ToString("N"), recovering, result);

    private static async Task SeedProductionProgress(Fixture f, Actor actor)
    {
        await f.Update("""
            INSERT INTO DungeonProgress(CharacterId,Episode,Difficulty,ClearMask,BestRatings,BestScore,ClearedAt,UpdatedAt)
                VALUES($id,3,0,8,192,321,'2026-10-11T00:00:00Z','2026-10-11T00:00:00Z');
            INSERT INTO DungeonTitleMilestones(CharacterId,Grade,HdIndex,Episode,Dungeon,Difficulty,Stage,ClearedAt,UpdatedAt)
                VALUES($id,4,0,3,2,0,1,'2026-10-11T00:00:00Z','2026-10-11T00:00:00Z');
            CREATE TABLE IF NOT EXISTS NativeCardProfileArchives(
                CharacterId INTEGER NOT NULL, Sha256 TEXT NOT NULL, State BLOB NOT NULL, ArchivedAt TEXT NOT NULL,
                PRIMARY KEY(CharacterId,Sha256));
            INSERT INTO NativeCardProfileArchives VALUES($id,'fixture',X'01020304','fixture');
            """, actor.CharacterId);
        var character = (await f.Database.GetCharacterByIdAsync(actor.CharacterId))!;
        var state = NativeDungeonState.Create(character, [], []);
        foreach (var field in new[] { (5024, 39u), (5028, 1u), (5032, 0u),
            (5036, 3u), (5040, 2u), (5044, 0u), (5048, 1u) }) Put(state, field.Item1, field.Item2);
        await using var connection = await f.Open();
        await using var tx = connection.BeginTransaction();
        await using var command = connection.CreateCommand();
        command.Transaction = tx;
        command.CommandText = """
            CREATE TABLE IF NOT EXISTS NativeDungeonProfiles(CharacterId INTEGER PRIMARY KEY REFERENCES Characters(Id),State BLOB NOT NULL);
            INSERT INTO NativeDungeonProfiles VALUES($id,$state)
                ON CONFLICT(CharacterId) DO UPDATE SET State=excluded.State;
            """;
        command.Parameters.AddWithValue("$id", actor.CharacterId);
        command.Parameters.AddWithValue("$state", state.Bytes);
        await command.ExecuteNonQueryAsync();
        await tx.CommitAsync();
    }

    private static async Task<string> ProtectedProductionState(Fixture f, Actor actor)
    {
        var state = await NativePair(f, actor);
        var progress = await f.Scalar("""
            SELECT group_concat(Episode||':'||Difficulty||':'||ClearMask||':'||BestRatings||':'||BestScore||':'||ClearedAt)
            FROM (SELECT * FROM DungeonProgress WHERE CharacterId=$id ORDER BY Episode,Difficulty)
            """, actor.CharacterId);
        var titles = await f.Scalar("""
            SELECT group_concat(Grade||':'||HdIndex||':'||Episode||':'||Dungeon||':'||Difficulty||':'||Stage||':'||ClearedAt||':'||UpdatedAt)
            FROM (SELECT * FROM DungeonTitleMilestones WHERE CharacterId=$id ORDER BY Grade)
            """, actor.CharacterId);
        var archive = await f.Scalar("""
            SELECT group_concat(Sha256||':'||hex(State)||':'||ArchivedAt)
            FROM (SELECT * FROM NativeCardProfileArchives WHERE CharacterId=$id ORDER BY Sha256)
            """, actor.CharacterId);
        var records = await f.Database.GetDungeonProgressAdminAsync(actor.CharacterId);
        var archiveView = records.Select(r => new { r.Episode, r.Dungeon, r.IsSuperBoss,
            r.ClearMask, r.BestRatings, r.BestScore, r.BestElapsedMinutes }).ToArray();
        return $"{progress}|{titles}|{archive}|{System.Text.Json.JsonSerializer.Serialize(archiveView)}|"
            + Convert.ToHexString(state.Before.Bytes.AsSpan(5024, 28)) + "|"
            + Convert.ToHexString(state.Before.Bytes.AsSpan(5052, 60));
    }

    private static async Task CheckProductionSettlements(Fixture f)
    {
        var actor = await f.Actor("MonkProduction");
        await SeedProductionProgress(f, actor);
        var protectedState = await ProtectedProductionState(f, actor);
        var state = await NativePair(f, actor, 7, 3);
        var result = Result() with { CharacterExperienceAward = 25, StageRecordScore = 100 };
        var commit = Guid.NewGuid().ToString("N");
        Check((await ApplyProduction(f, actor, state, result, commit)).Applied,
            "production settlement commits a successful challenge");
        var saved = (await f.Database.GetCharacterByIdAsync(actor.CharacterId))!;
        Check(saved.Hans == 7 && saved.Cash == 3 && saved.Experience == 25 && saved.DungeonGrade == 39,
            "production currency and EXP commit with the unchanged title grade");
        Check((await f.Database.GetMonkChallengeClearMaskAsync(actor.AccountId, actor.CharacterId)).ClearMask == 1
            && await f.ReceiptCount(actor.CharacterId) == 1
            && (long)(await f.Scalar("SELECT COUNT(*) FROM NativeDungeonSettlements WHERE CharacterId=$id", actor.CharacterId))! == 1,
            "production settlement and challenge receipts commit together");
        Check(protectedState == await ProtectedProductionState(f, actor),
            "production challenge preserves main-story masks, milestones, frontier and archived profiles");
        Check(!(await ApplyProduction(f, actor, state, result, commit)).Applied,
            "duplicate production snapshot commit is a complete no-op");
        Check((await ApplyProduction(f, actor, await NativePair(f, actor), result)).Applied
            && (await f.Database.GetCharacterByIdAsync(actor.CharacterId))!.Experience == 25
            && await f.ReceiptCount(actor.CharacterId) == 1,
            "new checkpoint identity cannot repeat settlement EXP or the challenge receipt");
        var reopened = new DatabaseService(f.Root, readOnly: true);
        Check((await reopened.GetMonkChallengeClearMaskAsync(actor.AccountId, actor.CharacterId)).ClearMask == 1
            && (await reopened.GetCharacterByIdAsync(actor.CharacterId))!.DungeonGrade == 39,
            "read-only reopen restores independent progress and the original title");
        var readOnlyState = await NativePair(f, actor);
        var beforeReadOnly = await f.UnrelatedState();
        SqliteConnection.ClearAllPools();
        bool readOnlyRejected = false;
        try { await ApplyProduction(f, actor, readOnlyState, Result("1:1"), database: reopened); }
        catch (SqliteException ex) when (ex.SqliteErrorCode == 8) { readOnlyRejected = true; }
        catch (InvalidOperationException) { readOnlyRejected = true; }
        Check(readOnlyRejected, "read-only production entry rejects writes");
        Check(beforeReadOnly == await f.UnrelatedState()
            && await f.ReceiptCount(actor.CharacterId) == 1,
            "read-only production write is rejected without changing any settlement state");
        SqliteConnection.ClearAllPools();

        await CheckProductionFailure(f);
        await CheckProductionInvalid(f);
        await CheckProductionRollback(f);
        await CheckProductionRecovery(f);
        await CheckProductionJournal(f);
        await CheckMixedReadOnly(f);
    }

    private static async Task CheckProductionFailure(Fixture f)
    {
        var actor = await f.Actor("MProdFailure");
        await SeedProductionProgress(f, actor);
        var protectedState = await ProtectedProductionState(f, actor);
        var state = await NativePair(f, actor);
        Put(state.After, 20, 0);
        var failed = Result(rating: 0) with { CharacterExperienceAward = 13 };
        Check((await ApplyProduction(f, actor, state, failed)).Applied,
            "production failure closes the ordinary settlement cycle");
        Check((await f.Database.GetMonkChallengeClearMaskAsync(actor.AccountId, actor.CharacterId)).ClearMask == 0
            && await f.ReceiptCount(actor.CharacterId) == 0
            && (await f.Database.GetCharacterByIdAsync(actor.CharacterId))!.Experience == 13,
            "failed challenge creates no clear receipt while retaining ordinary personal score EXP");
        Check(protectedState == await ProtectedProductionState(f, actor),
            "failed production challenge preserves all independent main-story state and archives");
        await ApplyProduction(f, actor, await NativePair(f, actor), Result() with { CharacterExperienceAward = 25 });
        Check((await f.Database.GetMonkChallengeClearMaskAsync(actor.AccountId, actor.CharacterId)).ClearMask == 0,
            "a failed production cycle cannot later be relabeled as success");
        state = await NativePair(f, actor);
        Put(state.After, 20, 16);
        Check((await ApplyProduction(f, actor, state, Result("1:1") with { CharacterExperienceAward = 25 })).Applied
            && (await f.Database.GetMonkChallengeClearMaskAsync(actor.AccountId, actor.CharacterId)).ClearMask == 1
            && await f.ReceiptCount(actor.CharacterId) == 1,
            "authorized next retry cycle can first clear the independent challenge");
    }
}
