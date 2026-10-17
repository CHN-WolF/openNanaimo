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
    // Explicit candidate policy; the KR type40 difficulty/settlement algorithm is not yet proven.
    internal const byte RequiredOrdinaryDungeonMask = 7;
    internal static bool Valid(ChapterStoryState s)
    {
        if (s.QuestId < StoryChapterCatalog.FirstQuestId || s.QuestId > StoryChapterCatalog.LastQuestId
            || s.Revision < 0 || s.ClearMask > 7) return false;
        var q = StoryChapterCatalog.Get(s.QuestId);
        if (s.ObjectiveIndex > (q.ExistingMonkMask == 0 ? 2 : 3)) return false;
        if (s.ObjectiveIndex == 0 && s.ClearMask != 0) return false;
        if (s.ObjectiveIndex == 1 && s.ClearMask == 7) return false;
        if (s.ObjectiveIndex >= 2 && s.ClearMask != 7) return false;
        if (s.RewardPending && s.ObjectiveIndex != (q.ExistingMonkMask == 0 ? 2 : 3)) return false;
        return !s.Finished || s.QuestId == StoryChapterCatalog.LastQuestId && s.RewardPending;
    }
    internal static ChapterStoryState ConfirmDialogue(ChapterStoryState s, long revision, int sourceScene)
    {
        if (!Valid(s) || s.Revision != revision || s.RewardPending || s.Finished
            || s.ObjectiveIndex is not (0 or 2)) return s;
        var q = StoryChapterCatalog.Get(s.QuestId);
        if (q.Dialogue.Single(d => d.ObjectiveIndex == s.ObjectiveIndex).SourceScene != sourceScene) return s;
        return s.ObjectiveIndex == 0
            ? s with { ObjectiveIndex = 1, Revision = checked(s.Revision+1) }
            : s with { ObjectiveIndex = (byte)(q.ExistingMonkMask == 0 ? 2 : 3),
                       RewardPending = q.ExistingMonkMask == 0, Revision = checked(s.Revision+1) };
    }
    internal static ChapterStoryState ClearSettled(ChapterStoryState s, int zeroBasedEpisode, int dungeon)
    {
        if (!Valid(s) || s.Finished || s.RewardPending || s.ObjectiveIndex != 1 || dungeon is < 0 or > 2
            || StoryChapterCatalog.Get(s.QuestId).Episode - 1 != zeroBasedEpisode) return s;
        var mask = (byte)(s.ClearMask | 1 << dungeon);
        if (mask == s.ClearMask) return s;
        return s with { ClearMask=mask, ObjectiveIndex=(byte)(mask == 7 ? 2 : 1), Revision=checked(s.Revision+1) };
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
