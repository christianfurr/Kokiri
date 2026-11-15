"""Build Kokiri Game from an owned OoT update 131072 dump or NUP."""
import argparse
import concurrent.futures
import hashlib
import json
import os
import re
from pathlib import Path
import plistlib
import shutil
import subprocess
import sys
import time

GAME=Path(__file__).resolve().parent
VERSION='oot'
TITLE='0400486024DEC000'
PRODUCT_VERSION = '0.1.0'
RUNTIME_BUNDLE_ID = 'com.christianfurr.kokiri.runtime'
RUNTIME_EXECUTABLE = 'KokiriGame'
_helpers = None
_shader_tools = None

def build_helpers():
    global _helpers
    if _helpers is None:
        import importlib.util
        spec = importlib.util.spec_from_file_location('kokiri_engine_helpers', GAME/'_build_helpers.py')
        _helpers = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(_helpers)
    return _helpers

def shader_tools():
    """Load the trusted engine package explicitly, including under Python -I."""
    global _shader_tools
    if _shader_tools is None:
        import importlib.util
        package_name = 'kokiri_engine_tools'
        package_spec = importlib.util.spec_from_file_location(
            package_name, GAME/'tools/__init__.py',
            submodule_search_locations=[str(GAME/'tools')])
        package = importlib.util.module_from_spec(package_spec)
        sys.modules[package_name] = package
        package_spec.loader.exec_module(package)
        spec = importlib.util.spec_from_file_location(
            package_name+'.build_shader_service', GAME/'tools/build_shader_service.py')
        module = importlib.util.module_from_spec(spec)
        sys.modules[spec.name] = module
        spec.loader.exec_module(module)
        _shader_tools = module
    return _shader_tools

def external_workspace(path):
    path = Path(path).expanduser().resolve()
    repo = GAME.parent.resolve()
    if path == repo or repo in path.parents:
        raise ValueError('build output must remain outside the Kokiri source repository')
    return path

def available_space(path):
    path = Path(path).resolve()
    while not path.exists():
        path = path.parent
    return shutil.disk_usage(path).free

def ensure_disk_space(path):
    if available_space(path) < 2 * (1 << 30):
        raise OSError('less than 2 GiB free; build stopped without deleting data')

def validate_runtime_app(app):
    app = Path(app)
    if app.exists():
        try:
            info = plistlib.loads((app/'Contents/Info.plist').read_bytes())
        except (OSError, ValueError) as error:
            raise ValueError('existing output is not a Kokiri runtime app') from error
        if info.get('CFBundleIdentifier') != RUNTIME_BUNDLE_ID:
            raise ValueError('refusing to replace an app not owned by Kokiri')

def shader_service_folders(work):
    import xml.etree.ElementTree as ET
    version = ET.parse(GAME/'tools/totk_xlate/totk_xlate.csproj').findtext('PropertyGroup/RuntimeFrameworkVersion')
    if not re.fullmatch(r'\d+\.\d+\.\d+', version or ''):
        raise ValueError('the shader service must pin its NativeAOT runtime version')
    return (Path(work)/('shader-tools-aot-'+version), Path(work)/'shader-tools')

def ready_shader_service(work):
    """Read-only discovery: a versioned folder still needs all input/output proofs."""
    expected = shader_tools().expected_inputs()
    for folder in shader_service_folders(work):
        try:
            have = json.loads((folder/'build-record.json').read_text())
            if not all(have.get(key) == value for key, value in expected.items()):
                continue
            native = folder/'native'
            if sha(native/'totk_xlate') == have.get('binary_sha256') and sha(native/'oot_write_proof.dylib') == have.get('proof_binary_sha256'):
                return native
        except (OSError, ValueError):
            continue
    return None

def ensure_shader_service(work):
    work = external_workspace(work)
    ready = ready_shader_service(work)
    if ready:
        return ready
    folder = shader_service_folders(work)[0]
    ensure_disk_space(work)
    if available_space(work) < 6 * (1 << 30):
        raise OSError('building the shader toolchain requires at least 6 GiB free; existing caches are kept')
    subprocess.run([sys.executable, GAME/'tools/build_shader_service.py', '--work', folder], check=True)
    ready = ready_shader_service(work)
    if not ready:
        raise ValueError('the built shader toolchain does not match its source and output proofs')
    return ready

def runtime_metadata(mode, commit):
    return dict(CFBundleDevelopmentRegion='en', CFBundleExecutable=RUNTIME_EXECUTABLE,
                CFBundleIdentifier=RUNTIME_BUNDLE_ID, CFBundleName='Kokiri Game',
                CFBundleDisplayName='Kokiri Game', CFBundlePackageType='APPL',
                CFBundleShortVersionString=PRODUCT_VERSION, CFBundleVersion='1',
                LSMinimumSystemVersion='26.0', NSHighResolutionCapable=True,
                LSSupportsGameMode=True, GCSupportsControllerUserInteraction=True,
                KokiriGameUpdate='131072', KokiriProductVersion=PRODUCT_VERSION,
                KokiriLiveStatusVersion=1,
                KokiriCatalogWarmVersion=1,
                KokiriSourceCommit=commit or 'uncommitted', KokiriShaders=mode,
                KokiriHUDPreferencesVersion=1)

def catalog_context(tree):
    """Identify actual local content; unknown compilation/device facts stay null."""
    tree = Path(tree)
    code = tree/'extracted/oot/exefs'
    expected = json.loads((GAME/'assets/expected-v131072.json').read_text())
    exefs = {path.name:sha(path) for path in sorted(code.iterdir()) if path.is_file()}
    for name, digest in expected['exefs_sha256'].items():
        if exefs.get(name) != digest:
            raise ValueError('catalog content identity: original module verification failed: '+name)
    image = tree/'extracted/oot/romfs/romfs.bin'
    before = image.stat()
    image_sha = sha(image)
    after = image.stat()
    if (before.st_ino, before.st_size, before.st_mtime_ns) != (after.st_ino, after.st_size, after.st_mtime_ns):
        raise ValueError('game image changed while hashing its content identity')
    index = json.loads((image.parent/'index.json').read_text())
    if image_sha != index['romfs_sha256'] or after.st_size != index['romfs_size']:
        raise ValueError('catalog content identity: game image differs from verified extraction')
    identity = dict(schema='kokiri-game-content-v1', title_id=TITLE, content_version=131072,
                    exefs_sha256=exefs, romfs_sha256=image_sha, romfs_size=after.st_size)
    encoded = json.dumps(identity, sort_keys=True, separators=(',', ':'), ensure_ascii=True).encode('ascii')
    record = tree/'build/game-data/oot/kokiri-content-identity.json'
    record.write_bytes(encoded+b'\n')
    chain = re.search(r'#define DMSH_CHAIN "([^"]+)"\s*/\* game: oot\b',
                      (GAME/'third_party/d2r_gfx/gfx/nvn/dmsh_chain.h').read_text())[1]
    return dict(game_id='oot', game_version='131072', game_content_sha256=hashlib.sha256(encoded).hexdigest(),
                recipe_format='mng-list-v1', backend='metal', shader_chain=chain,
                translator_sha256=sha(tree/'build/shader-service/totk_xlate'),
                compiler_sha256=None, target_sha256=None, options_sha256=None)

TREE_SKIP=('__pycache__','*.pyc','.venv','build','extracted','rewritten','analysis','Gen')   # the build's own output and caches (Gen: ios/Gen, the device seed and its compiled-library cache)

def sync_tree(source,tree):
    """The work folder's copy of games/oot mirrors the checkout: files are copied (linked folders, the shared graphics
    layer and zeldaVR, as their contents), and a file or folder the checkout no longer has is deleted. A copy that only
    added files kept another branch's nvn_pool_sources.m, which the Makefile's wildcard compiled with this checkout's
    headers (2026-11-13). The names in TREE_SKIP are neither copied nor deleted."""
    import fnmatch
    shutil.copytree(source,tree,dirs_exist_ok=True,ignore=shutil.ignore_patterns(*TREE_SKIP))
    skip=lambda name:any(fnmatch.fnmatch(name,p) for p in TREE_SKIP)
    for here,dirs,files in os.walk(tree,topdown=True):
        rel=Path(here).relative_to(tree)
        dirs[:]=[d for d in dirs if not skip(d)]
        for name in list(dirs):
            if not (source/rel/name).exists():shutil.rmtree(Path(here)/name);dirs.remove(name)
        for name in files:
            if not skip(name) and not (source/rel/name).exists():(Path(here)/name).unlink()

def sha(path):
    h=hashlib.sha256()
    with Path(path).open('rb') as f:
        while data:=f.read(8<<20):h.update(data)
    return h.hexdigest()

