"""Standalone Metal compiler discovery, adapted from MacNativeGames (MIT)."""
import os
import hashlib
import json
import re
from pathlib import Path
import subprocess

METAL_FLAGS = ['-mmacosx-version-min=26.0', '-fmetal-math-mode=safe']


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
    context['schema'] = 'kokiri-metal-compiler-context-v1'
    context['resource_headers_sha256'] = observation.get('resource_headers', {}).get('content_sha256')
    if not observation.get('qualified'):
        context['reason'] = observation.get('reason')
    encoded = json.dumps(context, sort_keys=True, separators=(',', ':')).encode()
    return hashlib.sha256(encoded).hexdigest()


def compiler_observation(metal, version, env, flags):
    """Record what this driver actually chooses; JIT equivalence is not implied."""
    if not Path(metal).is_file():
        return dict(qualified=False, backend='metal', version=version, effective_flags=list(flags),
                    effective_target=None, sdk_mode='unobserved',
                    reason='compiler executable unavailable')
    command=[metal,'-###',*flags,'-c','-x','metal','/dev/null']
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
    sdk={}
    for key,arg in [('path','--show-sdk-path'),('version','--show-sdk-version')]:
        probe=subprocess.run(['xcrun','--sdk','macosx',arg],capture_output=True,text=True,env=env)
        sdk[key]=probe.stdout.strip() if probe.returncode==0 else None
    return dict(qualified=True,backend='metal',path=str(Path(metal).resolve()),version=version,
                executable_sha256=hashlib.sha256(Path(metal).read_bytes()).hexdigest(),
                effective_flags=list(flags),effective_target=triples[0],driver_command=command,
                driver_plan=result.stderr,driver_plan_sha256=hashlib.sha256(result.stderr.encode()).hexdigest(),
                resource_dir=resources[0],resource_headers=headers,
                sdk_mode='compiler-default-resource-headers',available_macos_sdk=sdk,
                developer_dir=env.get('DEVELOPER_DIR'),
                limitation='Offline compiler observation only; runtime JIT and actual library loading require separate evidence.')


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
