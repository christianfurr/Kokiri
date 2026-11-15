"""Read-only reconciliation of existing seed partitions and completed finite windows.

The resume document indexes evidence; it does not authorize missing work or
convert an observed cache into request-verification evidence.
"""
from collections import Counter
import hashlib
import json
from pathlib import Path
import re

import prepare_ns2_seed as seed

SCHEMA = 'kokiri-ns2-seed-resume-v1'
IDENTITY_FIELDS = ('chain', 'version', 'source_romfs_sha256', 'corpus_sha256', 'shader_list_sha256',
                   'runtime_sha256', 'translator_sha256', 'translation_context_sha256', 'nvn_depth_mode')
COUNT_FIELDS = ('translated_default', 'corpus_shaders', 'listed_variants', 'listed_asked',
                'listed_requests', 'checked_variants', 'cached_kept', 'made_again')
UNPINNED = object()


def reconcile_plan(plan_path, *, expected_identity, corpus, shader_list, cache, jobs=2):
    """Return proven outputs/metadata, or fail without writing files or running native code."""
    protected = [Path(plan_path), Path(corpus), Path(shader_list)]

    def read(path, expected_sha=UNPINNED, *, json_value=False):
        if expected_sha is not UNPINNED and (not isinstance(expected_sha, str) or not re.fullmatch('[0-9a-f]{64}', expected_sha)):
            raise ValueError('resume evidence lacks a valid pinned hash')
        path = Path(path)
        protected.append(path)
        before = path.stat()
        raw = path.read_bytes()
        after = path.stat()
        if (before.st_dev, before.st_ino, before.st_size, before.st_mtime_ns, before.st_ctime_ns) != (
            after.st_dev, after.st_ino, after.st_size, after.st_mtime_ns, after.st_ctime_ns):
            raise ValueError('resume evidence changed while reading: '+str(path))
        digest = hashlib.sha256(raw).hexdigest()
        if expected_sha is not UNPINNED and digest != expected_sha:
            raise ValueError('resume evidence hash differs: '+str(path))
        value = json.loads(raw) if json_value else raw.decode()
        if json_value and not isinstance(value, dict):
            raise ValueError('resume JSON evidence must be an object')
        return value, digest

    plan, plan_sha = read(plan_path, json_value=True)
    if not isinstance(plan, dict) or plan.get('schema') != SCHEMA:
        raise ValueError('unsupported shader resume plan format')
    expected = {field: expected_identity[field] for field in IDENTITY_FIELDS}
    context_inputs = dict(schema=3, chain=seed.CHAIN, depth_mode=expected['nvn_depth_mode'],
                          translator_sha256=expected['translator_sha256'])
    context_sha = hashlib.sha256(json.dumps(context_inputs, sort_keys=True, separators=(',', ':')).encode()).hexdigest()
    if (expected['chain'] != seed.CHAIN or expected['nvn_depth_mode'] not in ('minus-w', 'zero') or
        expected['translation_context_sha256'] != context_sha):
        raise ValueError('resume translation context is inconsistent with the active shader chain')
    if plan.get('identity') != expected:
        raise ValueError('resume identity differs; changed runtime or requests need native revalidation')
    if seed.sha256(corpus) != expected['corpus_sha256'] or seed.sha256(shader_list) != expected['shader_list_sha256']:
        raise ValueError('resume original corpus or source list changed')
    inventory = seed.corpus_inventory(Path(corpus))
    original_rows = {}
    source_text, _ = read(shader_list, expected['shader_list_sha256'])
    for line in source_text.splitlines():
        if line.startswith('V\t'):
            fields = line.split('\t')
            if len(fields) != 3:
                raise ValueError('invalid original source binding row')
            original_rows.setdefault(fields[1], []).append(line)
    original_listed = seed.source_listed_requests(shader_list, inventory)
    descriptors = plan.get('partitions')
    if not isinstance(descriptors, list) or not descriptors:
        raise ValueError('resume plan has no immutable partitions')
    original = iter(seed.corpus_records(corpus))
    partitions, all_keys, paths, offset = {}, set(), set(), 12
    for number, descriptor in enumerate(descriptors):
        if not isinstance(descriptor, dict) or descriptor.get('number') != number:
            raise ValueError('resume partitions must be unique and ordered from zero')
        chunk, listed = Path(descriptor['corpus']), Path(descriptor['list'])
        for path in (chunk, listed):
            resolved = path.resolve()
            if resolved in paths:
                raise ValueError('resume partition paths overlap')
            paths.add(resolved); protected.append(path)
        if seed.sha256(chunk) != descriptor.get('corpus_sha256'):
            raise ValueError('resume partition corpus hash differs')
        keys, first_offset = [], offset
        for key, stage, label, raw in seed.corpus_records(chunk):
            source = next(original, None)
            if source is None or (key, stage, label, raw) != source or key in all_keys:
                raise ValueError('resume partitions do not cover original records exactly once in order')
            keys.append(key); all_keys.add(key)
            offset += len(raw)
        text, _ = read(listed, descriptor.get('list_sha256'))
        rows = [line for line in text.splitlines() if line and not line.startswith('#')]
        wanted = [line for key in keys for line in original_rows.get(key, [])]
        if Counter(rows) != Counter(wanted):
            raise ValueError('resume partition omits or changes original V binding membership')
        known = len(keys)+len(rows)
        if known > 500:
            raise ValueError('resume partition exceeds 500 known requests')
        partitions[number] = dict(keys=keys, descriptor=descriptor, known_requests=known,
                                  listed_requests=seed.listed_request_count(rows), source_record_offset=first_offset)
    if next(original, None) is not None or all_keys != set(inventory):
        raise ValueError('resume partitions are incomplete for the original corpus')
    if sum(partition['listed_requests'] for partition in partitions.values()) != original_listed:
        raise ValueError('resume partition requests differ from the independent original source census')

    windows = plan.get('windows')
    if not isinstance(windows, list) or not windows:
        raise ValueError('resume plan has no accepted finite-window ledgers')
    accepted, verified_union, output_hashes, receipts = {}, set(), {}, []
    for reference in windows:
        if not isinstance(reference, dict) or not reference.get('receipt_sha256') or not reference.get('ledger_sha256'):
            raise ValueError('resume window reference lacks pinned receipt and ledger hashes')
        window_path = Path(reference['receipt'])
        window, window_sha = read(window_path, reference['receipt_sha256'], json_value=True)
        if (window.get('schema') != 'kokiri-finite-shader-window-v2' or window.get('status') != 'finite-window-complete-only' or
            window.get('stop_reason') or window.get('error') or window.get('cleanup_error') or
            window.get('remaining_supervisor_group') or window.get('jobs') != 1 or
            window.get('maximum_known_requests') != 4000 or window.get('maximum_seconds') != 300 or
            window.get('full_seed_published') is not False or window.get('prepared') is not False):
            raise ValueError('resume accepts only successful finite-window evidence with clean descendants')
        proof, proof_sha = read(window['source_proof_path'], window['source_proof_sha256'], json_value=True)
        if (proof.get('schema') != 'kokiri-finite-source-proof-v1' or
            proof.get('source_corpus', {}).get('sha256') != expected['corpus_sha256']):
            raise ValueError('resume finite source proof belongs to another original corpus')
        grant = window.get('grant', {})
        if (grant.get('owner_thread_id') != '01a1e00c-e2ee-7dd3-bdcf-31eef3625144' or
            grant.get('state') != 'granted' or proof.get('grant_id') != grant.get('grant_id') or
            proof.get('lease_content_sha256') != grant.get('lease_content_sha256')):
            raise ValueError('resume finite window lacks its granted proof identity')
        producer, producer_sha = read(proof['producer_progress_path'], proof['producer_progress_sha256'], json_value=True)
        for field in ('corpus_sha256', 'runtime_sha256', 'translator_sha256', 'translation_context_sha256'):
            if producer.get(field) != expected[field]:
                raise ValueError('resume producer context differs; real request revalidation required')
        if producer.get('planned_batches') != len(partitions):
            raise ValueError('resume plan differs from the immutable producer partition inventory')
        source_binding = proof.get('inputs', {}).get(str(Path(shader_list).resolve()), {})
        if source_binding.get('sha256') != expected['shader_list_sha256']:
            raise ValueError('resume source proof lacks the current original binding list')
        selected = window.get('selected_batches')
        completed = window.get('completed')
        if (not isinstance(selected, list) or not 1 <= len(selected) <= 8 or len(set(selected)) != len(selected) or
            selected != proof.get('selected_batches') or not isinstance(completed, list) or
            [entry.get('batch') for entry in completed] != selected or any(number not in partitions for number in selected)):
            raise ValueError('resume finite window completion inventory differs from its scope')
        if sum(partitions[number]['known_requests'] for number in selected) > 4000:
            raise ValueError('resume finite window exceeds its request bound')
        ledger_text, ledger_sha = read(window_path.parent/'ledger.jsonl', reference['ledger_sha256'])
        ledger = [json.loads(line) for line in ledger_text.splitlines() if line]
        if ledger != completed:
            raise ValueError('resume finite ledger does not bind exactly its completed receipts')
        for entry in completed:
            number = entry['batch']
            if number in accepted:
                raise ValueError('resume has duplicate completion evidence for a partition')
            if entry.get('result') != 'batch-complete-only':
                raise ValueError('resume ledger does not credit a completed batch')
            child, child_sha = read(entry['receipt'], entry['receipt_sha256'], json_value=True)
            partition = partitions[number]
            descriptor = partition['descriptor']
            matching = [item for item in proof.get('batch_plans', []) if item.get('batch_number') == number]
            if len(matching) != 1:
                raise ValueError('resume source proof lacks a unique immutable partition plan')
            planned = matching[0]
            if (planned.get('batch_sha256') != descriptor['corpus_sha256'] or planned.get('list_sha256') != descriptor['list_sha256'] or
                not isinstance(planned.get('keys'), list) or len(planned['keys']) != len(partition['keys']) or
                set(planned['keys']) != set(partition['keys']) or planned.get('defaults_requested') != len(partition['keys']) or
                planned.get('binding_requests') != partition['listed_requests'] or
                planned.get('conservative_known_requests') != partition['known_requests'] or
                planned.get('source_record_offset') != partition['source_record_offset'] or
                Path(planned['batch_path']).resolve() != Path(descriptor['corpus']).resolve() or
                Path(planned['list_path']).resolve() != Path(descriptor['list']).resolve()):
                raise ValueError('resume immutable partition plan differs from its source proof')
            if (child.get('schema') != 'kokiri-bounded-shader-batch-v2' or child.get('status') != 'batch-complete-only' or
                child.get('returncode') != 0 or child.get('stop_reason') or child.get('error') or child.get('cleanup_error') or
                child.get('remaining_native_group') or child.get('batch_number') != number or
                child.get('source_proof_sha256') != proof_sha or Path(child['source_proof_path']).resolve() != Path(window['source_proof_path']).resolve()):
                raise ValueError('resume child is failed, unknown, incomplete or belongs to another proof')
            if child.get('batch_sha256') != descriptor['corpus_sha256'] or child.get('batch_list_sha256', child.get('list_sha256')) != descriptor['list_sha256']:
                raise ValueError('resume child checked another immutable partition')
            env, command = child.get('effective_env', {}), child.get('command', [])
            required_env = dict(TOTK_SHADER_CACHE=str(Path(cache).resolve()), TOTK_SEED_DEPTH_MODE=expected['nvn_depth_mode'],
                                TOTK_SHADER_SEED='off', TOTK_RT_BG_WORKERS='1', TOTK_SHADER_SERVICE='native',
                                TOTK_XLATE_SPIRV_CROSS='inproc', TOTK_SEED_VERIFY='1')
            if (any(env.get(key) != value for key, value in required_env.items()) or len(command) != 5 or command[2] != 'seed-shaders' or
                Path(command[3]).resolve() != Path(descriptor['corpus']).resolve() or Path(command[4]).resolve() != Path(descriptor['list']).resolve()):
                raise ValueError('resume child did not perform the required native request verification')
            native_path = str(Path(command[0]).resolve())
            translator_path = str((Path(env.get('TOTK_NATIVE_DIR', ''))/'shader-service/totk_xlate').resolve())
            for path, field in ((native_path, 'runtime_sha256'), (translator_path, 'translator_sha256')):
                protected.append(Path(path))
                if proof.get('inputs', {}).get(path, {}).get('sha256') != expected[field]:
                    raise ValueError('resume child executable context differs; real request revalidation required')
            attempt = Path(entry['receipt']).parent
            completion = child.get('completion', {})
            log_path = Path(completion.get('log', attempt/'native.log'))
            verified_path = Path(completion.get('verified_path', attempt/'verified.txt'))
            historical = 'log_sha256' in completion and 'verified_sha256' in completion
            if ('log_sha256' in completion) != ('verified_sha256' in completion):
                raise ValueError('resume child has incomplete historical log/verified hash evidence')
            if not historical and reference.get('allow_import_time_corroboration') is not True:
                raise ValueError('resume legacy child requires explicit import-time corroboration admission')
            log, log_sha = read(log_path, completion['log_sha256']) if historical else read(log_path)
            names_text, names_sha = read(verified_path, completion['verified_sha256']) if historical else read(verified_path)
            names = set(names_text.split())
            actual = seed.batch_completion(log, partition['keys'], names, True, 0,
                                           expected_listed_requests=partition['listed_requests'])
            if any(completion.get(field) != actual[field] for field in COUNT_FIELDS) or set(completion.get('keys', [])) != set(partition['keys']):
                raise ValueError('resume native reports disagree with ledger-bound completion counts')
            outputs, _ = seed.verified_batch_outputs(Path(cache), names, partition['keys'], jobs)
            expected_outputs = completion.get('output_sha256')
            if not isinstance(expected_outputs, dict) or set(outputs) != set(expected_outputs):
                raise ValueError('resume verified output inventory differs from its receipt')
            for filename, source in outputs.items():
                if seed.sha256(source) != expected_outputs[filename]:
                    raise ValueError('resume cached output or request index changed: '+filename)
                if filename.endswith('.variants'):
                    for variant in json.loads(source.read_text()):
                        if variant.get('variant') in names and not seed.VARIANTS.fullmatch(filename):
                            raise ValueError('resume request index refers to another shader')
                        if variant.get('variant') in names and not re.fullmatch('[0-9a-f]{64}', variant.get('request', '')):
                            raise ValueError('resume verified variant lacks its original runtime request identity')
                if filename in output_hashes and output_hashes[filename] != expected_outputs[filename]:
                    raise ValueError('resume conflicting output proofs')
                output_hashes[filename] = expected_outputs[filename]
            actual.update(output_sha256=expected_outputs, source_child_receipt=str(Path(entry['receipt']).resolve()),
                          source_child_receipt_sha256=child_sha, source_window_receipt_sha256=window_sha,
                          source_ledger_snapshot_sha256=ledger_sha, source_proof_sha256=proof_sha,
                          producer_progress_sha256=producer_sha,
                          corroboration='historical-hashes' if historical else 'import-time-only',
                          imported_log_sha256=log_sha, imported_verified_sha256=names_sha)
            accepted[number] = actual
            verified_union.update(names)
        receipts.append(dict(receipt=str(window_path.resolve()), receipt_sha256=window_sha, ledger_snapshot_sha256=ledger_sha))
    if set(accepted) != set(partitions):
        raise ValueError('resume lacks accepted completion evidence for every partition')
    reports = [accepted[number] for number in sorted(accepted)]
    totals = seed.aggregate_batches(inventory, reports, verified_union, expected_listed_requests=original_listed)
    progress = dict(schema=1, status='complete', corpus_sha256=expected['corpus_sha256'],
                    runtime_sha256=expected['runtime_sha256'], translator_sha256=expected['translator_sha256'],
                    translation_context_sha256=expected['translation_context_sha256'], corpus_shaders=len(inventory),
                    listed_requests=original_listed, planned_batches=len(partitions), batches=reports, totals=totals,
                    resume_plan_sha256=plan_sha, resume_implementation_sha256=seed.sha256(Path(__file__)), source_windows=receipts)
    return dict(inventory=inventory, verified=verified_union, totals=totals, progress=progress,
                output_sha256=output_hashes, protected_paths=protected)
