"""Managed installer checks with synthetic resources; no original client is launched."""
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import tempfile
import unittest

from Crypto.Cipher import AES
from Crypto.Util.Padding import pad, unpad
from test_prepare_client_compatibility import synthetic_pe

ROOT = Path(__file__).resolve().parents[1]
ADAPTER = Path(os.environ.get('NANAIMO_LAND_ADAPTER', ROOT / 'adapter_runtime/Nanaimo.Adapter.exe'))
KEY = bytes.fromhex('0123456789abcdef123456789abcdef0')
PAGES = (6, 7, 8, 11, 16, 17, 18, 19)


def encrypt(text):
    return AES.new(KEY, AES.MODE_CBC, bytes(16)).encrypt(pad(text.encode('ascii'), 16))


def decode(data):
    return unpad(AES.new(KEY, AES.MODE_CBC, bytes(16)).decrypt(data), 16).decode('ascii')


def fixture():
    # The server's unchanged baseline supplies the installer fixture, not the price oracle.
    text = (ROOT / 'managed/Services/ApartmentLandPrices.cs').read_text('utf8')
    prices = [tuple(map(int, row)) for row in re.findall(
        r'\[\((\d+), (\d+)\)\] = new\((\d+), (\d+)\)', text) if int(row[0]) < 4]
    assert len(prices) == 78
    plots = [(0, 2, 0, 2)] + [(4, page, 0, 3) for page in PAGES[:6]]
    return encrypt('#'.join(map(str, ['MINIROOMTRADE', '20070312', len(plots), len(prices)]
                               + [n for row in plots + prices for n in row])) + '#')


@unittest.skipUnless(ADAPTER.is_file(), 'Build a matching adapter and set NANAIMO_LAND_ADAPTER')
class FifthVillageInstallerTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='nanaimo-land-install-')
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.source = self.root / 'source'
        self.output = self.root / 'overlay'
        self.source.mkdir()
        self.exe = synthetic_pe()[0]
        self.catalog = fixture()
        (self.source / 'game.exe').write_bytes(self.exe)
        (self.source / 'MT._D18').write_bytes(self.catalog)

    def invoke(self, *args, success=True):
        proc = subprocess.run([str(ADAPTER), '--tools', 'compatibility', '--source-root', str(self.source),
            '--output-root', str(self.output), '--land-purchase', *args], capture_output=True, text=True)
        if success:
            self.assertEqual(proc.returncode, 0, proc.stdout + proc.stderr)
            return json.loads(proc.stdout)
        self.assertNotEqual(proc.returncode, 0)
        return proc

    def test_dry_run_overlay_apply_backup_and_idempotence(self):
        dry = self.invoke('--dry-run', '--apply')
        self.assertIn('MT._D18', dry['session_inputs'])
        self.assertFalse(self.output.exists())
        self.assertEqual((self.source / 'MT._D18').read_bytes(), self.catalog)
        report = self.invoke()
        self.assertTrue(report['verification']['all_pass'])
        updated = (self.output / 'MT._D18').read_bytes()
        self.assertEqual((self.source / 'game.exe').read_bytes(), self.exe)
        self.assertEqual((self.source / 'MT._D18').read_bytes(), self.catalog)
        plain = decode(updated)
        self.assertTrue(plain.startswith('MINIROOMTRADE#20070312#9#86#0#2#0#2#'))
        for page in PAGES:
            self.assertIn(f'#4#{page}#0#0#', plain)
            self.assertIn(f'#4#{page}#2000#600#', plain)
        self.invoke('--apply', '--overwrite')
        self.assertEqual((self.source / 'MT._D18').read_bytes(), updated)
        backup = self.output / 'backups' / hashlib.sha256(self.catalog).hexdigest().upper() / 'MT._D18'
        self.assertEqual(backup.read_bytes(), self.catalog)
        again = self.invoke('--apply', '--overwrite')
        self.assertTrue(all(r['status'] == 'unchanged' for r in again['apply_results']))
        operation = next(r for r in again['operations'] if r['operation'] == 'fifth_village_land')
        self.assertFalse(operation['changed'])
        self.assertFalse(operation['runtime_acceptance'])

    def test_bad_catalog_refuses_before_any_file_write(self):
        (self.source / 'MT._D18').write_bytes(b'bad')
        self.invoke('--apply', success=False)
        self.assertEqual((self.source / 'game.exe').read_bytes(), self.exe)
        self.assertEqual((self.source / 'MT._D18').read_bytes(), b'bad')
        self.assertFalse(self.output.exists())

    def test_missing_catalog_refuses_before_any_file_write(self):
        (self.source / 'MT._D18').unlink()
        self.invoke('--apply', success=False)
        self.assertFalse(self.output.exists())
        self.assertEqual((self.source / 'game.exe').read_bytes(), self.exe)

    def test_unapproved_overlay_does_not_modify_source(self):
        self.output.mkdir()
        (self.output / 'MT._D18').write_bytes(b'private-overlay')
        self.invoke('--apply', success=False)
        self.assertEqual((self.source / 'MT._D18').read_bytes(), self.catalog)
        self.assertEqual((self.source / 'game.exe').read_bytes(), self.exe)
        self.assertEqual((self.output / 'MT._D18').read_bytes(), b'private-overlay')


if __name__ == '__main__':
    unittest.main()
