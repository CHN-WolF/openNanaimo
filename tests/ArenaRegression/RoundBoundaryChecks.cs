using System.Buffers.Binary;
using System.Collections;
using System.Text;
using Microsoft.Data.Sqlite;
using OpenNanaimo.Adapter.Models;
using OpenNanaimo.Adapter.Services;

internal static partial class Program
{
    private static async Task CheckRoundBoundariesAsync()
    {
        var root = Path.Combine(Path.GetTempPath(), "nanaimo-arena-boundaries-" + Guid.NewGuid().ToString("N"));
        Directory.CreateDirectory(root);
        try
        {
            File.WriteAllBytes(Path.Combine(root, "game.db"), []);
            var database = new DatabaseService(root);
            await database.InitializeAsync();
            await using var service = new NetworkAdapterService(database, _ => { }, root);
            object Actor(long id)
            {
                var actor = Activator.CreateInstance(Session, true)!;
                Set(actor, "Character", new CharacterRecord { Id = id, Name = "P" + id });
                Set(actor, "OnlineTracked", true); Set(actor, "AuxiliaryGameSession", true);
                Set(actor, "ArenaGameType", (byte)4); Set(actor, "ChannelId", 1);
                return actor;
            }
            var owner = Actor(27);
            var guest = Actor(29);
            var create = new ArenaCreateRequest(new byte[44], "Arena", "", 0, 0, 0, 0, 0, 0);
            var room = Invoke(service, "CreateArenaRoom", owner, create)!;
            Check((bool)Invoke(service, "TryJoinArenaRoom", guest, checked((ushort)(int)Get(room, "Id")!), "", null)!,
                "round-boundary guest joins");
            Task<byte[]?> Send(object actor, ushort opcode, byte[] payload, byte tag = 0)
            {
                var frame = NativeDungeonClient.Frame(opcode, payload);
                frame[0] = tag;
                return (Task<byte[]?>)Invoke(service, "HandleNativeFrameAsync", frame, opcode,
                    "ArenaAdapter", "127.0.0.1:30000", "127.0.0.1", actor, CancellationToken.None)!;
            }
            IList Pending(object actor) => (IList)Get(actor, "PendingSessionBroadcasts")!;
            object[] Messages(object actor, object target, ushort opcode) => Pending(actor).Cast<object>()
                .Where(b => ReferenceEquals(Get(b, "Target"), target) && (ushort)Get(b, "Opcode")! == opcode).ToArray();
            async Task Register(object actor, ushort port)
            {
                var endpoint = new byte[20];
                Encoding.ASCII.GetBytes("127.0.0.1").CopyTo(endpoint, 0);
                BinaryPrimitives.WriteUInt32LittleEndian(endpoint.AsSpan(16), port);
                Check(await Send(actor, 0xCFD1, endpoint) is { Length: 12 }, "room endpoint registers through CFD1");
            }
            async Task Roster(int round)
            {
                Pending(owner).Clear(); Pending(guest).Clear();
                Check(await Send(owner, 0xCF70, new byte[4]) is { Length: 184 }, "owner requests current ready-room actor");
                Check(Messages(owner, guest, 0xCF71).Length == 0, "uninitialized peer receives no early ready-room actor");
                Check(await Send(guest, 0xCF70, new byte[4]) is { Length: 184 }, "guest requests current ready-room actor");
                foreach (var pair in new[] { (Recipient: owner, Uid: (ushort)29), (Recipient: guest, Uid: (ushort)27) })
                {
                    var rows = Messages(guest, pair.Recipient, 0xCF71);
                    Check(rows.Length == 1 && ((byte[])Get(rows[0], "Payload")!).Length == 176
                        && BinaryPrimitives.ReadUInt16LittleEndian(((byte[])Get(rows[0], "Payload")!).AsSpan(0x12)) == pair.Uid,
                        $"round {round} restores exactly one peer CF71 for each viewer");
                }
                Pending(owner).Clear(); Pending(guest).Clear();
                await Send(owner, 0xCF70, new byte[4]); await Send(guest, 0xCF70, new byte[4]);
                Check(!Pending(owner).Cast<object>().Concat(Pending(guest).Cast<object>())
                    .Any(b => (ushort)Get(b, "Opcode")! == 0xCF71), "duplicate current-round roster does not recreate peers");
                Pending(owner).Clear(); Pending(guest).Clear();
                await Send(owner, 0xCFD9, []); await Send(guest, 0xCFD9, []);
                Check(Messages(owner, guest, 0xCFDA).Length == 1 && Messages(guest, owner, 0xCFDA).Length == 1,
                    $"round {round} reactivates both peer actors from their own CFD9");
                Pending(owner).Clear(); Pending(guest).Clear();
                await Send(owner, 0xCFD9, []); await Send(guest, 0xCFD9, []);
                Check(Pending(owner).Count == 0 && Pending(guest).Count == 0, "duplicate actor activation is not rebroadcast");
            }
            async Task Start(int round)
            {
                await Send(owner, 0xCF7D, [1, 0, 0, 0]); await Send(guest, 0xCF7D, [1, 0, 0, 0]);
                Check(await Send(owner, 0xCFEB, [0, 0, 1, 0]) is { Length: 808 }, "current room publishes complete game data");
                await Send(owner, 0xCFD5, [1, 0, 0, 0]); await Send(guest, 0xCFD5, [1, 0, 0, 0]);
                Pending(owner).Clear(); Pending(guest).Clear();
                var first = round % 2 == 0 ? guest : owner;
                var last = ReferenceEquals(first, owner) ? guest : owner;
                Check(await Send(first, 0xCF7F, [], 7) is null && !(bool)Get(room, "Started")!,
                    "first member waits without an unsolicited start");
                Check(await Send(last, 0xCF7F, [], 19) is { Length: 8 } && (bool)Get(room, "Started")!,
                    "last current-room member releases the loading barrier");
                var starts = Messages(last, first, 0xCF80);
                Check(starts.Length == 1 && (byte?)Get(starts[0], "RequestTag") == 7,
                    "waiting member receives its own request-qualified start");
            }
            await Register(owner, 3534); await Register(guest, 3535);
            for (var round = 1; round <= 3; round++)
            {
                await Roster(round); await Start(round);
                Set(room, "PvpResultPayload", new byte[4]);
                ((HashSet<string>)Get(room, "ResultSessionIds")!).Add(Id(owner));
                Check(await Send(owner, 0xCF8B, [0, 1, 1, 0]) is { Length: 48 }, "authorized rematch retains the shared room");
                Check(((HashSet<string>)Get(room, "EntityInitializedSessions")!).Count == 0
                    && ((HashSet<string>)Get(room, "EntityAnnouncements")!).Count == 0,
                    "rematch retires the previous ready-room roster epoch");
                Check(!(bool)Get(owner, "ArenaMulticastInitialized")! && !(bool)Get(guest, "ArenaMulticastInitialized")!,
                    "rematch retires previous actor activation");
                Check((bool)Get(owner, "P2PInfoRegistered")! && (bool)Get(guest, "P2PInfoRegistered")!,
                    "same-room rematch does not require another CFD1");
            }
            Invoke(service, "RemoveArenaRoomMember", owner, null); Invoke(service, "RemoveArenaRoomMember", guest, null);
            room = Invoke(service, "CreateArenaRoom", owner, create)!;
            Check((bool)Invoke(service, "TryJoinArenaRoom", guest, checked((ushort)(int)Get(room, "Id")!), "", null)!,
                "same connections form a distinct room after settlement leave");
            Check(!(bool)Get(owner, "P2PInfoRegistered")! && !(bool)Get(guest, "P2PInfoRegistered")!,
                "actual room leave clears both old endpoints");
            await Register(owner, 3534); await Register(guest, 3535);
            await Roster(4); await Start(4);
        }
        finally
        {
            SqliteConnection.ClearAllPools();
            Directory.Delete(root, true);
        }
    }
}
