using System.Buffers.Binary;
using System.Reflection;
using Microsoft.Data.Sqlite;
using OpenNanaimo.Adapter.Models;
using OpenNanaimo.Adapter.Services;

internal static class QuestSystemChecks
{
    public static async Task RunAsync()
    {
        System.Text.Encoding.RegisterProvider(System.Text.CodePagesEncodingProvider.Instance);
        var root = Path.Combine(Path.GetTempPath(), "nanaimo-quest-system-" + Guid.NewGuid().ToString("N"));
        Directory.CreateDirectory(root);
        try
        {
            File.WriteAllBytes(Path.Combine(root, "game.db"), []);
            var db = new DatabaseService(root);
            await db.InitializeAsync();
            var account = await db.OpenLocalAccountAsync("quest-system-check");
            var characterId = await db.CreateLocalCharacterAsync(account, "QuestCheck", 1);
            await using var adapter = new NetworkAdapterService(db, Console.WriteLine, root);
            var adapterType = typeof(NetworkAdapterService);
            var sessionType = adapterType.GetNestedType("ConnectionSession", BindingFlags.NonPublic)!;
            var session = Activator.CreateInstance(sessionType, true)!;
            var sessionId = (string)Get(session, "SessionId")!;
            Check(await db.BeginWorldSessionAsync(account, characterId, sessionId, 1, "127.0.0.1"),
                "quest fixture begins an isolated world session");

            await using var sql = new SqliteConnection($"Data Source={db.DatabasePath}");
            await sql.OpenAsync();
            async Task Execute(string text, params (string Name, object Value)[] values)
            {
                await using var command = sql.CreateCommand();
                command.CommandText = text;
                foreach (var (name, value) in values) command.Parameters.AddWithValue(name, value);
                await command.ExecuteNonQueryAsync();
            }
            await Execute("UPDATE Characters SET TutorialCompleted=1,Hans=1000000000 WHERE Id=$id", ("$id", characterId));
            Set(session, "AccountId", account); Set(session, "Username", "quest-system-check");
            Set(session, "ChannelId", 1); Set(session, "ListenerPort", 12050);
            Set(session, "OnlineTracked", true); Set(session, "TownSceneActive", true);
            Set(session, "Character", (await db.GetCharacterAsync(account))!);

            var dispatch = adapterType.GetMethod("HandleNativeFrameAsync", BindingFlags.Instance | BindingFlags.NonPublic)!;
            ushort control = 1;
            async Task<byte[]> Dispatch(ushort opcode, byte[] payload)
            {
                var frame = NativeDungeonClient.Frame(opcode, payload);
                BinaryPrimitives.WriteUInt16LittleEndian(frame, control++);
                var output = await (Task<byte[]?>)dispatch.Invoke(adapter,
                    [frame, opcode, "WorldAdapter", "127.0.0.1:30000", "127.0.0.1", session, CancellationToken.None])!;
                return output ?? throw new InvalidDataException($"No response to {opcode:X4}");
            }

            Check(QuestCatalog.Quests.Count == 217 && QuestCatalog.Scrolls.Count == 204,
                "official QT/QH task catalogs load completely");
            Check(QuestCatalog.MainLineQuestIds.SequenceEqual(Enumerable.Range(0, 13).Select(i => 71_000_000u + (uint)i)),
                "mainline chain is the thirteen unsold QT story quests");
            Check(QuestCatalog.MainLineQuestIds.Take(12).All(id =>
                    QuestCatalog.TryGetQuest(id, out var quest)
                    && quest.Rewards.Any(reward => reward.RewardType == 8
                        && reward.RewardCode == 0 && reward.Amount == 1))
                && QuestCatalog.TryGetQuest(71_000_012u, out var epilogue)
                && !epilogue.Rewards.Any(reward => reward.RewardType == 8
                    && reward.RewardCode == 0 && reward.Amount == 1),
                "the exact QT type8/code0/amount1 tuple marks the twelve medal-granting mainline quests");
            Check(NetworkAdapterService.ResolveTaskCompletionKind(71_000_000u, 3) == 1
                && NetworkAdapterService.ResolveTaskCompletionKind(71_000_012u, 3) == 0
                && NetworkAdapterService.ResolveTaskCompletionKind(70_000_007u, 6) == 6,
                "C59A completion kind keeps ordinary task categories and maps only exact story-medal rewards to one");

            var firstVillage = await Dispatch(0xC354, []);
            var firstVillageReady = FindFrame(firstVillage, 0xC594);
            Check(Opcodes(firstVillage).SequenceEqual(new ushort[] { 0xC594, 0xC355, 0xC476, 0xC44C })
                && BinaryPrimitives.ReadUInt32LittleEndian(firstVillageReady.AsSpan(8, 4)) == 0,
                "first village entry restores zero completed story guides so Nemo and route guidance can start");

            var listFrames = await Dispatch(0xC59B, []);
            Check(ReadOpcode(listFrames) == 0xC59C && BinaryPrimitives.ReadUInt16LittleEndian(listFrames.AsSpan(4)) == 252,
                "C59B returns the fixed 252-byte C59C task list");
            Check(BinaryPrimitives.ReadUInt32LittleEndian(listFrames.AsSpan(8 + 224 + 12, 4)) == 71_000_000u,
                "first mainline quest is restored in fixed slot type 1");

            var beforeNemo = (await db.GetCharacterAsync(account))!;
            var nemoCompletion = new byte[80];
            BinaryPrimitives.WriteUInt16LittleEndian(nemoCompletion.AsSpan(0, 2), 0);
            BinaryPrimitives.WriteUInt16LittleEndian(nemoCompletion.AsSpan(2, 2), 0);
            BinaryPrimitives.WriteUInt32LittleEndian(nemoCompletion.AsSpan(4, 4), 0);
            nemoCompletion.AsSpan(8).Fill(0xA5);
            var nemoFrame = await Dispatch(0xC599, nemoCompletion);
            var afterNemo = (await db.GetCharacterAsync(account))!;
            var nemoState = await db.GetStoryGuideStateAsync(account, characterId, sessionId);
            Check(Opcodes(nemoFrame).SequenceEqual(new ushort[] { 0xC59A })
                && nemoFrame.Length == 36 && nemoFrame[8] == 0 && nemoFrame[9] == 1
                && BinaryPrimitives.ReadUInt32LittleEndian(nemoFrame.AsSpan(12, 4)) == 0
                && BinaryPrimitives.ReadUInt16LittleEndian(nemoFrame.AsSpan(16, 2)) == 0,
                "Nemo C599 type0/guide0 receives the exact C59A success tuple that closes the client guide state");
            static ushort Quantity(CharacterRecord character, uint itemCode)
                => character.Items.FirstOrDefault(item => item.ItemCode == itemCode)?.Quantity ?? 0;
            Check(nemoState.Authorized && (nemoState.Mask & 1) != 0
                && afterNemo.Hans == beforeNemo.Hans
                && Quantity(afterNemo, 46_000_008u) == Quantity(beforeNemo, 46_000_008u) + 1,
                "Nemo completion persists guide bit zero and its one-time 100-Hans certificate");
            var repeatedNemo = await Dispatch(0xC599, nemoCompletion);
            var afterRepeatedNemo = (await db.GetCharacterAsync(account))!;
            Check(repeatedNemo[8] == 0 && repeatedNemo[9] == 0
                && afterRepeatedNemo.Hans == afterNemo.Hans
                && Quantity(afterRepeatedNemo, 46_000_008u) == Quantity(afterNemo, 46_000_008u),
                "repeated Nemo completion acknowledges the waiting client without duplicating rewards");
            var certificateInventory = await Dispatch(0xC42F, []);
            var certificateIdentity = BinaryPrimitives.ReadUInt16LittleEndian(certificateInventory.AsSpan(16, 2));
            Check(ReadOpcode(certificateInventory) == 0xC430
                && BinaryPrimitives.ReadUInt16LittleEndian(certificateInventory.AsSpan(10, 2)) == 1
                && BinaryPrimitives.ReadUInt32LittleEndian(certificateInventory.AsSpan(12, 4)) == 46_000_008u
                && certificateIdentity != 0,
                "Nemo certificate is restored through the ordinary game-item inventory");
            var redeemCertificate = new byte[8];
            BinaryPrimitives.WriteUInt32LittleEndian(redeemCertificate, 46_000_008u);
            BinaryPrimitives.WriteUInt32LittleEndian(redeemCertificate.AsSpan(4), certificateIdentity);
            var redeemedFrames = await Dispatch(0xC46D, redeemCertificate);
            var redeemResult = FindFrame(redeemedFrames, 0xC46E);
            var afterRedeem = (await db.GetCharacterAsync(account))!;
            Check(Opcodes(redeemedFrames).SequenceEqual(new ushort[] { 0xC430, 0xC46E })
                && BinaryPrimitives.ReadUInt32LittleEndian(redeemResult.AsSpan(8, 4)) == 1
                && BinaryPrimitives.ReadUInt32LittleEndian(redeemResult.AsSpan(12, 4)) == 46_000_008u
                && BinaryPrimitives.ReadUInt32LittleEndian(redeemResult.AsSpan(16, 4)) == certificateIdentity
                && afterRedeem.Hans == afterNemo.Hans + 100
                && Quantity(afterRedeem, 46_000_008u) == 0,
                "using the 100-Hans certificate refreshes inventory, reports zero remaining and credits the wallet atomically");

            var firstProgress = await db.EvaluateQuestObjectivesAsync(account, characterId, sessionId, true,
                new QuestRunRestrictions(false, false, false, true, 0, 0, 0, 1000)
                { BattlePetCode = 15_000_010u, BossDefeated = true });
            Check(firstProgress.Changed && firstProgress.NewlyCompleted,
                "authoritative Epi1 dungeon1 clear completes the first mainline objective");
            var completion = new byte[80];
            BinaryPrimitives.WriteUInt16LittleEndian(completion.AsSpan(0, 2), 3);
            BinaryPrimitives.WriteUInt16LittleEndian(completion.AsSpan(2, 2), 1);
            BinaryPrimitives.WriteUInt32LittleEndian(completion.AsSpan(4, 4), 71_000_000u);
            completion.AsSpan(8).Fill(0xA5);
            Check(NetworkAdapterService.TryParseTaskCompletionRequest(completion, out var parsedType,
                    out var parsedState, out var parsedQuest)
                && parsedType == 3 && parsedState == 1 && parsedQuest == 71_000_000u,
                "C599 accepts the original client's non-zero opaque 72-byte tail");
            var completionFrames = await Dispatch(0xC599, completion);
            var firstLength = BinaryPrimitives.ReadUInt16LittleEndian(completionFrames.AsSpan(4));
            Check(ReadOpcode(completionFrames) == 0xC59A && firstLength == 36
                && completionFrames.Length > firstLength
                && Opcodes(completionFrames).SequenceEqual(new ushort[] { 0xC59A, 0xC430, 0xC379, 0xC59C }),
                "successful hand-in refreshes inventory and quick slots before the advanced task list");
            Check(BinaryPrimitives.ReadUInt16LittleEndian(completionFrames.AsSpan(16, 2)) == 1,
                "medal-granting mainline hand-in publishes C59A completion kind one even without a level gain");
            var storyState = await db.GetStoryGuideStateAsync(account, characterId, sessionId);
            Check(storyState.Authorized && storyState.Medals == 1,
                "the committed story-claim ledger persists one earned medal");
            var restoredProfile = await Dispatch(0xC354, []);
            var restoredReady = FindFrame(restoredProfile, 0xC594);
            var restoredC355 = FindFrame(restoredProfile, 0xC355);
            Check(Opcodes(restoredProfile).Take(2).SequenceEqual(new ushort[] { 0xC594, 0xC355 })
                && BinaryPrimitives.ReadUInt32LittleEndian(restoredReady.AsSpan(8, 4)) == 0x81
                && restoredC355[0xF3] == 1,
                "C354 reconnect restores Nemo plus mainline story progress before C355 and the persisted medal count");
            var tasks = await db.GetCharacterTasksAsync(account, characterId, sessionId);
            Check(tasks.Any(task => task.SlotType == 1 && task.QuestId == 71_000_001u),
                "hand-in atomically advances the fixed mainline slot");
            var rewarded = (await db.GetCharacterAsync(account))!;
            Check(rewarded.Items.Any(item => item.ItemCode == 15_005_009u && item.Quantity >= 1),
                "mainline item rewards persist with currency and EXP rewards");

            async Task SetStory(uint questId)
            {
                var now = DateTime.UtcNow.ToString("O");
                await Execute("DELETE FROM CharacterTasks WHERE CharacterId=$id AND SlotType=1", ("$id", characterId));
                await Execute("""
                    INSERT INTO CharacterTasks(CharacterId,QuestId,TaskType,RuntimeState,State3,Progress1,Progress2,Progress3,SlotType,CreatedAt,UpdatedAt)
                    VALUES($id,$quest,3,0,0,0,1,0,1,$now,$now)
                    """, ("$id", characterId), ("$quest", questId), ("$now", now));
            }

            await SetStory(71_000_006u);
            var multi1 = await db.EvaluateQuestObjectivesAsync(account, characterId, sessionId, true,
                new QuestRunRestrictions(false, false, false, true, 2, 0, 0, 1000));
            var multi1Task = (await db.GetCharacterTasksAsync(account, characterId, sessionId))
                .Single(task => task.QuestId == 71_000_006u);
            var multi1List = FindFrame(await Dispatch(0xC59B, []), 0xC59C);
            Check(multi1Task.State3 == 1 && multi1List[8 + 224 + 3] == 1
                && BinaryPrimitives.ReadUInt32LittleEndian(multi1List.AsSpan(8 + 224 + 12)) == 71_000_006u
                && multi1List.Length == 252,
                "Epi3 dungeon1 clear selects objective index one in the request-driven C59C mainline record");
            var multi2 = await db.EvaluateQuestObjectivesAsync(account, characterId, sessionId, true,
                new QuestRunRestrictions(false, false, false, true, 2, 0, 1, 1000));
            var multi2Task = (await db.GetCharacterTasksAsync(account, characterId, sessionId))
                .Single(task => task.QuestId == 71_000_006u);
            var multi2List = FindFrame(await Dispatch(0xC59B, []), 0xC59C);
            Check(multi2Task.State3 == 2 && multi2List[8 + 224 + 3] == 2,
                "Epi3 dungeon2 clear selects objective index two in C59C instead of changing only the aggregate count");
            var multi3 = await db.EvaluateQuestObjectivesAsync(account, characterId, sessionId, true,
                new QuestRunRestrictions(false, false, false, true, 2, 0, 2, 1000));
            tasks = await db.GetCharacterTasksAsync(account, characterId, sessionId);
            Check(multi1.Changed && !multi1.NewlyCompleted && multi2.Changed && !multi2.NewlyCompleted
                && multi3.Changed && multi3.NewlyCompleted
                && multi1Task.Progress3 == 1 && multi1Task.Progress1 == 0
                && multi2Task.Progress3 == 2 && multi2Task.Progress1 == 0
                && tasks.Single(task => task.QuestId == 71_000_006u).Progress3 == 3
                && tasks.Single(task => task.QuestId == 71_000_006u).Progress1 == 1,
                "multi-dungeon story objectives expose incremental progress and complete only after the full set");
            Check(tasks.Single(task => task.QuestId == 71_000_006u).State3 == 2,
                "completed multi-objective task retains the final valid index rather than dereferencing past QT objectives");

            // Preserve an old out-of-order ledger while repairing its stale UI cursor.
            await SetStory(71_000_006u);
            await Execute("INSERT INTO CharacterQuestObjectives VALUES($id,71000006,75000144,$now),($id,71000006,75000146,$now)",
                ("$id", characterId), ("$now", DateTime.UtcNow.ToString("O")));
            await Execute("UPDATE CharacterTasks SET Progress3=2 WHERE CharacterId=$id AND QuestId=71000006", ("$id", characterId));
            var repairList = FindFrame(await Dispatch(0xC59B, []), 0xC59C);
            var repairedTask = (await db.GetCharacterTasksAsync(account, characterId, sessionId))
                .Single(task => task.QuestId == 71_000_006u);
            Check(repairedTask.State3 == 1 && repairedTask.Progress3 == 2 && repairedTask.Progress1 == 0
                && repairedTask.RuntimeState == 0 && repairList[8 + 224 + 3] == 1,
                "C59B repairs old dungeon1-plus-dungeon3 progress to the missing dungeon2 without erasing either clear");
            var passiveRepairRepeat = await db.EvaluateQuestObjectivesAsync(account, characterId, sessionId, true,
                QuestRunRestrictions.None);
            Check(!passiveRepairRepeat.Changed && !passiveRepairRepeat.NewlyCompleted,
                "repaired objective cursor is idempotent and a passive refresh does not invent a clear");
            var cursorReopened = new DatabaseService(root);
            await cursorReopened.InitializeAsync();
            Check(await cursorReopened.BeginWorldSessionAsync(account, characterId, sessionId, 1, "127.0.0.1")
                && (await cursorReopened.GetCharacterTasksAsync(account, characterId, sessionId))
                    .Single(task => task.QuestId == 71_000_006u).State3 == 1,
                "the repaired current objective persists across database reopen");
            var missingClear = await db.EvaluateQuestObjectivesAsync(account, characterId, sessionId, true,
                new QuestRunRestrictions(false, false, false, true, 2, 0, 1, 1000));
            var allCleared = (await db.GetCharacterTasksAsync(account, characterId, sessionId))
                .Single(task => task.QuestId == 71_000_006u);
            Check(missingClear.NewlyCompleted && allCleared.State3 == 2
                && allCleared.Progress3 == 3 && allCleared.Progress1 == 1,
                "clearing the missing dungeon2 completes the preserved legacy ledger without replaying dungeon1 or dungeon3");

            async Task<(QuestScrollDefinition Scroll, QuestDefinition Quest)> PurchaseAndActivate(uint questId)
            {
                var scroll = QuestCatalog.Scrolls.Single(item => item.QuestId == questId);
                var purchase = await db.PurchaseQuestScrollAsync(account, characterId, sessionId, scroll);
                Check(purchase.Status == QuestScrollPurchaseStatus.Success, $"purchase quest {questId}");
                var activation = await db.ActivateQuestTaskAsync(account, characterId, sessionId, questId, 3, 0);
                Check(activation.Success, $"activate quest {questId}");
                return (scroll, QuestCatalog.Quests.Single(item => item.QuestId == questId));
            }

            await PurchaseAndActivate(70_000_007u); // type21: no charge
            var charged = await db.EvaluateQuestObjectivesAsync(account, characterId, sessionId, true,
                new QuestRunRestrictions(false, true, false, true, 0, 0, 2, 5000));
            Check(!charged.NewlyCompleted, "no-charge quest rejects a charged clear");
            var uncharged = await db.EvaluateQuestObjectivesAsync(account, characterId, sessionId, true,
                new QuestRunRestrictions(false, false, false, true, 0, 0, 2, 5000));
            Check(uncharged.NewlyCompleted, "no-charge quest accepts the matching clean clear");

            await PurchaseAndActivate(70_000_135u); // type22: no item
            var itemUsed = await db.EvaluateQuestObjectivesAsync(account, characterId, sessionId, true,
                new QuestRunRestrictions(true, false, false, true, 0, 0, 1, 5000));
            Check(!itemUsed.NewlyCompleted, "no-item quest rejects a clear after quick-item use");
            var noItem = await db.EvaluateQuestObjectivesAsync(account, characterId, sessionId, true,
                new QuestRunRestrictions(false, false, false, true, 0, 0, 1, 5000));
            Check(noItem.NewlyCompleted, "no-item quest accepts the matching clean clear");

            await PurchaseAndActivate(70_000_151u); // type23: no revival
            var revived = await db.EvaluateQuestObjectivesAsync(account, characterId, sessionId, true,
                new QuestRunRestrictions(false, false, true, true, 0, 0, 1, 5000));
            Check(!revived.NewlyCompleted, "no-revival quest rejects a revived clear");
            var noRevival = await db.EvaluateQuestObjectivesAsync(account, characterId, sessionId, true,
                new QuestRunRestrictions(false, false, false, true, 0, 0, 1, 5000));
            Check(noRevival.NewlyCompleted, "no-revival quest accepts the matching clean clear");

            // Characterization of current adapter policy, not proof of original-server rules.
            var expectedThresholds = new uint[] { 5000, 15000, 55000, 90000, 220000, 270000,
                360000, 420000, 630000, 750000, 820000, 1000000, 1100000, 1200000, 1300000, 1450000 };
            for (var episode = 0; episode < expectedThresholds.Length; episode++)
            {
                Check(QuestCatalog.TryGetQuest(70_000_071u + (uint)episode, out var scoreQuest)
                    && scoreQuest.Objectives.Count == 1
                    && QuestCatalog.TryGetScoreTarget(scoreQuest.Objectives[0], out var targetEpisode, out var threshold)
                    && targetEpisode == episode && threshold == expectedThresholds[episode],
                    $"QT score target episode {episode + 1} preserves its catalog threshold");
            }
            await PurchaseAndActivate(70_000_071u); // Epi 1 >= 5000
            async Task<bool> ScoreReady() => (await db.GetCharacterTasksAsync(account, characterId, sessionId))
                .Single(task => task.QuestId == 70_000_071u).Progress1 != 0;
            await db.EvaluateQuestObjectivesAsync(account, characterId, sessionId, true,
                new QuestRunRestrictions(false, false, false, true, 1, 0, 0, 5000));
            Check(!await ScoreReady(), "score-target policy rejects a different episode");
            await db.EvaluateQuestObjectivesAsync(account, characterId, sessionId, true,
                new QuestRunRestrictions(false, false, false, false, 0, 0, 0, 5000));
            Check(!await ScoreReady(), "score-target policy rejects a failed/non-clear result");
            await db.EvaluateQuestObjectivesAsync(account, characterId, sessionId, true, QuestRunRestrictions.None);
            Check(!await ScoreReady(), "passive refresh cannot complete score-target policy");
            await db.EvaluateQuestObjectivesAsync(account, characterId, sessionId, true,
                new QuestRunRestrictions(false, false, false, true, 0, 0, 0, 3000));
            await db.EvaluateQuestObjectivesAsync(account, characterId, sessionId, true,
                new QuestRunRestrictions(false, false, false, true, 0, 0, 1, 2000));
            Check(!await ScoreReady(), "current score-target policy does not add separate-stage settlements");
            var scoreSingleRun = await db.EvaluateQuestObjectivesAsync(account, characterId, sessionId, true,
                new QuestRunRestrictions(false, false, false, true, 0, 0, 1, 5000));
            Check(scoreSingleRun.NewlyCompleted && await ScoreReady(),
                "current score-target policy completes from one input score at the threshold");
            var repeatedScore = await db.EvaluateQuestObjectivesAsync(account, characterId, sessionId, true,
                new QuestRunRestrictions(false, false, false, true, 0, 0, 1, 5000));
            Check(!repeatedScore.NewlyCompleted && await ScoreReady(), "score-target completion is idempotent");
            var reopened = new DatabaseService(root);
            await reopened.InitializeAsync();
            Check(await reopened.BeginWorldSessionAsync(account, characterId, sessionId, 1, "127.0.0.1"),
                "database reinitialization requires a newly authorized world session");
            Check((await reopened.GetCharacterTasksAsync(account, characterId, sessionId))
                .Single(task => task.QuestId == 70_000_071u).Progress1 == 1,
                "completed score objective persists across database reopen");

            await SetStory(71_000_010u);
            var lowSkill = await db.AdvanceQuestActionAsync(account, characterId, sessionId, 52_000_000u, 1, false);
            var gradeTwo = await db.AdvanceQuestActionAsync(account, characterId, sessionId, 52_000_000u, 2, false);
            Check(!lowSkill.Changed && gradeTwo.Changed && gradeTwo.NewlyCompleted,
                "skill-use mainline objective enforces the catalogued grade");
            await SetStory(71_000_007u);
            var revivalAction = await db.AdvanceQuestActionAsync(account, characterId, sessionId, 0, 0, true);
            Check(revivalAction.Changed && revivalAction.NewlyCompleted,
                "successful revival advances the sacrifice mainline objective");

            await SetStory(71_000_003u);
            await Execute("""
                INSERT INTO CharacterItems(CharacterId,ItemCode,Quantity,UpdatedAt) VALUES($id,15000017,1,$now)
                ON CONFLICT(CharacterId,ItemCode) DO UPDATE SET Quantity=MAX(Quantity,1),UpdatedAt=excluded.UpdatedAt
                """, ("$id", characterId), ("$now", DateTime.UtcNow.ToString("O")));
            var synthesized = await db.EvaluateQuestObjectivesAsync(account, characterId, sessionId, true,
                QuestRunRestrictions.None);
            Check(synthesized.NewlyCompleted, "synthesized-pet ownership completes the card-synthesis story objective");

            await SetStory(71_000_009u);
            await Execute("""
                INSERT OR REPLACE INTO CharacterApartmentItems(CharacterId,SlotIndex,ItemCode,PositionX,PositionY,Layer,Mirror,InteriorType,UpdatedAt)
                VALUES($id,0,11430081,0,0,0,0,4,$now)
                """, ("$id", characterId), ("$now", DateTime.UtcNow.ToString("O")));
            var furnished = await db.EvaluateQuestObjectivesAsync(account, characterId, sessionId, true,
                QuestRunRestrictions.None);
            Check(furnished.NewlyCompleted, "placed apartment furniture completes the housing story objective");

            var mentorQuest = QuestCatalog.Quests.Single(quest =>
                QuestCatalog.MainLineQuestIds.Contains(quest.QuestId)
                && quest.Objectives.Count == 1 && quest.Objectives[0].ObjectiveType == 11);
            Check(mentorQuest.Objectives[0].RequiredCount == 2,
                $"QT mentor mainline {mentorQuest.QuestId} ({mentorQuest.Name}: {mentorQuest.Objectives[0].Name}) requires two accepted students");
            await SetStory(mentorQuest.QuestId);
            async Task CheckMentorProgress(uint expected, bool ready, string label)
            {
                var frames = await Dispatch(0xC59B, []);
                var list = FindFrame(frames, 0xC59C);
                var task = (await db.GetCharacterTasksAsync(account, characterId, sessionId))!
                    .Single(task => task.QuestId == mentorQuest.QuestId);
                Check(task.Progress3 == expected && task.Progress1 == (ready ? 1 : 0)
                    && task.State3 == 0
                    && BinaryPrimitives.ReadUInt32LittleEndian(list.AsSpan(8 + 224 + 8, 4)) == expected
                    && BinaryPrimitives.ReadUInt16LittleEndian(list.AsSpan(8 + 224 + 4, 2)) == (ready ? 1 : 0),
                    label);
            }
            await CheckMentorProgress(0, false, "mentor mainline starts at 0/2");
            var studentAccount = await db.OpenLocalAccountAsync("quest-mentor-student-one");
            var studentId = await db.CreateLocalCharacterAsync(studentAccount, "QuestStudent1", 1);
            var secondStudentAccount = await db.OpenLocalAccountAsync("quest-mentor-student-two");
            var secondStudentId = await db.CreateLocalCharacterAsync(secondStudentAccount, "QuestStudent2", 1);
            await Execute("INSERT INTO MentorshipRelations(TeacherCharacterId,StudentCharacterId,State,CreatedAt) VALUES($id,$student,0,$now)",
                ("$id", characterId), ("$student", studentId), ("$now", DateTime.UtcNow.ToString("O")));
            await CheckMentorProgress(1, false, "one active student persists and encodes 1/2 instead of zero");
            await Execute("UPDATE MentorshipRelations SET State=1,EndedAt=$now WHERE TeacherCharacterId=$id AND StudentCharacterId=$student",
                ("$id", characterId), ("$student", studentId), ("$now", DateTime.UtcNow.ToString("O")));
            await CheckMentorProgress(1, false, "graduation keeps the accepted student counted at 1/2");
            await Execute("INSERT INTO MentorshipRelations(TeacherCharacterId,StudentCharacterId,State,CreatedAt,EndedAt) VALUES($id,$student,1,$now,$now),($id,$second,2,$now,$now)",
                ("$id", characterId), ("$student", studentId), ("$second", secondStudentId), ("$now", DateTime.UtcNow.ToString("O")));
            await CheckMentorProgress(1, false, "duplicate graduated history and released relations do not inflate 1/2");
            await Execute("INSERT INTO MentorshipRelations(TeacherCharacterId,StudentCharacterId,State,CreatedAt) VALUES($id,$student,0,$now)",
                ("$id", characterId), ("$student", secondStudentId), ("$now", DateTime.UtcNow.ToString("O")));
            await CheckMentorProgress(2, true, "second distinct accepted student completes 2/2 without graduation");
            await CheckMentorProgress(2, true, "repeated mentor refresh preserves completion and valid objective index");

            Console.WriteLine("QUEST_SYSTEM_CHECKS_PASS");
        }
        finally
        {
            try { Directory.Delete(root, true); } catch { }
        }
    }

