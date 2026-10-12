using Microsoft.Data.Sqlite;
using OpenNanaimo.Adapter.Services;

internal static partial class Program
{
    private static async Task CheckTransactionFailure(Fixture f)
    {
        var actor = await f.Actor("MonkRollback");
        await using (var connection = await f.Open())
        await using (var tx = connection.BeginTransaction())
        {
            await f.Execute(connection, tx, $"""
                CREATE TRIGGER RejectMonkMask BEFORE INSERT ON CharacterMonkChallenges
                WHEN NEW.CharacterId={actor.CharacterId}
                BEGIN SELECT RAISE(ABORT, 'intentional test failure'); END;
                """, actor.CharacterId);
            await tx.CommitAsync();
        }
        bool failed = false;
        try { await f.Commit(actor, Result()); }
        catch (SqliteException ex) when (ex.SqliteErrorCode == 19) { failed = true; }
        Check(failed && await f.ReceiptCount(actor.CharacterId) == 0
            && (await f.Database.GetMonkChallengeClearMaskAsync(actor.AccountId, actor.CharacterId)).ClearMask == 0,
            "mask write failure rolls back the receipt in the caller's transaction");
        await using (var connection = await f.Open())
        await using (var tx = connection.BeginTransaction())
        {
            await f.Execute(connection, tx, "DROP TRIGGER RejectMonkMask", actor.CharacterId);
            await tx.CommitAsync();
        }
        Check((await f.Commit(actor, Result())).NewlyCleared, "retry after rollback can commit exactly once");
    }

    private static async Task CheckAtomicCommit(Fixture f)
    {
        var actor = await f.Actor("MonkAtomic");
        await using (var connection = await f.Open())
        await using (var tx = connection.BeginTransaction())
        {
            var result = await DatabaseService.CommitMonkChallengeSuccessAsync(
                connection, tx, actor.CharacterId, actor.SessionId, Result());
            Check(result.Applied, "helper accepts the existing settlement transaction");
            await f.Execute(connection, tx, "UPDATE Characters SET Hans=Hans+7 WHERE Id=$id", actor.CharacterId);
            var duplicate = await DatabaseService.CommitMonkChallengeSuccessAsync(
                connection, tx, actor.CharacterId, actor.SessionId, Result());
            Check(duplicate.Status == MonkChallengeCommitStatus.Duplicate && !duplicate.NewlyCleared,
                "duplicate inside the same transaction does not repeat eligibility");
            await tx.CommitAsync();
        }
        Check((await f.Database.GetCharacterByIdAsync(actor.CharacterId))!.Hans == 7
            && (await f.Database.GetMonkChallengeClearMaskAsync(actor.AccountId, actor.CharacterId)).ClearMask == 1
            && await f.ReceiptCount(actor.CharacterId) == 1,
            "outer settlement commit persists currency, bit and receipt atomically");
    }

    private static async Task CheckConcurrency(Fixture f)
    {
        var actor = await f.Actor("MonkConcurrent");
        var results = await Task.WhenAll(Enumerable.Range(0, 8).Select(_ => Task.Run(() => f.Commit(actor, Result()))));
        Check(results.Count(r => r.Applied && r.NewlyCleared) == 1
            && results.Count(r => r.Status == MonkChallengeCommitStatus.Duplicate) == 7
            && await f.ReceiptCount(actor.CharacterId) == 1,
            "eight concurrent retries yield one durable first clear and one receipt");
        await using var connection = await f.Open();
        await using var other = await f.Open();
        await using var tx = connection.BeginTransaction();
        bool rejected = false;
        try { await DatabaseService.CommitMonkChallengeSuccessAsync(other, tx, actor.CharacterId, actor.SessionId, Result()); }
        catch (ArgumentException) { rejected = true; }
        Check(rejected, "helper rejects a transaction from a different connection");
    }

    private static async Task CheckRecovery(Fixture f)
    {
        var actor = await f.Actor("MonkRecovery");
        await f.Update("UPDATE Characters SET IsOnline=0,ActiveSessionId=NULL WHERE Id=$id", actor.CharacterId);
        await f.Update("UPDATE Accounts SET IsOnline=0,ActiveSessionId=NULL WHERE Id=$id", actor.AccountId);
        Check((await f.Commit(actor, Result())).Status == MonkChallengeCommitStatus.Unauthorized,
            "offline settlement requires explicit recovery authorization");
        Check((await f.Commit(actor, Result(), recovering: true))
            == new MonkChallengeCommitResult(MonkChallengeCommitStatus.Applied, 1, true),
            "authenticated offline recovery persists the original successful settlement");
        Check((await f.Commit(actor, Result(), recovering: true))
            == new MonkChallengeCommitResult(MonkChallengeCommitStatus.Duplicate, 1, false)
            && await f.ReceiptCount(actor.CharacterId) == 1,
            "replayed offline recovery cannot repeat its receipt or first clear");
        Check((await new DatabaseService(f.Root, readOnly: true)
            .GetMonkChallengeClearMaskAsync(actor.AccountId, actor.CharacterId)).ClearMask == 1,
            "recovered clear mask survives database reopen");
        await f.Update("UPDATE Accounts SET IsBanned=1 WHERE Id=$id", actor.AccountId);
        Check((await f.Commit(actor, Result("1:1"), recovering: true)).Status == MonkChallengeCommitStatus.Unauthorized,
            "banned account cannot authorize offline recovery");
        await f.Update("UPDATE Accounts SET IsBanned=0 WHERE Id=$id", actor.AccountId);
        var takeover = actor with { SessionId = Guid.NewGuid().ToString("N") };
        Check(await f.Database.BeginWorldSessionAsync(actor.AccountId, actor.CharacterId, takeover.SessionId, 1, "127.0.0.1"),
            "new session takes ownership after recovery");
        Check((await f.Commit(actor, Result("1:1"), recovering: true)).Status == MonkChallengeCommitStatus.Unauthorized,
            "new online session blocks the old recovery identity");
        await f.Update("UPDATE Characters SET IsOnline=0,ActiveSessionId=NULL WHERE Id=$id", actor.CharacterId);
        Check((await f.Commit(actor, Result("1:1"), recovering: true)).Status == MonkChallengeCommitStatus.Unauthorized,
            "account session takeover alone blocks recovery");
        await f.Update("UPDATE Characters SET IsOnline=1,ActiveSessionId='new-owner' WHERE Id=$id", actor.CharacterId);
        await f.Update("UPDATE Accounts SET IsOnline=0,ActiveSessionId=NULL WHERE Id=$id", actor.AccountId);
        Check((await f.Commit(actor, Result("1:1"), recovering: true)).Status == MonkChallengeCommitStatus.Unauthorized,
            "character session takeover alone blocks recovery");
        Check(await f.ReceiptCount(actor.CharacterId) == 1,
            "rejected recovery creates no additional receipt");
    }

