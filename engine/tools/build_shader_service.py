#!/usr/bin/env python3
"""Build this title's isolated NativeAOT GPU shader service in an external workspace."""
import argparse
import concurrent.futures
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import xml.etree.ElementTree as ET

GAME = Path(__file__).resolve().parents[1]
if not __package__ and str(GAME) not in sys.path:
    sys.path.insert(0, str(GAME))
if __package__:
    from .build_proof_tools import build as build_proof_tools, TOOLS as PROOF_TOOLS, HEADERS as PROOF_HEADERS
    from .shader_pins import SPIRV_CROSS, SPIRV_CROSS_SOURCES, SPIRV_CROSS_FLAGS
    from .deps import program
else:
    from tools.build_proof_tools import build as build_proof_tools, TOOLS as PROOF_TOOLS, HEADERS as PROOF_HEADERS
    from tools.shader_pins import SPIRV_CROSS, SPIRV_CROSS_SOURCES, SPIRV_CROSS_FLAGS
    from tools.deps import program


def expected_inputs():
    source = GAME/'tools/totk_xlate'
    inputs = [*sorted((GAME/'third_party/ryujinx').rglob('*.cs')),
              *sorted((source/'patches').glob('*.patch'))]
    service_inputs = sorted(p for p in source.rglob('*') if p.suffix in ('.cs', '.csproj', '.cpp')
                            and not {'obj', 'bin'} & set(p.parts))
    return dict(
        shader_source_sha256=hashlib.sha256(b''.join(str(p.relative_to(GAME)).encode()+p.read_bytes() for p in inputs)).hexdigest(),
        shader_service_source_sha256=hashlib.sha256(b''.join(str(p.relative_to(source)).encode()+p.read_bytes() for p in service_inputs)).hexdigest(),
        spirv_cross_commit=SPIRV_CROSS[1], spirv_tools_commit=PROOF_TOOLS[1], spirv_headers_commit=PROOF_HEADERS[1],
        build_tools_sha256={name:hashlib.sha256((GAME/'tools'/name).read_bytes()).hexdigest()
                           for name in ('build_shader_service.py','build_proof_tools.py','shader_pins.py')})

