"""Standalone Metal compiler discovery, adapted from MacNativeGames (MIT)."""
import os
import hashlib
import json
import re
import platform
import shlex
from pathlib import Path
import subprocess
import tempfile

METAL_FLAGS = ['-mmacosx-version-min=26.0', '-fmetal-math-mode=safe']


def file_content_identity(path):
    path = Path(path).resolve(strict=True)
    before = path.stat()
    value = hashlib.sha256()
    with path.open('rb') as stream:
        for block in iter(lambda: stream.read(1 << 20), b''):
            value.update(block)
    after = path.stat()
    if (before.st_dev, before.st_ino, before.st_size, before.st_mtime_ns, before.st_ctime_ns) != (
        after.st_dev, after.st_ino, after.st_size, after.st_mtime_ns, after.st_ctime_ns):
        raise ValueError('compiler component changed while hashing: '+str(path))
    return dict(path=str(path), sha256=value.hexdigest(), size=after.st_size)


def driver_commands(text):
    commands = [shlex.split(line.strip()) for line in text.splitlines() if line.lstrip().startswith('"')]
    if (len(commands) < 2 or sum('-cc1' in command for command in commands) != 1 or
        '-cc1' in commands[-1]):
        raise ValueError('Metal library driver plan lacks a unique frontend and selected linker')
    return commands


def tool_dependencies(path, env, os_build):
    """Audit declared load dependencies; system cache contents are bound to OS build."""
    queue, visited, out = [Path(path).resolve()], set(), []
    while queue:
        loader = queue.pop(0)
        if loader in visited:
            continue
        visited.add(loader)
        loader_hash = file_content_identity(loader)['sha256']
        probe = subprocess.run(['otool', '-arch', platform.machine(), '-L', str(loader)],
                               capture_output=True, text=True, env=env)
        if probe.returncode:
            raise ValueError('cannot audit compiler load dependencies: '+str(loader))
        names = [line.strip().split(' (compatibility version', 1)[0] for line in probe.stdout.splitlines()
                 if line[:1].isspace() and ' (compatibility version' in line]
        if names and loader.suffix == '.dylib' and Path(names[0]).name == loader.name:
            names = names[1:]  # otool -L lists a dylib's own install ID first
        rpaths = None
        for name in dict.fromkeys(names):
            record = dict(loader_sha256=loader_hash, install_name=name)
            if name.startswith(('/usr/lib/', '/System/Library/')):
                record.update(binding='os-build-system-component', os_build=os_build)
            else:
                candidates = []
                if name.startswith('@loader_path/'):
                    candidates = [loader.parent/name[len('@loader_path/'):]]
                elif name.startswith('@executable_path/'):
                    candidates = [Path(path).resolve().parent/name[len('@executable_path/'):]]
                elif name.startswith('@rpath/'):
                    if rpaths is None:
                        loads = subprocess.run(['otool', '-arch', platform.machine(), '-l', str(loader)],
                                               capture_output=True, text=True, env=env)
                        if loads.returncode:
                            raise ValueError('cannot audit compiler rpaths: '+str(loader))
                        rpaths = re.findall(r'cmd LC_RPATH\s+cmdsize \d+\s+path (.+?) \(offset \d+\)', loads.stdout)
                    for rpath in rpaths:
                        expanded = rpath.replace('@loader_path', str(loader.parent)).replace(
                            '@executable_path', str(Path(path).resolve().parent))
                        candidates.append(Path(expanded)/name[len('@rpath/'):])
                elif Path(name).is_absolute():
                    candidates = [Path(name)]
                resolved = next((candidate for candidate in candidates if candidate.is_file()), None)
                if resolved is None:
                    raise ValueError('unresolved non-system compiler dependency: '+name)
                identity = file_content_identity(resolved)
                record.update(binding='hashed-file', **identity)
                queue.append(Path(identity['path']))
            out.append(record)
    return out


def resource_headers_identity(resource_dir):
    """Hash the selected Metal header tree by relative names and file contents."""
    headers = Path(resource_dir)/'include/metal'
    files = sorted(path for path in headers.rglob('*') if path.is_file())
    if not files:
        raise ValueError('Metal compiler resource headers are unavailable: '+str(headers))
    content = hashlib.sha256()
    size = 0
    for path in files:
        raw = path.read_bytes()
        size += len(raw)
        content.update(path.relative_to(headers).as_posix().encode()+b'\0')
        content.update(hashlib.sha256(raw).digest())
    return dict(path=str(headers.resolve()), content_sha256=content.hexdigest(), files=len(files), bytes=size)


