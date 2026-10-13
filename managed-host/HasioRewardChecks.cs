using System.Buffers.Binary;
using System.Reflection;
using Microsoft.Data.Sqlite;
using OpenNanaimo.Adapter.Models;
using OpenNanaimo.Adapter.Services;

internal static class HasioRewardChecks
{
    internal static async Task RunAsync()
    {
        var root = Path.Combine(Path.GetTempPath(), "nanaimo-hasio-" + Guid.NewGuid().ToString("N"));
        Directory.CreateDirectory(root);
        try
        {
            File.WriteAllBytes(Path.Combine(root, "game.db"), []);
            var db = new DatabaseService(root);
            await db.InitializeAsync();
            var account = await db.OpenLocalAccountAsync("hasio-check");
            var characterId = await db.CreateLocalCharacterAsync(account, "HasioCheck", 1);
            await using var adapter = new NetworkAdapterService(db, Console.WriteLine, root);
            var type = typeof(NetworkAdapterService);
            var session = Activator.CreateInstance(type.GetNestedType("ConnectionSession", BindingFlags.NonPublic)!, true)!;
            var sessionId = (string)Get("SessionId")!;
            Check(await db.BeginWorldSessionAsync(account, characterId, sessionId, 1, "127.0.0.1"), "session authorized");
            await using var sql = new SqliteConnection($"Data Source={db.DatabasePath}");
            await sql.OpenAsync();
            async Task Execute(string text)
            {
                await using var command = sql.CreateCommand();
                command.CommandText = text;
                command.Parameters.AddWithValue("$id", characterId);
                await command.ExecuteNonQueryAsync();
            }
            async Task<long> Scalar(string text)
            {
                await using var command = sql.CreateCommand();
                command.CommandText = text;
                command.Parameters.AddWithValue("$id", characterId);
                return Convert.ToInt64(await command.ExecuteScalarAsync() ?? 0L);
            }
            async Task Reset(int medals = 12, bool legacy = false)
            {
                await Execute("""
                    DELETE FROM CharacterQuickSlots WHERE CharacterId=$id;
                    DELETE FROM CharacterItems WHERE CharacterId=$id;
                    DELETE FROM CharacterCards WHERE CharacterId=$id;
                    DELETE FROM CharacterStoryClaims WHERE CharacterId=$id;
                    DELETE FROM CharacterStoryGuides WHERE CharacterId=$id;
                    UPDATE Characters SET TutorialCompleted=1,Hans=500,CurrentHp=100,CurrentMp=50 WHERE Id=$id;
                    INSERT INTO CharacterStoryGuides VALUES($id,0,0,'fixture');
                    """);
                for (var index = 0; index < medals; index++)
                    await Execute($"INSERT INTO CharacterStoryClaims VALUES($id,{71_000_000 + index},'fixture')");
                if (legacy) await Execute("INSERT INTO CharacterStoryGuides VALUES($id,6,1,'old-build')");
                Set("Character", (await db.GetCharacterAsync(account))!);
            }
            object? Get(string name) => session.GetType().GetProperty(name, BindingFlags.Instance | BindingFlags.Public | BindingFlags.NonPublic)!.GetValue(session);
            void Set(string name, object? value) => session.GetType().GetProperty(name, BindingFlags.Instance | BindingFlags.Public | BindingFlags.NonPublic)!.SetValue(session, value);
            Set("AccountId", account); Set("Username", "hasio-check"); Set("ChannelId", 1);
            Set("ListenerPort", 12050); Set("OnlineTracked", true); Set("TownSceneActive", true);
            var dispatch = type.GetMethod("HandleNativeFrameAsync", BindingFlags.Instance | BindingFlags.NonPublic)!;
            ushort sequence = 1;
            async Task<byte[]> Send(ushort opcode, byte[] payload)
            {
                var frame = NativeDungeonClient.Frame(opcode, payload);
                BinaryPrimitives.WriteUInt16LittleEndian(frame, sequence++);
                return await (Task<byte[]?>)dispatch.Invoke(adapter,
                    [frame, opcode, "WorldAdapter", "127.0.0.1:30000", "127.0.0.1", session, CancellationToken.None])!
                    ?? throw new InvalidDataException("Missing Hasio response");
            }
            var request = new byte[80];
            BinaryPrimitives.WriteUInt16LittleEndian(request, 7);
            BinaryPrimitives.WriteUInt32LittleEndian(request.AsSpan(4), 6);
            request.AsSpan(8).Fill(0xA5);
            Task<(bool Authorized, bool Success, bool RewardPending, CharacterRecord? Character)> Claim(ushort kind = 7)
                => db.CompleteStoryGuideAsync(account, characterId, sessionId, 6, kind);
            async Task CheckUnchanged(string name, bool legacy = false)
            {
                Check(await Scalar("SELECT Hans FROM Characters WHERE Id=$id") == 500
                    && await Scalar("SELECT COUNT(*) FROM CharacterItems WHERE CharacterId=$id") == 0
                    && await Scalar("SELECT COUNT(*) FROM CharacterStoryGuides WHERE CharacterId=$id AND GuideId=6") == (legacy ? 1 : 0), name);
            }

            Check(HasioRewardPolicy.TryLoad(root, out var policy)
                && policy.Hans == 10_000 && policy.Items.Single() == new HasioRewardEntry(14_002_486u, 10)
                && policy.Cards.Single() == new HasioRewardEntry(12_000_002u, 5), "default is explicit local policy with valid catalog entries");
            await Reset(11);
            Check(!(await Claim()).Success, "eleven medals cannot exchange");
            await CheckUnchanged("ineligible exchange leaves wallet and ledger intact");
            await Reset();
            Check(!(await Claim(0)).Success, "guide six requires type seven");
            Check(!(await db.CompleteStoryGuideAsync(account, characterId, "foreign-session", 6, 7)).Authorized, "foreign session cannot claim");
            await Execute("UPDATE Characters SET TutorialCompleted=0 WHERE Id=$id");
            Check(!(await Claim()).Success, "tutorial eligibility enforced");
            await Reset();
            await Execute("DELETE FROM CharacterStoryGuides WHERE CharacterId=$id");
            Check(!(await Claim()).Success, "intro eligibility enforced");

            await Reset();
            await Execute("INSERT INTO CharacterItems(CharacterId,ItemCode,Quantity,UpdatedAt) VALUES($id,14002497,1,'fixture'); INSERT INTO CharacterQuickSlots VALUES($id,0,14002497,0,'fixture');");
            Set("Character", (await db.GetCharacterAsync(account))!);
            var reply = await Send(0xC599, request);
            Check(Opcodes(reply).SequenceEqual(new ushort[] { 0xC59A, 0xC430, 0xC379 })
                && reply[8] == 0 && reply[9] == 1 && reply[10] == 1
                && U32(reply, 12) == 6 && U16(reply, 16) == 7, "request-driven success carries wallet/card invalidation then inventory and quick slots");
            Check(await Scalar("SELECT Hans FROM Characters WHERE Id=$id") == 10_500
                && await Scalar("SELECT Quantity FROM CharacterItems WHERE CharacterId=$id AND ItemCode=14002486") == 10
                && await Scalar("SELECT Quantity FROM CharacterCards WHERE CharacterId=$id AND CardCode=12000002") == 5,
                "entire default bundle is granted, SP cards go to the album");
            Check(await Scalar("SELECT InventoryIndex FROM CharacterQuickSlots WHERE CharacterId=$id AND Slot=0") == 10,
                "existing quick-slot identity survives inserted potions");
            var state = await db.GetStoryGuideStateAsync(account, characterId, sessionId);
            Check(state.Medals == 100 && (state.Mask & 0x40) != 0
                && await Scalar("SELECT RewardPending FROM CharacterStoryGuides WHERE CharacterId=$id AND GuideId=6") == 0,
                "only committed delivery projects redeemed sentinel and completed guide");
            var repeats = await Task.WhenAll(Claim(), Claim());
            Check(repeats.All(result => result.Success && !result.RewardPending)
                && await Scalar("SELECT Hans FROM Characters WHERE Id=$id") == 10_500
                && await Scalar("SELECT Quantity FROM CharacterCards WHERE CharacterId=$id AND CardCode=12000002") == 5,
                "concurrent/repeated exchange cannot duplicate rewards");
            reply = await Send(0xC599, request);
            Check(Opcodes(reply).SequenceEqual(new ushort[] { 0xC59A }) && reply[9] == 0 && reply[10] == 0,
                "duplicate wire request acknowledges without refresh or regrant");
            var profile = await Send(0xC354, []);
            Check(FindFrame(profile, 0xC355)[0xF3] == 100, "reconnect restores redeemed medal sentinel");

            await Reset(legacy: true);
            state = await db.GetStoryGuideStateAsync(account, characterId, sessionId);
            profile = await Send(0xC354, []);
            Check(state.Medals == 12 && (state.Mask & 0x40) == 0 && FindFrame(profile, 0xC355)[0xF3] == 12
                && (U32(FindFrame(profile, 0xC594), 8) & 0x40) == 0,
                "old unpaid epilogue reopens the native Hasio entry without unsolicited grant");
            Check((await Claim()).Success && (await Claim()).Success
                && await Scalar("SELECT Hans FROM Characters WHERE Id=$id") == 10_500,
                "legacy pending debt is paid exactly once on claim");

            await Reset();
            await Execute("INSERT INTO CharacterItems(CharacterId,ItemCode,Quantity,UpdatedAt) VALUES($id,14002497,75,'fixture')");
            reply = await Send(0xC599, request);
            Check(reply[8] == 3 && reply.AsSpan(9).ToArray().All(value => value == 0)
                && await Scalar("SELECT Hans FROM Characters WHERE Id=$id") == 500
                && await Scalar("SELECT COUNT(*) FROM CharacterStoryGuides WHERE CharacterId=$id AND GuideId=6") == 0,
                "full inventory returns recoverable failure and preserves twelve medals");
            await Execute("UPDATE CharacterItems SET Quantity=74 WHERE CharacterId=$id");
            Check((await Claim()).Success, "exact 84-row inventory boundary accepts the entire bundle");

            await Reset(legacy: true);
            await Execute("INSERT INTO CharacterCards VALUES($id,12000002,251,'fixture')");
            Check(!(await Claim()).Success && (await db.GetStoryGuideStateAsync(account, characterId, sessionId)).Medals == 12,
                "album overflow keeps legacy reward pending and exchange available");
            await CheckUnchanged("card overflow rolls back wallet/items/legacy receipt", legacy: true);
            await Execute("UPDATE CharacterCards SET Quantity=250 WHERE CharacterId=$id");
            Check((await Claim()).Success && await Scalar("SELECT Quantity FROM CharacterCards WHERE CharacterId=$id AND CardCode=12000002") == 255,
                "exact card capacity grants without clamping");

            await Reset();
            await Execute("UPDATE Characters SET Hans=9223372036854775807 WHERE Id=$id");
            Check(!(await Claim()).Success && await Scalar("SELECT COUNT(*) FROM CharacterStoryGuides WHERE CharacterId=$id AND GuideId=6") == 0,
                "wallet overflow rejects rather than corrupting or consuming the reward");
            await Reset();
            await Execute("CREATE TRIGGER hasio_reject BEFORE INSERT ON CharacterItems WHEN NEW.ItemCode=14002486 BEGIN SELECT RAISE(IGNORE); END;");
            Check(!(await Claim()).Success, "failed item grant aborts claim");
            await CheckUnchanged("mid-transaction failure rolls back credited gold and completion");
            await Execute("DROP TRIGGER hasio_reject");

            var config = Path.Combine(root, HasioRewardPolicy.FileName);
            foreach (var invalid in new[]
            {
                "not-json", "{\"Version\":1,\"Hans\":0,\"Items\":[],\"Cards\":[]}",
                "{\"Version\":1,\"Hans\":1,\"Hans\":2,\"Items\":[],\"Cards\":[]}",
                "{\"Version\":1,\"Hans\":-1,\"Items\":[],\"Cards\":[]}",
                "{\"Version\":1,\"Hans\":1,\"Items\":[{\"Code\":1,\"Quantity\":1}],\"Cards\":[]}",
                "{\"Version\":1,\"Hans\":1,\"Items\":[],\"Cards\":[{\"Code\":12000002,\"Quantity\":256}]}",
                "{\"Version\":1,\"Hans\":1,\"Items\":[],\"Cards\":[{\"Code\":12000002,\"Quantity\":1},{\"Code\":12000002,\"Quantity\":1}]}"
            })
            {
                await File.WriteAllTextAsync(config, invalid);
                Check(!(await Claim()).Success, "invalid policy never falls back to success/default");
                await CheckUnchanged("invalid policy preserves claim");
            }
            await File.WriteAllTextAsync(config, "{\"Version\":1,\"Hans\":123,\"Items\":[],\"Cards\":[{\"Code\":12000002,\"Quantity\":2}]}");
            Check((await Claim()).Success && await Scalar("SELECT Hans FROM Characters WHERE Id=$id") == 623
                && await Scalar("SELECT Quantity FROM CharacterCards WHERE CharacterId=$id AND CardCode=12000002") == 2,
                "operator policy is applied atomically");
            await File.WriteAllTextAsync(config, "invalid-after-commit");
            Check((await Claim()).Success && await Scalar("SELECT Hans FROM Characters WHERE Id=$id") == 623,
                "committed receipt is independent of subsequent policy edits");
            var reopened = new DatabaseService(root);
            await reopened.InitializeAsync();
            Check(await reopened.BeginWorldSessionAsync(account, characterId, sessionId, 1, "127.0.0.1")
                && (await reopened.GetStoryGuideStateAsync(account, characterId, sessionId)).Medals == 100
                && (await reopened.CompleteStoryGuideAsync(account, characterId, sessionId, 6, 7)).Success,
                "database reopen preserves paid receipt without regrant");
            Console.WriteLine("HASIO_REWARD_CHECKS_PASS");
        }
        finally
        {
            SqliteConnection.ClearAllPools();
            var target = Path.GetFullPath(root);
            var temporary = Path.GetFullPath(Path.GetTempPath()).TrimEnd(Path.DirectorySeparatorChar)
                + Path.DirectorySeparatorChar;
            if (!target.StartsWith(temporary, StringComparison.OrdinalIgnoreCase)
                || !Path.GetFileName(target).StartsWith("nanaimo-hasio-", StringComparison.Ordinal))
                throw new InvalidOperationException("Unexpected Hasio fixture path.");
            Directory.Delete(root, true);
        }
    }

    private static ushort U16(byte[] frame, int offset) => BinaryPrimitives.ReadUInt16LittleEndian(frame.AsSpan(offset));
    private static uint U32(byte[] frame, int offset) => BinaryPrimitives.ReadUInt32LittleEndian(frame.AsSpan(offset));
    private static IEnumerable<ushort> Opcodes(byte[] frames)
    {
        for (var offset = 0; offset < frames.Length; offset += U16(frames, offset + 4))
            yield return U16(frames, offset + 6);
    }
    private static byte[] FindFrame(byte[] frames, ushort opcode)
    {
        for (var offset = 0; offset < frames.Length; offset += U16(frames, offset + 4))
            if (U16(frames, offset + 6) == opcode) return frames.AsSpan(offset, U16(frames, offset + 4)).ToArray();
        throw new InvalidDataException($"Missing frame {opcode:X4}");
    }
    private static void Check(bool passed, string name)
    {
        if (!passed) throw new InvalidDataException("HASIO_CHECK_FAILED " + name);
        Console.WriteLine("HASIO_CHECK_PASS " + name);
    }
}
