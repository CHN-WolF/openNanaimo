using System.Buffers.Binary;
using System.Reflection;
using Microsoft.Data.Sqlite;
using OpenNanaimo.Adapter.Models;
using OpenNanaimo.Adapter.Services;

internal static partial class Program
{
    private static async Task CheckRoomListsAsync()
    {
        var empty = ArenaProtocol.BuildRoomList([]);
        Check(empty.Length == 4 && BinaryPrimitives.ReadUInt32LittleEndian(empty) == 0,
            "empty room list initializes the count without any rows");
        var entries = Enumerable.Range(1, 4).Select(count => new ArenaRoomListEntry(
            (ushort)(100 + count), "Room" + count, count == 2 ? "secret" : "",
            (byte)count, count == 4)).ToArray();
        var payload = ArenaProtocol.BuildRoomList(entries);
        Check(payload.Length == 4 + 40 * entries.Length
            && BinaryPrimitives.ReadUInt32LittleEndian(payload) == entries.Length,
            "room list uses the exact count and 40-byte stride");
        for (var i = 0; i < entries.Length; i++)
        {
            var row = payload.AsSpan(4 + 40 * i, 40).ToArray();
            Check(BinaryPrimitives.ReadUInt16LittleEndian(row.AsSpan(34)) == i + 1
                && row[36] == 0 && row[37] == i + 1,
                "client display WORD holds member count while adjacent bytes keep their prior construction");
            Check(BinaryPrimitives.ReadUInt16LittleEndian(row.AsSpan(38)) == entries[i].RoomId
                && row[32] == (entries[i].Started ? 20 : 10) && row[33] == 100
                && row.AsSpan(24, 8).ToArray().Any(b => b != 0) == (i == 1),
                "member count preserves room identity, state and password");
        }

        var root = Path.Combine(Path.GetTempPath(), "nanaimo-arena-list-" + Guid.NewGuid().ToString("N"));
        Directory.CreateDirectory(root);
        try
        {
            File.WriteAllBytes(Path.Combine(root, "game.db"), []);
            var database = new DatabaseService(root);
            await database.InitializeAsync();
            await using var service = new NetworkAdapterService(database, _ => { }, root);
            const BindingFlags flags = BindingFlags.Instance | BindingFlags.NonPublic;
            var type = typeof(NetworkAdapterService);
            var sessionType = type.GetNestedType("ConnectionSession", BindingFlags.NonPublic)!;
            object Call(string name, params object?[] args)
                => type.GetMethod(name, flags)!.Invoke(service, args)!;
            object Session(long id, int gameType = 4, int channel = 1)
            {
                var session = Activator.CreateInstance(sessionType, true)!;
                sessionType.GetProperty("Character")!.SetValue(session, new CharacterRecord { Id = id, Name = "P" + id });
                sessionType.GetProperty("ArenaGameType")!.SetValue(session, (byte)gameType);
                sessionType.GetProperty("ChannelId")!.SetValue(session, channel);
                return session;
            }
            var owner = Session(1);
            var observer = Session(2);
            var members = new[] { owner, Session(3), Session(4), Session(5) };
            foreach (var metadata in new ushort[] { 0, 1, 200 })
            {
                var room = Call("CreateArenaRoom", owner,
                    new ArenaCreateRequest(new byte[44], "Arena", "", 0, 0, metadata, 0, 0, 0));
                var roomId = checked((ushort)(int)room.GetType().GetProperty("Id")!.GetValue(room)!);
                void Count(int expected)
                {
                    var list = (byte[])Call("BuildArenaRoomListPayload", observer);
                    Check(list.Length == 44 && BinaryPrimitives.ReadUInt16LittleEndian(list.AsSpan(38)) == expected
                        && BinaryPrimitives.ReadUInt16LittleEndian(list.AsSpan(42)) == roomId,
                        $"production room list reports {expected}/4 independently of create metadata {metadata}");
                }
                Count(1);
                for (var i = 1; i < members.Length; i++)
                {
                    Check((bool)Call("TryJoinArenaRoom", members[i], roomId, "", null), "arena member joins");
                    Count(i + 1);
                }
                Check(!(bool)Call("TryJoinArenaRoom", observer, roomId, "", null), "full room rejects a fifth member");
                Count(4);
                foreach (var excluded in new[] { Session(6, 3), Session(7, 4, 2) })
                    Check(((byte[])Call("BuildArenaRoomListPayload", excluded)).Length == 4,
                        "room lists isolate other game types and channels");
                for (var i = members.Length - 1; i >= 1; i--)
                {
                    Call("RemoveArenaRoomMember", members[i], null);
                    Count(i);
                }
                Call("RemoveArenaRoomMember", owner, null);
                Check(((byte[])Call("BuildArenaRoomListPayload", observer)).Length == 4,
                    "last departure removes the room from the list");
            }
        }
        finally
        {
            SqliteConnection.ClearAllPools();
            if (!Path.GetFullPath(root).StartsWith(Path.GetFullPath(Path.GetTempPath()), StringComparison.OrdinalIgnoreCase))
                throw new InvalidOperationException("Invalid test workspace.");
            Directory.Delete(root, true);
        }
    }
}
