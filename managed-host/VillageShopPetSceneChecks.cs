using System.Buffers.Binary;
using System.Collections;
using System.Reflection;
using System.Text;
using Microsoft.Data.Sqlite;
using OpenNanaimo.Adapter.Models;
using OpenNanaimo.Adapter.Services;

// Construction-only regression for the physical village shop actor path.
internal static class VillageShopPetSceneChecks
{
    private const BindingFlags Private = BindingFlags.Instance | BindingFlags.NonPublic;
    private static readonly Type ServiceType = typeof(NetworkAdapterService);
    private static readonly Type SessionType = ServiceType.GetNestedType("ConnectionSession", BindingFlags.NonPublic)!;
    private static readonly Type PresenceType = ServiceType.GetNestedType("WorldPresence", BindingFlags.NonPublic)!;
    private static int _checks;

    internal static async Task RunAsync()
    {
        Encoding.RegisterProvider(CodePagesEncodingProvider.Instance);
        var root = Path.Combine(Path.GetTempPath(), "open-nanaimo-shop-pet-" + Guid.NewGuid().ToString("N"));
        Directory.CreateDirectory(root);
        try
        {
            using (File.Create(Path.Combine(root, "game.db"))) { }
            var database = new DatabaseService(root);
            await database.InitializeAsync();
            await using var service = new NetworkAdapterService(database, _ => { }, root);

            var pet = ShopCatalog.All.First(item => item.Section == InventorySection.Pet
                && !item.IsPetMaterial
                && item.PetGoldDustItemCode != 0
                && ShopCatalog.TryGet(19, item.PetGoldDustItemCode, out _));
            var sourceCharacter = GoldenPet(101, "ShopSource", pet.ItemCode);
            var peerCharacter = GoldenPet(102, "ShopPeer", pet.ItemCode);
            var source = CreateSession(sourceCharacter, 1, "shop-source");
            var peer = CreateSession(peerCharacter, 2, "shop-peer");
            var sourcePresence = CreatePresence(source, sourceCharacter, 1);
            var peerPresence = CreatePresence(peer, peerCharacter, 2);

            var presences = ServiceType.GetField("_activeWorldSessions", Private)!.GetValue(service)!;
            presences.GetType().GetMethod("TryAdd")!.Invoke(presences, [
                (string)Get(source, "SessionId")!, sourcePresence]);
            presences.GetType().GetMethod("TryAdd")!.Invoke(presences, [
                (string)Get(peer, "SessionId")!, peerPresence]);

            var dispatch = ServiceType.GetMethod("HandleNativeFrameAsync", Private)!;
            var requestPayload = new byte[4];
            BinaryPrimitives.WriteUInt16LittleEndian(requestPayload.AsSpan(0, 2), 400);
            BinaryPrimitives.WriteUInt16LittleEndian(requestPayload.AsSpan(2, 2), 300);
            var directResponse = (byte[])(await (Task<byte[]?>)dispatch.Invoke(service, [
                NativeDungeonClient.Frame(0xC3AD, requestPayload),
                (ushort)0xC3AD,
                "WorldAdapter",
                "shop-test",
                "127.0.0.1",
                source,
                CancellationToken.None])!)!;
            Check(U16(directResponse, 6) == 0xC3AE,
                "C3AD returns the native C3AE shop actor response");

            var pending = Pending(source).Cast<object>().ToArray();
            Check(pending.Length == 5, "shop entry queues local plus bidirectional C3AE/C47F attachments");

            var local = pending.Where(item => ReferenceEquals(Get(item, "Target"), sourcePresence)).ToArray();
            var remote = pending.Where(item => ReferenceEquals(Get(item, "Target"), peerPresence)).ToArray();
            Check(local.Select(item => (ushort)Get(item, "Opcode")!).SequenceEqual(new ushort[] { 0xC47F, 0xC3AE, 0xC47F }),
                "shop entrant receives its own attachment then the existing peer snapshot");
            Check(remote.Select(item => (ushort)Get(item, "Opcode")!).SequenceEqual(new ushort[] { 0xC3AE, 0xC47F }),
                "existing shop occupant receives the entrant snapshot then attachment");

            var localPeerAttachment = Payload(local[2]);
            var remoteSourceAttachment = Payload(remote[1]);
            Check(localPeerAttachment[2] == 3 && localPeerAttachment[3] == 3
                && U32(localPeerAttachment, 36) == pet.ItemCode,
                "existing peer C47F preserves golden current/max stage and PET code");
            Check(remoteSourceAttachment[2] == 3 && remoteSourceAttachment[3] == 3
                && U32(remoteSourceAttachment, 36) == pet.ItemCode,
                "entrant C47F preserves golden current/max stage and PET code");

            var remoteShopSnapshot = Payload(remote[0]);
            Check(U32(remoteShopSnapshot, 48) == pet.ItemCode,
                "C3AE still carries the PET appearance code before C47F");
            Console.WriteLine($"VILLAGE_SHOP_PET_SCENE_CHECKS_PASS checks={_checks} construction-only");
        }
        finally
        {
            SqliteConnection.ClearAllPools();
            var full = Path.GetFullPath(root);
            var temp = Path.GetFullPath(Path.GetTempPath()).TrimEnd(Path.DirectorySeparatorChar)
                + Path.DirectorySeparatorChar;
            if (!full.StartsWith(temp, StringComparison.OrdinalIgnoreCase)
                || !Path.GetFileName(full).StartsWith("open-nanaimo-shop-pet-", StringComparison.Ordinal))
                throw new InvalidOperationException("Unexpected PET shop test directory");
            Directory.Delete(full, recursive: true);
        }
    }