def exact_source_commit():
    # A release extracted inside an unrelated checkout must not inherit its HEAD.
    if (GAME.parent/'.git').exists():
        top=subprocess.run(['git','-C',GAME.parent,'rev-parse','--show-toplevel'],capture_output=True,text=True)
        if top.returncode==0 and Path(top.stdout.strip()).resolve()==GAME.parent.resolve():
            result=subprocess.run(['git','-C',GAME.parent,'rev-parse','HEAD'],capture_output=True,text=True)
            if result.returncode==0:return result.stdout.strip()
    marker=GAME.parent/'kokiri-source-release.json'
    if marker.is_file():
        record=json.loads(marker.read_text())
        chain=re.search(r'#define DMSH_CHAIN "([^"]+)"\s*/\* game: oot\b',
                        (GAME/'third_party/d2r_gfx/gfx/nvn/dmsh_chain.h').read_text())[1]
        commit=record.get('source_commit','')
        if (record.get('schema')!='kokiri-runtime-source-v1' or record.get('product')!=RUNTIME_BUNDLE_ID or
            str(record.get('game_update'))!='131072' or record.get('shader_chain')!=chain or
            not re.fullmatch('[0-9a-f]{40}',commit)):
            raise ValueError('invalid source-release identity record')
        return commit   # authenticated by the updater before extraction/build, not a synthetic git HEAD
    return ''

def paths_overlap(a,b):
    a,b=Path(a).resolve(),Path(b).resolve()
    return a==b or a in b.parents or b in a.parents

def validate_staged_paths(app,destination,work):
    if paths_overlap(app,destination) or paths_overlap(app,work):
        raise ValueError('staged rebuild must not overlap the original app')
    if destination==work or destination in work.parents:
        raise ValueError('staged rebuild work must not be inside its replaceable output app')
    original=plistlib.loads((app/'Contents/Info.plist').read_bytes())
    for key in ('MNGWorkFolder','MNGGameDataFolder'):
        if original.get(key) and (paths_overlap(original[key],work) or paths_overlap(original[key],destination)):
            raise ValueError('staged rebuild requires independent copies of the original work and game-data folders')

def _script(name):
    """games/oot/scripts/<name>.py by its path (games/totk/scripts may hold a module of the same name)."""
    import importlib.util
    spec=importlib.util.spec_from_file_location('oot_'+name,GAME/f'scripts/{name}.py')
    module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module);return module

romfs_pin=_script('romfs_pin')

def imported_romfs(tree):
    """The RomFS image this tree imported (its index.json): the shader seed is translated from it and the game-data marker
    names it. Not a pinned image: two retail dumps of update 131072 pack to different images (#2009, #2011)."""
    index=json.loads((Path(tree)/'extracted/oot/romfs/index.json').read_text())
    return dict(sha256=index['romfs_sha256'],size=index['romfs_size'])

def make_path(work):
    """The work folder as make can name it (#2045): make splits target and prerequisite names at spaces, and the default
    work folder sits next to the dump, named after the game. A path with spaces gets a fixed alias in the temporary
    folder, a link to it; the build's files still land in the work folder."""
    work=Path(work)
    if ' ' not in str(work):return work
    import tempfile
    alias=Path(tempfile.gettempdir())/('oot-work-'+hashlib.sha256(str(work.resolve()).encode()).hexdigest()[:12])
    if ' ' in str(alias):raise ValueError(f'the temporary folder {alias.parent} has a space too: set TMPDIR to a folder without one')
    if alias.is_symlink() and alias.resolve()==work.resolve():return alias
    if alias.is_symlink() or alias.exists():alias.unlink()
    alias.symlink_to(work.resolve(),target_is_directory=True)
    return alias

def clone_file(source, destination):
    """APFS copy-on-write keeps the verified game image independent without duplicating disk blocks."""
    import ctypes
    source=Path(source);destination=Path(destination)
    destination.parent.mkdir(parents=True,exist_ok=True)
    libc=ctypes.CDLL('/usr/lib/libSystem.B.dylib',use_errno=True)
    clone=libc.clonefile;clone.argtypes=[ctypes.c_char_p,ctypes.c_char_p,ctypes.c_int];clone.restype=ctypes.c_int
    if clone(os.fsencode(source),os.fsencode(destination),0):
        if shutil.disk_usage(destination.parent).free<source.stat().st_size+(1<<30):
            raise OSError('APFS cloning unavailable and insufficient space for '+str(source))
        shutil.copy2(source,destination)
    return str(destination)

def bundle_shaders():
    """The App carries the offline seed, the Metal libraries (every shader; OOT_SHADER_SUBSET=listed for test builds:
    shader_subset) and the pipeline archive. User 2026-11-08: no translated shaders while the port changes; 2026-11-09:
    "不要编译全部着色器 … 用我最近玩的 … 管线要全部预热", "只要 我一直用的 我收集的", "为什么不能和以前一样 自动";
    2026-11-10: "用户要编译 预热全部着色器。测试只预热我的". OOT_BUNDLE_SHADERS=0 leaves the shaders out (each translated
    at first use)."""
    return shader_mode()!='none'

SHADER_MODES=('full','title','none')

def shader_mode(app=None):
    """How many shaders the App carries (user 2026-11-13, MNG Launcher's 快速启动): 'full' every one (the player's build),
    'title' only those the shared list's title rows name, so packaging takes minutes and the rest are translated and
    compiled by the game at first use (MNG Launcher's 补全着色器 fills them in later: update_shaders), 'none' none
    (OOT_BUNDLE_SHADERS=0, the older test build). OOT_SHADERS chooses for a build; an update keeps what the App records
    (MNGShaders in its Info.plist) unless OOT_SHADERS is given."""
    want=os.environ.get('OOT_SHADERS','')
    if not want and app is not None:
        try:want=plistlib.loads((Path(app)/'Contents/Info.plist').read_bytes()).get('MNGShaders','')
        except (OSError,ValueError):want=''
    if not want:want='none' if os.environ.get('OOT_BUNDLE_SHADERS','1')=='0' else 'full'
    if want not in SHADER_MODES:raise ValueError(f'OOT_SHADERS={want}: one of '+', '.join(SHADER_MODES))
    return want

def shader_dirs(tree, mode='full'):
    """(seed, Metal libraries, suffix) of a build's shaders: a 'title' build keeps its own (shader-seed-title,
    shader-libs-title, and with the suffix its pipeline cache, warm lists, archive files and shader data bundle), so it
    never replaces or prunes a full build's. 2026-11-13: a title build in the full build's work folder deleted 3,081
    pipeline archive files of the full build and cut its libraries' record to 33 shaders, so the next full update would
    have built 23,710 pipelines and 42,895 libraries again."""
    suffix='-title' if mode=='title' else ''
    return tree/f'build/shader-seed{suffix}/oot',tree/f'build/shader-libs{suffix}',suffix

def title_shader_file(tree, shared):
    """The shaders the title rows of the shared list name, written for prepare_ns2_seed.py --only (a 'title' build)."""
    keys=oot_shader_list().ShaderList.load(shared).title_keys()
    if not keys:raise ValueError(f'{shared} has no title rows (flag t): a quick build has nothing to take; record them first (TOTK_PSO_CAPTURE, shader_list.py merge --title)')
    path=tree/'build/shader-seed-title.txt';path.parent.mkdir(parents=True,exist_ok=True)
    path.write_text(''.join(k+'\n' for k in sorted(keys)))
    print(f'quick build: the {len(keys)} shaders of the title rows; the game translates the rest at first use',flush=True)
    return path

def oot_shader_list():
    """games/oot/scripts/shader_list.py, imported by its path: "import shader_list" can give TOTK's module of the same name
    (another script put games/totk/scripts first, or imported it already), which does not know mesh (M) rows."""
    import importlib.util
    if 'oot_shader_list' not in sys.modules:
        spec=importlib.util.spec_from_file_location('oot_shader_list',GAME/'scripts/shader_list.py')
        module=importlib.util.module_from_spec(spec);sys.modules['oot_shader_list']=module;spec.loader.exec_module(module)
    return sys.modules['oot_shader_list']

def contrib_folder():
    """<clone>/shader-list-contribution (MNG_CONTRIB_FOLDER overrides), as build_app.py contrib_folder: where the launcher
    keeps the contribution file (shader-list-contribution-oot.txt, app/launcher.m contrib_file), which the game contributes
    over HTTPS when the player lets it. Made here if missing."""
    folder=Path.home()/'Library/Application Support/Kokiri/OcarinaOfTime/catalog/pending'
    folder.mkdir(parents=True,exist_ok=True)
    return folder

# The Mac agent an iOS build installed until 2026-11-10 (ios/tools/shader_contrib_watch.py, Ocarina of Time's own): while
# an iPhone / iPad was connected it asked to send the device's shaders in a GitHub issue. The devices contribute over HTTPS
# on their own now (totk_contrib_upload.h) and the script is gone, so a build takes the agent off (as build_app.py does).
DEVICE_REMINDER_LABEL='org.macnativegames.oot.ios-shader-contrib'

def remove_device_reminder():
    agent=Path.home()/f'Library/LaunchAgents/{DEVICE_REMINDER_LABEL}.plist'
    if not agent.exists():return
    subprocess.run(['launchctl','bootout',f'gui/{os.getuid()}/{DEVICE_REMINDER_LABEL}'],capture_output=True)
    agent.unlink(missing_ok=True)
    print('removed the old Mac reminder for iPhone / iPad shader contributions: the devices contribute on their own now',flush=True)

