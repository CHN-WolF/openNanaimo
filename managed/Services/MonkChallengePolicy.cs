namespace OpenNanaimo.Adapter.Services;

public static class MonkChallengePolicy
{
    public const byte FirstEpisode = 24;
    public const int ChallengeCount = 4;
    public const byte FullClearMask = 0x0F;

    // Project policy: only newly crossed boundaries require their challenge.
    // Do not retroactively strand a legacy character returning to an old village.
    public static bool CanTravelForward(byte sourceTown, byte destinationTown, byte clearMask)
    {
        if (sourceTown > 4 || destinationTown > 4 || clearMask > FullClearMask) return false;
        if (destinationTown <= sourceTown) return true;
        var required = (1 << destinationTown) - (1 << sourceTown);
        return (clearMask & required) == required;
    }

    // Episodes 24..27 map to the four village-exit challenges.
    public static bool IsReservedEpisode(byte episode)
        => episode >= FirstEpisode && episode < FirstEpisode + ChallengeCount;

    public static bool TryGetChallengeIndex(
        byte hd, byte ep, byte dg, byte st, out int challengeIndex)
    {
        challengeIndex = -1;
        if (hd != 0 || dg != 0 || st != 0 || !IsReservedEpisode(ep)) return false;
        challengeIndex = ep - FirstEpisode;
        return true;
    }

    public static bool IsPlayableTuple(byte hd, byte ep, byte dg, byte st)
        => TryGetChallengeIndex(hd, ep, dg, st, out _);

    public static bool IsVillageEntry(byte episode, byte village, byte page)
        => IsReservedEpisode(episode) && village == episode - FirstEpisode
            && page == (village switch { 0 => 27, 1 => 26, 2 => 12, 3 => 6, _ => -1 });
}

public enum MonkChallengeCommitStatus
{
    InvalidSettlement,
    ChallengeClosed,
    Unauthorized,
    StaleSettlement,
    Duplicate,
    Applied
}

public readonly record struct MonkChallengeCommitResult(
    MonkChallengeCommitStatus Status, byte ClearMask, bool NewlyCleared)
{
    public bool Applied => Status == MonkChallengeCommitStatus.Applied;
}

public readonly record struct MonkChallengeProgressResult(bool Authorized, byte ClearMask);
