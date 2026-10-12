"""Launcher resource receipt regression, not NPC/gameplay acceptance.

An independent scene marker must not authorize a modified L7/L8-owned pack.
Exercise the real managed verifier in an isolated directory; no client writes.
"""
from pathlib import Path
import hashlib
import json
import subprocess
import tempfile
import unittest

import port_lumineos_resources as io

ROOT = Path(__file__).resolve().parents[1]
TOOL = ROOT / 'adapter_runtime/Nanaimo.Adapter.exe'
PACK = 'Village_map_image/Village_map_image.pack'
BASELINE = b'isolated-baseline-village-record'


@unittest.skipUnless(TOOL.is_file(), 'self-contained managed tools are a separate build input')
class MonkLauncherResourceTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='monk-launcher-contract-')
        self.addCleanup(self.temp.cleanup)
        self.client = Path(self.temp.name)
        self.pack = self.client / PACK
        self.pack.parent.mkdir()
        self.pack.write_bytes(BASELINE)
        receipt = dict(schema='openNanaimo.l7-visual-l8-resources.v1',
                       runtime_accepted=False, files=[dict(path=PACK, size=len(BASELINE),
                       sha256=io.digest(BASELINE))], preserve_l7_combat=[])
        receipt['id'] = io.digest(io.encoded(receipt))
        self.receipt = receipt
        (self.client / 'openNanaimo-l7-l8-resources.json').write_bytes(io.encoded(receipt))

    def verify(self):
        return subprocess.run([str(TOOL), '--tools', 'verify-resources', '--kind', 'lumineos',
                               '--root', str(ROOT), '--client-root', str(self.client)],
                              stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                              timeout=30, encoding='utf8', errors='replace')

    def test_registered_baseline_passes(self):
        result = self.verify()
        self.assertEqual(result.returncode, 0, result.stdout)
        self.assertIn('LUMINEOS_RESOURCES_PASS', result.stdout)

    def test_unregistered_scene_overlay_is_rejected(self):
        self.pack.write_bytes(BASELINE + b'-unregistered-monk-decoration')
        result = self.verify()
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('Installed resource mismatch: ' + PACK, result.stdout)

    def test_preview_marker_cannot_override_other_installer_receipt(self):
        self.pack.write_bytes(BASELINE + b'-unregistered-monk-decoration')
        (self.client / '.openNanaimo-monk-entry-preview.json').write_bytes(
            io.encoded(dict(status='scene-preview-unbound', runtime_accepted=False, interactive=False)))
        result = self.verify()
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('Installed resource mismatch: ' + PACK, result.stdout)

    def test_restore_exact_baseline_recovers_verifier(self):
        self.pack.write_bytes(BASELINE + b'-unregistered-monk-decoration')
        self.assertNotEqual(self.verify().returncode, 0)
        self.pack.write_bytes(BASELINE)
        result = self.verify()
        self.assertEqual(result.returncode, 0, result.stdout)
        self.assertIn('LUMINEOS_RESOURCES_PASS', result.stdout)

    def test_receipt_hash_tampering_is_not_a_repair(self):
        tampered = dict(self.receipt, id='0' * 64)
        (self.client / 'openNanaimo-l7-l8-resources.json').write_bytes(io.encoded(tampered))
        result = self.verify()
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('receipt digest mismatch', result.stdout)


if __name__ == '__main__':
    unittest.main(verbosity=2)
