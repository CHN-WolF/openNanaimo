using System.Buffers.Binary;
using System.Linq.Expressions;
using System.Net;
using System.Net.Sockets;
using System.Reflection;
using Microsoft.Data.Sqlite;
using OpenNanaimo.Adapter.Services;

internal static class DeathRetryChecks
{
    private const BindingFlags Private = BindingFlags.Instance | BindingFlags.NonPublic;
    private delegate bool BeginBattle(object session, ReadOnlySpan<byte> frame);
    private static object? Get(object instance, string name) => instance.GetType().GetProperty(name)!.GetValue(instance);
    private static void Set(object instance, string name, object? value) => instance.GetType().GetProperty(name)!.SetValue(instance, value);
    private static T Call<T>(NetworkAdapterService service, string name, params object?[] args)
        => (T)typeof(NetworkAdapterService).GetMethod(name, Private)!.Invoke(service, args)!;
    private static ushort U16(byte[] frame, int offset) => BinaryPrimitives.ReadUInt16LittleEndian(frame.AsSpan(offset));
    private static void Check(bool value, string message)
    {
        if (!value) throw new InvalidOperationException(message);
        Console.WriteLine("PASS " + message);
    }

    // Controlled responses exercise production routing, not client rendering.
    private sealed class Worker : IAsyncDisposable
    {
        private readonly TcpListener listener = new(IPAddress.Loopback, 0);
        private readonly CancellationTokenSource stop = new();
        private readonly Task run;
        public int ResetRequests { get; private set; }
        public int Port => ((IPEndPoint)listener.LocalEndpoint).Port;
        public Worker(NativeDungeonState state, long uid)
        {
            listener.Start();
            run = Task.Run(async () =>
            {
                using var client = await listener.AcceptTcpClientAsync(stop.Token);
                var stream = client.GetStream();
                while (!stop.IsCancellationRequested)
                {
                    var header = new byte[8];
                    await stream.ReadExactlyAsync(header, stop.Token);
                    var body = new byte[U16(header, 4) - 8];
                    await stream.ReadExactlyAsync(body, stop.Token);
                    switch (U16(header, 6))
                    {
                        case 0xCF87:
                            var result = NativeDungeonClient.Frame(0xCF88, new byte[56]);
                            BinaryPrimitives.WriteUInt16LittleEndian(result.AsSpan(8), 1);
                            BinaryPrimitives.WriteUInt16LittleEndian(result.AsSpan(10), checked((ushort)uid));
                            BinaryPrimitives.WriteUInt16LittleEndian(result.AsSpan(12), checked((ushort)uid));
                            await stream.WriteAsync(result, stop.Token);
                            break;
                        case 0xCF8B:
                            ResetRequests++;
                            var reset = NativeDungeonClient.Frame(0xCF8C, new byte[40]);
                            reset[0x29] = body[1];
                            await stream.WriteAsync(reset, stop.Token);
                            break;
                        case 0xCFEB:
                            var map = NativeDungeonClient.Frame(0xCFEC, new byte[800]);
                            map[0x2DA] = body[0]; map[0x2DB] = body[2];
                            await stream.WriteAsync(map, stop.Token);
                            break;
                        case 0xF101:
                            await stream.WriteAsync(NativeDungeonClient.Frame(0xF102, state.Bytes), stop.Token);
                            break;
                    }
                }
            });
        }
        public async ValueTask DisposeAsync()
        {
            stop.Cancel(); listener.Stop();
            try { await run; }
            catch (Exception ex) when (ex is OperationCanceledException or IOException or SocketException) { }
            stop.Dispose();
        }
    }

