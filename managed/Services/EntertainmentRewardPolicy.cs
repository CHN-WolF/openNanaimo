using System.Security.Cryptography;

namespace OpenNanaimo.Adapter.Services;

internal static class EntertainmentRewardPolicy
{
    // Adapter policy: D005 operation 10 advances the combo counter.
    public const uint SelectionScore = 100;
    public const uint TargetScore = 1500;
    public const int LuckyThreshold = 1000;
    private static readonly Lazy<uint[]> BasicCards = new(() => CardCatalog.All
        .Where(card => IsBasicCard(card.CardCode))
        .Select(card => card.CardCode).OrderBy(code => code).ToArray());

    internal static IReadOnlyList<uint> Pool => BasicCards.Value;

    internal static bool IsBasicCard(uint code) => code is >= 13000001 and <= 13000420
        && !CardCatalog.IsGoldPowder(code);

    internal static uint GetPetRewardPercent(int place) => place switch
    {
        0 => 20,
        1 => 15,
        2 => 10,
        >= 3 and < EntertainmentProtocol.MaximumMembers => 5,
        _ => 0
    };

    internal static uint GetPetExperience(PetState state, int place)
    {
        state = PetProgression.NormalizeState(state);
        if (!ShopCatalog.TryGet(15, state.ItemCode, out var pet)
            || !ShopCatalog.TryGetPetGrowthStage(pet.PetGrowthClass, state.CurrentStage, out var growth))
            return 0;
        return checked((uint)((ulong)growth.ExperiencePerLevel * GetPetRewardPercent(place) / 100));
    }

    internal static uint PickBasicCard()
        => BasicCards.Value[RandomNumberGenerator.GetInt32(BasicCards.Value.Length)];
}