    private static object CreateSession(CharacterRecord character, long accountId, string username)
    {
        var session = Activator.CreateInstance(SessionType, nonPublic: true)!;
        Set(session, "AccountId", accountId);
        Set(session, "Username", username);
        Set(session, "Character", character);
        Set(session, "ChannelId", 1);
        Set(session, "OnlineTracked", true);
        Set(session, "VillageShopCode", (byte)110);
        return session;
    }

    private static object CreatePresence(object session, CharacterRecord character, long accountId)
    {
        var sessionId = (string)Get(session, "SessionId")!;
        return PresenceType.GetConstructors().Single().Invoke([
            session, sessionId, accountId, character.Id, (string)Get(session, "Username")!,
            character.Name, "127.0.0.1", 1, DateTime.UtcNow, DateTime.UtcNow, (Action<string>)(_ => { })]);
    }

    private static CharacterRecord GoldenPet(long id, string name, uint petCode)
    {
        var character = new CharacterRecord
        {
            Id = id,
            AccountId = id,
            Name = name,
            Gender = 1,
            Appearance = new byte[36],
            EquippedPetItemCode = petCode,
            Items = [new CharacterItemRecord
            {
                ItemCode = petCode,
                Quantity = 1,
                PetCurrentStage = 3,
                PetMaximumStage = 3,
                PetLevel = 9,
                PetExperience = 77
            }]
        };
        BinaryPrimitives.WriteUInt32LittleEndian(character.Appearance.AsSpan(28, 4), petCode);
        return character;
    }

    private static IList Pending(object session) => (IList)Get(session, "PendingBroadcasts")!;
    private static byte[] Payload(object pending) => (byte[])Get(pending, "Payload")!;
    private static object? Get(object instance, string name)
        => instance.GetType().GetProperty(name)!.GetValue(instance);
    private static void Set(object instance, string name, object value)
        => instance.GetType().GetProperty(name)!.SetValue(instance, value);
    private static uint U32(byte[] payload, int offset)
        => BinaryPrimitives.ReadUInt32LittleEndian(payload.AsSpan(offset, 4));
    private static ushort U16(byte[] payload, int offset)
        => BinaryPrimitives.ReadUInt16LittleEndian(payload.AsSpan(offset, 2));
    private static void Check(bool valid, string name)
    {
        ++_checks;
        if (!valid)
            throw new InvalidDataException("VILLAGE_SHOP_PET_SCENE_CHECK_FAILED " + name);
        Console.WriteLine("VILLAGE_SHOP_PET_SCENE_CHECK_PASS " + name);
    }
}