def resolve_lists(tree, folder, logs, shared=None, mode='full'):
    """The App's warm-up lists beside build/shader-map.tsv, build/pso_manifest.tsv and build/pso_title.tsv: the shared
    list's rows of this game, each variant named as the seed serves its bind state (scripts/shader_list.py resolve), as
    build_app.py resolve_lists makes them for every game it packages. The Mac runtime reads the lists in the shader map's
    folder (nvn_mtl.m warm_start, pso_user_record, pso_contribute) and the launcher prunes the contribution file against them
    (app/launcher.m, totk_shader_contrib.h totk_contrib_prune). With them only in the seed (prepare_ns2_seed.py) every
    pipeline the game drew was written as one the list lacks (2026-11-10: 3,091 rows, 3,040 of them in the list) and the
    title list was never read (user: "要统一").
    Written once per package into folder and returned as (pso_title.tsv, pso_manifest.tsv): the pipeline archive is built
    from these same files and the App carries them (package_app). The seed's own copies are of the list the seed was
    translated with; a fast update keeps that seed, so on 2026-11-11 the archive had 2,957 listed render pipelines of the
    11-09 list while the App's lists named 7,516."""
    seed=shader_dirs(tree,mode)[0];shared=Path(shared) if shared else tree/'assets/shader_list.tsv'   # shared: shader_update.py's download
    folder=Path(folder);folder.mkdir(parents=True,exist_ok=True)
    title,manifest=folder/'pso_title.tsv',folder/'pso_manifest.tsv'
    for path in (title,manifest):path.unlink(missing_ok=True)   # never an older package's file
    log=Path(logs)/'shader-list-resolve.log';log.parent.mkdir(parents=True,exist_ok=True)
    with log.open('w') as f:
        subprocess.run([sys.executable,'-I',GAME/'scripts/shader_list.py','resolve',seed,shared,manifest,title],cwd=GAME,stdout=f,stderr=subprocess.STDOUT,check=True)
    for path in (title,manifest):
        if not path.is_file():raise ValueError(f'the shader list resolve wrote no {path}; see {log}')
    print(log.read_text().strip(),flush=True)
    if mode=='full' and any(int(n) for n in re.findall(r'(\d+) the seed cannot build',log.read_text())):
        raise ValueError('incomplete resolved pipeline lists; see '+str(log))
    return title,manifest

def listed_shader_keys(seed, shared, compute):
    """The shaders whose Metal libraries the Mac App carries: every shader the seed's resolved warm-up lists use (a render,
    tile or mesh row names its stages inside its hex key: shader_list.row_variants), the shared list's own variants (its
    V rows) and every compute shader (the compute pipeline archive must be complete). The others are compiled by the game
    at first use. On 2026-11-09 this held all 5,923 shaders picked by hand (the ones played + the warm-up lists)."""
    row_variants=oot_shader_list().row_variants
    keys=set()
    for row in compute:keys.update(name[:64] for name in row_variants(row.split('\t')))
    for path in (Path(seed)/'pso_title.tsv',Path(seed)/'pso_manifest.tsv'):
        if not path.is_file():continue
        for line in path.read_text().splitlines():
            if line and not line.startswith('#'):keys.update(name[:64] for name in row_variants(line.split('\t')))
    if Path(shared).is_file():
        keys.update(line.split('\t')[1] for line in Path(shared).read_text().splitlines() if line.startswith('V\t'))
    return keys

def shader_subset(tree, shared, env=None):
    """Which Metal libraries a full build compiles (user 2026-11-10: "用户要编译 预热全部着色器。测试只预热我的"): a
    player's build compiles every shader (unset); OOT_SHADER_SUBSET=listed, for the test builds, the shaders the list uses
    (listed_shader_file); a path, the keys in that file. None means every shader."""
    want=(os.environ if env is None else env).get('OOT_SHADER_SUBSET','')
    if want in ('','all'):return None
    return listed_shader_file(tree,shared) if want=='listed' else want

def listed_shader_file(tree, shared):
    """listed_shader_keys of this build's seed, written for build_shader_libs.py --only."""
    scripts=str(GAME/'scripts')
    if scripts not in sys.path:sys.path.insert(0,scripts)
    from prepare_compute_pipelines import compute_rows
    seed=tree/'build/shader-seed/oot'
    keys=listed_shader_keys(seed,shared,compute_rows(seed))
    path=tree/'build/shader-libs-listed.txt';path.write_text(''.join(k+'\n' for k in sorted(keys)))
    print(f'Metal libraries: {len(keys)} shaders the list uses (OOT_SHADER_SUBSET=listed; unset compiles every one)',flush=True)
    return str(path)

def verify_shader_resources(tree, mode='full'):
    """Check every prepared variant/library and bind both manifests into the normal build record."""
    seed,libraries,_=shader_dirs(tree,mode)
    if not seed.exists():raise ValueError('missing shader seed; only mode none permits unprepared development packages')
    metadata=json.loads((seed/'seed-manifest.json').read_text())
    chain=re.search(r'#define DMSH_CHAIN "([^"]+)"\s*/\* game: oot\b',(GAME/'third_party/d2r_gfx/gfx/nvn/dmsh_chain.h').read_text())[1]   # the shared layer's line for this game
    imported=imported_romfs(tree)   # the seed is translated from this tree's own RomFS image (#2009: images differ by dump)
    if (metadata.get('version')!='oot' or metadata.get('source_romfs_sha256')!=imported['sha256'] or
        metadata.get('translator_sha256')!=sha(tree/'build/shader-service/totk_xlate') or
        metadata.get('chain')!=chain or not metadata.get('all_default') or
        metadata.get('nvn_depth_mode')!='minus-w' or not metadata.get('corpus_shaders') or
        metadata.get('translated_default')!=metadata['corpus_shaders']):
        raise ValueError('OOT shader seed is incomplete or belongs to another translation context')
    libs=json.loads((libraries/'libraries-manifest.json').read_text())
    if not libs.get('complete'):raise ValueError('OOT Metal libraries are incomplete')
    if mode=='full' and (metadata.get('only') is not None or libs.get('subset') or
                        metadata.get('listed_asked') != metadata.get('listed_variants')):
        raise ValueError('full shader preparation cannot use subsets or incomplete listed variants')
    if '-fpreserve-invariance' not in libs.get('compiler','').split():raise ValueError('OOT Metal libraries lack position invariance')
    if '-fwrapv' not in libs.get('compiler','').split():raise ValueError('OOT Metal libraries lack signed-overflow wrapping')
    shared=build_helpers()
    known_seed=shared.seed_digests(seed);known_libs=shared.seed_digests(libraries)
    for name,want in metadata['files'].items():
        if Path(name).name!=name or shared.seed_sha256(seed,name,known_seed)!=want:raise ValueError('damaged shader seed: '+name)
        if name.endswith('_b.metal'):
            if libs.get('subset') and name not in libs['sources']:continue   # OOT_SHADER_SUBSET builds: compiled by the game at first use
            if libs['sources'].get(name)!=want:raise ValueError('library source differs from seed: '+name)
            library=want+'.metallib'
            if shared.seed_sha256(libraries,library,known_libs)!=libs['files'].get(library):raise ValueError('damaged Metal library: '+library)
    for library,want in libs['files'].items():
        if Path(library).name!=library or shared.seed_sha256(libraries,library,known_libs)!=want:
            raise ValueError('damaged Metal library: '+library)
    scripts=str(GAME/'scripts')
    if scripts not in sys.path:sys.path.insert(0,scripts)
    from prepare_shader_seed import record_verified
    record_verified(seed,metadata['files']);record_verified(libraries,libs['files'])
    record=dict(schema=1,chain=chain,nvn_depth_mode=metadata['nvn_depth_mode'],
                corpus_shaders=metadata['corpus_shaders'],shaders=metadata['shaders'],
                seed_manifest_sha256=sha(seed/'seed-manifest.json'),
                libraries_manifest_sha256=sha(libraries/'libraries-manifest.json'),compiler=libs['compiler'])
    # record_ns2_device_build already hashes every build/game-data/oot file.
    (tree/'build/game-data/oot/precompiled-shaders.json').write_text(json.dumps(record,indent=2)+'\n')
    return record

def shader_bundle(tree,record,mode='full'):
    """Seal the large immutable seed once, using the repository's nested-bundle layout."""
    seed,libraries,suffix=shader_dirs(tree,mode)
    shared=build_helpers();bundle=tree/f'build/shader-bundles/ShaderData-oot{suffix}.bundle'
    stamp=bundle.with_name(bundle.name+'.json')
    want={k:record[k]for k in ('seed_manifest_sha256','libraries_manifest_sha256')}
    if (bundle/'Contents/_CodeSignature/CodeResources').is_file() and stamp.exists() and json.loads(stamp.read_text())==want:
        return bundle
    temporary=bundle.with_name(bundle.name+'.partial-'+str(os.getpid()))
    if temporary.exists():raise ValueError('unfinished shader bundle: '+str(temporary))
    resources=temporary/'Contents/Resources'
    shared.copy_tree(seed,resources/'shader-seed')
    manifest=json.loads((libraries/'libraries-manifest.json').read_text())
    for name in manifest['files']:clone_file(libraries/name,resources/'shader-libs'/name)
    clone_file(libraries/'libraries-manifest.json',resources/'shader-libs/libraries-manifest.json')
    (temporary/'Contents/Info.plist').write_bytes(plistlib.dumps(dict(
        CFBundleIdentifier=RUNTIME_BUNDLE_ID+'.shaders.oot',CFBundleName='Startup shaders',
        CFBundlePackageType='BNDL',CFBundleShortVersionString='131072',CFBundleVersion='1')))
    subprocess.run(['codesign','--force','--sign','-',temporary],check=True)
    subprocess.run(['codesign','--verify','--strict',temporary],check=True)
    old=bundle.with_name(bundle.name+'.previous-'+str(time.time_ns()))
    if bundle.exists():bundle.rename(old)
    temporary.rename(bundle);stamp.write_text(json.dumps(want)+'\n')
    return bundle

