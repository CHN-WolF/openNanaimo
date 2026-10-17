using Microsoft.Data.Sqlite;

namespace OpenNanaimo.Adapter.Services;

internal enum ChapterClaimStatus { Rejected, ReviewRequired, CapacityExceeded, Claimed, AlreadyClaimed }
internal sealed record ChapterClaimResult(ChapterClaimStatus Status, ChapterStoryState? State);

public sealed partial class DatabaseService
{
    // Isolated candidate API. No opcode or production review provider calls it.
    internal async Task<ChapterClaimResult> ClaimChapterRewardsAsync(long account, long character, string session,
        uint quest, long revision, ChapterRewardReview? review = null, CancellationToken token = default)
    {
        var plan = ChapterRewardPolicy.Resolve(quest, review);
        await using var c = await OpenConnectionAsync(token);
        using var tx = c.BeginTransaction(deferred: false);
        if (!await ChapterAuthorizedAsync(c, tx, account, character, session, token))
            return new(ChapterClaimStatus.Rejected, null);
        await EnsureChapterSchemaAsync(c, tx, token);
        var before = await ReadChapterRowAsync(c, tx, character, token);
        if (plan is null) return new(ChapterClaimStatus.ReviewRequired, before);
        using var command = c.CreateCommand();
        command.Transaction = tx;
        command.CommandText = """
            CREATE TABLE IF NOT EXISTS CharacterChapterClaims(
                CharacterId INTEGER NOT NULL REFERENCES Characters(Id) ON DELETE CASCADE,
                QuestId INTEGER NOT NULL CHECK(QuestId BETWEEN 73000000 AND 73000015),
                Revision INTEGER NOT NULL CHECK(Revision>=0),
                RewardDigest TEXT NOT NULL, ReviewId TEXT NOT NULL, CreatedAt TEXT NOT NULL,
                PRIMARY KEY(CharacterId,QuestId));
            """;
        await command.ExecuteNonQueryAsync(token);
        command.Parameters.AddWithValue("$id", character);
        command.Parameters.AddWithValue("$quest", quest);
        command.CommandText = "SELECT Revision,RewardDigest FROM CharacterChapterClaims WHERE CharacterId=$id AND QuestId=$quest";
        using (var reader = await command.ExecuteReaderAsync(token))
        {
            if (await reader.ReadAsync(token))
                return new(reader.GetInt64(0) == revision && reader.GetString(1) == plan.Digest
                    ? ChapterClaimStatus.AlreadyClaimed : ChapterClaimStatus.Rejected, before);
        }
        if (before is null || before.QuestId != quest || before.Revision != revision
            || !before.RewardPending || before.Finished)
            return new(ChapterClaimStatus.Rejected, before);
        var after = ChapterStoryPolicy.AfterRewardTransaction(before, revision);
        if (after == before || !ChapterStoryPolicy.Valid(after))
            return new(ChapterClaimStatus.Rejected, before);

        // The shared inventory owner defines pet instances, terms and capacity.
        // Every mandatory member must be granted; a blank draw cannot settle this transaction.
        command.CommandText = "SELECT PetVariant FROM Characters WHERE Id=$id";
        int petVariant = Convert.ToInt32(await command.ExecuteScalarAsync(token));
        var inventoryBefore = await GetGameInventoryItemCodesAsync(c, tx, character, token);
        foreach (var reward in plan.Grants)
        {
            // The shared capacity helper assumes stored quantities are nonnegative integers.
            bool card = reward.Kind == 6;
            command.CommandText = card
                ? "SELECT 1 FROM CharacterCards WHERE CharacterId=$id AND CardCode=$code AND (typeof(Quantity)<>'integer' OR Quantity<0)"
                : "SELECT 1 FROM CharacterItems WHERE CharacterId=$id AND ItemCode=$code AND (typeof(Quantity)<>'integer' OR Quantity<0)";
            command.Parameters.AddWithValue("$code", reward.Code);
            if (await command.ExecuteScalarAsync(token) is not null)
                return new(ChapterClaimStatus.CapacityExceeded, before);
            command.Parameters.RemoveAt("$code");
            for (uint i = 0; i < reward.Amount; i++)
            {
                if (await CheckCardRewardCapacityAsync(c, tx, character, reward.Code, petVariant, token) != CardRewardCapacity.Available
                    || await GrantCardRewardAsync(c, tx, character, reward.Code, token) != CardRewardGrant.Granted)
                    return new(ChapterClaimStatus.CapacityExceeded, before);
            }
        }
        if (!await ReindexGameQuickSlotsAfterGrantAsync(c, tx, character, inventoryBefore, token)
            || !await GrantChapterCurrencyAsync(c, tx, character, plan, token))
            return new(ChapterClaimStatus.CapacityExceeded, before);

        command.Parameters.AddWithValue("$revision", revision);
        command.Parameters.AddWithValue("$digest", plan.Digest);
        command.Parameters.AddWithValue("$review", plan.ReviewId);
        command.Parameters.AddWithValue("$now", DateTime.UtcNow.ToString("O"));
        command.CommandText = """
            INSERT INTO CharacterChapterClaims(CharacterId,QuestId,Revision,RewardDigest,ReviewId,CreatedAt)
            VALUES($id,$quest,$revision,$digest,$review,$now)
            """;
        if (await command.ExecuteNonQueryAsync(token) != 1) throw new InvalidDataException("Chapter claim write failed");
        command.Parameters.AddWithValue("$nextQuest", after.QuestId);
        command.Parameters.AddWithValue("$index", after.ObjectiveIndex);
        command.Parameters.AddWithValue("$mask", after.ClearMask);
        command.Parameters.AddWithValue("$pending", after.RewardPending);
        command.Parameters.AddWithValue("$finished", after.Finished);
        command.Parameters.AddWithValue("$nextRevision", after.Revision);
        command.CommandText = """
            UPDATE CharacterChapterStory SET QuestId=$nextQuest,ObjectiveIndex=$index,ClearMask=$mask,
                RewardPending=$pending,Finished=$finished,Revision=$nextRevision
            WHERE CharacterId=$id AND QuestId=$quest AND Revision=$revision
            """;
        if (await command.ExecuteNonQueryAsync(token) != 1) throw new InvalidDataException("Chapter claim revision race");
        await tx.CommitAsync(token);
        return new(ChapterClaimStatus.Claimed, after);
    }

