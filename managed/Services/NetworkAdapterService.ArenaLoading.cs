namespace OpenNanaimo.Adapter.Services;

public sealed partial class NetworkAdapterService
{
    private bool TryConfirmArenaLoading(ConnectionSession requester, byte requestTag, out string reason)
    {
        lock (_arenaRoomGate)
        {
            if (!_arenaRooms.TryGetValue(requester.ArenaRoomId, out var room)
                || !room.Members.ContainsKey(requester.SessionId))
            {
                reason = "room-not-found";
                return false;
            }
            if (room.Started)
            {
                reason = "already-confirmed";
                return false;
            }
            if (room.GameDataPayload.Length != ArenaProtocol.GameDataResponseLength
                || !requester.P2PInfoRegistered || !requester.ArenaP2PProtocolConfirmed)
            {
                reason = "member-loading";
                return false;
            }
            room.LoadingRequestTags.TryAdd(requester.SessionId, (byte)(requestTag & 0x1F));
            if (!TryCompleteArenaLoadingLocked(room, requester, requester))
            {
                reason = "waiting-for-member-confirmations";
                return false;
            }
            reason = "ok";
            return true;
        }
    }

    // Caller holds the room gate. Only members with their own CF7F receive CF80.
    private bool TryCompleteArenaLoadingLocked(ArenaRoom room, ConnectionSession source,
        ConnectionSession? directRecipient = null)
    {
        if (room.Started || room.LoadingRequestTags.Count == 0
            || !room.Members.Keys.All(room.LoadingRequestTags.ContainsKey)
            || !room.Members.TryGetValue(room.OwnerSessionId, out var owner)
            || !TryStartArenaRoom(owner, out _)) return false;
        foreach (var member in room.Members.Values)
        {
            if (ReferenceEquals(member, directRecipient)) continue;
            source.PendingSessionBroadcasts.Add(new PendingSessionBroadcast(member, 0xCF80, [],
                "arena member loading complete", RequestTag: room.LoadingRequestTags[member.SessionId],
                ArenaRoundId: room.RoundId));
        }
        return true;
    }
}