def pipeline_archive_environment(tree,cache,seed):
    """Use normal host libraries and precise math, regardless of diagnostic overrides."""
    return dict(os.environ,TOTK_NATIVE_DIR=str(tree/'build'),TOTK_SHADER_CACHE=str(cache),
                TOTK_SHADER_SEED_DIR=str(seed),TOTK_PIPELINE_ARCHIVE_HOST='1',TOTK_DEBUG_LOG='1',
                TOTK_PAR_RECHECK='1',TOTK_WARM_THREADS=str(shader_jobs()),
                TOTK_FAST_MATH='0',TOTK_SHADER_DEVICE_LIBS='0',OOT_UMUL_INLINE='0')

def pipeline_library_inputs(libraries):
    """Hash and inspect one manifest byte snapshot; no compiler or library execution."""
    path=Path(libraries)/'libraries-manifest.json'
    try:
        raw=path.read_bytes()
        manifest=json.loads(raw)
    except (OSError,ValueError) as error:
        raise ValueError('missing or invalid pipeline library manifest: '+str(path)) from error
    if (not isinstance(manifest,dict) or
            type(manifest.get('compiler_context_schema')) is not int or manifest['compiler_context_schema']!=2 or
            not isinstance(manifest.get('compiler_context_sha256'),str) or
            not re.fullmatch('[0-9a-f]{64}',manifest['compiler_context_sha256'])):
        raise ValueError('pipeline libraries require a schema 2 compiler context: '+str(path))
    return dict(libraries_manifest_sha256=hashlib.sha256(raw).hexdigest(),
                compiler_context_sha256=manifest['compiler_context_sha256'],compiler_context_schema=2)

def compute_pipeline_archive(work, tree, lists, mode='full'):
    """Build every seed compute pipeline and, with them, the render pipelines the App's warm-up lists name (lists: the
    pso_title.tsv / pso_manifest.tsv resolve_lists made from the current games/oot/assets/shader_list.tsv, the files the
    App carries), then package only a complete verified archive: every planned compute pipeline must be in the index; the
    render rows are reported."""
    scripts=str(GAME/'scripts')
    if scripts not in sys.path:sys.path.insert(0,scripts)
    from prepare_compute_pipelines import compute_rows
    from dev.game_slot import GameSlot
    seed,libraries,suffix=shader_dirs(tree,mode)
    rows=compute_rows(seed)
    folder=tree/'build/compute-pipelines';folder.mkdir(parents=True,exist_ok=True)
    plan=folder/'compute.tsv';plan.write_text('\n'.join(rows)+'\n')
    chain=json.loads((seed/'seed-manifest.json').read_text())['chain']
    # The runtime's archive metadata also checks GPU, OS and chain before reuse.
    cache=folder/(chain+suffix)   # a title build's own: its pruning never reaches the full build's files
    # Kept from one package to the next, also when the runtime changed: with TOTK_PAR_RECHECK=1 the tool makes every listed
    # pipeline against the archive (Metal compares the functions and state), so one this runtime describes otherwise is
    # compiled and written again and the rest come from their files (nvn_mtl.m mtl_pipeline_archive_tool, par_stale; user
    # 2026-11-11: "如何让 快速更新 不要这么容易失效"). Until then any runtime change threw it away: 17 min for 21,330 pipelines.
    logs=work/'logs';logs.mkdir(exist_ok=True)
    log=logs/'compute-pipelines.log'
    env=pipeline_archive_environment(tree,cache,seed)
    lists_sha256={p.name:sha(p) for p in lists}   # check_archive_lists compares them with the files the App carries
    lists=[p for p in lists if p.is_file() and any(l and not l.startswith('#') for l in p.read_text().splitlines())]
    render_rows=sum(1 for p in lists for l in p.read_text().splitlines() if l.startswith(RENDER_ROWS))
    mesh_rows=sum(1 for p in lists for l in p.read_text().splitlines() if l.startswith(MESH_ROWS))
    requested=len({line for p in (plan,*lists) for line in p.read_text().splitlines()
                   if line.startswith(('C\t',*RENDER_ROWS,*MESH_ROWS))})
    print(f'Preparing {len(rows)} compute pipelines, {render_rows} listed render pipelines and {mesh_rows} listed mesh pipelines before packaging',flush=True)
    library_inputs=pipeline_library_inputs(libraries)
    with GameSlot(owner='build',purpose='OOT offline pipelines',expect_seconds=3600),log.open('w') as f:
        tool=subprocess.run([work/'build/oot-native',tree/'rewritten/oot','pipeline-archive',plan,*lists],
                       cwd=tree,env=env,stdout=f,stderr=subprocess.STDOUT)   # exit 1 when any row failed: judged from its report below
    if pipeline_library_inputs(libraries)!=library_inputs:
        raise ValueError('pipeline library manifest or compiler context changed during archive preparation')
    reports=[json.loads(line) for line in log.read_text().splitlines() if line.startswith('{"render":')]
    if not reports:raise ValueError(f'pipeline archive exit {tool.returncode} without a completion report; see {log}')
    report=reports[-1]
    completed=sum(report[k] for k in ('render','compute','mesh','kept'))
    if tool.returncode or report['write_failed'] or report['failed'] or completed != requested:
        raise ValueError('incomplete pipeline archive: '+str(report))
    target=tree/f'build/pipelines{suffix}'
    count=build_helpers().mac_pipeline_files(cache/'pipelines',target,report['arch'],chain)
    expected={'c'+hashlib.sha256(row[2:].encode()).hexdigest()[:40]for row in rows}
    index=target/f"pipelines-{report['arch']}.tsv"
    actual={line.split('\t')[0]for line in index.read_text().splitlines()} if index.exists() else set()
    missing=missing_compute(rows,actual)
    if missing:raise ValueError(missing_compute_message(missing,report['arch'],log))
    mesh_indexed=sum(1 for key in actual if key.startswith(MESH_KEY))
    if mesh_rows and not mesh_indexed:raise ValueError(f'the pipeline archive holds none of the {mesh_rows} listed mesh pipelines; see {log}')
    if mesh_indexed<mesh_rows:raise ValueError(f'{mesh_rows-mesh_indexed} listed mesh pipelines are not in the archive; see {log}')
    report.update(planned=len(rows),listed_render=render_rows,listed_mesh=mesh_rows,mesh_indexed=mesh_indexed,lists=[p.name for p in lists],lists_sha256=lists_sha256,indexed=count,chain=chain,
                  plan_sha256=sha(plan),runtime_sha256=sha(work/'build/oot-native'),
                  requested=requested,completed=completed,
                  **library_inputs,
                  library_input_binding='intended manifest snapshot; actual library use and zero-JIT proof are not established by this record',
                  counter_basis='render/compute count successful PSO creation including archive hits; kept does not count newly compiled pipelines',
                  files={p.name:sha(p)for p in sorted(target.iterdir()) if p.is_file() and p.name!='compute-manifest.json'})
    (target/'compute-manifest.json').write_text(json.dumps(report,indent=2)+'\n')
    return target

RENDER_ROWS=('R\t','B\t','T\t')   # the warm rows that are render pipelines (shader_list.py row kinds)
MESH_ROWS=('M\t',)                 # mesh pipelines: archived since 2026-11-11 (nvn_mesh_tasks.inc mtk_archive_key)
MESH_KEY='m'                       # their archive keys ('m' + 40 hex; render keys are hex, compute keys 'c' + hex)
WARM_LISTS=('pso_title.tsv','pso_manifest.tsv')

def check_archive_lists(build):
    """The App's pipeline archive must be built from the warm-up lists the App carries (build/pso_title.tsv,
    build/pso_manifest.tsv). On 2026-11-11 a fast update built it from the seed's older list: 2,957 render pipelines in
    the archive, 7,516 in the App's lists, so 4,559 were compiled at the first start. Raises ValueError naming what
    differs; an App without a pipeline archive has nothing to check."""
    build=Path(build);record=build/'pipelines/compute-manifest.json'
    if not record.is_file():return
    report=json.loads(record.read_text())
    want=report.get('lists_sha256')
    if not isinstance(want,dict) or sorted(want)!=sorted(WARM_LISTS):
        raise ValueError(f'{record} does not name the warm-up lists it was built from (lists_sha256): package again')
    for name in WARM_LISTS:
        path=build/name
        if not path.is_file():raise ValueError(f'the App has no {path}')
        if sha(path)!=want[name]:raise ValueError(f'the pipeline archive was built from another {name} than the App carries ({path})')
    for field,kinds,what in (('listed_render',RENDER_ROWS,'render'),('listed_mesh',MESH_ROWS,'mesh')):
        rows=sum(1 for name in WARM_LISTS for line in (build/name).read_text().splitlines() if line.startswith(kinds))
        if report.get(field)!=rows:
            raise ValueError(f"the pipeline archive planned {report.get(field)} listed {what} pipelines, the App's lists name {rows}")

