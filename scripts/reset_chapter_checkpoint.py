"""Rewind one offline character to a chapter's defeated-super-boss checkpoint.

Preserves inventory, permanent challenge scores and reward receipts. The adapter
requires a fresh objective-bound monk win and never grants claimed rewards twice.
"""
from __future__ import annotations

import argparse
from contextlib import closing
from datetime import datetime, timezone
import json
from pathlib import Path
import sqlite3
import uuid


def reset(db: Path, character: int, episode: int, apply: bool = False) -> dict:
    if character <= 0 or not 1 <= episode <= 16:
        raise ValueError('Invalid character or episode')
    db = db.resolve(strict=True)
    with closing(sqlite3.connect(db, timeout=10)) as c, c:
        c.row_factory = sqlite3.Row

        def inspect():
            row = c.execute('''SELECT c.Id,c.AccountId,c.Name,c.IsOnline,a.IsOnline AS AccountOnline
                FROM Characters c JOIN Accounts a ON a.Id=c.AccountId WHERE c.Id=?''', (character,)).fetchone()
            if row is None or row['IsOnline'] or row['AccountOnline']:
                raise ValueError('Character must exist and both character/account must be offline')
            state = c.execute('SELECT * FROM CharacterChapterStory WHERE CharacterId=?', (character,)).fetchone()
            if state is None:
                raise ValueError('Character has no chapter story to rewind')
            if state['QuestId'] < 73000000 + episode - 1:
                raise ValueError('Refusing to advance a character beyond their current chapter')
            return dict(row), dict(state)

        owner, before = inspect()
        result = dict(character=owner, before=before, episode=episode, applied=False)
        if not apply:
            return result
        folder = db.parent / 'backups' / ('chapter-checkpoint-' + uuid.uuid4().hex)
        folder.mkdir(parents=True)
        backup = folder / 'game.db'
        with closing(sqlite3.connect(backup)) as destination:
            c.backup(destination)
        c.execute('BEGIN IMMEDIATE')
        if inspect() != (owner, before):
            raise ValueError('Progress changed while creating backup')
        quest = 73000000 + episode - 1
        now = datetime.now(timezone.utc).isoformat()
        c.execute('''UPDATE CharacterChapterStory SET QuestId=?,ObjectiveIndex=1,ClearMask=8,
            RewardPending=0,Finished=0,Revision=Revision+1 WHERE CharacterId=?''', (quest, character))
        c.execute('DELETE FROM CharacterTasks WHERE CharacterId=? AND SlotType=2', (character,))
        c.execute('''INSERT INTO CharacterTasks(CharacterId,QuestId,TaskType,RuntimeState,State3,
            Progress1,Progress2,Progress3,SlotType,CreatedAt,UpdatedAt)
            VALUES(?,?,2,0,2,0,1,1,2,?,?)''', (character, quest, now, now))
        if c.execute("SELECT 1 FROM sqlite_master WHERE name='CharacterChapterMonkCompletions'").fetchone():
            c.execute('DELETE FROM CharacterChapterMonkCompletions WHERE CharacterId=? AND QuestId>=?',
                      (character, quest))
        result.update(applied=True, backup=str(backup), after=dict(c.execute(
            'SELECT * FROM CharacterChapterStory WHERE CharacterId=?', (character,)).fetchone()))
        # Write the audit before commit, so an audit failure cannot leave an unrecorded reset.
        (folder / 'reset.json').write_text(json.dumps(result, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
        c.commit()
        return result


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--db', type=Path, required=True)
    p.add_argument('--character-id', type=int, required=True)
    p.add_argument('--episode', type=int, required=True)
    p.add_argument('--apply', action='store_true')
    a = p.parse_args()
    print(json.dumps(reset(a.db, a.character_id, a.episode, a.apply), ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
