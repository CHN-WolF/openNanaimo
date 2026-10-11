using System.Collections;
using Microsoft.Data.Sqlite;
using OpenNanaimo.Adapter.Models;
using OpenNanaimo.Adapter.Services;

internal static partial class Program
{
    private static async Task CheckReentryAsync()
    {
        var root = Path.Combine(Path.GetTempPath(), "nanaimo-arena-reentry-" + Guid.NewGuid().ToString("N"));
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
                Set(actor, "OnlineTracked", true);
                Set(actor, "AuxiliaryGameSession", true);
                Set(actor, "ArenaGameType", (byte)4);
                Set(actor, "ChannelId", 1);
                return actor;
            }
            var owner = Actor(1);
            var guest = Actor(2);
            var room = Invoke(service, "CreateArenaRoom", owner,
                new ArenaCreateRequest(new byte[44], "Arena", "", 0, 0, 0, 0, 0, 0))!;
            var roomId = checked((ushort)(int)Get(room, "Id")!);
            Check((bool)Invoke(service, "TryJoinArenaRoom", guest, roomId, "", null)!, "reentry guest joins");
            foreach (var actor in new[] { owner, guest })
            {
                Set(actor, "ArenaReady", true);
                Set(actor, "ArenaTeamCode", (byte)0);
                Set(actor, "P2PIpAddress", "127.0.0.1");
                Set(actor, "P2PPort", (ushort)3534);
                Set(actor, "P2PInfoRegistered", true);
                Set(actor, "ArenaP2PProtocolConfirmed", true);
            }
            Set(room, "GameDataPayload", ArenaProtocol.BuildGameData(0, 1));
            Check((bool)Invoke(service, "TryStartArenaRoom", owner, "")!, "reentry fixture starts initial round");
            Set(room, "PvpResultPayload", new byte[4]);
            ((HashSet<string>)Get(room, "ResultSessionIds")!).Add(Id(owner));
            Task<byte[]?> Send(object actor, ushort opcode, byte[] payload, byte tag = 0)
            {
                var frame = NativeDungeonClient.Frame(opcode, payload);
                frame[0] = tag;
                return (Task<byte[]?>)Invoke(service, "HandleNativeFrameAsync", frame, opcode,
                    "ArenaAdapter", "127.0.0.1:30000", "127.0.0.1", actor, CancellationToken.None)!;
            }
            Check(await Send(owner, 0xCF8B, [0, 1, 1, 0]) is { Length: 48 }, "one confirm resets the shared room");
            Check((int)Get(owner, "ArenaRoomId")! == roomId && (int)Get(guest, "ArenaRoomId")! == roomId,
                "result confirm retains both memberships and the listed room");
            Check((bool)Get(owner, "P2PInfoRegistered")! && (ushort)Get(owner, "P2PPort")! == 3534,
                "same-connection reset preserves the owner endpoint without another CFD1");
            Check(!(bool)Get(owner, "ArenaP2PProtocolConfirmed")!, "new round requires a fresh protocol confirmation");
            // A client-side rematch cleanup can clear the session's endpoint
            // fields even though the room connection remains valid. The room
            // epoch must still be able to reconstruct the loading tuple.
            Set(owner, "P2PIpAddress", null); Set(owner, "P2PPort", (ushort)0);
            Set(owner, "P2PInfoRegistered", false); Set(owner, "ArenaP2PProtocolConfirmed", false);
            Set(owner, "ArenaReady", true); Set(guest, "ArenaReady", true);
            Set(owner, "ArenaTeamCode", (byte)0); Set(guest, "ArenaTeamCode", (byte)0);
            Check(await Send(owner, 0xCFEB, [0, 0, 1, 0]) is { Length: 808 },
                "same-room rematch republishes game data after endpoint cleanup");
            await Send(owner, 0xCFD5, [1, 0, 0, 0]);
            await Send(guest, 0xCFD5, [1, 0, 0, 0]);
            Check(await Send(guest, 0xCF7F, [], 7) is null && !(bool)Get(room, "Started")!,
                "endpoint recovery keeps the first rematch CF7F waiting");
            Check(await Send(owner, 0xCF7F, [], 19) is { Length: 8 }
                && (bool)Get(room, "Started")!
                && (bool)Get(owner, "P2PInfoRegistered")!,
                "endpoint recovery releases the second-round loading barrier");
            Set(room, "PvpResultPayload", new byte[4]);
            ((HashSet<string>)Get(room, "ResultSessionIds")!).Add(Id(owner));
            Check(await Send(owner, 0xCF8B, [0, 1, 1, 0]) is { Length: 48 },
                "endpoint recovery round can be reset normally");
            Invoke(service, "RemoveArenaRoomMember", guest, null);
            Check(!(bool)Get(guest, "P2PInfoRegistered")!, "real leave clears the departed endpoint");
            Check((bool)Invoke(service, "TryJoinArenaRoom", guest, roomId, "", null)!, "departed guest can rejoin the same listed room");
            Set(guest, "P2PIpAddress", "127.0.0.1"); Set(guest, "P2PPort", (ushort)3535);
            Set(guest, "P2PInfoRegistered", true);
            Set(guest, "ArenaReady", true); Set(guest, "ArenaTeamCode", (byte)0);
            Set(owner, "ArenaTeamCode", (byte)0);
            Check(await Send(owner, 0xCFEB, [0, 0, 1, 0]) is { Length: 808 }, "reentry publishes new game data");
            await Send(owner, 0xCFD5, [1, 0, 0, 0]);
            await Send(guest, 0xCFD5, [1, 0, 0, 0]);
            ((IList)Get(owner, "PendingSessionBroadcasts")!).Clear();
            ((IList)Get(guest, "PendingSessionBroadcasts")!).Clear();
            Check(await Send(guest, 0xCF7F, [], 7) is null && !(bool)Get(room, "Started")!,
                "guest-first CF7F waits at the current loading barrier");
            var started = await Send(owner, 0xCF7F, [], 19);
            Check(started is { Length: 8 } && started[0] == 19 && (bool)Get(room, "Started")!,
                "owner completion releases both members without an unsolicited early start");
            var queued = ((IList)Get(owner, "PendingSessionBroadcasts")!).Cast<object>()
                .Where(b => (ushort)Get(b, "Opcode")! == 0xCF80).ToArray();
            Check(queued.Length == 1 && ReferenceEquals(Get(queued[0], "Target"), guest)
                && (byte?)Get(queued[0], "RequestTag") == 7,
                "deferred start carries the guest's own request tag");
            Check(await Send(owner, 0xCF7F, [], 19) is null && await Send(guest, 0xCF7F, [], 7) is null,
                "duplicate starts do not reset a running round or replay the countdown");
            var firstRound = (Guid)Get(room, "RoundId")!;
            Set(room, "PvpResultPayload", new byte[4]);
            ((HashSet<string>)Get(room, "ResultSessionIds")!).Add(Id(owner));
            await Send(owner, 0xCF8B, [0, 1, 1, 0]);
            Set(guest, "ArenaReady", true);
            Set(owner, "ArenaTeamCode", (byte)0); Set(guest, "ArenaTeamCode", (byte)0);
            await Send(owner, 0xCFEB, [0, 0, 1, 0]);
            await Send(owner, 0xCFD5, [1, 0, 0, 0]); await Send(guest, 0xCFD5, [1, 0, 0, 0]);
            ((IList)Get(owner, "PendingSessionBroadcasts")!).Clear();
            ((IList)Get(guest, "PendingSessionBroadcasts")!).Clear();
            Check(await Send(owner, 0xCF7F, [], 21) is null
                && ((IList)Get(owner, "PendingSessionBroadcasts")!).Count == 0,
                "owner-first loading does not push CF80 to an unconfirmed guest");
            Check(await Send(guest, 0xCF7F, [], 9) is { Length: 8 }
                && (Guid)Get(room, "RoundId")! != firstRound,
                "late guest completion starts a distinct epoch after same-map rematch");
            var ownerReply = ((IList)Get(guest, "PendingSessionBroadcasts")!).Cast<object>()
                .Single(b => (ushort)Get(b, "Opcode")! == 0xCF80);
            Check(ReferenceEquals(Get(ownerReply, "Target"), owner) && (byte?)Get(ownerReply, "RequestTag") == 21,
                "owner's deferred acknowledgement retains its own request tag");

