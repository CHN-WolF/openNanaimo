using System.Buffers.Binary;
using System.Collections;
using System.Net;
using System.Net.Sockets;
using Microsoft.Data.Sqlite;
using OpenNanaimo.Adapter.Models;
using OpenNanaimo.Adapter.Services;

internal static partial class Program
{
    private static async Task CheckLoadingPhasesAsync()
    {
        var root = Path.Combine(Path.GetTempPath(), "nanaimo-arena-phase-" + Guid.NewGuid().ToString("N"));
        Directory.CreateDirectory(root);
        try
        {
            File.WriteAllBytes(Path.Combine(root, "game.db"), []);
            await using var service = new NetworkAdapterService(new DatabaseService(root), _ => { }, root);
            object Actor(long id)
            {
                var actor = Activator.CreateInstance(Session, true)!;
                Set(actor, "Character", new CharacterRecord { Id = id, Name = "P" + id });
                Set(actor, "OnlineTracked", true); Set(actor, "AuxiliaryGameSession", true);
                Set(actor, "ArenaGameType", (byte)4); Set(actor, "ChannelId", 1);
                return actor;
            }
            var owner = Actor(41); var guest = Actor(43);
            var room = Invoke(service, "CreateArenaRoom", owner,
                new ArenaCreateRequest(new byte[44], "Arena", "", 0, 0, 0, 0, 0, 0))!;
            Check((bool)Invoke(service, "TryJoinArenaRoom", guest,
                checked((ushort)(int)Get(room, "Id")!), "", null)!, "phase fixture joins");
            foreach (var actor in new[] { owner, guest })
            {
                Set(actor, "ArenaReady", true); Set(actor, "ArenaTeamCode", (byte)0);
                Set(actor, "P2PInfoRegistered", true);
                Set(actor, "P2PIpAddress", "127.0.0.1"); Set(actor, "P2PPort", (ushort)3534);
            }
            Task<byte[]?> Send(object actor, ushort opcode, byte[] payload) =>
                (Task<byte[]?>)Invoke(service, "HandleNativeFrameAsync", NativeDungeonClient.Frame(opcode, payload),
                    opcode, "ArenaAdapter", "127.0.0.1:30000", "127.0.0.1", actor, CancellationToken.None)!;
            var map = await Send(guest, 0xCFEB, [0, 0, 1, 0]);
            var protocol = await Send(guest, 0xCFD5, [1, 0, 0, 0]);
            var peers = await Send(guest, 0xCFD3, []);
            Check(map is { Length: 808 } && protocol is not null && peers is not null,
                "loading member receives map and peer initialization");
            await Send(owner, 0xCFD5, [1, 0, 0, 0]);
            using var timeout = new CancellationTokenSource(TimeSpan.FromSeconds(10));
            var listener = new TcpListener(IPAddress.Loopback, 0);
            listener.Start();
            try
            {
                using var receiver = new TcpClient();
                var accept = listener.AcceptTcpClientAsync();
                await receiver.ConnectAsync(IPAddress.Loopback, ((IPEndPoint)listener.LocalEndpoint).Port);
                using var sender = await accept;
                Set(guest, "Stream", sender.GetStream());
                foreach (var response in new[] { map!, protocol!, peers! })
                    await (ValueTask)Invoke(service, "QueueDirectNativeResponseAsync", guest, response,
                        "ArenaAdapter", 22054, "127.0.0.1", true, timeout.Token)!;
                Check(await Send(guest, 0xCF7F, []) is null, "first loading confirmation waits");
                foreach (var response in new[] { map!, protocol!, peers! })
                    Check(!(bool)Invoke(service, "IsCurrentArenaResponse", guest, response)!,
                        "confirmed member retires pending loading responses before shared start");
                foreach (var request in new (ushort Opcode, byte[] Data)[]
                    { (0xCFD3, []), (0xCFD5, [1, 0, 0, 0]), (0xCFEB, [0, 0, 1, 0]) })
                    Check(await Send(guest, request.Opcode, request.Data) is null,
                        "confirmed member keeps its loading barrier monotonic");
                var pending = (IList)Get(owner, "PendingSessionBroadcasts")!;
                pending.Clear();
                Check(await Send(owner, 0xCFEB, [0, 0, 1, 0]) is { Length: 808 },
                    "unconfirmed peer retains its map request");
                var mapBroadcast = pending.Cast<object>().Single(b => (ushort)Get(b, "Opcode")! == 0xCFEC);
                await (Task)Invoke(service, "SendSessionBroadcastAsync", mapBroadcast, timeout.Token)!;
                var start = await Send(owner, 0xCF7F, []);
                Check(start is { Length: 8 }, "last confirmation starts the round");
                foreach (var actor in new[] { owner, guest })
                foreach (var request in new (ushort Opcode, byte[] Data)[]
                    { (0xCFD3, []), (0xCFD5, [1, 0, 0, 0]), (0xCFEB, [0, 0, 1, 0]) })
                    Check(await Send(actor, request.Opcode, request.Data) is null,
                        "running round rejects loading-state reentry");
                var startBroadcast = pending.Cast<object>().Single(b => (ushort)Get(b, "Opcode")! == 0xCF80);
                await (Task)Invoke(service, "SendSessionBroadcastAsync", startBroadcast, timeout.Token)!;
                Check((bool)Invoke(service, "IsCurrentArenaResponse", owner, start!)!,
                    "direct start binds the newly created battle round");
                Set(room, "RoundId", Guid.NewGuid());
                Check(!(bool)Invoke(service, "IsCurrentArenaResponse", owner, start!)!,
                    "direct start retains its original battle round");
                var sentinel = NativeDungeonClient.Frame(0xCF8C, []);
                await (ValueTask)Invoke(service, "QueueDirectNativeResponseAsync", guest, sentinel,
                    "ArenaAdapter", 22054, "127.0.0.1", true, timeout.Token)!;
                var writes = Get(guest, "OutboundWrites")!;
                var writer = Get(writes, "Writer")!;
                writer.GetType().GetMethod("TryComplete")!.Invoke(writer, [null]);
                await (Task)Invoke(service, "RunOutboundWriterAsync", guest, sender.GetStream(), timeout.Token)!;
                var received = new byte[8];
                for (var offset = 0; offset < received.Length;)
                {
                    var read = await receiver.GetStream().ReadAsync(received.AsMemory(offset), timeout.Token);
                    Check(read > 0, "phase writer delivers current boundary");
                    offset += read;
                }
                Check(BinaryPrimitives.ReadUInt16LittleEndian(received.AsSpan(6)) == 0xCF8C
                    && !receiver.GetStream().DataAvailable && (byte)Get(guest, "ResponseTransportSequence")! == 1,
                    "final writer filters stale loading and round-scoped start before sequence allocation");
            }
            finally { listener.Stop(); }

            Set(room, "Started", false);
            ((IDictionary)Get(room, "LoadingRequestTags")!).Clear();
            Set(owner, "P2PInfoRegistered", false);
            ((IDictionary)Get(room, "P2PEndpointsBySession")!).Clear();
            var delayedPeers = Send(guest, 0xCFD3, []);
            Check(!delayedPeers.IsCompleted, "peer initialization has an asynchronous member wait");
            Set(guest, "ArenaDeliveryEpoch", Guid.NewGuid());
            Set(owner, "P2PInfoRegistered", true);
            var expiredPeers = await delayedPeers;
            Check(expiredPeers is not null && !(bool)Invoke(service, "IsCurrentArenaResponse", guest, expiredPeers)!,
                "asynchronous peer initialization retains the requesting membership epoch");
        }
        finally
        {
            SqliteConnection.ClearAllPools();
            Directory.Delete(root, true);
        }
    }
}
