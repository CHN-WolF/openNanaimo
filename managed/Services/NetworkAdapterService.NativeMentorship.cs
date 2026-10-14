using System.Buffers.Binary;
using OpenNanaimo.Adapter.Models;

namespace OpenNanaimo.Adapter.Services;

public sealed partial class NetworkAdapterService
{
    private readonly Dictionary<string, MentorshipRequestRecord> _nativeMentorshipRequests = new(StringComparer.Ordinal);

    private static byte[] BuildNativeMentorshipPeer(CharacterRecord peer, byte role, byte status, bool response)
    {
        var payload = new byte[24];
        payload[0] = status;
        payload[1] = role;
        payload[2] = (byte)Math.Clamp(peer.Level, 1, byte.MaxValue);
        payload[3] = CharacterTitleState.GetGrade(peer);
        if (response)
        {
            BinaryPrimitives.WriteUInt16LittleEndian(payload.AsSpan(4), role);
            BinaryPrimitives.WriteUInt16LittleEndian(payload.AsSpan(6), GetSceneEntityId(peer));
        }
        else BinaryPrimitives.WriteUInt32LittleEndian(payload.AsSpan(4), GetSceneEntityId(peer));
        WriteFixedGbk(payload.AsSpan(8, 16), peer.Name);
        return payload;
    }

    private async Task<byte[]?> HandleNativeMentorshipNegotiationAsync(byte[] frame, ushort opcode,
        byte[] payload, ConnectionSession session, CancellationToken token)
    {
        if (payload.Length != 24 || session.Character is not { } character
            || !TryGetMentorshipPresence(session.SessionId, out _) || !session.TownSceneActive
            || session.NativeDungeon is not null || session.DungeonRoomId > 0) return null;
        if (opcode == 0xC576)
        {
            if (payload[1] > 1 || payload[0] != 1 - payload[1]) return null;
            var hasPeerName = MentorProtocol.TryReadPeerName(payload.AsSpan(8), out var requestedName);
            if (!hasPeerName && payload.Skip(8).Any(value => value != 0)) return null;
            var uid = BinaryPrimitives.ReadUInt32LittleEndian(payload.AsSpan(4));
            var candidates = _activeWorldSessions.Values.Where(p => p.CharacterId != character.Id
                && p.ChannelId == session.ChannelId && TryGetMentorshipPresence(p.SessionId, out _)
                && p.Session.Character is not null && p.Session.TownSceneActive
                && p.Session.NativeDungeon is null && p.Session.DungeonRoomId == 0).ToArray();
            WorldPresence? target = null;
            if (uid is > 0 and <= 0x0FFF)
            {
                // Scene actions carry a real 12-bit entity ID. A supplied name must agree.
                var matching = candidates.Where(p => GetSceneEntityId(p.Session.Character!) == uid
                    && (!hasPeerName || string.Equals(p.CharacterName, requestedName, StringComparison.OrdinalIgnoreCase))).ToArray();
                if (matching.Length == 1) target = matching[0];
            }
            else if (hasPeerName)
            {
                // C57E advertisements carry names rather than scene IDs. Resolve
                // non-scene identities in C576 advertisement requests by name.
                // Only a currently eligible, session-owned advertisement authorizes this route.
                var advertisements = await _database.GetMentorshipAdvertisingCharactersAsync(
                    CreateMentorshipActor(session), MentorshipRules, token);
                var advertisedIds = advertisements.Where(p => string.Equals(p.Name, requestedName,
                    StringComparison.OrdinalIgnoreCase)).Select(p => p.Id).ToHashSet();
                var named = candidates.Where(p => advertisedIds.Contains(p.CharacterId)
                    && string.Equals(p.CharacterName, requestedName, StringComparison.OrdinalIgnoreCase)).ToArray();
                if (named.Length == 1) target = named[0];
            }
            if (target?.Session.Character is not { } targetCharacter)
            {
                _log($"Mentorship request target unavailable: session={session.SessionId} uid=0x{uid:X8} named={hasPeerName}");
                return null;
            }
            var direction = payload[1] == 1 ? MentorshipDirection.TeacherInvitation : MentorshipDirection.StudentApplication;
            var result = await RequestMentorshipAsync(session.SessionId, target.CharacterId, direction, token);
            if (!result.Success || result.Request is not { } request)
                return BuildNativeFrame(frame, 0xC577,
                    BuildNativeMentorshipPeer(targetCharacter, payload[1], 1, true), session);
            lock (_mentorGate) _nativeMentorshipRequests[target.SessionId] = request;
            session.PendingBroadcasts.Add(new PendingNativeBroadcast(target, 0xC576,
                BuildNativeMentorshipPeer(character, payload[1], 0, false), "mentorship invitation"));
            return null;
        }
        MentorshipRequestRecord pending;
        lock (_mentorGate)
        {
            if (!_nativeMentorshipRequests.TryGetValue(session.SessionId, out pending!)) return null;
        }
        if (payload[0] is not (1 or 2 or 10 or 20)
            || !TryGetMentorshipPresence(pending.Requester.SessionId, out var requester)
            || CreateMentorshipActor(requester.Session) != pending.Requester
            || CreateMentorshipActor(session) != pending.Target
            || requester.Session.Character is not { } requesterCharacter
            || BinaryPrimitives.ReadUInt16LittleEndian(payload.AsSpan(6)) != GetSceneEntityId(requesterCharacter)) return null;
        var answered = await RespondMentorshipAsync(session.SessionId, pending.Id, payload[0] == 10, token);
        lock (_mentorGate)
            if (_nativeMentorshipRequests.GetValueOrDefault(session.SessionId)?.Id == pending.Id)
                _nativeMentorshipRequests.Remove(session.SessionId);
        var status = answered.Success ? payload[0] : (byte)1;
        var sourceRole = pending.Direction == MentorshipDirection.TeacherInvitation ? (byte)1 : (byte)0;
        session.PendingBroadcasts.Add(new PendingNativeBroadcast(requester, 0xC577,
            BuildNativeMentorshipPeer(character, sourceRole, status, true), "mentorship answer"));
        return BuildNativeFrame(frame, 0xC577,
            BuildNativeMentorshipPeer(requesterCharacter, (byte)(1 - sourceRole), status, true), session);
    }

