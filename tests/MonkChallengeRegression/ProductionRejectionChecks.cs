using Microsoft.Data.Sqlite;
using OpenNanaimo.Adapter.Services;

internal static partial class Program
{
    private static async Task CheckProductionInvalid(Fixture f)
    {
        var actor = await f.Actor("MProdInvalid");
        await SeedProductionProgress(f, actor);
        var invalid = new[] {
            Result() with { HdIndex = 1 }, Result() with { Dungeon = 1 }, Result() with { Stage = 1 },
            Result() with { LogicalDifficulty = 3 }, Result() with { Score = -1 },
            Result() with { StageRecordScore = 99 }, Result(null), Result("01:0"), Result("1") };
        for (int index = 0; index < invalid.Length; index++)
        {
            var state = await NativePair(f, actor, 7, 3);
            var snapshot = await f.UnrelatedState();
            bool rejected = false;
            try { await ApplyProduction(f, actor, state, invalid[index] with { CharacterExperienceAward = 25 }); }
            catch (Exception ex) when (ex is InvalidDataException or InvalidOperationException) { rejected = true; }
            Check(rejected && snapshot == await f.UnrelatedState()
                && await f.ReceiptCount(actor.CharacterId) == 0,
                $"illegal production settlement{index} rolls back currencies, EXP, commit and both receipts");
        }
        var wrongAccount = actor with { AccountId = long.MaxValue };
        var before = await f.UnrelatedState();
        bool unauthorized = false;
        try { await ApplyProduction(f, wrongAccount, await NativePair(f, actor, 7), Result()); }
        catch (InvalidOperationException) { unauthorized = true; }
        Check(unauthorized && before == await f.UnrelatedState(),
            "production character/account mismatch rolls back the complete transaction");

        Check((await ApplyProduction(f, actor, await NativePair(f, actor), Result("3:5"))).Applied,
            "production records an authorized newer battle cycle");
        before = await f.UnrelatedState();
        bool stale = false;
        try { await ApplyProduction(f, actor, await NativePair(f, actor, 7), Result("2:999")); }
        catch (InvalidOperationException) { stale = true; }
        Check(stale && before == await f.UnrelatedState() && await f.ReceiptCount(actor.CharacterId) == 1,
            "production stale cycle rejection also rolls back ordinary settlement rewards");

        var invalidRatingActor = await f.Actor("MonkProdRating");
        await ApplyProduction(f, invalidRatingActor, await NativePair(f, invalidRatingActor),
            Result(rating: 6) with { CharacterExperienceAward = 25 });
        Check((await f.Database.GetMonkChallengeClearMaskAsync(invalidRatingActor.AccountId, invalidRatingActor.CharacterId)).ClearMask == 0
            && await f.ReceiptCount(invalidRatingActor.CharacterId) == 0
            && (await f.Database.GetCharacterByIdAsync(invalidRatingActor.CharacterId))!.Experience == 0,
            "invalid rating has no successful result authority even on a valid checkpoint");
    }

    private static async Task CheckProductionRollback(Fixture f)
    {
        var actor = await f.Actor("MProdRollback");
        await SeedProductionProgress(f, actor);
        await f.Update($"""
            CREATE TRIGGER RejectMonkProfile BEFORE INSERT ON NativeDungeonProfiles
            WHEN NEW.CharacterId={actor.CharacterId}
            BEGIN SELECT RAISE(ABORT, 'intentional final profile failure'); END;
            """, actor.CharacterId);
        var state = await NativePair(f, actor, 7, 3);
        var before = await f.UnrelatedState();
        var commit = Guid.NewGuid().ToString("N");
        var result = Result() with { CharacterExperienceAward = 25 };
        bool rejected = false;
        try { await ApplyProduction(f, actor, state, result, commit); }
        catch (SqliteException ex) when (ex.SqliteErrorCode == 19) { rejected = true; }
        Check(rejected && before == await f.UnrelatedState()
            && await f.ReceiptCount(actor.CharacterId) == 0
            && (await f.Database.GetMonkChallengeClearMaskAsync(actor.AccountId, actor.CharacterId)).ClearMask == 0,
            "production final profile failure rolls back the already-written challenge bit and all rewards");
        await f.Update("DROP TRIGGER RejectMonkProfile", actor.CharacterId);
        Check((await ApplyProduction(f, actor, await NativePair(f, actor, 7, 3), result, commit)).Applied
            && await f.ReceiptCount(actor.CharacterId) == 1,
            "production retry after rollback can reuse its original commit and settlement identities");
    }