def compiler_context_key(observation):
    """Stable compilation identity: paths and diagnostic driver text are provenance."""
    context = {key: observation.get(key) for key in (
        'qualified', 'backend', 'version', 'executable_sha256',
        'effective_flags', 'effective_target', 'sdk_mode')}
    context['schema'] = 'kokiri-metal-compiler-context-v2'
    context['resource_headers_sha256'] = observation.get('resource_headers', {}).get('content_sha256')
    if not observation.get('qualified'):
        context['reason'] = observation.get('reason')
    else:
        components = observation.get('tool_components', [])
        roles = [component.get('role') for component in components]
        if (not all(role in roles for role in ('driver', 'frontend', 'linker')) or
            any(not re.fullmatch('[0-9a-f]{64}', component.get('executable_sha256', '')) for component in components) or
            not isinstance(observation.get('required_files'), list) or
            not observation.get('host_identity', {}).get('os_build')):
            raise ValueError('qualified Metal compiler observation lacks component or host identities')
        context['tool_components'] = []
        for component in components:
            if not isinstance(component.get('dependencies'), list):
                raise ValueError('qualified Metal compiler observation lacks dependency audit')
            dependencies = []
            for dependency in component['dependencies']:
                if dependency.get('binding') == 'hashed-file':
                    if not re.fullmatch('[0-9a-f]{64}', dependency.get('sha256', '')):
                        raise ValueError('compiler dependency lacks content identity')
                elif (dependency.get('binding') != 'os-build-system-component' or
                      dependency.get('os_build') != observation['host_identity']['os_build']):
                    raise ValueError('compiler dependency lacks system identity')
                dependencies.append({key: dependency.get(key) for key in (
                    'loader_sha256', 'install_name', 'binding', 'sha256', 'os_build')})
            context['tool_components'].append(dict(role=component['role'],
                executable_sha256=component['executable_sha256'], dependencies=dependencies))
        context['required_files'] = []
        for required in observation['required_files']:
            if not re.fullmatch('[0-9a-f]{64}', required.get('sha256', '')):
                raise ValueError('compiler invocation input lacks content identity')
            context['required_files'].append(dict(role=required['role'], sha256=required['sha256']))
        context['host_identity'] = observation['host_identity']
        context['effective_invocations'] = observation.get('effective_invocations')
    encoded = json.dumps(context, sort_keys=True, separators=(',', ':')).encode()
    return hashlib.sha256(encoded).hexdigest()


