"""Read-only provenance for explicitly selected, already-owned preparation inputs.

Row totals describe metadata, never compiled shaders or prepared pipelines. Cache
identity is preserved verbatim; the producer still validates MSL and reflection.
"""
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import stat

DEFAULT_CHAIN = 'oot-native-v28-mesh-primitive-blocks'


def require(condition, message):
    if not condition:
        raise ValueError(message)


def token(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(',', ':')).encode()).hexdigest()


def file_stat(value):
    return [value.st_dev, value.st_ino, value.st_size, value.st_mode,
            value.st_mtime_ns, value.st_ctime_ns, value.st_nlink]


def fingerprint(path, count_rows):
    before = path.lstat()
    require(stat.S_ISREG(before.st_mode) and before.st_nlink == 1,
            'Preparation inputs must be regular files without hardlinks')
    descriptor = os.open(path, os.O_RDONLY | os.O_NOFOLLOW)
    digest, pending, rows = hashlib.sha256(), b'', 0
    try:
        require(file_stat(os.fstat(descriptor)) == file_stat(before), 'Input changed before reading')
        while block := os.read(descriptor, 1 << 20):
            digest.update(block)
            if count_rows:
                lines = (pending + block).split(b'\n')
                pending = lines.pop()
                rows += sum(bool(line.strip()) and not line.lstrip().startswith(b'#') for line in lines)
        if count_rows:
            rows += bool(pending.strip()) and not pending.lstrip().startswith(b'#')
        require(file_stat(os.fstat(descriptor)) == file_stat(before)
                == file_stat(path.lstat()), 'Input changed while hashing')
    finally:
        os.close(descriptor)
    return dict(kind='file', mode=stat.S_IMODE(before.st_mode), bytes=before.st_size,
                sha256=digest.hexdigest(), stat=file_stat(before)), rows


def content_inventory(snapshot):
    return {name: {key: value for key, value in entry.items() if key not in {'stat', 'path', 'relative_to_work'}}
            for name, entry in snapshot['entries'].items()}


def read_identity(path, entry):
    require(entry['bytes'] <= 1 << 20, 'Cache identity exceeds its metadata bound')
    require(file_stat(path.lstat()) == entry['stat'], 'Cache identity changed')
    descriptor = os.open(path, os.O_RDONLY | os.O_NOFOLLOW)
    try:
        require(file_stat(os.fstat(descriptor)) == entry['stat'], 'Cache identity changed before reading')
        with os.fdopen(descriptor, 'rb', closefd=False) as stream:
            data = stream.read((1 << 20) + 1)
        require(file_stat(os.fstat(descriptor)) == entry['stat'], 'Cache identity changed while reading')
    finally:
        os.close(descriptor)
    require(hashlib.sha256(data).hexdigest() == entry['sha256']
            and file_stat(path.lstat()) == entry['stat'], 'Cache identity changed while reading')
    def unique(pairs):
        result = {}
        for key, value in pairs:
            require(key not in result, 'Duplicate cache identity key')
            result[key] = value
        return result
    value = json.loads(data, object_pairs_hook=unique)
    require(isinstance(value, dict), 'Cache identity must be a JSON object')
    return value