            Set(room, "PvpResultPayload", new byte[4]);
            ((HashSet<string>)Get(room, "ResultSessionIds")!).Add(Id(owner));
            await Send(owner, 0xCF8B, [0, 1, 1, 0]);
            var slow = Actor(3);
            Check((bool)Invoke(service, "TryJoinArenaRoom", slow, roomId, "", null)!, "loading fixture adds a slow third member");
            foreach (var actor in new[] { owner, guest, slow })
            {
                Set(actor, "ArenaReady", true); Set(actor, "ArenaTeamCode", (byte)0);
                Set(actor, "P2PIpAddress", "127.0.0.1"); Set(actor, "P2PPort", (ushort)3534);
                Set(actor, "P2PInfoRegistered", true);
            }
            await Send(owner, 0xCFEB, [0, 0, 1, 0]);
            await Send(owner, 0xCFD5, [1, 0, 0, 0]); await Send(guest, 0xCFD5, [1, 0, 0, 0]);
            Check(await Send(owner, 0xCF7F, [], 3) is null && await Send(guest, 0xCF7F, [], 17) is null,
                "both loaded members wait for the current third member");
            ((IList)Get(slow, "PendingSessionBroadcasts")!).Clear();
            Check(await Send(slow, 0xCF73, []) is { Length: 12 } && (bool)Get(room, "Started")!,
                "a real preload departure removes only that member from the loading barrier");
            var released = ((IList)Get(slow, "PendingSessionBroadcasts")!).Cast<object>()
                .Where(b => (ushort)Get(b, "Opcode")! == 0xCF80).ToArray();
            Check(released.Length == 2 && released.All(b => !ReferenceEquals(Get(b, "Target"), slow)),
                "preload departure releases exactly the remaining request-qualified members");
            Check((int)Get(slow, "ArenaRoomId")! == 0 && !(bool)Get(slow, "P2PInfoRegistered")!,
                "explicit leave remains effective and cannot receive a later start");
        }
        finally
        {
            SqliteConnection.ClearAllPools();
            Directory.Delete(root, true);
        }
    }
}
