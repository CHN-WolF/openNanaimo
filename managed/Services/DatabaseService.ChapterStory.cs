using Microsoft.Data.Sqlite;

namespace OpenNanaimo.Adapter.Services;

public sealed partial class DatabaseService
{
    // Candidate API only. No live opcode invokes this until the CN renderer and wire contract close.
    internal async Task<ChapterStoryState?> ReadChapterStoryAsync(long account, long character, string session,
        bool explicitlyStart = false, CancellationToken token = default)
    {
        await using var c = await OpenConnectionAsync(token);
        using var tx = c.BeginTransaction(deferred:false);
        if (!await ChapterAuthorizedAsync(c,tx,account,character,session,token)) return null;
        await EnsureChapterSchemaAsync(c,tx,token);
        if (explicitlyStart)
        {
            using var insert = c.CreateCommand(); insert.Transaction=tx;
            insert.CommandText="""
                INSERT INTO CharacterChapterStory(CharacterId,QuestId,ObjectiveIndex,ClearMask,RewardPending,Finished,Revision)
                VALUES($id,$first,0,0,0,0,0) ON CONFLICT(CharacterId) DO NOTHING
                """;
            insert.Parameters.AddWithValue("$id",character);
            insert.Parameters.AddWithValue("$first",StoryChapterCatalog.FirstQuestId);
            await insert.ExecuteNonQueryAsync(token);
        }
        var state=await ReadChapterRowAsync(c,tx,character,token);
        await tx.CommitAsync(token); return state;
    }
    internal async Task<ChapterStoryState?> ApplyChapterDialogueAsync(long account,long character,string session,
        uint quest,long revision,int sourceScene,CancellationToken token=default)
        => await MutateChapterAsync(account,character,session,quest,revision,
            s=>ChapterStoryPolicy.ConfirmDialogue(s,revision,sourceScene),false,token);
    internal async Task<ChapterStoryState?> ApplyChapterSettlementAsync(long account,long character,string session,
        uint quest,long revision,int episode,int dungeon,CancellationToken token=default)
        => await MutateChapterAsync(account,character,session,quest,revision,
            s=>ChapterStoryPolicy.ClearSettled(s,episode,dungeon),false,token);
    internal async Task<ChapterStoryState?> RefreshChapterMonkAsync(long account,long character,string session,
        uint quest,long revision,CancellationToken token=default)
        => await MutateChapterAsync(account,character,session,quest,revision,s=>s,true,token);

