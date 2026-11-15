"""Offline final-archive admission checks; all data and code signatures are fixtures."""
from copy import deepcopy
import json
import unittest
from unittest.mock import patch

import test_runtime_update as fixtures


PROOF_FIELDS = (
    'verify_only', 'verification_process_fresh', 'verification_runtime_sha256',
    'native_exit_code', 'library_jit_attempts', 'archive_misses', 'archive_writes',
    'verified_rows', 'archive_files_opened', 'libraries_manifest_sha256',
    'compiler_context_sha256', 'compiler_context_schema',
    'archive_snapshot_before_sha256', 'archive_snapshot_after_sha256',
)


class ArchiveAdmissionTests(unittest.TestCase):
    def setUp(self):
        # Keep the shared TestCase behind its module; discovery must not run a
        # duplicate copy of its entire suite through this test module.
        self.fixture = fixtures.RuntimeUpdateTests(methodName='runTest')
        self.fixture.setUp()
        self.addCleanup(self.fixture.doCleanups)
        self.runtime = fixtures.runtime
        self.app, self.receipt, self.info = self.fixture.app()
        self.report_path = self.app / 'Contents/Resources/totk/build/pipelines/compute-manifest.json'
        self.report = self.runtime.read_json(self.report_path)
        self.enterContext(patch.object(self.runtime.subprocess, 'run'))

    def write_report(self, report, *, receipt=None, mirror=True):
        """Rebind every resource hash so rejection must inspect actual proof semantics."""
        updated = deepcopy(self.receipt if receipt is None else receipt)
        self.report_path.write_text(json.dumps(report, sort_keys=True))
        updated['artifact_sha256']['pipeline_manifest_sha256'] = self.runtime.sha(self.report_path)
        if mirror:
            updated['archive_verification'] = {field: report.get(field) for field in PROOF_FIELDS}
        info = deepcopy(self.info)
        self.fixture.write_receipt(self.app, updated, info)
        return updated, info

    def assert_refused(self):
        with self.assertRaises(ValueError) as failure:
            self.runtime.inspect_app(self.app, self.fixture.record)
        # A stale outer digest would make all malformed proofs appear covered.
        self.assertNotIn('Preparation artifact differs', str(failure.exception))
        self.assertNotIn('does not bind a full preparation receipt', str(failure.exception))

    def test_candidate_accepts_actual_flat_report_and_exact_receipt_projection(self):
        self.assertEqual(set(self.receipt['archive_verification']), set(PROOF_FIELDS))
        self.assertEqual(self.receipt['archive_verification'],
                         {field: self.report.get(field) for field in PROOF_FIELDS})
        candidate = self.runtime.inspect_app(self.app, self.fixture.record)
        self.assertEqual(candidate['build_runtime_sha256'], self.receipt['artifact_sha256']['runtime_sha256'])
        self.assertNotEqual(candidate['executable_sha256'], candidate['build_runtime_sha256'])

    def test_candidate_rejects_missing_fresh_read_only_proof_after_resealing(self):
        for field in ('verify_only', 'verification_process_fresh'):
            for value in (None, False, 1, 'true'):
                with self.subTest(field=field, value=value):
                    report = deepcopy(self.report)
                    if value is None:
                        report.pop(field, None)
                    else:
                        report[field] = value
                    self.write_report(report)
                    self.assert_refused()

    def test_candidate_rejects_native_exit_failures_and_error_reports(self):
        for value in (None, True, False, 1, -1, '0'):
            with self.subTest(native_exit_code=value):
                report = {**self.report, 'native_exit_code': value}
                self.write_report(report)
                self.assert_refused()
        self.write_report({**self.report, 'error': 'synthetic native verification failure'})
        self.assert_refused()

    def test_candidate_rejects_missing_boolean_negative_or_partial_completion_counters(self):
        for field in ('render', 'compute', 'mesh', 'kept', 'failed', 'write_failed'):
            for value in (None, True, False, -1, '0'):
                with self.subTest(field=field, value=value):
                    report = {**self.report, field: value}
                    self.write_report(report)
                    self.assert_refused()
        report = {**self.report, 'render': 0, 'compute': 0, 'mesh': 0, 'kept': 0}
        self.write_report(report)
        self.assert_refused()
        for field in ('failed', 'write_failed'):
            with self.subTest(nonzero_failure=field):
                self.write_report({**self.report, field: 1})
                self.assert_refused()

    def test_candidate_rejects_jit_archive_misses_or_writes_with_zero_exit(self):
        for field in ('library_jit_attempts', 'archive_misses', 'archive_writes'):
            for value in (None, True, False, 1, -1, '0'):
                with self.subTest(field=field, value=value):
                    self.write_report({**self.report, field: value})
                    self.assert_refused()

    def test_candidate_requires_all_requested_rows_and_actual_archive_reopen(self):
        requested = self.receipt['pipelines']['requested']
        for value in (None, True, False, 0, requested - 1, requested + 1, str(requested)):
            with self.subTest(verified_rows=value):
                self.write_report({**self.report, 'verified_rows': value})
                self.assert_refused()
        for value in (None, True, False, 0, -1, '1'):
            with self.subTest(archive_files_opened=value):
                self.write_report({**self.report, 'archive_files_opened': value})
                self.assert_refused()

    def test_candidate_requires_current_raw_runtime_actual_library_manifest_and_context(self):
        final_signed_hash = self.runtime.sha(self.app / 'Contents/MacOS/KokiriGame')
        for field in ('verification_runtime_sha256', 'libraries_manifest_sha256', 'compiler_context_sha256'):
            for value in (None, 'invalid', '0' * 64):
                with self.subTest(field=field, value=value):
                    self.write_report({**self.report, field: value})
                    self.assert_refused()
        self.write_report({**self.report, 'verification_runtime_sha256': final_signed_hash})
        self.assert_refused()
        for value in (None, True, 1, '2'):
            with self.subTest(compiler_context_schema=value):
                self.write_report({**self.report, 'compiler_context_schema': value})
                self.assert_refused()

    def test_candidate_rejects_unstable_or_missing_archive_snapshots(self):
        for field in ('archive_snapshot_before_sha256', 'archive_snapshot_after_sha256'):
            for value in (None, 'invalid', '0' * 64):
                with self.subTest(field=field, value=value):
                    self.write_report({**self.report, field: value})
                    self.assert_refused()

    def test_candidate_rejects_receipt_projection_disagreement_and_extra_claims(self):
        for projection in (None, {}, [], {**self.receipt['archive_verification'], 'archive_misses': 1},
                           {**self.receipt['archive_verification'], 'unverified_extra_claim': True}):
            with self.subTest(projection=projection):
                receipt = {**deepcopy(self.receipt), 'archive_verification': projection}
                self.write_report(self.report, receipt=receipt, mirror=False)
                self.assert_refused()

    def test_candidate_rejects_flat_report_identity_or_requested_count_disagreement(self):
        changes = [('requested', None), ('requested', True), ('requested', 0),
                   ('requested', self.receipt['pipelines']['requested'] + 1),
                   ('completed', self.receipt['pipelines']['completed'] - 1),
                   ('completed', True), ('arch', 'another-gpu'), ('chain', 'oot-native-v23'),
                   ('runtime_sha256', '0' * 64)]
        for field, value in changes:
            with self.subTest(field=field, value=value):
                self.write_report({**self.report, field: value})
                self.assert_refused()

    def test_candidate_requires_exact_artifact_path_contract(self):
        variants = [None, {}, {**self.receipt['artifact_paths'], 'runtime_sha256': 'Contents/MacOS/OtherRuntime'},
                    {**self.receipt['artifact_paths'], 'pipeline_manifest_sha256': 'Contents/Resources/other.json'}]
        for paths in variants:
            with self.subTest(paths=paths):
                receipt = deepcopy(self.receipt)
                if paths is None:
                    receipt.pop('artifact_paths', None)
                else:
                    receipt['artifact_paths'] = paths
                self.write_report(self.report, receipt=receipt)
                self.assert_refused()

    def test_archive_proof_does_not_promote_an_explicitly_unprepared_candidate(self):
        receipt = {**deepcopy(self.receipt), 'prepared': False}
        self.write_report(self.report, receipt=receipt)
        self.assert_refused()

    def test_unchanged_historical_snapshot_without_archive_proof_can_still_roll_back(self):
        report, receipt = deepcopy(self.report), deepcopy(self.receipt)
        for field in PROOF_FIELDS:
            report.pop(field, None)
        receipt.pop('archive_verification', None)
        receipt.pop('artifact_paths', None)
        self.write_report(report, receipt=receipt, mirror=False)
        self.assert_refused()  # Historical recovery is separate from candidate promotion.
        previous = self.runtime.inspect_app(self.app)
        previous.update(preparation_receipt_sha256=self.runtime.sha(self.app / self.runtime.RECEIPT),
                        preparation_artifact_sha256=self.runtime.verify_preparation_artifacts(
                            self.app, self.runtime.read_json(self.app / self.runtime.RECEIPT)))
        store = self.fixture.root / 'rollback-store'
        store.mkdir(mode=0o700)
        original_active = {'app': str(self.fixture.root / 'UnlaunchedCurrent.app')}
        self.runtime.atomic_json(store / 'state.json', dict(schema=1, highest_version=9,
                                                           active=original_active, previous=previous))
        with patch.object(self.runtime, 'game_closed'):
            restored = self.runtime.rollback(store)
        self.assertEqual(restored['active'], previous)
        self.assertEqual(restored['highest_version'], 9)
        self.assertFalse(restored['game_launched'])


if __name__ == '__main__':
    unittest.main()