    private static ushort ReadOpcode(ReadOnlySpan<byte> frame)
        => frame.Length >= 8 ? BinaryPrimitives.ReadUInt16LittleEndian(frame.Slice(6, 2)) : (ushort)0;

    private static ushort[] Opcodes(byte[] response)
    {
        var result = new List<ushort>();
        for (var offset = 0; offset < response.Length;)
        {
            var length = BinaryPrimitives.ReadUInt16LittleEndian(response.AsSpan(offset + 4, 2));
            result.Add(BinaryPrimitives.ReadUInt16LittleEndian(response.AsSpan(offset + 6, 2)));
            offset += length;
        }
        return result.ToArray();
    }

    private static byte[] FindFrame(byte[] response, ushort opcode)
    {
        for (var offset = 0; offset < response.Length;)
        {
            var length = BinaryPrimitives.ReadUInt16LittleEndian(response.AsSpan(offset + 4, 2));
            if (BinaryPrimitives.ReadUInt16LittleEndian(response.AsSpan(offset + 6, 2)) == opcode)
                return response.AsSpan(offset, length).ToArray();
            offset += length;
        }
        throw new InvalidDataException($"Missing response frame {opcode:X4}");
    }

    private static object? Get(object instance, string name)
        => instance.GetType().GetProperty(name, BindingFlags.Instance | BindingFlags.Public | BindingFlags.NonPublic)!.GetValue(instance);

    private static void Set(object instance, string name, object? value)
        => instance.GetType().GetProperty(name, BindingFlags.Instance | BindingFlags.Public | BindingFlags.NonPublic)!.SetValue(instance, value);

    private static void Check(bool passed, string name)
    {
        if (!passed) throw new InvalidDataException("CHECK_FAILED " + name);
        Console.WriteLine("CHECK_PASS " + name);
    }
}
