using System.Buffers.Binary;
using System.Collections;
using System.Net;
using System.Net.Sockets;
using System.Reflection;
using OpenNanaimo.Adapter.Models;
using OpenNanaimo.Adapter.Services;

internal static partial class Program
{
    private static async Task CheckDeliveryEpochsAsync()
    {
        var root = Path.Combine(Path.GetTempPath(), "nanaimo-arena-delivery-" + Guid.NewGuid().ToString("N"));
        Directory.CreateDirectory(root);
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
        var owner = Actor(27); var guest = Actor(29);
        var room = Invoke(service, "CreateArenaRoom", owner,
            new ArenaCreateRequest(new byte[44], "Arena", "", 0, 0, 0, 0, 0, 0))!;
        Check((bool)Invoke(service, "TryJoinArenaRoom", guest, checked((ushort)(int)Get(room, "Id")!), "", null)!,
            "delivery epoch fixture joins one room");
        var oldEpoch = (Guid)Get(guest, "ArenaDeliveryEpoch")!;
        Set(room, "GameDataPayload", ArenaProtocol.BuildGameData(0, 1));
        foreach (var actor in new[] { owner, guest })
        {
            Set(actor, "ArenaReady", true);
            Set(actor, "P2PInfoRegistered", true);
            Set(actor, "ArenaP2PProtocolConfirmed", true);
        }
        Check((bool)Invoke(service, "TryStartArenaRoom", owner, "")!, "delivery fixture starts");
        Task<byte[]?> Send(object actor, ushort opcode, byte[] payload) =>
            (Task<byte[]?>)Invoke(service, "HandleNativeFrameAsync", NativeDungeonClient.Frame(opcode, payload),
                opcode, "ArenaAdapter", "127.0.0.1:30000", "127.0.0.1", actor, CancellationToken.None)!;
        await Send(owner, 0xD034, [30, 0, 10, 0, 100, 0, 0, 0]);
        var pending = (IList)Get(owner, "PendingSessionBroadcasts")!;
        var oldPickup = pending.Cast<object>().Single(b => (ushort)Get(b, "Opcode")! == 0xD035);
        Check((Guid?)Get(oldPickup, "ArenaDeliveryEpoch") == oldEpoch,
            "arena gameplay broadcast records its original delivery epoch");

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
            var writeType = typeof(NetworkAdapterService).GetNestedType("OutboundNativeWrite", BindingFlags.NonPublic)!;
            var staleWrite = Activator.CreateInstance(writeType,
                [NativeDungeonClient.Frame(0xD015, new byte[16]), "ArenaAdapter", 22054, "127.0.0.1",
                    true, true, "old already-queued hit", oldEpoch, null, null])!;
            await (ValueTask)Invoke(service, "QueueOutboundWriteAsync", guest, staleWrite, timeout.Token)!;
            // Use the same direct-response queue path as the real connection loop.
            // A peer can reset while this recipient's writer still holds CF98.
            var staleEndResponse = await Send(guest, 0xCF97, []);
            Check(staleEndResponse is { Length: 8 }, "ending request creates a direct CF98 response");
            await (ValueTask)Invoke(service, "QueueDirectNativeResponseAsync", guest, staleEndResponse!,
                "ArenaAdapter", 22054, "127.0.0.1", true, timeout.Token)!;
            Set(room, "PvpResultPayload", new byte[4]);
            ((HashSet<string>)Get(room, "ResultSessionIds")!).Add(Id(owner));
            await Send(owner, 0xCF8B, [0, 1, 1, 0]);
            var currentEpoch = (Guid)Get(room, "DeliveryEpoch")!;
            Check(currentEpoch != oldEpoch, "shared rematch advances the delivery epoch separately from frozen results");
            Check(!(bool)Invoke(service, "IsCurrentArenaDelivery", guest, oldEpoch)!
                && (bool)Invoke(service, "IsCurrentArenaDelivery", guest, currentEpoch)!,
                "old gameplay and actor messages become invalid at rematch");
            await (Task)Invoke(service, "SendSessionBroadcastAsync", oldPickup, timeout.Token)!;
            var reset = pending.Cast<object>().Single(b => (ushort)Get(b, "Opcode")! == 0xCF8C
                && ReferenceEquals(Get(b, "Target"), guest));
            await (Task)Invoke(service, "SendSessionBroadcastAsync", reset, timeout.Token)!;
            var delayedResult = await Send(guest, 0xCF89, new byte[4]);
            Check(delayedResult is { Length: 12 }, "previous frozen result remains requestable before next start");
            await (ValueTask)Invoke(service, "QueueDirectNativeResponseAsync", guest, delayedResult!,
                "ArenaAdapter", 22054, "127.0.0.1", true, timeout.Token)!;
            Set(room, "GameDataPayload", ArenaProtocol.BuildGameData(0, 1));
            foreach (var actor in new[] { owner, guest })
            {
                Set(actor, "ArenaReady", true); Set(actor, "P2PInfoRegistered", true);
                Set(actor, "ArenaP2PProtocolConfirmed", true);
            }
            Check(await Send(owner, 0xCF7F, []) is null, "new-round first arrival still waits");
            var settlementGate = (SemaphoreSlim)Get(room, "SettlementGate")!;
            await settlementGate.WaitAsync(timeout.Token);
            var waitingResult = Send(owner, 0xCF89, new byte[4]);
            Check(!waitingResult.IsCompleted, "late previous-round result waits at the real settlement gate");
            byte[]? newStart;
            try
            {
                newStart = await Send(guest, 0xCF7F, []);
                Check(newStart is { Length: 8 }, "new-round final arrival produces current direct CF80");
                Check((Guid)Get(guest, "ArenaDeliveryEpoch")! == currentEpoch,
                    "start keeps ready-room delivery epoch while replacing terminal result round");
            }
            finally { settlementGate.Release(); }
            Check(await waitingResult is null && ((byte[])Get(room, "PvpResultPayload")!).Length == 0,
                "old settlement waiter cannot construct or freeze a result for the new round");
            await (ValueTask)Invoke(service, "QueueDirectNativeResponseAsync", guest, newStart!,
                "ArenaAdapter", 22054, "127.0.0.1", true, timeout.Token)!;
            var writes = Get(guest, "OutboundWrites")!;
            var writer = Get(writes, "Writer")!;
            writer.GetType().GetMethod("TryComplete")!.Invoke(writer, [null]);
            await (Task)Invoke(service, "RunOutboundWriterAsync", guest, sender.GetStream(), timeout.Token)!;
            var frame = new byte[56];
            var offset = 0;
            while (offset < frame.Length)
            {
                var read = await receiver.GetStream().ReadAsync(frame.AsMemory(offset), timeout.Token);
                Check(read > 0, "TCP writer delivers the current rematch response");
                offset += read;
            }
            Console.WriteLine("DELIVERY_WIRE " + Convert.ToHexString(frame));
            Check(BinaryPrimitives.ReadUInt16LittleEndian(frame.AsSpan(6)) == 0xCF8C
                && BinaryPrimitives.ReadUInt16LittleEndian(frame.AsSpan(54)) == 0xCF80
                && !receiver.GetStream().DataAvailable,
                "real TCP writer rejects stale direct CF98/CF8A and broadcast D015 but keeps CF8C/CF80");
            Check((byte)Get(guest, "ResponseTransportSequence")! == 2,
                "discarded frames consume no S2C sequence; only reset and new start advance it");
            Invoke(service, "RemoveArenaRoomMember", guest, null);
            Check(!(bool)Invoke(service, "IsCurrentArenaDelivery", guest, currentEpoch)!,
                "real room leave rejects the former room delivery epoch");
            Check(!(bool)Invoke(service, "IsCurrentArenaResponse", guest, newStart!)!,
                "direct start response is invalid after its recipient leaves");
            Set(room, "Started", false); // Return fixture to ready-room before testing rejoin.
            Check((bool)Invoke(service, "TryJoinArenaRoom", guest, checked((ushort)(int)Get(room, "Id")!), "", null)!,
                "same connection can rejoin after an explicit leave");
            Check(!(bool)Invoke(service, "IsCurrentArenaDelivery", guest, currentEpoch)!,
                "same-room rejoin does not authorize old queued frames for the reused connection");
            Check(!(bool)Invoke(service, "IsCurrentArenaResponse", guest, newStart!)!,
                "rejoining the same room cannot revive an old direct response");
            Set(room, "PvpResultPayload", new byte[4]);
            ((HashSet<string>)Get(room, "ResetSessionIds")!).Add(Id(guest));
            await settlementGate.WaitAsync(timeout.Token);
            var departedWaiter = Send(guest, 0xCF89, new byte[4]);
            Check(!departedWaiter.IsCompleted, "settlement waiter is captured before same-room leave/rejoin");
            try
            {
                Invoke(service, "RemoveArenaRoomMember", guest, null);
                Check((bool)Invoke(service, "TryJoinArenaRoom", guest,
                    checked((ushort)(int)Get(room, "Id")!), "", null)!, "waiting recipient can rejoin ready room");
            }
            finally { settlementGate.Release(); }
            Check(await departedWaiter is null, "old settlement task cannot attach to reused same-room membership");
        }
        finally
        {
            listener.Stop();
            if (!Path.GetFullPath(root).StartsWith(Path.GetFullPath(Path.GetTempPath()), StringComparison.OrdinalIgnoreCase))
                throw new InvalidOperationException("Unsafe test path.");
            Directory.Delete(root, true);
        }
    }
}
