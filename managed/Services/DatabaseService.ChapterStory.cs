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
            byte existingMask = await ReadChapterMonkMaskAsync(c, tx, character, token);
            after=ChapterStoryPolicy.ObserveExistingMonk(before,existingMask);
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
                ClearMask INTEGER NOT NULL CHECK(ClearMask BETWEEN 0 AND 15),
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
            // The recovered candidate carried ClearMask 0..7 and, in its earliest
            // shape, a narrower quest range. Both are widened here; nothing else is.
            string legacy=schema.Replace("ClearMask BETWEEN 0 AND 15", "ClearMask BETWEEN 0 AND 7");
            var accepted = new[]
            {
                Normalize(legacy),
                Normalize(legacy.Replace("BETWEEN 73000000 AND", "BETWEEN 73000004 AND")),
            };
            if (!accepted.Contains(Normalize(previous)))
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
        r.Close();
        var original = s;
        // Undo only the unclaimed current objective produced by the removed test
        // bypass. Never invent clear bits or revisit earlier claimed chapters.
        if (!s.Finished && s.ObjectiveIndex >= 2 && s.ClearMask < 8
            && ChapterStoryPolicy.Valid(s with { ClearMask = 8 }))
            s = s with { ObjectiveIndex = 1, RewardPending = false, Revision = checked(s.Revision + 1) };
        if (ChapterStoryPolicy.Valid(s) && !s.Finished && s.RewardPending)
        {
            var needed = StoryChapterCatalog.Get(s.QuestId).ExistingMonkMask;
            if (needed != 0 && (await ReadChapterMonkMaskAsync(c, tx, character, token) & needed) != needed)
                s = s with { RewardPending = false, Revision = checked(s.Revision + 1) };
        }
        if (!ChapterStoryPolicy.Valid(s))
        {
            // Rows written while an episode required three dungeons become valid
            // again once its real count is one; promote the settled mask instead
            // of dropping the character's session.
            if (!ChapterStoryPolicy.TryMigrateSettled(s, out var migrated))
                throw new InvalidDataException($"Corrupt chapter progress; refusing automatic repair: quest={s.QuestId} index={s.ObjectiveIndex} mask={s.ClearMask} pending={s.RewardPending}");
            s=migrated;
        }
        if (s != original)
        {
            using var fix=c.CreateCommand();fix.Transaction=tx;
            fix.CommandText="UPDATE CharacterChapterStory SET ObjectiveIndex=$index,RewardPending=$pending,Revision=$revision WHERE CharacterId=$id";
            fix.Parameters.AddWithValue("$index",s.ObjectiveIndex);
            fix.Parameters.AddWithValue("$pending",s.RewardPending);
            fix.Parameters.AddWithValue("$revision",s.Revision);
            fix.Parameters.AddWithValue("$id",character);
            await fix.ExecuteNonQueryAsync(token);
        }
        return s;
    }

    private static async Task<byte> ReadChapterMonkMaskAsync(SqliteConnection c, SqliteTransaction tx,
        long character, CancellationToken token)
    {
        using var command = c.CreateCommand(); command.Transaction = tx;
        command.CommandText = "SELECT 1 FROM sqlite_master WHERE type='table' AND name='CharacterMonkChallenges'";
        if (await command.ExecuteScalarAsync(token) is null) return 0;
        command.CommandText = "SELECT ClearMask FROM CharacterMonkChallenges WHERE CharacterId=$id";
        command.Parameters.AddWithValue("$id", character);
        var value = await command.ExecuteScalarAsync(token);
        return value is not null and not DBNull && Convert.ToInt64(value) is >= 0 and <= 15
            ? Convert.ToByte(value) : (byte)0;
    }

    /// <summary>
    /// Mirror the chapter's current objective into the fixed type-2 task slot.
    /// The slot holds one chapter at a time, the row is only projected when the
    /// stored progress matches the requested quest and objective, and the whole
    /// operation stays inside one authorized transaction.
    /// </summary>
    public async Task<bool> ActivateChapterTaskAsync(long account, long character, string session,
        uint questId, byte objectiveIndex, CancellationToken token = default)
    {
        if (!QuestCatalog.StoryChaptersEnabled
            || questId < StoryChapterCatalog.FirstQuestId || questId > StoryChapterCatalog.LastQuestId)
            return false;
        var chapter = StoryChapterCatalog.Get(questId);
        if (objectiveIndex > (chapter.ExistingMonkMask == 0 ? 2 : 3)) return false;
        await using var c = await OpenConnectionAsync(token);
        using var tx = c.BeginTransaction(deferred: false);
        if (!await ChapterAuthorizedAsync(c, tx, account, character, session, token)) return false;
        await EnsureChapterSchemaAsync(c, tx, token);
        var state = await ReadChapterRowAsync(c, tx, character, token);
        if (state is null || state.QuestId != questId || state.ObjectiveIndex != objectiveIndex) return false;
        // State3 is the current QT objective, not the dialogue phase. Keep it
        // within the actual three/four-row topology. Only the durable reward
        // gate can mark the task complete; an exit dialogue alone cannot satisfy
        // a village's fourth (monk) objective.
        var completed = objectiveIndex switch
        {
            0 => 0,
            1 => ChapterStoryPolicy.HasCleared(state.ClearMask, chapter.Episode) ? 2 : 1,
            _ => state.RewardPending ? chapter.ObjectiveIds.Count : 3
        };
        var rows = Math.Min(completed, chapter.ObjectiveIds.Count - 1);
        var submittable = state.RewardPending && !state.Finished ? 1 : 0;
        if (state.Finished)
        {
            using var remove = c.CreateCommand(); remove.Transaction = tx;
            remove.CommandText = "DELETE FROM CharacterTasks WHERE CharacterId=$id AND SlotType=2 AND QuestId=$quest";
            remove.Parameters.AddWithValue("$id", character);
            remove.Parameters.AddWithValue("$quest", questId);
            var removed = await remove.ExecuteNonQueryAsync(token);
            await tx.CommitAsync(token);
            return removed > 0;
        }
        var now = DateTime.UtcNow.ToString("O");
        using var clear = c.CreateCommand(); clear.Transaction = tx;
        clear.CommandText = "DELETE FROM CharacterTasks WHERE CharacterId=$id AND SlotType=2 AND QuestId<>$quest";
        clear.Parameters.AddWithValue("$id", character);
        clear.Parameters.AddWithValue("$quest", questId);
        var changed = await clear.ExecuteNonQueryAsync(token);
        using var upsert = c.CreateCommand(); upsert.Transaction = tx;
        upsert.CommandText = """
            INSERT INTO CharacterTasks(
                CharacterId, QuestId, TaskType, RuntimeState, State3,
                Progress1, Progress2, Progress3, SlotType, CreatedAt, UpdatedAt)
            VALUES($id, $quest, 2, 0, $rows, $submittable, 1, $index, 2, $now, $now)
            ON CONFLICT(CharacterId, QuestId) DO UPDATE SET
                TaskType=2, RuntimeState=0, State3=$rows, Progress1=$submittable,
                Progress2=1, Progress3=$index, SlotType=2, UpdatedAt=$now
            """;
        upsert.Parameters.AddWithValue("$id", character);
        upsert.Parameters.AddWithValue("$quest", questId);
        upsert.Parameters.AddWithValue("$rows", rows);
        upsert.Parameters.AddWithValue("$submittable", submittable);
        upsert.Parameters.AddWithValue("$index", objectiveIndex);
        upsert.Parameters.AddWithValue("$now", now);
        changed += await upsert.ExecuteNonQueryAsync(token);
        await tx.CommitAsync(token);
        return changed > 0;
    }
}
