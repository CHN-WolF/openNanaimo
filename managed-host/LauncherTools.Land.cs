using System.Globalization;
using System.Security.Cryptography;
using System.Text;
using OpenNanaimo.Adapter.Services;

internal static partial class LauncherTools
{
    // Derive only the selected fifth-village rows; never ship a client catalog.
    internal static byte[] PatchFifthVillageLand(byte[] encrypted)
    {
        Require(encrypted.Length is > 0 and <= 1048576 && encrypted.Length % 16 == 0,
            "Invalid MT._D18 encrypted length");
        using var aes = Aes.Create();
        aes.Key = Convert.FromHexString("0123456789ABCDEF123456789ABCDEF0");
        aes.IV = new byte[16];
        aes.Mode = CipherMode.CBC;
        aes.Padding = PaddingMode.PKCS7;
        using var decryptor = aes.CreateDecryptor();
        var raw = decryptor.TransformFinalBlock(encrypted, 0, encrypted.Length);
        Require(raw.All(b => b < 128), "Non-ASCII MT._D18 fields");
        var fields = Encoding.ASCII.GetString(raw).Split('#');
        int Number(string text)
        {
            Require(int.TryParse(text, NumberStyles.None, CultureInfo.InvariantCulture, out var value),
                "Invalid MT._D18 numeric field");
            return value;
        }
        Require(fields.Length >= 5 && fields[0] == "MINIROOMTRADE" && fields[1] == "20070312"
            && fields[^1] == "", "Unsupported MT._D18 header");
        var plotCount = Number(fields[2]);
        var priceCount = Number(fields[3]);
        Require(plotCount <= 10000 && priceCount <= 10000
            && fields.Length == 5 + 4 * (plotCount + priceCount), "MT._D18 row count mismatch");
        var plots = Enumerable.Range(0, plotCount).Select(i => fields[(4 + i * 4)..(8 + i * 4)]).ToList();
        var prices = Enumerable.Range(0, priceCount).Select(i => fields[(4 + plotCount * 4 + i * 4)..(8 + plotCount * 4 + i * 4)]).ToList();
        var plotKeys = new HashSet<(int Town, int Page, int Slot)>();
        var priceKeys = new HashSet<(int Town, int Page)>();
        foreach (var row in plots)
        {
            var v = row.Select(Number).ToArray();
            Require(v[0] <= 4 && v[1] <= 255 && v[2] < 20 && v[3] <= 3
                && plotKeys.Add((v[0], v[1], v[2])), "Invalid or duplicate MT._D18 plot");
        }
        foreach (var row in prices)
        {
            var v = row.Select(Number).ToArray();
            Require(v[0] <= 4 && v[1] <= 255 && priceKeys.Add((v[0], v[1])),
                "Invalid or duplicate MT._D18 price");
            if (v[0] < 4)
                Require(ApartmentLandPrices.TryGet((byte)v[0], (ushort)v[1], out var price)
                    && price.DailyHans == v[2] && price.RecommendationPoints == v[3],
                    "MT._D18 base price differs from server policy");
        }
        Require(priceKeys.Count(k => k.Town < 4) == 78, "Incomplete MT._D18 base price catalog");
        foreach (var page in ApartmentLandPrices.FifthVillagePages)
        {
            var plot = plots.SingleOrDefault(r => Number(r[0]) == 4 && Number(r[1]) == page && Number(r[2]) == 0);
            if (plot is null)
            {
                Require(page is 18 or 19, "Missing existing fifth-village plot");
                plots.Add(["4", page.ToString(CultureInfo.InvariantCulture), "0", "0"]);
            }
            else
            {
                Require(Number(plot[3]) is 0 or 3, "Unreviewed fifth-village plot flag");
                plot[3] = "0";
            }
            Require(ApartmentLandPrices.TryGet(4, page, out var price), "Fifth-village server price missing");
            var priceRow = prices.SingleOrDefault(r => Number(r[0]) == 4 && Number(r[1]) == page);
            if (priceRow is null)
            {
                priceRow = ["4", page.ToString(CultureInfo.InvariantCulture), "0", "0"];
                prices.Add(priceRow);
            }
            priceRow[2] = price.DailyHans.ToString(CultureInfo.InvariantCulture);
            priceRow[3] = price.RecommendationPoints.ToString(CultureInfo.InvariantCulture);
        }
        var result = new[] { fields[0], fields[1], plots.Count.ToString(CultureInfo.InvariantCulture),
            prices.Count.ToString(CultureInfo.InvariantCulture) }.Concat(plots.SelectMany(r => r)).Concat(prices.SelectMany(r => r));
        var plain = Encoding.ASCII.GetBytes(string.Join("#", result) + "#");
        using var encryptor = aes.CreateEncryptor();
        return encryptor.TransformFinalBlock(plain, 0, plain.Length);
    }
}
