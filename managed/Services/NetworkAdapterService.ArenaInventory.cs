using System.Buffers.Binary;

namespace OpenNanaimo.Adapter.Services;

public sealed partial class NetworkAdapterService
{
    private static bool IsAuxiliaryInventoryOpcode(ushort opcode) => opcode is
        0xC451 or 0xC378 or 0xC37A or 0xC3CB or 0xC3E7 or 0xC409 or 0xC42F or 0xC44B or 0xC469 or 0xC473
        or 0xC47D or 0xC44D or 0xC44F or 0xC433 or 0xC43D or 0xC46D or 0xC3CF or 0xC475 or 0xC453;

    private ConnectionSession? FindInventoryOwner(ConnectionSession session)
    {
        if (!session.AuxiliaryGameSession) return IsTrackedWorldSession(session) ? session : null;
        return _activeWorldSessions.TryGetValue(session.AuxiliaryWorldSessionId, out var owner)
            && owner.AccountId == session.AccountId && owner.CharacterId == session.Character?.Id
            && owner.ChannelId == session.ChannelId && IsTrackedWorldSession(owner.Session)
            ? owner.Session : null;
    }

    private ConnectionSession[] AuxiliaryInventorySessions(ConnectionSession owner) =>
        _activeArenaSessions.Values.Where(peer => peer.OnlineTracked && peer.AuxiliaryGameSession
            && peer.ArenaGameType == 4 && peer.AuxiliaryWorldSessionId == owner.SessionId && peer.AccountId == owner.AccountId
            && peer.Character?.Id == owner.Character?.Id && peer.ChannelId == owner.ChannelId).ToArray();

    private bool HasAuxiliaryInventoryContext(ConnectionSession session) =>
        session.AuxiliaryGameSession || AuxiliaryInventorySessions(session).Length != 0;

    private static void ShareInventoryIdentity(ConnectionSession owner, ConnectionSession peer)
    {
        peer.GameInventoryIdentities = owner.GameInventoryIdentities;
        peer.PetMaterialIdentities = owner.PetMaterialIdentities;
        peer.ShoppingCouponIdentities = owner.ShoppingCouponIdentities;
        peer.InventoryAcquisitions = owner.InventoryAcquisitions;
        peer.Character = owner.Character;
        peer.NonCombatResourceSnapshot = owner.NonCombatResourceSnapshot;
    }

    private void PublishInventoryCharacter(ConnectionSession source)
    {
        var owner = FindInventoryOwner(source);
        if (owner is null || source.Character is null) return;
        owner.Character = source.Character;
        owner.NonCombatResourceSnapshot = source.NonCombatResourceSnapshot;
        foreach (var peer in AuxiliaryInventorySessions(owner)) ShareInventoryIdentity(owner, peer);
    }

