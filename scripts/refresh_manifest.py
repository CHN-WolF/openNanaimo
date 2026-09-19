"""Refresh the explicit current local-runtime contract after reviewed changes.

This does not approve redistribution, install a patch, or certify runtime play.
"""
from pathlib import Path
import hashlib
import json

ROOT = Path(__file__).resolve().parents[1]
BASE_FILES = [
    'start_nanaimo_launcher.bat', 'game.exe',
    'scripts/verify_client_baseline.py',
    'adapter/nanaimo_adapter.exe', 'adapter/nanaimo_adapter_testports.exe',
    'Village_map_image/Village_map_image.pack',
    'flying/hd0_ep22_dg00_st01.sstg', 'flying/hd0_ep22_dg01_st01.sstg',
    'gui_launcher/nanaimo_launcher.ps1', 'gui_launcher/client_connect.ps1',
    'gui_launcher/inventory_admin_gui.ps1', 'gui_launcher/inventory_admin_backend.py',
    'gui_launcher/launch_modes/gamestartoption.network.ini',
]


def sha(path):
    h = hashlib.sha256()
    with path.open('rb') as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b''):
            h.update(block)
    return h.hexdigest().upper()


def main():
    rels = set(BASE_FILES)
    for patch in (ROOT / 'gui_launcher/resource_patches').glob('*.json'):
        rels.add(patch.relative_to(ROOT).as_posix())
        rels.update(x['relative_path'] for x in json.loads(patch.read_text('utf-8-sig'))['assets'])
    critical = {}
    for rel in sorted(rels):
        p = ROOT / rel
        if not p.resolve().is_relative_to(ROOT) or not p.is_file():
            raise ValueError('invalid runtime dependency: ' + rel)
        critical[rel] = {'size': p.stat().st_size, 'sha256': sha(p)}
    closure = json.loads((ROOT / 'manifest/source_closure.json').read_text('utf-8-sig'))
    m = {
        'channel': 'release',
        'description': 'Korean flight-shooting game nanaimo launcher and local protocol adapter',
        'runtime_acceptance': False,
        'validation_scope': 'Local file contract and deterministic rebuild; not clean official-install or gameplay acceptance',
        'critical_files': critical,
        'source_closure_count': closure['count'],
        'public_export_policy': {
            'mode': 'explicit-reviewed-allowlist-only',
            'exclude_private_profiles_states_logs_backups': True,
            'exclude_official_installers_and_full_client_assets': True,
            'working_tree_is_public_package': False,
            'manifest': 'manifest/patch_allowlist.json',
        },
    }
    (ROOT / 'manifest/open_release_manifest.json').write_text(json.dumps(m, ensure_ascii=False, indent=2) + '\n', 'utf-8')
    print('MANIFEST_WRITTEN', len(critical), 'runtime_acceptance=false')


if __name__ == '__main__':
    main()
