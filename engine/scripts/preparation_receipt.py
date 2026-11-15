"""Account for preparation evidence without treating a development package as prepared.

Callers verify file contents first, then supply their manifests and SHA-256 identities.
The receipt proves coverage of that exact requested work, not all future gameplay.
"""
import re


DIGEST = re.compile(r'^[0-9a-f]{64}$')
COMMIT = re.compile(r'^[0-9a-f]{40,64}$')
IDENTITY_FIELDS = ('chain', 'source_romfs_sha256', 'translator_sha256', 'nvn_depth_mode')
ARTIFACT_FIELDS = ('seed_manifest_sha256', 'libraries_manifest_sha256',
                   'pipeline_manifest_sha256', 'pipeline_index_sha256', 'runtime_sha256')


def _count(record, name, errors):
    value = record.get(name)
    if type(value) is not int or value < 0:
        errors.append('missing or invalid count: ' + name)
        return None
    return value


def _difference(requested, completed):
    return max(0, requested - completed) if requested is not None and completed is not None else None


def preparation_receipt(mode, seed, libraries, pipelines, *, expected_identity,
                        artifact_sha256, pipeline_requested, source_commit):
    """Build a fail-closed coverage receipt from already integrity-checked manifests.

    ``pipeline_requested`` counts unique C/R/B/T/M lines across every tool input,
    matching warm_fill_archive's deduplication. The archive's ``kept`` counter has
    no per-stage breakdown; do not infer one. ``expected_identity`` comes from the
    current source/tools/import, not from an older seed being considered for reuse.
    Missing records stay unknown and cannot establish preparation.
    """
    errors = []
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
    sources = libraries.get('sources') if isinstance(libraries.get('sources'), dict) else {}
    library_files = libraries.get('files') if isinstance(libraries.get('files'), dict) else {}
    compiled = sum(sources.get(name) == digest and digest + '.metallib' in library_files
                   for name, digest in seed_sources.items())
    if compiled != len(seed_sources):
        errors.append('Metal libraries do not cover every seed variant')
    for field in ARTIFACT_FIELDS:
        if not DIGEST.fullmatch(str(artifact_sha256.get(field, ''))):
            errors.append('missing artifact SHA-256: ' + field)
    if pipelines.get('chain') != expected_identity.get('chain'):
        errors.append('pipeline archive belongs to another shader chain')
    if pipelines.get('runtime_sha256') != artifact_sha256.get('runtime_sha256'):
        errors.append('pipeline archive belongs to another runtime')
    if not isinstance(pipelines.get('arch'), str) or not pipelines.get('arch'):
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
                       failed=len(seed_sources) - compiled, files=len(library_files)),
        pipelines=dict(requested=pipeline_requested, completed=completed,
                       failed=counts['failed'], write_failed=counts['write_failed'],
                       unaccounted=_difference(pipeline_requested, completed),
                       newly_render=counts['render'], newly_compute=counts['compute'],
                       newly_mesh=counts['mesh'], kept=counts['kept'],
                       mesh_requested=mesh_requested, mesh_indexed=mesh_indexed),
        artifact_sha256=dict(artifact_sha256), errors=errors,
        limitation='Coverage applies to the requested corpus, binding variants and pipeline lists; '
                   'unobserved gameplay variants may still compile.')


def require_prepared(receipt):
    """Reject a package's prepared claim unless the full receipt passed."""
    if receipt.get('schema') != 'kokiri-preparation-receipt-v1' or receipt.get('mode') != 'full' \
            or receipt.get('prepared') is not True or receipt.get('errors'):
        raise ValueError('package is not fully prepared: ' + '; '.join(receipt.get('errors') or ['invalid receipt']))
    return receipt
