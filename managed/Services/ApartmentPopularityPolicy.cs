namespace OpenNanaimo.Adapter.Services;

/// <summary>
/// Converts the persisted apartment visit index into one five-second recovery step.
/// Every occupant of a room receives the same rate so owner and visitor views stay consistent.
/// </summary>
internal static class ApartmentPopularityPolicy
{
    internal const uint LandCardCode = 60_000_000;

    internal static HealthRecoveryParameters GetRecoveryParameters(long totalVisitIndex)
    {
        // Clamp before multiplication so even corrupt totals fit the thermometer WORDs.
        var visits = Math.Clamp(totalVisitIndex, 0L, ushort.MaxValue);
        return new HealthRecoveryParameters(
            (int)Math.Clamp(visits * 5, 70L, ushort.MaxValue),
            (int)Math.Max(20L, visits));
    }
}
