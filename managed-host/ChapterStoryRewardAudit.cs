using System.Text.Json;
using OpenNanaimo.Adapter.Services;

// Read-only catalog lookup. Matching numbers/names are NOT reward authorization.
internal static class ChapterStoryRewardAudit
{
    internal static void Run(string? output = null)
    {
        var rows=StoryChapterCatalog.Chapters.OrderBy(q=>q.Id).Select(q=>new
        {
            quest_id=q.Id,
            episode=q.Episode,
            rewards=q.SourceRewards.Select(r=>
            {
                bool found=false;
                string? name=null,source=null,section=null;
                ushort? days=null;
                uint? synthesis=null;
                if(r.Kind==6 && CardCatalog.TryGet(r.Code,out var card))
                {
                    found=true;name=card.Name;section="card";synthesis=card.SynthesisItemCode;
                    source="CardCatalog";
                }
                else if(r.Kind is 2 or 4 && ShopCatalog.TryGet(r.Code,out var item))
                {
                    found=true;name=item.Name;source=item.Source;section=item.Section.ToString();days=item.DurationDays;
                }
                else if(r.Kind is 1 or 7 && r.Code==0)
                {
                    found=true;name=r.Kind==1?"Hans":"Experience";source="existing-CN-quest-reward-kind";section="currency-or-growth";
                }
                return new { source_reward=new[]{r.Kind,r.Code,r.Amount},cn_catalog_present=found,
                    cn_name=name,cn_source=source,cn_section=section,cn_catalog_duration_days=days,
                    chapter_grant_duration_days=ChapterRewardPolicy.DurationDays(q.Id,r),
                    cn_synthesis_item_code=synthesis,
                    mapping_status=found?"candidate-identity-not-reviewed-grant":"missing-CN-catalog-identity",
                    grant_allowed=false };
            }).ToArray()
        }).ToArray();
        Console.WriteLine(JsonSerializer.Serialize(new {schema="openNanaimo.chapter-reward-audit.v1",
            runtime_acceptance=false,activation_allowed=false,chapters=rows},new JsonSerializerOptions{WriteIndented=true}));
        if (output is null) return;
        if (File.Exists(output))
            throw new InvalidDataException("Refusing to overwrite an existing reward review: " + output);
        // A template, not an approval: every chapter starts unapproved with an
        // empty review id so a human has to authorize it deliberately.
        var reviews = StoryChapterCatalog.Chapters.OrderBy(q => q.Id).Select(q => new
        {
            quest_id = q.Id,
            episode = q.Episode,
            approved = false,
            review_id = "",
            source_rewards = q.SourceRewards.Select(r => new[] { r.Kind, r.Code, r.Amount }).ToArray(),
            duration_days = q.SourceRewards.Select(r => ChapterRewardPolicy.DurationDays(q.Id, r)).ToArray(),
            catalog_identity_complete = q.SourceRewards.All(Resolved)
        }).ToArray();
        var document = new
        {
            schema = "openNanaimo.chapter-reward-review.v1",
            package_sha256 = ChapterRewardPolicy.PackageSha256,
            note = "Fill review_id and set approved=true only after the reward mapping review; "
                + "the adapter accepts this file as the review input and never grants unreviewed rewards.",
            runtime_acceptance = false,
            reviews
        };
        File.WriteAllBytes(output, JsonSerializer.SerializeToUtf8Bytes(document,
            new JsonSerializerOptions { WriteIndented = true }));
        Console.WriteLine("CHAPTER_REWARD_REVIEW_TEMPLATE " + Path.GetFullPath(output)
            + " reviews=" + reviews.Length + " approved=0");
    }

    private static bool Resolved(ChapterSourceReward reward)
        => reward.Kind switch
        {
            6 => CardCatalog.TryGet(reward.Code, out _),
            2 or 4 => ShopCatalog.TryGet(reward.Code, out _),
            1 or 7 => reward.Code == 0,
            _ => false
        };

}

// Loads the operator's reward review. It is validated against the embedded
// chapter package so a review for another package can never be replayed; the
// adapter still refuses any chapter left unapproved.
internal static class ChapterRewardReviewFile
{
    internal static IReadOnlyList<ChapterRewardReview> Load(string path)
    {
        using var document = JsonDocument.Parse(File.ReadAllBytes(path));
        var root = document.RootElement;
        if (root.GetProperty("schema").GetString() != "openNanaimo.chapter-reward-review.v1")
            throw new InvalidDataException("Unsupported chapter reward review: " + path);
        var package = root.GetProperty("package_sha256").GetString();
        if (!string.Equals(package, ChapterRewardPolicy.PackageSha256, StringComparison.OrdinalIgnoreCase))
            throw new InvalidDataException("Reward review belongs to another chapter package: " + path);
        var reviews = new List<ChapterRewardReview>();
        foreach (var row in root.GetProperty("reviews").EnumerateArray())
        {
            var quest = row.GetProperty("quest_id").GetUInt32();
            var rewards = row.GetProperty("source_rewards").EnumerateArray()
                .Select(triple => new ChapterSourceReward(triple[0].GetUInt32(), triple[1].GetUInt32(),
                    triple[2].GetUInt32())).ToArray();
            var days = row.GetProperty("duration_days").EnumerateArray()
                .Select(value => checked((ushort)value.GetUInt32())).ToArray();
            if (rewards.Length != days.Length)
                throw new InvalidDataException(
                    $"Reward review {quest} has {rewards.Length} rewards and {days.Length} durations");
            reviews.Add(new ChapterRewardReview(quest, package!, row.GetProperty("review_id").GetString() ?? "",
                row.GetProperty("approved").GetBoolean(), rewards, days));
        }
        if (reviews.Count == 0 || reviews.Select(row => row.QuestId).Distinct().Count() != reviews.Count)
            throw new InvalidDataException("Chapter reward review is empty or repeats a quest: " + path);
        return reviews;
    }
}