    private async Task<byte[]?> HandleNativeFrameAsync(byte[] frame, ushort opcode, string channel,
        string remote, string? remoteIp, ConnectionSession session, CancellationToken token)
    {
        if (!IsAuxiliaryInventoryOpcode(opcode))
            return await HandleNativeInventoryCoreAsync(frame, opcode, channel, remote, remoteIp, session, token);
        if (channel != "WorldAdapter" && channel != "ArenaAdapter") return null;
        var owner = FindInventoryOwner(session);
        if (channel == "ArenaAdapter" && (owner is null || !session.OnlineTracked || !session.AuxiliaryGameSession
            || session.ArenaGameType != 4)) return null;
        if (owner is null)
            return await HandleNativeInventoryCoreAsync(frame, opcode, channel, remote, remoteIp, session, token);
        await owner.InventoryGate.WaitAsync(token);
        var peers = AuxiliaryInventorySessions(owner);
        if (session.AuxiliaryGameSession && !peers.Contains(session))
        {
            owner.InventoryGate.Release();
            return null;
        }
        Dictionary<string, (int RoomId, Guid Epoch)> scopes;
        lock (_arenaRoomGate)
            scopes = peers.ToDictionary(peer => peer.SessionId, peer => (peer.ArenaRoomId, peer.ArenaDeliveryEpoch));
        try
        {
            if (!ReferenceEquals(FindInventoryOwner(session), owner)) return null;
            lock (_arenaRoomGate)
            {
                if (peers.Any(peer => _arenaRooms.TryGetValue(peer.ArenaRoomId, out var room)
                    && room.Members.ContainsKey(peer.SessionId) && (room.Started || room.GameDataPayload.Length != 0))) return null;
                foreach (var peer in peers) peer.ArenaInventoryBusy = true;
            }
            foreach (var peer in peers) ShareInventoryIdentity(owner, peer);
            var before = owner.Character is null ? null : BuildFoodReadyProfile(owner, GetSceneEntityId(owner.Character));
            var beforePet = owner.Character is null ? [] : BuildPetInventoryPayload(owner.Character);
            var response = await HandleNativeInventoryCoreAsync(frame, opcode, channel, remote, remoteIp, session, token);
            PublishInventoryCharacter(session);
            var petChanged = owner.Character is not null
                && !beforePet.AsSpan().SequenceEqual(BuildPetInventoryPayload(owner.Character));
            if (response is not null && (IsNativeInventoryMutation(opcode) || opcode == 0xC43D))
                QueueArenaInventoryProfiles(session, peers, scopes, before, petChanged);
            return response;
        }
        finally
        {
            lock (_arenaRoomGate)
            {
                foreach (var peer in peers) peer.ArenaInventoryBusy = false;
                foreach (var roomId in peers.Select(peer => peer.ArenaRoomId).Distinct())
                    if (_arenaRooms.TryGetValue(roomId, out var room))
                        TryCompleteArenaLoadingLocked(room, session);
            }
            owner.InventoryGate.Release();
        }
    }

    private bool IsCurrentInventoryDelivery(ConnectionSession target, OutboundNativeWrite write)
    {
        if (write.ArenaDeliveryEpoch is null || ReadFirstNativeOpcode(write.Frames) != 0xCF72) return true;
        lock (_arenaRoomGate)
            return _arenaRooms.TryGetValue(target.ArenaRoomId, out var room)
                && !room.Started && room.GameDataPayload.Length == 0 && room.Members.ContainsKey(target.SessionId);
    }

    private void QueueArenaInventoryProfiles(ConnectionSession source, ConnectionSession[] peers, Dictionary<string, (int RoomId, Guid Epoch)> scopes, byte[]? before, bool petChanged)
    {
        lock (_arenaRoomGate)
        {
            foreach (var actor in peers)
            {
                if (!scopes.TryGetValue(actor.SessionId, out var scope) || scope.RoomId != actor.ArenaRoomId
                    || scope.Epoch != actor.ArenaDeliveryEpoch || actor.Character is null || !_arenaRooms.TryGetValue(actor.ArenaRoomId, out var room)
                    || room.Started || room.GameDataPayload.Length != 0 || !room.Members.ContainsKey(actor.SessionId)) continue;
                var payload = BuildFoodReadyProfile(actor, GetSceneEntityId(actor.Character));
                if (!petChanged && before is not null && payload.AsSpan().SequenceEqual(before)) continue;
                var rebuild = petChanged || before is null || !payload.AsSpan(12, 36).SequenceEqual(before.AsSpan(12, 36))
                    || !payload.AsSpan(94, 2).SequenceEqual(before.AsSpan(94, 2));
                BinaryPrimitives.WriteUInt16LittleEndian(payload.AsSpan(92), rebuild ? (ushort)1 : (ushort)0);
                foreach (var target in room.Members.Values.Where(target => room.EntityInitializedSessions.Contains(target.SessionId)))
                    source.PendingSessionBroadcasts.Add(new PendingSessionBroadcast(target, 0xCF72, payload.ToArray(),
                        "ready-room inventory profile", ArenaDeliveryEpoch: target.ArenaDeliveryEpoch));
            }
        }
    }
}
