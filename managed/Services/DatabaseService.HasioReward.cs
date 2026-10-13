using Microsoft.Data.Sqlite;

namespace OpenNanaimo.Adapter.Services;

public sealed partial class DatabaseService
{
    private static async Task<bool> GrantHasioRewardAsync(SqliteConnection connection,
        SqliteTransaction transaction, long characterId, HasioReward reward, CancellationToken token)
    {
        var before = await GetGameInventoryItemCodesAsync(connection, transaction, characterId, token);
        if (before.Count + reward.Items.Sum(entry => entry.Quantity) > 84) return false;

        await using var command = connection.CreateCommand();
        command.Transaction = transaction;
        command.Parameters.AddWithValue("$id", characterId);
        foreach (var entry in reward.Cards)
        {
            command.CommandText = "SELECT Quantity FROM CharacterCards WHERE CharacterId=$id AND CardCode=$code";
            command.Parameters.AddWithValue("$code", entry.Code);
            var quantity = Convert.ToInt64(await command.ExecuteScalarAsync(token) ?? 0L);
            command.Parameters.RemoveAt("$code");
            if (quantity < 0 || quantity + entry.Quantity > 255) return false;
        }

        // Keep SQLite arithmetic integral: reject overflow rather than converting
        // the wallet to REAL or completing the exchange with a truncated prize.
        command.Parameters.AddWithValue("$hans", reward.Hans);
        command.Parameters.AddWithValue("$limit", long.MaxValue - reward.Hans);
        command.Parameters.AddWithValue("$now", DateTime.UtcNow.ToString("O"));
        command.CommandText = """
            UPDATE Characters SET Hans=Hans+$hans,LastSavedAt=$now
            WHERE Id=$id AND typeof(Hans)='integer' AND Hans BETWEEN 0 AND $limit
            """;
        if (await command.ExecuteNonQueryAsync(token) != 1) return false;

        foreach (var entry in reward.Items.Concat(reward.Cards))
            for (var count = 0; count < entry.Quantity; count++)
                if (await GrantCardRewardAsync(connection, transaction, characterId, entry.Code, token)
                    != CardRewardGrant.Granted) return false;
        return await ReindexGameQuickSlotsAfterGrantAsync(connection, transaction, characterId, before, token);
    }
}
