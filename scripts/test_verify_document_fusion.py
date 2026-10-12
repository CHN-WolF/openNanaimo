"""Temporary-fixture tests for information-preserving document fusion."""

import gzip
import hashlib
import json
from pathlib import Path
import tempfile
import unittest

from verify_document_fusion import digest, verify


class DocumentFusionTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.root = Path(self.directory.name)
        (self.root / 'manifest').mkdir()
        (self.root / 'knowledge/业务/住宅').mkdir(parents=True)
        (self.root / 'knowledge/指南').mkdir()
        self.source = 'docs/住宅.md'
        self.target = 'knowledge/业务/住宅/规则.md'
        self.original = '# 住宅\n\n## 当前规则\n\n住宅期限14天；费用4200金币。\n'
        self.body = self.original
        self.fragment = {
            'id': 'df-01-001', 'source': self.source,
            'start': 0, 'end': len(self.original),
            'source_sha256': digest(self.original),
            'target': self.target, 'content_sha256': digest(self.body),
        }
        self.data = {
            'schema_version': 1,
            'baseline_archive': 'manifest/document_fusion_baseline.json.gz',
            'source_count': 1, 'fragment_count': 1,
            'source_files': {}, 'fragments': [self.fragment],
            'path_mapping': {self.source: self.target},
        }
        self.write_baseline()
        self.write_target()
        self.write_manifest()

    def write_baseline(self):
        archive = gzip.compress(json.dumps({self.source: self.original}, ensure_ascii=False).encode('utf-8'), mtime=0)
        (self.root / self.data['baseline_archive']).write_bytes(archive)
        self.data['baseline_archive_sha256'] = hashlib.sha256(archive).hexdigest()
        self.data['source_files'][self.source] = {'chars': len(self.original), 'sha256': digest(self.original)}
        self.fragment['end'] = len(self.original)
        self.fragment['source_sha256'] = digest(self.original)

    def block(self):
        return '<a id="df-01-001"></a>\n\n<!-- FUSION BEGIN df-01-001 -->\n' + self.body + '<!-- FUSION END df-01-001 -->\n'

    def write_target(self):
        path = self.root / self.target
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(self.block(), encoding='utf-8')

    def write_manifest(self):
        (self.root / 'manifest/document_fusion.json').write_text(json.dumps(self.data, ensure_ascii=False), encoding='utf-8')

    def test_full_chinese_source_passes(self):
        report = verify(self.root, strict=True)
        self.assertTrue(report.ok, report.errors)
        self.assertEqual(report.chars, len(self.original))

    def test_local_link_relocation_is_allowed_and_checked(self):
        self.original += '\n[操作步骤](../knowledge/指南/安装.md#安装)\n'
        self.body = self.original.replace('(../knowledge/指南/安装.md#安装)', '(../../指南/安装.md#安装)')
        self.write_baseline()
        self.fragment['content_sha256'] = digest(self.body)
        (self.root / 'knowledge/指南/安装.md').write_text('# 操作指南\n\n## 安装\n', encoding='utf-8')
        self.write_target()
        self.write_manifest()
        self.assertTrue(verify(self.root, strict=True).ok)
        (self.root / 'knowledge/指南/安装.md').write_text('# 缺少锚点\n', encoding='utf-8')
        self.assertFalse(verify(self.root, strict=True).ok)

    def test_rehashing_a_changed_number_cannot_hide_information_loss(self):
        self.body = self.original.replace('14天', '7天')
        self.fragment['content_sha256'] = digest(self.body)
        self.write_target()
        self.write_manifest()
        report = verify(self.root, strict=True)
        self.assertFalse(report.ok)
        self.assertIn('original information changed', '\n'.join(report.errors))

    def test_remote_reference_must_be_preserved(self):
        self.original += '\n[证据](https://example.com/original)\n'
        self.body = self.original.replace('/original)', '/different)')
        self.write_baseline()
        self.fragment['content_sha256'] = digest(self.body)
        self.write_target()
        self.write_manifest()
        self.assertFalse(verify(self.root, strict=True).ok)

    def test_duplicate_live_fragment_is_rejected(self):
        (self.root / 'knowledge/指南/重复.md').write_text(self.block(), encoding='utf-8')
        self.assertFalse(verify(self.root, strict=True).ok)

    def test_unmatched_marker_is_rejected(self):
        (self.root / self.target).write_text(self.block().replace('FUSION END df-01-001', 'FUSION END df-01-002'), encoding='utf-8')
        self.assertFalse(verify(self.root, strict=True).ok)

    def test_character_gap_is_rejected_even_with_valid_fragment_hash(self):
        self.fragment['start'] = 1
        self.body = self.original[1:]
        self.fragment['source_sha256'] = digest(self.body)
        self.fragment['content_sha256'] = digest(self.body)
        self.write_target()
        self.write_manifest()
        self.assertFalse(verify(self.root, strict=True).ok)

    def test_corrupt_baseline_is_rejected(self):
        (self.root / self.data['baseline_archive']).write_bytes(b'corrupt gzip')
        self.assertFalse(verify(self.root, strict=True).ok)

    def test_default_reports_later_edits_but_strict_rejects_them(self):
        self.body += '\n后续维护的规则补充。\n'
        self.write_target()
        report = verify(self.root)
        self.assertTrue(report.ok, report.errors)
        self.assertEqual(report.edits, ['df-01-001'])
        self.assertFalse(verify(self.root, strict=True).ok)

    def test_live_old_directory_is_rejected(self):
        (self.root / 'docs').mkdir()
        (self.root / self.source).write_text(self.original, encoding='utf-8')
        self.assertFalse(verify(self.root, strict=True).ok)

    def test_declared_target_must_stay_under_knowledge(self):
        self.fragment['target'] = '../escape.md'
        self.write_manifest()
        self.assertFalse(verify(self.root, strict=True).ok)

    def rewrite_body(self, original, body):
        self.original += original
        self.body = self.original.replace(original, body)
        self.write_baseline()
        self.fragment['content_sha256'] = digest(self.body)
        self.write_target()
        self.write_manifest()

    def test_rehashing_link_looking_code_cannot_hide_example_changes(self):
        for original in ('\n```python\n[value](123)\n```\n',
                         '\n~~~text\n[value](123)\n~~~\n',
                         '\n`[value](123)`\n', '\n``[value](123)``\n'):
            with self.subTest(example=original):
                self.rewrite_body(original, original.replace('123', '999'))
                report = verify(self.root, strict=True)
                self.assertFalse(report.ok, report.errors)
                self.assertIn('original information changed', '\n'.join(report.errors))

    def test_local_resource_relocation_preserves_target_identity(self):
        self.rewrite_body('\n[资源](../resource-packs/a.zip)\n',
                          '\n[资源](../../../resource-packs/a.zip)\n')
        self.assertTrue(verify(self.root, strict=True).ok)
        self.body = self.body.replace('a.zip', 'b.zip')
        self.fragment['content_sha256'] = digest(self.body)
        self.write_target()
        self.write_manifest()
        self.assertFalse(verify(self.root, strict=True).ok)

    def test_declared_heading_route_allows_cross_topic_relocation(self):
        self.data['heading_routes'] = [{'from': self.target + '#当前规则',
                                       'to': 'knowledge/指南/安装.md#新位置'}]
        (self.root / 'knowledge/指南/安装.md').write_text('# 新位置\n', encoding='utf-8')
        self.rewrite_body('\n[规则](#当前规则)\n',
                          '\n[规则](../../指南/安装.md#新位置)\n')
        report = verify(self.root, strict=True)
        self.assertTrue(report.ok, report.errors)

    def test_rehashing_a_link_to_another_existing_page_is_rejected(self):
        for name in ('正确', '错误'):
            (self.root / ('knowledge/指南/' + name + '.md')).write_text('# 相同标题\n', encoding='utf-8')
        self.rewrite_body('\n[证据](../knowledge/指南/正确.md#相同标题)\n',
                          '\n[证据](../../指南/错误.md#相同标题)\n')
        report = verify(self.root, strict=True)
        self.assertFalse(report.ok)
        self.assertIn('original information changed', '\n'.join(report.errors))

    def test_link_query_change_is_rejected(self):
        (self.root / 'knowledge/指南/安装.md').write_text('# 安装\n', encoding='utf-8')
        self.rewrite_body('\n[步骤](../knowledge/指南/安装.md?v=1#安装)\n',
                          '\n[步骤](../../指南/安装.md?v=2#安装)\n')
        self.assertFalse(verify(self.root, strict=True).ok)

    def test_undeclared_live_fragment_is_rejected(self):
        path = self.root / self.target
        path.write_text(path.read_text('utf-8') + self.block().replace('df-01-001', 'df-01-002'), encoding='utf-8')
        self.assertFalse(verify(self.root, strict=True).ok)

    def test_duplicate_declared_fragment_is_rejected(self):
        self.data['fragments'].append(dict(self.fragment))
        self.data['fragment_count'] = 2
        self.write_manifest()
        self.assertFalse(verify(self.root, strict=True).ok)

    def test_overlapping_intervals_are_rejected(self):
        extra = dict(self.fragment, id='df-01-002')
        self.data['fragments'].append(extra)
        self.data['fragment_count'] = 2
        path = self.root / self.target
        path.write_text(self.block() + self.block().replace('df-01-001', 'df-01-002'), encoding='utf-8')
        self.write_manifest()
        report = verify(self.root, strict=True)
        self.assertFalse(report.ok)
        self.assertIn('gap/overlap', '\n'.join(report.errors))

    def test_out_of_bounds_interval_is_rejected(self):
        self.fragment['end'] += 1
        self.write_manifest()
        self.assertFalse(verify(self.root, strict=True).ok)

    def test_malformed_records_fail_without_crashing(self):
        for field, value in [('fragments', [42]), ('fragments', {}),
                             ('source_files', []), ('path_mapping', [])]:
            with self.subTest(field=field, value=value):
                original = self.data[field]
                self.data[field] = value
                self.write_manifest()
                self.assertFalse(verify(self.root, strict=True).ok)
                self.data[field] = original

    def test_corrupt_compressed_stream_with_updated_hash_is_rejected(self):
        # Valid gzip header followed by an invalid DEFLATE block.
        archive = bytes.fromhex('1f8b0800000000000203') + b'\x07' + b'\x00' * 8
        (self.root / self.data['baseline_archive']).write_bytes(archive)
        self.data['baseline_archive_sha256'] = hashlib.sha256(archive).hexdigest()
        self.write_manifest()
        self.assertFalse(verify(self.root, strict=True).ok)


if __name__ == '__main__':
    unittest.main()
