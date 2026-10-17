using System.Security.Cryptography;
using System.Text.Json;

namespace OpenNanaimo.Adapter.Services;

// Trusted server-side review input, never data accepted from a client packet.
// No production review provider is installed: catalog presence alone is not approval.
internal sealed record ChapterRewardReview(uint QuestId, string PackageSha256, string ReviewId,
    bool Approved, IReadOnlyList<ChapterSourceReward> SourceRewards,
    IReadOnlyList<ushort> DurationDays);
internal sealed record ChapterRewardPlan(long Hans, long Experience,
    IReadOnlyList<ChapterSourceReward> Grants, string Digest, string ReviewId);

internal static class ChapterRewardPolicy
{
    internal static string PackageSha256 { get; } = HashPackage();

    private static string HashPackage()
    {
        using var stream = typeof(StoryChapterCatalog).Assembly.GetManifestResourceStream(StoryChapterCatalog.ResourceName)
            ?? throw new InvalidDataException("Missing chapter package");
        using var sha = SHA256.Create();
        return Convert.ToHexString(sha.ComputeHash(stream));
    }

    internal static ChapterRewardPlan? Resolve(uint quest, ChapterRewardReview? review)
    {
        if (quest < StoryChapterCatalog.FirstQuestId || quest > StoryChapterCatalog.LastQuestId
            || review is null || !review.Approved || review.QuestId != quest
            || !string.Equals(review.PackageSha256, PackageSha256, StringComparison.OrdinalIgnoreCase)
            || string.IsNullOrWhiteSpace(review.ReviewId) || review.ReviewId.Length > 128)
            return null;
        // Snapshot caller-owned collections before any asynchronous database work.
        var rewards = review.SourceRewards.ToArray();
        var days = review.DurationDays.ToArray();
        if (!rewards.SequenceEqual(StoryChapterCatalog.Get(quest).SourceRewards) || days.Length != rewards.Length)
            return null;
        long hans = 0, experience = 0;
        var grants = new List<ChapterSourceReward>();
        for (int i = 0; i < rewards.Length; i++)
        {
            var r = rewards[i];
            if (r.Amount == 0) return null;
            switch (r.Kind)
            {
                case 1 when r.Code == 0 && days[i] == 0:
                    hans = checked(hans + r.Amount);
                    break;
                case 7 when r.Code == 0 && days[i] == 0:
                    experience = checked(experience + r.Amount);
                    break;
                case 6 when CardCatalog.TryGet(r.Code, out _) && r.Amount <= 255 && days[i] == 0:
                    grants.Add(r);
                    break;
                case 2 or 4 when !CardCatalog.TryGet(r.Code, out _) && ShopCatalog.TryGet(r.Code, out var item)
                    && r.Amount <= ushort.MaxValue && days[i] == item.DurationDays
                    && (!item.HasExpiry || days[i] > 0):
                    grants.Add(r);
                    break;
                default:
                    return null; // An unsupported member blocks the entire chapter, including Hans.
            }
        }
        var bytes = JsonSerializer.SerializeToUtf8Bytes(new { quest, package = PackageSha256,
            review = review.ReviewId, rewards, days });
        return new(hans, experience, grants.ToArray(), Convert.ToHexString(SHA256.HashData(bytes)), review.ReviewId);
    }
}
