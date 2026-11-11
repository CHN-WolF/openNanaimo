using System.Buffers.Binary;

namespace OpenNanaimo.Adapter.Services;

public sealed partial class NetworkAdapterService
{
    private sealed record SecretEntryAttempt(long CharacterId, int ChannelId, byte Town, byte Page,
        bool Granted);

    private async Task<byte[]?> HandleSecretEntryAsync(byte[] frame, byte[] payload,
        ConnectionSession session, CancellationToken token)
    {
        if (!session.OnlineTracked || session.Character is null || session.AuxiliaryGameSession
            || payload.Length != SceneTransitionRequestPayloadLength)
            return null;

        await session.InventoryGate.WaitAsync(token);
        try
        {
            var mode = BinaryPrimitives.ReadUInt32LittleEndian(payload);
            var character = session.Character;
            var attempt = session.SecretEntry;
            if (attempt is not null && (attempt.CharacterId != character.Id
                || attempt.ChannelId != session.ChannelId || attempt.Town != session.TownId
                || attempt.Page != session.TownPage))
                session.SecretEntry = attempt = null;

            SecretEntryResult result = default;
            if ((mode is 1 or 10) && (mode == 1 || attempt is not null))
            {
                result = await _database.ResolveSecretEntryAsync(session.AccountId, character.Id,
                    session.SessionId, session.TownId, mode == 10 && attempt is { Granted: false }, token);
                if (result.Action != 0)
                {
                    character.Hans = result.Hans;
                    character.Cash = result.Cash;
                    if (attempt is { Granted: true })
                        result = result with { Action = 20, Price = 0 };
                    session.SecretEntry = result.Action is 10 or 11 or 20
                        ? new(character.Id, session.ChannelId, session.TownId, session.TownPage,
                            result.Action is 11 or 20)
                        : null;
                }
                else session.SecretEntry = null;
            }
            else if (mode is not (1 or 10)) session.SecretEntry = null;

            var response = new byte[SceneTransitionResponsePayloadLength];
            BinaryPrimitives.WriteUInt16LittleEndian(response, result.Action);
            // C5AB action 11 inverts frame+11 into the client's closed-state gate.
            // A paid admission under our always-open policy must keep that gate clear.
            if (result.Action == 11) response[3] = 1;
            BinaryPrimitives.WriteUInt32LittleEndian(response.AsSpan(4), result.Price);
            _log($"Secret entry: character={character.Id} town={session.TownId} mode={mode} action={result.Action} price={result.Price} hans={character.Hans}");
            if (result.Action == 11) AccountStateChanged?.Invoke();
            // Unrequested C37B has no town consumer without a balance window and
            // blocks the receive queue. C378/C37A own subsequent wallet refreshes.
            return BuildNativeFrame(frame, 0xC5AB, response, session);
        }
        finally { session.InventoryGate.Release(); }
    }
}
