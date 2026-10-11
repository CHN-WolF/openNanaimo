using System.Buffers.Binary;
using System.Runtime.CompilerServices;
using OpenNanaimo.Adapter.Models;

namespace OpenNanaimo.Adapter.Services;

public sealed partial class NetworkAdapterService
{
    private readonly ConditionalWeakTable<byte[], object> _coupleExperienceFrames = new();
    private readonly ConditionalWeakTable<ConnectionSession, List<string>> _nativeFriendNames = new();

    private async Task RestoreNativeFriendNamesAsync(byte[] frames, ConnectionSession session, CancellationToken token)
    {
        var names = _nativeFriendNames.GetOrCreateValue(session);
        names.Clear();
        foreach (var contact in (await _database.GetNativeFriendContactsAsync(session.Character!.Id, token)).Take(20))
        {
            PrivateChatProtocol.WriteText(frames.AsSpan(0xF4 + names.Count * 16, 16), contact.Name);
            names.Add(contact.Name);
        }
        var blocks = await _database.GetNativeBlockedContactsAsync(session.Character.Id, token);
        for (var index = 0; index < blocks.Count; index++)
            PrivateChatProtocol.WriteText(frames.AsSpan(0x234 + index * 16, 16), blocks[index].Name);
    }

    private async Task<byte[]?> HandleNativeFriendAsync(
        byte[] frame, ushort opcode, byte[] payload, ConnectionSession session, CancellationToken token)
    {
        if (!IsTrackedWorldSession(session) || session.Character is not { } character) return null;
        if (opcode == 0xC5AC)
        {
            if (payload.Length != 0) return null;
            var contacts = await _database.GetNativeFriendContactsAsync(character.Id, token);
            var names = _nativeFriendNames.GetOrCreateValue(session);
            var result = new byte[4 + names.Count * 4];
            BinaryPrimitives.WriteUInt16LittleEndian(result, checked((ushort)names.Count));
            for (var index = 0; index < names.Count; index++)
                if (contacts.FirstOrDefault(c => c.Name == names[index]) is { } contact)
                    WriteNativeFriendPresence(result.AsSpan(4 + index * 4, 4), contact);
            var responses = new List<byte[]> { BuildNativeFrame(frame, 0xC5AD, result, session) };
            // The client creates positional UI rows before applying named changes.
            // Reconcile only at this request boundary, after those rows exist.
            foreach (var removed in names.Where(n => !contacts.Any(c => c.Name == n)).ToArray())
            {
                responses.Add(BuildNativeFrame(frame, 0xC5AF,
                    BuildNativeFriendResult(2, new CharacterRecord { Name = removed }), session));
                names.Remove(removed);
            }
            foreach (var added in contacts.Where(c => !names.Contains(c.Name)).Take(20 - names.Count))
            {
                responses.Add(BuildNativeFrame(frame, 0xC5AF, BuildNativeFriendResult(1, added), session));
                names.Add(added.Name);
            }
            return CombineNativeFrames(responses.ToArray());
        }
        if (payload.Length != 20) return null;
        var operation = BinaryPrimitives.ReadUInt16LittleEndian(payload);
        if (operation is not (1 or 2 or 3 or 4)
            || !PrivateChatProtocol.TryReadText(payload.AsSpan(4, 16), out var peerName)) return null;
        var clientNames = _nativeFriendNames.GetOrCreateValue(session);
        var duplicateName = operation == 1 && clientNames.Any(n => string.Equals(n, peerName, StringComparison.OrdinalIgnoreCase));
        if (operation == 1 && !duplicateName && clientNames.Count >= 20)
            return BuildNativeFrame(frame, 0xC5AF, BuildNativeFriendResult(operation, null), session);
        var changed = await _database.ApplyNativeFriendCommandAsync(
            session.AccountId, session.Character.Id, session.SessionId, operation, peerName, token);
        if (!changed.Success)
            return BuildNativeFrame(frame, 0xC5AF, BuildNativeFriendResult(operation, null), session);

        var peer = await _database.GetCharacterByIdAsync(changed.PeerId, token);
        if (peer is not null && operation == 1 && !duplicateName) clientNames.Add(peer.Name);
        if (peer is not null && operation == 2) clientNames.Remove(peer.Name);
        if (peer is not null && changed.Added)
        {
            RaiseFriendStateChanged();
            if (operation == 1)
            {
                var presence = _activeWorldSessions.Values.FirstOrDefault(item =>
                    item.CharacterId == peer.Id && IsTrackedWorldSession(item.Session));
                if (presence is not null)
                    session.PendingBroadcasts.Add(new PendingNativeBroadcast(presence, 0xCB25,
                        PrivateChatProtocol.BuildMessage("系统通知", $"{session.Character.Name}已加你为好友"),
                        "friend contact added"));
            }
        }
        if (duplicateName)
        {
            var duplicate = BuildNativeFriendResult(operation, null);
            BinaryPrimitives.WriteUInt16LittleEndian(duplicate, 10);
            return BuildNativeFrame(frame, 0xC5AF, duplicate, session);
        }
        // Addition and deletion acknowledge exactly the requested peer.
        // Deletion is idempotent and never emits an unsolicited contact result.
        // Its operation is independent of the number of persisted contacts.
        return BuildNativeFrame(frame, 0xC5AF, BuildNativeFriendResult(operation, peer), session);
    }

