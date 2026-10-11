"""Production offline tooling checks on isolated SQLite and GUI fixtures."""
from contextlib import contextmanager
import copy
import json
import os
from pathlib import Path
import sqlite3
import struct
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
EXE = Path(os.environ.get('NANAIMO_TOOLS_EXE', ROOT / 'adapter_runtime/Nanaimo.Adapter.exe'))

@contextmanager
def connection(path):
    c=sqlite3.connect(path)
    try:
        with c:yield c
    finally:c.close()

class IncrementalSaveTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.catalog = {kind: json.loads((ROOT / f'gui_launcher/data/inventory_{file}.json').read_text('utf-8-sig')) for kind, file in [('clothing','clothing'),('pets','pets'),('game','game_items'),('furniture','furniture'),('cards','cards')]}

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='nanaimo-incremental-')
        self.root = Path(self.temp.name); (self.root/'adapter_data').mkdir()
        self.db = self.root/'adapter_data/game.db'
        with connection(self.db) as c:
            c.executescript('''
            CREATE TABLE Accounts(Id INTEGER PRIMARY KEY, Username TEXT, IsOnline INTEGER NOT NULL);
            CREATE TABLE Characters(Id INTEGER PRIMARY KEY,AccountId INTEGER,Name TEXT,Gender INTEGER,IsOnline INTEGER,Level INTEGER,Experience INTEGER,CurveVersion INTEGER,MaxHp INTEGER,MaxMp INTEGER,CurrentHp INTEGER,CurrentMp INTEGER,AttackModifier INTEGER,DefenseFlat INTEGER,ApartmentRecommendationPoints INTEGER,Hans INTEGER,Cash INTEGER,SelectedSkill0 INTEGER,SelectedSkill1 INTEGER,SkillSlotExpansionExpires INTEGER,Appearance BLOB,EquippedPetItemCode INTEGER,PetLevel INTEGER,PetExperience INTEGER,LastSavedAt TEXT);
            CREATE TABLE CharacterItems(CharacterId INTEGER,ItemCode INTEGER,Quantity INTEGER,PetCurrentStage INTEGER DEFAULT 0,PetAccessory0 INTEGER DEFAULT 0,PetAccessory1 INTEGER DEFAULT 0,PetAccessory2 INTEGER DEFAULT 0,PetLevel INTEGER DEFAULT 0,PetExperience INTEGER DEFAULT 0,UpdatedAt TEXT,PRIMARY KEY(CharacterId,ItemCode));
            CREATE TABLE CharacterSkills(CharacterId INTEGER,SkillCode INTEGER,Grade INTEGER,UpdatedAt TEXT,PRIMARY KEY(CharacterId,SkillCode));
            CREATE TABLE CharacterApartmentItems(CharacterId INTEGER,SlotIndex INTEGER,ItemCode INTEGER,PositionX INTEGER,PositionY INTEGER,Layer INTEGER,Mirror INTEGER,InteriorType INTEGER,UpdatedAt TEXT,PRIMARY KEY(CharacterId,SlotIndex));
            CREATE TABLE CharacterCards(CharacterId INTEGER,CardCode INTEGER,Quantity INTEGER,UpdatedAt TEXT,PRIMARY KEY(CharacterId,CardCode));
            CREATE TABLE NativeDungeonProfiles(CharacterId INTEGER PRIMARY KEY,State BLOB NOT NULL);
            CREATE TABLE NativeState(Scope TEXT COLLATE NOCASE,Name TEXT,Content BLOB,UpdatedAt TEXT,PRIMARY KEY(Scope,Name));
            CREATE TABLE NativeStateImports(Scope TEXT COLLATE NOCASE,Name TEXT,Content BLOB,ImportedAt TEXT,PRIMARY KEY(Scope,Name));
            CREATE TABLE Audit(Domain TEXT,Operation TEXT);
            INSERT INTO Accounts VALUES(1,'P1',0);
            INSERT INTO Characters VALUES(1,1,'P1',1,0,1,0,3,1500,100,1234,77,0,0,0,0,0,0,0,0,zeroblob(36),0,0,0,'ORIGINAL');
            ''')
            appearance=bytearray(36);struct.pack_into('<I',appearance,32,1);c.execute('UPDATE Characters SET Appearance=?',(bytes(appearance),))
            data=bytearray(5704)
            for offset,value in [(0,4),(8,1),(5124,4),(5128,5704),(5132,3),(5024,2)]:struct.pack_into('<I',data,offset,value)
            c.execute('INSERT INTO NativeDungeonProfiles VALUES(1,?)',(bytes(data),))
            for table,domain in [('Characters','profile'),('CharacterItems','items'),('CharacterSkills','skills'),('CharacterCards','cards'),('CharacterApartmentItems','furniture'),('NativeDungeonProfiles','title')]:
                for operation in ['INSERT','UPDATE','DELETE']:
                    c.execute(f"CREATE TRIGGER audit_{table}_{operation} AFTER {operation} ON {table} BEGIN INSERT INTO Audit VALUES('{domain}','{operation}'); END")
        self.snap=self.run_tool('snapshot')
        self.clear_audit()

    def tearDown(self): self.temp.cleanup()
    def run_tool(self, command, state=None, title=None, id=1, hex='5031', expect=True):
        args=[str(EXE),'--tools','inventory',command,'--root',str(self.root),'--catalog-root',str(ROOT),'--name-hex',hex]
        if id is not None:args+=['--character-id',str(id)]
        if state is not None:
            path=self.root/'input.json';path.write_text(json.dumps(state),encoding='utf-8');args+=['--input',str(path)]
        if title is not None:args+=['--title-grade',str(title)]
        p=subprocess.run(args,capture_output=True,text=True,encoding='utf-8',errors='replace',timeout=30)
        if expect:self.assertEqual(p.returncode,0,p.stdout+p.stderr);return json.loads(p.stdout)
        self.assertNotEqual(p.returncode,0);return p.stderr
    def backups(self):return list((self.root/'inventory_admin_backups').glob('*/game.db'))
    def audit(self):
        with connection(self.db) as c:return c.execute('SELECT * FROM Audit').fetchall()
    def clear_audit(self):
        with connection(self.db) as c:c.execute('DELETE FROM Audit')
    def game_row(self, count=2):
        meta=self.catalog['game'][0];return dict(code=meta['id'],count=count,carrier='deliberately-wrong-input-label')

    def test_noop_ignores_property_order_and_legacy_shop_lists(self):
        s=copy.deepcopy(self.snap);s['shop']={k:v for k,v in reversed(list(s['shop'].items())) if k not in ['clothing','pets','gift_pets','cash_items']}
        r=self.run_tool('apply',s);self.assertFalse(r['changed']);self.assertIsNone(r['backup']);self.assertEqual(self.backups(),[]);self.assertEqual(self.audit(),[])
    def test_hp_only_does_not_write_inventory_or_skills(self):
        s=copy.deepcopy(self.snap);s['profile']['hp_max']=1600;r=self.run_tool('apply',s)
        self.assertEqual(r['domains'],['profile']);self.assertEqual(self.audit(),[('profile','UPDATE')]);self.assertEqual(len(self.backups()),1)
        self.clear_audit();r=self.run_tool('apply',s);self.assertFalse(r['changed']);self.assertEqual(len(self.backups()),1);self.assertEqual(self.audit(),[])
    def test_item_only_repeat_does_not_backup_or_reset_resources(self):
        s=copy.deepcopy(self.snap);s['game_items']=[self.game_row()];r=self.run_tool('apply',s);self.assertEqual(r['domains'],['game_items']);self.assertEqual(self.audit(),[('items','INSERT')]);self.assertEqual(len(self.backups()),1)
        self.clear_audit();r=self.run_tool('apply',s);self.assertFalse(r['changed']);self.assertEqual(self.audit(),[]);self.assertEqual(len(self.backups()),1)
        with connection(self.db) as c:self.assertEqual(c.execute('SELECT CurrentHp,CurrentMp,LastSavedAt FROM Characters').fetchone(),(1234,77,'ORIGINAL'))
    def test_changed_item_does_not_touch_other_item_metadata(self):
        s=copy.deepcopy(self.snap);s['game_items']=[self.game_row(),dict(code=self.catalog['game'][1]['id'],count=3,carrier='stackable')];self.run_tool('apply',s)
        with connection(self.db) as c:c.execute("UPDATE CharacterItems SET UpdatedAt='KEEP' WHERE ItemCode=?",(s['game_items'][1]['code'],))
        self.clear_audit();s['game_items'][0]['count']=4;self.run_tool('apply',s);self.assertEqual(self.audit(),[('items','UPDATE')])
        with connection(self.db) as c:self.assertEqual(c.execute('SELECT UpdatedAt FROM CharacterItems WHERE ItemCode=?',(s['game_items'][1]['code'],)).fetchone()[0],'KEEP')
    def test_cards_preserve_unknown_and_touch_only_changed_row(self):
        codes=[x['id'] for x in self.catalog['cards'][:2]]
        with connection(self.db) as c:c.executemany('INSERT INTO CharacterCards VALUES(1,?,3,?)',[(codes[0],'A'),(codes[1],'B'),(99999999,'UNKNOWN')])
        s=self.run_tool('snapshot');s['cards']=[x for x in s['cards'] if x['code']!=99999999];s['cards'][0]['count']=4;self.clear_audit();self.run_tool('apply',s);self.assertEqual(self.audit(),[('cards','UPDATE')])
        with connection(self.db) as c:self.assertEqual(c.execute('SELECT Quantity,UpdatedAt FROM CharacterCards WHERE CardCode=99999999').fetchone(),(3,'UNKNOWN'));self.assertEqual(c.execute('SELECT UpdatedAt FROM CharacterCards WHERE CardCode=?',(codes[1],)).fetchone()[0],'B')
    def test_card_rejection_creates_no_backup(self):
        s=copy.deepcopy(self.snap);s['cards']=[dict(code=99999999,count=2)];self.run_tool('apply',s,expect=False);self.assertEqual(self.backups(),[]);self.assertEqual(self.audit(),[])
    def test_placement_edit_does_not_rebuild_all_rows(self):
        meta=self.catalog['furniture'][0];s=copy.deepcopy(self.snap);s['furniture']=[dict(code=meta['id'],index=i,placed=True,type=meta['type'],x=100*i,y=20,z=0,mirror=0) for i in [1,2]];self.run_tool('apply',s)
        with connection(self.db) as c:c.execute("UPDATE CharacterApartmentItems SET UpdatedAt='KEEP' WHERE SlotIndex=1")
        self.clear_audit();s['furniture'][0]['x']=123;self.run_tool('apply',s);self.assertEqual(self.audit(),[('furniture','DELETE'),('furniture','INSERT')])
        with connection(self.db) as c:self.assertEqual(c.execute('SELECT UpdatedAt FROM CharacterApartmentItems WHERE SlotIndex=1').fetchone()[0],'KEEP')
    def test_equipment_keeps_nonselector_bytes_and_owns_selected_item(self):
        s=copy.deepcopy(self.snap);s['shop']['equipped'][0]=self.catalog['clothing'][0]['id']
        with connection(self.db) as c:
            a=bytearray(c.execute('SELECT Appearance FROM Characters').fetchone()[0]);a[16:20]=b'KEEP';c.execute('UPDATE Characters SET Appearance=?',(bytes(a),))
        self.clear_audit();r=self.run_tool('apply',s);self.assertEqual(r['domains'],['clothing','shop'])
        with connection(self.db) as c:
            a=c.execute('SELECT Appearance FROM Characters').fetchone()[0];self.assertEqual(a[16:20],b'KEEP');self.assertEqual(struct.unpack_from('<I',a)[0],s['shop']['equipped'][0])
        self.clear_audit();self.assertFalse(self.run_tool('apply',s)['changed']);self.assertEqual(self.audit(),[])
    def test_pet_stage_and_progress_survive_unrelated_edits(self):
        meta=self.catalog['pets'][0];s=copy.deepcopy(self.snap);s['pets']=[dict(code=meta['id'],upgrade_material=0,gems=[0,0,0])];s['shop']['selected_pet']=meta['id'];self.run_tool('apply',s)
        with connection(self.db) as c:c.execute("UPDATE CharacterItems SET PetLevel=4,PetExperience=123,UpdatedAt='PET_KEEP' WHERE ItemCode=?",(meta['id'],))
        self.clear_audit();s['profile']['hp_max']=1888;self.run_tool('apply',s);self.assertEqual(self.audit(),[('profile','UPDATE')])
        with connection(self.db) as c:self.assertEqual(c.execute('SELECT PetLevel,PetExperience,UpdatedAt FROM CharacterItems WHERE ItemCode=?',(meta['id'],)).fetchone(),(4,123,'PET_KEEP'))
    def test_skills_only_write_changed_grade(self):
        s=copy.deepcopy(self.snap);s['profile']['skill_grade0']=1;self.run_tool('apply',s);self.clear_audit();s['profile']['skill_grade0']=2;r=self.run_tool('apply',s);self.assertEqual(r['domains'],['skills']);self.assertEqual(self.audit(),[('skills','UPDATE')]);self.clear_audit();self.assertFalse(self.run_tool('apply',s)['changed']);self.assertEqual(self.audit(),[])
    def test_character_identity_conflict_is_rejected(self):
        self.run_tool('apply',self.snap,hex='5032',expect=False);self.assertEqual(self.backups(),[])
    def test_profile_plus_title_one_backup_and_repeat_noop(self):
        s=copy.deepcopy(self.snap);s['profile']['hp_max']=1700;r=self.run_tool('apply',s,title=5);self.assertEqual(r['domains'],['profile','title']);self.assertEqual(len(self.backups()),1)
        with connection(self.backups()[0]) as c:self.assertEqual(c.execute('SELECT MaxHp FROM Characters').fetchone()[0],1500);self.assertEqual(struct.unpack_from('<I',c.execute('SELECT State FROM NativeDungeonProfiles').fetchone()[0],5024)[0],2)
        with connection(self.db) as c:
            data=c.execute('SELECT State FROM NativeDungeonProfiles').fetchone()[0];self.assertEqual(struct.unpack_from('<I',data,5024)[0],5)
            receipt=c.execute("SELECT Content FROM NativeState WHERE Name='dungeon_grade_state_v1_5031.dat'").fetchone()[0];self.assertIn(b'\ngrade=5\n',receipt)
        self.clear_audit();r=self.run_tool('apply',s,title=5);self.assertFalse(r['changed']);self.assertEqual(len(self.backups()),1);self.assertEqual(self.audit(),[])
    def test_gui_save_uses_combined_title_request_no_second_backup(self):
        import shutil
        shutil.copytree(ROOT/'gui_launcher/data',self.root/'gui_launcher/data',ignore=shutil.ignore_patterns('previews','__pycache__'))
        s=copy.deepcopy(self.snap);s['profile']['hp_max']=1919;(self.root/'gui-input.json').write_text(json.dumps(s),encoding='utf-8')
        ps=self.root/'gui-save.ps1';ps.write_text(r"""
$ErrorActionPreference='Stop'
. (Join-Path $env:REPO_ROOT 'gui_launcher/inventory_admin_gui.ps1')
. (Join-Path $env:REPO_ROOT 'gui_launcher/launcher_worker.ps1')
function Get-LocalAdapters{return @()}
function Write-DungeonGradeState{throw 'SECOND_TITLE_TOOL_CALL'}
$state=Get-Content (Join-Path $env:FIXTURE_ROOT 'gui-input.json') -Raw|ConvertFrom-Json
$context=[pscustomobject]@{Backend=$env:TOOLS_EXE;Root=$env:FIXTURE_ROOT;NameHex='5031';CharacterId=1;Shop=$state.shop;Profile=$state.profile;Clothing=$state.clothing;Pets=$state.pets;GameItems=$state.game_items;Furniture=$state.furniture;Cards=$state.cards}
$ProfileStateRoot=Join-Path $env:FIXTURE_ROOT 'profile state with spaces';[void][IO.Directory]::CreateDirectory($ProfileStateRoot)
$ProfileIni=Join-Path $env:FIXTURE_ROOT 'profile.ini';$ProfileJson=Join-Path $env:FIXTURE_ROOT 'profile.json';$LauncherProgress=@{}
$request=@{Context=$context;Hex='5031';Shop=$state.shop;TitleGrade=8;Lines=@('version=2','dungeon_grade=8');View=@{title=@{state_file=$null};inventory_admin=@{backup=$null;account_suffix=$null}}}
try{$result=Write-LauncherProfileRequest $request;if(-not$result.changed){throw 'GUI did not save'};if(-not(Test-Path $ProfileIni)-or-not(Test-Path $ProfileJson)){throw 'config output missing'}}finally{Stop-InventoryBackendSessions}
'GUI_COMBINED_SAVE_PASS'
""",encoding='utf-8-sig')
        p=subprocess.run(['powershell.exe','-NoProfile','-ExecutionPolicy','Bypass','-File',str(ps)],cwd=ROOT,env={**os.environ,'REPO_ROOT':str(ROOT),'TOOLS_EXE':str(EXE),'FIXTURE_ROOT':str(self.root)},capture_output=True,text=True,encoding='utf-8',errors='replace',timeout=90)
        self.assertEqual(p.returncode,0,p.stdout+p.stderr);self.assertIn('GUI_COMBINED_SAVE_PASS',p.stdout);self.assertEqual(len(self.backups()),1)
        with connection(self.db) as c:self.assertEqual(c.execute('SELECT MaxHp FROM Characters').fetchone()[0],1919);self.assertEqual(struct.unpack_from('<I',c.execute('SELECT State FROM NativeDungeonProfiles').fetchone()[0],5024)[0],8)
    def test_title_failure_rolls_back_profile_and_card(self):
        with connection(self.db) as c:c.execute("CREATE TRIGGER reject_title BEFORE UPDATE ON NativeDungeonProfiles BEGIN SELECT RAISE(ABORT,'INJECTED_TITLE_FAILURE'); END")
        s=copy.deepcopy(self.snap);s['profile']['hp_max']=1777;s['cards']=[dict(code=self.catalog['cards'][0]['id'],count=2)]
        error=self.run_tool('apply',s,title=7,expect=False);self.assertIn('INJECTED_TITLE_FAILURE',error);self.assertEqual(len(self.backups()),1);self.assertEqual(self.audit(),[])
        with connection(self.db) as c:self.assertEqual(c.execute('SELECT MaxHp FROM Characters').fetchone()[0],1500);self.assertEqual(c.execute('SELECT COUNT(*) FROM CharacterCards').fetchone()[0],0)
    def test_online_rejected_before_backup(self):
        with connection(self.db) as c:c.execute('UPDATE Accounts SET IsOnline=1')
        s=copy.deepcopy(self.snap);s['profile']['hp_max']=1666;self.clear_audit();self.run_tool('apply',s,expect=False);self.assertEqual(self.backups(),[]);self.assertEqual(self.audit(),[])
    def test_invalid_grade_rejected_before_backup(self):
        self.run_tool('apply',self.snap,title=43,expect=False);self.assertEqual(self.backups(),[])
    def test_draft_plus_title_same_backup_and_noop(self):
        s=dict(version=2,profile=dict(hp_max=1500,mp_max=100),shop=dict(coin=0,nana=0,equipped=[0]*5,effect=0,selected_pet=0),clothing=[],pets=[],game_items=[],furniture=[],cards=[])
        r=self.run_tool('apply',s,id=None,hex='5032',title=6);self.assertEqual(r['domains'],['draft','title']);self.assertEqual(len(self.backups()),1)
        r=self.run_tool('apply',s,id=None,hex='5032',title=6);self.assertFalse(r['changed']);self.assertEqual(len(self.backups()),1)

