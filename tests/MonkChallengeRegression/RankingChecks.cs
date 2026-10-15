using System.Buffers.Binary;
using System.Reflection;
using Microsoft.Data.Sqlite;
using OpenNanaimo.Adapter.Services;

internal static partial class Program
{
    private static async Task CheckRankings(Fixture f)
    {
        var actors = new List<Actor>();
        for (int i = 0; i < 12; i++) actors.Add(await f.Actor($"MRank{i:D2}"));
        var protectedState = await ProtectedProductionState(f, actors[0]);
        for (int actor = 0; actor < actors.Count; actor++)
        for (byte index = 0; index < 4; index++)
        for (byte difficulty = 0; difficulty < 3; difficulty++)
        {
            var score = 1000 + index * 10000 + difficulty * 1000 + actor * 10;
            var result = new NativeDungeonSettlementRecord(0, (byte)(24 + index), 0, 0,
                difficulty, (byte)(1 + (actor + index + difficulty) % 5), score,
                score, SettlementId: $"{index * 3 + difficulty + 1}:0");
            Check((await f.Commit(actors[actor], result)).Applied,
                $"monk{index} difficulty{difficulty} actor{actor}: successful receipt and ranking commit together");
        }
        var restarted = new DatabaseService(f.Root, readOnly: true);
        for (byte index = 0; index < 4; index++)
        for (byte difficulty = 0; difficulty < 3; difficulty++)
        {
            var rows = await restarted.GetDungeonStageLeaderboardAsync(0, (byte)(24 + index), 0, 0, difficulty);
            Check(rows.Count == 10 && rows.Select(r => r.CharacterName)
                    .SequenceEqual(Enumerable.Range(2, 10).Reverse().Select(i => $"MRank{i:D2}"))
                && rows[0].BestScore == 1110 + index * 10000 + difficulty * 1000,
                $"monk{index} difficulty{difficulty}: exact independent top-ten survives read-only reopen");
            var rank = await restarted.GetMonkChallengeReadyRoomRankAsync(actors[0].CharacterId,
                (byte)(24 + index), difficulty);
            Check(rank == Math.Clamp((index + difficulty) % 5 - 1, 0, 3),
                "monk ready-room badge is selected difficulty's actual blank/B/A/S, never another challenge's rating");
            var selector = new byte[] { 20, 0, 0, 0 };
            var builder = typeof(NetworkAdapterService).GetMethod("BuildDungeonStageRecordsPayload",
                BindingFlags.NonPublic | BindingFlags.Static)!;
            var payload = (byte[])builder.Invoke(null, [selector, rows])!;
            Check(payload.Length == 244 && BinaryPrimitives.ReadUInt32LittleEndian(payload.AsSpan(20)) == rows[0].BestScore
                && BinaryPrimitives.ReadUInt16LittleEndian(payload.AsSpan(24)) == rows[0].CharacterLevel
                && BinaryPrimitives.ReadUInt16LittleEndian(payload.AsSpan(26)) == rows[0].DungeonGrade,
                "monk CF16 uses existing initialized score/real-level/exact-title layout");
        }
        var cache = await f.Database.GetDungeonFrontierBestRatingsAsync(actors[0].CharacterId);
        for (byte challenge = 0; challenge < 4; challenge++)
        for (byte clientDifficulty = 0; clientDifficulty < 3; clientDifficulty++)
        {
            var logical = DungeonNavigationPolicy.DecodeLogicalDifficulty(0, 0, clientDifficulty);
            var expected = Math.Clamp((challenge + logical) % 5 - 1, 0, 3);
            Check(((cache[8 + challenge] >> (clientDifficulty * 2)) & 3) == expected,
                "monk popup cache keeps four challenge rows and client/logical difficulty mapping");
        }
        Check(cache.AsSpan(0, 8).ToArray().All(b => b == 0) && cache.AsSpan(12).ToArray().All(b => b == 0),
            "monk cache does not fill any fifth-village or unassigned rating rows");
        var first = actors[0];
        var better = new NativeDungeonSettlementRecord(0, 24, 0, 0, 0, 5, 90000, 90000, SettlementId: "20:0");
        Check((await ApplyProduction(f, first, await NativePair(f, first), better)).Applied,
            "production native checkpoint persists monk ranking via the same atomic settlement transaction");
        var before = await f.Database.GetDungeonStageLeaderboardAsync(0, 24, 0, 0, 0);
        Check(before[0].CharacterId == first.CharacterId && before[0].BestScore == 90000,
            "fresh production result is visible to the first subsequent leaderboard query");
        await ApplyProduction(f, first, await NativePair(f, first), better with { Score = 100000, StageRecordScore = 100000 });
        Check((await f.Database.GetDungeonStageLeaderboardAsync(0, 24, 0, 0, 0))[0].BestScore == 90000,
            "replayed settlement identity cannot upgrade its score");
        await f.Commit(first, better with { Rating = 1, Score = 1, StageRecordScore = 1, SettlementId = "20:1" });
        Check((await f.Database.GetDungeonStageLeaderboardAsync(0, 24, 0, 0, 0))[0].BestScore == 90000
            && await f.Database.GetMonkChallengeReadyRoomRankAsync(first.CharacterId, 24, 0) == 3,
            "lower retry cannot downgrade best score or S badge");
        Check(protectedState == await ProtectedProductionState(f, first),
            "monk rankings leave main-story progress, title milestones and archived profiles unchanged");
        Check((await f.Database.GetDungeonStageLeaderboardAsync(1, 24, 0, 0, 0)).Count == 0
            && (await f.Database.GetDungeonStageLeaderboardAsync(0, 24, 1, 0, 0)).Count == 0
            && (await f.Database.GetDungeonStageLeaderboardAsync(0, 24, 0, 1, 0)).Count == 0
            && (await f.Database.GetDungeonStageLeaderboardAsync(0, 24, 0, 0, 3)).Count == 0,
            "invalid monk hd/dungeon/stage/difficulty cannot alias real records");
        var rollback = await f.Actor("MRankRollback");
        await f.Update($"CREATE TRIGGER RejectMonkRanking BEFORE INSERT ON MonkChallengePerformance WHEN NEW.CharacterId={rollback.CharacterId} BEGIN SELECT RAISE(ABORT,'ranking rollback'); END", rollback.CharacterId);
        var snapshot = await f.UnrelatedState();
        bool rejected = false;
        try { await ApplyProduction(f, rollback, await NativePair(f, rollback, 7), Result()); }
        catch (SqliteException ex) when (ex.SqliteErrorCode == 19) { rejected = true; }
        Check(rejected && snapshot == await f.UnrelatedState() && await f.ReceiptCount(rollback.CharacterId) == 0
            && (await f.Database.GetMonkChallengeClearMaskAsync(rollback.AccountId, rollback.CharacterId)).ClearMask == 0
            && (await f.Database.GetDungeonStageLeaderboardAsync(0, 24, 0, 0, 0)).All(r => r.CharacterId != rollback.CharacterId),
            "ranking failure rolls back currency, checkpoint, success receipt and clear bit together");
        await f.Update("DROP TRIGGER RejectMonkRanking", rollback.CharacterId);
        var legacy = await f.Actor("MRankLegacy");
        await f.Commit(legacy, Result());
        await f.Update("DELETE FROM MonkChallengePerformance WHERE CharacterId=$id", legacy.CharacterId);
        Check((await f.Commit(legacy, Result())).Status == MonkChallengeCommitStatus.Duplicate
            && await f.Database.GetMonkChallengeReadyRoomRankAsync(legacy.CharacterId, 24, 0) == 0
            && (await f.Database.GetDungeonStageLeaderboardAsync(0, 24, 0, 0, 0)).All(r => r.CharacterId != legacy.CharacterId),
            "legacy clear bits and duplicate receipts do not fabricate missing historical scores");
        Console.WriteLine("MONK_RANKING_CHECKS_PASS four-challenges three-difficulties top10 CF16 CF71 atomic restart no-fake-history");
    }
}
