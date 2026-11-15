#!/usr/bin/env python3
"""Analyze immutable presentation events against Python monotonic-time segments."""
import argparse
import json
import math
import statistics
import sys
from collections import Counter, defaultdict
from pathlib import Path


HEADER = 'event frame ticket serial generated presented_s observed_s reason'.split()
EVENTS = {'queued', 'presented', 'dropped', 'invalid'}


def distribution(values):
    ordered = sorted(values)
    if not ordered:
        return dict(samples=0, mean=None, p50=None, p95=None, p99=None, maximum=None)
    return dict(samples=len(ordered), mean=statistics.fmean(ordered),
                p50=statistics.median(ordered),
                p95=ordered[math.ceil(.95 * len(ordered)) - 1],
                p99=ordered[math.ceil(.99 * len(ordered)) - 1], maximum=ordered[-1])


def read_events(path):
    rows = []
    issues = []
    duplicates = 0
    seen = set()
    magic = False
    header = False
    with path.open() as stream:
        for number, line in enumerate(stream, 1):
            if line.startswith('#'):
                magic |= 'nvn-present-events-v1' in line and 'clock=mach_absolute_time_seconds' in line
                continue
            if not line.strip():
                continue
            fields = line.rstrip('\n\r').split('\t')
            if fields == HEADER:
                if header:
                    issues.append({'line': number, 'reason': 'Repeated header; possible concatenated captures'})
                header = True
                continue
            try:
                if not line.endswith('\n'):
                    raise ValueError('Unfinished final row')
                if not header or len(fields) != len(HEADER):
                    raise ValueError('Missing header or wrong column count')
                row = dict(zip(HEADER, fields))
                if row['event'] not in EVENTS:
                    raise ValueError('Unknown event type')
                for key in ('frame', 'ticket', 'serial', 'generated'):
                    if not row[key].isdigit():
                        raise ValueError(f'Invalid {key}')
                    row[key] = int(row[key])
                    if row[key] > 2 ** 64 - 1:
                        raise ValueError(f'{key} exceeds the schema uint64 range')
                if row['generated'] not in (0, 1):
                    raise ValueError('generated must be 0 or 1')
                for key in ('presented_s', 'observed_s'):
                    row[key] = float(row[key])
                    if not math.isfinite(row[key]):
                        raise ValueError(f'Nonfinite {key}')
                if row['event'] == 'presented' and row['presented_s'] <= 0:
                    raise ValueError('Presented event needs a positive actual timestamp')
                if row['observed_s'] < 0 or (row['observed_s'] == 0 and row['event'] != 'invalid'):
                    raise ValueError('Non-invalid event needs a positive observed timestamp')
                if row['event'] == 'queued' and (not row['ticket'] or row['generated'] or row['presented_s'] != 0):
                    raise ValueError('Invalid queued identity/state')
                if not row['ticket'] and not (row['event'] == 'dropped' and not row['generated']
                                             and row['reason'] == 'discard_before_enqueue'):
                    raise ValueError('Only explicit unqueued discards may use ticket zero')
                if row['event'] == 'dropped' and row['presented_s'] != 0:
                    raise ValueError('Drop cannot carry a presentation timestamp')
                identity = tuple(row[key] for key in HEADER)
                if identity in seen:
                    duplicates += 1
                    continue
                seen.add(identity)
                row['line'] = number
                rows.append(row)
            except ValueError as error:
                issues.append({'line': number, 'reason': str(error)})
    if not magic:
        issues.append({'line': 0, 'reason': 'Missing version/clock declaration'})
    if not header:
        issues.append({'line': 0, 'reason': 'Missing schema header'})
    return {'rows': rows, 'parse_issues': issues, 'exact_duplicate_rows': duplicates}


def terminal_identity(row):
    return (row['event'], row['frame'], row['serial'], row['presented_s'], row['reason'])