def write_preparation_receipt(work,tree,mode,pipelines):
    """Bind verified coverage to the exact packaged inputs; never infer readiness from mode alone."""
    scripts=str(GAME/'scripts')
    if scripts not in sys.path:sys.path.insert(0,scripts)
    from preparation_receipt import preparation_receipt,require_prepared
    seed,libraries,_=shader_dirs(tree,mode)
    seed_manifest=seed/'seed-manifest.json';library_manifest=libraries/'libraries-manifest.json'
    metadata=json.loads(seed_manifest.read_text()) if mode!='none' and seed_manifest.is_file() else {}
    libs=json.loads(library_manifest.read_text()) if mode!='none' and library_manifest.is_file() else {}
    pipeline_manifest=Path(pipelines)/'compute-manifest.json' if pipelines else None
    report=json.loads(pipeline_manifest.read_text()) if pipeline_manifest else {}
    chain=re.search(r'#define DMSH_CHAIN "([^"]+)"\s*/\* game: oot\b',
                    (GAME/'third_party/d2r_gfx/gfx/nvn/dmsh_chain.h').read_text())[1]
    artifacts={'runtime_sha256':sha(work/'build/oot-native')}
    for name,path in [('seed_manifest_sha256',seed_manifest),('libraries_manifest_sha256',library_manifest),
                      ('pipeline_manifest_sha256',pipeline_manifest),
                      ('pipeline_index_sha256',Path(pipelines)/f"pipelines-{report['arch']}.tsv" if pipelines else None)]:
        if path and path.is_file() and mode!='none':artifacts[name]=sha(path)
    receipt=preparation_receipt(mode,metadata,libs,report,
        expected_identity=dict(chain=chain,source_romfs_sha256=imported_romfs(tree)['sha256'],
                               translator_sha256=sha(tree/'build/shader-service/totk_xlate'),nvn_depth_mode='minus-w'),
        artifact_sha256=artifacts,pipeline_requested=report.get('requested'),source_commit=exact_source_commit())
    receipt['identity']['runtime_hash_scope']='pre-seal build executable; final signed bytes require an external package fingerprint'
    record=tree/'build/game-data/oot/preparation-receipt.json';record.parent.mkdir(parents=True,exist_ok=True)
    record.write_text(json.dumps(receipt,indent=2)+'\n')
    if mode=='full':require_prepared(receipt)
    return receipt

def verify_recorded_variant_coverage(libraries,caches):
    """A final archive recheck must not introduce an unprepared specialization."""
    sources,_=_script('build_shader_libs').recorded_variants([Path(p)for p in caches])
    manifest=json.loads((Path(libraries)/'libraries-manifest.json').read_text())
    for name,source in sources.items():
        digest=sha(source)
        if manifest['sources'].get(name)!=digest or digest+'.metallib' not in manifest['files']:
            raise ValueError('unprepared recorded specialization after pipeline recheck: '+name)
    return len(sources)

def package_app(work,tree,out,game_data_mode='app',game_data_folder=None,shared=None,mode=None,learned_caches=()):
    """Stage a sealed App containing its runtime data, then replace the closed App. mode: shader_mode, recorded in the
    App (MNGShaders) for its updates and MNG Launcher."""
    mode=mode or shader_mode()
    validate_runtime_app(out)
    ensure_disk_space(work)
    context=catalog_context(tree)
    shader_record=verify_shader_resources(tree,mode) if mode!='none' else None
    suffix=shader_dirs(tree,mode)[2]
    if mode == 'none':
        folder=tree/'build/warm-lists-none';folder.mkdir(parents=True,exist_ok=True)
        lists=tuple(folder/name for name in ('pso_title.tsv','pso_manifest.tsv'))
        for path in lists:path.write_text('# Kokiri unbundled development build: no prepared pipelines\n')
    else:
        lists=resolve_lists(tree,tree/f'build/warm-lists{suffix}',work/'logs',shared,mode)   # identical lists feed archive and App
    pipelines=compute_pipeline_archive(work,tree,lists,mode) if shader_record else None
    if pipelines:
        # Archive construction records additional patched MSL. Compile those
        # exact sources, then verify PSOs against the same libraries play loads.
        archive_cache=tree/'build/compute-pipelines'/shader_record['chain']
        if suffix:archive_cache=archive_cache.with_name(archive_cache.name+suffix)
        compile_shader_libraries(work,tree,mode,shared,learned_caches=(*learned_caches,archive_cache))
        pipelines=compute_pipeline_archive(work,tree,lists,mode)
        shader_record=verify_shader_resources(tree,mode)
        verify_recorded_variant_coverage(shader_dirs(tree,mode)[1],(*learned_caches,archive_cache))
    receipt=write_preparation_receipt(work,tree,mode,pipelines)
    prepared=shader_bundle(tree,shader_record,mode) if shader_record else None
    opening_overlay=tree/'extracted/oot/opening-patches'
    subprocess.run([sys.executable,GAME/'scripts/make_opening_overlay.py','--romfs',tree/'extracted/oot/romfs',
                    '--output',opening_overlay],check=True)
    temporary=out.with_name('.'+out.name+'.ready')
    if temporary.exists():raise ValueError('unfinished App staging directory exists; left untouched: '+str(temporary))
    mac=temporary/'Contents/MacOS';res=temporary/'Contents/Resources';data=res/'totk'
    clone_file(GAME.parent/'assets/brand/kokiri-mark.png',res/'KokiriMark.png')
    mac.mkdir(parents=True);data.mkdir(parents=True)
    clone_file(work/'build/oot-native',mac/RUNTIME_EXECUTABLE)
    if sha(mac/RUNTIME_EXECUTABLE)!=receipt['artifact_sha256']['runtime_sha256']:
        raise ValueError('staged runtime differs from the verified build input')
    if pipelines:shutil.copytree(pipelines,data/'build/pipelines',copy_function=clone_file)
    for rel in ('build/game-data/oot','build/shader-service','extracted/oot/exefs',
                'extracted/firmware/shared-fonts'):
        shutil.copytree(tree/rel,data/rel,copy_function=clone_file)
    # Runtime libraries are addressed by the exact MSL source hash. Carry any
    # libraries prepared by the build so a new translation chain does not make
    # the player's first start compile those sources synchronously again.
    libraries=tree/'build/shader-libs'
    if prepared:
        build_helpers().place_shader_bundle(prepared,temporary,data)
    elif mode != 'none' and libraries.is_dir():
        shutil.copytree(libraries,data/'build/shader-libs',copy_function=clone_file)
    shutil.copytree(tree/'extracted/oot/romfs',data/'extracted/oot/romfs',copy_function=clone_file,
                    ignore=shutil.ignore_patterns('romfs.bin','.romfs-verified*'))
    shutil.copytree(opening_overlay,data/'extracted/oot/romfs-patches',copy_function=clone_file)
    # Reuse the repository's existing game-data packaging. Its signed helper
    # avoids hashing an unchanged 26 GB image on every native runtime update.
    build_app=build_helpers()
    if game_data_mode=='library':
        game_data_folder=(Path(game_data_folder) if game_data_folder else Path.home()/'Library/Application Support/Kokiri/OcarinaOfTime/GameData').expanduser().resolve()
        repo=GAME.parent
        if game_data_folder==repo or repo in game_data_folder.parents:raise ValueError('game library must remain outside the source checkout')
        build_app.place_library_image(tree,'oot','oot',game_data_folder,expected_romfs=imported_romfs(tree))   # the launcher compares it with romfs-config.txt
    elif game_data_mode=='app':
        logs=work/'logs';logs.mkdir(exist_ok=True)
        bundle=build_app.data_bundle(tree,'oot',logs,bundle_id=RUNTIME_BUNDLE_ID,display_version='131072')
        build_app.place_data_bundle(bundle,temporary,data,'oot')
    else:raise ValueError('invalid Mac game-data mode')
    rewrites=data/'rewritten/oot';rewrites.mkdir(parents=True)
    for module in sorted((tree/'rewritten/oot').glob('*.patched.bin')):clone_file(module,rewrites/module.name)
    clone_file(tree/'build/shader-map.tsv',data/'build/shader-map.tsv')
    title,manifest=lists   # the archive's lists, beside the shader map, where the runtime and the launcher look (build_app.py resolve_lists)
    clone_file(title,data/'build/pso_title.tsv');clone_file(manifest,data/'build/pso_manifest.tsv')
    if pipelines:check_archive_lists(data/'build')   # never an App whose archive was built from other lists
    # VideoToolbox is the primary AV1 decoder; the bounded dav1d fallback is linked statically (build_app.codec_libraries
    # builds it from its pinned source), so the App carries no dylib for it, only its license.
    clone_file(GAME/'third_party/dav1d-COPYING',res/'licenses/dav1d-COPYING')
    info=runtime_metadata(mode,exact_source_commit())
    icon=tree/'build/KokiriAppIcon.icns'
    subprocess.run(['bash',GAME.parent/'macos/scripts/create_icon.sh',
                    GAME.parent/'assets/brand/kokiri-mark.png',icon],check=True)
    clone_file(icon,res/'KokiriAppIcon.icns');info['CFBundleIconFile']='KokiriAppIcon'
    if game_data_mode=='library':info['MNGGameDataFolder']=str(game_data_folder)
    info['KokiriGameUpdate']='131072'
    info['KokiriProductVersion']=PRODUCT_VERSION
    info['KokiriShaders']=mode
    info['KokiriPrepared']=receipt['prepared']
    info['KokiriBuildRuntimeSHA256']=receipt['artifact_sha256']['runtime_sha256']
    info['KokiriPreparationReceiptSHA256']=sha(tree/'build/game-data/oot/preparation-receipt.json')
    info['MNGShaders']=mode   # shader_mode: 'title' is a quick build, filled in by MNG Launcher's 补全着色器 (update_shaders)
    info['MNGContributionFolder']=str(contrib_folder())   # app/launcher.m contrib_file: where players find it, as build_app.py sets it
    build_app.record_update_source(info,work)   # Settings > Update (#2055): the checkout, the work folder and the Python, as build_app.py records them
    commit=exact_source_commit()
    info['KokiriSourceCommit']=commit or 'uncommitted'
    if commit:info['MNGSourceCommit']=commit   # the HUD box and the Update page name the commit the app was built from
    (res/'KokiriCatalogContext.json').write_text(json.dumps(context,sort_keys=True,separators=(',',':'),ensure_ascii=True)+'\n')
    (temporary/'Contents/Info.plist').write_bytes(plistlib.dumps(info));(temporary/'Contents/PkgInfo').write_bytes(b'APPL????')
    subprocess.run(['codesign','--force','--sign','-',temporary],check=True)
    subprocess.run(['codesign','--verify','--strict',temporary],check=True)
    # The installed .app folder stays and takes the new contents: macOS keeps its first-run check of an app with the folder.
    while app_running(out):time.sleep(5)   # the build may have taken a while: the App is replaced only once it is closed
    build_app.install_app(temporary,out)
    # Code signing changes the executable's signature bytes. Final byte hashes
    # live outside the sealed bundle to avoid a circular resource signature.
    fingerprint=dict(schema='kokiri-package-output-v1',app=str(out),
                     build_runtime_sha256=receipt['artifact_sha256']['runtime_sha256'],
                     signed_runtime_sha256=sha(out/'Contents/MacOS'/RUNTIME_EXECUTABLE),
                     info_sha256=sha(out/'Contents/Info.plist'),
                     code_resources_sha256=sha(out/'Contents/_CodeSignature/CodeResources'),
                     preparation_receipt_sha256=sha(out/'Contents/Resources/totk/build/game-data/oot/preparation-receipt.json'))
    (work/'logs/package-output.json').write_text(json.dumps(fingerprint,indent=2)+'\n')
    return out