    private static async Task CheckSuccessfulRatings(Fixture f)
    {
        var actor = await f.Actor("MonkRatings");
        for (byte rating = 1; rating <= 5; rating++)
            Check((await f.Commit(actor, Result($"1:{rating}", rating)))
                == new MonkChallengeCommitResult(MonkChallengeCommitStatus.Applied, 1, rating == 1),
                $"successful rating{rating} records only the independent first bit");
        Check(await f.ReceiptCount(actor.CharacterId) == 5, "all five successful ratings have isolated cycle receipts");
    }

    private static async Task CheckAuthorization(Fixture f, Actor actor)
    {
        await f.Update("UPDATE Accounts SET IsBanned=1 WHERE Id=$id", actor.AccountId);
        Check((await f.Commit(actor, Result("3:0"))).Status == MonkChallengeCommitStatus.Unauthorized,
            "banned account cannot commit success");
        await f.Update("UPDATE Accounts SET IsBanned=0 WHERE Id=$id", actor.AccountId);
        await f.Update("UPDATE Characters SET IsOnline=0,ActiveSessionId=NULL WHERE Id=$id", actor.CharacterId);
        await f.Update("UPDATE Accounts SET IsOnline=0,ActiveSessionId=NULL WHERE Id=$id", actor.AccountId);
        Check((await f.Commit(actor, Result("3:0"))).Status == MonkChallengeCommitStatus.Unauthorized,
            "offline character cannot commit success");
        Check((await f.Database.GetMonkChallengeClearMaskAsync(actor.AccountId, actor.CharacterId)).ClearMask == 1,
            "offline login read retains the completed challenge");
        var relogged = actor with { SessionId = Guid.NewGuid().ToString("N") };
        Check(await f.Database.BeginWorldSessionAsync(actor.AccountId, actor.CharacterId, relogged.SessionId, 1, "127.0.0.1"),
            "relogin establishes a new owned session");
        Check((await f.Commit(actor, Result("3:0"))).Status == MonkChallengeCommitStatus.Unauthorized,
            "old session cannot reward a relogged character");
        Check((await f.Commit(relogged, Result("1:0"))) == new MonkChallengeCommitResult(MonkChallengeCommitStatus.Applied, 1, false),
            "new session may reset epoch while preserving first-clear deduplication");
    }

    private static async Task CheckFourBits(Fixture f)
    {
        var actor = await f.Actor("MonkMask");
        // Storage fixtures exercise future bit preservation, not playable content.
        for (var mask = 0; mask <= 15; mask++)
        {
            await f.Update($"""
                INSERT INTO CharacterMonkChallenges VALUES($id,{mask},'fixture')
                ON CONFLICT(CharacterId) DO UPDATE SET ClearMask=excluded.ClearMask
                """, actor.CharacterId);
            var db = new DatabaseService(f.Root, readOnly: true);
            Check((await db.GetMonkChallengeClearMaskAsync(actor.AccountId, actor.CharacterId)).ClearMask == mask,
                $"reopened login preserves all four bits for mask{mask}");
        }
        foreach (var mask in new[] { -1, 16 })
        {
            bool rejected = false;
            try { await f.Update($"UPDATE CharacterMonkChallenges SET ClearMask={mask} WHERE CharacterId=$id", actor.CharacterId); }
            catch (SqliteException ex) when (ex.SqliteErrorCode == 19) { rejected = true; }
            Check(rejected, $"schema rejects out-of-range mask{mask}");
        }
        await f.Update("UPDATE CharacterMonkChallenges SET ClearMask=10 WHERE CharacterId=$id", actor.CharacterId);
        Check((await f.Commit(actor, Result())) == new MonkChallengeCommitResult(MonkChallengeCommitStatus.Applied, 11, true),
            "bit0 clear preserves all preexisting independent higher bits");
        await f.Update("DELETE FROM Characters WHERE Id=$id", actor.CharacterId);
        Check(await f.ReceiptCount(actor.CharacterId) == 0
            && !(await f.Database.GetMonkChallengeClearMaskAsync(actor.AccountId, actor.CharacterId)).Authorized,
            "character deletion cascades challenge receipts and removes readable progress");
    }
}
