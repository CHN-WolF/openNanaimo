from pathlib import Path
import re
root=Path(__file__).resolve().parents[1]
protocol=(root/'managed/Services/ArenaProtocol.cs').read_text(encoding='utf-8')
service=(root/'managed/Services/NetworkAdapterService.cs').read_text(encoding='utf-8')
combat=(root/'managed/Services/NetworkAdapterService.ArenaCombat.cs').read_text(encoding='utf-8-sig')
checks=[
 ('complete D010 length', 'public const int GameEventResponseLength = 36;' in protocol),
 ('bounded player damage policy', 'CalculatePvpDamage' in protocol),
 ('initialized D010 tail', 'payload.AsSpan(28).Clear();' in protocol),
 ('target HP ledger', 'room.CurrentHpBySession[victim.SessionId] = hp;' in combat),
 ('elimination winner ledger', 'room.EliminationWinnerSessionId = attacker.SessionId;' in combat),
 ('scene contact does not invent score', 'Scene contacts do not award stars' in service),
 ('attacker identity fallback', 'ResolveArenaPvpAttackerLocked' in combat),
 ('timed-round respawn', 'IsTimedScoreArena(room)' in combat and 'GetArenaMaximumHp(victim)' in combat),
 ('terminal notification one-shot', 'if (room.PvpResultPayload.Length != 0)' in service and 'if (!room.EndingSessionIds.Add(requester.SessionId)) return false;' in service),
 ('obstacle terminal damage suppressed', '20 or 30 => 0' in protocol),
 ('round reset clears winner', 'room.EliminationWinnerSessionId = null;' in service),
]
for name,ok in checks:
    if not ok: raise SystemExit('ARENA_STATIC_REGRESSION_FAIL '+name)
    print('ARENA_STATIC_REGRESSION_PASS '+name)
print('ARENA_STATIC_REGRESSION_PASS all')
