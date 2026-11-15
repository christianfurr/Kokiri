#!/usr/bin/env python3
"""Prepare a Switch 2 game's shader seed for its app (build_app.py; docs/ns2-port.md): the same folder Tears of the
Kingdom's prepare_shader_seed.py writes (build/shader-seed/<version>: *.variants, *_b.metal, *_b.json, shader-keys.json,
seed-manifest.json), so the app's shader steps take it as they are (step_shader_libs, shader_bundle, resolve_lists,
mac_pipelines).

scripts/ns2_shader_corpus.py reads Nintendo's BNSH/BAHS/NDVE resources (OOT: Shader, Lib, Effect, Layout2Shader and Movie),
its modules and, for Koei Tecmo games, LINKDATA and the listed RDB shaders. The game's seed-shaders mode translates each through the
runtime itself (totk_rt_variant), so keys and variant names are the runtime's own: the default bind state for every
shader, and every bind state the game's shared shader list (games/<game>/assets/shader_list.tsv) names, with the answers
a build gives that row. The translations go into a cache kept in the work folder (build/ns2-seed-cache/<version>), so
a rebuild translates only what changed; the seed is that cache's translations, checked and listed in its manifest.

The output is game-derived data: it belongs in the work folder, never in the repository.

  prepare_ns2_seed.py --version oot --depth-mode minus-w --binary ../build/oot-native
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import struct
import subprocess
import sys
import time

sys.path.insert(0, str(Path(__file__).resolve().parent))
from prepare_shader_seed import CHAIN, shader_key_scope, record_verified   # noqa: E402
from shader_list import canonical, listed_answers
from ns2_shader_corpus import CORPUS_MAGIC, shader_key

VARIANTS = re.compile(r'^[0-9a-f]{64}\.variants$')
VARIANT = re.compile(r'^[0-9a-f]{64}-[0-9a-f]{12}$')


def sha256(path):
    h = hashlib.sha256()
    with open(path, 'rb') as f:
        for block in iter(lambda: f.read(1 << 20), b''):
            h.update(block)
    return h.hexdigest()


def translation_context(translator, depth_mode):
    """The cache folder: what decides every translation at once, the chain, the device depth mode and the translator (its
    spirv-cross runs inside it, TOTK_XLATE_SPIRV_CROSS=inproc). Not the runtime code that makes the requests: each
    translation keeps the request it was made from (totk_shader_rt.m variant_request, its index entry's "request"), and a
    seed run of another runtime keeps those it would ask for the same way and makes only the others again
    (TOTK_SEED_VERIFY, seed_verified; user 2026-11-11: "如何让 快速更新 不要这么容易失效"). Until then the source of the
    request functions counted, and removing a fallback for starting the translator (4b308d25) made all 42,891 translate again.

    The shader/bind-state key alone does not describe device depth mode. The old unversioned seed cache kept vertex
    shaders made with near=0 after the runtime was corrected to NVN's near=-w default.
    """
    inputs = dict(schema=3, chain=CHAIN, depth_mode=depth_mode, translator_sha256=sha256(translator))
    return hashlib.sha256(json.dumps(inputs, sort_keys=True, separators=(',', ':')).encode()).hexdigest()


def run(cmd, log, env=None):
    with open(log, 'w') as out:
        r = subprocess.run([str(c) for c in cmd], stdout=out, stderr=subprocess.STDOUT, env=env)
    if r.returncode:
        raise SystemExit(f'{Path(str(cmd[0])).name} failed ({r.returncode}); see {log}')


def parallel_sha256(paths, jobs=None):
    """name -> sha256 with bounded I/O concurrency after translation."""
    import concurrent.futures
    with concurrent.futures.ThreadPoolExecutor(min(2, jobs or 2)) as pool:
        return dict(zip((p.name for p in paths), pool.map(sha256, paths)))


def publish_digests(paths, seed, hash_all):
    """name -> SHA-256 of the seed about to be published, and how many files were read for it. A file that is still the
    cache file the last published seed had (same device, inode, size and modification time in that seed's .verified.json,
    record_verified) keeps the digest recorded then; every other one is read (hash_all). The change time is not compared:
    linking a cache file into the new seed changes its inode's. A translation made again is a new file, and an index this
    run writes is new too (user 2026-11-11 "极速更新": hashing all 250,000 files took 3 minutes of every update)."""
    known = {}
    try:
        record = json.loads(seed.with_name(seed.name + '.verified.json').read_text())
        if record.get('schema') == 1 and isinstance(record.get('files'), dict):
            known = record['files']
    except (OSError, ValueError):
        pass
    out, todo = {}, []
    for path in paths:
        entry = known.get(path.name)
        try:
            st = path.stat()
        except OSError:
            todo.append(path)
            continue
        if isinstance(entry, list) and len(entry) == 6 and entry[:4] == [st.st_dev, st.st_ino, st.st_size, st.st_mtime_ns]:
            out[path.name] = entry[5]
        else:
            todo.append(path)
    out.update(hash_all(todo))
    return out, len(todo)


GENERATED = {'shader-keys.json', 'pso_title.tsv', 'pso_manifest.tsv'}   # written by the publish itself, from the inputs


def seed_unchanged(out, files, inputs):
    """Whether the published seed already is this one: made from the same inputs (translator, chain, depth mode, game
    files, shader list, corpus and the scripts that write it), and every translation and index file is the very file it has
    (same device and inode: a translation made again, or an index this run writes, is another file). Then it is kept as it
    is, without new links, digests or manifest, so the shader data bundle made from it is kept too (user 2026-11-11 "极速
    更新": publishing an unchanged seed took 3 minutes, and its new manifest had the bundle signed again, 3 more)."""
    try:
        old = json.loads((out / 'seed-manifest.json').read_text())
        if old.get('inputs') != inputs:
            return False
        names = set(old.get('files', {}))
        if not set(files) <= names or not names - set(files) <= GENERATED:
            return False
        for name, src in files.items():
            a, b = (out / name).stat(), src.stat()
            if (a.st_dev, a.st_ino) != (b.st_dev, b.st_ino):
                return False
        return True
    except (OSError, ValueError, AttributeError):
        return False


def seed_files(cache, verified=None, jobs=2, shader_keys=None):
    """name -> path for the translations of the seed cache: each shader's index and the variants it lists; with verified
    (the variants the seed run checked against its runtime's requests or made), only those, and indexes -> the entries left
    of each shader's index (written into the seed in place of the cache's file)."""
    files, checks, indexes = {}, [], {}
    indexes_to_read = (cache.glob('*.variants') if shader_keys is None else
                       (cache/(key+'.variants') for key in sorted(shader_keys)))
    for index in sorted(indexes_to_read):
        if not VARIANTS.match(index.name):
            continue
        try:
            entries = json.loads(index.read_text())
        except (OSError, ValueError):
            continue
        kept = []
        for entry in entries if isinstance(entries, list) else []:
            name = entry.get('variant') if isinstance(entry, dict) else None
            if not isinstance(name, str) or not VARIANT.match(name):
                continue
            if name[:64] != index.stem:
                raise ValueError(f'seed index refers to another shader: {index}')
            if verified is not None and name not in verified:
                continue
            metal, refl = cache / f'{name}_b.metal', cache / f'{name}_b.json'
            if metal.is_file() and metal.stat().st_size and refl.is_file():
                checks.append((name, refl))
                files[metal.name], files[refl.name] = metal, refl
                kept.append(entry)
        if kept:
            files[index.name] = index
            if verified is not None and len(kept) != len(entries):
                indexes[index.name] = kept
    # The reflections are checked on all cores (42,845 JSON files; one thread read them for minutes).
    def check(item):
        name, refl = item
        reflection = json.loads(refl.read_text())
        if reflection.get('chain') != CHAIN or reflection.get('key') != name + '_b' or not reflection.get('entry'):
            raise ValueError(f'invalid seed reflection: {refl}')
    import concurrent.futures
    with concurrent.futures.ThreadPoolExecutor(min(2, jobs)) as pool:
        for _ in pool.map(check, checks):
            pass
    return (files, indexes) if verified is not None else files


def corpus_records(path):
    """Yield one original record at a time; never retain the full binary corpus."""
    seen = set()
    with Path(path).open('rb') as stream:
        header = stream.read(12)
        if len(header) != 12 or header[:8] != CORPUS_MAGIC:
            raise ValueError('invalid shader corpus')
        count, = struct.unpack('<I', header[8:])
        for _ in range(count):
            head = stream.read(14)
            if len(head) != 14:
                raise ValueError('truncated shader corpus header')
            st, cn, kn, ln = struct.unpack('<IIIH', head)
            label = stream.read(ln)
            control, code = stream.read(cn), stream.read(kn)
            if len(label) != ln or len(control) != cn or len(code) != kn:
                raise ValueError('truncated shader corpus')
            key = shader_key(control, code)
            if key in seen:
                raise ValueError('duplicate shader in corpus: ' + key)
            seen.add(key)
            yield key, st, label.decode(), head + label + control + code
        if stream.read(1) or not count:
            raise ValueError('empty corpus or trailing bytes')


def corpus_inventory(path):
    """Check actual records, not the runtime's queue count."""
    return {key: dict(stage=stage, source=label) for key, stage, label, _ in corpus_records(path)}


def corpus_subset(path, keys, out):
    """The corpus records of these shaders, written to out in the same form (a quick build's seed translates only them:
    --only). Returns how many there are; a key the corpus does not hold is left out, as the full seed would have it."""
    out = Path(out)
    count = 0
    with out.open('wb') as target:
        target.write(CORPUS_MAGIC + struct.pack('<I', 0))
        for key, _, _, raw in corpus_records(path):
            if key in keys:
                target.write(raw)
                count += 1
        target.seek(8)
        target.write(struct.pack('<I', count))
    if not count:
        raise ValueError('none of the --only shaders is in the corpus')
    return count


def listed_request_count(rows):
    """Count the nondefault requests runtime_shader_seed will make, including repeats."""
    empty = '{"attr":{},"fout":{},"img":{},"tex":{}}'
    count = 0
    for line in rows:
        fields = line.split('\t')
        if len(fields) != 3 or fields[0] != 'V' or canonical(json.loads(fields[2])) is None:
            raise ValueError('invalid recorded shader binding row')
        if listed_answers(fields[2]) != empty:
            count += 1
    return count


def source_listed_requests(shader_list, inventory):
    """Census the original source independently of any partition's filtering."""
    if not shader_list:
        return 0
    rows = []
    for line in Path(shader_list).read_text().splitlines():
        if not line.startswith('V\t'):
            continue
        fields = line.split('\t')
        if len(fields) != 3 or not re.fullmatch('[0-9a-f]{64}', fields[1]):
            raise ValueError('invalid recorded shader binding row')
        if fields[1] in inventory:
            rows.append(line)
    return listed_request_count(rows)


def partition_corpus(path, folder, batch_size=500, shader_list=None):
    """Bound each process by defaults plus all supplied V rows, conservatively.

    The runtime ignores default-equivalent V rows. Counting those too gives an
    upper bound without reproducing or inventing its binding answers.
    """
    if not 1 <= batch_size <= 500:
        raise ValueError('batch size must be between 1 and 500 known requests')
    listed = {}
    if shader_list:
        for line in Path(shader_list).read_text().splitlines():
            if not line.startswith('V\t'):
                continue
            fields = line.split('\t')
            if (len(fields) != 3 or not re.fullmatch('[0-9a-f]{64}', fields[1]) or
                not isinstance(json.loads(fields[2]), dict)):
                raise ValueError('invalid recorded shader binding row')
            listed.setdefault(fields[1], []).append(line)
    folder = Path(folder)
    folder.mkdir(parents=True, exist_ok=False)
    chunks, keys, rows, requests, output = [], [], [], 0, None

    def finish():
        output.seek(8)
        output.write(struct.pack('<I', len(keys)))
        output.close()
        corpus = folder/f'batch-{len(chunks):04d}.bin'
        partial.replace(corpus)
        list_path = folder/f'batch-{len(chunks):04d}.tsv' if shader_list else None
        if list_path:
            list_path.write_text(''.join(line+'\n' for line in rows))
        chunks.append(dict(corpus=str(corpus.resolve()), corpus_sha256=sha256(corpus),
                           list=str(list_path.resolve()) if list_path else None,
                           list_sha256=sha256(list_path) if list_path else None,
                           keys=list(keys), known_requests=requests, listed_rows=len(rows),
                           listed_requests=listed_request_count(rows)))

    try:
        for key, _, _, raw in corpus_records(path):
            weight = 1 + len(listed.get(key, []))
            if weight > batch_size:
                raise ValueError(f'shader {key} exceeds the {batch_size}-request batch bound')
            if keys and requests + weight > batch_size:
                finish()
                keys, rows, requests, output = [], [], 0, None
            if output is None:
                partial = folder/f'batch-{len(chunks):04d}.partial'
                output = partial.open('wb')
                output.write(CORPUS_MAGIC + struct.pack('<I', 0))
            output.write(raw)
            keys.append(key)
            rows.extend(listed.get(key, []))
            requests += weight
        if keys:
            finish()
    finally:
        if output is not None and not output.closed:
            output.close()
    return chunks


def batch_completion(text, keys, verified, has_list=False, returncode=0, *, expected_listed_requests=0):
    """Accept only actual native reports paired with this process's verified set."""
    if returncode:
        raise ValueError(f'seed batch exited with {returncode}')
    done = re.findall(r'\[seed\] done in \d+ s: (\d+) of (\d+) shaders', text)
    checked = re.findall(r'\[seed\] requests checked: (\d+) variants for this runtime, (\d+) cached ones kept, (\d+) made again', text)
    listed = re.findall(r"the shader list's bind states: (\d+) of (\d+) translated", text)
    if len(done) != 1 or len(checked) != 1 or (has_list and len(listed) != 1):
        raise ValueError('seed batch lacks unambiguous native completion reports')
    completed, asked = map(int, done[0])
    variants, kept, made_again = map(int, checked[0])
    listed_done, listed_asked = map(int, listed[0]) if listed else (0, 0)
    if completed != len(keys) or asked != len(keys):
        raise ValueError('incomplete shader seed batch defaults')
    if listed_asked != expected_listed_requests:
        raise ValueError('native listed request population differs from the source binding plan')
    if listed_done != listed_asked:
        raise ValueError('incomplete listed shader variants in batch')
    if (not verified or any(not VARIANT.fullmatch(name) for name in verified) or
        {name[:64] for name in verified} != set(keys) or variants != len(verified) or kept > variants):
        raise ValueError('seed batch verified set differs from its requests or corpus')
    return dict(keys=list(keys), translated_default=completed, corpus_shaders=asked,
                listed_variants=listed_done, listed_asked=listed_asked,
                listed_requests=expected_listed_requests,
                checked_variants=variants, cached_kept=kept, made_again=made_again)


def aggregate_batches(inventory, batches, verified, *, expected_listed_requests=0):
    seen = set()
    fields = ('translated_default', 'corpus_shaders', 'listed_variants', 'listed_asked', 'listed_requests',
              'checked_variants', 'cached_kept', 'made_again')
    total = dict.fromkeys(fields, 0)
    for batch in batches:
        keys = set(batch['keys'])
        if seen & keys or not keys or batch['translated_default'] != len(keys) or batch['corpus_shaders'] != len(keys):
            raise ValueError('duplicate or incomplete shader batch')
        if batch['listed_variants'] != batch['listed_asked'] or batch['listed_asked'] != batch['listed_requests']:
            raise ValueError('incomplete listed shader variants in batch')
        seen.update(keys)
        for field in fields:
            total[field] += batch[field]
    if (seen != set(inventory) or {name[:64] for name in verified} != set(inventory) or
        total['checked_variants'] != len(verified)):
        raise ValueError('incomplete shader batches: full corpus and verified coverage required')
    if total['listed_asked'] != expected_listed_requests:
        raise ValueError('aggregate listed requests differ from the source binding plan')
    return total


def atomic_json(path, report):
    partial = path.with_suffix('.partial')
    partial.write_text(json.dumps(report, indent=2)+'\n')
    partial.replace(path)


def only_keys(path):
    """The 64-hex shader keys of an --only file, one per line."""
    keys = {line.strip() for line in Path(path).read_text().splitlines() if line.strip()}
    bad = [k for k in keys if not re.fullmatch('[0-9a-f]{64}', k)]
    if bad or not keys:
        raise ValueError(f'{path}: not a list of shader keys' + (f' ({bad[0]})' if bad else ' (empty)'))
    return keys


def require_complete(inventory, keys, done, listed=None):
    missing = sorted(inventory.keys() - set(keys))
    if missing or not done or int(done.group(1)) != len(inventory) or int(done.group(2)) != len(inventory):
        raise ValueError(f'incomplete shader seed: {len(inventory) - len(missing)}/{len(inventory)} keys; '
                         f'{len(missing)} missing (including skipped stages)')
    if listed and listed.group(1) != listed.group(2):
        raise ValueError(f'incomplete listed shader variants: {listed.group(1)} of {listed.group(2)} bind states translated')


def main():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument('--version', required=True, help='the game folder name (oot)')
    p.add_argument('--depth-mode', choices=('minus-w', 'zero'), required=True, help="the game's observed NVN device depth mode")
    p.add_argument('--binary', type=Path, required=True, help="the game's binary (build/totk-native-<version>)")
    p.add_argument('--translator', type=Path, default=Path('build/shader-service/totk_xlate'),
                   help='source-verified serviced translator installed by engine/build.py')
    p.add_argument('--list', type=Path, help="optional recorded bind states; OOT always extracts all resource shaders")
    p.add_argument('--jobs', type=int, default=2, help='bounded extraction/translation concurrency')
    p.add_argument('--batch-size', type=int, default=500,
                   help='maximum known default plus recorded binding requests per process (1-500)')
    p.add_argument('--max-batches', type=int, help='bounded pilot; incomplete coverage exits 2 without publishing a seed')
    p.add_argument('--output', type=Path, help='default build/shader-seed/<version>')
    p.add_argument('--logs', type=Path, default=Path('logs'))
    p.add_argument('--only', type=Path, help='translate only these shaders (one 64-hex key per line): a quick build\'s '
                   'seed (games/oot/build.py, the title rows\' shaders); the game translates the rest at first use')
    a = p.parse_args()
    if not 1 <= a.jobs <= 32:
        p.error('--jobs must be between 1 and 32')
    if not 1 <= a.batch_size <= 500:
        p.error('--batch-size must be between 1 and 500 known requests')
    if a.max_batches is not None and a.max_batches < 1:
        p.error('--max-batches must be positive')
    a.binary = a.binary.resolve()
    v = a.version
    out = a.output or Path(f'build/shader-seed/{v}')
    romfs, elf = Path(f'extracted/{v}/romfs'), Path(f'extracted/{v}/elf')
    corpus, cache = Path(f'build/ns2-corpus/{v}.bin'), Path(f'build/ns2-seed-cache/{v}')
    a.logs.mkdir(parents=True, exist_ok=True)
    t0 = time.time()
    romfs_sha = json.loads((romfs / 'index.json').read_text())['romfs_sha256']

    stamp = corpus.with_suffix('.json')   # the corpus is made again only for other game files
    want = {'romfs_sha256': romfs_sha, 'modules': {e.name: sha256(e) for e in sorted(elf.glob('*.elf'))},
            'tool': sha256(Path(__file__).resolve().parent / 'ns2_shader_corpus.py'), 'list': sha256(a.list) if a.list else None}
    if not corpus.is_file() or not stamp.is_file() or json.loads(stamp.read_text()) != want:
        corpus.parent.mkdir(parents=True, exist_ok=True)
        run([sys.executable, Path(__file__).resolve().parent / 'ns2_shader_corpus.py', '--romfs', romfs,
             '--modules', *sorted(elf.glob('*.elf')), '--out', corpus, '--jobs', a.jobs,
             *(['--listed', a.list] if a.list else [])], a.logs / f'ns2-corpus-{v}.log')
        stamp.write_text(json.dumps(want))

    full_corpus, seed_list = corpus, a.list
    only = only_keys(a.only) if a.only else None
    if only:   # the corpus and the list cut to these shaders; the full corpus stays as it is (its stamp), for the next build
        corpus = corpus.with_name(f'{v}-only.bin')
        print(f'quick seed: {corpus_subset(full_corpus, only, corpus)} of the {len(only)} shaders asked for are in the corpus', flush=True)
        if a.list:
            from shader_list import ShaderList
            seed_list = corpus.with_name(f'{v}-only-list.tsv')
            ShaderList.load(a.list).only(only).save(seed_list)

    prebuilt = a.translator.resolve()
    if not prebuilt.is_file():
        raise ValueError('missing source-built shader translator: ' + str(prebuilt))
    context = translation_context(prebuilt, a.depth_mode)
    cache = cache / context
    cache.mkdir(parents=True, exist_ok=True)
    # A concurrent App package may replace the shared build/shader-service binary.
    # This preparation uses its own immutable copy, named by the translation context.
    native = cache / 'tool/build'
    service = native / 'shader-service/totk_xlate'
    if not service.is_file() or sha256(service) != sha256(prebuilt):
        service.parent.mkdir(parents=True, exist_ok=True)
        # A new file, never written over the old one: macOS keeps the code signature it checked for a file it ran, and a
        # program overwritten in place is then killed at launch (SIGKILL, Code Signature Invalid; 2026-11-03).
        service.unlink(missing_ok=True)
        shutil.copy2(prebuilt, service)
    sys.path.insert(0, str(Path(__file__).resolve().parent / 'dev'))
    from game_slot import GameSlot
    os.environ.setdefault('TOTK_GAME_SLOT_DIR', str(Path.home() / 'Library/Application Support/MacNativeGames/TOTK/game-slot'))
    env = {k: value for k, value in os.environ.items() if k not in ('TOTK_SHADER_XLATE', 'TOTK_SHADER_DEBUGMODE')}
    env.update(TOTK_SHADER_CACHE=str(cache.resolve()), TOTK_SEED_DEPTH_MODE=a.depth_mode,
               TOTK_NATIVE_DIR=str(native.resolve()), TOTK_SHADER_SEED='off', TOTK_RT_BG_WORKERS=str(a.jobs),
               TOTK_SHADER_SERVICE='native', TOTK_XLATE_SPIRV_CROSS='inproc',
               TOTK_SEED_VERIFY='1')
    batch_dir = a.logs/f'ns2-seed-{v}-batches-{time.time_ns()}'
    inventory = corpus_inventory(corpus)
    source_listed_total = source_listed_requests(seed_list, inventory)
    batches = partition_corpus(corpus, batch_dir, a.batch_size, seed_list)
    if sum(batch['listed_requests'] for batch in batches) != source_listed_total:
        raise ValueError('partition listed requests differ from the original source binding plan')
    progress_path = batch_dir/'progress.json'
    progress = dict(schema=1, status='incomplete', corpus_sha256=sha256(corpus),
                    runtime_sha256=sha256(a.binary), translator_sha256=sha256(prebuilt),
                    translation_context_sha256=context, batch_size=a.batch_size, jobs=a.jobs,
                    planned_batches=len(batches), corpus_shaders=len(inventory),
                    known_requests=sum(batch['known_requests'] for batch in batches), batches=[])
    progress['listed_requests'] = source_listed_total
    atomic_json(progress_path, progress)
    print(f"seed batches: {len(batches)}, at most {a.batch_size} known requests per process; progress {progress_path}", flush=True)
    verified = set()
    with GameSlot(owner='build', purpose=f'{v}: complete offline shader translation', expect_seconds=1200) as slot:
        for number, batch in enumerate(batches):
            if a.max_batches is not None and number >= a.max_batches:
                break
            log = batch_dir/f'batch-{number:04d}.log'
            verified_list = (batch_dir/f'batch-{number:04d}-verified.txt').resolve()
            batch_env = dict(env, TOTK_SEED_VERIFIED_OUT=str(verified_list))
            try:
                with log.open('w') as output:
                    result = slot.popen([str(a.binary), f'rewritten/{v}', 'seed-shaders', batch['corpus'],
                                         *([batch['list']] if batch['list'] else [])], env=batch_env,
                                        stdout=output, stderr=subprocess.STDOUT).wait()
                checked = set(verified_list.read_text().split()) if verified_list.is_file() else set()
                report = batch_completion(log.read_text(errors='replace'), batch['keys'], checked,
                                          bool(batch['list']), result,
                                          expected_listed_requests=batch['listed_requests'])
                if report['corpus_shaders']+report['listed_asked'] > batch['known_requests']:
                    raise ValueError('native batch requested more than the planned bound')
                outputs, _ = seed_files(cache, checked, a.jobs, batch['keys'])
                if {name[:-len('.variants')] for name in outputs if name.endswith('.variants')} != set(batch['keys']):
                    raise ValueError('verified batch cache outputs are incomplete')
                if {name[:-len('_b.metal')] for name in outputs if name.endswith('_b.metal')} != checked:
                    raise ValueError('verified batch variants are missing cached outputs')
                report.update(corpus_sha256=batch['corpus_sha256'], list_sha256=batch['list_sha256'],
                              known_requests=batch['known_requests'], log=str(log.resolve()),
                              log_sha256=sha256(log), verified_sha256=sha256(verified_list),
                              output_sha256=parallel_sha256(list(outputs.values()), a.jobs))
                verified.update(checked)
                progress['batches'].append(report)
                atomic_json(progress_path, progress)
                print(f"seed batch {number+1}/{len(batches)}: {report['translated_default']} defaults, "
                      f"{report['listed_variants']}/{report['listed_asked']} listed; "
                      f"{report['cached_kept']} verified cached variants", flush=True)
            except (OSError, ValueError) as error:
                progress.update(status='failed', failed_batch=number, error=str(error), log=str(log.resolve()))
                atomic_json(progress_path, progress)
                raise
    if len(progress['batches']) != len(batches):
        print(f'partial seed pilot: {len(progress["batches"])}/{len(batches)} batches checked; no full seed published; {progress_path}', flush=True)
        raise SystemExit(2)
    totals = aggregate_batches(inventory, progress['batches'], verified,
                               expected_listed_requests=progress['listed_requests'])
    progress.update(status='complete', totals=totals)
    atomic_json(progress_path, progress)
    files, indexes = seed_files(cache, verified, a.jobs)
    keys = sorted(n[:-len('.variants')] for n in files if n.endswith('.variants'))
    missing = {k: inventory[k] for k in sorted(inventory.keys() - set(keys))}
    (a.logs / f'ns2-seed-{v}-missing.json').write_text(json.dumps(missing, indent=2) + '\n')
    if missing:
        raise ValueError('verified full seed has missing cached shader keys')
    shaders = sum(n.endswith('_b.metal') for n in files)
    here = Path(__file__).resolve().parent
    inputs = dict(chain=CHAIN, version=v, source_romfs_sha256=romfs_sha, translation_context_sha256=context,
                  nvn_depth_mode=a.depth_mode, translator_sha256=sha256(prebuilt),
                  shader_list_sha256=sha256(a.list) if a.list else None, corpus_sha256=sha256(corpus),
                  scripts_sha256={n: sha256(here / n) for n in ('prepare_ns2_seed.py', 'prepare_shader_seed.py', 'shader_list.py')},
                  only_sha256=sha256(a.only) if only else None)
    if not indexes and seed_unchanged(out, files, inputs):
        print(f'seed unchanged: its {len(files)} translation files are the ones published, from the same inputs; '
              'kept as it is (no new links, digests or manifest)', flush=True)
        return
    staging = out.with_name(out.name + '.partial')
    shutil.rmtree(staging, ignore_errors=True)
    staging.mkdir(parents=True)
    for name, src in files.items():
        if name in indexes:   # only the variants this run checked or made
            (staging / name).write_text(json.dumps(indexes[name], sort_keys=True, separators=(',', ':'), ensure_ascii=False))
            continue
        os.link(src, staging / name) if src.stat().st_dev == staging.stat().st_dev else shutil.copy2(src, staging / name)
    # every shader of the game, also the ones a quick seed leaves out: the runtime takes the scope as the game's shaders
    # (totk_rt_note_set writes a shader outside it into the player's contribution file as new)
    scope = shader_key_scope(sorted(corpus_inventory(full_corpus)) if only else keys, v, romfs_sha)
    (staging / 'shader-keys.json').write_text(json.dumps(scope, separators=(',', ':')) + '\n')
    # Unlike the shaders, a complete render-pipeline description needs the game's bind state: the warm-up lists come from
    # the shared list's recorded rows (S / C / R / B / T), each variant named as this seed serves it (shader_list.py
    # resolve, as the TOTK packaging's resolve_lists). Without a list the file only says so (never invent descriptors).
    if a.list:
        sys.path.insert(0, str(Path(__file__).resolve().parent))
        from shader_list import ShaderList, EXPORT, list_name
        lst = ShaderList.load(a.list)
        title, counts_t = lst.resolve(staging, 't')
        rest, counts_m = lst.resolve(staging, 'm', given=title)
        for name, rows, counts in (('pso_title.tsv', title, counts_t), ('pso_manifest.tsv', rest, counts_m)):
            (staging / name).write_text(EXPORT.format(list_name(a.list)) + ''.join('\t'.join(row) + '\n' for row in rows))
            print(f'{name}: {len(rows)} warm rows; left out {counts["other"]} of other versions, {counts["missing"]} the seed cannot build, '
                  f'{counts["renamed"]} renamed to the seed\'s variants', flush=True)
    else:
        (staging / 'pso_manifest.tsv').write_text('# NS2 startup shaders; render pipelines come from the shared list.\n')
    report = dict(schema=1, chain=CHAIN, version=v, game=v, source_romfs_sha256=romfs_sha,
                  translation_context_sha256=context,
                  nvn_depth_mode=a.depth_mode,
                  runtime_sha256=sha256(a.binary), translator_sha256=sha256(prebuilt),
                  shader_list_sha256=sha256(a.list) if a.list else None,
                  corpus_sha256=sha256(corpus), corpus_inputs=want, all_default=True,
                  only=len(only) if only else None,   # a quick seed: only these shaders (the rest translated at first use)
                  stages={str(st): sum(x['stage'] == st for x in inventory.values()) for st in range(6)},
                  preparation_sha256=sha256(Path(__file__).resolve()), shaders=shaders,
                  corpus_shaders=totals['corpus_shaders'], translated_default=totals['translated_default'],
                  listed_variants=totals['listed_variants'], listed_asked=totals['listed_asked'],
                  batch_receipts=progress,
                  seconds=round(time.time() - t0, 1), inputs=inputs, files={})
    report['files'], read = publish_digests(sorted(staging.iterdir()), out, lambda paths: parallel_sha256(paths, a.jobs))
    print(f'seed files: {len(report["files"])}, {read} read again (the rest kept the digest of the last seed)', flush=True)
    (staging / 'seed-manifest.json').write_text(json.dumps(report, indent=2) + '\n')
    # Publish first; deleting tens of thousands of old files on an external APFS volume takes minutes. The old seed
    # is entirely generated data and no longer read once its replacement is published.
    old = out.with_name(f'.{out.name}.old-{os.getpid()}-{time.time_ns()}')
    if out.exists(): out.rename(old)
    try:
        staging.rename(out)
    except OSError:
        if old.exists(): old.rename(out)
        raise
    if old.exists(): subprocess.Popen(['/bin/rm', '-rf', str(old)], start_new_session=True)
    record_verified(out, report['files'])
    print(json.dumps({k: report[k] for k in ('version', 'shaders', 'corpus_shaders', 'translated_default',
                                             'listed_variants', 'listed_asked', 'seconds')}))


if __name__ == '__main__':
    main()