def analyze(capture, start, end, scene='manual'):
    if not math.isfinite(start) or not math.isfinite(end) or start <= 0 or end <= start:
        raise ValueError('Require finite monotonic bounds with 0 < start < end')
    rows = capture['rows']
    queues = defaultdict(list)
    game_terminals = defaultdict(list)
    generated_terminals = defaultdict(list)
    unqueued = []
    for row in rows:
        if row['event'] == 'queued':
            queues[row['ticket']].append(row)
        elif not row['ticket']:
            unqueued.append(row)
        elif row['generated']:
            generated_terminals[row['ticket']].append(row)
        else:
            game_terminals[row['ticket']].append(row)

    queue_conflicts = []
    terminal_conflicts = []
    identity_mismatches = []
    publication_violations = []
    temporal_violations = []
    terminal_observation_violations = []
    duplicate_terminals = 0
    resolved = {}
    for ticket, queued in queues.items():
        if len({(q['frame'], q['serial'], q['observed_s']) for q in queued}) != 1:
            queue_conflicts.append(ticket)
        queue = queued[0]
        terminals = game_terminals.get(ticket, [])
        distinct = {terminal_identity(row) for row in terminals}
        duplicate_terminals += len(terminals) - len(distinct)
        if len(distinct) > 1:
            terminal_conflicts.append(ticket)
        if any((row['frame'], row['serial']) != (queue['frame'], queue['serial']) for row in terminals):
            identity_mismatches.append(ticket)
        if any(row['line'] < queue['line'] for row in terminals):
            publication_violations.append(ticket)
        if any(row['observed_s'] < queue['observed_s'] or
               (row['event'] == 'presented' and
                (row['presented_s'] < queue['observed_s'] or row['observed_s'] < row['presented_s']))
               for row in terminals):
            temporal_violations.append(ticket)
        if any(row['observed_s'] < queue['observed_s']
               for row in terminals + generated_terminals.get(ticket, [])):
            terminal_observation_violations.append(ticket)
        if (len(distinct) == 1 and ticket not in queue_conflicts and
                ticket not in identity_mismatches and ticket not in publication_violations):
            resolved[ticket] = terminals[0]

    orphan_tickets = sorted((game_terminals.keys() | generated_terminals.keys()) - queues.keys())
    tickets = sorted(queues)
    missing_ranges = [{'first': left + 1, 'last': right - 1, 'count': right - left - 1}
                      for left, right in zip(tickets, tickets[1:]) if right > left + 1]
    if tickets and tickets[0] != 1:
        missing_ranges.insert(0, {'first': 1, 'last': tickets[0] - 1, 'count': tickets[0] - 1})
    relevant = {ticket for ticket, values in queues.items() if values[0]['observed_s'] < end}
    cohort = {ticket for ticket in relevant if queues[ticket][0]['observed_s'] >= start}
    pending = sorted(relevant - resolved.keys())
    invalid = sorted(ticket for ticket in relevant if ticket in resolved and resolved[ticket]['event'] == 'invalid')
    observed = [row['observed_s'] for row in rows if row['observed_s'] > 0]
    extent = {'first_observed_s': min(observed) if observed else None,
              'last_observed_s': max(observed) if observed else None}
    blockers = []
    if capture['parse_issues']:
        blockers.append('Malformed/schema/unfinished rows make missing events unknown')
    if not observed or min(observed) > start or max(observed) < end:
        blockers.append('Capture does not bracket the full monotonic segment')
    if missing_ranges:
        blockers.append('Gaps between queued ticket IDs; missing enqueues are unknown')
    if orphan_tickets:
        blockers.append('Terminal events without queued identities')
    if queue_conflicts or terminal_conflicts or identity_mismatches or publication_violations:
        blockers.append('Conflicting identities/states or terminal-before-enqueue publication')
    if temporal_violations:
        blockers.append('Game terminal precedes enqueue or callback observation precedes presentation')
    if terminal_observation_violations:
        blockers.append('Terminal observation precedes its enqueue observation')
    if pending:
        blockers.append('Queued-before-end tickets have no unambiguous terminal; pending/unknown')
    if invalid:
        blockers.append('Invalid game terminals have unknown display outcome')

    # Callback/publication order is deliberately not used as display order.
    presented = [row for row in rows if row['event'] == 'presented' and start <= row['presented_s'] < end]
    by_stamp = defaultdict(list)
    for row in presented:
        by_stamp[row['presented_s']].append(row)
    game_collisions = [stamp for stamp, values in by_stamp.items()
                       if len({row['ticket'] for row in values if not row['generated']}) > 1]
    mixed_collisions = [stamp for stamp, values in by_stamp.items() if len({row['generated'] for row in values}) > 1]
    if game_collisions:
        blockers.append('Multiple game tickets claim the same actual display timestamp')
    if mixed_collisions:
        blockers.append('Game and generated content claim the same actual display timestamp')
    generated_conflicts = sorted(ticket for ticket, terminals in generated_terminals.items()
                                 if len({terminal_identity(row) for row in terminals}) > 1)
    for ticket, terminals in generated_terminals.items():
        if ticket in queues and any((row['frame'], row['serial']) !=
                                    (queues[ticket][0]['frame'], queues[ticket][0]['serial']) for row in terminals):
            generated_conflicts.append(ticket)

    def timestamp_metrics(selected, certified):
        stamps = sorted({row['presented_s'] for row in selected})
        gaps = [round((right - left) * 1000, 6) for left, right in zip(stamps, stamps[1:])]
        slow = sorted(gaps, reverse=True)[:max(1, math.ceil(len(gaps) * .01))] if gaps else []
        stats = distribution(gaps)
        low = 1000 / statistics.fmean(slow) if slow and statistics.fmean(slow) > 0 else None
        hitches = {f'greater_than_{limit:g}_ms': sum(value > limit for value in gaps)
                   for limit in (33.3, 50, 100)}
        return {
            'positive_presented_event_rows': len(selected), 'distinct_presented_timestamps': len(stamps),
            'observed_count_rate_fps': len(stamps) / (end - start),
            'complete_coverage': certified,
            'average_presented_fps': len(stamps) / (end - start) if certified else None,
            'interval_ms': stats if certified else None,
            'one_percent_low_fps': low if certified else None,
            'one_percent_low_interval_count': len(slow),
            'hitch_counts': hitches if certified else None,
            'observed_timestamp_gaps_ms': stats,
            'observed_gap_one_percent_low_fps': low,
            'observed_gap_hitch_counts': hitches,
            'first_presented_s': stamps[0] if stamps else None,
            'last_presented_s': stamps[-1] if stamps else None,
            'interval_boundary_rule': 'Only consecutive distinct timestamps both within [start,end); no clipped or outside-boundary intervals',
        }

    game_presented = [row for row in presented if not row['generated']]
    generated_presented = [row for row in presented if row['generated']]
    publication_stamps = [row['presented_s'] for row in presented]
    callback_regressions = sum(right < left for left, right in zip(publication_stamps, publication_stamps[1:]))
    ticket_order = sorted(game_presented, key=lambda row: row['ticket'])
    ticket_regressions = sum(right['presented_s'] < left['presented_s']
                             for left, right in zip(ticket_order, ticket_order[1:]))

    def outcomes(tickets_to_count):
        return dict(Counter(resolved[ticket]['event'] if ticket in resolved else 'pending_unknown'
                            for ticket in tickets_to_count))

    drops_in_window = [row for row in rows if row['event'] == 'dropped' and start <= row['observed_s'] < end]
    invalid_in_window = [row for row in rows if row['event'] == 'invalid'
                         and (not row['observed_s'] or start <= row['observed_s'] < end)]
    return {
        'scene': scene, 'start_monotonic_s_inclusive': start, 'end_monotonic_s_exclusive': end,
        'duration_s': end - start,
        'average_boundary_method': 'Distinct actual presentation timestamps in [start,end) divided by the full end-start wall duration',
        'game': timestamp_metrics(game_presented, not blockers),
        'generated': timestamp_metrics(generated_presented, False),
        'all_observed': timestamp_metrics(presented, False),
        'generated_coverage_note': 'No generated enqueue/expected marker exists in v1; absent generated terminals are unknown, not assumed drops or zero generation',
        'all_coverage_note': 'Total physical-update completeness cannot be certified without expected generated-drawable coverage; game coverage is reported separately',
        'coverage_blockers': blockers, 'capture_extent': extent,
        'queued_in_segment': len(cohort), 'queued_in_segment_outcomes': outcomes(cohort),
        'queued_before_end': len(relevant), 'queued_before_end_outcomes': outcomes(relevant),
        'pending_unknown_tickets_before_end': pending, 'invalid_game_tickets_before_end': invalid,
        'late_terminal_rows_after_segment_end': sum(row['observed_s'] >= end for row in rows
                                                    if row['event'] != 'queued' and row['ticket'] in relevant),
        'presented_in_window_callback_after_end': sum(row['observed_s'] >= end for row in presented),
        'explicit_drop_rows_observed_in_window': len(drops_in_window),
        'explicit_drop_reasons_observed_in_window': dict(Counter(row['reason'] for row in drops_in_window)),
        'unqueued_discard_rows_observed_in_window': sum(start <= row['observed_s'] < end for row in unqueued),
        'invalid_rows_observed_in_window_or_unknown_time': len(invalid_in_window),
        'invalid_positive_timestamp_rows': sum(row['event'] == 'invalid' and start <= row['presented_s'] < end
                                               and row['presented_s'] > 0 for row in rows),
        'duplicate_game_terminal_observations': duplicate_terminals,
        'duplicate_generated_terminal_observations': sum(
            len(terminals) - len({terminal_identity(row) for row in terminals})
            for terminals in generated_terminals.values()),
        'queue_conflict_tickets': sorted(queue_conflicts), 'terminal_conflict_tickets': sorted(terminal_conflicts),
        'identity_mismatch_tickets': sorted(identity_mismatches),
        'terminal_before_queue_publication_tickets': sorted(publication_violations),
        'game_temporal_causality_violation_tickets': sorted(temporal_violations),
        'terminal_observation_before_queue_tickets': sorted(terminal_observation_violations),
        'orphan_terminal_tickets': orphan_tickets, 'missing_queue_ticket_ranges': missing_ranges,
        'generated_ambiguous_terminal_tickets': sorted(set(generated_conflicts)),
        'game_same_timestamp_collisions': len(game_collisions),
        'mixed_content_same_timestamp_collisions': len(mixed_collisions),
        'publication_order_presented_time_regressions': callback_regressions,
        'publication_order_note': 'Callback/publication reordering alone is expected and does not invalidate display-sorted intervals',
        'game_ticket_order_presented_time_regressions': ticket_regressions,
        'ticket_order_note': 'Display order comes from actual timestamps, not queue tickets; ticket-order regressions are reported separately',
    }


