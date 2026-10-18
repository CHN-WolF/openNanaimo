import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import deploy_adapter_runtime as deploy


class ChapterReviewPreflightTests(unittest.TestCase):
    def test_missing_review_and_matching_review(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            deploy.chapter_review_preflight(root, 'abc')
            (root / 'adapter_data').mkdir()
            path = root / 'adapter_data/chapter_reward_review.json'
            data = dict(schema='openNanaimo.chapter-reward-review.v1', package_sha256='ABC')
            path.write_text(json.dumps(data), encoding='utf-8')
            before = path.read_bytes()
            deploy.chapter_review_preflight(root, 'abc')
            self.assertEqual(path.read_bytes(), before)

    def test_mismatch_schema_and_missing_hash_rejected_without_mutation(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            (root / 'adapter_data').mkdir()
            path = root / 'adapter_data/chapter_reward_review.json'
            for data in ({'schema': 'old', 'package_sha256': 'abc'},
                         {'schema': 'openNanaimo.chapter-reward-review.v1', 'package_sha256': 'old'},
                         {'schema': 'openNanaimo.chapter-reward-review.v1'}):
                path.write_text(json.dumps(data), encoding='utf-8')
                before = path.read_bytes()
                with self.assertRaisesRegex(ValueError, 'before deploying'):
                    deploy.chapter_review_preflight(root, 'abc')
                self.assertEqual(path.read_bytes(), before)

    def test_apply_rejects_before_payload_write_or_backup(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            (root / 'adapter_data').mkdir()
            (root / 'adapter_data/chapter_reward_review.json').write_text(
                '{"schema":"openNanaimo.chapter-reward-review.v1","package_sha256":"old"}', encoding='utf-8')
            with patch.object(deploy, 'verify_root', return_value=({}, {})), \
                 patch.object(deploy.io, 'file_hash', return_value='new'), \
                 patch.object(deploy.io, 'atomic') as write:
                with self.assertRaisesRegex(ValueError, 'No target files'):
                    deploy.deploy(root, apply=True)
                write.assert_not_called()
            self.assertFalse((root / 'deployment_backups').exists())


if __name__ == '__main__':
    unittest.main()