def missing_compute(rows,index_ids):
    """The variants of the planned compute rows ("C\\t<variant>") the archive index lacks (index ids: 'c' + 40 hex of the
    row's SHA-256, as mac_pipeline_files names them)."""
    return [row[2:] for row in rows if 'c'+hashlib.sha256(row[2:].encode()).hexdigest()[:40] not in index_ids]

def missing_compute_message(missing,arch,log):
    """#2070: name the shaders whose compute pipelines this Mac's Metal compiler could not build, instead of a bare error."""
    return (f"{len(missing)} compute pipeline{'s' if len(missing)!=1 else ''} could not be built on this Mac ({arch}): "
            +', '.join(missing[:10])+(' …' if len(missing)>10 else '')
            +f". The Metal compiler failed on {'them' if len(missing)!=1 else 'it'}; the reason is in {log}. "
            'Please report the shader key and the log lines in an issue.')

def app_running(app):
    """The game is running from this App. The Update window runs the same executable as "--update-install <pid>" or
    "--update-check" and waits for this installer, so it is not the game (#1784; build_app.py wait_until_closed, 577e4576)."""
    try:
        info = plistlib.loads((Path(app)/'Contents/Info.plist').read_bytes())
    except FileNotFoundError:
        info = {}
    name = info.get('CFBundleExecutable', RUNTIME_EXECUTABLE)
    if name not in (RUNTIME_EXECUTABLE, 'OcarinaOfTime'):
        raise ValueError('unrecognized Kokiri runtime executable')
    executable=str((Path(app)/'Contents/MacOS'/name).resolve())
    table=subprocess.run(['ps','-axo','pid=,comm='],capture_output=True,text=True,check=True).stdout.splitlines()
    for line in table:
        fields=line.strip().split(maxsplit=1)
        if len(fields)!=2 or fields[1]!=executable:continue
        args=subprocess.run(['ps','-ww','-p',fields[0],'-o','args='],capture_output=True,text=True)
        if args.returncode==1 and not args.stdout.strip():continue   # it exited between the two snapshots
        args.check_returncode()
        command=args.stdout.strip()
        options=command[len(executable)+1:].split() if command.startswith(executable+' ') else []
        if options==['--update-check'] or (len(options)==2 and options[0]=='--update-install' and options[1].isdigit() and int(options[1])>0):continue
        return True
    return False

def update_blocker(work, mode='full'):
    """Why this work folder cannot take an update without the full build ('' when it can): its last full build's files
    are missing, its shaders are of another translation chain or translator than this repository's (the seed's
    translation_context), or its rewritten modules are not this repository's. update_runtime refuses then, and
    update_runtime.py --plan (MNG Launcher, tools/mng.py) answers "full" instead of an express update that would stop
    (2026-11-13: chain v27 made the Launcher start an express update that refused at once).
    A 'title' App's update makes its few shaders again in a minute or two, so neither an earlier seed nor the same
    translation chain is needed for it: only the game files and this repository's rewritten modules."""
    work=Path(work);tree=work/'oot';seed,libraries,_=shader_dirs(tree,'title' if mode=='title' else 'full')
    manifest=seed/'seed-manifest.json'
    shaders=() if mode=='title' else (manifest,libraries/'libraries-manifest.json')
    for needed in (*shaders,tree/'extracted/oot/romfs/index.json',tree/'rewritten/oot'):
        if not needed.exists():return f'{needed} is missing: run the full build once with this work folder'
    if mode!='title':
        scripts=str(GAME/'scripts')
        if scripts not in sys.path:sys.path.insert(0,scripts)
        from prepare_ns2_seed import translation_context
        try:metadata=json.loads(manifest.read_text())
        except ValueError:return f'{manifest} is not readable: run the full build'
        native=ready_shader_service(work)
        if not native:return 'the current verified shader toolchain is missing: run the full build'
        if metadata.get('translation_context_sha256')!=translation_context(native/'totk_xlate',metadata.get('nvn_depth_mode')):
            return 'the translation chain or the translator changed, or the seed is older than the request checks (2026-11-11): the shaders need the full build'
    expected=json.loads((GAME/'assets/expected-v131072.json').read_text())
    for name,want in expected['rewritten_sha256'].items():
        if sha(tree/'rewritten/oot'/name)!=want:return 'rewritten module differs from this repository: run the full build: '+name
    return ''

def update_runtime(app,work=None,out=None,shared=None,learned_caches=()):
    """Put a new runtime into an App this build made, keeping its shaders: rebuild the runtime and its pipeline archive only.
    The translations and Metal libraries of the last full build are reused; a new translation chain, translator or request
    code needs the full build. A running game is waited for, not closed."""
    app=Path(app).resolve();validate_runtime_app(app)
    destination=Path(out).expanduser().resolve() if out else app
    if out and destination==app:raise ValueError('staged rebuild output must differ from the source app')
    if destination.suffix!='.app':raise ValueError('staged rebuild output must end in .app')
    external_workspace(destination);validate_runtime_app(destination)
    work=external_workspace(work if work else build_helpers().recorded_work_folder(app,'Kokiri-work')[0]);ensure_disk_space(work)   # the app's own record first
    if out:
        validate_staged_paths(app,destination,work)
    repo=GAME.parent
    if work==repo or repo in work.parents:raise ValueError('game build data must remain outside the source checkout')
    tree=work/'oot'
    mode=shader_mode(app)
    if mode=='none':mode='full'   # an update always carries shaders, as before (an App of OOT_BUNDLE_SHADERS=0 gets them all)
    ensure_shader_service(work)
    blocker=update_blocker(work,mode)
    if blocker:raise ValueError(blocker)
    native=ready_shader_service(work)
    if sha(tree/'build/shader-service/totk_xlate')!=sha(native/'totk_xlate'):
        raise ValueError('work shader translator differs from source-verified serviced tool; run the full build')
    told=False
    while destination==app and app_running(app):
        if not told:print('waiting for the game to close',flush=True);told=True
        time.sleep(5)
    start=time.monotonic()
    sync_tree(GAME,tree)
    logs=work/'logs';logs.mkdir(exist_ok=True)
    print('building the runtime',flush=True)
    env=dict(os.environ,DM_RULESET='native',DM_PRIVATE_GATES='0')
    with (logs/'native-runtime.log').open('w') as f:
        subprocess.run(['make','-C',GAME,'WORK='+str(make_path(work)),'-j'+str(shader_jobs())],cwd=work,stdout=f,stderr=subprocess.STDOUT,check=True,env=env)
    def run(cmd,name,cwd=tree):
        print(name,flush=True)
        ensure_disk_space(work)
        with (logs/(name+'.log')).open('w') as f:subprocess.run([str(x)for x in cmd],cwd=cwd,env=env,stdout=f,stderr=subprocess.STDOUT,check=True)
    # The new runtime asks for every translation again: the ones whose request is the same are kept, the others made again
    # (prepare_ns2_seed.py, totk_shader_rt.m seed_verified), and only the libraries whose source changed are compiled.
    shader_steps(work,tree,logs,run,mode=mode,shared=shared,learned_caches=learned_caches)
    folder=plistlib.loads((app/'Contents/Info.plist').read_bytes()).get('MNGGameDataFolder')
    if out and folder:
        # Staging must never publish into the original player's mutable library.
        folder=work/'staged-game-data'
    package_app(work,tree,destination,'library' if folder else 'app',folder,mode=mode,shared=shared,learned_caches=learned_caches)
    print(f'built {destination} in {time.monotonic()-start:.0f} s',flush=True)