    private static async Task CheckMixedReadOnly(Fixture f)
    {
        var actor = await f.Actor("MMixedReadonly");
        var state = await NativePair(f, actor, 7);
        var before = await f.UnrelatedState();
        var reader = new DatabaseService(f.Root, readOnly: true);
        Check((await reader.GetMonkChallengeClearMaskAsync(actor.AccountId, actor.CharacterId)).Authorized,
            "read-only login can coexist with an active read-write database service");
        bool rejected = false;
        try { await ApplyProduction(f, actor, state, Result(), database: reader); }
        catch (SqliteException ex) when (ex.SqliteErrorCode == 8) { rejected = true; }
        catch (InvalidOperationException) { rejected = true; }
        Check(rejected && before == await f.UnrelatedState() && await f.ReceiptCount(actor.CharacterId) == 0,
            "mixed read-write and read-only connections cannot relax the read-only settlement boundary");
        Check((await ApplyProduction(f, actor, state, Result())).Applied,
            "read-only connection lifetime does not prevent an authorized read-write settlement");
    }

    private static async Task CheckProductionJournal(Fixture f)
    {
        var actor = await f.Actor("MProdJournal");
        await SeedProductionProgress(f, actor);
        var state = await NativePair(f, actor, 7);
        var journalDirectory = Path.Combine(f.Root, "journal");
        Directory.CreateDirectory(journalDirectory);
        var path = Path.Combine(journalDirectory, actor.SessionId + ".json");
        var record = System.Text.Json.JsonSerializer.Serialize(new {
            CommitId = Guid.NewGuid().ToString("N"), actor.AccountId, actor.CharacterId, actor.SessionId,
            Before = Convert.ToBase64String(state.Before.Bytes), After = Convert.ToBase64String(state.After.Bytes),
            Settlement = Result() with { CharacterExperienceAward = 25 }
        });
        await f.Update("UPDATE Characters SET IsOnline=0,ActiveSessionId=NULL WHERE Id=$id", actor.CharacterId);
        await f.Update("UPDATE Accounts SET IsOnline=0,ActiveSessionId=NULL WHERE Id=$id", actor.AccountId);
        await f.Update($"""
            CREATE TRIGGER RejectMonkJournal BEFORE INSERT ON NativeDungeonProfiles
            WHEN NEW.CharacterId={actor.CharacterId}
            BEGIN SELECT RAISE(ABORT, 'intentional recovery failure'); END;
            """, actor.CharacterId);
        await File.WriteAllTextAsync(path, record);
        bool rejected = false;
        try { await new DatabaseService(f.Root).RecoverNativeDungeonJournalsAsync(journalDirectory, CancellationToken.None); }
        catch (SqliteException ex) when (ex.SqliteErrorCode == 19) { rejected = true; }
        Check(rejected && File.Exists(path) && await f.ReceiptCount(actor.CharacterId) == 0
            && (await f.Database.GetCharacterByIdAsync(actor.CharacterId))!.Experience == 0,
            "production recovery failure retains its journal and rolls back the successful clear and rewards");
        await f.Update("DROP TRIGGER RejectMonkJournal", actor.CharacterId);
        await new DatabaseService(f.Root).RecoverNativeDungeonJournalsAsync(journalDirectory, CancellationToken.None);
        var saved = (await f.Database.GetCharacterByIdAsync(actor.CharacterId))!;
        Check(!File.Exists(path) && saved.Experience == 25 && saved.Hans == 7 && saved.DungeonGrade == 39
            && (await f.Database.GetMonkChallengeClearMaskAsync(actor.AccountId, actor.CharacterId)).ClearMask == 1
            && await f.ReceiptCount(actor.CharacterId) == 1,
            "production journal retry atomically commits the independent clear and deletes the completed journal");
        await File.WriteAllTextAsync(path, record);
        await new DatabaseService(f.Root).RecoverNativeDungeonJournalsAsync(journalDirectory, CancellationToken.None);
        saved = (await f.Database.GetCharacterByIdAsync(actor.CharacterId))!;
        Check(!File.Exists(path) && saved.Experience == 25 && saved.Hans == 7
            && await f.ReceiptCount(actor.CharacterId) == 1,
            "repeated successful journal recovery deletes the duplicate without repeating rewards");
    }