    private async Task<ChapterStoryState?> MutateChapterAsync(long account,long character,string session,
        uint quest,long revision,Func<ChapterStoryState,ChapterStoryState> mutate,bool readMonk,CancellationToken token)
    {
        await using var c=await OpenConnectionAsync(token);
        using var tx=c.BeginTransaction(deferred:false);
        if (!await ChapterAuthorizedAsync(c,tx,account,character,session,token)) return null;
        await EnsureChapterSchemaAsync(c,tx,token);
        var before=await ReadChapterRowAsync(c,tx,character,token);
        if (before is null || before.QuestId!=quest || before.Revision!=revision) return null;
        var after=mutate(before);
        if (readMonk)
        {
            using var m=c.CreateCommand();m.Transaction=tx;
            m.CommandText="SELECT 1 FROM sqlite_master WHERE type='table' AND name='CharacterMonkChallenges'";
            if (await m.ExecuteScalarAsync(token) is not null)
            {
                m.CommandText="SELECT ClearMask FROM CharacterMonkChallenges WHERE CharacterId=$id";
                m.Parameters.AddWithValue("$id",character);
                var value=await m.ExecuteScalarAsync(token);
                if (value is not null and not DBNull && Convert.ToInt64(value) is >=0 and <=15)
                    after=ChapterStoryPolicy.ObserveExistingMonk(before,Convert.ToByte(value));
            }
        }
        if (!ChapterStoryPolicy.Valid(after)) throw new InvalidDataException("Invalid chapter transition");
        if (after!=before)
        {
            using var update=c.CreateCommand();update.Transaction=tx;
            update.CommandText="""
                UPDATE CharacterChapterStory SET ObjectiveIndex=$index,ClearMask=$mask,
                RewardPending=$pending,Revision=$next WHERE CharacterId=$id AND QuestId=$quest AND Revision=$rev
                """;
            update.Parameters.AddWithValue("$index",after.ObjectiveIndex);
            update.Parameters.AddWithValue("$mask",after.ClearMask);
            update.Parameters.AddWithValue("$pending",after.RewardPending);
            update.Parameters.AddWithValue("$next",after.Revision);
            update.Parameters.AddWithValue("$id",character);
            update.Parameters.AddWithValue("$quest",quest);
            update.Parameters.AddWithValue("$rev",revision);
            if (await update.ExecuteNonQueryAsync(token)!=1) throw new InvalidDataException("Chapter revision race");
        }
        await tx.CommitAsync(token);return after;
    }
    private static async Task<bool> ChapterAuthorizedAsync(SqliteConnection c,SqliteTransaction tx,long account,
        long character,string session,CancellationToken token)
    {
        using var query=c.CreateCommand();query.Transaction=tx;
        query.CommandText="""
            SELECT 1 FROM Characters c JOIN Accounts a ON a.Id=c.AccountId
            WHERE c.Id=$id AND c.AccountId=$account AND c.IsOnline=1 AND a.IsOnline=1
              AND c.ActiveSessionId=$session AND a.ActiveSessionId=$session AND c.TutorialCompleted=1
            """;
        query.Parameters.AddWithValue("$id",character);query.Parameters.AddWithValue("$account",account);
        query.Parameters.AddWithValue("$session",session);
        return await query.ExecuteScalarAsync(token) is not null;
    }
    private static async Task EnsureChapterSchemaAsync(SqliteConnection c,SqliteTransaction tx,CancellationToken token)
    {
        using var command=c.CreateCommand();command.Transaction=tx;
        const string schema="""
            CREATE TABLE IF NOT EXISTS CharacterChapterStory(
                CharacterId INTEGER PRIMARY KEY REFERENCES Characters(Id) ON DELETE CASCADE,
                QuestId INTEGER NOT NULL CHECK(QuestId BETWEEN 73000000 AND 73000015),
                ObjectiveIndex INTEGER NOT NULL CHECK(ObjectiveIndex BETWEEN 0 AND 3),
                ClearMask INTEGER NOT NULL CHECK(ClearMask BETWEEN 0 AND 7),
                RewardPending INTEGER NOT NULL CHECK(RewardPending IN(0,1)),
                Finished INTEGER NOT NULL CHECK(Finished IN(0,1)),
                Revision INTEGER NOT NULL CHECK(Revision>=0));
            """;
        command.CommandText="SELECT sql FROM sqlite_master WHERE type='table' AND name='CharacterChapterStory'";
        var previous=await command.ExecuteScalarAsync(token) as string;
        static string Normalize(string sql) => System.Text.RegularExpressions.Regex.Replace(
            sql.Replace("IF NOT EXISTS ","",StringComparison.OrdinalIgnoreCase)
                .Replace("\"CharacterChapterStory\"","CharacterChapterStory"),@"\s+","").TrimEnd(';').ToUpperInvariant();
        if (previous is not null && Normalize(previous)!=Normalize(schema))
        {
            string legacy=schema.Replace("BETWEEN 73000000 AND", "BETWEEN 73000004 AND");
            if (Normalize(previous)!=Normalize(legacy))
                throw new InvalidDataException("Unknown chapter schema; refusing lossy migration");
            command.CommandText="SELECT COUNT(*) FROM sqlite_master WHERE tbl_name='CharacterChapterStory' AND type IN ('index','trigger')";
            if (Convert.ToInt64(await command.ExecuteScalarAsync(token))!=0)
                throw new InvalidDataException("Custom chapter schema dependencies; refusing lossy migration");
            // Only the recovered candidate's exact schema is expanded. All progress is copied,
            // and schema plus rows roll back together with the caller's transaction.
            command.CommandText=schema.Replace("IF NOT EXISTS CharacterChapterStory(","CharacterChapterStoryExpanded(")+"""
                INSERT INTO CharacterChapterStoryExpanded
                    (CharacterId,QuestId,ObjectiveIndex,ClearMask,RewardPending,Finished,Revision)
                SELECT CharacterId,QuestId,ObjectiveIndex,ClearMask,RewardPending,Finished,Revision FROM CharacterChapterStory;
                DROP TABLE CharacterChapterStory;
                ALTER TABLE CharacterChapterStoryExpanded RENAME TO CharacterChapterStory;
                """;
            await command.ExecuteNonQueryAsync(token);
        }
        command.CommandText=schema;
        await command.ExecuteNonQueryAsync(token);
    }
    private static async Task<ChapterStoryState?> ReadChapterRowAsync(SqliteConnection c,SqliteTransaction tx,
        long character,CancellationToken token)
    {
        using var query=c.CreateCommand();query.Transaction=tx;
        query.CommandText="SELECT QuestId,ObjectiveIndex,ClearMask,RewardPending,Finished,Revision FROM CharacterChapterStory WHERE CharacterId=$id";
        query.Parameters.AddWithValue("$id",character);
        using var r=await query.ExecuteReaderAsync(token);
        if (!await r.ReadAsync(token)) return null;
        var s=new ChapterStoryState(checked((uint)r.GetInt64(0)),checked((byte)r.GetInt32(1)),checked((byte)r.GetInt32(2)),
            r.GetBoolean(3),r.GetBoolean(4),r.GetInt64(5));
        if (!ChapterStoryPolicy.Valid(s)) throw new InvalidDataException("Corrupt chapter progress; refusing automatic repair");
        return s;
    }
}