def update_shaders(app,listfile,work=None):
    """Only the shaders and pipelines of an App this build made, from another shared list (shader_update.py: the newest
    from GitHub; user 2026-11-13): the listed variants the seed lacks translated by the work folder's game binary (the
    translations made before are kept), their libraries compiled, the warm-up lists resolved from that list and the
    pipeline archive checked against them, then the App packaged as update_runtime does. The work folder is used as it
    is: no source sync and no runtime build, so the shaders are of the runtime the App carries."""
    app=Path(app).resolve();validate_runtime_app(app)
    work=external_workspace(work if work else build_helpers().recorded_work_folder(app,'Kokiri-work')[0]);ensure_disk_space(work)
    tree=work/'oot'
    # the App's own seed (a quick App's is shader-seed-title): its translations are of this repository's chain and translator
    manifest=shader_dirs(tree,shader_mode(app))[0]/'seed-manifest.json'
    for needed in (manifest,tree/'extracted/oot/romfs/index.json',work/'build/oot-native'):
        if not needed.exists():raise ValueError(f'{needed} is missing: the work folder cannot translate shaders (a full build makes it)')
    scripts=str(GAME/'scripts')
    if scripts not in sys.path:sys.path.insert(0,scripts)
    from prepare_ns2_seed import translation_context
    metadata=json.loads(manifest.read_text())
    native=ready_shader_service(work)
    if not native:raise ValueError('the current verified shader toolchain is missing: run the full build')
    if metadata.get('translation_context_sha256')!=translation_context(native/'totk_xlate',metadata.get('nvn_depth_mode')):
        raise ValueError('this repository translates for another chain or translator than the App\'s shaders: update the App first')
    told=False
    while app_running(app):
        if not told:print('waiting for the game to close',flush=True);told=True
        time.sleep(5)
    start=time.monotonic();logs=work/'logs';logs.mkdir(exist_ok=True)
    env=dict(os.environ,DM_RULESET='native',DM_PRIVATE_GATES='0')
    def run(cmd,name,cwd=tree):
        print(name,flush=True)
        ensure_disk_space(work)
        with (logs/(name+'.log')).open('w') as f:subprocess.run([str(x)for x in cmd],cwd=cwd,env=env,stdout=f,stderr=subprocess.STDOUT,check=True)
    shader_steps(work,tree,logs,run,shared=listfile)   # every shader: a quick App becomes a full one (补全着色器)
    folder=plistlib.loads((app/'Contents/Info.plist').read_bytes()).get('MNGGameDataFolder')
    package_app(work,tree,app,'library' if folder else 'app',folder,shared=listfile,mode='full')
    print(f'updated the shaders of {app} in {time.monotonic()-start:.0f} s',flush=True)

def compile_shader_libraries(work,tree,mode='full',shared=None,learned_caches=()):
    seed,libraries,_=shader_dirs(tree,mode)
    subset=shader_subset(tree,shared or GAME/'assets/shader_list.tsv') if mode=='full' else None
    py=work/'venv/bin/python'
    if not py.exists():py=Path(sys.executable)
    cmd=[py,GAME/'scripts/build_shader_libs.py','--cache',seed,'--out',libraries,'--jobs',str(shader_jobs()),
         *(['--only',subset] if subset else []),
         *[arg for cache in learned_caches for arg in ('--variant-cache',Path(cache))]]
    with (work/'logs/compile-shader-libraries.log').open('w') as log:
        subprocess.run([str(c) for c in cmd],cwd=tree,stdout=log,stderr=subprocess.STDOUT,check=True)

def shader_steps(work,tree,logs,run,device=False,shared=None,mode='full',learned_caches=()):
    """The seed of the full build and of a runtime update: every translation the runtime asks for, a cached one kept when
    the runtime's request for it is the one it was made from (prepare_ns2_seed.py; user 2026-11-11: "如何让 快速更新 不要这么
    容易失效"), and on the Mac the Metal libraries, compiled only where the translation changed (build_shader_libs.py)."""
    py=work/'venv/bin/python'
    shared=Path(shared) if shared else GAME/'assets/shader_list.tsv'   # recorded bind states and pipelines (scripts/shader_list.py merge): listed variants and the warm-up lists; shader_update.py gives the newest from GitHub
    only=title_shader_file(tree,shared) if mode=='title' else None   # a quick build: the title rows' shaders only
    seed,libraries,_=shader_dirs(tree,mode)
    run([py,GAME/'scripts/prepare_ns2_seed.py','--version','oot','--depth-mode','minus-w',
        '--binary',work/'build/oot-native','--translator',tree/'build/shader-service/totk_xlate',
        '--jobs',str(shader_jobs()),'--logs',logs,'--output',seed,
        *(['--list',shared] if shared.is_file() else []),*(['--only',only] if only else [])],'prepare-shader-seed')
    if not device:
        compile_shader_libraries(work,tree,mode,shared,learned_caches)

def shader_jobs():
    """A bounded budget shared by runtime builds, translation, libraries and archives."""
    jobs=int(os.environ.get('KOKIRI_BUILD_JOBS','2'))
    if not 1<=jobs<=8:raise ValueError('KOKIRI_BUILD_JOBS must be between 1 and 8')
    return jobs

def library_image(args,out):
    """The RomFS image an earlier build put in the game library (package_app 'library': <folder>/oot/romfs.bin), to take
    instead of packing the dump's 26 GB again (import_dump.py adopt_image; 2026-11-12): the folder --mac-game-data-folder
    names, else the one the app being replaced records (MNGGameDataFolder), else the default one. None when there is none."""
    folders=[args.mac_game_data_folder]
    try:folders.append(plistlib.loads((out/'Contents/Info.plist').read_bytes()).get('MNGGameDataFolder'))
    except (OSError,ValueError):pass
    folders.append(Path.home()/'Library/Application Support/Kokiri/OcarinaOfTime/GameData')
    for folder in folders:
        if folder and (Path(folder).expanduser()/'oot/romfs.bin').is_file():return Path(folder).expanduser()/'oot/romfs.bin'
    return None

