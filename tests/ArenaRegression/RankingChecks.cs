using System.Buffers.Binary;
using System.Text;
using Microsoft.Data.Sqlite;
using OpenNanaimo.Adapter.Models;
using OpenNanaimo.Adapter.Services;

internal static partial class Program
{
    private static async Task CheckRankingAsync()
    {
        var payload = ArenaProtocol.BuildRanking(10, [new("ID-name", 12345, 200, 39)]);
        Check(payload.Length == 364 && BinaryPrimitives.ReadUInt32LittleEndian(payload) == 10,
            "CF18 initializes all ten 36-byte rows without a row-count field");
        Check(Encoding.ASCII.GetString(payload, 4, 7) == "ID-name"
            && BinaryPrimitives.ReadUInt32LittleEndian(payload.AsSpan(28)) == 12345
            && BinaryPrimitives.ReadUInt16LittleEndian(payload.AsSpan(36)) == 200
            && BinaryPrimitives.ReadUInt16LittleEndian(payload.AsSpan(38)) == 39,
            "ranking ID, score, Lv text and dungeon-title icon have independent carriers");
        Check(payload.AsSpan(40).ToArray().All(b => b == 0)
            && BinaryPrimitives.ReadUInt32LittleEndian(payload.AsSpan(32)) == 0,
            "unused ranking rows and uninterpreted DWORD are initialized");
        Check(BinaryPrimitives.ReadUInt32LittleEndian(ArenaProtocol.BuildRanking(20,
            [new("bounded", uint.MaxValue, 1, 0)]).AsSpan(28)) == int.MaxValue,
            "ranking score respects the signed client formatter");

        var root = Path.Combine(Path.GetTempPath(), "nanaimo-arena-ranking-" + Guid.NewGuid().ToString("N"));
        Directory.CreateDirectory(root);
        try
        {
            File.WriteAllBytes(Path.Combine(root, "game.db"), []);
            var database = new DatabaseService(root);
            await database.InitializeAsync();
            Check((await database.GetArenaRankingAsync(20)).Count == 0, "fresh database has no invented ranking scores");
            var characters = new List<CharacterRecord>();
            var sessions = new List<string>();
            for (var i = 0; i < 12; i++)
            {
                var account = await database.OpenLocalAccountAsync("ranking" + i);
                await database.CreateLocalCharacterAsync(account, "Rank" + i, 0);
                var character = (await database.GetCharacterAsync(account))!;
                var session = Guid.NewGuid().ToString("N");
                Check(await database.BeginWorldSessionAsync(character.AccountId, character.Id, session, 1, "127.0.0.1"),
                    "ranking fixture authenticates the reward owner");
                characters.Add(character); sessions.Add(session);
            }
            Task<CharacterRecord?> Reward(int i, string key, uint score, string? session = null) => database.ApplyDungeonRewardAsync(
                characters[i].AccountId, characters[i].Id, session ?? sessions[i], 0, 0, 0, 0, 0, 0,
                10, 0, 0, completed: false, activitySettlementKey: "arena:" + key, arenaScore: score);
            Check(await Reward(0, "invalid-session", 99999, "stale") is null,
                "stale world session cannot add ranking points or rewards");
            for (var i = 0; i < 12; i++)
                Check(await Reward(i, "round-one", (uint)(100 + i)) is not null, "authoritative settlement records one arena score");
            var before = (await database.GetCharacterByIdAsync(characters[0].Id))!.Experience;
            await Reward(0, "round-one", 99999);
            Check((await database.GetCharacterByIdAsync(characters[0].Id))!.Experience == before,
                "duplicate score settlement also preserves exactly-once experience");
            await Reward(0, "round-two", 500);
            var total = await database.GetArenaRankingAsync(20);
            Check(total.Count == 10 && total[0].Name == "Rank0" && total[0].Score == 500
                && total[1].Name == "Rank11" && total[1].Score == 111,
                "total ranking keeps the best single round, sorts descending and bounds the top ten");
            await using (var connection = new SqliteConnection(new SqliteConnectionStringBuilder { DataSource = database.DatabasePath }.ToString()))
            {
                await connection.OpenAsync();
                await using var command = connection.CreateCommand();
                command.CommandText = "UPDATE ArenaRoundScores SET PlayedAt=$old WHERE CharacterId=$id AND SettlementKey='arena:round-two'";
                command.Parameters.AddWithValue("$old", DateTime.UtcNow.AddDays(-1).ToString("O"));
                command.Parameters.AddWithValue("$id", characters[0].Id);
                await command.ExecuteNonQueryAsync();
                command.Parameters.Clear();
                command.CommandText = "CREATE TRIGGER arena_test_failure BEFORE INSERT ON ArenaRoundScores BEGIN SELECT RAISE(ABORT,'arena rollback'); END";
                await command.ExecuteNonQueryAsync();
                try
                {
                    await Reward(0, "failed-round", 700);
                    Check(false, "injected ranking write failure must reject settlement");
                }
                catch (SqliteException) { }
                Check((await database.GetCharacterByIdAsync(characters[0].Id))!.Experience == before + 10,
                    "ranking write failure rolls back the entire reward transaction");
                command.CommandText = "DROP TRIGGER arena_test_failure";
                await command.ExecuteNonQueryAsync();
                Check(await Reward(0, "failed-round", 700) is not null,
                    "rolled-back receipt does not consume retry eligibility");
            }
            var today = await database.GetArenaRankingAsync(10);
            Check(today[0].Name == "Rank0" && today[0].Score == 700,
                "today ranking excludes previous UTC dates without erasing lifetime best scores");
            Check((await database.GetArenaRankingAsync(10, DateTime.UtcNow.AddDays(1))).Count == 0
                && (await database.GetArenaRankingAsync(20))[0].Score == 700,
                "day rollover isolates the daily board while preserving the lifetime board");
            await using var service = new NetworkAdapterService(database, _ => { }, root);
            var actor = Activator.CreateInstance(Session, true)!;
            Set(actor, "Character", characters[0]); Set(actor, "OnlineTracked", true);
            Set(actor, "AuxiliaryGameSession", true); Set(actor, "ArenaGameType", (byte)4);
            var request = new byte[4]; BinaryPrimitives.WriteUInt32LittleEndian(request, 20);
            var response = await (Task<byte[]?>)Invoke(service, "HandleNativeFrameAsync",
                NativeDungeonClient.Frame(0xCF17, request), (ushort)0xCF17, "ArenaAdapter",
                "127.0.0.1:30000", "127.0.0.1", actor, CancellationToken.None)!;
            Check(response is { Length: 372 } && BinaryPrimitives.ReadUInt16LittleEndian(response.AsSpan(6)) == 0xCF18
                && BinaryPrimitives.ReadUInt32LittleEndian(response.AsSpan(36)) == 700,
                "production CF17 dispatcher returns the persistent ranking with the full safe length");
            var reopened = new DatabaseService(root);
            Check((await reopened.GetArenaRankingAsync(20))[0].Score == 700,
                "ranking survives database-service recreation");
        }
        finally
        {
            SqliteConnection.ClearAllPools();
            Directory.Delete(root, true);
        }
    }
}
