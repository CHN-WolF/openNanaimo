using System.Globalization;
using Microsoft.Data.Sqlite;

namespace OpenNanaimo.Adapter.Services;

public sealed partial class DatabaseService
{
    public async Task InitializeMonkChallengesAsync(CancellationToken token = default)
    {
        await using var connection = await OpenConnectionAsync(token);
        await using var transaction = connection.BeginTransaction();
        await EnsureMonkChallengeSchemaAsync(connection, transaction, token);
        await transaction.CommitAsync(token);
    }

    private static async Task EnsureMonkChallengeSchemaAsync(
        SqliteConnection connection, SqliteTransaction transaction, CancellationToken token)
    {
        await using var command = connection.CreateCommand();
        command.Transaction = transaction;
        command.CommandText = """
            CREATE TABLE IF NOT EXISTS CharacterMonkChallenges (
                CharacterId INTEGER PRIMARY KEY REFERENCES Characters(Id) ON DELETE CASCADE,
                ClearMask INTEGER NOT NULL CHECK (ClearMask BETWEEN 0 AND 15),
                UpdatedAt TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS MonkChallengeCommits (
                CharacterId INTEGER NOT NULL REFERENCES Characters(Id) ON DELETE CASCADE,
                SessionId TEXT NOT NULL,
                SettlementId TEXT NOT NULL,
                BattleEpoch INTEGER NOT NULL CHECK (BattleEpoch > 0),
                SettlementCycle INTEGER NOT NULL CHECK (SettlementCycle >= 0),
                ChallengeIndex INTEGER NOT NULL CHECK (ChallengeIndex BETWEEN 0 AND 3),
                Rating INTEGER NOT NULL CHECK (Rating BETWEEN 1 AND 5),
                CommittedAt TEXT NOT NULL,
                PRIMARY KEY (CharacterId, SessionId, SettlementId)
            );
            CREATE INDEX IF NOT EXISTS IX_MonkChallengeCommits_Cycle
                ON MonkChallengeCommits(CharacterId, SessionId, BattleEpoch, SettlementCycle);
            CREATE TABLE IF NOT EXISTS MonkChallengePerformance (
                CharacterId INTEGER NOT NULL REFERENCES Characters(Id) ON DELETE CASCADE,
                ChallengeIndex INTEGER NOT NULL CHECK (ChallengeIndex BETWEEN 0 AND 3),
                Difficulty INTEGER NOT NULL CHECK (Difficulty = 0),
                BestRating INTEGER NOT NULL CHECK (BestRating BETWEEN 1 AND 5),
                BestScore INTEGER NOT NULL CHECK (BestScore >= 0),
                BestElapsedMinutes INTEGER NULL,
                ClearedAt TEXT NOT NULL,
                UpdatedAt TEXT NOT NULL,
                PRIMARY KEY (CharacterId, ChallengeIndex)
            );
            """;
        await command.ExecuteNonQueryAsync(token);
        command.CommandText = "SELECT pk FROM pragma_table_info('MonkChallengePerformance') WHERE name='Difficulty'";
        if (Convert.ToInt32(await command.ExecuteScalarAsync(token)) == 0) return;

        // Collapse the released three-difficulty ledger atomically. Score metadata
        // follows the winning score row; rating and first clear remain independent.
        command.CommandText = """
            CREATE TABLE MonkChallengePerformanceSingle (
                CharacterId INTEGER NOT NULL REFERENCES Characters(Id) ON DELETE CASCADE,
                ChallengeIndex INTEGER NOT NULL CHECK (ChallengeIndex BETWEEN 0 AND 3),
                Difficulty INTEGER NOT NULL CHECK (Difficulty = 0),
                BestRating INTEGER NOT NULL CHECK (BestRating BETWEEN 1 AND 5),
                BestScore INTEGER NOT NULL CHECK (BestScore >= 0),
                BestElapsedMinutes INTEGER NULL,
                ClearedAt TEXT NOT NULL,
                UpdatedAt TEXT NOT NULL,
                PRIMARY KEY (CharacterId, ChallengeIndex)
            );
            INSERT INTO MonkChallengePerformanceSingle
            SELECT CharacterId,ChallengeIndex,0,Rating,BestScore,BestElapsedMinutes,FirstClear,UpdatedAt
            FROM (
                SELECT *,
                    MAX(BestRating) OVER (PARTITION BY CharacterId,ChallengeIndex) AS Rating,
                    MIN(ClearedAt) OVER (PARTITION BY CharacterId,ChallengeIndex) AS FirstClear,
                    ROW_NUMBER() OVER (PARTITION BY CharacterId,ChallengeIndex ORDER BY
                        BestScore DESC, BestElapsedMinutes IS NULL, BestElapsedMinutes,
                        UpdatedAt, Difficulty) AS Winner
                FROM MonkChallengePerformance
            ) WHERE Winner=1;
            DROP TABLE MonkChallengePerformance;
            ALTER TABLE MonkChallengePerformanceSingle RENAME TO MonkChallengePerformance;
            """;
        await command.ExecuteNonQueryAsync(token);
    }