def capture_inputs(work, shader_list=None, learned_caches=(), expected_chain=DEFAULT_CHAIN):
    """Inventory the complete selected run directory, including sibling PSO files."""
    caches = tuple(learned_caches)
    if shader_list is None:
        require(not caches, 'Learned caches require an explicit shader list')
        return None
    work = Path(work).expanduser().resolve(strict=True)
    shader_list = Path(shader_list).expanduser().absolute()
    root, preparation = shader_list.parent, work / 'preparation-inputs'
    require(work.is_dir() and root != preparation and root.is_relative_to(preparation)
            and root.resolve(strict=True) == root, 'Use an owned run below WORK/preparation-inputs')
    caches = tuple(Path(path).expanduser().absolute() for path in caches)
    require(len(set(caches)) == len(caches), 'Duplicate learned cache selection')
    for cache in caches:
        require(cache != root and cache.is_relative_to(root) and cache.resolve(strict=True) == cache
                and cache.is_dir(), 'Selected cache must be an unlinked directory inside the input run')
        require(not any(cache != other and cache.is_relative_to(other) for other in caches),
                'Selected learned cache roots must not overlap')
    require(isinstance(expected_chain, str) and expected_chain, 'An expected shader chain is required')
    entries, metadata_rows = {}, {}

    def visit(directory):
        before = directory.lstat()
        require(stat.S_ISDIR(before.st_mode), 'Input tree contains a linked or nonregular directory')
        relative = directory.relative_to(root).as_posix()
        entries[relative] = dict(kind='directory', mode=stat.S_IMODE(before.st_mode),
                                 bytes=0, stat=file_stat(before))
        with os.scandir(directory) as children:
            paths = sorted((Path(child.path) for child in children), key=lambda path: path.name)
        for path in paths:
            item = path.lstat()
            if stat.S_ISDIR(item.st_mode):
                visit(path)
            else:
                relative = path.relative_to(root).as_posix()
                counted = path == shader_list or path.suffix == '.tsv' and 'pso' in path.name
                entries[relative], rows = fingerprint(path, counted)
                if counted:
                    metadata_rows[relative] = rows
        require(file_stat(directory.lstat()) == file_stat(before), 'Input directory changed while reading')

    visit(root)
    require(shader_list.relative_to(root).as_posix() in entries
            and entries[shader_list.name]['kind'] == 'file', 'Explicit shader list is missing or nonregular')
    selected = []
    for cache in caches:
        path = cache / 'pipelines/identity.json'
        relative = path.relative_to(root).as_posix()
        require(relative in entries and entries[relative]['kind'] == 'file', 'Selected cache lacks pipelines/identity.json')
        identity = read_identity(path, entries[relative])
        require(identity.get('chain') == expected_chain, 'Learned cache shader chain differs from this runtime')
        selected.append(dict(path=str(cache), relative_to_work=cache.relative_to(work).as_posix(), identity=identity))
    for relative, entry in entries.items():
        path = root / relative
        require(file_stat(path.lstat()) == entry['stat'], 'Input tree changed during capture')
        entry.update(path=str(path), relative_to_work=path.relative_to(work).as_posix())
    snapshot = dict(schema='kokiri-preparation-inputs-v1', work=str(work), root=str(root),
                    root_relative_to_work=root.relative_to(work).as_posix(), shader_list=str(shader_list),
                    shader_list_relative_to_work=shader_list.relative_to(work).as_posix(),
                    learned_caches=selected, expected_chain=expected_chain, entries=entries,
                    metadata_rows=metadata_rows, row_count_basis='nonempty non-comment metadata lines; not compiled work',
                    files=sum(entry['kind'] == 'file' for entry in entries.values()),
                    bytes=sum(entry['bytes'] for entry in entries.values()))
    snapshot['content_sha256'] = token(content_inventory(snapshot))
    snapshot['stat_sha256'] = token({name: entry['stat'] for name, entry in entries.items()})
    return snapshot


def remap_inputs(snapshot, cloned_work):
    if snapshot is None:
        return None, ()
    clone = Path(cloned_work).expanduser().resolve(strict=True)
    source = Path(snapshot['work'])
    require(clone.is_dir() and not clone.is_relative_to(source) and not source.is_relative_to(clone),
            'Cloned work must not overlap the original work')
    def mapped(relative):
        path = PurePosixPath(relative)
        require(not path.is_absolute() and '..' not in path.parts, 'Invalid recorded input path')
        return clone / path
    return mapped(snapshot['shader_list_relative_to_work']), tuple(
        mapped(cache['relative_to_work']) for cache in snapshot['learned_caches'])


def verify_unchanged(snapshot):
    if snapshot is not None:
        current = capture_inputs(snapshot['work'], snapshot['shader_list'],
                                 [cache['path'] for cache in snapshot['learned_caches']], snapshot['expected_chain'])
        require(current == snapshot, 'Original preparation inputs changed')


def verify_cloned_inputs(snapshot, cloned_work):
    if snapshot is None:
        return None
    shader_list, caches = remap_inputs(snapshot, cloned_work)
    clone = capture_inputs(cloned_work, shader_list, caches, snapshot['expected_chain'])
    require(content_inventory(clone) == content_inventory(snapshot)
            and clone['content_sha256'] == snapshot['content_sha256'], 'Cloned preparation inputs differ')
    original_files = {tuple(entry['stat'][:2]) for entry in snapshot['entries'].values() if entry['kind'] == 'file'}
    require(not any(tuple(entry['stat'][:2]) in original_files for entry in clone['entries'].values()
                    if entry['kind'] == 'file'), 'Clone shares original input file identities')
    return clone
