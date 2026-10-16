using System.Text;
using Microsoft.Data.Sqlite;
using OpenNanaimo.Adapter.Services;

internal static partial class Program
{
    private static int checks;
    private sealed record Actor(long AccountId, long CharacterId, string SessionId);

    public static async Task Main()
    {
        Encoding.RegisterProvider(CodePagesEncodingProvider.Instance);
        CheckPolicy();
        await using var fixture = await Fixture.Create();
        await CheckLedger(fixture);
        await CheckProductionSettlements(fixture);
        await CheckRankings(fixture);
        await CheckRankingMigration();
        IntegrationChecks.Run();
        Console.WriteLine($"MONK_CHALLENGE_REGRESSION_PASS checks={checks}");
    }

    private static void Check(bool value, string message)
    {
        if (!value) throw new InvalidOperationException(message);
        checks++;
        Console.WriteLine("PASS " + message);
    }

    private static void CheckPolicy()
    {
        Check(MonkChallengePolicy.FirstEpisode == 24 && MonkChallengePolicy.ChallengeCount == 4
            && MonkChallengePolicy.FullClearMask == 15, "four independent clear positions begin at episode24");
        for (var episode = 0; episode <= byte.MaxValue; episode++)
        {
            var reserved = episode is >= 24 and <= 27;
            if (MonkChallengePolicy.IsReservedEpisode((byte)episode) != reserved
                || MonkChallengePolicy.IsPlayableTuple(0, (byte)episode, 0, 0) != reserved
                || MonkChallengePolicy.TryGetChallengeIndex(0, (byte)episode, 0, 0, out var index) != reserved
                || index != (reserved ? episode - 24 : -1))
                throw new InvalidOperationException($"Incorrect challenge policy for episode {episode}.");
        }
        Check(true, "all 256 episodes distinguish four playable challenges and unrelated selections");
        for (var field = 1; field <= byte.MaxValue; field++)
        {
            foreach (var tuple in new[] { ((byte)field, (byte)24, (byte)0, (byte)0),
                ((byte)0, (byte)24, (byte)field, (byte)0), ((byte)0, (byte)24, (byte)0, (byte)field) })
                if (MonkChallengePolicy.IsPlayableTuple(tuple.Item1, tuple.Item2, tuple.Item3, tuple.Item4)
                    || MonkChallengePolicy.TryGetChallengeIndex(tuple.Item1, tuple.Item2, tuple.Item3, tuple.Item4, out _))
                    throw new InvalidOperationException("Nonstandard challenge tuple was accepted.");
        }
        Check(true, "every nonzero hd, dungeon and realStage is rejected for episode24");
        for (byte episode = 24; episode <= 27; episode++)
            Check(!DungeonTitleProgression.TryGetGrade(0, episode, 0, 0, out _),
                $"challenge episode{episode} has no automatic main-story title");
        Check(DungeonTitleProgression.TryGetGrade(0, 15, 2, 1, out var p16) && p16 == 16
            && DungeonTitleProgression.TryGetGrade(0, 100, 7, 1, out var r8) && r8 == 24,
            "existing P16 and R8 title rules remain unchanged");
    }

    private static NativeDungeonSettlementRecord Result(string? id = "1:0", byte rating = 5)
        => new(0, 24, 0, 0, 0, rating, 100, SettlementId: id);

