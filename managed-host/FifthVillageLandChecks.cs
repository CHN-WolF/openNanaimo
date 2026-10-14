using System.Globalization;
using System.Security.Cryptography;
using System.Text;
using OpenNanaimo.Adapter.Services;

internal static class FifthVillageLandChecks
{
    internal static byte[] Crypt(byte[] data, bool encrypt)
    {
        using var aes = Aes.Create();
        aes.Key = Convert.FromHexString("0123456789ABCDEF123456789ABCDEF0");
        aes.IV = new byte[16];
        using var transform = encrypt ? aes.CreateEncryptor() : aes.CreateDecryptor();
        return transform.TransformFinalBlock(data, 0, data.Length);
    }

    internal static void Run()
    {
        int checks = 0;
        void Check(bool value, string label)
        {
            if (!value) throw new InvalidDataException("Fifth village: " + label);
            checks++;
        }
        byte[] Encrypt(string text) => Crypt(Encoding.ASCII.GetBytes(text), true);
        string Decode(byte[] data) => Encoding.ASCII.GetString(Crypt(data, false));
        var prices = new List<string>();
        long maxHans = 0, maxPoints = 0;
        for (byte town = 0; town < 4; town++)
            for (ushort page = 0; page < 256; page++)
                if (ApartmentLandPrices.TryGet(town, page, out var price))
                {
                    prices.Add(FormattableString.Invariant($"{town}#{page}#{price.DailyHans}#{price.RecommendationPoints}"));
                    maxHans = Math.Max(maxHans, price.DailyHans);
                    maxPoints = Math.Max(maxPoints, price.RecommendationPoints);
                }
        Check(prices.Count == 78 && maxHans == 1000 && maxPoints == 300, "original price baseline");
        foreach (var page in ApartmentLandPrices.FifthVillagePages)
            Check(ApartmentLandPrices.TryGet(4, page, out var price) && price.DailyHans == maxHans * 2
                && price.RecommendationPoints == maxPoints * 2 && price.PurchaseHans == 28000
                && ApartmentHousingPolicy.IsHouseSlot(4, page, 0) && !ApartmentHousingPolicy.IsHouseSlot(4, page, 1),
                "price and single slot " + page);
        var plots = new List<string> { "0#2#0#2", "0#2#1#0" };
        plots.AddRange(new[] { 6, 7, 8, 11, 16, 17 }.Select(p => $"4#{p}#0#3"));
        string Pack(List<string> p, List<string> r) => $"MINIROOMTRADE#20070312#{p.Count}#{r.Count}#"
            + string.Join("#", p.Concat(r)) + "#";
        var source = Pack(plots, prices);
        var input = Encrypt(source);
        var output = LauncherTools.PatchFifthVillageLand(input);
        var decoded = Decode(output);
        Check(decoded.StartsWith("MINIROOMTRADE#20070312#10#86#0#2#0#2#0#2#1#0#"), "counts and unrelated plots preserved");
        Check(decoded.Contains(string.Join("#", prices) + "#"), "all original prices preserved in order");
        Check(Decode(input) == source, "input unchanged");
        Check(output.SequenceEqual(LauncherTools.PatchFifthVillageLand(output)), "byte idempotence");
        foreach (var page in ApartmentLandPrices.FifthVillagePages)
            Check(decoded.Contains($"#4#{page}#0#0#") && decoded.Contains($"#4#{page}#2000#600#"), "derived page " + page);
        var reference = decoded.Replace("#2000#600#", "#300#30#");
        Check(output.SequenceEqual(LauncherTools.PatchFifthVillageLand(Encrypt(reference))), "reference-style expanded catalog normalized");
        var previousCulture = CultureInfo.CurrentCulture;
        try
        {
            CultureInfo.CurrentCulture = CultureInfo.GetCultureInfo("ar-SA");
            Check(output.SequenceEqual(LauncherTools.PatchFifthVillageLand(input)), "locale independent output");
        }
        finally { CultureInfo.CurrentCulture = previousCulture; }
        void Refuses(byte[] bytes)
        {
            try { LauncherTools.PatchFifthVillageLand(bytes); }
            catch (Exception ex) when (ex is InvalidDataException or CryptographicException) { checks++; return; }
            throw new InvalidDataException("Malformed land catalog accepted");
        }
        Refuses([]);
        Refuses(input[..^1]);
        Refuses(Encrypt(source.Replace("20070312", "20070313")));
        Refuses(Encrypt(source.Replace("#8#78#", "#9#78#")));
        Refuses(Encrypt(source.Replace("#4#6#0#3#", "#4#6#0#2#")));
        Refuses(Encrypt(source.Replace("#1000#300#", "#999#300#")));
        Refuses(Encrypt(source[..^1]));
        Refuses(Encrypt(Pack(plots.Append(plots[0]).ToList(), prices)));
        Refuses(Encrypt(Pack(plots, prices.Append(prices[0]).ToList())));
        Refuses(Encrypt(Pack(plots.Where(p => p != "4#6#0#3").ToList(), prices)));
        Refuses(Encrypt(Pack(plots, prices.Skip(1).ToList())));
        Console.WriteLine($"FIFTH_VILLAGE_LAND_CHECKS_PASS checks={checks}");
    }
}