    private static async Task CheckProductionRecovery(Fixture f)
    {
        var actor = await f.Actor("MProdRecovery");
        await SeedProductionProgress(f, actor);
        var protectedState = await ProtectedProductionState(f, actor);
        var state = await NativePair(f, actor, 7, 3);
        var result = Result() with { CharacterExperienceAward = 25 };
        var commit = Guid.NewGuid().ToString("N");
        await f.Update("UPDATE Characters SET IsOnline=0,ActiveSessionId=NULL WHERE Id=$id", actor.CharacterId);
        await f.Update("UPDATE Accounts SET IsOnline=0,ActiveSessionId=NULL WHERE Id=$id", actor.AccountId);
        var reopened = new DatabaseService(f.Root);
        Check((await ApplyProduction(f, actor, state, result, commit, recovering: true, database: reopened)).Applied,
            "reopened production database accepts authenticated offline recovery");
        Check((await reopened.GetMonkChallengeClearMaskAsync(actor.AccountId, actor.CharacterId)).ClearMask == 1
            && (await reopened.GetCharacterByIdAsync(actor.CharacterId))!.Experience == 25
            && protectedState == await ProtectedProductionState(f, actor),
            "production recovery restores the clear and rewards without advancing main-story progress");
        Check(!(await ApplyProduction(f, actor, state, result, commit, recovering: true, database: reopened)).Applied,
            "replayed production recovery commit is a no-op");
        await ApplyProduction(f, actor, await NativePair(f, actor), result, recovering: true, database: reopened);
        Check((await reopened.GetCharacterByIdAsync(actor.CharacterId))!.Experience == 25
            && await f.ReceiptCount(actor.CharacterId) == 1,
            "new recovery checkpoint cannot repeat the same successful settlement receipt");
        var takeover = actor with { SessionId = Guid.NewGuid().ToString("N") };
        Check(await f.Database.BeginWorldSessionAsync(actor.AccountId, actor.CharacterId, takeover.SessionId, 1, "127.0.0.1"),
            "production recovery actor can subsequently relogin");
        var before = await f.UnrelatedState();
        bool rejected = false;
        try { await ApplyProduction(f, actor, await NativePair(f, actor, 7), Result("1:1"), recovering: true); }
        catch (InvalidOperationException) { rejected = true; }
        Check(rejected && before == await f.UnrelatedState(),
            "new session takeover blocks and rolls back an old production recovery");
        await f.Update("UPDATE Characters SET IsOnline=0,ActiveSessionId=NULL WHERE Id=$id", actor.CharacterId);
        before = await f.UnrelatedState();
        rejected = false;
        try { await ApplyProduction(f, actor, await NativePair(f, actor, 7), Result("1:1"), recovering: true); }
        catch (InvalidOperationException) { rejected = true; }
        Check(rejected && before == await f.UnrelatedState(),
            "account-only takeover reaches the helper and rolls back the entire production recovery");
    }
}