def main():
    ap=argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--work',type=Path,required=True)
    ap.add_argument('--dotnet', help='explicit .NET executable; otherwise use the pinned SDK')
    ap.add_argument('--proof-tools-work',type=Path)
    args=ap.parse_args();work=args.work.resolve()
    repo=GAME.parent
    if work==repo or repo in work.parents:raise ValueError('workspace must be outside the source tree')
    work.mkdir(parents=True,exist_ok=True)
    if shutil.disk_usage(work).free < 6 * (1 << 30):
        raise OSError('shader toolchain build requires at least 6 GiB free; no cache is deleted')
    dotnet = args.dotnet or program('dotnet')
    record = expected_inputs()
    def run(cmd):
        if shutil.disk_usage(work).free < 2 * (1 << 30):
            raise OSError('less than 2 GiB free; shader build stopped without deleting data')
        subprocess.run([str(x) for x in cmd],check=True)
    source=GAME/'tools/totk_xlate';ryu=work/'ryujinx'
    runtime_version=ET.parse(source/'totk_xlate.csproj').findtext('PropertyGroup/RuntimeFrameworkVersion')
    if not runtime_version or runtime_version!=ET.parse(source/'proof/oot_write_proof.csproj').findtext('PropertyGroup/RuntimeFrameworkVersion'):
        raise ValueError('shader service and proof must pin the same serviced NativeAOT runtime')
    runtime_property='-p:RuntimeFrameworkVersion='+runtime_version
    fingerprint=record['shader_source_sha256']
    stamp=work/'ryujinx-source.sha256'
    if not stamp.exists() or stamp.read_text().strip()!=fingerprint:
        if ryu.exists():shutil.rmtree(ryu) # only this command's generated dependency copy
        shutil.copytree(GAME/'third_party/ryujinx',ryu,ignore=shutil.ignore_patterns('obj','bin','__pycache__'))
        for patch in sorted((source/'patches').glob('*.patch')):run(['patch','-s','-d',ryu,'-p1','--forward','-i',patch])
        stamp.write_text(fingerprint+'\n')
    xlate=work/'xlate';shutil.copytree(source,xlate,dirs_exist_ok=True)
    cross=work/'spirv-cross'
    if not (cross/'.git').exists():
        run(['git','init','-q',cross]);run(['git','-C',cross,'fetch','-q','--depth','1',*SPIRV_CROSS]);run(['git','-C',cross,'checkout','-q','FETCH_HEAD'])
    if subprocess.check_output(['git','-C',cross,'rev-parse','HEAD'],text=True).strip()!=SPIRV_CROSS[1]:raise ValueError('SPIRV-Cross pin mismatch')
    obj=work/'spvc';obj.mkdir(exist_ok=True)
    jobs=[(cross/n,obj/(n+'.o'))for n in SPIRV_CROSS_SOURCES if n!='main.cpp']+[(source/'spirv_cross_inproc.cpp',obj/'inproc.o')]
    def compile_one(job):
        src,out=job
        if not out.exists() or out.stat().st_mtime<src.stat().st_mtime:run(['xcrun','clang++',*SPIRV_CROSS_FLAGS,'-mmacosx-version-min=12.0','-I'+str(cross),'-c',src,'-o',out])
    with concurrent.futures.ThreadPoolExecutor(2)as pool:list(pool.map(compile_one,jobs))
    lib=work/'libtotk_spirv_cross.a';run(['xcrun','ar','rcs',lib,*[p for _,p in jobs]])
    proof_work=(args.proof_tools_work or work/'proof-tools').resolve()
    if proof_work==repo or repo in proof_work.parents:raise ValueError('proof tools workspace must be outside source tree')
    wrapper,opt,core=build_proof_tools(proof_work,source/'spirv_tools_inproc.cpp')
    run([dotnet,'publish',xlate/'totk_xlate.csproj','-c','Release','-r','osx-arm64','-m:2','-p:IlcMaxDegreeOfParallelism=2',runtime_property,'-p:PublishAot=true','-p:InvariantGlobalization=true','-p:RyuSrc='+str(ryu),'-p:TotkSpirvCrossLib='+str(lib),'-p:TotkSpirvToolsWrapper='+str(wrapper),'-p:TotkSpirvToolsOpt='+str(opt),'-p:TotkSpirvToolsCore='+str(core),'-o',work/'native'])
    binary=work/'native/totk_xlate';dest=binary
    run([dotnet,'publish',xlate/'proof/oot_write_proof.csproj','-c','Release','-r','osx-arm64','-m:2','-p:IlcMaxDegreeOfParallelism=2',runtime_property,'-p:RyuSrc='+str(ryu),'-o',work/'proof-native'])
    proof_binary=work/'proof-native/oot_write_proof.dylib';proof_dest=dest.with_name('oot_write_proof.dylib')
    shutil.copy2(proof_binary,proof_dest);proof_digest=hashlib.sha256(proof_binary.read_bytes()).hexdigest();proof_dest.with_suffix('.dylib.sha256').write_text(proof_digest+'\n')
    for name in ('SPIRV-Cross.LICENSE', 'SPIRV-Tools.LICENSE', 'dotnet-runtime.LICENSE'):
        shutil.copy2(GAME/'third_party/licenses'/name, dest.with_name(name))
    digest=hashlib.sha256(binary.read_bytes()).hexdigest();dest.with_suffix('.sha256').write_text(digest+'\n')
    record.update(binary_sha256=digest,proof_binary_sha256=proof_digest)
    (work/'build-record.json').write_text(json.dumps(record,indent=2)+'\n')
    print(dest)
if __name__=='__main__':main()
