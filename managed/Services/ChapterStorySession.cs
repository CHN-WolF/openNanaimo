using OpenNanaimo.Adapter.Models;

namespace OpenNanaimo.Adapter.Services;

// A candidate host session, not a wire handler. The future renderer must call this
// only with its actual page acknowledgements; arbitrary C5A0 is not accepted here.
internal sealed class ChapterStorySession
{
    private readonly DatabaseService database;
    private readonly long account, character;
    private readonly string session;
    private readonly SemaphoreSlim serial = new(1,1);
    private long sceneEpoch;
    private int? scene;
    private DialogueTicket? dialogue;
    private BattleTicket? battle;
    private uint lastBattleEpoch;
    private sealed record DialogueTicket(Guid Token,uint Quest,long Revision,long SceneEpoch,int Scene,
        IReadOnlyList<ChapterDialoguePage> Pages,int Page);
    private sealed record BattleTicket(Guid Token,uint Quest,long Revision,long SceneEpoch,uint BattleEpoch,int Episode,int Dungeon);
    internal ChapterStorySession(DatabaseService database,long account,long character,string session)
    { this.database=database;this.account=account;this.character=character;this.session=session; }

    internal async Task EnterSceneAsync(int? verifiedSourceScene)
    {
        await serial.WaitAsync();
        try { checked {sceneEpoch++;} scene=verifiedSourceScene;dialogue=null;battle=null; }
        finally {serial.Release();}
    }
    internal async Task CancelDialogueAsync()
    {
        await serial.WaitAsync();
        try { dialogue=null; }
        finally {serial.Release();}
    }
    internal async Task<(Guid Token,IReadOnlyList<ChapterDialoguePage> Pages)?> BeginDialogueAsync(string name)
    {
        await serial.WaitAsync();
        try
        {
            long epoch=sceneEpoch;int? location=scene;
            var state=await database.ReadChapterStoryAsync(account,character,session);
            if (epoch!=sceneEpoch || location is null || state is null || state.RewardPending || state.Finished
                || state.ObjectiveIndex is not (0 or 2)) return null;
            var q=StoryChapterCatalog.Get(state.QuestId);
            if (q.Dialogue.Single(d=>d.ObjectiveIndex==state.ObjectiveIndex).SourceScene!=location) return null;
            var pages=ChapterStoryPolicy.Pages(q,state.ObjectiveIndex,name);
            var token=Guid.NewGuid(); dialogue=new(token,state.QuestId,state.Revision,epoch,location.Value,pages,0);
            return (token,pages);
        }
        finally {serial.Release();}
    }
    internal async Task<bool> AcknowledgePageAsync(Guid token,int page)
    {
        await serial.WaitAsync();
        try
        {
            var d=dialogue;
            if (d is null || d.Token!=token || d.SceneEpoch!=sceneEpoch || d.Scene!=scene || d.Page!=page) return false;
            var state=await database.ReadChapterStoryAsync(account,character,session);
            if (state is null || state.QuestId!=d.Quest || state.Revision!=d.Revision
                || state.RewardPending || state.Finished || state.ObjectiveIndex is not (0 or 2))
            { dialogue=null; return false; }
            if (page+1<d.Pages.Count) {dialogue=d with {Page=page+1};return true;}
            dialogue=null;
            var result=await database.ApplyChapterDialogueAsync(account,character,session,d.Quest,d.Revision,d.Scene);
            return result is not null && result.Revision==d.Revision+1;
        }
        finally {serial.Release();}
    }
    internal async Task<Guid?> BeginBattleAsync(uint epoch,int episode,int dungeon)
    {
        await serial.WaitAsync();
        try
        {
            if (epoch==0 || epoch<=lastBattleEpoch || dungeon is <0 or >2) return null;
            long current=sceneEpoch;
            var state=await database.ReadChapterStoryAsync(account,character,session);
            if (current!=sceneEpoch || state is null || state.ObjectiveIndex!=1 || state.RewardPending || state.Finished
                || StoryChapterCatalog.Get(state.QuestId).Episode-1!=episode
                || scene != (episode+1)*2-1) return null;
            lastBattleEpoch=epoch;dialogue=null;
            var token=Guid.NewGuid();battle=new(token,state.QuestId,state.Revision,current,epoch,episode,dungeon);
            return token;
        }
        finally {serial.Release();}
    }
    internal async Task<bool> SettleBattleAsync(Guid token,NativeQuestSettlement settlement)
    {
        await serial.WaitAsync();
        try
        {
            var b=battle;
            if (b is null || b.Token!=token || b.SceneEpoch!=sceneEpoch || !settlement.Authoritative
                || settlement.BattleEpoch!=b.BattleEpoch || settlement.Episode!=b.Episode
                || settlement.DungeonBit!=b.Dungeon || settlement.Difficulty is <0 or >2) return false;
            battle=null;
            var result=await database.ApplyChapterSettlementAsync(account,character,session,b.Quest,b.Revision,b.Episode,b.Dungeon);
            return result is not null;
        }
        finally {serial.Release();}
    }
}