def compiler_observation(metal, version, env, flags):
    """Record what this driver actually chooses; JIT equivalence is not implied."""
    if not Path(metal).is_file():
        return dict(qualified=False, backend='metal', version=version, effective_flags=list(flags),
                    effective_target=None, sdk_mode='unobserved',
                    reason='compiler executable unavailable')
    # Match build_shader_libs compile_one: no -c; this invocation produces a
    # library through the selected frontend AND linker. -### performs no codegen.
    with tempfile.TemporaryDirectory(prefix='kokiri-metal-identity-') as folder:
        source, output = Path(folder)/'identity.metal', Path(folder)/'identity.partial'
        source.write_text('')
        command=[metal,'-###',*flags,'-o',str(output),str(source)]
        result=subprocess.run(command,capture_output=True,text=True,env=env)
    if result.returncode:
        raise ValueError('cannot observe Metal compiler target: '+result.stderr)
    triples=re.findall(r'"-triple" "([^"]+)"',result.stderr)
    if len(triples)!=1:raise ValueError('Metal driver did not report one effective target')
    resources=re.findall(r'"-resource-dir" "([^"]+)"',result.stderr)
    if len(resources)!=1:raise ValueError('Metal driver did not report one resource directory')
    headers=resource_headers_identity(resources[0])
    sysroots=re.findall(r'"-isysroot" "([^"]+)"',result.stderr)
    if sysroots:raise ValueError('Metal SDK sysroot compilation needs a separate SDK content identity')
    build = subprocess.run(['sw_vers', '-buildVersion'], capture_output=True, text=True, env=env)
    if build.returncode or not build.stdout.strip():
        raise ValueError('cannot bind system compiler dependencies to an OS build')
    host = dict(os_build=build.stdout.strip(), machine=platform.machine(), kernel_release=platform.release())
    commands = driver_commands(result.stderr)
    selected = [('driver', Path(metal))]+[
        ('frontend' if '-cc1' in argv else 'linker' if index == len(commands)-1 else 'compiler-tool', Path(argv[0]))
        for index, argv in enumerate(commands)]
    components = []
    for role, executable in selected:
        identity = file_content_identity(executable)
        components.append(dict(role=role, path=identity['path'], executable_sha256=identity['sha256'],
                               size=identity['size'], dependencies=tool_dependencies(executable, env, host['os_build'])))
    component_paths = {Path(component['path']) for component in components}
    planned_outputs = {argv[index+1] for argv in commands for index, arg in enumerate(argv[:-1]) if arg == '-o'}
    required, seen = [], set()
    for argv in commands:
        for argument in argv[1:]:
            candidate = Path(argument)
            if (candidate.is_absolute() and argument not in planned_outputs and
                candidate.suffix in ('.a', '.dylib', '.tbd', '.bc') and not candidate.is_file()):
                raise ValueError('selected compiler invocation input is missing: '+argument)
            if candidate.is_absolute() and candidate.is_file():
                resolved = candidate.resolve()
                if str(resolved).startswith(str(Path(folder).resolve())+os.sep) or resolved in component_paths or resolved in seen:
                    continue
                required.append(dict(role='selected-invocation-input', **file_content_identity(resolved)))
                seen.add(resolved)
    def stable_argument(argument):
        for probe in sorted({folder, str(Path(folder).resolve())}, key=len, reverse=True):
            argument = argument.replace(probe, '<probe-dir>')
        return '<intermediate.air>' if re.search(r'/identity-[0-9a-f]+\.air$', argument) else argument
    invocations = [[stable_argument(argument) for argument in argv] for argv in commands]
    sdk={}
    for key,arg in [('path','--show-sdk-path'),('version','--show-sdk-version')]:
        probe=subprocess.run(['xcrun','--sdk','macosx',arg],capture_output=True,text=True,env=env)
        sdk[key]=probe.stdout.strip() if probe.returncode==0 else None
    return dict(qualified=True,backend='metal',path=str(Path(metal).resolve()),version=version,
                executable_sha256=components[0]['executable_sha256'],
                effective_flags=list(flags),effective_target=triples[0],driver_command=command,
                driver_plan=result.stderr,driver_plan_sha256=hashlib.sha256(result.stderr.encode()).hexdigest(),
                resource_dir=resources[0],resource_headers=headers,
                observation_schema=2,tool_components=components,required_files=required,
                host_identity=host,effective_invocations=invocations,
                sdk_mode='compiler-default-resource-headers',available_macos_sdk=sdk,
                developer_dir=env.get('DEVELOPER_DIR'),
                limitation='Declared library-driver tools, explicit file inputs and non-system load dependencies are hashed; system components are bound to OS build. Unseen dlopen components, runtime JIT and actual library loading are not established.')


def metal_compiler():
    """Return the executable, exact version and environment, or None."""
    developers = [os.environ.get('DEVELOPER_DIR', '')]
    selected = subprocess.run(['xcode-select', '-p'], capture_output=True, text=True)
    if selected.returncode == 0:
        developers.append(selected.stdout.strip())
    for root in (Path('/Applications'), Path.home() / 'Applications'):
        developers.extend(str(p / 'Contents/Developer') for p in sorted(root.glob('Xcode*.app')))
    for developer in dict.fromkeys(d for d in developers if d):
        env = dict(os.environ, DEVELOPER_DIR=developer)
        found = subprocess.run(['xcrun', '--find', 'metal'], capture_output=True, text=True, env=env)
        if found.returncode or not found.stdout.strip():
            continue
        metal = found.stdout.strip()
        version = subprocess.run([metal, '--version'], capture_output=True, text=True, env=env)
        if version.returncode == 0 and version.stdout:
            return metal, version.stdout.splitlines()[0], env
    return None