    private byte[] BuildNativeFriendResult(ushort operation, CharacterRecord? peer)
    {
        var payload = new byte[24];
        BinaryPrimitives.WriteUInt16LittleEndian(payload, peer is null ? (ushort)0 : (ushort)1);
        BinaryPrimitives.WriteUInt16LittleEndian(payload.AsSpan(2), operation);
        if (peer is not null)
        {
            PrivateChatProtocol.WriteText(payload.AsSpan(4, 16), peer.Name);
            WriteNativeFriendPresence(payload.AsSpan(20, 4), peer);
        }
        return payload;
    }

    private void WriteNativeFriendPresence(Span<byte> field, CharacterRecord character)
    {
        field.Clear();
        field[1] = CharacterTitleState.GetGrade(character);
        field[3] = checked((byte)Math.Clamp(character.Level, 1, CharacterProgression.MaximumLevel));
        var presence = _activeWorldSessions.Values.FirstOrDefault(item =>
            item.CharacterId == character.Id && IsTrackedWorldSession(item.Session));
        if (presence is null) return;
        field[0] = 1;
    }

    private async Task<byte[]?> HandlePrivateChatAsync(
        byte[] frame, byte[] payload, ConnectionSession session, CancellationToken token)
    {
        if (!IsTrackedWorldSession(session) || session.Character is not { } character
            || !PrivateChatProtocol.TryReadRequest(payload, out var peerName, out var text))
            return null;
        var peer = _activeWorldSessions.Values.FirstOrDefault(presence =>
            IsTrackedWorldSession(presence.Session)
            && presence.Session.Character is not null
            && string.Equals(presence.CharacterName, peerName, StringComparison.Ordinal));
        if (peer is null)
            return BuildNativeFrame(frame, 0xCB25,
                PrivateChatProtocol.BuildMessage("系统通知", "对方当前离线。"), session);
        if (await _database.IsPrivateChatBlockedAsync(character.Id, peer.CharacterId, token))
            return null;
        session.PendingBroadcasts.Add(new PendingNativeBroadcast(peer, 0xCB25,
            PrivateChatProtocol.BuildMessage(character.Name, text), "private chat"));
        return null;
    }

    private async Task<uint> GetCoupleRingAsync(ConnectionSession session, CancellationToken token)
        => session.Character is null ? 0
            : CoupleBenefitPolicy.NormalizeRingItemCode(
                (await _database.GetActiveCoupleRelationAsync(session.Character.Id, token))?.RingItemCode ?? 0);

