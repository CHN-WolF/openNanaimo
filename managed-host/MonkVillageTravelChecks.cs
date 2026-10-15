using System.Buffers.Binary;
using System.Reflection;
using System.Text;
using Microsoft.Data.Sqlite;
using OpenNanaimo.Adapter.Services;

internal static class MonkVillageTravelChecks
{
    internal static async Task RunAsync()
    {
        Encoding.RegisterProvider(CodePagesEncodingProvider.Instance);
        var root = Path.Combine(Path.GetTempPath(), "open-nanaimo-monk-travel-" + Guid.NewGuid().ToString("N"));
        Directory.CreateDirectory(root);
        int checks = 0;
        void Check(bool condition, string label)
        {
            if (!condition) throw new InvalidOperationException(label);
            checks++;
        }
        try
        {
            using (File.Create(Path.Combine(root, "game.db"))) { }
            var db = new DatabaseService(root);
            await db.InitializeAsync();
            long account = await db.OpenLocalAccountAsync("monk-travel");
            await db.CreateLocalCharacterAsync(account, "MonkGate", 1);
            var character = (await db.GetCharacterAsync(account))!;
            await using var service = new NetworkAdapterService(db, _ => { }, root)
            { RequireMonkChallengeForVillageTravel = true, UnlockAllDungeons = true };
            var type = typeof(NetworkAdapterService);
            var sessionType = type.GetNestedType("ConnectionSession", BindingFlags.NonPublic)!;
            var dispatch = type.GetMethod("HandleNativeFrameAsync", BindingFlags.Instance | BindingFlags.NonPublic)!;
            object session = Activator.CreateInstance(sessionType, nonPublic: true)!;
            void Set(string name, object value) => sessionType.GetProperty(name)!.SetValue(session, value);
            object Get(string name) => sessionType.GetProperty(name)!.GetValue(session)!;
            var sessionId = (string)Get("SessionId");
            Check(await db.BeginWorldSessionAsync(account, character.Id, sessionId, 1, "127.0.0.1"), "online fixture");
            Set("AccountId", account);
            Set("Character", character);
            Set("ChannelId", 1);
            Set("ListenerPort", 12050);
            Set("OnlineTracked", true);
            character.TutorialCompleted = true;
            character.PositionX = 400;
            character.PositionY = 96;
            Set("LastReportedPositionX", (ushort)400);
            Set("LastReportedPositionY", (ushort)96);

            async Task Execute(string sql, int mask = 0)
            {
                await using var connection = new SqliteConnection($"Data Source={db.DatabasePath}");
                await connection.OpenAsync();
                await using var command = connection.CreateCommand();
                command.CommandText = sql;
                command.Parameters.AddWithValue("$id", character.Id);
                command.Parameters.AddWithValue("$mask", mask);
                await command.ExecuteNonQueryAsync();
            }
            await Execute("UPDATE Characters SET Hans=1000 WHERE Id=$id");
            character.Hans = 1000;
            async Task SetMask(int mask) => await Execute("""
                INSERT INTO CharacterMonkChallenges(CharacterId,ClearMask,UpdatedAt) VALUES($id,$mask,'fixture')
                ON CONFLICT(CharacterId) DO UPDATE SET ClearMask=excluded.ClearMask
                """, mask);
            void Source(byte town)
            {
                Set("TownId", town);
                Set("TownPage", (byte)6);
                Set("TownSceneActive", true);
                character.CurrentMapId = town;
                character.CurrentTownPage = 6;
            }
            async Task<byte[]> Travel(byte destination, byte mode)
            {
                var payload = new byte[10];
                payload[0] = destination;
                payload[4] = mode;
                BinaryPrimitives.WriteUInt16LittleEndian(payload.AsSpan(6), ushort.MaxValue);
                BinaryPrimitives.WriteUInt16LittleEndian(payload.AsSpan(8), ushort.MaxValue);
                var frame = NativeDungeonClient.Frame(0xC365, payload);
                return (await (Task<byte[]?>)dispatch.Invoke(service,
                    [frame, (ushort)0xC365, "WorldAdapter", "127.0.0.1:30000", "127.0.0.1", session, CancellationToken.None])!)!;
            }
            async Task Reject(byte source, byte destination, byte mode)
            {
                Source(source);
                var before = character.Hans;
                var response = await Travel(destination, mode);
                Check(response.Length == 12 && BinaryPrimitives.ReadUInt16LittleEndian(response.AsSpan(6)) == 0xC366
                    && response[8] == NetworkAdapterService.TownEnterStatusGenericFailure, "native generic rejection");
                Check(response[9] == source && response[10] == 6, "rejection retains source tuple");
                Check(character.Hans == before && (await db.GetCharacterAsync(account))!.Hans == before, "no rejected fare");
                Check((byte)Get("TownId") == source && (byte)Get("TownPage") == 6
                    && (bool)Get("TownSceneActive") && character.CurrentMapId == source
                    && character.CurrentTownPage == 6 && character.PositionX == 400 && character.PositionY == 96,
                    "rejection precedes scene teardown and preserves position");
            }

            // A pre-feature database has no entitlement; reading must not invent it.
            await Execute("DROP TABLE IF EXISTS CharacterMonkChallenges");
            await Reject(0, 1, 0);
            await db.InitializeMonkChallengesAsync();
            await Reject(0, 1, 1);
            for (byte source = 0; source < 4; source++)
                for (byte mode = 0; mode < 2; mode++)
                {
                    await SetMask(0);
                    await Reject(source, (byte)(source + 1), mode);
                    await SetMask(1 << source);
                    Source(source);
                    var before = character.Hans;
                    var response = await Travel((byte)(source + 1), mode);
                    var fare = TownTravelPolicy.ResolveFare(source, (byte)(source + 1), mode);
                    Check(response[8] == NetworkAdapterService.TownEnterStatusSuccess
                        && (byte)Get("TownId") == source + 1, "matching clear admits next village");
                    Check(character.Hans == before - fare && (await db.GetCharacterAsync(account))!.Hans == before - fare,
                        "authorized ride preserves original fare");
                }
            await SetMask(1);
            await Reject(0, 4, 0);
            await SetMask(15);
            Source(0);
            Check((await Travel(4, 0))[8] == 200, "all crossed boundaries required for direct travel");
            Check((await new DatabaseService(root).GetMonkChallengeClearMaskAsync(account, character.Id)).ClearMask == 15,
                "existing clear ledger survives reopen");
            Check(!await db.AuthorizeMonkVillageTravelAsync(account, character.Id, "stale", 0, 1), "stale session denied");
            Check(!await db.AuthorizeMonkVillageTravelAsync(account + 999, character.Id, sessionId, 0, 1), "foreign owner denied");
            await Execute("UPDATE Accounts SET ActiveSessionId='stale' WHERE Id=(SELECT AccountId FROM Characters WHERE Id=$id)");
            await Reject(0, 1, 0);
            await Execute("UPDATE Accounts SET ActiveSessionId=(SELECT ActiveSessionId FROM Characters WHERE Id=$id) WHERE Id=(SELECT AccountId FROM Characters WHERE Id=$id)");
            await SetMask(0);
            Source(4);
            Check((await Travel(3, 0))[8] == 200, "legacy return remains available");
            Source(3);
            Check((await Travel(3, 0))[8] == 200, "same village remains available");
            await Reject(0, 255, 0);
            service.RequireMonkChallengeForVillageTravel = false;
            Source(0);
            Check((await Travel(1, 0))[8] == 200, "disabled option retains existing travel policy");

            for (byte source = 0; source < 5; source++)
                for (byte destination = 0; destination < 5; destination++)
                    for (byte mask = 0; mask < 16; mask++)
                    {
                        bool expected = true;
                        for (int boundary = source; boundary < destination; boundary++)
                            expected &= (mask & (1 << boundary)) != 0;
                        Check(MonkChallengePolicy.CanTravelForward(source, destination, mask) == expected,
                            "all mask and village policy combinations");
                    }
            Console.WriteLine($"MONK_TRAVEL_CHECKS_PASS checks={checks} runtime_acceptance=false");
        }
        finally
        {
            SqliteConnection.ClearAllPools();
            Directory.Delete(root, recursive: true);
        }
    }
}
