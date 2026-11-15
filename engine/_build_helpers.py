"""OoT-only packaging helpers adapted from MacNativeGames 3edfb0b (MIT).

Only the dependency closure used by this engine is retained. Generated game
payloads and build output remain outside the source repository.
"""
import glob
import hashlib
import json
import os
from pathlib import Path
import plistlib
import shutil
import subprocess
import sys
import threading
import time

REPO = Path(__file__).resolve().parent.parent
ENGINE = Path(__file__).resolve().parent
VERSIONS = {'oot': json.loads((ENGINE / 'assets/expected-v131072.json').read_text())}
APPS = {'oot': ('Kokiri Game', 'com.christianfurr.kokiri.runtime', 'OcarinaOfTime')}
BUNDLE_ID = 'com.christianfurr.kokiri.runtime'
PAR_SCHEMA = 6
SHADER_DATA = ('shader-seed', 'shader-libs')
WORK_FOLDERS = 'Kokiri-work'
_libc = None

class BuildError(Exception):
    pass

def say(msg):
    print(f'[{time.strftime("%H:%M:%S")}] {msg}', flush=True)

def run(cmd, log, cwd=None, env=None, quiet=True):
    """Run a step with its whole output in log; on failure show the end of it. quiet: a line a minute instead of the output."""
    cmd = [str(c) for c in cmd]
    log.parent.mkdir(parents=True, exist_ok=True)
    done = threading.Event()

    def beat():
        t0 = time.time()
        while not done.wait(60):
            say(f'   ... still running ({(time.time() - t0) / 60:.0f} min)')
    if quiet:
        threading.Thread(target=beat, daemon=True).start()
    try:
        with open(log, 'w') as f:
            p = subprocess.run(cmd, cwd=cwd, env=env, stdout=f, stderr=subprocess.STDOUT)
    finally:
        done.set()
    if p.returncode:
        tail = log.read_text(errors='replace').splitlines()[-25:]
        raise BuildError(f'{Path(cmd[1] if Path(cmd[0]).name.startswith("python") else cmd[0]).name} failed (exit {p.returncode}); '
                         f'full output: {log}\n' + '\n'.join(tail))

def sha256(path):
    h = hashlib.sha256()
    with open(path, 'rb') as f:
        while chunk := f.read(8 << 20):
            h.update(chunk)
    return h.hexdigest()

def seed_digests(seed):
    """name -> SHA-256 for the seed files whose identity (device, inode, size, modification and change time) is still the
    one prepare_shader_seed.py recorded when it checked them (<seed>.verified.json, its verified_digests). Hashing all
    65,436 files in each packaging took tens of seconds (2026-10-21); a changed file is hashed as before."""
    try:
        record = json.loads(seed.with_name(seed.name + '.verified.json').read_text())
        if record.get('schema') != 1:
            return {}
        known = {}
        for name, entry in record['files'].items():
            try:
                s = os.stat(seed / name)
            except OSError:
                continue
            if Path(name).name == name and entry[:-1] == [s.st_dev, s.st_ino, s.st_size, s.st_mtime_ns, s.st_ctime_ns]:
                known[name] = entry[-1]
        return known
    except (OSError, ValueError, KeyError, TypeError, AttributeError):
        return {}

def seed_sha256(seed, name, known):
    return known.get(name) or sha256(seed / name)

