using Microsoft.Data.Sqlite;

namespace OpenNanaimo.Adapter.Services;

public sealed partial class DatabaseService
{
    private static async Task InitializeEntertainmentScoresAsync(SqliteConnection connection, CancellationToken token)
    {
        await using var command = connection.CreateCommand();
        command.CommandText = """
            CREATE TABLE IF NOT EXISTS EntertainmentBestScores (
                CharacterId INTEGER NOT NULL REFERENCES Characters(Id) ON DELETE CASCADE,
                GameType INTEGER NOT NULL CHECK(GameType BETWEEN 1 AND 3),
                BestScore INTEGER NOT NULL CHECK(BestScore BETWEEN 0 AND 65535),
                UpdatedAt TEXT NOT NULL,
                PRIMARY KEY(CharacterId, GameType));
            """;
        await command.ExecuteNonQueryAsync(token);
    }

    internal async Task<uint> GetEntertainmentBestScoreAsync(long characterId, byte gameType, CancellationToken token = default)
    {
        if (characterId <= 0 || gameType is < 1 or > 3) return 0;
        await using var connection = await OpenConnectionAsync(token);
        await using var command = connection.CreateCommand();
        command.CommandText = "SELECT BestScore FROM EntertainmentBestScores WHERE CharacterId=$id AND GameType=$game";
        command.Parameters.AddWithValue("$id", characterId);
        command.Parameters.AddWithValue("$game", gameType);
        var result = await command.ExecuteScalarAsync(token);
        return result is null ? 0 : checked((uint)Convert.ToInt64(result));
    }

    internal async Task<IReadOnlyList<EntertainmentRankingEntry>> GetEntertainmentRankingAsync(
        byte gameType, ushort page, CancellationToken token = default)
    {
        if (gameType is < 1 or > 3) return [];
        await using var connection = await OpenConnectionAsync(token);
        await using var command = connection.CreateCommand();
        command.CommandText = """
            SELECT c.Name,s.BestScore FROM EntertainmentBestScores s
            JOIN Characters c ON c.Id=s.CharacterId
            WHERE s.GameType=$game AND s.BestScore>0
            ORDER BY s.BestScore DESC,s.CharacterId ASC LIMIT 10 OFFSET $offset
            """;
        command.Parameters.AddWithValue("$game", gameType);
        command.Parameters.AddWithValue("$offset", (long)page * 10);
        var rows = new List<EntertainmentRankingEntry>();
        await using var reader = await command.ExecuteReaderAsync(token);
        while (await reader.ReadAsync(token))
            rows.Add(new EntertainmentRankingEntry(reader.GetString(0), checked((uint)reader.GetInt64(1))));
        return rows;
    }

    private static async Task<int> GetEntertainmentPetExperienceAsync(SqliteConnection connection,
        SqliteTransaction transaction, long characterId, uint petCode, int place, int memberCount, CancellationToken token)
    {
        if (!ShopCatalog.TryGet(15, petCode, out var pet)) return 0;
        var current = pet.PetModelStage;
        var maximum = pet.PetUpgradeStage;
        await using var command = connection.CreateCommand();
        command.Transaction = transaction;
        command.CommandText = """
            SELECT PetCurrentStage, PetMaximumStage FROM CharacterInventoryInstances
            WHERE CharacterId=$id AND ItemCode=$pet AND Quantity>0
                AND PetInstanceId=(SELECT EquippedPetInstanceId FROM Characters WHERE Id=$id)
            """;
        command.Parameters.AddWithValue("$id", characterId);
        command.Parameters.AddWithValue("$pet", petCode);
        await using var reader = await command.ExecuteReaderAsync(token);
        if (await reader.ReadAsync(token))
        {
            if (reader.GetInt32(0) > 0) current = checked((byte)reader.GetInt32(0));
            if (reader.GetInt32(1) > 0) maximum = checked((byte)reader.GetInt32(1));
        }
        var state = new PetState(petCode, current, maximum, 0, 0, 0, 0, 0, pet.PetMaxDurability);
        return checked((int)EntertainmentRewardPolicy.GetPetExperience(state, place, memberCount));
    }

    private static async Task SaveEntertainmentBestScoreAsync(SqliteConnection connection, SqliteTransaction transaction,
        long characterId, byte gameType, int score, string now, CancellationToken token)
    {
        await using var command = connection.CreateCommand();
        command.Transaction = transaction;
        command.CommandText = """
            INSERT INTO EntertainmentBestScores(CharacterId,GameType,BestScore,UpdatedAt)
            VALUES($id,$game,$score,$now)
            ON CONFLICT(CharacterId,GameType) DO UPDATE SET
                BestScore=MAX(EntertainmentBestScores.BestScore,excluded.BestScore),
                UpdatedAt=CASE WHEN excluded.BestScore>EntertainmentBestScores.BestScore
                    THEN excluded.UpdatedAt ELSE EntertainmentBestScores.UpdatedAt END
            """;
        command.Parameters.AddWithValue("$id", characterId);
        command.Parameters.AddWithValue("$game", gameType);
        command.Parameters.AddWithValue("$score", score);
        command.Parameters.AddWithValue("$now", now);
        await command.ExecuteNonQueryAsync(token);
    }
}
