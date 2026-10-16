using System.Text.Json;

namespace OpenNanaimo.Adapter.Services;

// Independent from QuestCatalog: no automatic type1/type0 enrollment or live C59C projection.
internal sealed record ChapterSpeech(uint TextId, int NpcId, string Text,
    IReadOnlyDictionary<string, string> SourceAttributes);
internal sealed record ChapterDialogue(int ObjectiveIndex, int SourceScene, IReadOnlyList<ChapterSpeech> Speeches);
internal sealed record ChapterSourceReward(uint Kind, uint Code, uint Amount);
internal sealed record ChapterDefinition(uint Id, int Episode, int Village, uint NextId, string Title,
    IReadOnlyList<uint> ObjectiveIds, IReadOnlyList<ChapterDialogue> Dialogue, byte ExistingMonkMask,
    IReadOnlyList<ChapterSourceReward> SourceRewards);

internal static class StoryChapterCatalog
{
    internal const uint FirstQuestId = 73_000_000, LastQuestId = 73_000_015;
    internal const string ResourceName = "OpenNanaimo.Adapter.StoryChapters.json";
    private static readonly Lazy<IReadOnlyDictionary<uint, ChapterDefinition>> Data = new(Load);
    internal static IReadOnlyCollection<ChapterDefinition> Chapters => Data.Value.Values.ToArray();
    internal static ChapterDefinition Get(uint id) => Data.Value.TryGetValue(id, out var value)
        ? value : throw new ArgumentOutOfRangeException(nameof(id));

    private static IReadOnlyDictionary<uint, ChapterDefinition> Load()
    {
        using var stream = typeof(StoryChapterCatalog).Assembly.GetManifestResourceStream(ResourceName)
            ?? throw new InvalidDataException("Missing chapter package");
        using var document = JsonDocument.Parse(stream);
        var root = document.RootElement;
        if (root.GetProperty("schema").GetString() != "openNanaimo.chapter-story.v1"
            || root.GetProperty("activation_allowed").GetBoolean()
            || root.GetProperty("runtime_acceptance").GetBoolean())
            throw new InvalidDataException("Unreviewed chapter activation contract");
        var result = new Dictionary<uint, ChapterDefinition>();
        foreach (var q in root.GetProperty("chapters").EnumerateArray())
        {
            uint id = q.GetProperty("quest_id").GetUInt32();
            int episode = q.GetProperty("episode").GetInt32();
            var objectives = q.GetProperty("objectives").EnumerateArray().ToArray();
            var dialogue = q.GetProperty("dialogue").EnumerateArray().Select(d => new ChapterDialogue(
                d.GetProperty("objective_index").GetInt32(), d.GetProperty("source_scene_selector").GetInt32(),
                d.GetProperty("speeches").EnumerateArray().Select(s => new ChapterSpeech(
                    s.GetProperty("qs_id").GetUInt32(), s.GetProperty("npc_uid").GetInt32(),
                    s.GetProperty("text").GetString()!,
                    s.GetProperty("source_attributes").EnumerateObject().ToDictionary(
                        a => a.Name, a => a.Value.GetString()!))).ToArray())).ToArray();
            var monk = q.GetProperty("existing_monk");
            byte mask = monk.ValueKind == JsonValueKind.Null ? (byte)0 : monk.GetProperty("clear_mask").GetByte();
            uint next = q.GetProperty("next_quest_id").GetUInt32();
            var rewards=q.GetProperty("source_rewards").EnumerateArray().Select(r =>
            {
                if(r.GetArrayLength()!=3)throw new InvalidDataException("Invalid source reward triple");
                return new ChapterSourceReward(r[0].GetUInt32(),r[1].GetUInt32(),r[2].GetUInt32());
            }).ToArray();
            if(q.GetProperty("rewards_resolved").GetBoolean() || rewards.Length==0
                || rewards.Any(r=>r.Amount==0 || r.Kind is not (1 or 2 or 4 or 6 or 7)))
                throw new InvalidDataException("Unreviewed chapter reward contract");
            if (id < FirstQuestId || id > LastQuestId || episode != id - 73_000_000 + 1
                || q.GetProperty("village_index").GetInt32() != (episode - 1) / 4
                || next != (id == LastQuestId ? 0 : id + 1)
                || !objectives.Select(o => o.GetProperty("kind").GetInt32()).SequenceEqual(
                    episode % 4 == 0 ? new[] {39,40,39,1} : new[] {39,40,39})
                || !dialogue.Select(d => d.ObjectiveIndex).SequenceEqual(new[] {0,2})
                || dialogue.Any(d => d.SourceScene != episode * 2 - 1 || d.Speeches.Count == 0
                    || d.Speeches.Any(s => s.TextId is >= 6000 and <= 6011 || string.IsNullOrWhiteSpace(s.Text)))
                || mask != (episode % 4 == 0 ? 1 << (episode / 4 - 1) : 0))
                throw new InvalidDataException("Invalid chapter topology");
            result.Add(id, new(id, episode, (episode-1)/4, next, q.GetProperty("title").GetString()!,
                objectives.Select(o => o.GetProperty("id").GetUInt32()).ToArray(), dialogue, mask,rewards));
        }
        if (result.Count != 16) throw new InvalidDataException("Incomplete chapter package");
        return result;
    }
}
