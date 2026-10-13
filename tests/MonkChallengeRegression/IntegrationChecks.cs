using System.Buffers.Binary;
using OpenNanaimo.Adapter.Services;

internal static class IntegrationChecks
{
    internal static void Run()
    {
        static void Require(bool value, string name)
        {
            if (!value) throw new InvalidOperationException(name);
        }
        var selection = new byte[52];
        BinaryPrimitives.WriteUInt16LittleEndian(selection.AsSpan(4), 52);
        BinaryPrimitives.WriteUInt16LittleEndian(selection.AsSpan(6), 0xCF6C);
        selection[35] = MonkChallengePolicy.FirstEpisode;
        for (ushort difficulty = 0; difficulty < 3; difficulty++)
        {
            BinaryPrimitives.WriteUInt16LittleEndian(selection.AsSpan(38), difficulty);
            Require(NetworkAdapterService.TryParseNativeDungeonSelectionFrame(selection,
                out var hd, out var ep, out var dg, out var st, out var logical), "prototype selection");
            Require(NetworkAdapterService.IsMonkPrototypeSelectionAllowed(hd, ep, dg, st, logical, 0), "solo selection");
            Require(!NetworkAdapterService.IsMonkPrototypeSelectionAllowed(hd, ep, dg, st, logical, 1), "party selection");
        }
        foreach (var field in new[] { 34, 36, 37 })
        {
            selection[field] = 1;
            Require(!NetworkAdapterService.TryParseNativeDungeonSelectionFrame(selection,
                out _, out _, out _, out _, out _), "prototype field bounds");
            selection[field] = 0;
        }
        for (byte episode = 25; episode <= 27; episode++)
        {
            selection[35] = episode;
            Require(NetworkAdapterService.TryParseNativeDungeonSelectionFrame(selection,
                out var hd25, out var ep25, out var dg25, out var st25, out var logical25), "four-challenge selection parse");
            Require(MonkChallengePolicy.IsReservedEpisode(ep25) && MonkChallengePolicy.TryGetChallengeIndex(hd25, ep25, dg25, st25, out var index25) && index25 == episode - 24,
                "four-challenge index");
            Require(NetworkAdapterService.IsMonkPrototypeSelectionAllowed(hd25, ep25, dg25, st25, logical25, 0), "four-challenge solo selection");
        }
        var request = new byte[12];
        BinaryPrimitives.WriteUInt16LittleEndian(request.AsSpan(4), 12);
        BinaryPrimitives.WriteUInt16LittleEndian(request.AsSpan(6), 0xCF8B);
        BinaryPrimitives.WriteUInt16LittleEndian(request.AsSpan(10), 1);
        var response = new byte[48];
        BinaryPrimitives.WriteUInt16LittleEndian(response.AsSpan(4), 48);
        BinaryPrimitives.WriteUInt16LittleEndian(response.AsSpan(6), 0xCF8C);
        for (byte difficulty = 0; difficulty < 3; difficulty++)
        {
            Require(NetworkAdapterService.TryResolveNativeDungeonTransition(0, 0, difficulty,
                request, response, out var dg, out var st, out var nextDifficulty, 0, 24)
                && dg == 0 && st == 0 && nextDifficulty == difficulty, "same challenge retry");
        }
        BinaryPrimitives.WriteUInt16LittleEndian(request.AsSpan(10), 2);
        Require(!NetworkAdapterService.TryResolveNativeDungeonTransition(0, 0, 0,
            request, response, out _, out _, out _, 0, 24), "challenge next-stage bound");
        BinaryPrimitives.WriteUInt16LittleEndian(request.AsSpan(10), 1);
        response[40] = 1;
        Require(!NetworkAdapterService.TryResolveNativeDungeonTransition(0, 0, 0,
            request, response, out _, out _, out _, 0, 24), "challenge response stage bound");
        Require(!DungeonTitleProgression.TryGetGrade(0, 24, 0, 0, out _), "challenge title isolation");
        var pages = new byte[] { 27, 26, 12, 6 };
        foreach (var opcode in new ushort[] { 0xCF6C, 0xCF77 })
        {
            var entry = new byte[opcode == 0xCF6C ? 52 : 16];
            BinaryPrimitives.WriteUInt16LittleEndian(entry.AsSpan(4), (ushort)entry.Length);
            BinaryPrimitives.WriteUInt16LittleEndian(entry.AsSpan(6), opcode);
            if (opcode == 0xCF77) BinaryPrimitives.WriteUInt16LittleEndian(entry.AsSpan(8), 100);
            var offset = opcode == 0xCF6C ? 34 : 10;
            for (byte village = 0; village < 4; village++)
            {
                entry[offset + 1] = (byte)(24 + village);
                Require(NetworkAdapterService.TryParseMonkVillageSelection(entry, 0, village, pages[village],
                    out _, out var episode, out _, out _) && episode == 24 + village, "village dialogue entry");
                Require(!NetworkAdapterService.TryParseMonkVillageSelection(entry, 0, 4, pages[village],
                    out _, out _, out _, out _), "village origin ownership");
                Require(!NetworkAdapterService.TryParseMonkVillageSelection(entry, 0, village, 0,
                    out _, out _, out _, out _), "village exit page ownership");
                Require(!NetworkAdapterService.TryParseMonkVillageSelection(entry, 1, village, pages[village],
                    out _, out _, out _, out _), "village solo ownership");
            }
        }
        Console.WriteLine("MONK_INTEGRATION_CHECKS_PASS");
    }
}
