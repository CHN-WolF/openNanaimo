using Microsoft.Data.Sqlite;
using OpenNanaimo.Adapter.Models;
using OpenNanaimo.Adapter.Services;
using System.Text;

internal static class ChapterStoryChecks
{
    internal static async Task RunAsync()
    {
        int checks=0;
        void Check(bool ok,string label) {if(!ok)throw new InvalidOperationException(label);checks++;}
        Encoding.RegisterProvider(CodePagesEncodingProvider.Instance);
        QuestCatalog.StoryChaptersEnabled = true;
        var gbk=Encoding.GetEncoding(936,EncoderFallback.ExceptionFallback,DecoderFallback.ExceptionFallback);
        Check(StoryChapterCatalog.Chapters.Count==16,"16 chapters");
        Check(StoryChapterCatalog.Chapters.Sum(q=>q.ObjectiveIds.Count)==52,"52 objectives including reused monk references");
        Check(StoryChapterCatalog.Get(73000000).SourceRewards.SequenceEqual(new[]{
            new ChapterSourceReward(1,0,200),new ChapterSourceReward(6,13000020,10)}),"original episode1 reward triples retained");
        Check(QuestCatalog.MainLineQuestIds.SequenceEqual(Enumerable.Range(0,13).Select(i=>71_000_000u+(uint)i)),"medal chain unchanged");
        Check(QuestCatalog.Quests.Count(q => q.QuestId < StoryChapterCatalog.FirstQuestId || q.QuestId > StoryChapterCatalog.LastQuestId)==217
            && QuestCatalog.Scrolls.Count==204,"ordinary catalog unchanged");
        int speeches=0,pages=0;
        var s=ChapterStoryState.Start;
        foreach(var q in StoryChapterCatalog.Chapters.OrderBy(q=>q.Id))
        {
            Check(q.Id==s.QuestId && ChapterStoryPolicy.Valid(s),"sequential chapter");
            foreach(int index in new[]{0,2})
            {
                var rendered=ChapterStoryPolicy.Pages(q,index,"测试角色"); pages+=rendered.Count;
                foreach(var p in rendered)
                {
                    Check(p.Lines.Count is >=1 and <=4,"four native lines per page");
                    Check(p.Lines.All(l=>gbk.GetByteCount(l)<=48),"GBK byte width");
                    Check(p.TextId is <6000 or >6011,"no monk text duplication");
                    Check(p.Lines.All(l=>!l.Contains("%s")),"name formatted without native printf");
                }
                var expected=q.Dialogue.Single(d=>d.ObjectiveIndex==index).Speeches;
                Check(rendered.Select(p=>p.TextId).Distinct().SequenceEqual(expected.Select(e=>e.TextId).Distinct()),"speaker/text order");
                foreach(var p in rendered)
                    Check(p.SourceAttributes==expected[p.SpeechIndex].SourceAttributes,"action attributes survive pagination");
                Check(rendered.Count(p=>p.LastSpeechPage)==expected.Count,"one action terminal page per speech");
                speeches+=expected.Count;
            }
            Check(ChapterStoryPolicy.ClearSettled(s,q.Episode-1,0)==s,"no pre-dialogue clear");
            Check(ChapterStoryPolicy.ObserveExistingMonk(s,15)==s,"existing monk does not skip chapter");
            Check(ChapterStoryPolicy.ConfirmDialogue(s,s.Revision,999)==s,"wrong scene rejected");
            var old=s;s=ChapterStoryPolicy.ConfirmDialogue(s,s.Revision,q.Episode*2-1);
            Check(s.ObjectiveIndex==1,"entry advances one objective");
            Check(ChapterStoryPolicy.ConfirmDialogue(s,old.Revision,q.Episode*2-1)==s,"stale confirmation rejected");
            Check(ChapterStoryPolicy.ClearSettled(s,q.Episode,0)==s,"wrong episode rejected");
            var required = ChapterStoryPolicy.RequiredDungeonCount(q.Episode);
            Check(ChapterStoryPolicy.ClearSettled(s,q.Episode-1,required)==s,"dungeon beyond the episode count rejected");
            for (var dg = required - 1; dg >= 0; dg--)
            {
                s=ChapterStoryPolicy.ClearSettled(s,q.Episode-1,dg);
                Check(ChapterStoryPolicy.ClearSettled(s,q.Episode-1,dg)==s,"duplicate clear idempotent");
                Check(ChapterStoryPolicy.Valid(s),"clear state valid");
            }
            // Settling every dungeon records the mask but keeps objective 1: the
            // exit dialogue plays only when the player walks back into the room.
            Check(s.ObjectiveIndex==1 && s.ClearMask==15 && ChapterStoryPolicy.HasCleared(s.ClearMask,q.Episode),
                "all settled bits retained, super boss permits exit room");
            Check(ChapterStoryPolicy.AfterRewardTransaction(s,s.Revision)==s,"no early reward");
            s=ChapterStoryPolicy.ConfirmDialogue(s,s.Revision,q.Episode*2-1);
            Check(s.ObjectiveIndex==2 && s.RewardPending==(q.ExistingMonkMask==0),"exit opens and ordinary chapter becomes claimable");
            s=ChapterStoryPolicy.ConfirmDialogue(s,s.Revision,q.Episode*2-1);
            if(q.ExistingMonkMask!=0)
            {
                Check(s.ObjectiveIndex==3&&!s.RewardPending,"monk dependency pending");
                Check(ChapterStoryPolicy.ObserveExistingMonk(s,(byte)(15^q.ExistingMonkMask))==s,"wrong monk rejected");
                s=ChapterStoryPolicy.ObserveExistingMonk(s,q.ExistingMonkMask);
            }
            Check(s.RewardPending,"reward only after own objectives");
            Check(ChapterStoryPolicy.AfterRewardTransaction(s,s.Revision-1)==s,"stale claim rejected");
            s=ChapterStoryPolicy.AfterRewardTransaction(s,s.Revision);
        }
        Check(s.Finished && s.QuestId==StoryChapterCatalog.LastQuestId,"terminal without episode17");
        Check(ChapterStoryPolicy.AfterRewardTransaction(s,s.Revision)==s,"terminal replay idempotent");
        Check(speeches==107,"107 chapter speeches");
        Check(!ChapterStoryPolicy.Valid(ChapterStoryState.Start with {ObjectiveIndex=2}),"corrupt mask rejected");
        bool badName=false;try{ChapterStoryPolicy.Pages(StoryChapterCatalog.Get(StoryChapterCatalog.FirstQuestId),0,"%n");}
        catch(ArgumentException){badName=true;}Check(badName,"format injection rejected");

        var root=Path.Combine(Path.GetTempPath(),"nanaimo-chapter-"+Guid.NewGuid().ToString("N"));
        Directory.CreateDirectory(root);
        try
        {
            File.WriteAllBytes(Path.Combine(root,"game.db"),[]);
            var db=new DatabaseService(root);await db.InitializeAsync();
            long account=await db.OpenLocalAccountAsync("chapter-test");
            long character=await db.CreateLocalCharacterAsync(account,"ChapterTest",1);
            string session=Guid.NewGuid().ToString("N");
            Check(await db.BeginWorldSessionAsync(account,character,session,1,"127.0.0.1"),"world session");
            async Task Execute(string sql)
            {
                await using var c=new SqliteConnection($"Data Source={db.DatabasePath}");await c.OpenAsync();
                using var cmd=c.CreateCommand();cmd.CommandText=sql;cmd.Parameters.AddWithValue("$id",character);
                await cmd.ExecuteNonQueryAsync();
            }
            Check(await db.ReadChapterStoryAsync(account,character,session,true)==null,"tutorial gate");
            await Execute("UPDATE Characters SET TutorialCompleted=1 WHERE Id=$id");
            Check(await db.ReadChapterStoryAsync(account,character,session)==null,"no implicit grant");
            Check(await db.ReadChapterStoryAsync(account,character,"stale",true)==null,"stale session cannot grant");
            Check(await db.ReadChapterStoryAsync(account,character,session,true)==ChapterStoryState.Start,"explicit episode1 start");
            Check(await db.ReadChapterStoryAsync(account,character,session,true)==ChapterStoryState.Start,"start idempotent");
            var controller=new ChapterStorySession(db,account,character,session);
            await controller.EnterSceneAsync(999);
            Check(await controller.BeginDialogueAsync("测试角色")==null,"wrong scene no dialogue");
            await controller.EnterSceneAsync(1);
            var d=(await controller.BeginDialogueAsync("测试角色"))!.Value;
            Check(!await controller.AcknowledgePageAsync(d.Token,1),"out of order page");
            Check(await controller.AcknowledgePageAsync(d.Token,0),"first page");
            Check(!await controller.AcknowledgePageAsync(d.Token,0),"duplicate page");
            await controller.CancelDialogueAsync();
            Check(!await controller.AcknowledgePageAsync(d.Token,1),"cancel invalidates token");
            Check((await db.ReadChapterStoryAsync(account,character,session))!.ObjectiveIndex==0,"cancel not complete");
            d=(await controller.BeginDialogueAsync("测试角色"))!.Value;
            await controller.EnterSceneAsync(1);
            Check(!await controller.AcknowledgePageAsync(d.Token,0),"same-map new epoch invalidates token");
            d=(await controller.BeginDialogueAsync("测试角色"))!.Value;
            for(int i=0;i<d.Pages.Count;i++)Check(await controller.AcknowledgePageAsync(d.Token,i),"page acknowledgement");
            Check(!await controller.AcknowledgePageAsync(d.Token,d.Pages.Count-1),"complete cannot replay");
            Check((await db.ReadChapterStoryAsync(account,character,session))!.ObjectiveIndex==1,"entry persisted");
            var reopened=new DatabaseService(root);
            Check((await reopened.ReadChapterStoryAsync(account,character,session))!.ObjectiveIndex==1,"reopen preserves progress");
            Check(await db.ApplyChapterDialogueAsync(account,character,session,73000000,0,1)==null,"database revision gate");
            Check(await controller.BeginBattleAsync(0,0,0)==null,"zero epoch denied");
            Check(await controller.BeginBattleAsync(1,1,0)==null,"wrong battle episode denied");
            var token=(await controller.BeginBattleAsync(1,0,0))!.Value;
            var settlement=new NativeQuestSettlement(0,0,0,100){Authoritative=true,BattleEpoch=1};
            Check(!await controller.SettleBattleAsync(token,settlement with {Authoritative=false}),"untrusted settlement denied");
            Check(!await controller.SettleBattleAsync(token,settlement with {BattleEpoch=2}),"wrong battle epoch denied");
            await controller.EnterSceneAsync(1);
            Check(!await controller.SettleBattleAsync(token,settlement),"old scene settlement denied");
            Check(await controller.BeginBattleAsync(1,0,0)==null,"battle epoch cannot replay");
            var requiredDungeons = ChapterStoryPolicy.RequiredDungeonCount(
                StoryChapterCatalog.Get(73_000_000).Episode);
            for(int dg=0;dg<requiredDungeons;dg++)
            {
                uint epoch=(uint)(dg+2);token=(await controller.BeginBattleAsync(epoch,0,dg))!.Value;
                var clear=new NativeQuestSettlement(0,2,dg,100){Authoritative=true,BattleEpoch=epoch};
                Check(await controller.SettleBattleAsync(token,clear),"authoritative settlement persists");
                Check(!await controller.SettleBattleAsync(token,clear),"settlement token one-shot");
            }
            // Settling every dungeon only records the mask; the exit dialogue needs
            // the player back in the episode's dungeon room (page 31 for chapter 1).
            var settled=(await db.ReadChapterStoryAsync(account,character,session))!;
            Check(settled.ObjectiveIndex==1
                && settled.ClearMask==15 && ChapterStoryPolicy.HasCleared(settled.ClearMask,1),
                "exit waits for the room");
            var atRoom=await db.ApplyChapterDialogueAsync(account,character,session,settled.QuestId,
                settled.Revision,StoryChapterCatalog.Get(settled.QuestId).Episode*2-1);
            Check(atRoom is not null && atRoom.ObjectiveIndex==2,"room entry opens the exit");
            Check((await db.ReadChapterStoryAsync(account,character,session))!.ObjectiveIndex==2,"exit ready");
            var pending=(await db.ReadChapterStoryAsync(account,character,session))!;
            Check(pending.RewardPending && pending.QuestId==73000000,"unmapped rewards fail closed");
            Check(await controller.BeginDialogueAsync("测试角色")==null,"pending reward no repeat dialogue");
            await Execute("UPDATE CharacterChapterStory SET QuestId=73000007,ObjectiveIndex=3,ClearMask=8,RewardPending=0,Revision=100 WHERE CharacterId=$id");
            Check(!(await db.RefreshChapterMonkAsync(account,character,session,73000007,100))!.RewardPending,"missing monk progress rejected");
            await db.InitializeMonkChallengesAsync();
            Check(!(await db.RefreshChapterMonkAsync(account,character,session,73000007,100))!.RewardPending,"missing monk row rejected");
            await Execute("INSERT INTO CharacterMonkChallenges(CharacterId,ClearMask,UpdatedAt) VALUES($id,2,'test') ON CONFLICT(CharacterId) DO UPDATE SET ClearMask=2");
            Check((await db.RefreshChapterMonkAsync(account,character,session,73000007,100))!.RewardPending,"existing monk ledger reused");
            await Execute("UPDATE CharacterChapterStory SET ObjectiveIndex=0,ClearMask=0,RewardPending=0,Revision=200 WHERE CharacterId=$id");
            Check((await db.RefreshChapterMonkAsync(account,character,session,73000007,200))!.ObjectiveIndex==0,"old monk does not skip story");
            await using(var connection=new SqliteConnection($"Data Source={db.DatabasePath}"))
            {
                await connection.OpenAsync();
                using var command=connection.CreateCommand();
                command.CommandText="SELECT sql FROM sqlite_master WHERE name='CharacterChapterStory'";
                string schema=(string)(await command.ExecuteScalarAsync())!;
                using var transaction=connection.BeginTransaction();command.Transaction=transaction;
                command.CommandText="ALTER TABLE CharacterChapterStory RENAME TO ChapterStoryFixture;"+
                    schema.Replace("BETWEEN 73000000 AND","BETWEEN 73000004 AND").Replace("ClearMask BETWEEN 0 AND 15","ClearMask BETWEEN 0 AND 7")+";"+
                    "INSERT INTO CharacterChapterStory SELECT * FROM ChapterStoryFixture; DROP TABLE ChapterStoryFixture;";
                await command.ExecuteNonQueryAsync();await transaction.CommitAsync();
            }
            var legacy=await db.ReadChapterStoryAsync(account,character,session,true);
            Check(legacy is {QuestId:73000007,Revision:200,ObjectiveIndex:0},"old candidate progress preserved, not backfilled");
            await Execute("UPDATE CharacterChapterStory SET QuestId=73000000 WHERE CharacterId=$id");
            Check((await db.ReadChapterStoryAsync(account,character,session))!.QuestId==73000000,"legacy constraint expanded for episode1");
            await Execute("UPDATE CharacterChapterStory SET QuestId=73000007 WHERE CharacterId=$id");
            await controller.EnterSceneAsync(15);
            d=(await controller.BeginDialogueAsync("测试角色"))!.Value;
            await Execute("UPDATE Accounts SET ActiveSessionId='replaced'");
            Check(!await controller.AcknowledgePageAsync(d.Token,0),"revoked session rejects even nonfinal page");
            Check(await db.ReadChapterStoryAsync(account,character,session)==null,"account session invalidation");
            await Execute("UPDATE Accounts SET ActiveSessionId='"+session+"'");
            await Execute("ALTER TABLE CharacterChapterStory ADD COLUMN UnknownProgress INTEGER DEFAULT 17");
            bool unknownSchema=false;
            try { await db.ReadChapterStoryAsync(account,character,session,true); }
            catch(InvalidDataException){unknownSchema=true;}
            Check(unknownSchema,"unknown schema not silently migrated or reset");
        }
        finally {SqliteConnection.ClearAllPools();Directory.Delete(root,true);}
        Console.WriteLine($"CHAPTER_STORY_CHECKS_OK assertions={checks} chapters=16 speeches={speeches} pages={pages} runtime_acceptance=false activation_allowed=false");
        await ChapterRewardChecks.RunAsync();
    }
}
