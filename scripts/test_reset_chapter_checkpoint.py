import sqlite3
from contextlib import closing
import tempfile
from pathlib import Path
import unittest

from reset_chapter_checkpoint import reset


class ResetCheckpointTests(unittest.TestCase):
    def test_scoped_reset_preserves_history_and_other_characters(self):
        with tempfile.TemporaryDirectory() as root:
            db = Path(root) / 'game.db'
            with closing(sqlite3.connect(db)) as c, c:
                c.executescript('''
                    CREATE TABLE Accounts(Id INTEGER,IsOnline INTEGER);
                    CREATE TABLE Characters(Id INTEGER,AccountId INTEGER,Name TEXT,IsOnline INTEGER,Hans INTEGER);
                    CREATE TABLE CharacterChapterStory(CharacterId INTEGER,QuestId INTEGER,ObjectiveIndex INTEGER,
                        ClearMask INTEGER,RewardPending INTEGER,Finished INTEGER,Revision INTEGER);
                    CREATE TABLE CharacterTasks(CharacterId INTEGER,QuestId INTEGER,TaskType INTEGER,RuntimeState INTEGER,
                        State3 INTEGER,Progress1 INTEGER,Progress2 INTEGER,Progress3 INTEGER,SlotType INTEGER,CreatedAt TEXT,UpdatedAt TEXT);
                    CREATE TABLE CharacterChapterClaims(CharacterId INTEGER,QuestId INTEGER);
                    CREATE TABLE CharacterMonkChallenges(CharacterId INTEGER,ClearMask INTEGER);
                    CREATE TABLE CharacterChapterMonkCompletions(CharacterId INTEGER,QuestId INTEGER);
                    INSERT INTO Accounts VALUES(4,0),(5,0);
                    INSERT INTO Characters VALUES(4,4,'Current',0,123),(5,5,'Other',0,456);
                    INSERT INTO CharacterChapterStory VALUES(4,73000004,0,0,0,0,63),(5,73000007,3,8,0,0,20);
                    INSERT INTO CharacterChapterClaims VALUES(4,73000003);
                    INSERT INTO CharacterMonkChallenges VALUES(4,15);
                    INSERT INTO CharacterChapterMonkCompletions VALUES(4,73000003),(5,73000007);
                ''')
            self.assertFalse(reset(db, 4, 4)['applied'])
            report = reset(db, 4, 4, True)
            with closing(sqlite3.connect(db)) as c, c, closing(sqlite3.connect(report['backup'])) as b:
                self.assertEqual(c.execute('SELECT * FROM CharacterChapterStory WHERE CharacterId=4').fetchone(),
                                 (4, 73000003, 1, 8, 0, 0, 64))
                for table in ('Characters', 'Accounts', 'CharacterChapterClaims', 'CharacterMonkChallenges'):
                    self.assertEqual(c.execute('SELECT * FROM ' + table).fetchall(), b.execute('SELECT * FROM ' + table).fetchall())
                self.assertEqual(c.execute('SELECT * FROM CharacterChapterStory WHERE CharacterId=5').fetchall(),
                                 b.execute('SELECT * FROM CharacterChapterStory WHERE CharacterId=5').fetchall())
                self.assertEqual(c.execute('SELECT * FROM CharacterChapterMonkCompletions').fetchall(), [(5, 73000007)])
                self.assertEqual(c.execute('SELECT State3,Progress1,Progress3 FROM CharacterTasks WHERE CharacterId=4').fetchone(), (2, 0, 1))
                c.execute('UPDATE Characters SET IsOnline=1 WHERE Id=4')
            with self.assertRaises(ValueError):
                reset(db, 4, 4, True)
            with self.assertRaises(ValueError):
                reset(db, 5, 16, True)


if __name__ == '__main__':
    unittest.main()
