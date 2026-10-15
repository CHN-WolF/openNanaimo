using System.Globalization;
using System.Text.Json;
using Microsoft.Data.Sqlite;
using OpenNanaimo.Adapter.Services;

internal static partial class Program
{
    private sealed class Fixture : IAsyncDisposable
    {
        internal string Root { get; }
        internal DatabaseService Database { get; }
        private readonly string connectionString;

        private Fixture(string root)
        {
            Root = root;
            Database = new(root);
            connectionString = new SqliteConnectionStringBuilder
            {
                DataSource = Database.DatabasePath, ForeignKeys = true,
                Mode = SqliteOpenMode.ReadWrite, DefaultTimeout = 15
            }.ToString();
        }

        internal static async Task<Fixture> Create()
        {
            var root = Path.Combine(Path.GetTempPath(), "NanaimoMonkRegression", Guid.NewGuid().ToString("N"));
            Directory.CreateDirectory(root);
            using (File.Create(Path.Combine(root, "game.db"))) { }
            var fixture = new Fixture(root);
            await fixture.Database.InitializeAsync();
            return fixture;
        }

        internal async Task<Actor> Actor(string name)
        {
            var account = await Database.OpenLocalAccountAsync(name);
            await Database.CreateLocalCharacterAsync(account, name, 0);
            var character = (await Database.GetCharacterAsync(account))!;
            var actor = new Actor(account, character.Id, Guid.NewGuid().ToString("N"));
            Check(await Database.BeginWorldSessionAsync(account, character.Id, actor.SessionId, 1, "127.0.0.1"),
                "owned world session for " + name);
            return actor;
        }

        internal async Task<SqliteConnection> Open()
        {
            var connection = new SqliteConnection(connectionString);
            await connection.OpenAsync();
            return connection;
        }

        internal async Task<MonkChallengeCommitResult> Commit(
            Actor actor, NativeDungeonSettlementRecord result, bool recovering = false)
        {
            await using var connection = await Open();
            await using var tx = connection.BeginTransaction();
            var committed = await DatabaseService.CommitMonkChallengeSuccessAsync(
                connection, tx, actor.CharacterId, actor.SessionId, result, recovering: recovering);
            await tx.CommitAsync();
            return committed;
        }

        internal async Task Execute(SqliteConnection connection, SqliteTransaction tx, string sql, long id)
        {
            await using var command = connection.CreateCommand();
            command.Transaction = tx;
            command.CommandText = sql;
            command.Parameters.AddWithValue("$id", id);
            await command.ExecuteNonQueryAsync();
        }

        internal async Task Update(string sql, long id)
        {
            await using var connection = await Open();
            await using var tx = connection.BeginTransaction();
            await Execute(connection, tx, sql, id);
            await tx.CommitAsync();
        }

        internal async Task<object?> Scalar(string sql, long id)
        {
            await using var connection = await Open();
            await using var command = connection.CreateCommand();
            command.CommandText = sql;
            command.Parameters.AddWithValue("$id", id);
            return await command.ExecuteScalarAsync();
        }

        internal async Task<long> CountTables()
        {
            await using var connection = await Open();
            await using var command = connection.CreateCommand();
            command.CommandText = "SELECT COUNT(*) FROM sqlite_master WHERE type='table' AND name IN ('CharacterMonkChallenges','MonkChallengeCommits')";
            return (long)(await command.ExecuteScalarAsync())!;
        }

        internal async Task<long> ReceiptCount(long id)
        {
            await using var connection = await Open();
            await using var command = connection.CreateCommand();
            command.CommandText = "SELECT COUNT(*) FROM MonkChallengeCommits WHERE CharacterId=$id";
            command.Parameters.AddWithValue("$id", id);
            return (long)(await command.ExecuteScalarAsync())!;
        }

        internal async Task<string> UnrelatedState()
        {
            await using var connection = await Open();
            var names = new List<string>();
            await using (var command = connection.CreateCommand())
            {
                command.CommandText = """
                    SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'
                      AND name NOT IN ('CharacterMonkChallenges','MonkChallengeCommits','MonkChallengePerformance') ORDER BY name
                    """;
                await using var reader = await command.ExecuteReaderAsync();
                while (await reader.ReadAsync()) names.Add(reader.GetString(0));
            }
            var state = new Dictionary<string, List<string[]>>();
            foreach (var name in names)
            {
                await using var command = connection.CreateCommand();
                command.CommandText = "SELECT * FROM [" + name.Replace("]", "]]") + "] ORDER BY rowid";
                await using var reader = await command.ExecuteReaderAsync();
                var rows = new List<string[]>();
                while (await reader.ReadAsync())
                    rows.Add(Enumerable.Range(0, reader.FieldCount).Select(i => reader.GetValue(i) is byte[] bytes
                        ? Convert.ToHexString(bytes) : Convert.ToString(reader.GetValue(i), CultureInfo.InvariantCulture)!).ToArray());
                state[name] = rows;
            }
            return JsonSerializer.Serialize(state);
        }

        public ValueTask DisposeAsync()
        {
            SqliteConnection.ClearAllPools();
            var boundary = Path.GetFullPath(Path.Combine(Path.GetTempPath(), "NanaimoMonkRegression"))
                + Path.DirectorySeparatorChar;
            if (!Path.GetFullPath(Root).StartsWith(boundary, StringComparison.OrdinalIgnoreCase))
                throw new InvalidOperationException("Unsafe regression cleanup path.");
            Directory.Delete(Root, recursive: true);
            return ValueTask.CompletedTask;
        }
    }
}
