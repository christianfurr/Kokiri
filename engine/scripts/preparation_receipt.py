"""Account for preparation evidence without treating a development package as prepared.

Callers verify file contents first, then supply their manifests and SHA-256 identities.
The receipt proves coverage of that exact requested work, not all future gameplay.
"""
import copy
import re

try:
    from .metal_toolchain import compiler_context_key
except ImportError:  # standalone script imports used by the build entry point
    import importlib.util
    from pathlib import Path
    _spec = importlib.util.spec_from_file_location('receipt_metal_toolchain', Path(__file__).with_name('metal_toolchain.py'))
    _compiler = importlib.util.module_from_spec(_spec)
    _spec.loader.exec_module(_compiler)
    compiler_context_key = _compiler.compiler_context_key


DIGEST = re.compile(r'^[0-9a-f]{64}$')
COMMIT = re.compile(r'^[0-9a-f]{40,64}$')
IDENTITY_FIELDS = ('chain', 'source_romfs_sha256', 'translator_sha256', 'nvn_depth_mode')
ARTIFACT_FIELDS = ('seed_manifest_sha256', 'libraries_manifest_sha256',
                   'pipeline_manifest_sha256', 'pipeline_index_sha256', 'runtime_sha256')


def preparation_artifact_paths(architecture):
    base = 'Contents/Resources/totk/build/'
    index = base + 'pipelines/pipelines-' + architecture + '.tsv' \
        if isinstance(architecture, str) and re.fullmatch(r'[A-Za-z0-9_.-]+', architecture) else None
    return dict(runtime_sha256='Contents/MacOS/KokiriGame',
                seed_manifest_sha256=base+'shader-seed/seed-manifest.json',
                libraries_manifest_sha256=base+'shader-libs/libraries-manifest.json',
                pipeline_manifest_sha256=base+'pipelines/compute-manifest.json', pipeline_index_sha256=index)


def _count(record, name, errors):
    value = record.get(name)
    if type(value) is not int or value < 0:
        errors.append('missing or invalid count: ' + name)
        return None
    return value


def _difference(requested, completed):
    return max(0, requested - completed) if requested is not None and completed is not None else None


def archive_verification_errors(report, *, requested, libraries_manifest_sha256,
                                compiler_context_sha256, runtime_sha256):
    """Check native verification against independently frozen final package inputs."""
    errors = []
    if report.get('verify_only') is not True or report.get('verification_process_fresh') is not True:
        errors.append('missing fresh read-only pipeline verification')
    if type(report.get('native_exit_code')) is not int or report['native_exit_code'] != 0 or report.get('error'):
        errors.append('pipeline verification native process failed or lacks an exit status')
    fields = ('render', 'compute', 'mesh', 'kept', 'failed', 'write_failed')
    if any(type(report.get(field)) is not int or report[field] < 0 for field in fields):
        errors.append('pipeline verification has invalid completion counters')
    elif sum(report[field] for field in fields[:4]) != requested or report['failed'] or report['write_failed']:
        errors.append('pipeline verification completion counters do not cover the requested rows')
    for field in ('library_jit_attempts', 'archive_misses', 'archive_writes'):
        if type(report.get(field)) is not int or report[field] != 0:
            errors.append('pipeline verification requires zero ' + field)
    if type(requested) is not int or requested <= 0 or type(report.get('verified_rows')) is not int \
            or report['verified_rows'] != requested:
        errors.append('pipeline verification does not cover every requested row')
    if type(report.get('archive_files_opened')) is not int or report['archive_files_opened'] <= 0:
        errors.append('pipeline verification has no actual archive reopen evidence')
    if not isinstance(runtime_sha256, str) or not DIGEST.fullmatch(runtime_sha256) \
            or report.get('verification_runtime_sha256') != runtime_sha256:
        errors.append('pipeline verification used another runtime')
    for field, expected in (('libraries_manifest_sha256', libraries_manifest_sha256),
                            ('compiler_context_sha256', compiler_context_sha256)):
        if not isinstance(expected, str) or not DIGEST.fullmatch(expected) or report.get(field) != expected:
            errors.append('pipeline verification differs from final ' + field)
    if type(report.get('compiler_context_schema')) is not int or report['compiler_context_schema'] != 2:
        errors.append('pipeline verification lacks compiler context schema 2')
    before, after = report.get('archive_snapshot_before_sha256'), report.get('archive_snapshot_after_sha256')
    if not isinstance(before, str) or not DIGEST.fullmatch(before) or before != after:
        errors.append('pipeline archive changed or lacks independent before/after snapshots')
    return errors


