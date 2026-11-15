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
QUALIFIED_DRIVER_FLAGS = (*METAL_FLAGS, '-fpreserve-invariance', '-fwrapv')
CONFLICTING_COMPILE_FLAGS = frozenset(('-fno-wrapv', '-fno-preserve-invariance', '-fstrict-overflow',
                                      '-ffast-math', '-funsafe-math-optimizations'))


def validate_driver_flags(flags):
    if (not isinstance(flags, list) or len(flags) != len(QUALIFIED_DRIVER_FLAGS) or
        any(not isinstance(flag, str) for flag in flags) or set(flags) != set(QUALIFIED_DRIVER_FLAGS)):
        raise ValueError('qualified Metal compiler flags must be the exact four safe driver options')


def validate_invocation_math(invocations):
    for argv in invocations:
        for flag in argv[1:]:
            if (flag.split('=', 1)[0] in CONFLICTING_COMPILE_FLAGS or
                (flag.startswith('-fmetal-math-mode=') and flag != '-fmetal-math-mode=safe')):
                raise ValueError('qualified Metal invocation contains a conflicting compilation option: '+flag)
        if '-cc1' in argv and any(argv.count(flag) != 1 for flag in ('-fwrapv', '-fpreserve-invariance')):
            raise ValueError('qualified Metal frontend lacks exact wrap and invariance options')


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
    """Hash the validated library invocation, including its recorded absolute paths.

    Only probe-temporary paths are normalized. Selected tools/inputs and emitted
    working-directory arguments stay bound in effective_invocations, so moving
    a toolchain or checkout may conservatively invalidate reuse. The top-level
    observation.path and raw diagnostic text are provenance, not extra key fields.
    """
    context = {key: observation.get(key) for key in (
        'qualified', 'backend', 'version', 'executable_sha256',
        'effective_flags', 'effective_target', 'sdk_mode')}
    context['schema'] = 'kokiri-metal-compiler-context-v2'
    context['resource_headers_sha256'] = observation.get('resource_headers', {}).get('content_sha256')
    if not observation.get('qualified'):
        context['reason'] = observation.get('reason')
    else:
        components = observation.get('tool_components', [])
        roles = [component.get('role') for component in components if isinstance(component, dict)]
        host = observation.get('host_identity', {})
        def sha(value):
            return isinstance(value, str) and re.fullmatch('[0-9a-f]{64}', value) is not None
        def file_identity(record, field='sha256'):
            return (isinstance(record, dict) and sha(record.get(field)) and
                    isinstance(record.get('path'), str) and Path(record['path']).is_absolute() and
                    type(record.get('size')) is int and record['size'] > 0)
        if (not isinstance(components, list) or len(roles) != len(components) or
            any(roles.count(role) != 1 for role in ('driver', 'frontend', 'linker')) or
            not roles or roles[0] != 'driver' or roles[-1] != 'linker' or
            any(not file_identity(component, 'executable_sha256') for component in components) or
            not isinstance(observation.get('required_files'), list) or
            not isinstance(host, dict) or
            any(not isinstance(host.get(field), str) or not host[field] for field in ('os_build', 'machine', 'kernel_release'))):
            raise ValueError('qualified Metal compiler observation lacks component or host identities')
        if (observation.get('observation_schema') != 2 or
            observation.get('executable_sha256') != components[0]['executable_sha256'] or
            not sha(observation.get('resource_headers', {}).get('content_sha256')) or
            observation.get('backend') != 'metal' or not isinstance(observation.get('effective_flags'), list) or
            not observation['effective_flags'] or any(not isinstance(flag, str) for flag in observation['effective_flags']) or
            not isinstance(observation.get('effective_target'), str) or not observation['effective_target'] or
            observation.get('sdk_mode') != 'compiler-default-resource-headers'):
            raise ValueError('qualified Metal compiler observation lacks component or host identities')
        if observation.get('loader_environment_policy') != 'reject-nonempty-DYLD':
            raise ValueError('qualified Metal compiler observation lacks the required loader environment policy')
        context['loader_environment_policy'] = observation['loader_environment_policy']
        validate_driver_flags(observation['effective_flags'])
        invocations = observation.get('effective_invocations')
        if (not isinstance(invocations, list) or len(invocations) != len(components)-1 or
            any(not isinstance(argv, list) or not argv or any(not isinstance(arg, str) for arg in argv) for argv in invocations) or
            sum('-cc1' in argv for argv in invocations) != 1 or '-cc1' in invocations[-1]):
            raise ValueError('qualified Metal compiler observation lacks effective library invocations')
        validate_invocation_math(invocations)
        for index, (component, argv) in enumerate(zip(components[1:], invocations)):
            role = 'frontend' if '-cc1' in argv else 'linker' if index == len(invocations)-1 else 'compiler-tool'
            if component['role'] != role or argv[0] != component['path']:
                raise ValueError('selected compiler executable roles differ from effective invocations')
            if role == 'frontend':
                if argv.count('-triple') != 1 or argv.index('-triple')+1 >= len(argv) or argv[argv.index('-triple')+1] != observation.get('effective_target'):
                    raise ValueError('selected frontend target differs from compiler observation')
        planned_outputs = {argv[index+1] for argv in invocations for index, arg in enumerate(argv[:-1]) if arg == '-o'}
        selected_inputs = {arg for argv in invocations for arg in argv[1:] if Path(arg).is_absolute() and
                           Path(arg).suffix in ('.a', '.dylib', '.tbd', '.bc') and arg not in planned_outputs}
        required = observation['required_files']
        if (not selected_inputs or not any(Path(arg).suffix == '.a' for arg in selected_inputs) or
            any(not file_identity(item) or item.get('role') != 'selected-invocation-input' for item in required) or
            len({item['path'] for item in required}) != len(required) or
            {item['path'] for item in required} != selected_inputs):
            raise ValueError('compiler invocation input lacks content identity: selected input inventory incomplete')
        graph_hashes = {component['executable_sha256'] for component in components}
        for component in components:
            if not isinstance(component.get('dependencies'), list):
                raise ValueError('qualified Metal compiler observation lacks dependency audit')
            graph_hashes.update(dep.get('sha256') for dep in component['dependencies']
                                if isinstance(dep, dict) and dep.get('binding') == 'hashed-file')
        context['tool_components'] = []
        for component in components:
            if not isinstance(component.get('dependencies'), list):
                raise ValueError('qualified Metal compiler observation lacks dependency audit')
            dependencies = []
            for dependency in component['dependencies']:
                if (not isinstance(dependency, dict) or not sha(dependency.get('loader_sha256')) or
                    dependency['loader_sha256'] not in graph_hashes or
                    not isinstance(dependency.get('install_name'), str) or
                    not dependency['install_name'].startswith(('/', '@loader_path/', '@executable_path/', '@rpath/'))):
                    raise ValueError('compiler dependency lacks content identity: loader or install name')
                if dependency.get('binding') == 'hashed-file':
                    if not file_identity(dependency):
                        raise ValueError('compiler dependency lacks content identity')
                elif (dependency.get('binding') != 'os-build-system-component' or
                      not dependency['install_name'].startswith(('/usr/lib/', '/System/Library/')) or
                      dependency.get('os_build') != observation['host_identity']['os_build']):
                    raise ValueError('compiler dependency lacks system identity')
                dependencies.append({key: dependency.get(key) for key in (
                    'loader_sha256', 'install_name', 'binding', 'sha256', 'os_build')})
            context['tool_components'].append(dict(role=component['role'],
                executable_sha256=component['executable_sha256'], dependencies=dependencies))
        context['required_files'] = []
        for required in observation['required_files']:
            if not file_identity(required):
                raise ValueError('compiler invocation input lacks content identity')
            context['required_files'].append(dict(role=required['role'], sha256=required['sha256']))
        context['host_identity'] = observation['host_identity']
        context['effective_invocations'] = invocations
    encoded = json.dumps(context, sort_keys=True, separators=(',', ':')).encode()
    return hashlib.sha256(encoded).hexdigest()