def link(path, target):
    if path.is_symlink() or path.exists():
        if path.is_symlink() and path.resolve() == Path(target).resolve():
            return
        path.unlink() if path.is_symlink() else shutil.rmtree(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.symlink_to(target)

def app_game_data(app, version):
    """The game data bundle the app at `app` carries for version (data_bundle), or None."""
    return Path(app) / f'Contents/Helpers/GameData-{version}.bundle' if app else None

def clonefile(src, dst):
    """macOS clonefile(2): an APFS clone of a file or a whole folder (no extra space) in one call, without starting a
    program for it (an app holds about 50,000 shader files per version: one cp each took minutes, 2026-10-19). False
    when it cannot: another volume or file system, or dst exists."""
    global _libc
    if _libc is None:
        import ctypes
        _libc = ctypes.CDLL(None, use_errno=True)
        _libc.clonefile.argtypes = [ctypes.c_char_p, ctypes.c_char_p, ctypes.c_uint32]
    return _libc.clonefile(os.fsencode(src), os.fsencode(dst), 0) == 0

def clone(src, dst):
    """APFS clone when on the same volume (no extra space), else a copy; an existing dst is replaced."""
    dst.parent.mkdir(parents=True, exist_ok=True)
    if dst.exists() or dst.is_symlink():
        dst.unlink()
    if not clonefile(src, dst):
        if Path(src).name == 'romfs.bin':
            raise BuildError('the game image requires an APFS clone; no full-image copy was attempted')
        shutil.copy2(src, dst)

def copy_tree(src, dst):
    """The files of src in dst: one clone of the whole folder when dst does not exist yet, else file by file."""
    if not dst.exists():
        dst.parent.mkdir(parents=True, exist_ok=True)
        if clonefile(src, dst):
            return
    for p in sorted(src.rglob('*')):
        if p.is_file():
            clone(p, dst / p.relative_to(src))

def remove_tree(path):
    """Remove a bundle. Finder can put .DS_Store back while it is being deleted, which makes the last rmdir fail."""
    for _ in range(5):
        try:
            shutil.rmtree(path)
            return
        except OSError as error:
            if error.errno != 66 or not path.exists():
                raise
            time.sleep(0.2)
    shutil.rmtree(path)

def data_bundle_info(bundle_id, version, display_version=None):
    """The Info.plist of a game data bundle, as data_bundle writes it (an adopted bundle must have the same)."""
    return plistlib.dumps(dict(
        CFBundleIdentifier=f'{bundle_id}.data.{version}', CFBundleName='Game data', CFBundlePackageType='BNDL',
        CFBundleShortVersionString=display_version or VERSIONS[version]['display_version'], CFBundleVersion='1'))

def adoptable_bundle(image, app, version, info):
    """The app's signed game data bundle when the work folder's image was taken from it (adopt_game_data recorded where
    from, its size and modification time) and the bundle is unchanged since and has this build's Info.plist, else None."""
    source = app_game_data(app, version)
    if source is None:
        return None
    try:
        report = json.loads((image.parent / 'index.json').read_text())
        st = (source / 'Contents/Resources/romfs.bin').stat()
        if (report.get('adopted_from') == str(source / 'Contents/Resources/romfs.bin')
                and report.get('adopted_size') == st.st_size and report.get('adopted_mtime_ns') == st.st_mtime_ns
                and (source / 'Contents/_CodeSignature/CodeResources').is_file()
                and (source / 'Contents/Info.plist').read_bytes() == info):
            return source
    except (OSError, ValueError):
        pass
    return None

def data_bundle(tree, version, logs, *, bundle_id=BUNDLE_ID, display_version=None, app=None):
    """The RomFS image (16 GB) as a bundle of its own, signed once and kept in the work folder (build/data-bundles). The
    app carries a clone of it in Contents/Helpers, and the app's seal records only its signature: sealing the image
    inside the app hashed all 16 GB on every packaging (88 s on an M4 Mac mini, 2026-10-20), now only when the image
    changed (the stamp names the image: size, mtime and the SHA-256 the extraction verified, extracted/<version>/romfs/
    index.json). Not its inode, which an APFS clone of the work folder changes: a clone signed all 16 GB again (8 min on
    the external disk, 2026-10-22). The game opens the image through a link at its usual place,
    extracted/<version>/romfs/romfs.bin, and checks its SHA-256 itself as before (runtime/romfs.c)."""
    image = tree / f'extracted/{version}/romfs/romfs.bin'
    bundle = tree / f'build/data-bundles/GameData-{version}.bundle'
    stamp = bundle.with_name(bundle.name + '.json')
    st = image.stat()
    try:
        sha = json.loads((image.parent / 'index.json').read_text()).get('romfs_sha256')
    except (OSError, ValueError):
        sha = None
    want = dict(format=2, size=st.st_size, mtime_ns=st.st_mtime_ns, sha256=sha) if sha else \
        dict(format=1, size=st.st_size, mtime_ns=st.st_mtime_ns, inode=st.st_ino)
    try:
        have = json.loads(stamp.read_text())
        if (bundle / 'Contents/_CodeSignature/CodeResources').is_file():
            if have == want:
                return bundle
            if (want['format'] == 2 and have.get('format') == 1 and have.get('size') == st.st_size
                    and have.get('mtime_ns') == st.st_mtime_ns):   # an older stamp (or a clone's: other inode, same file)
                stamp.write_text(json.dumps(want))
                return bundle
    except (OSError, ValueError):
        pass
    info = data_bundle_info(bundle_id, version, display_version)
    tmp = bundle.with_name(bundle.name + '.partial')
    if tmp.exists():
        shutil.rmtree(tmp)
    source = adoptable_bundle(image, app, version, info)
    if source:   # the image came from this bundle and is the verified one: its signature is this image's
        say(f'4/4 app: the game data bundle is the one {Path(app).name} carries, signed for this same image: not signed again')
        copy_tree(source, tmp)
    else:
        why = ('there is no signed game data bundle in this work folder' if not bundle.exists() else
               'the image changed since the bundle was signed (it was extracted again)')
        say(f'4/4 app: signing the game data once (a minute or two; later builds reuse it): {why}')
        clone(image, tmp / 'Contents/Resources/romfs.bin')
        (tmp / 'Contents/Info.plist').write_bytes(info)
        run(['codesign', '--force', '--sign', '-', tmp], logs / f'sign-data-{version}.log')
        # Checked once here, where the 16 GB are hashed anyway; an app carrying this bundle checks only its own seal (which
        # records this bundle's signature), not --deep (55 s on each packaging, 2026-10-21).
        run(['codesign', '--verify', '--strict', tmp], logs / f'verify-data-{version}.log')
    stamp.unlink(missing_ok=True)
    if bundle.exists():
        shutil.rmtree(bundle)
    tmp.rename(bundle)
    write_stamp = stamp.with_name(stamp.name + '.tmp')
    write_stamp.write_text(json.dumps(want))
    write_stamp.replace(stamp)
    return bundle

def place_data_bundle(bundle, app, res, version):
    """The signed game data in the app (Contents/Helpers), and the link the game opens it by."""
    copy_tree(bundle, app / 'Contents/Helpers' / bundle.name)
    link = res / f'extracted/{version}/romfs/romfs.bin'
    link.parent.mkdir(parents=True, exist_ok=True)
    link.symlink_to(os.path.relpath(app / 'Contents/Helpers' / bundle.name / 'Contents/Resources/romfs.bin', link.parent))

def library_game_data(game, version, base=None):
    """--mac-game-data library: where the launcher looks for the RomFS image of an app that carries none (app/launcher.m):
    <base>/<version>, base being the folder --mac-game-data-folder names (the app's Info.plist MNGGameDataFolder), else the
    game's data folder's GameData. One base can hold both games: their versions are named apart."""
    base = base or Path.home() / 'Library/Application Support/Kokiri' / APPS[game][2] / 'GameData'
    return base / version

def place_library_image(tree, game, version, base=None, *, expected_romfs=None):
    """--mac-game-data library: the RomFS image in library_game_data instead of the app, put there once per image (an APFS
    clone when the work folder is on the same volume, else a 16 GB copy). romfs.sha256 is written last, so the launcher
    never takes a half-copied image; the image is not hashed here (the extraction checked it against the pin, and the
    runtime checks it once more at its first start). Returns whether it was put there now."""
    image, sha = tree / f'extracted/{version}/romfs/romfs.bin', (expected_romfs or VERSIONS[version]['romfs'])['sha256']
    folder = library_game_data(game, version, base)
    target, mark = folder / 'romfs.bin', folder / 'romfs.sha256'
    try:
        if mark.read_text().strip() == sha and target.stat().st_size == image.stat().st_size:
            return False
    except OSError:
        pass
    mark.unlink(missing_ok=True)
    partial = folder / 'romfs.bin.partial'
    clone(image, partial)
    partial.replace(target)
    written = mark.with_name(mark.name + '.tmp')
    written.write_text(sha + '\n')
    written.replace(mark)
    return True

def app_seal_valid(app):
    """The app's own seal, which records each helper bundle's signature (not --deep: that hashes the 16 GB image)."""
    return subprocess.run(['codesign', '--verify', '--strict', app], capture_output=True).returncode == 0

class _AppMoves:
    """Keep rename inverses until publication finishes; do not discard the fresh data before then."""
    def __init__(self):
        self.done = []
        self.discard = []
        self.recovery_failed = False

    def move(self, source, target):
        source.rename(target)
        self.done.append((source, target))

    def restore(self, checkpoint=0):
        while len(self.done) > checkpoint:
            source, target = self.done[-1]
            try:
                if source.exists() or source.is_symlink():
                    raise OSError(f'recovery destination already exists: {source}')
                target.rename(source)
            except OSError as error:
                self.recovery_failed = True
                raise BuildError(f'App update rollback could not restore {target} to {source}: {error}. '
                                 'Files have been retained; recover them before rebuilding.') from error
            self.done.pop()

    def __enter__(self):
        return self

    def __exit__(self, kind, error, traceback):
        if kind is not None and not self.recovery_failed:
            self.restore()
        elif kind is None:
            for path in self.discard:
                try:
                    remove_tree(path)
                except OSError as cleanup_error:
                    say(f'Could not remove temporary game data {path}: {cleanup_error}')
        return False

def keep_game_data(new, old, *, verify=app_seal_valid, _moves=None):
    """When the app being replaced carries the same signed game data as the new one (the same signature, which names the
    image's SHA-256, the same Info.plist and image size), move its data bundle into the new app in place of the fresh
    clone. The image keeps its inode and times, so the runtime's RomFS verification record (runtime/romfs.c, keyed by
    them) still matches and the first start after a packaging does not hash 16 GB again (19.5 s, 2026-10-21). An image
    changed since keeps nothing either: its modification time moved, so the runtime hashes it and refuses it. Called when
    the old app no longer runs, just before it is replaced; if the new app's seal does not verify, the clone goes back."""
    if _moves is None:
        with _AppMoves() as moves:
            return keep_game_data(new, old, verify=verify, _moves=moves)
    image = 'Contents/Resources/romfs.bin'
    swapped, start = [], len(_moves.done)
    helpers = new / 'Contents/Helpers'
    for bundle in sorted([*helpers.glob('GameData-*.bundle'), *helpers.glob('ShaderData-*.bundle')]):
        # ShaderData (shader_bundle) the same way: 117,000 files moved instead of cloned, sealed and deleted (2026-11-03);
        # in update_runtime.py's new app it is only its signature (Info.plist, _CodeSignature), what the app's seal records
        before = old / 'Contents/Helpers' / bundle.name
        if not all((before / rel).is_file() and (before / rel).read_bytes() == (bundle / rel).read_bytes()
                   for rel in ('Contents/_CodeSignature/CodeResources', 'Contents/Info.plist')):
            continue
        if bundle.name.startswith('GameData-'):
            if bundle.name in ('GameData-ss.bundle', 'GameData-worldend.bundle'):
                # SS and Worldend store verified directory trees, whose complete file hashes are
                # sealed in files.json (ss_bundle.signed_bundle), rather than romfs.bin.
                manifest = 'Contents/Resources/files.json'
                if not (before/manifest).is_file() or (before/manifest).read_bytes() != (bundle/manifest).read_bytes():
                    continue
            elif not (before / image).is_file() or (before / image).stat().st_size != (bundle / image).stat().st_size:
                continue
        fresh = new.with_name(f'{new.name}.{bundle.name}.fresh')   # outside the app: anything extra in it fails the seal
        if fresh.exists():
            remove_tree(fresh)
        checkpoint = len(_moves.done)
        _moves.move(bundle, fresh)
        try:
            _moves.move(before, bundle)
        except OSError:
            _moves.restore(checkpoint)
            continue
        swapped.append((bundle, fresh))
    if swapped and not verify(new):   # one check of the seal for every bundle moved (16 s each)
        _moves.restore(start)
        swapped = []
    _moves.discard.extend(fresh for _, fresh in swapped)
    for bundle in helpers.glob('ShaderData-*.bundle'):   # update_runtime.py's signature-only bundle must have been replaced
        if not (bundle / 'Contents/Resources').is_dir():
            raise BuildError(f'{bundle.name}: the installed app\'s shader data could not be moved into the new app; the installed app is unchanged')
    return any(bundle.name.startswith('GameData-') for bundle, _ in swapped)

def remove_in_background(path):
    """Delete a replaced app after the new one is in place, without waiting: its 90,000 shader files took 25 s."""
    subprocess.Popen(['rm', '-rf', str(path)], stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                     stderr=subprocess.DEVNULL, start_new_session=True)

def install_app(new, out, *, verify=None, remove=None):
    """Put the signed app `new` at `out`. Its seal is checked once, before the installed app is touched: by keep_game_data
    when the installed game data is kept, else here (a seal that does not verify stops the build and leaves the installed
    app as it is). The installed .app folder stays and takes the new contents; the replaced contents go to a folder whose
    name is not an app's, deleted in the background with any left by an earlier packaging. Returns whether the installed
    game data was kept."""
    verify, remove = verify or app_seal_valid, remove or remove_in_background
    with _AppMoves() as moves:
        kept = out.exists() and keep_game_data(new, out, verify=verify, _moves=moves)
        if not kept and not verify(new):
            raise BuildError(f'{new}: the new app\'s signature does not verify (codesign --verify --strict); the installed app is unchanged')
        leftovers = sorted(out.parent.glob(f'{glob.escape(out.name)}.replaced-*'))
        if out.exists():
            # The .app folder itself stays: macOS keeps its first-run check of an app (Gatekeeper / XProtect read the whole
            # bundle, 185-200 s for the 17 GB one) with the folder. A new folder with the same contents was scanned again,
            # new Contents in the same folder were not (2026-10-22). Everything in it moves out, the new Contents move in.
            old = out.with_name(f'{out.name}.replaced-{os.getpid()}')
            if old.exists():
                remove_tree(old)
            old.mkdir()
            for entry in list(out.iterdir()):
                moves.move(entry, old / entry.name)
            for entry in list(new.iterdir()):
                moves.move(entry, out / entry.name)
            new.rmdir()
            leftovers.append(old)
        else:
            moves.move(new, out)
    for path in leftovers:
        remove(path)
    return kept

def link_shader_data(app, res, name):
    """build/shader-seed and build/shader-libs: links to the app's ShaderData bundle (relative: the app moves)."""
    target = app / 'Contents/Helpers' / name / 'Contents/Resources'
    for rel in SHADER_DATA:
        link = res / 'build' / rel
        link.parent.mkdir(parents=True, exist_ok=True)
        if link.is_symlink() or link.is_file():
            link.unlink()
        elif link.is_dir():   # an older app's own folder (update_runtime.py migrate_shader_data): out of the app, deleted later
            aside = app.with_name(f'{app.name}.{rel}.old')
            if aside.exists():
                remove_tree(aside)
            link.rename(aside)
            remove_in_background(aside)
        link.symlink_to(os.path.relpath(target / rel, link.parent))

def place_shader_bundle(bundle, app, res):
    """The signed shader data in the app (Contents/Helpers), and the links the game reads it by."""
    copy_tree(bundle, app / 'Contents/Helpers' / bundle.name)
    link_shader_data(app, res, bundle.name)

def record_update_source(info, work):
    """Where an update (MNG Launcher, update_runtime.py) finds what made the app: this checkout, the work folder
    (update_runtime.py --work) and the Python that runs update_runtime.py. update_runtime.py writes them again."""
    info['MNGSourceRepo'] = str(REPO)
    info['MNGWorkFolder'] = str(Path(work).resolve())
    info['MNGBuildPython'] = sys.executable

def default_work(out, game):
    """The work folder of a build run without --work, and why, one rule for build_app.py, update_runtime.py and MNG Launcher
    (user 2026-11-12: "目录规范要和 launcher 统一"): the one the app at out records, when there is one (a rebuild then
    reuses that build's files, and an express update finds them); else <the folder above the apps folder>/MacNativeGames-work/
    <game>, on the app's volume (the game data is cloned, not copied) and outside the folder that holds the apps; with the
    apps in a folder whose parent cannot be written (/Applications), ~/MacNativeGames-work/<game>. Until then the default
    was a TOTK_build next to the game file, and the Launcher used a third place."""
    out = Path(out)
    try:
        recorded = plistlib.loads((out / 'Contents/Info.plist').read_bytes()).get('MNGWorkFolder')
    except (OSError, ValueError, plistlib.InvalidFileException, AttributeError):
        recorded = None
    if isinstance(recorded, str) and recorded and Path(recorded).parent.is_dir():
        return Path(recorded), f'recorded by {out.name}'
    base = out.parent.parent
    if base == Path(base.anchor) or not os.access(base, os.W_OK):
        base = Path.home()
    return base / WORK_FOLDERS / game, f'{WORK_FOLDERS}/{game} beside the folder of the app'

def recorded_work_folder(app, name):
    """The work folder of an update run without --work, and why: the one the app records (record_update_source), so the
    update reuses the files of the build that made the app. Only an app that records none (built before 31 October 2026)
    falls back to <name> next to the app. A recorded folder that was deleted is made again where it was: an app that
    carries its game data needs none of its old files, and one that does says so later (game_data). A recorded folder
    whose parent is gone too (a disk not connected, a volume deleted) is an error naming both ways out, never a new
    folder next to the app. 2026-11-11: the fallback was the only default, and an update of an app built with --work
    made a second 2.2 GB work folder in the folder that holds the apps, which the updated app then recorded."""
    app = Path(app)
    try:
        recorded = plistlib.loads((app / 'Contents/Info.plist').read_bytes()).get('MNGWorkFolder')
    except (OSError, ValueError, plistlib.InvalidFileException, AttributeError):
        recorded = None
    fallback = app.parent / name
    if isinstance(recorded, str) and recorded:
        if Path(recorded).is_dir():
            return Path(recorded).resolve(), 'recorded by the app'
        if Path(recorded).parent.is_dir():
            return Path(recorded), 'recorded by the app; it was deleted, so it is made again there'
        raise BuildError(f'the work folder {app.name} records, {recorded}, cannot be found, nor the folder it was in (a disk '
                         f'that is not connected, or a folder moved or deleted): connect that disk and run the same command '
                         f'again, or pass --work <a folder of your choice> (docs/install.md, Folders); the app then records it')
    return fallback, f'the app records no work folder; using {name} next to the app'

def source_commit():
    """The short hash of the commit this checkout is on (user 2026-10-25: the HUD shows it, to tell which commit an app
    was built from; uncommitted changes are not shown), or '' outside a git checkout."""
    # GitHub Release launchers use a verified source snapshot, with no .git directory.
    marker = REPO / '.mng-source-commit'
    if marker.is_file():
        return marker.read_text().strip()[:7]
    result = subprocess.run(['git', '-C', REPO, 'rev-parse', '--short=7', 'HEAD'], capture_output=True, text=True)
    return result.stdout.strip() if result.returncode == 0 else ''

def mac_pipeline_files(made, seed, arch, chain):
    """The pipeline-archive mode's files (<name>.metalarchive + <name>.keys) into the app's build/pipelines (`seed`; the
    app's seed until 2026-11-03, now in the shader data bundle, which they would change on every build) as the runtime
    reads them (totk_pipeline_archive.h par_load_prebuilt): pipelines-<arch>-<name>.metalarchive, pipelines-<arch>.tsv
    ("<key>\\t<name>") and pipelines-<arch>.json (schema, chain, arch). The last build's files go first. Returns how many
    pipelines."""
    seed.mkdir(parents=True, exist_ok=True)
    for old in seed.glob('pipelines-*'):
        old.unlink()
    index = []
    for archive in sorted(made.glob('*.metalarchive')):
        keys = archive.with_suffix('.keys')
        if not keys.is_file():
            continue
        clone(archive, seed / f'pipelines-{arch}-{archive.stem}.metalarchive')
        index += [f'{key}\t{archive.stem}' for key in keys.read_text().split('\n') if key]
    if not index:
        return 0
    # #2070: the compute shaders this GPU's Metal compiler built only with their float adds lowered (nvn_float_rmw.h): the
    # app takes the lowered form at once instead of crashing the compiler service on the native one at its first start.
    lowered = made / 'float-rmw-lowered.txt'
    keys = sorted({c[1] for c in (line.split('\t') for line in lowered.read_text().splitlines()) if len(c) == 2 and c[0] == arch and c[1]}
                  ) if lowered.is_file() else []
    if keys:
        (seed / f'pipelines-{arch}-lowered.txt').write_text('\n'.join(keys) + '\n')
    (seed / f'pipelines-{arch}.tsv').write_text('\n'.join(index) + '\n')
    (seed / f'pipelines-{arch}.json').write_text(json.dumps({'schema': PAR_SCHEMA, 'chain': chain, 'arch': arch,
                                                             'pipelines': len(index)}, indent=1) + '\n')
    return len(index)