def preparation_receipt(mode, seed, libraries, pipelines, *, expected_identity,
                        artifact_sha256, pipeline_requested, source_commit, unresolved_inputs=()):
    """Build a fail-closed coverage receipt from already integrity-checked manifests.

    ``pipeline_requested`` counts unique C/R/B/T/M lines across every tool input,
    matching warm_fill_archive's deduplication. The archive's ``kept`` counter has
    no per-stage breakdown; do not infer one. ``expected_identity`` comes from the
    current source/tools/import, not from an older seed being considered for reuse.
    Missing records stay unknown and cannot establish preparation.
    """
    errors = []
    unresolved_inputs = [unresolved_inputs] if isinstance(unresolved_inputs, str) else list(unresolved_inputs or ())
    if unresolved_inputs:
        errors.append('required preparation inputs remain unresolved')
    if mode not in ('full', 'title', 'none'):
        errors.append('unknown shader mode')
    if mode != 'full':
        errors.append('only full shader mode can be described as prepared')
    seed = seed if isinstance(seed, dict) else {}
    libraries = libraries if isinstance(libraries, dict) else {}
    pipelines = pipelines if isinstance(pipelines, dict) else {}
    expected_identity = expected_identity if isinstance(expected_identity, dict) else {}
    artifact_sha256 = artifact_sha256 if isinstance(artifact_sha256, dict) else {}
    if not isinstance(source_commit, str) or not COMMIT.fullmatch(source_commit):
        errors.append('missing exact source commit')
    for field in IDENTITY_FIELDS:
        wanted = expected_identity.get(field)
        if not isinstance(wanted, str) or not wanted:
            errors.append('missing expected identity: ' + field)
        elif seed.get(field) != wanted:
            errors.append('seed identity differs: ' + field)
    for field in ('source_romfs_sha256', 'translator_sha256'):
        if not DIGEST.fullmatch(str(expected_identity.get(field, ''))):
            errors.append('invalid expected SHA-256: ' + field)
    if not DIGEST.fullmatch(str(seed.get('translation_context_sha256', ''))):
        errors.append('missing translation context SHA-256')
    if mode == 'full':
        seed_runtime = seed.get('runtime_sha256')
        if not isinstance(seed_runtime, str) or not DIGEST.fullmatch(seed_runtime):
            errors.append('seed request proof lacks a valid runtime SHA-256')
        elif seed_runtime != artifact_sha256.get('runtime_sha256'):
            errors.append('seed requests were not verified by the packaged runtime')
    if seed.get('version') != 'oot' or seed.get('all_default') is not True:
        errors.append('seed does not attest complete OoT default requests')
    if seed.get('only') is not None:
        errors.append('seed was restricted to a shader subset')
    defaults_requested = _count(seed, 'corpus_shaders', errors)
    defaults_completed = _count(seed, 'translated_default', errors)
    listed_requested = _count(seed, 'listed_asked', errors)
    listed_completed = _count(seed, 'listed_variants', errors)
    variants_completed = _count(seed, 'shaders', errors)
    if not defaults_requested or defaults_completed != defaults_requested:
        errors.append('default shader requests are incomplete')
    if listed_requested is None or listed_completed != listed_requested:
        errors.append('listed shader requests are incomplete')
    seed_sources = {name: digest for name, digest in seed.get('files', {}).items()
                    if name.endswith('_b.metal')} if isinstance(seed.get('files'), dict) else {}
    if variants_completed is None or variants_completed != len(seed_sources) or not seed_sources:
        errors.append('seed variant count differs from its source manifest')
    if defaults_requested is not None and variants_completed is not None and variants_completed < defaults_requested:
        errors.append('seed has fewer variants than default shader requests')
    if libraries.get('complete') is not True:
        errors.append('Metal library compilation is incomplete')
    if libraries.get('subset'):
        errors.append('Metal libraries were restricted to a shader subset')
    compiler = libraries.get('compiler', '')
    if not isinstance(compiler, str) or not {'-fpreserve-invariance', '-fwrapv'} <= set(compiler.split()):
        errors.append('Metal compiler identity lacks required correctness options')
    observation = libraries.get('compiler_observation')
    compiler_context = libraries.get('compiler_context_sha256')
    compiler_context_schema = libraries.get('compiler_context_schema')
    if mode == 'full':
        if not isinstance(observation, dict) or observation.get('qualified') is not True:
            errors.append('full preparation requires a qualified compiler observation')
        else:
            if observation.get('observation_schema') != 2 or compiler_context_schema != 2:
                errors.append('full preparation requires compiler observation and context schema 2')
            if observation.get('backend') != 'metal':
                errors.append('compiler observation backend is not Metal')
            if not DIGEST.fullmatch(str(observation.get('executable_sha256', ''))):
                errors.append('compiler observation lacks executable SHA-256')
            headers = observation.get('resource_headers')
            if not isinstance(headers, dict) or not DIGEST.fullmatch(str(headers.get('content_sha256', ''))):
                errors.append('compiler observation lacks resource header SHA-256')
            flags = observation.get('effective_flags')
            if not isinstance(flags, list) or '-mmacosx-version-min=26.0' not in flags:
                errors.append('compiler observation lacks the macOS 26.0 deployment flag')
            target = observation.get('effective_target')
            if not isinstance(target, str) or not re.search(r'-apple-macosx26\.0\.0(?:$|-)', target):
                errors.append('compiler observation target is not macOS 26.0.0')
            if not DIGEST.fullmatch(str(compiler_context or '')):
                errors.append('missing library compiler context SHA-256')
            elif isinstance(headers, dict):
                try:
                    observed_context = compiler_context_key(observation)
                except (ValueError, TypeError, AttributeError, KeyError) as error:
                    errors.append('compiler observation identity is invalid: ' + str(error))
                else:
                    if compiler_context != observed_context:
                        errors.append('library compiler context differs from its observation')
    sources = libraries.get('sources') if isinstance(libraries.get('sources'), dict) else {}
    library_files = libraries.get('files') if isinstance(libraries.get('files'), dict) else {}
    def library_covered(name, digest):
        return isinstance(digest, str) and DIGEST.fullmatch(digest) is not None \
            and sources.get(name) == digest \
            and DIGEST.fullmatch(str(library_files.get(digest + '.metallib', ''))) is not None

    compiled = sum(library_covered(name, digest) for name, digest in seed_sources.items())
    if compiled != len(seed_sources):
        errors.append('Metal libraries do not cover every seed variant')
    observed_sources = {}
    variant_caches = libraries.get('variant_caches', [])
    if not isinstance(variant_caches, list):
        errors.append('invalid observed specialization cache inventory')
        variant_caches = []
    for cache in variant_caches:
        if not isinstance(cache, dict) or not isinstance(cache.get('sources'), dict):
            errors.append('invalid observed specialization source inventory')
            continue
        if not isinstance(cache.get('identity'), dict) or cache['identity'].get('chain') != expected_identity.get('chain'):
            errors.append('observed specialization cache belongs to another shader chain')
        for name, digest in cache['sources'].items():
            if not isinstance(name, str) or not isinstance(digest, str) or not DIGEST.fullmatch(digest) \
                    or name != digest + '.metal':
                errors.append('invalid observed specialization source identity: ' + str(name))
            if name in observed_sources and observed_sources[name] != digest:
                errors.append('conflicting observed specialization source: ' + str(name))
            observed_sources[name] = digest
    observed_compiled = sum(library_covered(name, digest) for name, digest in observed_sources.items())
    if observed_compiled != len(observed_sources):
        errors.append('Metal libraries do not cover every observed specialization')
    required_library_hashes = {digest for digest in (*seed_sources.values(), *observed_sources.values())
                               if isinstance(digest, str) and DIGEST.fullmatch(digest)}
    unique_prepared_files = sum(
        DIGEST.fullmatch(str(library_files.get(digest + '.metallib', ''))) is not None
        for digest in required_library_hashes)
    if unique_prepared_files != len(required_library_hashes):
        errors.append('Metal library files do not cover every unique requested source hash')
    for field in ARTIFACT_FIELDS:
        if not DIGEST.fullmatch(str(artifact_sha256.get(field, ''))):
            errors.append('missing artifact SHA-256: ' + field)
    if pipelines.get('chain') != expected_identity.get('chain'):
        errors.append('pipeline archive belongs to another shader chain')
    if pipelines.get('runtime_sha256') != artifact_sha256.get('runtime_sha256'):
        errors.append('pipeline archive belongs to another runtime')
    if not isinstance(pipelines.get('arch'), str) or not re.fullmatch(r'[A-Za-z0-9_.-]+', pipelines['arch']):
        errors.append('pipeline archive has no GPU architecture')
    if type(pipeline_requested) is not int or pipeline_requested <= 0:
        pipeline_requested = None
        errors.append('missing exact deduplicated pipeline request count')
    counts = {name: _count(pipelines, name, errors)
              for name in ('render', 'compute', 'mesh', 'kept', 'failed', 'write_failed')}
    completed = sum(counts[name] for name in ('render', 'compute', 'mesh', 'kept')) \
        if all(counts[name] is not None for name in ('render', 'compute', 'mesh', 'kept')) else None
    if completed != pipeline_requested or pipeline_requested is None:
        errors.append('pipeline completion does not cover the exact requested set')
    if counts['failed'] != 0 or counts['write_failed'] != 0:
        errors.append('pipeline preparation or archive writes failed')
    mesh_requested = _count(pipelines, 'listed_mesh', errors)
    mesh_indexed = _count(pipelines, 'mesh_indexed', errors)
    if mesh_requested is None or mesh_indexed is None or mesh_indexed < mesh_requested:
        errors.append('pipeline archive does not cover the declared mesh requests')
    if mode == 'full':
        errors.extend(archive_verification_errors(pipelines, requested=pipeline_requested,
                      libraries_manifest_sha256=artifact_sha256.get('libraries_manifest_sha256'),
                      compiler_context_sha256=compiler_context,
                      runtime_sha256=artifact_sha256.get('runtime_sha256')))
    return dict(
        schema='kokiri-preparation-receipt-v1', mode=mode, prepared=not errors,
        identity=dict(source_commit=source_commit, **{field: seed.get(field) for field in IDENTITY_FIELDS},
                      translation_context_sha256=seed.get('translation_context_sha256'),
                      seed_runtime_sha256=seed.get('runtime_sha256'),
                      runtime_sha256=artifact_sha256.get('runtime_sha256'), compiler=compiler,
                      gpu_architecture=pipelines.get('arch')),
        variants=dict(default=dict(requested=defaults_requested, completed=defaults_completed,
                                   failed=_difference(defaults_requested, defaults_completed)),
                      listed=dict(requested=listed_requested, completed=listed_completed,
                                  failed=_difference(listed_requested, listed_completed)),
                      unique_completed=variants_completed),
        libraries=dict(requested=len(seed_sources), completed=compiled,
                       failed=len(seed_sources) - compiled, files=len(library_files),
                       count_basis='seed variant source coverage; not unique library files',
                       unique_requested_files=len(required_library_hashes),
                       unique_prepared_files=unique_prepared_files,
                       retained_library_files=len(library_files)),
        pipelines=dict(requested=pipeline_requested, completed=completed,
                       failed=counts['failed'], write_failed=counts['write_failed'],
                       unaccounted=_difference(pipeline_requested, completed),
                       successful_render=counts['render'], successful_compute=counts['compute'],
                       successful_mesh=counts['mesh'], kept=counts['kept'],
                       counter_basis='successful pipeline requests including archive hits; not newly compiled pipelines',
                       mesh_requested=mesh_requested, mesh_indexed=mesh_indexed),
        archive_verification={field: pipelines.get(field) for field in (
            'verify_only', 'verification_process_fresh', 'verification_runtime_sha256',
            'native_exit_code',
            'library_jit_attempts', 'archive_misses', 'archive_writes', 'verified_rows',
            'archive_files_opened', 'libraries_manifest_sha256', 'compiler_context_sha256',
            'compiler_context_schema', 'archive_snapshot_before_sha256', 'archive_snapshot_after_sha256')},
        library_jit_counter_basis='translated shader libraries only; excludes embedded host/support shaders and OS/driver code generation',
        observed_specializations=dict(requested=len(observed_sources), completed=observed_compiled,
                                      failed=len(observed_sources) - observed_compiled),
        compiler_observation=copy.deepcopy(observation), compiler_context_sha256=compiler_context,
        compiler_context_schema=compiler_context_schema,
        unresolved_inputs=copy.deepcopy(unresolved_inputs),
        artifact_paths=preparation_artifact_paths(pipelines.get('arch')),
        artifact_sha256=dict(artifact_sha256), errors=errors,
        limitation='Coverage applies to the requested corpus, binding variants and pipeline lists; '
                   'unobserved gameplay variants may still compile.')


def require_prepared(receipt):
    """Reject a package's prepared claim unless the full receipt passed."""
    if receipt.get('schema') != 'kokiri-preparation-receipt-v1' or receipt.get('mode') != 'full' \
            or receipt.get('prepared') is not True or receipt.get('errors'):
        raise ValueError('package is not fully prepared: ' + '; '.join(receipt.get('errors') or ['invalid receipt']))
    return receipt