    private static bool TryParseMonkChallengeSettlementId(
        string? settlementId, out long epoch, out long cycle)
    {
        epoch = cycle = 0;
        if (string.IsNullOrEmpty(settlementId)) return false;
        var separator = settlementId.IndexOf(':');
        return separator > 0
            && long.TryParse(settlementId.AsSpan(0, separator), NumberStyles.None,
                CultureInfo.InvariantCulture, out epoch)
            && long.TryParse(settlementId.AsSpan(separator + 1), NumberStyles.None,
                CultureInfo.InvariantCulture, out cycle)
            && epoch > 0 && cycle >= 0
            && settlementId == epoch.ToString(CultureInfo.InvariantCulture) + ":"
                + cycle.ToString(CultureInfo.InvariantCulture);
    }

    // The caller owns the transaction and has already verified the character,
    // solo membership, current epoch/cycle and frozen personal successful result.
    // Session identity defines room ownership; a session ID must never be reused.
    // Recovery may use an offline character only while both owning session IDs
    // remain null. The caller has authenticated the original settlement identity.
    // This method neither commits nor disposes the caller's transaction. Results
    // become durable only with that transaction's commit; exceptions must roll it back.
    internal static async Task<MonkChallengeCommitResult> CommitMonkChallengeSuccessAsync(
        SqliteConnection connection, SqliteTransaction transaction,
        long characterId, string sessionId, NativeDungeonSettlementRecord settlement,
        CancellationToken token = default, bool recovering = false)
    {
        ArgumentNullException.ThrowIfNull(connection);
        ArgumentNullException.ThrowIfNull(transaction);
        if (transaction.Connection != connection)
            throw new ArgumentException("The transaction must belong to the supplied connection.", nameof(transaction));
        if (characterId <= 0 || string.IsNullOrWhiteSpace(sessionId)
            || settlement.Rating is < DungeonRewardPolicy.ClearRatingD or > DungeonRewardPolicy.ClearRatingS
            || settlement.LogicalDifficulty != 0 || settlement.Score < 0
            || settlement.StageRecordScore < settlement.Score
            || !TryParseMonkChallengeSettlementId(settlement.SettlementId, out var epoch, out var cycle)
            || !MonkChallengePolicy.TryGetChallengeIndex(settlement.HdIndex, settlement.Episode,
                settlement.Dungeon, settlement.Stage, out var index))
            return new(MonkChallengeCommitStatus.InvalidSettlement, 0, false);
        if (!MonkChallengePolicy.IsPlayableTuple(settlement.HdIndex, settlement.Episode,
            settlement.Dungeon, settlement.Stage))
            return new(MonkChallengeCommitStatus.ChallengeClosed, 0, false);

        SqliteCommand Command(string sql)
        {
            token.ThrowIfCancellationRequested();
            var command = connection.CreateCommand();
            command.Transaction = transaction;
            command.CommandText = sql;
            command.Parameters.AddWithValue("$id", characterId);
            command.Parameters.AddWithValue("$session", sessionId);
            command.Parameters.AddWithValue("$settlement", settlement.SettlementId!);
            command.Parameters.AddWithValue("$epoch", epoch);
            command.Parameters.AddWithValue("$cycle", cycle);
            command.Parameters.AddWithValue("$recover", recovering ? 1 : 0);
            return command;
        }

        await using (var owner = Command("""
            SELECT 1 FROM Characters c JOIN Accounts a ON a.Id=c.AccountId
            WHERE c.Id=$id AND a.IsBanned=0
              AND ((c.IsOnline=1 AND c.ActiveSessionId=$session
                    AND a.IsOnline=1 AND a.ActiveSessionId=$session)
                   OR ($recover=1 AND c.ActiveSessionId IS NULL AND a.ActiveSessionId IS NULL))
            """))
            if (await owner.ExecuteScalarAsync(token) is null)
                return new(MonkChallengeCommitStatus.Unauthorized, 0, false);

        await EnsureMonkChallengeSchemaAsync(connection, transaction, token);
        byte previous = 0;
        await using (var read = Command("SELECT ClearMask FROM CharacterMonkChallenges WHERE CharacterId=$id"))
            if (await read.ExecuteScalarAsync(token) is long mask) previous = checked((byte)mask);

        // The service rejects stale cycles even before the first success. This
        // durable check additionally rejects older successes after database reopen.
        await using (var newer = Command("""
            SELECT 1 FROM MonkChallengeCommits
            WHERE CharacterId=$id AND SessionId=$session
              AND (BattleEpoch>$epoch OR (BattleEpoch=$epoch AND SettlementCycle>$cycle)) LIMIT 1
            """))
            if (await newer.ExecuteScalarAsync(token) is not null)
                return new(MonkChallengeCommitStatus.StaleSettlement, previous, false);

        await using (var receipt = Command("""
            INSERT INTO MonkChallengeCommits
                (CharacterId,SessionId,SettlementId,BattleEpoch,SettlementCycle,ChallengeIndex,Rating,CommittedAt)
            VALUES ($id,$session,$settlement,$epoch,$cycle,$index,$rating,$now)
            ON CONFLICT(CharacterId,SessionId,SettlementId) DO NOTHING
            """))
        {
            receipt.Parameters.AddWithValue("$index", index);
            receipt.Parameters.AddWithValue("$rating", settlement.Rating);
            receipt.Parameters.AddWithValue("$now", DateTime.UtcNow.ToString("O"));
            if (await receipt.ExecuteNonQueryAsync(token) == 0)
                return new(MonkChallengeCommitStatus.Duplicate, previous, false);
        }

        var bit = (byte)(1 << index);
        var next = (byte)(previous | bit);
        await using (var write = Command("""
            INSERT INTO CharacterMonkChallenges (CharacterId,ClearMask,UpdatedAt) VALUES ($id,$mask,$now)
            ON CONFLICT(CharacterId) DO UPDATE SET ClearMask=ClearMask|excluded.ClearMask, UpdatedAt=excluded.UpdatedAt
            """))
        {
            write.Parameters.AddWithValue("$mask", next);
            write.Parameters.AddWithValue("$now", DateTime.UtcNow.ToString("O"));
            await write.ExecuteNonQueryAsync(token);
        }
        // A successful solo result supplies the score; do not manufacture
        // scores for historical clear bits/receipts or unknown elapsed times.
        await using (var performance = Command("""
            INSERT INTO MonkChallengePerformance
                (CharacterId,ChallengeIndex,Difficulty,BestRating,BestScore,BestElapsedMinutes,ClearedAt,UpdatedAt)
            VALUES($id,$index,0,$rating,$score,NULL,$now,$now)
            ON CONFLICT(CharacterId,ChallengeIndex) DO UPDATE SET
                BestRating=MAX(MonkChallengePerformance.BestRating,excluded.BestRating),
                BestElapsedMinutes=CASE WHEN excluded.BestScore>MonkChallengePerformance.BestScore
                    THEN excluded.BestElapsedMinutes ELSE MonkChallengePerformance.BestElapsedMinutes END,
                BestScore=MAX(MonkChallengePerformance.BestScore,excluded.BestScore),
                UpdatedAt=CASE WHEN excluded.BestScore>MonkChallengePerformance.BestScore
                    THEN excluded.UpdatedAt ELSE MonkChallengePerformance.UpdatedAt END
            """))
        {
            performance.Parameters.AddWithValue("$index", index);
            performance.Parameters.AddWithValue("$rating", settlement.Rating);
            performance.Parameters.AddWithValue("$score", settlement.StageRecordScore ?? settlement.Score);
            performance.Parameters.AddWithValue("$now", DateTime.UtcNow.ToString("O"));
            await performance.ExecuteNonQueryAsync(token);
        }
        // No currencies, EXP, inventory, title or main-story progress are changed.
        return new(MonkChallengeCommitStatus.Applied, next, (previous & bit) == 0);
    }