def compiler_observation(metal, version, env, flags):
    """Record what this driver actually chooses; JIT equivalence is not implied."""
    if not Path(metal).is_file():
        return dict(qualified=False, backend='metal', version=version, effective_flags=list(flags),
                    effective_target=None, sdk_mode='unobserved',
                    reason='compiler executable unavailable')
    overrides = sorted(key for key, value in env.items() if key.startswith('DYLD_') and value)
    if overrides:
        raise ValueError('qualified Metal compiler identity does not support nonempty DYLD_* environment: '+', '.join(overrides))
    validate_driver_flags(flags)
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
    required, seen, input_aliases = [], set(), {}
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
                identity = file_content_identity(resolved)
                required.append(dict(role='selected-invocation-input', **identity))
                input_aliases[argument] = identity['path']
                seen.add(resolved)
    def stable_argument(argument):
        if argument in input_aliases:
            return input_aliases[argument]
        for probe in sorted({folder, str(Path(folder).resolve())}, key=len, reverse=True):
            argument = argument.replace(probe, '<probe-dir>')
        return '<intermediate.air>' if re.search(r'/identity-[0-9a-f]+\.air$', argument) else argument
    invocations = [[stable_argument(argument) for argument in argv] for argv in commands]
    for invocation, component in zip(invocations, components[1:]):
        invocation[0] = component['path']
    sdk={}
    for key,arg in [('path','--show-sdk-path'),('version','--show-sdk-version')]:
        probe=subprocess.run(['xcrun','--sdk','macosx',arg],capture_output=True,text=True,env=env)
        sdk[key]=probe.stdout.strip() if probe.returncode==0 else None
    observation = dict(qualified=True,backend='metal',path=str(Path(metal).resolve()),version=version,
                executable_sha256=components[0]['executable_sha256'],
                effective_flags=list(flags),effective_target=triples[0],driver_command=command,
                driver_plan=result.stderr,driver_plan_sha256=hashlib.sha256(result.stderr.encode()).hexdigest(),
                resource_dir=resources[0],resource_headers=headers,
                observation_schema=2,tool_components=components,required_files=required,
                loader_environment_policy='reject-nonempty-DYLD',
                host_identity=host,effective_invocations=invocations,
                sdk_mode='compiler-default-resource-headers',available_macos_sdk=sdk,
                developer_dir=env.get('DEVELOPER_DIR'),
                limitation='Declared library-driver tools, explicit file inputs and non-system load dependencies are hashed; system components are bound to OS build. Unseen dlopen components, runtime JIT and actual library loading are not established.')
    compiler_context_key(observation)  # Qualified observations must pass the shared consumer validator too.
    return observation


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
