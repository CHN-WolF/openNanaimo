using System.Text;

namespace OpenNanaimo.Adapter.Services;

internal sealed record ChapterStoryState(uint QuestId, byte ObjectiveIndex, byte ClearMask, bool RewardPending,
    bool Finished, long Revision)
{
    internal static ChapterStoryState Start => new(StoryChapterCatalog.FirstQuestId, 0, 0, false, false, 0);
}
internal sealed record ChapterDialoguePage(int NpcId, uint TextId, IReadOnlyList<string> Lines,
    int SpeechIndex, int PageIndex, bool LastSpeechPage, IReadOnlyDictionary<string,string> SourceAttributes);

internal static class ChapterStoryPolicy
{
    // The chapter objective is "defeat the episode's super boss", not "clear
    // every dungeon of the episode". The settlement reports that fight as
    // dungeon bit 3 (dungeon + stage == 3), so the chapter waits for that bit.
    internal const byte SuperBossBit = 3;
    /// <summary>True when every bit the chapter requires is present in the mask.</summary>
    internal static bool HasCleared(int mask, int episode)
        => (mask & RequiredDungeonMask(episode)) == RequiredDungeonMask(episode);

    internal static byte RequiredDungeonMask(int episode) => (byte)(1 << SuperBossBit);
    // Settlement bits 0..3 exist for an episode; only bit 3 settles the chapter.
    // Kept so the host self-tests can walk every valid bit.
    internal static int RequiredDungeonCount(int episode) => 4;
    /// <summary>
    /// Resource-derived room binding: each of the first four towns has pages
    /// 31/52/73/94. The town is part of the identity; pages are not global.
    /// Original-client acceptance currently covers only town zero.
    /// </summary>
    internal static int DungeonRoomPage(int episode)
    {
        if (episode < 1 || episode > 16) return 0;
        // Local episode room pages repeat in each village pack namespace.
        return 31 + 21 * ((episode - 1) % 4);
    }
    internal static bool TryMigrateSettled(ChapterStoryState s, out ChapterStoryState migrated)
    {
        migrated = s;
        if (s.QuestId < StoryChapterCatalog.FirstQuestId || s.QuestId > StoryChapterCatalog.LastQuestId
            || s.Revision < 0 || s.ClearMask > 15 || s.ObjectiveIndex != 1) return false;
        var q = StoryChapterCatalog.Get(s.QuestId);
        if ((s.ClearMask & RequiredDungeonMask(q.Episode)) == 0) return false;
        migrated = s with { ObjectiveIndex = 2, Revision = checked(s.Revision + 1) };
        return Valid(migrated);
    }
    internal static bool Valid(ChapterStoryState s)
    {
        if (s.QuestId < StoryChapterCatalog.FirstQuestId || s.QuestId > StoryChapterCatalog.LastQuestId
            || s.Revision < 0 || s.ClearMask > 15) return false;
        var q = StoryChapterCatalog.Get(s.QuestId);
        if (s.ObjectiveIndex > (q.ExistingMonkMask == 0 ? 2 : 3)) return false;
        if (s.ObjectiveIndex == 0 && s.ClearMask != 0) return false;
        // Already-claimed terminal saves from the former test bypass remain historical.
        if (s.ObjectiveIndex >= 2 && !HasCleared(s.ClearMask, q.Episode) && !s.Finished) return false;
        if (s.RewardPending && s.ObjectiveIndex != (q.ExistingMonkMask == 0 ? 2 : 3)) return false;
        return !s.Finished || s.QuestId == StoryChapterCatalog.LastQuestId && s.RewardPending;
    }
    internal static ChapterStoryState ConfirmDialogue(ChapterStoryState s, long revision, int sourceScene)
    {
        if (!Valid(s) || s.Revision != revision || s.RewardPending || s.Finished
            || s.ObjectiveIndex is not (0 or 1 or 2)) return s;
        var q = StoryChapterCatalog.Get(s.QuestId);
        if (s.ObjectiveIndex == 1 && !HasCleared(s.ClearMask, q.Episode)) return s;
        // Objective 1 waits for the required settlement and exit room. The live
        // room event opens exit speech 2; it is not a final-page acknowledgement.
        var scene = s.ObjectiveIndex == 1 ? 2 : s.ObjectiveIndex;
        if (q.Dialogue.Single(d => d.ObjectiveIndex == scene).SourceScene != sourceScene) return s;
        if (s.ObjectiveIndex == 0)
            return s with { ObjectiveIndex = 1, Revision = checked(s.Revision+1) };
        if (s.ObjectiveIndex == 1)
            // The exit dialogue is confirmed in the room, so the reward becomes
            // claimable right there instead of one town event later (leaving the
            // page used to be required). Chapters that still have an existing monk
            // keep pending=false until that monk step sets it.
            return s with { ObjectiveIndex = 2, RewardPending = q.ExistingMonkMask == 0,
                            Revision = checked(s.Revision+1) };
        return s with { ObjectiveIndex = (byte)(q.ExistingMonkMask == 0 ? 2 : 3),
                        RewardPending = q.ExistingMonkMask == 0, Revision = checked(s.Revision+1) };
    }
    internal static ChapterStoryState ClearSettled(ChapterStoryState s, int zeroBasedEpisode, int dungeon)
    {
        if (!Valid(s) || s.Finished || s.RewardPending || s.ObjectiveIndex != 1
            || StoryChapterCatalog.Get(s.QuestId).Episode - 1 != zeroBasedEpisode) return s;
        var chapter = StoryChapterCatalog.Get(s.QuestId);
        // Any dungeon settlement records its bit; only the super boss bit settles
        // the chapter, and the mask comparison happens on the next room entry.
        if (dungeon < 0 || dungeon > 3) return s;
        var mask = (byte)(s.ClearMask | 1 << dungeon);
        if (mask == s.ClearMask) return s;
        // Finishing the last dungeon only records the mask; the exit dialogue
        // plays when the player walks back into the episode's dungeon room.
        return s with { ClearMask=mask, Revision=checked(s.Revision+1) };
    }
    internal static ChapterStoryState ObserveExistingMonk(ChapterStoryState s, byte existingMask)
    {
        if (!Valid(s) || s.Finished || s.RewardPending || s.ObjectiveIndex != 3 || existingMask > 15) return s;
        var needed = StoryChapterCatalog.Get(s.QuestId).ExistingMonkMask;
        return needed != 0 && (existingMask & needed) == needed
            ? s with { RewardPending=true, Revision=checked(s.Revision+1) } : s;
    }
    // Used by the isolated reviewed reward transaction, never directly by a client opcode.
    internal static ChapterStoryState AfterRewardTransaction(ChapterStoryState s, long expectedRevision)
    {
        if (!Valid(s) || s.Revision != expectedRevision || !s.RewardPending || s.Finished) return s;
        uint next = StoryChapterCatalog.Get(s.QuestId).NextId;
        return next == 0 ? s with { Finished=true, Revision=checked(s.Revision+1) }
            : new(next, 0, 0, false, false, checked(s.Revision+1));
    }
    internal static IReadOnlyList<ChapterDialoguePage> Pages(ChapterDefinition chapter, int index, string name)
    {
        Encoding.RegisterProvider(CodePagesEncodingProvider.Instance);
        var gbk = Encoding.GetEncoding(936, EncoderFallback.ExceptionFallback, DecoderFallback.ExceptionFallback);
        if (string.IsNullOrWhiteSpace(name) || name.Length > 64 || name.IndexOfAny(['#','\0','\r','\n','%','^','&']) >= 0)
            throw new ArgumentException("Invalid dialogue name", nameof(name));
        gbk.GetByteCount(name);
        var pages = new List<ChapterDialoguePage>();
        int speechIndex=0;
        foreach (var speech in chapter.Dialogue.Single(d => d.ObjectiveIndex == index).Speeches)
        {
            // Source/compiler restricts formatting to exact original tokens. Do not call native printf.
            string text = speech.Text.Replace("%s", name).Replace("%%", "%");
            var lines = new List<string>();
            foreach (string paragraph in text.Split("^&", StringSplitOptions.None))
            {
                string line = "";
                foreach (char c in paragraph)
                {
                    if (gbk.GetByteCount(line+c) > 48) { lines.Add(line); line=""; }
                    line += c;
                }
                lines.Add(line);
            }
            for (int i=0;i<lines.Count;i+=4)
                pages.Add(new(speech.NpcId,speech.TextId,lines.Skip(i).Take(4).ToArray(),
                    speechIndex,i/4,i+4>=lines.Count,speech.SourceAttributes));
            speechIndex++;
        }
        return pages;
    }
}
