namespace OpenNanaimo.Adapter.Services;

public static class MonkChallengePolicy
{
    public const byte FirstEpisode = 24;
    public const int ChallengeCount = 4;
    public const byte FullClearMask = 0x0F;

    // Episodes 25..27 reserve ledger positions only; they are not accepted challenges.
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
        => ep == FirstEpisode && TryGetChallengeIndex(hd, ep, dg, st, out _);
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