    private async Task<byte[]?> HandleNativeMentorshipReleaseAsync(byte[] frame, byte[] payload,
        ConnectionSession session, CancellationToken token)
    {
        if (payload.Length != 16 || !MentorProtocol.TryReadPeerName(payload, out var name)
            || !TryGetMentorshipPresence(session.SessionId, out _) || session.Character is null
            || !session.TownSceneActive || session.NativeDungeon is not null) return null;
        var relations = await _database.GetMentorshipRelationsAsync(CreateMentorshipActor(session), false, token);
        foreach (var relation in relations)
        {
            var teacher = relation.TeacherCharacterId == session.Character.Id;
            var peer = await _database.GetCharacterByIdAsync(teacher ? relation.StudentCharacterId : relation.TeacherCharacterId, token);
            if (peer is null || !string.Equals(peer.Name, name, StringComparison.OrdinalIgnoreCase)) continue;
            var result = await ReleaseMentorshipAsync(session.SessionId, relation.Id, token);
            if (!result.Success) return null;
            var counterpart = _activeWorldSessions.Values.FirstOrDefault(p => p.CharacterId == peer.Id
                && TryGetMentorshipPresence(p.SessionId, out _));
            if (counterpart is not null)
            {
                var notice = new byte[20]; notice[0] = teacher ? (byte)0 : (byte)1;
                notice[1] = (byte)Math.Clamp(session.Character.Level, 1, byte.MaxValue);
                BinaryPrimitives.WriteUInt16LittleEndian(notice.AsSpan(2), GetSceneEntityId(session.Character));
                WriteFixedGbk(notice.AsSpan(4, 16), session.Character.Name);
                session.PendingBroadcasts.Add(new PendingNativeBroadcast(counterpart, 0xC57B, notice, "mentorship release"));
            }
            var response = new byte[20]; response[0] = teacher ? (byte)2 : (byte)3;
            response[1] = (byte)Math.Clamp(peer.Level, 1, byte.MaxValue);
            BinaryPrimitives.WriteUInt16LittleEndian(response.AsSpan(2), GetSceneEntityId(peer));
            WriteFixedGbk(response.AsSpan(4, 16), peer.Name);
            return BuildNativeFrame(frame, 0xC57B, response, session);
        }
        return null;
    }