def build(args, source):
    if args.platform not in ('macos','ios'):raise ValueError('Ocarina of Time has macOS and iOS build paths only')
    device=args.platform=='ios'
    if args.update or args.dlc or args.mod:raise ValueError('use the complete original update 131072 in the dump/NUP')
    source=Path(source).resolve()
    out=args.out.expanduser().resolve() if args.out else source.parent/'Kokiri Game.app'
    # without --work: the folder the app records, else MacNativeGames-work/oot beside the apps folder (build_app.default_work)
    work,why=(args.work.expanduser().resolve(),'given with --work') if args.work else build_helpers().default_work(out,'oot')
    print(f'work folder {work} ({why})',flush=True)
    repo=GAME.parent
    if work==repo or repo in work.parents:raise ValueError('game build data must remain outside the source checkout')
    if out.suffix!='.app' and not (device and out.suffix=='.ipa'):raise ValueError('output must end in .app'+(' or .ipa' if device else ''))
    if out==repo or repo in out.parents:raise ValueError('App must remain outside the source checkout')
    if args.vr or args.native_4k or args.native_5k:raise ValueError('this title currently uses its original rendering options')
    # Nothing to install from Homebrew (2026-11-12): the rewrite check disassembles with Xcode's llvm-objdump
    # (third_party/d2r/structck.py) and the opening overlay cuts its clip in Python (scripts/webm_one_frame.py).
    # Close this title normally before changing its resource workspace or App.
    # The input command follows the same save-safe window close as normal play.
    validate_runtime_app(out)
    if not (work/'oot/extracted/oot/romfs/romfs.bin').is_file() and available_space(work) < 40 * (1 << 30):
        raise OSError('a fresh game import requires 40 GiB free; existing game data is left untouched')
    executable=out/'Contents/MacOS'/RUNTIME_EXECUTABLE
    def running():
        processes=subprocess.check_output(['ps','-axo','comm='],text=True).splitlines()
        return str(executable) in {p.strip()for p in processes}
    if running():
        raise RuntimeError('close Kokiri Game before rebuilding; no input was sent')
    work=external_workspace(work);ensure_disk_space(work)
    work.mkdir(parents=True,exist_ok=True);tree=work/'oot';logs=work/'logs';logs.mkdir(exist_ok=True)
    sync_tree(GAME,tree)
    env=dict(os.environ,DM_RULESET='native',DM_PRIVATE_GATES='0')
    def run(cmd,name,cwd=tree):
        print(name,flush=True)
        ensure_disk_space(work)
        with (logs/(name+'.log')).open('w') as f:subprocess.run([str(x)for x in cmd],cwd=cwd,env=env,stdout=f,stderr=subprocess.STDOUT,check=True)
    py=work/'venv/bin/python'
    if not py.exists():run([sys.executable,'-m','venv',work/'venv'],'python-environment',work)
    dependencies=subprocess.run([py,'-c','import lz4.block,capstone,zbic'],capture_output=True)
    if dependencies.returncode:run([py,'-m','pip','install','-r',GAME/'requirements.txt'],'python-dependencies',work)
    extracted=tree/'extracted/oot';index=extracted/'romfs/index.json'
    expected=json.loads((GAME/'assets/expected-v131072.json').read_text())
    if source.is_file():run([py,'scripts/import_nup.py',source,'--output',extracted],'import-original-nup')
    elif not index.exists():
        print('RomFS: there is no imported game data in this work folder',flush=True)   # a long step says why (2026-11-11)
        library=library_image(args,out)
        if library:
            try:
                run([py,'scripts/import_dump.py',source,'--output',extracted,'--update','131072','--adopted-image',library],'import-original-dump')
                romfs_pin.check(extracted/'romfs')
                print(f'RomFS: taken from the game library ({library}), an earlier pack of this dump: not packed again',flush=True)
            except (subprocess.CalledProcessError,ValueError) as e:
                print(f'RomFS: the game library image {library} is not this dump\'s ({e}): packing the folder',flush=True)
                shutil.rmtree(extracted,ignore_errors=True);library=None
        if not library:run([py,'scripts/import_dump.py',source,'--output',extracted,'--update','131072'],'import-original-dump')
    code=extracted/'exefs'
    for name,digest in expected['exefs_sha256'].items():
        if sha(code/name)!=digest:raise ValueError('unsupported or damaged original ExeFS: '+name)
    check=romfs_pin.check(extracted/'romfs')   # every file of update 131072 by size and hash (#2009, #2011); ValueError names what differs
    print(f"RomFS: the {check['files']} files of update 131072 verified"+(f"; {len(check['extra'])} more files the list does not name: {', '.join(check['extra'][:20])}" if check['extra'] else '')
          +(f"; {len(check['variant'])} of another retail package (listed size, other bytes, checked against the package's own hashes): {', '.join(check['variant'][:20])}" if check['variant'] else ''),flush=True)
    rom=json.loads(index.read_text())
    if 'directories' not in rom:
        folder=source/'updates/131072/romfs'
        if not folder.is_dir():raise ValueError('directory metadata missing from original dump')
        rom['directories']=sorted(str(p.relative_to(folder))for p in folder.rglob('*')if p.is_dir());index.write_text(json.dumps(rom)+'\n')
    run([py,'scripts/prepare_modules.py',code,'--output',extracted/'elf'],'verify-original-modules')
    rewritten=tree/'rewritten/oot';rewritten.mkdir(parents=True,exist_ok=True)
    def rewrite(name):
        target=rewritten/(name+'.patched.bin');want=expected['rewritten_sha256'].get(target.name)
        if not target.exists() or sha(target)!=want:run([py,'third_party/d2r/patch_nso.py',code/name,rewritten,name],'rewrite-'+name)
        run([py,'third_party/d2r/structck.py',rewritten,name,code/name],'verify-rewrite-'+name)
        if sha(target)!=want:raise ValueError('rewrite differs from verified rules: '+name)
    with concurrent.futures.ThreadPoolExecutor(2)as pool:list(pool.map(rewrite,['main','subsdk0','sdk']))
    hashes={str(p.relative_to(tree)):sha(p)for p in [*(code/n for n in ('main','subsdk0','sdk')),*(rewritten/(n+'.patched.bin')for n in ('main','subsdk0','sdk'))]}
    report=tree/'analysis/oot-port/phase12-validation.json';report.parent.mkdir(parents=True,exist_ok=True)
    report.write_text(json.dumps(dict(format=1,status='pass',rom_version='oot',module_file_sha256=hashes),indent=2)+'\n')
    for script in ('prepare_runtime.py','prepare_romfs_backend.py'):run([py,'scripts/'+script,'--version','oot'],script[:-3])
    fonts=tree/'extracted/firmware/shared-fonts'
    if args.shared_fonts and args.shared_fonts.expanduser().resolve()!=fonts.resolve():
        shutil.copytree(args.shared_fonts.expanduser().resolve(),fonts,dirs_exist_ok=True)
    if not (fonts/'manifest.json').exists():raise ValueError('pass --shared-fonts with the six verified firmware fonts')
    run([py,'scripts/prepare_shared_fonts.py','--version','oot'],'prepare-shared-fonts')
    service=tree/'build/shader-service';service.mkdir(parents=True,exist_ok=True)
    toolchain=ensure_shader_service(work)
    binary=toolchain/'totk_xlate'
    if sha(binary)!=(binary.with_suffix('.sha256')).read_text().strip():raise ValueError('shader translator checksum mismatch')
    temporary_service=service/'totk_xlate.new'
    shutil.copy2(binary,temporary_service);os.replace(temporary_service,service/'totk_xlate')
    proof=toolchain/'oot_write_proof.dylib'
    if sha(proof)!=proof.with_suffix('.dylib.sha256').read_text().strip():raise ValueError('shader proof analyzer checksum mismatch')
    shutil.copy2(proof,service/proof.name)
    shutil.copy2(proof.with_name('SPIRV-Tools.LICENSE'),service/'SPIRV-Tools.LICENSE')
    (tree/'build/shader-map.tsv').write_text('# TOTK control-code-sha256-v1\n')
    run(['make','-C',GAME,'WORK='+str(make_path(work)),'-j'+str(shader_jobs())],'native-runtime',work)
    mode='full' if device else shader_mode()
    if mode=='none':print('Shaders are not bundled (OOT_BUNDLE_SHADERS=0): translated at first use',flush=True)
    else:
     shader_steps(work,tree,logs,run,device,mode=mode,shared=getattr(args,'shader_list',None),learned_caches=getattr(args,'learned_cache',()))
    if device:
     # The phone's own Metal libraries and pipeline archive: the seed above is compiled for the device in ios/tools/build_ipa.py.
     run([py,tree/'ios/tools/build_ipa.py','--tree',tree,'--out',out,'--version','oot','--logs',logs,'--app-name','OcarinaOfTime','--bundle-id','org.macnativegames.oot',
         *([] if os.environ.get('OOT_IOS_ALL_SHADERS')=='1' else ['--listed-shaders-only']),   # user 2026-11-09: only the shaders the render pipelines use, for now
         *(['--image-outside'] if args.ios_game_data=='documents' else []),*[x for g in args.device_gpu or [] for x in ('--device-gpu',g)]],'build-ipa')
     remove_device_reminder()
    else:
     package_app(work,tree,out,'library' if args.mac_game_data_folder else args.mac_game_data,args.mac_game_data_folder,mode=mode,
                 shared=getattr(args,'shader_list',None),learned_caches=getattr(args,'learned_cache',()))
    print(f'Built {out}; native gameplay validation is recorded separately.',flush=True)
    chain=re.search(r'#define DMSH_CHAIN "([^"]+)"\s*/\* game: oot\b',(GAME/'third_party/d2r_gfx/gfx/nvn/dmsh_chain.h').read_text())[1]   # the shared layer's line for this game
    return out,tree,expected,chain


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('source', nargs='?', type=Path, help='owned update 131072 .nup or dump folder')
    parser.add_argument('-o', '--out', type=Path, help='Kokiri Game.app output, outside this repository')
    parser.add_argument('--work', type=Path, help='external workspace for generated game data and tools')
    parser.add_argument('--jobs',type=int,choices=range(1,9),default=2,help='bounded worker budget (default 2)')
    parser.add_argument('--shader-list',type=Path,help='explicit merged shader metadata list, including learned pipelines')
    parser.add_argument('--learned-cache',type=Path,action='append',default=[],help='compatible runtime cache containing patched MSL (repeatable)')
    parser.add_argument('--shared-fonts', type=Path, help='folder of six verified .bfttf fonts and manifest.json')
    parser.add_argument('--mac-game-data', choices=('app', 'library'), default='app')
    parser.add_argument('--mac-game-data-folder', type=Path)
    parser.add_argument('--rebuild', type=Path, metavar='APP', help='rebuild an existing Kokiri runtime app')
    args = parser.parse_args(argv)
    if args.shader_list:args.shader_list=args.shader_list.expanduser().resolve()
    args.learned_cache=[p.expanduser().resolve()for p in args.learned_cache]
    os.environ['KOKIRI_BUILD_JOBS']=str(args.jobs)
    if sys.version_info < (3, 14):
        parser.error('Python 3.14 or later is required')
    if args.rebuild:
        if args.source:
            parser.error('--rebuild cannot be combined with source')
        if args.out and args.work is None:parser.error('staged --rebuild --out requires an independently cloned --work')
        update_runtime(args.rebuild,args.work,out=args.out,shared=args.shader_list,learned_caches=args.learned_cache)
        return 0
    if args.source is None:
        parser.error('source is required unless --rebuild is given')
    if not args.source.expanduser().exists():
        parser.error('the owned game source does not exist')
    args.platform = 'macos'
    args.update = args.dlc = args.mod = None
    args.vr = args.native_4k = args.native_5k = False
    args.device_gpu = None
    args.ios_game_data = 'app'
    build(args, args.source.expanduser())
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
