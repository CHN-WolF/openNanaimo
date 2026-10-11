using System.Buffers.Binary;
using System.Collections;
using System.Reflection;
using System.Text;
using OpenNanaimo.Adapter.Services;

internal static partial class Program
{
    private static async Task CheckEntertainmentLobbyAsync()
    {
        await using var f = await Fixture.CreateAsync();
        var active = typeof(NetworkAdapterService).GetField("_activeArenaSessions", PrivateInstance)!.GetValue(f.Service)!;
        object Auxiliary(object world, byte game = 1)
        {
            var session = Activator.CreateInstance(SessionType, nonPublic: true)!;
            foreach (var property in new[] { "AccountId", "Username", "Character", "ChannelId", "RemoteIp" })
                Set(session, property, Get(world, property));
            Set(session, "OnlineTracked", true); Set(session, "AuxiliaryGameSession", true);
            Set(session, "ArenaGameType", game);
            active.GetType().GetMethod("TryAdd")!.Invoke(active, [Id(session), session]);
            return session;
        }
        Task<byte[]?> Send(object session, ushort opcode, byte[] payload)
            => Dispatch(f, session, opcode, payload, "ArenaAdapter");
        var host = Auxiliary(f.Teacher); var guest = Auxiliary(f.Student);
        Character(host).Gender = 1; Character(guest).Gender = 0;
        var extra = new List<object>();
        for (var i = 0; i < 12; i++)
        {
            var world = await f.CreateSessionAsync("lobby" + i, "Rank" + i, 1, 1);
            extra.Add(Auxiliary(world));
            await f.ExecuteAsync("INSERT INTO EntertainmentBestScores VALUES($id,1,$score,'test')",
                ("$id", Character(world).Id), ("$score", 2000 + i * 100));
        }
        await f.ExecuteAsync("INSERT INTO EntertainmentBestScores VALUES($id,1,4558,'test'),($id,2,60000,'test')",
            ("$id", Character(host).Id));
        var lobby = (await Send(host, 0xCF0B, []))!;
        Check(lobby.Length == 20 && BinaryPrimitives.ReadUInt32LittleEndian(lobby.AsSpan(8)) == Character(host).Id
            && BinaryPrimitives.ReadUInt32LittleEndian(lobby.AsSpan(16)) == 4558,
            "CF0C never substitutes character identity for the committed point record");
        var ranking = (await Send(host, 0xCF13, new byte[4]))!;
        Check(ranking.Length == 296 && BinaryPrimitives.ReadUInt32LittleEndian(ranking.AsSpan(8)) == 4558
            && BinaryPrimitives.ReadUInt16LittleEndian(ranking.AsSpan(12)) == 0
            && BinaryPrimitives.ReadUInt16LittleEndian(ranking.AsSpan(14)) == 10,
            "CF14 publishes personal best, zero-based page and at most ten rows");
        Check(Encoding.ASCII.GetString(ranking, 16, 7) == "Teacher"
            && BinaryPrimitives.ReadUInt32LittleEndian(ranking.AsSpan(40)) == 4558
            && BinaryPrimitives.ReadUInt32LittleEndian(ranking.AsSpan(68)) == 3100,
            "ranking nickname and point fields are sorted by persistent score, not identity");
        var page = new byte[4]; BinaryPrimitives.WriteUInt32LittleEndian(page, 1);
        var second = (await Send(host, 0xCF13, page))!;
        Check(BinaryPrimitives.ReadUInt16LittleEndian(second.AsSpan(12)) == 1
            && BinaryPrimitives.ReadUInt16LittleEndian(second.AsSpan(14)) == 3
            && BinaryPrimitives.ReadUInt32LittleEndian(second.AsSpan(8)) == 4558
            && BinaryPrimitives.ReadUInt32LittleEndian(second.AsSpan(40)) == 2200
            && second.AsSpan(16 + 3 * 28).ToArray().All(value => value == 0),
            "second ranking page preserves the personal best and initializes unused rows");
        BinaryPrimitives.WriteUInt32LittleEndian(page, 65536);
        Check(await Send(host, 0xCF13, page) is null && await Send(host, 0xCF13, []) is null,
            "malformed and out-of-range ranking requests cannot index the client page");
        Set(host, "ArenaGameType", (byte)2);
        var otherGame = (await Send(host, 0xCF13, new byte[4]))!;
        Check(BinaryPrimitives.ReadUInt32LittleEndian(otherGame.AsSpan(8)) == 60000
            && BinaryPrimitives.ReadUInt16LittleEndian(otherGame.AsSpan(14)) == 1,
            "ranking isolates entertainment game types");
        Set(host, "ArenaGameType", (byte)1);
        var waiting = (await Send(host, 0xCF19, [200, 0, 0, 0]))!;
        Check(waiting.Length == 212 && BinaryPrimitives.ReadUInt32LittleEndian(waiting.AsSpan(8)) == 10,
            "waiting-user response stays within the native dialog's ten fixed slots");
        Check(BinaryPrimitives.ReadUInt16LittleEndian(waiting.AsSpan(30)) == 1
            && BinaryPrimitives.ReadUInt16LittleEndian(waiting.AsSpan(50)) == 0,
            "waiting-user rows carry male one and female zero as WORDs, not the game type");
        var cursor = BinaryPrimitives.ReadUInt16LittleEndian(waiting.AsSpan(28 + 9 * 20));
        var nextRequest = new byte[4]; BinaryPrimitives.WriteUInt16LittleEndian(nextRequest, 100);
        BinaryPrimitives.WriteUInt16LittleEndian(nextRequest.AsSpan(2), cursor);
        var next = (await Send(host, 0xCF19, nextRequest))!;
        Check(BinaryPrimitives.ReadUInt32LittleEndian(next.AsSpan(8)) == 4
            && BinaryPrimitives.ReadUInt16LittleEndian(next.AsSpan(28)) > cursor,
            "waiting-user next page advances by UID without repeating rows");
        BinaryPrimitives.WriteUInt16LittleEndian(nextRequest, 200);
        BinaryPrimitives.WriteUInt16LittleEndian(nextRequest.AsSpan(2), BinaryPrimitives.ReadUInt16LittleEndian(next.AsSpan(28)));
        var previous = (await Send(host, 0xCF19, nextRequest))!;
        Check(previous.AsSpan(8).SequenceEqual(waiting.AsSpan(8)), "previous waiting-user page restores the same rows");
        Check(await Send(host, 0xCF19, [1, 0, 0, 0]) is null, "unknown waiting-list direction is rejected");
        await f.ExecuteAsync("UPDATE EntertainmentBestScores SET BestScore=9999 WHERE CharacterId=$id AND GameType=1",
            ("$id", Character(extra[^1]).Id));
        var create = new byte[44]; Encoding.ASCII.GetBytes("Invite room").CopyTo(create, 0);
        BinaryPrimitives.WriteUInt16LittleEndian(create.AsSpan(24), 200);
        create[35] = 1; Encoding.ASCII.GetBytes("secret").CopyTo(create, 36);
        var created = (await Send(host, 0xCF6C, create))!;
        Check(created.Length == 44 && BinaryPrimitives.ReadUInt32LittleEndian(created.AsSpan(16)) == 9999
            && Encoding.ASCII.GetString(created, 20, 6) == "Rank11",
            "CF6D GAME INFO highest record and holder are independent of the room owner UID and name");
        var memberInfo = (await Send(host, 0xCF6E, []))!;
        Check(BinaryPrimitives.ReadUInt16LittleEndian(memberInfo.AsSpan(24)) == WireIdentityAllocator.GetSceneEntityId(Character(host).Id)
            && BinaryPrimitives.ReadUInt16LittleEndian(memberInfo.AsSpan(26)) == WireIdentityAllocator.GetSceneEntityId(Character(host).Id)
            && BinaryPrimitives.ReadUInt16LittleEndian(memberInfo.AsSpan(32)) == 1500,
            "CF6F retains actual owner and member identity plus the independent target score");
        var invite = new byte[20]; Encoding.ASCII.GetBytes(Character(guest).Name).CopyTo(invite, 0);
        BinaryPrimitives.WriteUInt32LittleEndian(invite.AsSpan(16), WireIdentityAllocator.GetSceneEntityId(Character(guest).Id));
        var notifications = (IList)Get(host, "PendingSessionBroadcasts")!; notifications.Clear();
        Check(await Send(host, 0xCF8F, invite) is null && notifications.Count == 1,
            "native CF8F forwards one invitation to the target instead of fabricating a sender response");
        var notification = notifications[0]!; var notice = (byte[])Get(notification, "Payload")!;
        Check((ushort)Get(notification, "Opcode")! == 0xCF90 && notice.Length == 44
            && ReferenceEquals(Get(notification, "Target"), guest)
            && Encoding.ASCII.GetString(notice, 0, 7) == "Teacher"
            && BinaryPrimitives.ReadUInt32LittleEndian(notice.AsSpan(16)) == (int)Get(host, "EntertainmentRoomId")!
            && Encoding.ASCII.GetString(notice, 20, 6) == "secret",
            "CF90 supplies inviter name, room ID and the native CF75 password token");
        notifications.Clear();
        invite[0] = (byte)'X'; await Send(host, 0xCF8F, invite);
        Check(notifications.Count == 0, "mismatched invitation nickname cannot target another UID");
        invite[0] = (byte)'S';
        await f.Database.SetFriendBlockedAsync(Character(guest).Id, Character(host).Id, true);
        await Send(host, 0xCF8F, invite);
        Check(notifications.Count == 0, "nickname blocking prevents native invitation delivery");
        var enter = new byte[12]; BinaryPrimitives.WriteUInt16LittleEndian(enter, 20);
        BinaryPrimitives.WriteUInt16LittleEndian(enter.AsSpan(2), checked((ushort)(int)Get(host, "EntertainmentRoomId")!));
        notice.AsSpan(20, 8).CopyTo(enter.AsSpan(4));
        Check((await Send(guest, 0xCF75, enter))![8] == 50 && (int)Get(guest, "EntertainmentRoomId")! == 0,
            "blocking after invitation prevents acceptance from joining the room");
        await f.Database.SetFriendBlockedAsync(Character(guest).Id, Character(host).Id, false);
        var entered = (await Send(guest, 0xCF75, enter))!;
        Check(entered[8] == 10
            && Get(guest, "EntertainmentRoomId")!.Equals(Get(host, "EntertainmentRoomId")),
            "native invitation acceptance joins the password-protected room via CF75");
        Check(entered.Length == 72 && entered[9] == create[30]
            && BinaryPrimitives.ReadUInt32LittleEndian(entered.AsSpan(44)) == 9999
            && Encoding.ASCII.GetString(entered, 48, 6) == "Rank11",
            "CF76 joining the room uses the same real GAME INFO record as creation");
        Check(await Send(host, 0xCF8F, invite) is null && notifications.Cast<object>().All(row => (ushort)Get(row, "Opcode")! != 0xCF90),
            "an already joined member cannot receive another lobby invitation");
        Check((bool)typeof(NetworkAdapterService).GetMethod("IsArenaAdapterOpcode", BindingFlags.Static | BindingFlags.NonPublic)!
            .Invoke(null, [(ushort)0xCF8F])! && (string)typeof(NetworkAdapterService).GetMethod("GetRequiredInboundChannel", BindingFlags.Static | BindingFlags.NonPublic)!
            .Invoke(null, [(ushort)0xCF8F])! == "ArenaAdapter", "CF8F passes the real auxiliary channel gate");

        // Assert bytes consumed by the original client rather than an invented sync packet.
        create[35] = 0;
        for (byte gameType = 1; gameType <= 3; gameType++)
        for (byte difficulty = 0; difficulty <= 4; difficulty++)
        {
            Set(host, "ArenaGameType", gameType);
            Set(guest, "ArenaGameType", gameType);
            BinaryPrimitives.WriteUInt16LittleEndian(create.AsSpan(30), difficulty);
            Check((await Send(host, 0xCF6C, create))![8] == 10,
                $"create game={gameType} difficulty={difficulty}");
            foreach (ushort mode in new ushort[] { 20, 10 })
            {
                var request = new byte[12];
                BinaryPrimitives.WriteUInt16LittleEndian(request, mode);
                BinaryPrimitives.WriteUInt16LittleEndian(request.AsSpan(2), mode == 20
                    ? checked((ushort)(int)Get(host, "EntertainmentRoomId")!) : (ushort)0);
                ((IList)Get(guest, "PendingSessionBroadcasts")!).Clear();
                var response = (await Send(guest, 0xCF75, request))!;
                Check(response.Length == 72 && response[8] == 10 && response[9] == difficulty,
                    $"CF76 display difficulty follows room, not game type: {gameType}/{difficulty}/mode{mode}");
                Check(((IList)Get(guest, "PendingSessionBroadcasts")!).Cast<object>()
                    .All(row => (ushort)Get(row, "Opcode")! is not (0xCF6C or 0xCF0C)),
                    "entry has no unsupported CF6C or identity-clobbering CF0C push");
            }
        }
    }
}
