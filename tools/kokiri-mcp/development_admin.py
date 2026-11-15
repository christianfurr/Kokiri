"""Local registry setup. Never exposed as MCP tools and never launches a game."""
import argparse
import hashlib
from pathlib import Path
import plistlib

from development import Development, IDENTIFIER, digest, profile_manifest
from kokiri import KokiriError, SessionStore, atomic_json, bounded_bytes, checked_directory, json_file


def register(workspace: Path, kind: str, identifier: str, source: Path, acceptance: Path | None=None) -> dict:
    if not IDENTIFIER.fullmatch(identifier):
        raise KokiriError("Use a lowercase registry identifier with letters, digits, - or _.")
    root=SessionStore().managed_directory(workspace)
    if root.stat().st_mode & 0o077:
        raise KokiriError("The development workspace must be private (mode0700).")
    registry=json_file(root,"registry.json") if (root/"registry.json").exists() else {"schema":1,"runtimes":{},"fixtures":{},"scenarios":{}}
    if kind=="runtime":
        source=checked_directory(source)
        info_raw=bounded_bytes(source,"Contents/Info.plist",65536)
        info=plistlib.loads(info_raw)
        entry={"app":str(source),"executable_sha256":digest(source/"Contents/MacOS/KokiriGame"),
               "info_sha256":hashlib.sha256(info_raw).hexdigest(),"source_commit":info.get("KokiriSourceCommit","unknown"),
               "declared_prepared":info.get("KokiriPrepared") is True,
               "preparation_receipt_sha256":info.get("KokiriPreparationReceiptSHA256")}
        Development(root).runtime(entry)
        if acceptance is not None:
            proof=json_file(checked_directory(acceptance.parent),acceptance.name)
            if proof.get("passed") is not True or proof.get("executable_sha256")!=entry["executable_sha256"]:
                raise KokiriError("The isolation acceptance receipt does not match this runtime.")
            # Runtime acknowledgements can contain a private control nonce. Keep
            # only the acceptance identity in the registry, never echo the proof.
            entry["isolation_acceptance"]={"passed":True,"executable_sha256":entry["executable_sha256"],
                "receipt_sha256":digest(acceptance)}
        registry.setdefault("runtimes",{})[identifier]=entry
        result={"id":identifier,"executable_sha256":entry["executable_sha256"],"launch_accepted":acceptance is not None}
    elif kind=="fixture":
        source=checked_directory(source)
        manifest=profile_manifest(source)
        registry.setdefault("fixtures",{})[identifier]={"profile":str(source)}
        result={"id":identifier,"entries":len(manifest),"source_written":False}
    elif kind=="scenario":
        from commands import scenario
        import json
        raw=bounded_bytes(checked_directory(source.parent),source.name,65536)
        steps=json.loads(raw)
        scenario(steps)
        registry.setdefault("scenarios",{})[identifier]=steps
        result={"id":identifier,"steps":len(steps)}
    else:
        raise KokiriError("Unsupported private registration operation.")
    atomic_json(root/"registry.json",registry)
    return result


def main():
    import json
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--workspace",type=Path,default=Path.home()/"Library/Application Support/Kokiri/Development/Workbench")
    parser.add_argument("kind",choices=["runtime","fixture","scenario"])
    parser.add_argument("identifier")
    parser.add_argument("source",type=Path)
    parser.add_argument("--acceptance",type=Path)
    args=parser.parse_args()
    print(json.dumps(register(args.workspace,args.kind,args.identifier,args.source,args.acceptance),sort_keys=True))


if __name__=="__main__":main()