    private static async Task<bool> GrantChapterCurrencyAsync(SqliteConnection c, SqliteTransaction tx,
        long character, ChapterRewardPlan plan, CancellationToken token)
    {
        using var command = c.CreateCommand();
        command.Transaction = tx;
        command.Parameters.AddWithValue("$id", character);
        command.Parameters.AddWithValue("$hans", plan.Hans);
        command.Parameters.AddWithValue("$limit", long.MaxValue - plan.Hans);
        command.Parameters.AddWithValue("$now", DateTime.UtcNow.ToString("O"));
        command.CommandText = """
            UPDATE Characters SET Hans=Hans+$hans,LastSavedAt=$now
            WHERE Id=$id AND typeof(Hans)='integer' AND Hans BETWEEN 0 AND $limit
            """;
        if (await command.ExecuteNonQueryAsync(token) != 1) return false;
        if (plan.Experience == 0) return true;
        command.CommandText = """
            SELECT Level,Experience,MaxHp,MaxMp,CurveVersion FROM Characters
            WHERE Id=$id AND typeof(Experience)='integer'
            """;
        int oldLevel, maxHp, maxMp, curve;
        long experience;
        using (var reader = await command.ExecuteReaderAsync(token))
        {
            if (!await reader.ReadAsync(token)) return false;
            oldLevel = reader.GetInt32(0); experience = reader.GetInt64(1);
            maxHp = reader.GetInt32(2); maxMp = reader.GetInt32(3); curve = reader.GetInt32(4);
        }
        CharacterProgression.Validate(oldLevel, experience, curve);
        if (experience > CharacterProgression.MaximumExperience - plan.Experience) return false;
        experience += plan.Experience;
        int level = CharacterProgression.CalculateLevel(experience);
        command.Parameters.AddWithValue("$experience", experience);
        command.Parameters.AddWithValue("$level", level);
        command.Parameters.AddWithValue("$gained", level > oldLevel);
        command.Parameters.AddWithValue("$hp", Math.Max(maxHp, CharacterProgression.CalculateMaxHp(level)));
        command.Parameters.AddWithValue("$mp", Math.Max(maxMp, CharacterProgression.CalculateMaxMp(level)));
        command.CommandText = """
            UPDATE Characters SET Experience=$experience,Level=$level,MaxHp=$hp,MaxMp=$mp,
                CurrentHp=CASE WHEN $gained THEN $hp ELSE MIN(CurrentHp,$hp) END,
                CurrentMp=CASE WHEN $gained THEN $mp ELSE MIN(CurrentMp,$mp) END WHERE Id=$id
            """;
        return await command.ExecuteNonQueryAsync(token) == 1;
    }
}
