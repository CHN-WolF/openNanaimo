using System.Buffers.Binary;
using System.Reflection;
using Microsoft.Data.Sqlite;
using OpenNanaimo.Adapter.Services;

// Isolated host construction only: no writes to a player's database or client.
internal static class ChapterMonkChecks
{
    internal static async Task RunAsync()
    {
        var root = Path.Combine(Path.GetTempPath(), "nanaimo-chapter-monk-" + Guid.NewGuid().ToString("N"));
        Directory.CreateDirectory(root);
        var previous = QuestCatalog.StoryChaptersEnabled;
        var checks = 0;
        void Check(bool ok, string label)
        {
            if (!ok) throw new InvalidDataException("CHAPTER_MONK_FAILED " + label);
            checks++;
        }
        try
        {
            QuestCatalog.StoryChaptersEnabled = true;
            File.WriteAllBytes(Path.Combine(root, "game.db"), []);
            var db = new DatabaseService(root);
            await db.InitializeAsync();
            await db.InitializeMonkChallengesAsync();
            var account = await db.OpenLocalAccountAsync("chapter-monk-check");
            var character = await db.CreateLocalCharacterAsync(account, "MonkChapter", 1);
            await using var adapter = new NetworkAdapterService(db, Console.WriteLine, root);
            var type = typeof(NetworkAdapterService);
            var sessionType = type.GetNestedType("ConnectionSession", BindingFlags.NonPublic)!;
            var session = Activator.CreateInstance(sessionType, true)!;
            object? Get(string name) => sessionType.GetProperty(name)!.GetValue(session);
            void Set(string name, object value) => sessionType.GetProperty(name)!.SetValue(session, value);
            var sid = (string)Get("SessionId")!;
            Check(await db.BeginWorldSessionAsync(account, character, sid, 1, "127.0.0.1"), "session starts");
            async Task<long> Sql(string text)
            {
                await using var c = new SqliteConnection($"Data Source={db.DatabasePath}");
                await c.OpenAsync();
                using var q = c.CreateCommand(); q.CommandText = text;
                q.Parameters.AddWithValue("$id", character);
                return Convert.ToInt64(await q.ExecuteScalarAsync());
            }
            await Sql("UPDATE Characters SET TutorialCompleted=1,Hans=1000000 WHERE Id=$id");
            Set("AccountId", account); Set("Username", "chapter-monk-check");
            Set("ChannelId", 1); Set("ListenerPort", 12050);
            Set("OnlineTracked", true); Set("TownSceneActive", true);
            Set("Character", (await db.GetCharacterAsync(account))!);
            await db.ReadChapterStoryAsync(account, character, sid, true);
            var ensure = type.GetMethod("EnsureSessionChapterTaskAsync", BindingFlags.Instance | BindingFlags.NonPublic)!;
            var dispatch = type.GetMethod("HandleNativeFrameAsync", BindingFlags.Instance | BindingFlags.NonPublic)!;
            async Task Ensure() => await (Task)ensure.Invoke(adapter, [session, CancellationToken.None])!;
            async Task<byte[]?> Dispatch(ushort opcode, byte[] payload)
                => await (Task<byte[]?>)dispatch.Invoke(adapter,
                    [NativeDungeonClient.Frame(opcode, payload), opcode, "WorldAdapter", "127.0.0.1:30000",
                     "127.0.0.1", session, CancellationToken.None])!;
            async Task<byte[]> Claim(uint quest, ushort taskType = 2, ushort runtime = 0)
            {
                var payload = new byte[80];
                BinaryPrimitives.WriteUInt16LittleEndian(payload, taskType);
                BinaryPrimitives.WriteUInt16LittleEndian(payload.AsSpan(2), runtime);
                BinaryPrimitives.WriteUInt32LittleEndian(payload.AsSpan(4), quest);
                // The opaque original tail must not be treated as reward instructions.
                payload.AsSpan(8).Fill(0xA7);
                return await Dispatch(0xC599, payload) ?? [];
            }
            static byte[] Frame(byte[] bytes, ushort opcode)
            {
                for (int i = 0; i + 8 <= bytes.Length;)
                {
                    var n = BinaryPrimitives.ReadUInt16LittleEndian(bytes.AsSpan(i + 4));
                    if (n < 8 || i + n > bytes.Length) throw new InvalidDataException("Invalid host frame");
                    if (BinaryPrimitives.ReadUInt16LittleEndian(bytes.AsSpan(i + 6)) == opcode)
                        return bytes.AsSpan(i, n).ToArray();
                    i += n;
                }
                throw new InvalidDataException($"Missing host frame {opcode:X4}");
            }
            ChapterRewardReview Review(uint quest)
            {
                var q = StoryChapterCatalog.Get(quest);
                return new(quest, ChapterRewardPolicy.PackageSha256, "host-fixture-only", true, q.SourceRewards,
                    q.SourceRewards.Select(r => ChapterRewardPolicy.DurationDays(quest, r)).ToArray());
            }
            foreach (var chapter in StoryChapterCatalog.Chapters)
            {
                var entry = new ChapterStoryState(chapter.Id, 1, 0, false, false, 1);
                for (byte mask = 0; mask < 8; mask++)
                {
                    var waiting = entry with { ClearMask = mask };
                    Check(!ChapterStoryPolicy.HasCleared(mask, chapter.Episode)
                        && ChapterStoryPolicy.ConfirmDialogue(waiting, 1, chapter.Episode * 2 - 1) == waiting,
                        "ordinary clears cannot replace super boss");
                }
                var cleared = ChapterStoryPolicy.ClearSettled(entry, chapter.Episode - 1, 3);
                Check(ChapterStoryPolicy.ConfirmDialogue(cleared, cleared.Revision, chapter.Episode * 2 - 1)
                    .ObjectiveIndex == 2, "super boss permits exit");
            }
            foreach (var episode in new[] { 4, 8, 12, 16 })
            {
                var quest = StoryChapterCatalog.FirstQuestId + (uint)episode - 1;
                var chapter = StoryChapterCatalog.Get(quest);
                await Sql($"UPDATE CharacterChapterStory SET QuestId={quest},ObjectiveIndex=2,ClearMask=8,RewardPending=0,Finished=0,Revision=100 WHERE CharacterId=$id");
                await Sql("DELETE FROM CharacterMonkChallenges WHERE CharacterId=$id");
                await Ensure();
                var slot = (await db.GetCharacterTasksAsync(account, character, sid)).Single(t => t.SlotType == 2);
                Check(slot.State3 == 3 && slot.Progress1 == 0 && slot.Progress3 == 2,
                    $"chapter {episode} exit keeps three objectives complete, fourth pending, dialogue phase intact");
                var denied = Frame(await Claim(quest), 0xC59A);
                Check(denied.Length == 36 && denied[8] != 0, "early click returns explicit rejection");
                var s = (await db.ReadChapterStoryAsync(account, character, sid))!;
                s = (await db.ApplyChapterDialogueAsync(account, character, sid, quest, s.Revision, episode * 2 - 1))!;
                Check(s.ObjectiveIndex == 3 && !s.RewardPending, "transition to monk does not award completion");
                Check(ChapterStoryPolicy.ObserveExistingMonk(s, 0) == s,
                    "strict policy still requires real monk completion");
                Check(ChapterStoryPolicy.ObserveExistingMonk(s, (byte)(15 ^ chapter.ExistingMonkMask)) == s,
                    "strict policy rejects other villages");
                Check(ChapterStoryPolicy.ObserveExistingMonk(s, chapter.ExistingMonkMask).RewardPending,
                    "strict policy accepts own village");
                var exit = s with { ObjectiveIndex = 2 };
                Check(ChapterStoryPolicy.ObserveExistingMonk(exit, 0) == exit, "monk cannot skip exit phase");
                Check(ChapterStoryPolicy.ObserveExistingMonk(s, 16) == s, "invalid mask remains rejected");
                    Check(await db.RefreshChapterMonkAsync(account, character, "foreign-session", quest, s.Revision) is null,
                        "session authorization");
                    Check(await db.RefreshChapterMonkAsync(account, character, sid, quest, s.Revision - 1) is null,
                        "revision gate");
                    await Ensure();
                    Check(!(await db.ReadChapterStoryAsync(account, character, sid))!.RewardPending,
                        "missing monk row blocks reward");
                    Check(await Sql("SELECT COUNT(*) FROM CharacterMonkChallenges WHERE CharacterId=$id") == 0,
                        "never fabricates challenge progress");
                {
                    await Sql($"INSERT INTO CharacterMonkChallenges VALUES($id,{15 ^ chapter.ExistingMonkMask},'fixture')");
                    await Ensure();
                    Check(!(await db.ReadChapterStoryAsync(account, character, sid))!.RewardPending,
                        "all other villages cannot satisfy own challenge");
                    // Exercise the real receipt/epoch transaction, not a fabricated UI completion.
                    await using (var c = new SqliteConnection($"Data Source={db.DatabasePath}"))
                    {
                        await c.OpenAsync(); using var tx = c.BeginTransaction();
                        var result = await DatabaseService.CommitMonkChallengeSuccessAsync(c, tx, character, sid,
                            new NativeDungeonSettlementRecord(0, (byte)(24 + episode / 4 - 1), 0, 0, 0, 3, 100, 100, 0, $"{episode}:0"));
                        Check(result.Applied, "authoritative solo fixture commits monk receipt");
                        tx.Commit();
                    }
                }
                await Ensure();
                s = (await db.ReadChapterStoryAsync(account, character, sid))!;
                Check(s.RewardPending && s.ObjectiveIndex == 3, "monk policy unlocks reward at final objective");
                var revision = s.Revision;
                await Ensure();
                Check((await db.ReadChapterStoryAsync(account, character, sid))!.Revision == revision,
                    "repeated list/login reconciliation is idempotent");
                slot = (await db.GetCharacterTasksAsync(account, character, sid)).Single(t => t.SlotType == 2);
                Check(slot.State3 == 3 && slot.Progress1 == 1 && slot.Progress3 == 3,
                    "four-objective slot uses valid final index and reward gate");
                var list = Frame((await Dispatch(0xC59B, []))!, 0xC59C);
                Check(list.Length == 252 && list[215] == 3 && BinaryPrimitives.ReadUInt16LittleEndian(list.AsSpan(216)) == 1
                    && BinaryPrimitives.ReadUInt32LittleEndian(list.AsSpan(224)) == quest,
                    "request-driven C59C serializes fixed type2 fourth objective");
                var review = Review(quest);
                adapter.StoryChapterRewards = [review];
                Check((await Claim(quest, 3)).Length == 0 && (await Claim(quest, 2, 1)).Length == 0,
                    "foreign category/runtime cannot claim chapter");
                var wrong = quest == StoryChapterCatalog.LastQuestId ? quest - 1 : quest + 1;
                Check(Frame(await Claim(wrong), 0xC59A)[8] != 0, "different requested quest cannot claim current reward");
                Check((await db.ReadChapterStoryAsync(account, character, sid))!.Revision == revision,
                    "rejected tuple preserves chapter revision");
                adapter.StoryChapterRewards = [];
                var missingReview = await Claim(quest);
                Check(Frame(missingReview, 0xC59A)[8] == 1, "missing review is not reported as inventory full");
                Check(Frame(missingReview, 0xCB25).Length > 8, "missing review sends request-driven explanation");
                adapter.StoryChapterRewards = [review];
                var resultFrames = await Claim(quest);
                var resolved = ChapterRewardPolicy.Resolve(quest, review) is not null;
                Check((Frame(resultFrames, 0xC59A)[8] == 0) == resolved, "claim respects complete reward identity");
                if (resolved)
                {
                    var next = (await db.ReadChapterStoryAsync(account, character, sid))!;
                    var tasks = await db.GetCharacterTasksAsync(account, character, sid);
                    Check(episode == 16 ? next.Finished && tasks.All(t => t.SlotType != 2)
                        : next.QuestId == quest + 1 && tasks.Single(t => t.SlotType == 2).QuestId == quest + 1,
                        "claim advances fixed slot or removes terminal chapter without chapter17");
                    var money = await Sql("SELECT Hans FROM Characters WHERE Id=$id");
                    Check(Frame(await Claim(quest), 0xC59A)[8] != 0, "replayed old quest cannot claim successor");
                    Check(await Sql($"SELECT COUNT(*) FROM CharacterChapterClaims WHERE CharacterId=$id AND QuestId={quest}") == 1
                        && await Sql("SELECT Hans FROM Characters WHERE Id=$id") == money, "replay cannot duplicate rewards");
                }
                else
                {
                    Check((await db.ReadChapterStoryAsync(account, character, sid))!.RewardPending,
                        "unresolved reward stays pending without partial claim");
                }
                Console.WriteLine($"CHAPTER_MONK_CASE episode={episode} rewardIdentityResolved={resolved}");
            }
            Check(await Sql("SELECT COUNT(*) FROM CharacterStoryClaims WHERE CharacterId=$id") == 0,
                "chapter claims do not mutate medal ledger");
            const uint fifth = 73000004;
            await Sql($"UPDATE CharacterChapterStory SET QuestId={fifth},ObjectiveIndex=2,ClearMask=8,RewardPending=1,Finished=0,Revision=400 WHERE CharacterId=$id");
            var fifthReview = Review(fifth);
            adapter.StoryChapterRewards = [fifthReview with { Approved = false, ReviewId = "" }];
            var unapproved = await Claim(fifth);
            Check(Frame(unapproved, 0xC59A)[8] == 1 && Frame(unapproved, 0xCB25).Length > 8,
                "episode5 unapproved reward explains review failure, not capacity");
            Check(PrivateChatProtocol.TryReadText(Frame(unapproved, 0xCB25).AsSpan(24, 32), out var notice)
                && notice == "奖励未审核或失效，进度已保留", "review explanation fits native GBK text field");
            Check((await db.ReadChapterStoryAsync(account, character, sid))!.Revision == 400,
                "review rejection preserves episode5 progress");
            adapter.StoryChapterRewards = [fifthReview];
            var card = StoryChapterCatalog.Get(fifth).SourceRewards.First(r => r.Kind == 6).Code;
            await Sql($"INSERT INTO CharacterCards(CharacterId,CardCode,Quantity,UpdatedAt) VALUES($id,{card},255,'fixture') ON CONFLICT(CharacterId,CardCode) DO UPDATE SET Quantity=255");
            Check(Frame(await Claim(fifth), 0xC59A)[8] == 3, "real episode5 capacity failure keeps inventory-full result");
            await Sql($"DELETE FROM CharacterCards WHERE CharacterId=$id AND CardCode={card}");
            Check(Frame(await Claim(fifth), 0xC59A)[8] == 0, "reviewed episode5 grants rewards when capacity permits");
            Check((await db.ReadChapterStoryAsync(account, character, sid))!.QuestId == fifth + 1,
                "episode5 advances only after actual reward commit");
            foreach (var phase in new[] { 2, 3 })
            foreach (var mask in new[] { 0, 1, 7 })
            {
                await Sql($"UPDATE CharacterChapterStory SET QuestId=73000003,ObjectiveIndex={phase},ClearMask={mask},RewardPending={(phase == 3 ? 1 : 0)},Finished=0,Revision=500 WHERE CharacterId=$id");
                var restored = (await db.ReadChapterStoryAsync(account, character, sid))!;
                Check(restored is { QuestId: 73000003, ObjectiveIndex: 1, RewardPending: false, Revision: 501 }
                    && restored.ClearMask == mask,
                    "legacy progress waits for real boss without losing chapter identity or ordinary clears");
                Check(await db.ReadChapterStoryAsync(account, character, sid) == restored, "legacy recovery idempotent");
            }
            await Sql("DROP TABLE CharacterMonkChallenges");
            foreach (var pending in new[] { 0, 1 })
            {
                await Sql($"UPDATE CharacterChapterStory SET QuestId=73000003,ObjectiveIndex=3,ClearMask=8,RewardPending={pending},Finished=0,Revision=600 WHERE CharacterId=$id");
                await Ensure();
                Check(!(await db.ReadChapterStoryAsync(account, character, sid))!.RewardPending,
                    "missing monk table blocks old bypass and new pending rewards");
                Check(await Sql("SELECT COUNT(*) FROM sqlite_master WHERE name='CharacterMonkChallenges'") == 0,
                    "chapter recovery does not create challenge table");
            }
            await Sql("UPDATE CharacterChapterStory SET QuestId=73000015,ObjectiveIndex=3,ClearMask=0,RewardPending=1,Finished=1,Revision=700 WHERE CharacterId=$id");
            Check((await db.ReadChapterStoryAsync(account, character, sid)) is { Finished: true, Revision: 700 },
                "already claimed terminal history remains untouched");
            Console.WriteLine($"CHAPTER_MONK_CHECKS_OK assertions={checks} runtime_acceptance=false");
        }
        finally
        {
            QuestCatalog.StoryChaptersEnabled = previous;
            SqliteConnection.ClearAllPools(); Directory.Delete(root, true);
        }
    }
}
