using System.Buffers.Binary;

namespace OpenNanaimo.Adapter.Services;

public sealed partial class NetworkAdapterService
{
    // Byte-array identity keeps the scope captured before an async request
    // attached to its exact response, rather than re-stamping it at enqueue time.
    private sealed record ArenaResponseScope(Guid Epoch, Guid? RoundId, bool LoadingOnly = false,
        bool StartedOnly = false);
    private readonly System.Runtime.CompilerServices.ConditionalWeakTable<byte[], ArenaResponseScope>
        _arenaResponseScopes = new();

    private async Task<byte[]?> HandleArenaFrameWithDeliveryAsync(byte[] frame, ushort opcode,
        string channel, string remote, string? remoteIp, ConnectionSession session, CancellationToken token)
    {
        Guid epoch;
        Guid? round;
        lock (_arenaRoomGate)
        {
            epoch = session.ArenaDeliveryEpoch;
            round = _arenaRooms.TryGetValue(session.ArenaRoomId, out var room)
                && room.Members.ContainsKey(session.SessionId) ? room.RoundId : null;
            if ((opcode is 0xCFD3 or 0xCFD5 or 0xCFEB)
                && (room is null || !ArenaMemberIsLoading(room, session))) return null;
        }
        var response = await HandleNativeFrameCoreAsync(frame, opcode, channel, remote, remoteIp, session, token);
        if (response is not null && round is not null)
        {
            var responseOpcode = ReadFirstNativeOpcode(response);
            // These responses belong to the requested room, not to a room a
            // concurrent peer reset or rejoin may have established during await.
            // Join/leave/reset acknowledgements authorize their own boundaries.
            if (responseOpcode is 0xCF71 or 0xCF72 or 0xCF7E or 0xCFEC or 0xCF80
                or 0xCF98 or 0xCF8A or 0xCFD2 or 0xCFD4 or 0xCFD6 or 0xCFDA
                or 0xD00E or 0xD010 or 0xD015 or 0xD035 or 0xD037)
            {
                lock (_arenaRoomGate)
                {
                    if (responseOpcode == 0xCF80)
                    {
                        if (!_arenaRooms.TryGetValue(session.ArenaRoomId, out var current)
                            || session.ArenaDeliveryEpoch != epoch || !current.Started
                            || !current.Members.ContainsKey(session.SessionId)) return null;
                        round = current.RoundId;
                    }
                    _arenaResponseScopes.Add(response, new ArenaResponseScope(epoch,
                        responseOpcode is 0xCF98 or 0xCF8A or 0xCF80 ? round : null,
                        ArenaResponseRequiresLoading(responseOpcode), responseOpcode == 0xCF80));
                }
            }
        }
        return response;
    }

    private bool IsCurrentArenaResponse(ConnectionSession target, byte[] response)
    {
        if (!_arenaResponseScopes.TryGetValue(response, out var scope)) return true;
        lock (_arenaRoomGate)
            return _arenaRooms.TryGetValue(target.ArenaRoomId, out var room)
                && room.Members.ContainsKey(target.SessionId) && target.ArenaDeliveryEpoch == scope.Epoch
                && (scope.RoundId is null || room.RoundId == scope.RoundId)
                && (!scope.LoadingOnly || ArenaMemberIsLoading(room, target))
                && (!scope.StartedOnly || room.Started);
    }

    private static bool ArenaResponseRequiresLoading(ushort opcode) => opcode is 0xCFD4 or 0xCFD6 or 0xCFEC;

    private static bool ArenaMemberIsLoading(ArenaRoom room, ConnectionSession member) =>
        !room.Started && room.Members.ContainsKey(member.SessionId)
        && !room.LoadingRequestTags.ContainsKey(member.SessionId);

    private bool IsCurrentArenaWrite(ConnectionSession target, OutboundNativeWrite write)
    {
        if (write.ArenaDeliveryEpoch is null && write.ArenaRoundId is null) return true;
        lock (_arenaRoomGate)
            return _arenaRooms.TryGetValue(target.ArenaRoomId, out var room)
                && room.Members.ContainsKey(target.SessionId)
                && (write.ArenaDeliveryEpoch is null || target.ArenaDeliveryEpoch == write.ArenaDeliveryEpoch)
                && (write.ArenaRoundId is null || room.Started && room.RoundId == write.ArenaRoundId)
                && (!ArenaResponseRequiresLoading(ReadFirstNativeOpcode(write.Frames))
                    || ArenaMemberIsLoading(room, target));
    }

    private bool IsCurrentArenaDelivery(ConnectionSession target, Guid? epoch)
    {
        if (epoch is null) return true;
        lock (_arenaRoomGate)
            return _arenaRooms.TryGetValue(target.ArenaRoomId, out var room)
                && target.ArenaDeliveryEpoch == epoch && room.Members.ContainsKey(target.SessionId);
    }

    private static bool ArenaAcceptsGameplay(ArenaRoom room, ConnectionSession member) =>
        room.Started && room.EndingSessionIds.Count == 0 && room.PvpResultPayload.Length == 0
        && room.Members.ContainsKey(member.SessionId) && member.Character is not null
        && room.CurrentHpBySession.GetValueOrDefault(member.SessionId) > 0;

