from __future__ import annotations
from pathlib import Path
import fnmatch,hashlib
ROOT=Path(__file__).resolve().parents[1]
OUT=ROOT/'manifest/package_files.tsv'
ROOT_EXACT={'nanaimo_launcher_profile.ini','nanaimo_launcher_profile.json','adapter_ip.txt','accounts.dat','nanaimo_apartment_state_v1.dat','nanaimo_inventory_state_v1.dat'}
ROOT_PATTERNS=['adapter_*.log','*_stderr.log','*_state*.dat','*_state*.bak','*_state*.new','card_inventory_*.dat','card_guide_state_*.dat','card_key_*.dat','card_synthesis_rewards_*.dat','gui*_*.dat','adapter_*.dat','quickbar_state_*.dat','quickbar_state_*.handles','skill_progress_state_*.dat']
def generated(p):
 rel=p.relative_to(ROOT)
 if any(x in rel.parts for x in ('inventory_admin_backups', '__pycache__', '.git', 'build', 'dist', 'exports', '.private', 'github_openNanaimo')):return True
 if len(rel.parts)==1:
  n=rel.name
  if n in ROOT_EXACT or any(fnmatch.fnmatch(n,pat) for pat in ROOT_PATTERNS):return True
 return p.suffix.lower() in {'.pyc','.log','.pcap','.pcapng','.dmp','.etl','.evtx'}
def sha(p):
 h=hashlib.sha256()
 with p.open('rb') as f:
  for b in iter(lambda:f.read(1024*1024),b''):h.update(b)
 return h.hexdigest().upper()
rows=[]
for p in sorted(ROOT.rglob('*'),key=lambda x:str(x.relative_to(ROOT)).lower()):
 if not p.is_file() or p==OUT or generated(p):continue
 rel=p.relative_to(ROOT).as_posix();rows.append((rel,p.stat().st_size,sha(p)))
with OUT.open('w',encoding='utf-8',newline='\n') as f:
 f.write('path\tsize\tsha256\n')
 for rel,size,digest in rows:f.write(f'{rel}\t{size}\t{digest}\n')
print('PACKAGE_INDEX_WRITTEN',len(rows),sum(x[1] for x in rows),'generated_state_excluded=true')