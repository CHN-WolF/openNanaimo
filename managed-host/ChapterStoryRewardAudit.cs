using System.Text.Json;
using OpenNanaimo.Adapter.Services;

// Read-only catalog lookup. Matching numbers/names are NOT reward authorization.
internal static class ChapterStoryRewardAudit
{
    internal static void Run()
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
                    cn_synthesis_item_code=synthesis,
                    mapping_status=found?"candidate-identity-not-reviewed-grant":"missing-CN-catalog-identity",
                    grant_allowed=false };
            }).ToArray()
        }).ToArray();
        Console.WriteLine(JsonSerializer.Serialize(new {schema="openNanaimo.chapter-reward-audit.v1",
            runtime_acceptance=false,activation_allowed=false,chapters=rows},new JsonSerializerOptions{WriteIndented=true}));
    }
}
