using System.Globalization;

namespace OpenNanaimo.Adapter.Services;

public sealed partial class DatabaseService
{
    internal async Task<bool> AuthorizeMonkVillageTravelAsync(
        long accountId, long characterId, string sessionId, byte sourceTown, byte destinationTown,
        CancellationToken token = default)
    {
        if (sourceTown > 4 || destinationTown > 4) return false;
        if (destinationTown <= sourceTown) return true;
        await using var connection = await OpenConnectionAsync(token);
        await using var transaction = connection.BeginTransaction();
        await using var command = connection.CreateCommand();
        command.Transaction = transaction;
        command.CommandText = """
            SELECT 1 FROM Characters AS c JOIN Accounts AS a ON a.Id=c.AccountId
            WHERE c.Id=$character AND c.AccountId=$account
              AND c.IsOnline=1 AND a.IsOnline=1
              AND c.ActiveSessionId=$session AND a.ActiveSessionId=$session
            """;
        command.Parameters.AddWithValue("$character", characterId);
        command.Parameters.AddWithValue("$account", accountId);
        command.Parameters.AddWithValue("$session", sessionId);
        if (await command.ExecuteScalarAsync(token) is null) return false;
        command.CommandText = "SELECT 1 FROM sqlite_master WHERE type='table' AND name='CharacterMonkChallenges'";
        if (await command.ExecuteScalarAsync(token) is null) return false;
        command.CommandText = "SELECT ClearMask FROM CharacterMonkChallenges WHERE CharacterId=$character";
        var value = await command.ExecuteScalarAsync(token);
        if (value is null or DBNull) return false;
        var mask = Convert.ToInt32(value, CultureInfo.InvariantCulture);
        return mask is >= 0 and <= MonkChallengePolicy.FullClearMask
            && MonkChallengePolicy.CanTravelForward(sourceTown, destinationTown, (byte)mask);
    }
}