class ResidentCatalogTests(unittest.TestCase):
    def test_helper_exits_when_owning_powershell_exits(self):
        with tempfile.TemporaryDirectory(prefix='nanaimo owner exit ') as temp:
            work=Path(temp);ps=work/'owner.ps1'
            ps.write_text("$ErrorActionPreference='Stop'\n. (Join-Path $env:REPO_ROOT 'gui_launcher/inventory_admin_gui.ps1')\n[void](Invoke-InventoryAdminBackend @($env:TOOLS_EXE,'profiles','--root',$env:FIXTURE_ROOT))\n@($script:InventoryBackendSessions.Values)[0].Process.Id\n",encoding='utf-8-sig')
            env={**os.environ,'REPO_ROOT':str(ROOT),'TOOLS_EXE':str(EXE),'FIXTURE_ROOT':str(work)}
            p=subprocess.run(['powershell.exe','-NoProfile','-ExecutionPolicy','Bypass','-File',str(ps)],cwd=ROOT,env=env,capture_output=True,text=True,errors='replace',timeout=45)
            self.assertEqual(p.returncode,0,p.stdout+p.stderr);pid=int(p.stdout.strip())
            wait=work/'wait.ps1';wait.write_text(f"Wait-Process -Id {pid} -Timeout 8 -ErrorAction SilentlyContinue; if(Get-Process -Id {pid} -ErrorAction SilentlyContinue){{throw 'ownerless helper survived'}}",encoding='utf-8-sig')
            p=subprocess.run(['powershell.exe','-NoProfile','-File',str(wait)],capture_output=True,text=True,errors='replace',timeout=15);self.assertEqual(p.returncode,0,p.stdout+p.stderr)
    def test_gui_pipe_reuse_lazy_loading_invalidation_and_cleanup(self):
        import shutil
        with tempfile.TemporaryDirectory(prefix='nanaimo pipe root with spaces ') as temp:
            work=Path(temp);data=work/'gui_launcher/data';data.mkdir(parents=True)
            for name in ['clothing','pets','pet_gems','game_items','furniture','cards']:
                shutil.copy2(ROOT/f'gui_launcher/data/inventory_{name}.json',data)
            ps=work/'check.ps1'
            ps.write_text(r"""
$ErrorActionPreference='Stop'
. (Join-Path $env:REPO_ROOT 'gui_launcher/inventory_admin_gui.ps1')
$backend=$env:TOOLS_EXE;$root=$env:FIXTURE_ROOT
try{
    [void](Invoke-InventoryAdminBackend @($backend,'profiles','--root',$root,'--name-hex','5032'))
    $session=@($script:InventoryBackendSessions.Values)[0];$pid1=$session.Process.Id
    if($session.CatalogLoads-ne0){throw 'profiles loaded catalogs'}
    [void](Invoke-InventoryAdminBackend @($backend,'snapshot','--root',$root,'--name-hex','5032'))
    if($session.CatalogLoads-ne1){throw 'first snapshot did not load once'}
    $space=[Management.Automation.Runspaces.RunspaceFactory]::CreateRunspace();$space.Open()
    $space.SessionStateProxy.SetVariable('Sessions',$script:InventoryBackendSessions)
    $space.SessionStateProxy.SetVariable('Owner',$script:InventoryBackendOwnerPid)
    $power=[PowerShell]::Create();$power.Runspace=$space
    [void]$power.AddScript('param($module,$backend,$root) . $module; $script:InventoryBackendSessions=$Sessions;$script:InventoryBackendOwnerPid=$Owner;Invoke-InventoryAdminBackend @($backend,"snapshot","--root",$root,"--name-hex","5032")').AddArgument((Join-Path $env:REPO_ROOT 'gui_launcher/inventory_admin_gui.ps1')).AddArgument($backend).AddArgument($root)
    [void]$power.Invoke();if($power.HadErrors){throw ($power.Streams.Error|Out-String)};$power.Dispose();$space.Dispose()
    if($session.Process.Id-ne$pid1-or$session.CatalogLoads-ne1){throw 'runspace failed to reuse catalog process'}
    $path=Join-Path $root 'gui_launcher/data/inventory_cards.json';$original=[IO.File]::ReadAllBytes($path)
    [IO.File]::WriteAllText($path,'{invalid JSON')
    try{[void](Invoke-InventoryAdminBackend @($backend,'snapshot','--root',$root,'--name-hex','5032'));throw 'bad catalog reused'}catch{if($_.Exception.Message-eq'bad catalog reused'){throw}}
    [IO.File]::WriteAllBytes($path,$original);(Get-Item $path).LastWriteTimeUtc=[DateTime]::UtcNow.AddSeconds(5)
    [void](Invoke-InventoryAdminBackend @($backend,'snapshot','--root',$root,'--name-hex','5032'))
    if($session.CatalogLoads-ne2){throw 'modified catalog failed to reload'}
    # A helper must not be detected as a running game protocol service.
    $t=$null;$e=$null;$ast=[Management.Automation.Language.Parser]::ParseFile((Join-Path $env:REPO_ROOT 'gui_launcher/nanaimo_launcher.ps1'),[ref]$t,[ref]$e)
    $f=$ast.Find({param($n)$n-is[Management.Automation.Language.FunctionDefinitionAst]-and$n.Name-eq'Get-LocalAdapters'},$true)
    . ([scriptblock]::Create($f.Extent.Text));$Adapter=$backend;$AdapterBridge='missing';$LegacyAdapter='missing'
    if(@(Get-LocalAdapters|Where-Object Id -eq $pid1).Count){throw 'tools helper mistaken for game service'}
    Stop-InventoryBackendSessions
    if(-not$session.Process.HasExited){throw 'owned tools process survived cleanup'}
    'RESIDENT_CATALOG_PASS profiles_loads=0 snapshots_loads=1 runspace_reuse=true invalidation=true helper_not_service=true cleanup=true'
}finally{Stop-InventoryBackendSessions}
""",encoding='utf-8-sig')
            p=subprocess.run(['powershell.exe','-NoProfile','-ExecutionPolicy','Bypass','-File',str(ps)],cwd=ROOT,env={**os.environ,'REPO_ROOT':str(ROOT),'TOOLS_EXE':str(EXE),'FIXTURE_ROOT':str(work)},capture_output=True,text=True,encoding='utf-8',errors='replace',timeout=90)
            self.assertEqual(p.returncode,0,p.stdout+p.stderr);self.assertIn('RESIDENT_CATALOG_PASS',p.stdout)

if __name__=='__main__':unittest.main()