    private static async Task CheckLedger(Fixture f)
    {
        var owner = await f.Actor("MonkOwner");
        var peer = await f.Actor("MonkPeer");
        var readonlyDb = new DatabaseService(f.Root, readOnly: true);
        Check(await readonlyDb.GetMonkChallengeClearMaskAsync(owner.AccountId, owner.CharacterId)
            == new MonkChallengeProgressResult(true, 0), "read-only login reads zero before lazy schema creation");
        Check(!(await f.Database.GetMonkChallengeClearMaskAsync(peer.AccountId, owner.CharacterId)).Authorized,
            "login cannot read another account's character");
        Check(!(await f.Database.GetMonkChallengeClearMaskAsync(0, owner.CharacterId)).Authorized,
            "invalid account cannot read progress");
        Check(await f.CountTables() == 0, "login reads do not initialize schema");

        foreach (var id in new string?[] { null, "", "1", ":0", "1:", "0:0", "-1:0", "1:-1", "1:0:0",
            "01:0", "1:00", "1: 0", "1:+0", "9223372036854775808:0" })
            Check((await f.Commit(owner, Result(id))).Status == MonkChallengeCommitStatus.InvalidSettlement,
                $"malformed settlement identity {id ?? "null"} is rejected");
        foreach (var rating in new byte[] { 0, 6, 255 })
            Check((await f.Commit(owner, Result(rating: rating))).Status == MonkChallengeCommitStatus.InvalidSettlement,
                $"rating{rating} cannot write a success");
        foreach (var result in new[] { Result() with { HdIndex = 1 }, Result() with { Dungeon = 1 },
            Result() with { Stage = 1 }, Result() with { Episode = 23 }, Result() with { Episode = 100 } })
            Check((await f.Commit(owner, result)).Status == MonkChallengeCommitStatus.InvalidSettlement,
                "a nonchallenge selection is rejected without progress");
        for (byte episode = 25; episode <= 27; episode++)
            Check(MonkChallengePolicy.IsPlayableTuple(0, episode, 0, 0),
                $"episode{episode} is an independent playable challenge");
        Check((await f.Commit(owner with { CharacterId = peer.CharacterId }, Result())).Status
            == MonkChallengeCommitStatus.Unauthorized, "another room owner's member identity is rejected");
        Check((await f.Commit(owner with { SessionId = "obsolete" }, Result())).Status
            == MonkChallengeCommitStatus.Unauthorized, "unowned session identity is rejected");
        Check((await f.Commit(owner with { CharacterId = long.MaxValue }, Result())).Status
            == MonkChallengeCommitStatus.Unauthorized, "nonexistent character identity is rejected");
        Check(await f.CountTables() == 0, "invalid and unauthorized requests create no ledger tables");

        await using (var connection = await f.Open())
        await using (var tx = connection.BeginTransaction())
        {
            var result = await DatabaseService.CommitMonkChallengeSuccessAsync(
                connection, tx, owner.CharacterId, owner.SessionId, Result());
            Check(result.Applied && result.NewlyCleared && result.ClearMask == 1,
                "successful first clear is tentative inside the caller's transaction");
            await f.Execute(connection, tx, "UPDATE Characters SET Hans=Hans+7 WHERE Id=$id", owner.CharacterId);
            await tx.RollbackAsync();
        }
        Check(await f.CountTables() == 0 && (await f.Database.GetCharacterByIdAsync(owner.CharacterId))!.Hans == 0,
            "outer rollback removes schema, bit, receipt and settlement currency together");

        var baseline = await f.UnrelatedState();
        var first = await f.Commit(owner, Result());
        Check(first == new MonkChallengeCommitResult(MonkChallengeCommitStatus.Applied, 1, true),
            "first successful epoch/cycle persists bit0 only");
        Check(baseline == await f.UnrelatedState(), "challenge commit changes no existing character or business table");
        Check(await f.ReceiptCount(owner.CharacterId) == 1, "one successful receipt is persisted");
        Check((await f.Commit(owner, Result())) == new MonkChallengeCommitResult(MonkChallengeCommitStatus.Duplicate, 1, false),
            "duplicate settlement cannot repeat first-clear eligibility");
        Check((await f.Commit(owner, Result(rating: 1))).Status == MonkChallengeCommitStatus.Duplicate,
            "changing a successful rating cannot reward the same cycle twice");
        Check(await f.ReceiptCount(owner.CharacterId) == 1, "duplicates create no extra receipt");
        Check((await f.Commit(owner, Result("1:2"))) == new MonkChallengeCommitResult(MonkChallengeCommitStatus.Applied, 1, false),
            "new retry cycle is recorded without repeating first-clear eligibility");
        Check((await f.Commit(owner, Result("1:1"))).Status == MonkChallengeCommitStatus.StaleSettlement,
            "late lower cycle is rejected");
        Check((await f.Commit(owner, Result("1:0"))).Status == MonkChallengeCommitStatus.StaleSettlement,
            "an old successful receipt never authorizes a stale cycle");
        Check((await f.Commit(owner, Result("2:0"))).Applied, "new battle epoch can restart its cycle at zero");
        Check((await f.Commit(owner, Result("1:999"))).Status == MonkChallengeCommitStatus.StaleSettlement,
            "old epoch cannot bypass rejection with a higher cycle");
        Check(await f.ReceiptCount(owner.CharacterId) == 3, "stale results leave successful receipts unchanged");
        Check((await f.Commit(peer, Result("2:0"))).NewlyCleared,
            "character and session identity isolate the same epoch/cycle");

        var reopened = new DatabaseService(f.Root);
        Check(await reopened.GetMonkChallengeClearMaskAsync(owner.AccountId, owner.CharacterId)
            == new MonkChallengeProgressResult(true, 1), "database reopen restores the independent four-bit mask");
        Check((await f.Commit(owner, Result("2:0"))).Status == MonkChallengeCommitStatus.Duplicate,
            "receipt deduplication survives database reopen");

        await CheckTransactionFailure(f);
        await CheckAtomicCommit(f);
        await CheckConcurrency(f);
        await CheckRecovery(f);
        await CheckSuccessfulRatings(f);
        await CheckAuthorization(f, owner);
        await CheckFourBits(f);

        var beforeSchema = await f.UnrelatedState();
        var receipts = await f.ReceiptCount(owner.CharacterId);
        await f.Database.InitializeMonkChallengesAsync();
        await f.Database.InitializeMonkChallengesAsync();
        Check(await f.ReceiptCount(owner.CharacterId) == receipts && beforeSchema == await f.UnrelatedState(),
            "repeated schema initialization preserves receipts and all unrelated state");
        Check((await readonlyDb.GetMonkChallengeClearMaskAsync(owner.AccountId, owner.CharacterId)).ClearMask == 1,
            "read-only login restores persisted progress without writes");
        Check((await f.Database.GetMonkChallengeClearMaskAsync(peer.AccountId, peer.CharacterId)).ClearMask == 1,
            "one character's later operations do not overwrite another's mask");
    }
}
