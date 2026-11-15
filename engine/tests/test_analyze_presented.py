#!/usr/bin/env python3
"""Focused CPU-only fixtures for the v1 immutable presentation sidecar analyzer."""
import importlib.util
import json
import tempfile
import unittest
from pathlib import Path


spec = importlib.util.spec_from_file_location('analyze_presented', Path(__file__).resolve().parents[1] / 'scripts' / 'analyze_presented.py')
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)
MAGIC = '# nvn-present-events-v1 clock=mach_absolute_time_seconds\n'
HEADER = '\t'.join(module.HEADER) + '\n'


def row(event, ticket, presented=0, observed=0, generated=0, reason='ok', serial=None):
    return '\t'.join(map(str, [event, ticket + 10, ticket,
                              ticket + 100 if serial is None else serial,
                              generated, presented, observed, reason])) + '\n'


def standard():
    return [row('queued', 1, observed=.9), row('queued', 2, observed=1.005),
            row('queued', 3, observed=1.02), row('queued', 4, observed=1.045),
            row('presented', 1, 1.0, 1.002), row('presented', 2, 1.01, 1.012),
            row('presented', 3, 1.04, 1.042), row('presented', 4, 1.05, 1.052),
            row('queued', 5, observed=1.06)]


class PresentationFixtures(unittest.TestCase):
    def run_rows(self, rows, magic=MAGIC):
        with tempfile.TemporaryDirectory(prefix='presented-fixture-') as temporary:
            path = Path(temporary) / 'events.tsv'
            path.write_text(magic + HEADER + ''.join(rows))
            capture = module.read_events(path)
        return module.analyze(capture, 1.0, 1.05), capture

    def test_full_wall_boundary_and_interval_boundaries(self):
        result, _ = self.run_rows(standard())
        game = result['game']
        self.assertTrue(game['complete_coverage'])
        self.assertEqual(game['distinct_presented_timestamps'], 3)  # start included; end excluded
        self.assertAlmostEqual(game['average_presented_fps'], 60)
        self.assertEqual(game['interval_ms']['samples'], 2)
        self.assertEqual(game['interval_ms']['p50'], 20)
        self.assertEqual(game['interval_ms']['p95'], 30)
        self.assertEqual(game['interval_ms']['p99'], 30)
        self.assertAlmostEqual(game['one_percent_low_fps'], 1000 / 30)

    def test_callback_publication_reordering_is_not_display_disorder(self):
        rows = standard()
        rows[4:7] = [rows[6], rows[4], rows[5]]
        result, _ = self.run_rows(rows)
        self.assertEqual(result['publication_order_presented_time_regressions'], 1)
        self.assertTrue(result['game']['complete_coverage'])
        self.assertEqual(result['game']['interval_ms']['p50'], 20)

    def test_exact_and_repeated_callback_duplicates_do_not_add_updates(self):
        rows = standard() + [standard()[4], row('presented', 1, 1.0, 1.03)]
        result, capture = self.run_rows(rows)
        self.assertEqual(capture['exact_duplicate_rows'], 1)
        self.assertEqual(result['duplicate_game_terminal_observations'], 1)
        self.assertEqual(result['game']['distinct_presented_timestamps'], 3)
        self.assertTrue(result['game']['complete_coverage'])

    def test_missing_terminal_is_unknown_not_drop(self):
        rows = standard()
        del rows[5]
        result, _ = self.run_rows(rows)
        self.assertEqual(result['pending_unknown_tickets_before_end'], [2])
        self.assertEqual(result['explicit_drop_rows_observed_in_window'], 0)
        self.assertIsNone(result['game']['average_presented_fps'])
        self.assertIsNone(result['game']['interval_ms'])
        self.assertEqual(result['game']['observed_timestamp_gaps_ms']['samples'], 1)

    def test_explicit_drop_resolves_only_its_ticket(self):
        rows = standard()
        rows[5] = row('dropped', 2, observed=1.012, reason='merged')
        result, _ = self.run_rows(rows)
        self.assertTrue(result['game']['complete_coverage'])
        self.assertEqual(result['explicit_drop_reasons_observed_in_window'], {'merged': 1})
        self.assertEqual(result['queued_in_segment_outcomes']['dropped'], 1)
        self.assertAlmostEqual(result['game']['average_presented_fps'], 40)

    def test_drop_observed_before_enqueue_cannot_certify_game(self):
        rows = standard()
        rows[5] = row('dropped', 2, observed=1.004, reason='merged')
        result, _ = self.run_rows(rows)
        self.assertEqual(result['game_temporal_causality_violation_tickets'], [2])
        self.assertEqual(result['terminal_observation_before_queue_tickets'], [2])
        self.assertFalse(result['game']['complete_coverage'])
        self.assertIsNone(result['game']['average_presented_fps'])
        self.assertIsNone(result['game']['interval_ms'])

    def test_generated_terminal_observed_before_enqueue_blocks_certification(self):
        rows = standard() + [row('dropped', 2, observed=1.004, generated=1)]
        result, _ = self.run_rows(rows)
        self.assertEqual(result['terminal_observation_before_queue_tickets'], [2])
        self.assertFalse(result['game']['complete_coverage'])

    def test_invalid_terminal_is_not_a_drop(self):
        rows = standard()
        rows[5] = row('invalid', 2, observed=1.012, reason='invalid_presented_time')
        result, _ = self.run_rows(rows)
        self.assertEqual(result['invalid_game_tickets_before_end'], [2])
        self.assertEqual(result['explicit_drop_rows_observed_in_window'], 0)
        self.assertIsNone(result['game']['average_presented_fps'])

    def test_late_callback_still_counts_its_in_window_display(self):
        rows = standard()
        rows[5] = row('presented', 2, 1.01, 1.20)
        result, _ = self.run_rows(rows)
        self.assertTrue(result['game']['complete_coverage'])
        self.assertEqual(result['presented_in_window_callback_after_end'], 1)
        self.assertEqual(result['game']['distinct_presented_timestamps'], 3)

    def test_generated_callback_does_not_resolve_game_pending(self):
        rows = standard()
        del rows[5]
        rows.append(row('presented', 2, 1.015, 1.02, generated=1))
        result, _ = self.run_rows(rows)
        self.assertEqual(result['generated']['distinct_presented_timestamps'], 1)
        self.assertEqual(result['pending_unknown_tickets_before_end'], [2])
        self.assertIsNone(result['generated']['average_presented_fps'])
        self.assertIsNone(result['game']['average_presented_fps'])

    def test_generated_content_separate_from_game(self):
        result, _ = self.run_rows(standard() + [row('presented', 1, 1.005, 1.007, generated=1)])
        self.assertTrue(result['game']['complete_coverage'])
        self.assertEqual(result['game']['distinct_presented_timestamps'], 3)
        self.assertEqual(result['generated']['distinct_presented_timestamps'], 1)
        self.assertEqual(result['all_observed']['distinct_presented_timestamps'], 4)
        self.assertFalse(result['generated']['complete_coverage'])

    def test_game_and_generated_same_timestamp_cannot_certify_game(self):
        rows = standard() + [row('presented', 1, 1.0, 1.007, generated=1)]
        result, _ = self.run_rows(rows)
        self.assertEqual(result['mixed_content_same_timestamp_collisions'], 1)
        self.assertEqual(result['game']['distinct_presented_timestamps'], 3)
        self.assertFalse(result['game']['complete_coverage'])
        self.assertIsNone(result['game']['average_presented_fps'])
        self.assertIsNone(result['game']['interval_ms'])

    def test_multiple_generated_positives_are_ambiguous(self):
        rows = standard() + [row('presented', 2, 1.015, 1.02, generated=1),
                             row('presented', 2, 1.017, 1.022, generated=1)]
        result, _ = self.run_rows(rows)
        self.assertEqual(result['generated_ambiguous_terminal_tickets'], [2])
        self.assertFalse(result['generated']['complete_coverage'])
        self.assertEqual(result['generated']['distinct_presented_timestamps'], 2)

    def test_malformed_nonfinite_and_unfinished_rows_suppress_certification(self):
        for extra in ['malformed\n', row('presented', 7, 'nan', 1.03), standard()[4].rstrip('\n')]:
            with self.subTest(extra=extra):
                result, capture = self.run_rows(standard() + [extra])
                self.assertTrue(capture['parse_issues'])
                self.assertFalse(result['game']['complete_coverage'])
                self.assertIsNone(result['game']['average_presented_fps'])

    def test_missing_enqueue_and_ticket_gap_are_unknown(self):
        rows = standard()
        del rows[1]
        result, _ = self.run_rows(rows)
        self.assertEqual(result['orphan_terminal_tickets'], [2])
        self.assertEqual(result['missing_queue_ticket_ranges'], [{'first': 2, 'last': 2, 'count': 1}])
        self.assertIsNone(result['game']['average_presented_fps'])

    def test_missing_capture_prefix_is_unknown_even_without_orphans(self):
        rows = [line for line in standard() if line.split('\t')[2] != '1']
        result, _ = self.run_rows(rows)
        self.assertEqual(result['missing_queue_ticket_ranges'], [{'first': 1, 'last': 1, 'count': 1}])
        self.assertIsNone(result['game']['average_presented_fps'])

    def test_display_time_orders_updates_independently_of_ticket_order(self):
        rows = standard()
        rows[4] = row('presented', 1, 1.03, 1.032)
        result, _ = self.run_rows(rows)
        self.assertEqual(result['game_ticket_order_presented_time_regressions'], 1)
        self.assertTrue(result['game']['complete_coverage'])
        self.assertEqual(result['game']['interval_ms']['p50'], 15)

    def test_multiple_game_tickets_at_one_timestamp_are_not_double_counted(self):
        rows = standard()
        rows[1] = row('queued', 2, observed=.95)
        rows[5] = row('presented', 2, 1.0, 1.012)
        result, _ = self.run_rows(rows)
        self.assertEqual(result['game_same_timestamp_collisions'], 1)
        self.assertEqual(result['game']['distinct_presented_timestamps'], 2)
        self.assertIsNone(result['game']['average_presented_fps'])

    def test_conflicting_terminal_states_suppress_certification(self):
        result, _ = self.run_rows(standard() + [row('dropped', 2, observed=1.03, reason='merged')])
        self.assertEqual(result['terminal_conflict_tickets'], [2])
        self.assertIn(2, result['pending_unknown_tickets_before_end'])
        self.assertIsNone(result['game']['average_presented_fps'])

    def test_wrong_serial_and_temporal_causality_are_flagged(self):
        rows = standard()
        rows[5] = row('presented', 2, 1.01, 1.012, serial=999)
        result, _ = self.run_rows(rows)
        self.assertEqual(result['identity_mismatch_tickets'], [2])
        self.assertFalse(result['game']['complete_coverage'])
        rows[5] = row('presented', 2, 1.001, 1.012)
        result, _ = self.run_rows(rows)
        self.assertEqual(result['game_temporal_causality_violation_tickets'], [2])

    def test_unqueued_discard_does_not_create_a_pending_ticket(self):
        rows = standard() + [row('dropped', 0, observed=1.02, reason='discard_before_enqueue')]
        result, _ = self.run_rows(rows)
        self.assertEqual(result['unqueued_discard_rows_observed_in_window'], 1)
        self.assertTrue(result['game']['complete_coverage'])

    def test_capture_must_extend_to_end_and_clock_must_match(self):
        rows = standard()[:-2]
        result, _ = self.run_rows(rows)
        self.assertFalse(result['game']['complete_coverage'])
        result, capture = self.run_rows(standard(), magic='# clock=unix_epoch\n')
        self.assertTrue(capture['parse_issues'])
        self.assertFalse(result['game']['complete_coverage'])

    def test_segment_markers_need_monotonic_bounds_and_complete_pairs(self):
        with tempfile.TemporaryDirectory(prefix='presented-markers-') as temporary:
            path = Path(temporary) / 'segments.jsonl'
            rows = [{'scene': 'good', 'phase': 'start', 'monotonic': 1},
                    {'scene': 'good', 'phase': 'end', 'monotonic': 2},
                    {'scene': 'open', 'phase': 'start', 'monotonic': 3},
                    {'scene': 'epoch-only', 'phase': 'start', 'time': 1234}, []]
            path.write_text(''.join(json.dumps(value) + '\n' for value in rows))
            complete, incomplete, issues = module.read_segments(path)
        self.assertEqual(complete, [('good', 1, 2)])
        self.assertEqual(incomplete[0]['scene'], 'open')
        self.assertEqual(len(issues), 2)

    def test_hitch_threshold_is_strict_and_one_percent_rounds_up(self):
        self.assertEqual(module.distribution([1, 2, 3, 4])['p95'], 4)
        rows = [row('queued', 1, observed=.9), row('queued', 2, observed=1.001),
                row('presented', 1, 1.0, 1.001), row('presented', 2, 1.1, 1.101),
                row('queued', 3, observed=1.201)]
        with tempfile.TemporaryDirectory(prefix='presented-hitch-') as temporary:
            path = Path(temporary) / 'events.tsv'
            path.write_text(MAGIC + HEADER + ''.join(rows))
            result = module.analyze(module.read_events(path), 1.0, 1.2)
        self.assertEqual(result['game']['hitch_counts']['greater_than_100_ms'], 0)
        self.assertEqual(result['game']['hitch_counts']['greater_than_50_ms'], 1)
        self.assertEqual(result['game']['one_percent_low_fps'], 10)


if __name__ == '__main__':
    unittest.main(verbosity=2)