    public static async Task RunAsync()
    {
        var root = Path.Combine(Path.GetTempPath(), "NanaimoDeathRetry", Guid.NewGuid().ToString("N"));
        Directory.CreateDirectory(root);
        File.WriteAllBytes(Path.Combine(root, "game.db"), []);
        var db = new DatabaseService(root);
        await db.InitializeAsync();
        var service = new NetworkAdapterService(db, Console.WriteLine, root) { NativeDungeonEnabled = true };
        var account = await db.OpenLocalAccountAsync("DeathRetry");
        await db.CreateLocalCharacterAsync(account, "DeathRetry", 0);
        var character = (await db.GetCharacterAsync(account))!;
        var type = typeof(NetworkAdapterService).GetNestedType("ConnectionSession", BindingFlags.NonPublic)!;
        var session = Activator.CreateInstance(type, true)!;
        var id = (string)Get(session, "SessionId")!;
        Check(await db.BeginWorldSessionAsync(account, character.Id, id, 1, "127.0.0.1"), "retry test owns world session");
        Set(session, "AccountId", account); Set(session, "Character", character);
        Set(session, "OnlineTracked", true); Set(session, "NativeForwarding", true);
        Set(session, "NativeDungeonSelectionValid", true); Set(session, "NativeBattleEpoch", 1L);
        var state = NativeDungeonState.Create(character, [], []);
        Set(session, "NativeCheckpoint", state);
        await using var worker = new Worker(state, character.Id);
        await using var client = new NativeDungeonClient(_ => Task.CompletedTask, worker.Port);
        await client.ConnectAsync(CancellationToken.None);
        Set(session, "NativeDungeon", client);
        var method = typeof(NetworkAdapterService).GetMethod("TryBeginNativeDungeonRevivalBattle", Private)!;
        var parameter = Expression.Parameter(typeof(object));
        var frameParameter = Expression.Parameter(typeof(ReadOnlySpan<byte>));
        var begin = Expression.Lambda<BeginBattle>(Expression.Call(Expression.Constant(service), method,
            Expression.Convert(parameter, type), frameParameter), parameter, frameParameter).Compile();
        var start = NativeDungeonClient.Frame(0xCF7F, []);
        var retry = NativeDungeonClient.Frame(0xCF8B, [0, 0, 1, 0]);
        Task<bool> Route(byte[] frame) => Call<Task<bool>>(service, "RouteNativeDungeonAsync", frame,
            U16(frame, 6), "WorldAdapter", session, CancellationToken.None);
        Task<byte[]?> Surrender() => Call<Task<byte[]?>>(service, "HandleNativeFrameCoreAsync",
            NativeDungeonClient.Frame(0xCF95, []), (ushort)0xCF95, "WorldAdapter", "test", "127.0.0.1", session, CancellationToken.None);
        try
        {
            Call<object?>(service, "ArmNativeDungeonRevivalCycle", session);
            Check(await Route(retry) && worker.ResetRequests == 0, "pre-settlement retry never reaches worker");
            Check(begin(session, start), "initial battle is armed once");
            for (var round = 0; round < 3; round++)
            {
                Set(session, "NativeDungeonDeathLatched", true);
                Set(session, "NativeBattleResources", new BattleResourceSnapshot(0, 40, 2)
                    { MaximumHp = 160, MaximumMp = 100, Epoch = 1 });
                Check(await Surrender() is { Length: 8 } ack && U16(ack, 6) == 0xCF96,
                    "death surrender returns CF96 without leaving the room");
                Check(await Surrender() is { Length: 8 }, "duplicate surrender keeps the same boundary");
                var revival = Call<object>(service, "GetNativeRevivalCycle", session);
                Check(!(bool)revival.GetType().GetField("BattleStarted")!.GetValue(revival)!
                    && (bool)revival.GetType().GetField("BattleSurrendered")!.GetValue(revival)!,
                    "surrender disables revival billing while retaining result retry provenance");
                Check(await Route(retry) && worker.ResetRequests == round, "surrender alone does not authorize retry");
                Check(await Route(NativeDungeonClient.Frame(0xCF87, new byte[4]))
                    && (bool)Get(session, "NativeDungeonSettlementAwaitingAction")!, "failure settlement opens result actions");
                Check(await Route(NativeDungeonClient.Frame(0xCF8B, [0, 0, 2, 0]))
                    && worker.ResetRequests == round, "failed settlement cannot advance to next dungeon");
                var cycle = (long)Get(session, "NativeSettlementCycle")!;
                Check(await Route(retry) && worker.ResetRequests == round + 1,
                    "CF95 -> CF87 -> CF8B reaches worker exactly once");
                Check(!(bool)Get(session, "NativeDungeonDeathLatched")!
                    && !(bool)Get(session, "NativeDungeonSettlementAwaitingAction")!
                    && (long)Get(session, "NativeSettlementCycle")! == cycle + 1,
                    "captured CF8C advances one result cycle and clears death");
                var resources = (BattleResourceSnapshot)Get(session, "NativeBattleResources")!;
                Check(resources.CurrentHp == 160 && resources.CurrentMp == 100 && resources.AttackMode == 0
                    && resources.SettlementFrozen, "retry restores resources but keeps old-battle damage frozen");
                Check(await Route(retry) && worker.ResetRequests == round + 1, "duplicate retry does not reset again");
                if (round == 1)
                {
                    Check(await Route(NativeDungeonClient.Frame(0xCFEB, new byte[4])),
                        "request-bound CFEB/CFEC reload is consumed");
                    Check(!((BattleResourceSnapshot)Get(session, "NativeBattleResources")!).SettlementFrozen,
                        "captured map reload rearms resources before start confirmation");
                    Check(!begin(session, start), "map reload already consumed the one armed resource reset");
                }
                else
                {
                    Check(begin(session, start), "accepted retry arms the next battle");
                    Call<object?>(service, "ArmNativeDungeonCombatResources", session);
                }
                await Call<Task>(service, "HandleNativeWorkerFrameAsync", session,
                    NativeDungeonClient.Frame(0xCF80, []), 1L, CancellationToken.None);
                Check(!((BattleResourceSnapshot)Get(session, "NativeBattleResources")!).SettlementFrozen,
                    "next loading confirmation unfreezes combat resources");
                Check(!begin(session, start), "duplicate start does not arm another battle");
                Check(!(bool)revival.GetType().GetField("BattleSurrendered")!.GetValue(revival)!,
                    "next battle clears the previous surrender marker");
            }
            Check((byte)Get(session, "NativeDungeonDungeon")! == 0 && (byte)Get(session, "NativeDungeonStage")! == 0,
                "three death retries retain the failed selection");
            Check((await db.GetCharacterAsync(account))!.Experience == 0, "zero-score retries never grant success rewards");
        }
        finally
        {
            Set(session, "NativeDungeon", null);
            await service.DisposeAsync();
            SqliteConnection.ClearAllPools();
            var parent = Path.GetFullPath(Path.Combine(Path.GetTempPath(), "NanaimoDeathRetry")) + Path.DirectorySeparatorChar;
            if (!Path.GetFullPath(root).StartsWith(parent, StringComparison.OrdinalIgnoreCase)) throw new InvalidOperationException("Unsafe test path");
            Directory.Delete(root, true);
        }
    }
}
