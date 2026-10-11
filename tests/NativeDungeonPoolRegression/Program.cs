using System.Net;
using System.Net.Sockets;
using OpenNanaimo.Adapter.Services;

static void Check(bool ok, string message)
{
    if (!ok) throw new InvalidOperationException(message);
    Console.WriteLine("PASS " + message);
}

using var listener = new TcpListener(IPAddress.Loopback, 0);
listener.Start();
var port = ((IPEndPoint)listener.LocalEndpoint).Port;
using var client = new TcpClient();
var connect = client.ConnectAsync(IPAddress.Loopback, port);
using var accepted = await listener.AcceptTcpClientAsync();
await connect;

Check(!NativeDungeonPool.IsPortConnectionQuiet(port),
    "an established connection keeps a worker port quarantined");
Check(!await NativeDungeonPool.WaitForPortQuietAsync(
        port, TimeSpan.FromMilliseconds(100), TimeSpan.FromMilliseconds(10), CancellationToken.None),
    "quiet wait times out while the old room connection is alive");

accepted.Dispose();
client.Dispose();
listener.Stop();
Check(await NativeDungeonPool.WaitForPortQuietAsync(
        port, TimeSpan.FromSeconds(3), TimeSpan.FromMilliseconds(10), CancellationToken.None),
    "quiet wait releases the port after both endpoints close");

Console.WriteLine("NATIVE_DUNGEON_POOL_REGRESSION_PASS");

var workerPath = Path.GetFullPath(args.Length > 0 ? args[0] : "adapter_runtime/nanaimo_gameplay_bridge.exe");
var root = Path.Combine(Path.GetTempPath(), "nanaimo-isolated-pool-" + Guid.NewGuid().ToString("N"));
Directory.CreateDirectory(root);
try
{
    await using var isolated = new NativeDungeonPool(workerPath, Path.Combine(root, "rooms"), usePrimaryWorker: false);
    await using var lease = await isolated.AcquireAsync("fixture", CancellationToken.None);
    Check(lease.Port != 52050, "isolated pool never borrows the live primary worker");
    var rooms = await isolated.GetSnapshotAsync(CancellationToken.None);
    Check(rooms.Count == 1 && rooms[0].ProcessId is > 0,
        "isolated pool owns a separate worker process even on its first lease");
    await using var native = new NativeDungeonClient(_ => Task.CompletedTask, lease.Port);
    await native.ConnectAsync(CancellationToken.None);
    var snapshot = await native.ExchangeAsync(null, null, CancellationToken.None);
    Check(snapshot.Bytes.Length > 0, "isolated worker returns its own native state");
}
finally
{
    Directory.Delete(root, recursive: true);
}
Console.WriteLine("ISOLATED_NATIVE_DUNGEON_POOL_REGRESSION_PASS");