    private bool TryBuildArenaTargetCollision(ConnectionSession member, uint uid, out byte[] payload)
    {
        payload = [];
        lock (_arenaRoomGate)
        {
            if (!_arenaRooms.TryGetValue(member.ArenaRoomId, out var room)
                || !ArenaAcceptsGameplay(room, member) || uid >= ushort.MaxValue
                || room.GameDataPayload.Length != ArenaProtocol.GameDataResponseLength) return false;
            var stage = room.GameDataPayload[0x2D2];
            var slot = BinaryPrimitives.ReadUInt16LittleEndian(room.GameDataPayload.AsSpan(0x2D4));
            // Unknown runtime objects are not proof of a destructible target.
            if (!ArenaTargetCatalog.TryGet(stage, slot, uid, out var target)) return false;
            var terminal = false;
            if (target.CanTakeDamage && !room.ClearedEntityRuntimeUids.Contains(uid))
            {
                var hp = room.TargetHpByUid.GetValueOrDefault(uid, target.Hp);
                var character = member.Character!;
                var attack = PetProgression.GetAttackProfile(PetProgression.GetState(
                    character, GetEquippedPetItemCode(character))).Default;
                var damage = ArenaProtocol.CalculatePvpDamage(
                    (int)Math.Min(int.MaxValue, (long)attack
                        + CharacterCombatProgression.NativeAttack(character.Level, character.AttackModifier)),
                    target.Defense);
                hp = Math.Max(0, hp - damage);
                room.TargetHpByUid[uid] = hp;
                terminal = hp == 0 && room.ClearedEntityRuntimeUids.Add(uid);
            }
            // PvP scores live in D035/CF8A, not the three PvE score slots.
            payload = DungeonProtocol.BuildCollision([0u, 0u, 0u], uid, terminal);
            return true;
        }
    }

    private bool TryBuildArenaPickup(ConnectionSession member, byte[] request, out byte[] payload)
    {
        payload = [];
        var category = BinaryPrimitives.ReadUInt16LittleEndian(request);
        var uid = BinaryPrimitives.ReadUInt16LittleEndian(request.AsSpan(2));
        var value = BinaryPrimitives.ReadUInt32LittleEndian(request.AsSpan(4));
        if (!(category == 30 && value is 1 or 10 or 50 or 100 or 200 or 500
            || category == 40 && value is >= ArenaProtocol.SkyArenaItemTypeMinimum and <= ArenaProtocol.SkyArenaItemTypeMaximum))
            return false;
        lock (_arenaRoomGate)
        {
            if (!_arenaRooms.TryGetValue(member.ArenaRoomId, out var room)
                || !ArenaAcceptsGameplay(room, member)
                || !room.ClaimedDrops.Add((category, uid))) return false;
            if (category == 30)
                room.ScoreBySession[member.SessionId] = (int)Math.Min(int.MaxValue,
                    (long)room.ScoreBySession.GetValueOrDefault(member.SessionId) + value);
            else
                room.ArenaItems[(member.SessionId, uid)] = checked((byte)value);
            payload = BuildDungeonPickupPayload(member.Character!, null, category, uid, category == 30 ? value : 0);
            // D035 +12 is the arena item type; +14 is absolute HP, not base HP.
            BinaryPrimitives.WriteUInt16LittleEndian(payload.AsSpan(12), category == 40 ? (ushort)value : (ushort)0);
            BinaryPrimitives.WriteUInt16LittleEndian(payload.AsSpan(14), room.CurrentHpBySession[member.SessionId]);
            if (category == 30)
            {
                BinaryPrimitives.WriteUInt16LittleEndian(payload.AsSpan(2), 0);
                payload.AsSpan(12).Clear();
            }
            return true;
        }
    }

    private byte[]? HandleArenaItemUse(byte[] frame, byte[] request, ConnectionSession member)
    {
        var uid = BinaryPrimitives.ReadUInt16LittleEndian(request.AsSpan(4));
        byte[] payload;
        lock (_arenaRoomGate)
        {
            if (!_arenaRooms.TryGetValue(member.ArenaRoomId, out var room)
                || !ArenaAcceptsGameplay(room, member)
                || !room.ArenaItems.Remove((member.SessionId, uid), out var item)) return null;
            payload = BuildDungeonPickupPayload(member.Character!, member.Character, 40, uid, 0);
            BinaryPrimitives.WriteUInt16LittleEndian(payload.AsSpan(12), item);
            BinaryPrimitives.WriteUInt16LittleEndian(payload.AsSpan(14), room.CurrentHpBySession[member.SessionId]);
            QueueArenaBroadcast(member, 0xD035, payload, false, "arena owned item use");
        }
        return BuildNativeFrame(frame, 0xD035, payload, member);
    }

    private static bool ArenaMemberWon(ArenaRoom room, ConnectionSession member)
    {
        var members = room.FinalMembers.Length != 0 ? room.FinalMembers
            : room.Members.Values.Where(m => m.Character is not null).ToArray();
        byte Team(ConnectionSession m) => room.FinalTeams.GetValueOrDefault(m.SessionId, m.ArenaTeamCode);
        var teamMode = members.Length > 1 && members.All(m => Team(m) is 1 or 2)
            && members.Select(Team).Distinct().Count() == 2;
        if (room.EliminationWinnerSessionId is { } winner)
            return member.SessionId == winner || teamMode && members.FirstOrDefault(m => m.SessionId == winner) is { } winningMember
                && Team(member) == Team(winningMember);
        if (teamMode)
        {
            var totals = members.GroupBy(Team).ToDictionary(g => g.Key,
                g => g.Aggregate(0UL, (sum, m) => sum + room.EndValuesBySession.GetValueOrDefault(m.SessionId)));
            return totals[Team(member)] > totals.Where(p => p.Key != Team(member)).Max(p => p.Value);
        }
        return room.EndValuesBySession.GetValueOrDefault(member.SessionId) > members
            .Where(m => m.SessionId != member.SessionId).Select(m => room.EndValuesBySession.GetValueOrDefault(m.SessionId))
            .DefaultIfEmpty(0u).Max();
    }
}
