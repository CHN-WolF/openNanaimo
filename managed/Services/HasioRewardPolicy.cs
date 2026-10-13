using System.Text.Json;

namespace OpenNanaimo.Adapter.Services;

internal sealed record HasioReward(int Hans, IReadOnlyList<HasioRewardEntry> Items,
    IReadOnlyList<HasioRewardEntry> Cards);
internal readonly record struct HasioRewardEntry(uint Code, int Quantity);

internal static class HasioRewardPolicy
{
    internal const string FileName = "hasio-reward.json";

    // The retail QS/GQ resources prove the exchange, not its contents. These
    // amounts are explicit private-server policy, not an original-server recipe.
    internal static HasioReward Default => new(10_000,
        [new(14_002_486u, 10)], [new(12_000_002u, 5)]);

    internal static bool TryLoad(string directory, out HasioReward reward)
    {
        reward = Default;
        var path = Path.Combine(directory, FileName);
        try
        {
            byte[] bytes;
            try
            {
                using var stream = File.OpenRead(path);
                if (stream.Length > 65_536) return false;
                using var buffer = new MemoryStream();
                stream.CopyTo(buffer);
                bytes = buffer.ToArray();
                if (bytes.Length > 65_536) return false;
            }
            catch (FileNotFoundException) { return Validate(reward); }
            using var document = JsonDocument.Parse(bytes);
            var root = document.RootElement;
            Fields(root, "Version", "Hans", "Items", "Cards");
            if (root.GetProperty("Version").GetInt32() != 1) return false;
            reward = new(root.GetProperty("Hans").GetInt32(),
                Entries(root.GetProperty("Items")), Entries(root.GetProperty("Cards")));
            return Validate(reward);
        }
        catch (Exception ex) when (ex is IOException or UnauthorizedAccessException
            or JsonException or InvalidOperationException or FormatException
            or OverflowException or InvalidDataException)
        {
            return false;
        }
    }

    private static HasioRewardEntry[] Entries(JsonElement array)
    {
        if (array.ValueKind != JsonValueKind.Array || array.GetArrayLength() > 32)
            throw new InvalidDataException("Invalid Hasio reward list.");
        return array.EnumerateArray().Select(entry =>
        {
            Fields(entry, "Code", "Quantity");
            return new HasioRewardEntry(entry.GetProperty("Code").GetUInt32(),
                entry.GetProperty("Quantity").GetInt32());
        }).ToArray();
    }

    private static bool Validate(HasioReward reward)
        => reward.Hans is >= 0 and <= 1_000_000_000
            && (reward.Hans != 0 || reward.Items.Count != 0 || reward.Cards.Count != 0)
            && reward.Items.Select(entry => entry.Code).Distinct().Count() == reward.Items.Count
            && reward.Cards.Select(entry => entry.Code).Distinct().Count() == reward.Cards.Count
            && reward.Items.All(entry => entry.Quantity is >= 1 and <= 84
                && ShopCatalog.TryGet(entry.Code, out var item)
                && item.IsGameInventoryItem && item.QuickUsable && !item.HasExpiry
                && !CardCatalog.TryGet(entry.Code, out _))
            && reward.Items.Sum(entry => (long)entry.Quantity) <= 84
            && reward.Cards.All(entry => entry.Quantity is >= 1 and <= 255
                && CardCatalog.IsSkillPointCard(entry.Code) && CardCatalog.TryGet(entry.Code, out _));

    private static void Fields(JsonElement value, params string[] expected)
    {
        if (value.ValueKind != JsonValueKind.Object)
            throw new InvalidDataException("Expected Hasio configuration object.");
        var names = value.EnumerateObject().Select(field => field.Name).OrderBy(name => name).ToArray();
        if (!names.SequenceEqual(expected.OrderBy(name => name)))
            throw new InvalidDataException("Missing, duplicate or unknown Hasio configuration field.");
    }
}