    private async Task<byte[]> BuildNativeMentorshipProfileAsync(ConnectionSession session, CancellationToken token)
    {
        var character = (await _database.GetCharacterByIdAsync(session.Character!.Id, token))!;
        var actor = CreateMentorshipActor(session);
        await ReconcileLevelMentorshipsAsync(session, token);
        var relations = await _database.GetMentorshipRelationsAsync(actor, true, token);
        if (!MentorshipRules.AutomaticLevelGraduation)
        {
            foreach (var relation in relations.Where(r => r.TeacherCharacterId == character.Id))
                await GraduateMentorshipAsync(session.SessionId, relation.Id, token);
            relations = await _database.GetMentorshipRelationsAsync(actor, true, token);
        }
        relations = relations.Where(r => r.State != MentorshipRelationState.Released).ToArray();
        var teaching = relations.Where(r => r.TeacherCharacterId == character.Id).ToArray();
        relations = teaching.Length > 0
            ? teaching.OrderBy(r => r.State).ThenByDescending(r => r.Id).ToArray()
            : relations.Where(r => r.StudentCharacterId == character.Id).OrderByDescending(r => r.State).ThenByDescending(r => r.Id).Take(1).ToArray();
        var qualification = await _database.GetMentorshipQualificationAsync(actor, MentorshipRules, token);
        var payload = new byte[280];
        var student = relations.Any(r => r.StudentCharacterId == character.Id);
        BinaryPrimitives.WriteUInt16LittleEndian(payload.AsSpan(2), relations.Count > 0
            ? (student ? (ushort)3 : (ushort)2)
            : (character.Level >= MentorshipRules.MinimumTeacherLevel ? (ushort)0 : (ushort)1));
        var count = 0;
        foreach (var relation in relations.Take(10))
        {
            var id = student ? relation.TeacherCharacterId : relation.StudentCharacterId;
            var peer = await _database.GetCharacterByIdAsync(id, token);
            if (peer is null) continue;
            var offset = 4 + 24 * count++;
            payload[offset] = (byte)Math.Clamp(peer.Level, 1, byte.MaxValue);
            payload[offset + 1] = CharacterTitleState.GetGrade(peer);
            BinaryPrimitives.WriteUInt16LittleEndian(payload.AsSpan(offset + 2),
                _activeWorldSessions.Values.Any(p => p.CharacterId == id && TryGetMentorshipPresence(p.SessionId, out _)) ? (ushort)1 : (ushort)0);
            BinaryPrimitives.WriteUInt32LittleEndian(payload.AsSpan(offset + 4), GetSceneEntityId(peer));
            WriteFixedGbk(payload.AsSpan(offset + 8, 16), peer.Name);
        }
        payload[244] = (byte)Math.Clamp(character.Level, 1, byte.MaxValue);
        payload[245] = CharacterTitleState.GetGrade(character);
        BinaryPrimitives.WriteUInt32LittleEndian(payload.AsSpan(248), qualification.CanAdvertise ? 0u : 1u);
        // C579 -> 0x8B0340 consumes BYTE frame+260 independently of the row count.
        // Count the full persisted history, not the ten displayed relationship rows.
        var profile = await _database.GetMentorshipProfileAsync(character.Id, token);
        payload[252] = (byte)Math.Min(byte.MaxValue, profile.Graduates);
        BinaryPrimitives.WriteUInt32LittleEndian(payload.AsSpan(256), (uint)count);
        WriteFixedGbk(payload.AsSpan(264, 16), character.Name);
        return payload;
    }
    private async Task WriteProfileMentorshipAsync(byte[] payload, long characterId, CancellationToken token)
    {
        var profile = await _database.GetMentorshipProfileAsync(characterId, token);
        if (profile.TeacherName.Length > 0)
        {
            payload[45] = 3;
            WriteFixedGbk(payload.AsSpan(76, 16), profile.TeacherName);
        }
        else if (profile.Graduates > 0 || profile.Students > 0)
        {
            payload[45] = 2;
            payload[46] = (byte)Math.Min(255, profile.Students);
            payload[50] = (byte)Math.Min(255, profile.Graduates);
        }
    }

}