    private WorldPresence? FindNativeDungeonPartner(ConnectionSession session, CoupleRelationRecord relation)
    {
        if (!IsTrackedWorldSession(session) || session.Character is null
            || session.NativeDungeon is null || session.NativeLease is null
            || !CoupleBenefitPolicy.TryResolveRingEffect(relation.RingItemCode, out _))
            return null;
        var partnerId = relation.GetPartnerId(session.Character.Id);
        return _activeWorldSessions.Values.FirstOrDefault(presence =>
            presence.CharacterId == partnerId && IsTrackedWorldSession(presence.Session)
            && presence.Session.NativeDungeon is not null
            && presence.Session.NativeLease?.Port == session.NativeLease.Port
            && presence.Session.NativeLease?.Generation == session.NativeLease.Generation
            && presence.Session.NativeDungeonSelectionValid && session.NativeDungeonSelectionValid
            && presence.Session.NativeDungeonHdIndex == session.NativeDungeonHdIndex
            && presence.Session.NativeDungeonEpisode == session.NativeDungeonEpisode
            && presence.Session.NativeDungeonDungeon == session.NativeDungeonDungeon
            && presence.Session.NativeDungeonStage == session.NativeDungeonStage
            && presence.Session.NativeDungeonLogicalDifficulty == session.NativeDungeonLogicalDifficulty);
    }

    private Task RefreshCoupleBenefitsAsync(ConnectionSession session, CancellationToken token)
        => RefreshCoupleBenefitsCoreAsync(session, token, false);

    private async Task RefreshCoupleBenefitsCoreAsync(ConnectionSession session, CancellationToken token, bool force)
    {
        if (session.NativeDungeon is null || session.NativeCheckpoint is null)
            return;
        var relation = session.Character is null ? null
            : await _database.GetActiveCoupleRelationAsync(session.Character.Id, token);
        var ring = CoupleBenefitPolicy.NormalizeRingItemCode(relation?.RingItemCode ?? 0);
        var partner = relation is null ? null : FindNativeDungeonPartner(session, relation);
        var partnerUid = IsNativeDungeonRecoveryActive(session)
            && partner is not null && IsNativeDungeonRecoveryActive(partner.Session)
            && partner.Session.NativeCheckpoint is { } partnerState
                ? checked((ushort)partnerState.Get(4)) : (ushort)0;
        if (!force && session.NativeCheckpoint.Get(CoupleBenefitPolicy.NativeRingOffset) == ring
            && session.NativeCheckpoint.Get(NativeDungeonState.CouplePartnerUidOffset) == partnerUid)
            return;
        await RefreshNativeCoupleMetadataAsync(session, ring, partnerUid, token);
    }

    private async Task ApplyNativeCoupleExperienceAsync(
        ConnectionSession session, byte[] response, CancellationToken token)
    {
        if (session.Character is null || session.NativeCheckpoint is null
            || _coupleExperienceFrames.TryGetValue(response, out _)
            || !TryReadNativeDungeonSettlementFrame(response,
                checked((ushort)session.NativeCheckpoint.Get(4)), out _, out var score, out _))
            return;
        var relation = await _database.GetActiveCoupleRelationAsync(session.Character.Id, token);
        var amount = checked((uint)Math.Max(0, score));
        var scaled = await ScaleSettlementScoreAsync(session, amount, relation?.RingItemCode ?? 0,
            relation is not null && FindNativeDungeonPartner(session, relation) is not null, token);
        var count = BinaryPrimitives.ReadUInt16LittleEndian(response.AsSpan(8));
        for (var index = 0; index < count; index++)
        {
            var offset = 0x0C + index * 0x34;
            if (BinaryPrimitives.ReadUInt16LittleEndian(response.AsSpan(offset))
                != session.NativeCheckpoint.Get(4))
                continue;
            DungeonExperiencePolicy.WriteSettlementScore(response.AsSpan(offset, 0x34), amount, scaled);
            _coupleExperienceFrames.GetValue(response, static _ => new object());
            break;
        }
    }

    private Task PatchNativeCoupleFrameAsync(
        ConnectionSession session, byte[] response, CancellationToken token)
        => PatchValidatedNativeCoupleFrameAsync(session, response, token);
}