def read_segments(path):
    pending = defaultdict(list)
    complete = []
    issues = []
    seen = set()
    for number, line in enumerate(path.read_text().splitlines(), 1):
        if not line.strip():
            continue
        try:
            row = json.loads(line)
            if not isinstance(row, dict):
                raise ValueError('Segment marker must be a JSON object')
            identity = (row['scene'], row.get('suite'), row['phase'], row['monotonic'])
            if identity in seen:
                continue
            seen.add(identity)
            value = float(row['monotonic'])
            if not math.isfinite(value) or value <= 0 or row['phase'] not in ('start', 'end'):
                raise ValueError('Invalid phase or monotonic bound')
            key = row['scene'], row.get('suite')
            if row['phase'] == 'start':
                pending[key].append(value)
            elif pending[key]:
                start = pending[key].pop(0)
                if value <= start:
                    raise ValueError('End must be after start')
                complete.append((row['scene'], start, value))
            else:
                raise ValueError('Unmatched end marker')
        except (ValueError, KeyError, TypeError) as error:
            issues.append({'line': number, 'reason': str(error)})
    incomplete = [{'scene': key[0], 'suite': key[1], 'start_monotonic_s': start,
                   'status': 'incomplete; no end marker'} for key, starts in pending.items() for start in starts]
    return complete, incomplete, issues


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('sidecar', type=Path)
    parser.add_argument('--segments', type=Path, help='segments.jsonl with monotonic start/end bounds')
    parser.add_argument('--start', type=float, help='Explicit Python time.monotonic start seconds, inclusive')
    parser.add_argument('--end', type=float, help='Explicit Python time.monotonic end seconds, exclusive')
    parser.add_argument('--output', type=Path)
    args = parser.parse_args()
    if args.segments:
        if args.start is not None or args.end is not None:
            parser.error('Use --segments or --start/--end, not both')
        segments, incomplete, marker_issues = read_segments(args.segments)
    else:
        if args.start is None or args.end is None:
            parser.error('Provide --segments or both --start and --end')
        segments, incomplete, marker_issues = [('manual', args.start, args.end)], [], []
    capture = read_events(args.sidecar)
    result = {'schema': 'oot-presented-analysis-v1', 'sidecar': str(args.sidecar.resolve()),
              'clock': 'mach_absolute_time_seconds / Python time.monotonic on macOS',
              'parse_issues': capture['parse_issues'], 'exact_duplicate_rows': capture['exact_duplicate_rows'],
              'marker_issues': marker_issues, 'incomplete_segments': incomplete,
              'segments': [analyze(capture, start, end, scene) for scene, start, end in segments],
              'instrumentation_note': 'The emitter synchronously fprintf/fflush-es under locks. Enable identically in compared runs; overhead is not zero.'}
    encoded = json.dumps(result, indent=2, allow_nan=False) + '\n'
    if args.output:
        args.output.write_text(encoded)
    else:
        sys.stdout.write(encoded)


if __name__ == '__main__':
    try:
        main()
    except (OSError, ValueError, KeyError) as error:
        raise SystemExit(str(error))
