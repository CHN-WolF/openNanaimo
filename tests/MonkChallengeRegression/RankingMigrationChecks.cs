using Microsoft.Data.Sqlite;
using OpenNanaimo.Adapter.Services;

internal static partial class Program
{
    private static async Task CheckRankingMigration()
    {
        await using var f = await Fixture.Create();
        var actor = await f.Actor("MigrateMonk");
        var peer = await f.Actor("MigratePeer");
        await f.Update("""
            CREATE TABLE MonkChallengePerformance (
                CharacterId INTEGER NOT NULL REFERENCES Characters(Id) ON DELETE CASCADE,
                ChallengeIndex INTEGER NOT NULL CHECK (ChallengeIndex BETWEEN 0 AND 3),
                Difficulty INTEGER NOT NULL CHECK (Difficulty BETWEEN 0 AND 2),
                BestRating INTEGER NOT NULL CHECK (BestRating BETWEEN 1 AND 5),
                BestScore INTEGER NOT NULL CHECK (BestScore >= 0),
                BestElapsedMinutes INTEGER NULL, ClearedAt TEXT NOT NULL, UpdatedAt TEXT NOT NULL,
                PRIMARY KEY (CharacterId,ChallengeIndex,Difficulty)
            );
            """, actor.CharacterId);
        foreach (var owner in new[] { actor, peer })
        for (int index = 0; index < 4; index++)
            await f.Update($"""
                INSERT INTO MonkChallengePerformance VALUES
                    ($id,{index},0,5,100,2,'2026-10-01','2026-10-02'),
                    ($id,{index},1,3,{900 + index},NULL,'2026-10-03','2026-10-03'),
                    ($id,{index},2,4,{900 + index},7,'2026-10-04','2026-10-04');
                """, owner.CharacterId);
        var unrelated = await f.UnrelatedState();
        await using (var sql = await f.Open())
        await using (var tx = sql.BeginTransaction())
        {
            Check((await DatabaseService.CommitMonkChallengeSuccessAsync(sql, tx,
                actor.CharacterId, actor.SessionId, Result())).Applied,
                "legacy ledger can migrate inside a settlement transaction");
            await tx.RollbackAsync();
        }
        Check(Convert.ToInt32(await f.Scalar("SELECT pk FROM pragma_table_info('MonkChallengePerformance') WHERE name='Difficulty'", 0)) == 3
            && Convert.ToInt32(await f.Scalar("SELECT COUNT(*) FROM MonkChallengePerformance", 0)) == 24
            && unrelated == await f.UnrelatedState(),
            "rollback restores the exact legacy schema and all difficulty rows");
        var restarted = new DatabaseService(f.Root);
        await restarted.InitializeAsync();
        Check(Convert.ToInt32(await f.Scalar("SELECT pk FROM pragma_table_info('MonkChallengePerformance') WHERE name='Difficulty'", 0)) == 0,
            "ordinary writable startup migrates the legacy schema before any ranking query");
        await restarted.InitializeAsync();
        Check(Convert.ToInt32(await f.Scalar("SELECT COUNT(*) FROM MonkChallengePerformance", 0)) == 8,
            "startup migration is idempotent and retains one slot per actor and challenge");
        var readOnly = new DatabaseService(f.Root, readOnly: true);
        for (byte index = 0; index < 4; index++)
        {
            var rows = await readOnly.GetDungeonStageLeaderboardAsync(0, (byte)(24 + index), 0, 0, 0);
            Check(rows.Count == 2 && rows.All(r => r.BestScore == 900 + index)
                && await readOnly.GetMonkChallengeReadyRoomRankAsync(actor.CharacterId, (byte)(24 + index), 0) == 3,
                "migration merges best score and best rating independently for every challenge");
        }
        Check(Convert.ToInt32(await f.Scalar("SELECT COUNT(*) FROM MonkChallengePerformance WHERE Difficulty=0 AND BestElapsedMinutes=7 AND ClearedAt='2026-10-01' AND UpdatedAt='2026-10-04'", 0)) == 8,
            "winning score keeps its known elapsed/tie metadata and the earliest clear is preserved");
        foreach (var sql in new[] {
            "UPDATE MonkChallengePerformance SET Difficulty=1 WHERE CharacterId=$id",
            "UPDATE MonkChallengePerformance SET Difficulty=2 WHERE CharacterId=$id",
            "INSERT INTO MonkChallengePerformance SELECT * FROM MonkChallengePerformance WHERE CharacterId=$id" })
        {
            bool rejected = false;
            try { await f.Update(sql, actor.CharacterId); }
            catch (SqliteException ex) when (ex.SqliteErrorCode == 19) { rejected = true; }
            Check(rejected, "single-slot SQL constraints reject nonzero difficulty and duplicate slots");
        }
        Check(await f.Database.BeginWorldSessionAsync(actor.AccountId, actor.CharacterId, actor.SessionId, 1, "127.0.0.1"),
            "migration fixture reacquires its world session after startup resets online state");
        Check((await f.Commit(actor, Result() with { Score = 1000, StageRecordScore = 1000 })).Applied,
            "the migrated single slot accepts a fresh authorized score");
        Check(await f.Scalar("SELECT BestElapsedMinutes FROM MonkChallengePerformance WHERE CharacterId=$id AND ChallengeIndex=0", actor.CharacterId) is DBNull,
            "a new score with unknown elapsed does not inherit another score's migration metadata");
        await f.Update("DELETE FROM Characters WHERE Id=$id", peer.CharacterId);
        Check(Convert.ToInt32(await f.Scalar("SELECT COUNT(*) FROM MonkChallengePerformance WHERE CharacterId=$id", peer.CharacterId)) == 0,
            "migrated challenge scores retain character-delete cascade");
        Console.WriteLine("MONK_RANKING_MIGRATION_PASS startup atomic rollback best-values metadata constraints cascade");
    }
}