    internal async Task<byte[]> GetMonkChallengeBestRatingsAsync(long characterId, CancellationToken token = default)
    {
        var ratings = new byte[4];
        if (characterId <= 0) return ratings;
        await using var connection = await OpenConnectionAsync(token);
        await using var command = connection.CreateCommand();
        command.CommandText = "SELECT 1 FROM sqlite_master WHERE type='table' AND name='MonkChallengePerformance'";
        if (await command.ExecuteScalarAsync(token) is null) return ratings;
        command.CommandText = """
            SELECT ChallengeIndex,BestRating FROM MonkChallengePerformance WHERE CharacterId=$id AND Difficulty=0
            """;
        command.Parameters.AddWithValue("$id", characterId);
        await using var reader = await command.ExecuteReaderAsync(token);
        while (await reader.ReadAsync(token))
            ratings[reader.GetInt32(0)] = (byte)Math.Clamp(reader.GetInt32(1) - 2, 0, 3);
        return ratings;
    }

    internal async Task<byte> GetMonkChallengeReadyRoomRankAsync(long characterId,
        byte episode, byte difficulty, CancellationToken token = default)
    {
        if (characterId <= 0 || !MonkChallengePolicy.IsReservedEpisode(episode) || difficulty != 0) return 0;
        await using var connection = await OpenConnectionAsync(token);
        await using var command = connection.CreateCommand();
        command.CommandText = "SELECT 1 FROM sqlite_master WHERE type='table' AND name='MonkChallengePerformance'";
        if (await command.ExecuteScalarAsync(token) is null) return 0;
        command.CommandText = """
            SELECT BestRating FROM MonkChallengePerformance
            WHERE CharacterId=$id AND ChallengeIndex=$index AND Difficulty=0
            """;
        command.Parameters.AddWithValue("$id", characterId);
        command.Parameters.AddWithValue("$index", episode - MonkChallengePolicy.FirstEpisode);
        var value = await command.ExecuteScalarAsync(token);
        return value is null or DBNull ? (byte)0 : (byte)Math.Clamp(Convert.ToInt32(value) - 2, 0, 3);
    }

    // Login reads all four bits independently of main-story progress. Missing
    // tables read as zero, including when the database is opened read-only.
    public async Task<MonkChallengeProgressResult> GetMonkChallengeClearMaskAsync(
        long accountId, long characterId, CancellationToken token = default)
    {
        if (accountId <= 0 || characterId <= 0) return default;
        await using var connection = await OpenConnectionAsync(token);
        await using var command = connection.CreateCommand();
        command.CommandText = "SELECT 1 FROM Characters WHERE Id=$id AND AccountId=$account";
        command.Parameters.AddWithValue("$id", characterId);
        command.Parameters.AddWithValue("$account", accountId);
        if (await command.ExecuteScalarAsync(token) is null) return default;
        command.CommandText = "SELECT 1 FROM sqlite_master WHERE type='table' AND name='CharacterMonkChallenges'";
        if (await command.ExecuteScalarAsync(token) is null) return new(true, 0);
        command.CommandText = "SELECT ClearMask FROM CharacterMonkChallenges WHERE CharacterId=$id";
        var value = await command.ExecuteScalarAsync(token);
        return new(true, value is long mask ? checked((byte)mask) : (byte)0);
    }
}
