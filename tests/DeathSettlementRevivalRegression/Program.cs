using OpenNanaimo.Adapter.Services;
using OpenNanaimo.Adapter.Models;

static void Check(bool condition, string message)
{
    if (!condition) throw new InvalidOperationException(message);
    Console.WriteLine("PASS " + message);
}

Check(NetworkAdapterService.ResolveNativeDungeonRevivalBilling(true, 0)
    == NetworkAdapterService.NativeDungeonRevivalBillingMode.Hans,
    "CF83 mode0 selects Hans billing");
Check(NetworkAdapterService.ResolveNativeDungeonRevivalBilling(true, 1)
    == NetworkAdapterService.NativeDungeonRevivalBillingMode.RevivalEgg,
    "CF83 mode1 selects revival-egg billing");
Check(NetworkAdapterService.ResolveNativeDungeonRevivalBilling(false, 0)
    == NetworkAdapterService.NativeDungeonRevivalBillingMode.None,
    "alive CF83 cannot debit Hans");
Check(NetworkAdapterService.ResolveNativeDungeonRevivalBilling(true, 2)
    == NetworkAdapterService.NativeDungeonRevivalBillingMode.None,
    "unknown CF83 mode cannot debit either ledger");
var reset = NativeDungeonClient.Frame(0xCF8B, [0, 0, 1, 0]);
Check(NetworkAdapterService.ShouldAuthorizeNativeDungeonNextAction(true, true, reset, 0xCF8B),
    "failed settlement authorizes an explicit retry");
Check(NetworkAdapterService.ShouldAuthorizeNativeDungeonNextAction(true, false, reset, 0xCF8B),
    "successful settlement can still authorize a selected continuation");
Check(!NetworkAdapterService.ShouldAuthorizeNativeDungeonNextAction(false, true, reset, 0xCF8B),
    "retry requires the active settlement action boundary");
var frozen = new BattleResourceSnapshot(0, 120, 2)
{
    MaximumHp = 2000, MaximumMp = 800, SettlementFrozen = true,
    HpAuthority = BattleHpAuthority.Settlement
};
var character = new CharacterRecord { MaxHp = 1200, MaxMp = 500 };
var retry = NetworkAdapterService.ResetNativeDungeonDeathRetryResources(frozen, character)!;
Check(retry.CurrentHp == 200 && retry.CurrentMp == 120 && retry.AttackMode == 0
    && !retry.SettlementFrozen && retry.HpAuthority == BattleHpAuthority.Inherited,
    "accepted retry uses base death-return HP and retained MP with effective maxima unchanged");
foreach (var maximumHp in new[] { 0, 1, 5, 6, 7, 1200, 65535 })
    foreach (ushort mp in new ushort[] { 0, 120, 500, 800 })
    {
        character.MaxHp = maximumHp;
        var returned = HealthRecoveryPolicy.ResolveDungeonDeathReturn(character, mp);
        var result = NetworkAdapterService.ResetNativeDungeonDeathRetryResources(frozen with { CurrentMp = mp }, character)!;
        Check(result.CurrentHp == Math.Min(frozen.MaximumHp, returned.CurrentHp)
            && result.CurrentMp == returned.CurrentMp && result.MaximumHp == frozen.MaximumHp
            && result.MaximumMp == frozen.MaximumMp,
            $"retry matches town-return policy at base HP {maximumHp} and remaining MP {mp}");
    }
Check(NetworkAdapterService.ResetNativeDungeonDeathRetryResources(null, character) is null,
    "retry does not synthesize a missing resource snapshot");
await DeathRetryChecks.RunAsync();
Console.WriteLine("DEATH_SETTLEMENT_REVIVAL_REGRESSION_PASS");
