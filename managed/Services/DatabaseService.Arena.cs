using Microsoft.Data.Sqlite;
using OpenNanaimo.Adapter.Models;

namespace OpenNanaimo.Adapter.Services;

internal sealed record ArenaRankingRecord(string Name, uint Score, ushort Level, ushort DungeonGrade);

public sealed partial class DatabaseService
{
    private static async Task InitializeArenaScoresAsync(SqliteConnection connection, CancellationToken token)
    {
        await using var command = connection.CreateCommand();
        command.CommandText = """
            CREATE TABLE IF NOT EXISTS ArenaRoundScores (
                CharacterId INTEGER NOT NULL REFERENCES Characters(Id) ON DELETE CASCADE,
                SettlementKey TEXT NOT NULL,
                Score INTEGER NOT NULL CHECK(Score BETWEEN 0 AND 4294967295),
                PlayedAt TEXT NOT NULL,
                PRIMARY KEY(CharacterId, SettlementKey));
            CREATE INDEX IF NOT EXISTS IX_ArenaRoundScores_PlayedAt ON ArenaRoundScores(PlayedAt);
            """;
        await command.ExecuteNonQueryAsync(token);
    }

    private static async Task SaveArenaScoreAsync(SqliteConnection connection, SqliteTransaction transaction,
        long characterId, string settlementKey, uint score, string now, CancellationToken token)
    {
        await using var command = connection.CreateCommand();
        command.Transaction = transaction;
        command.CommandText = """
            INSERT INTO ArenaRoundScores(CharacterId,SettlementKey,Score,PlayedAt)
            VALUES($id,$key,$score,$now)
            """;
        command.Parameters.AddWithValue("$id", characterId);
        command.Parameters.AddWithValue("$key", settlementKey);
        command.Parameters.AddWithValue("$score", (long)score);
        command.Parameters.AddWithValue("$now", now);
        await command.ExecuteNonQueryAsync(token);
    }

    internal async Task<IReadOnlyList<ArenaRankingRecord>> GetArenaRankingAsync(uint rankingType,
        DateTime? dayUtc = null, CancellationToken token = default)
    {
        if (rankingType is not (10u or 20u)) return [];
        var day = (dayUtc ?? DateTime.UtcNow).Date;
        await using var connection = await OpenConnectionAsync(token);
        await using var command = connection.CreateCommand();
        command.CommandText = """
            SELECT c.Id, c.Name, c.Level, MAX(s.Score) AS Points
            FROM ArenaRoundScores s JOIN Characters c ON c.Id=s.CharacterId
            WHERE ($total=1 OR (s.PlayedAt >= $start AND s.PlayedAt < $end))
            GROUP BY c.Id,c.Name,c.Level
            ORDER BY Points DESC, c.Id ASC LIMIT 10
            """;
        command.Parameters.AddWithValue("$total", rankingType == 20u ? 1 : 0);
        command.Parameters.AddWithValue("$start", DateTime.SpecifyKind(day, DateTimeKind.Utc).ToString("O"));
        command.Parameters.AddWithValue("$end", DateTime.SpecifyKind(day.AddDays(1), DateTimeKind.Utc).ToString("O"));
        var rows = new List<(long Id, string Name, ushort Level, uint Score)>();
        await using (var reader = await command.ExecuteReaderAsync(token))
            while (await reader.ReadAsync(token))
                rows.Add((reader.GetInt64(0), reader.GetString(1),
                    (ushort)Math.Clamp(reader.GetInt32(2), 1, CharacterProgression.MaximumLevel),
                    (uint)Math.Clamp(reader.GetInt64(3), 0, int.MaxValue)));
        var result = new List<ArenaRankingRecord>();
        foreach (var row in rows)
            result.Add(new ArenaRankingRecord(row.Name, row.Score, row.Level,
                await LoadDungeonGradeAsync(connection, row.Id, token)));
        return result;
    }
}
