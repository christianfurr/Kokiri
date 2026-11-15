"""Private disposable development sessions. Never adopt an existing game process."""
from __future__ import annotations

from contextlib import contextmanager
import fcntl
import ctypes
import hashlib
import json
import math
import os
from pathlib import Path
import plistlib
import re
import shutil
import subprocess
import time
import uuid

from kokiri import (KokiriError, ProcessReader, SessionStore, atomic_json,
                    bounded_bytes, checked_directory, complete_png, json_file, open_relative, tail, LOG_FILES)
from containment import require_disjoint_directories

IDENTIFIER = re.compile(r"[a-z][a-z0-9_-]{0,47}\Z")
SESSION = re.compile(r"[0-9a-f]{32}\Z")
COORDINATOR = "01a1e00c-5a79-7400-8e01-da38c7ae9206"
MAX_PROFILE_BYTES = 1 << 30
MAX_PROFILE_FILES = 4096
PATHS = {"profile": "profile", "settings": "settings/game", "cache": "cache",
         "logs": "logs", "proof": "proof", "contributions": "contributions",
         "mods": "mods", "tmp": "tmp", "input": "input.txt", "status": "status.jsonl"}


def digest(path: Path) -> str:
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def profile_manifest(root: Path) -> dict:
    root = checked_directory(root)
    result = {}; total = 0
    for folder, dirs, files in os.walk(root, followlinks=False):
        for name in dirs + files:
            path = Path(folder)/name
            info = path.lstat()
            if path.is_symlink() or info.st_uid != os.getuid():
                raise KokiriError("Profiles must contain same-user directories and independent regular files.")
            if path.is_dir():
                result[str(path.relative_to(root))+"/"] = "directory"
            elif path.is_file() and info.st_nlink == 1:
                total += info.st_size
                if total > MAX_PROFILE_BYTES or len(result) >= MAX_PROFILE_FILES:
                    raise KokiriError("This profile exceeds the development copy bounds.")
                result[str(path.relative_to(root))] = digest(path)
            else:
                raise KokiriError("Linked or special profile files cannot enter a development session.")
            if len(result) > MAX_PROFILE_FILES:
                raise KokiriError("This profile exceeds the development file bound.")
    if not result:
        raise KokiriError("Choose a nonempty complete test profile.")
    return result


def manifest_digest(value: dict) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


class Development:
    def __init__(self, workspace: Path, process: ProcessReader | None = None):
        self.workspace = workspace.expanduser().absolute()
        self.process = process or ProcessReader()
        self.observer = SessionStore(process_reader=self.process)
        self.observer.observe_roots.append(self.workspace/"sessions")
        self.runtime_checks = {}
        self.children = {}

    def registry(self) -> dict:
        try:
            root = checked_directory(self.workspace)
            value = json_file(root, "registry.json")
        except FileNotFoundError as error:
            raise KokiriError("Configure the private development runtime and fixture registry first.") from error
        if value.get("schema") != 1:
            raise KokiriError("Configure the private development runtime and fixture registry first.")
        return value

    @contextmanager
    def locked(self, session_id: str):
        if not isinstance(session_id, str) or not SESSION.fullmatch(session_id):
            raise KokiriError("Choose an owned development session ID.")
        try:
            root = checked_directory(self.workspace/"sessions"/session_id)
        except FileNotFoundError as error:
            raise KokiriError("That owned development session was not found.") from error
        descriptor = open_relative(root, "operation.lock", os.O_RDWR)
        try:
            try:
                fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError as error:
                raise KokiriError("Another operation owns this development session.") from error
            owned = json_file(root, "ownership.json")
            if owned.get("schema") != 1 or owned.get("session_id") != session_id:
                raise KokiriError("This is not an owned development session.")
            yield root, owned
        finally:
            os.close(descriptor)

    def options(self) -> dict:
        registry = self.registry()
        return {"runtimes": sorted(registry.get("runtimes", {})),
                "fixtures": sorted(registry.get("fixtures", {})),
                "scenarios": sorted(registry.get("scenarios", {})),
                "human_sessions": "observation-only"}

    def sessions(self) -> dict:
        root=self.workspace/"sessions"
        rows=[]
        if root.exists():
            root=checked_directory(root)
            for path in sorted(root.iterdir()):
                if len(rows)>=32:break
                if not SESSION.fullmatch(path.name):continue
                try:
                    path=checked_directory(path);owned=json_file(path,"ownership.json")
                    if owned.get("session_id")!=path.name:continue
                    rows.append({"session_id":path.name,"state":owned.get("state"),"fixture_id":owned.get("fixture_id"),
                                 "runtime_id":owned.get("runtime_id"),"running_verified":self.sample(path) is not None})
                except (OSError,KokiriError):continue
        return {"sessions":rows,"limit":32,"human_processes_adopted":False}

    def runtime(self, entry: dict) -> tuple[Path, Path]:
        app = checked_directory(Path(entry["app"]))
        executable = app/"Contents/MacOS/KokiriGame"
        info_path=app/"Contents/Info.plist"
        def stamp(path):
            info=path.lstat()
            if path.is_symlink() or not path.is_file():raise KokiriError("Runtime identity paths must be regular files.")
            return (info.st_dev,info.st_ino,info.st_size,info.st_mtime_ns,info.st_ctime_ns)
        key=(str(app),stamp(executable),stamp(info_path),entry.get("executable_sha256"),entry.get("info_sha256"))
        if key in self.runtime_checks:return app,executable
        info_raw = bounded_bytes(app, "Contents/Info.plist", 65536)
        info = plistlib.loads(info_raw)
        if (info.get("CFBundleIdentifier") != "com.christianfurr.kokiri.runtime"
                or info.get("KokiriDevelopmentVersion") != 1
                or info.get("CFBundleExecutable") != "KokiriGame"):
            raise KokiriError("This runtime does not declare the isolated development entry.")
        if (executable.is_symlink() or not executable.is_file()
                or digest(executable) != entry.get("executable_sha256")
                or hashlib.sha256(info_raw).hexdigest() != entry.get("info_sha256")):
            raise KokiriError("The registered runtime changed; register and verify the new build.")
        self.runtime_checks={key:True}
        return app, executable

    def create(self, runtime_id: str, fixture_id: str) -> dict:
        registry = self.registry()
        if not all(isinstance(v, str) and IDENTIFIER.fullmatch(v) for v in (runtime_id, fixture_id)):
            raise KokiriError("Choose registered runtime and fixture identifiers.")
        try:
            runtime = registry["runtimes"][runtime_id]
            source = checked_directory(Path(registry["fixtures"][fixture_id]["profile"]))
        except KeyError as error:
            raise KokiriError("That registered runtime or fixture is unavailable.") from error
        _, executable = self.runtime(runtime)
        workspace = checked_directory(self.workspace)
        require_disjoint_directories(source, workspace)
        before = profile_manifest(source)
        needed=2*sum((source/name).stat().st_size for name in before if not name.endswith("/"))
        if shutil.disk_usage(workspace).free-needed<6*(1<<30):
            raise KokiriError("Development copies must leave at least6GiB free.")
        session_id = uuid.uuid4().hex
        sessions = self.observer.managed_directory(self.workspace/"sessions")
        if sum(1 for path in sessions.iterdir() if SESSION.fullmatch(path.name))>=32:
            raise KokiriError("The development workspace reached its32session bound. Preserve/archive completed work before creating more.")
        root = sessions/session_id
        root.mkdir(mode=0o700)
        try:
            shutil.copytree(source, root/"profile", copy_function=shutil.copy2)
            if before != profile_manifest(source) or before != profile_manifest(root/"profile"):
                raise KokiriError("The source profile changed during copying; no session was created.")
            shutil.copytree(root/"profile",root/"baseline-profile",copy_function=shutil.copy2)
            if before!=profile_manifest(root/"baseline-profile"):
                raise KokiriError("The reset baseline did not match the verified profile copy.")
            # Everything writable is newly created; no inherited settings can name
            # an external screenshot, mod, cache or upload destination.
            for name in ("settings/game", "cache", "logs", "proof", "contributions", "mods", "tmp", "save-state"):
                (root/name).mkdir(mode=0o700, parents=True, exist_ok=True)
            for name in ("input.txt", "status.jsonl", "operation.lock"):
                descriptor = os.open(root/name, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
                os.close(descriptor)
            owned = {"schema": 1, "session_id": session_id, "created": time.time(), "state": "prepared",
                     "runtime_id": runtime_id, "fixture_id": fixture_id, "runtime": runtime,
                     "executable": str(executable), "source_profile_sha256": manifest_digest(before),
                     "cache_condition": "cold private cache"}
            atomic_json(root/"source-manifest.json", before)
            atomic_json(root/"ownership.json", owned)
        except Exception:
            shutil.rmtree(root)
            raise
        return {"session_id": session_id, "state": "prepared", "profile_sha256": owned["source_profile_sha256"],
                "cache_condition": owned["cache_condition"], "source_unchanged": True}

    def sample(self, root: Path) -> dict | None:
        try:
            metadata = json_file(root, "session.json")
        except FileNotFoundError:
            return None
        return self.observer.verified_process(metadata)

    def stopped(self, root: Path, owned: dict) -> bool:
        return owned.get("state") in {"prepared", "stopped"} and self.recorded_exit(root, owned)

    def recorded_exit(self, root: Path, owned: dict) -> bool:
        try:
            metadata = json_file(root, "session.json")
        except FileNotFoundError:
            # Newly prepared or closed-without-launching sessions have no PID.
            return "spawn_pid" not in owned and owned.get("state") in {"prepared", "stopped"}
        pid = metadata.get("pid")
        if type(pid) is not int or pid <= 1:
            return False
        if "spawn_pid" in owned and (type(owned["spawn_pid"]) is not int or owned["spawn_pid"] != pid):
            return False
        child = self.children.get(root.name)
        if child is not None and child.pid != pid:
            return False
        if child is not None and child.pid == pid and child.poll() is not None:
            # Reap only handles created here; never reap/adopt an arbitrary PID.
            self.children.pop(root.name)
        return self.process.presence(pid) == "gone"

    def permit(self, owned: dict) -> dict:
        registry = self.registry()
        path = Path(registry.get("permit_file", ""))
        if not path.is_absolute():
            raise KokiriError("Integration has not configured an exclusive development test grant.")
        try:
            permit = json_file(checked_directory(path.parent), path.name)
        except FileNotFoundError as error:
            raise KokiriError("The exclusive development test grant is unavailable.") from error
        if (permit.get("schema") != 1 or permit.get("issuer") != COORDINATOR
                or permit.get("state") != "granted" or permit.get("session_id") != owned["session_id"]
                or permit.get("executable_sha256") != owned["runtime"]["executable_sha256"]
                or not isinstance(permit.get("expires_unix"), (int, float))
                or not math.isfinite(permit["expires_unix"]) or permit["expires_unix"] <= time.time()):
            raise KokiriError("The exclusive development test grant is missing, expired or belongs to another session.")
        return permit

    def identity(self, root: Path, owned: dict, require_live: bool = True) -> dict | None:
        self.runtime(owned["runtime"])
        sample = self.sample(root)
        if sample is None:
            if require_live:
                raise KokiriError("The owned runtime is not running with its recorded identity.")
            return None
        request = json_file(root, "request.json")
        lease = json_file(root, "lease.json")
        ack = json_file(root, "isolation.json")
        expected = {key: str(root/value) for key, value in PATHS.items()}
        if (ack.get("schema") != 1 or ack.get("isolation_version") != 1
                or ack.get("game_slot_acquired") is not True
                or ack.get("session_id") != owned["session_id"] or ack.get("nonce") != request.get("nonce")
                or lease.get("nonce") != request.get("nonce") or lease.get("session_id") != owned["session_id"]
                or not isinstance(lease.get("expires_unix"), (int, float))
                or not time.time() < lease["expires_unix"] <= request["expires_unix"]
                or (root/"revoked").exists() or ack.get("effective_paths") != expected
                or any(ack.get(key) != sample[key] for key in ("pid", "executable", "process_start"))
                or ack.get("executable_sha256") != owned["runtime"]["executable_sha256"]):
            raise KokiriError("Runtime isolation acknowledgement or development lease no longer matches.")
        return sample

    def launch(self, session_id: str, seconds: int = 600) -> dict:
        if type(seconds) is not int or not 10 <= seconds <= 1800:
            raise KokiriError("Development leases last10–1800seconds.")
        with self.locked(session_id) as (root, owned):
            if not self.stopped(root, owned):
                raise KokiriError("This session must be stopped before launch.")
            permit = self.permit(owned)
            app, executable = self.runtime(owned["runtime"])
            acceptance = owned["runtime"].get("isolation_acceptance")
            if not isinstance(acceptance, dict) or acceptance.get("executable_sha256") != owned["runtime"]["executable_sha256"] or acceptance.get("passed") is not True:
                raise KokiriError("Integration must accept actual runtime isolation before enabling development launch tools.")
            if self.process.game_running():
                raise KokiriError("Another game is running. Human gameplay takes precedence.")
            try:
                subprocess.run(["/usr/bin/codesign","--verify","--deep","--strict",str(app)],
                               check=True,capture_output=True,timeout=30)
            except subprocess.SubprocessError as error:
                raise KokiriError("The pinned app failed code-signature verification. No game was launched.") from error
            expires = min(time.time()+seconds, permit["expires_unix"])
            request = {"schema": 1, "session_id": session_id, "nonce": uuid.uuid4().hex+uuid.uuid4().hex,
                       "expires_unix": expires, "executable_sha256": owned["runtime"]["executable_sha256"]}
            for name in ("isolation.json", "revoked"):
                (root/name).unlink(missing_ok=True)
            for name in ("input.txt", "status.jsonl"):
                descriptor = open_relative(root, name, os.O_WRONLY | os.O_TRUNC); os.close(descriptor)
            atomic_json(root/"request.json", request); atomic_json(root/"lease.json", request)
            # Constructors execute before main: inherit no game/debug/dyld variables.
            environment = {"PATH": "/usr/bin:/bin:/usr/sbin:/sbin", "HOME": str(Path.home()),
                           "TMPDIR": str(root/"tmp"), "LANG": "en_US.UTF-8",
                           "KOKIRI_DEVELOPMENT_ROOT": str(root), "KOKIRI_DEVELOPMENT_NONCE": request["nonce"]}
            log_descriptor=open_relative(root,"game-full.log",os.O_WRONLY|os.O_APPEND|os.O_CREAT)
            if os.fstat(log_descriptor).st_nlink!=1:
                os.close(log_descriptor);raise KokiriError("The private runtime log must not be hardlinked.")
            with os.fdopen(log_descriptor,"ab") as log:
                # A launch can populate this preserved cache. Empty at creation
                # does not certify later launches or resets as cold.
                owned["cache_condition"]="private cache; current cold/warm state unverified"
                owned["state"]="launching";atomic_json(root/"ownership.json",owned)
                try:
                    process = subprocess.Popen([str(executable), "--kokiri-development", str(root)], cwd=app,
                                               env=environment, stdin=subprocess.DEVNULL, stdout=log, stderr=log,
                                               start_new_session=True)
                    self.children[session_id] = process
                except OSError:
                    owned["state"]="prepared";atomic_json(root/"ownership.json",owned)
                    raise
                owned["spawn_pid"]=process.pid;atomic_json(root/"ownership.json",owned)
            deadline = time.monotonic()+5
            sample = None
            while process.poll() is None and time.monotonic() < deadline:
                sample = self.process.sample(process.pid)
                if sample and sample["executable"] == str(executable):
                    break
                time.sleep(.05)
            if not sample or sample["executable"] != str(executable):
                atomic_json(root/"revoked", {"reason": "launch identity unavailable"})
                owned["state"]="unverified";atomic_json(root/"ownership.json",owned)
                raise KokiriError("Launch identity unavailable. Lease revoked; no existing process was adopted.")
            atomic_json(root/"session.json", {**sample, "started": time.time(), "session_id": session_id,
                                            "source_commit": owned["runtime"].get("source_commit", "unknown")})
            owned["state"] = "starting"; atomic_json(root/"ownership.json", owned)
            return {"session_id": session_id, "status": "starting", "pid": process.pid,
                    "expires_unix": expires, "isolation_accepted": False}

    def status(self, session_id: str) -> dict:
        with self.locked(session_id) as (root, owned):
            sample = self.sample(root)
            accepted = False
            if sample:
                try:
                    accepted = self.identity(root, owned) is not None
                except (KokiriError, OSError):
                    pass
            state="running" if accepted else "control-unavailable" if sample else owned["state"]
            runtime_identity={key:owned["runtime"].get(key) for key in ("executable_sha256","info_sha256","source_commit","declared_prepared","preparation_receipt_sha256")}
            return {"session_id": session_id, "state": state, "running_verified": sample is not None,
                    "isolation_accepted": accepted, "process": sample, "cache_condition": owned["cache_condition"],
                    "runtime":runtime_identity,"source_profile_sha256":owned["source_profile_sha256"],
                    "observation": self.observer.status(self.observer.session_id(root)) if root in self.observer.candidates() else None}

    def logs(self,session_id: str,kind: str="game",lines: int=80) -> dict:
        if kind not in LOG_FILES:raise KokiriError("Choose a documented development log kind.")
        with self.locked(session_id) as (root,owned):
            return {"session_id":session_id,"kind":kind,"lines":tail(root,LOG_FILES[kind],lines),
                    "scope":"owned session only; no global-log fallback"}

    def reset(self, session_id: str) -> dict:
        with self.locked(session_id) as (root,owned):
            if not self.stopped(root,owned):raise KokiriError("Reset requires a stopped owned session.")
            baseline=profile_manifest(root/"baseline-profile")
            if manifest_digest(baseline)!=owned["source_profile_sha256"]:
                raise KokiriError("The original fixture baseline changed; reset refused.")
            if sum(1 for path in root.iterdir() if path.name.startswith("reset-"))>=8:
                raise KokiriError("This session reached its8reset-backup bound. Preserve/review displaced progress before resetting again.")
            needed=sum((root/"baseline-profile"/name).stat().st_size for name in baseline if not name.endswith("/"))
            if shutil.disk_usage(root).free-needed<6*(1<<30):raise KokiriError("Reset must leave at least6GiB free.")
            stage=root/("reset-"+uuid.uuid4().hex)
            shutil.copytree(root/"baseline-profile",stage,copy_function=shutil.copy2)
            if profile_manifest(stage)!=baseline:
                shutil.rmtree(stage);raise KokiriError("Reset copy failed verification.")
            # Same-volume atomic exchange leaves the displaced test progress in
            # stage as a retained backup; no real profile participates.
            library=ctypes.CDLL(None,use_errno=True)
            swap=getattr(library,"renamex_np",None)
            if swap is None:
                shutil.rmtree(stage);raise KokiriError("Atomic profile reset requires macOS renamex_np.")
            swap.argtypes=[ctypes.c_char_p,ctypes.c_char_p,ctypes.c_uint];swap.restype=ctypes.c_int
            if swap(os.fsencode(stage),os.fsencode(root/"profile"),2):
                shutil.rmtree(stage);raise KokiriError("Atomic test-profile reset failed; current progress preserved.")
            owned["state"]="prepared";atomic_json(root/"ownership.json",owned)
            return {"session_id":session_id,"status":"reset","backup_id":stage.name,
                    "profile_sha256":owned["source_profile_sha256"],"cache":"preserved; reset does not make a warm cache cold"}

    def capture(self, session_id: str) -> dict:
        with self.locked(session_id) as (root,owned):
            return self._capture(root,owned)

    def _capture(self,root: Path,owned: dict) -> dict:
        initial=self.identity(root,owned);self.permit(owned)
        observer=SessionStore(support=root,observe_roots=[root],process_reader=self.process)
        path=observer.capture_request(observer.session_id(root),"window")
        data=bounded_bytes(checked_directory(path.parent),path.name,8<<20)
        current=self.identity(root,owned)
        if any(initial[k]!=current[k] for k in ("pid","executable","process_start","process_uuid")) or not complete_png(data):
            raise KokiriError("The native capture is incomplete or its process changed.")
        return {"session_id":owned["session_id"],"surface":"window","path":str(path),"png":data}

    def marker(self, session_id: str, name: str, position: dict | None=None) -> dict:
        from commands import action
        if not isinstance(name,str) or not IDENTIFIER.fullmatch(name):raise KokiriError("Use a bounded marker identifier.")
        with self.locked(session_id) as (root,owned):
            self.identity(root,owned);self.permit(owned)
            markers=json_file(root,"markers.json") if (root/"markers.json").exists() else {}
            if position is not None:
                action(dict(position,action="move"))
                if name not in markers and len(markers)>=64:raise KokiriError("This test session reached its64marker bound.")
                markers[name]=position;atomic_json(root/"markers.json",markers)
                return {"session_id":session_id,"status":"marker-saved","marker":name,"position":position}
            if name not in markers:raise KokiriError("That marker is unavailable in this test session.")
            operation,arguments,_=action(dict(markers[name],action="move"))
            token=self.write(root,owned,operation,arguments)
            return {"session_id":session_id,"status":"queued","request_id":token,"marker":name}

    def preset(self, session_id: str, scenario_id: str) -> dict:
        if not isinstance(scenario_id,str) or not IDENTIFIER.fullmatch(scenario_id):raise KokiriError("Choose a registered scenario ID.")
        try:steps=self.registry()["scenarios"][scenario_id]
        except KeyError as error:raise KokiriError("That scenario preset is unavailable.") from error
        return self.run(session_id,steps)

    def close(self, session_id: str) -> dict:
        with self.locked(session_id) as (root, owned):
            if owned["state"] in {"launching","unverified"}:
                raise KokiriError("Launch identity is unverified. Integration must inspect it before this session can be edited or reused.")
            exited = self.recorded_exit(root, owned)
            sample = self.sample(root)
            if sample:
                self.identity(root, owned)
                self.write(root, owned, "close", "")
                return {"session_id": session_id, "status": "close_requested", "exited": False}
            if not exited:
                raise KokiriError("Process exit is unproven. No process was signaled, adopted or marked stopped.")
            owned["state"] = "stopped"; atomic_json(root/"ownership.json", owned)
            atomic_json(root/"revoked", {"reason": "closed"})
            return {"session_id": session_id, "status": "stopped", "exited": True}

    def restart(self,session_id: str,seconds: int=600) -> dict:
        self.close(session_id)
        deadline=time.monotonic()+30
        while time.monotonic()<deadline:
            with self.locked(session_id) as (root,owned):
                if self.recorded_exit(root,owned):break
                self.identity(root,owned)   # Human takeover/revocation stops this workflow.
            time.sleep(.1)
        result=self.close(session_id)
        if not result["exited"]:raise KokiriError("The owned runtime has not exited; restart refused.")
        return self.launch(session_id,seconds)

    def write(self, root: Path, owned: dict, operation: str, arguments: str) -> str:
        self.identity(root, owned)
        self.permit(owned)
        request = json_file(root, "request.json")
        token = "dev-"+uuid.uuid4().hex[:20]
        wire = f"kokiri-dev {request['nonce']} {token} {operation} {arguments}\n".encode()
        if len(wire) > 1000:
            raise KokiriError("Development request exceeded its wire bound.")
        descriptor = open_relative(root, "input.txt", os.O_WRONLY | os.O_APPEND)
        try:
            if os.fstat(descriptor).st_size > 8 << 20:
                raise KokiriError("Development input reached its size limit.")
            if os.write(descriptor, wire) != len(wire):
                raise KokiriError("Development input append was incomplete.")
        finally:
            os.close(descriptor)
        return token

    def command(self, session_id: str, operation: str, arguments: str) -> dict:
        # Internal only: external MCP tools validate typed values before reaching here.
        with self.locked(session_id) as (root, owned):
            token = self.write(root, owned, operation, arguments)
            return {"session_id": session_id, "request_id": token, "status": "queued"}

    def action(self, session_id: str, step: dict) -> dict:
        from commands import action
        operation, arguments, _ = action(step)
        if operation in {"wait","checkpoint","capture"}:
            raise KokiriError("Waits and checkpoints belong to a bounded scenario.")
        return self.command(session_id,operation,arguments)

    def configure(self, session_id: str, values: dict) -> dict:
        from commands import SETTINGS
        if not isinstance(values,dict) or not values or any(name not in SETTINGS for name in values):
            raise KokiriError("Choose supported test HUD/display settings.")
        for name,value in values.items():
            if isinstance(value,bool) or not isinstance(value,(str,int)) or value not in SETTINGS[name]:
                raise KokiriError("Unsupported test setting value; no files changed.")
        with self.locked(session_id) as (root,owned):
            if not self.stopped(root,owned): raise KokiriError("Configure settings only while the owned test session is stopped.")
            settings=checked_directory(root/"settings/game")
            directory=os.open(settings,os.O_RDONLY|os.O_DIRECTORY|os.O_NOFOLLOW|os.O_CLOEXEC)
            try:
                for name,value in values.items():
                    try:descriptor=open_relative(settings,name)
                    except FileNotFoundError:continue
                    try:
                        if os.fstat(descriptor).st_nlink!=1:raise KokiriError("Test settings must be independent private files.")
                    finally:os.close(descriptor)
                for name,value in values.items():
                    temporary="."+name+"-"+uuid.uuid4().hex
                    descriptor=os.open(temporary,os.O_WRONLY|os.O_CREAT|os.O_EXCL|os.O_NOFOLLOW,0o600,dir_fd=directory)
                    try:
                        with os.fdopen(descriptor,"w") as stream:stream.write(str(value)+"\n")
                        os.replace(temporary,name,src_dir_fd=directory,dst_dir_fd=directory)
                    finally:
                        try:os.unlink(temporary,dir_fd=directory)
                        except FileNotFoundError:pass
            finally:os.close(directory)
            return {"session_id":session_id,"status":"configured","settings":values}

    def run(self, session_id: str, steps: list) -> dict:
        from commands import scenario
        actions=scenario(steps)   # Validate the whole batch before its first effect.
        with self.locked(session_id) as (root,owned):
            initial=self.identity(root,owned);permit=self.permit(owned)
            request=json_file(root,"request.json")
            lease=json_file(root,"lease.json")
            bound=sum(a[2] for a in actions)
            if time.time()+bound>=min(request["expires_unix"],lease["expires_unix"],permit["expires_unix"]):
                raise KokiriError("The scenario cannot finish inside its current lease and test grant.")
            run_id=uuid.uuid4().hex
            record={"schema":1,"run_id":run_id,"session_id":session_id,"started":time.time(),
                    "status":"running","steps":steps,"results":[],
                    "runtime":{key:owned["runtime"].get(key) for key in ("executable_sha256","info_sha256","source_commit","declared_prepared","preparation_receipt_sha256")},
                    "cache_condition":owned["cache_condition"],"certified_benchmark":False}
            destination=root/("scenario-"+run_id+".json")
            atomic_json(destination,record)
            try:
                for operation,arguments,timeout in actions:
                    current=self.identity(root,owned)
                    if any(initial[k]!=current[k] for k in ("pid","process_start","executable","process_uuid")):
                        raise KokiriError("Scenario process identity changed.")
                    self.permit(owned)
                    if operation=="checkpoint":
                        result={"label":arguments,"utc":time.time(),"process":current,
                                "observation":self.observer.status(self.observer.session_id(root))}
                    elif operation=="capture":
                        captured=self._capture(root,owned)
                        result={"label":arguments,"surface":"window","path":captured["path"],
                                "png_sha256":hashlib.sha256(captured["png"]).hexdigest()}
                    elif operation=="wait":
                        deadline=time.monotonic()+timeout
                        while time.monotonic()<deadline:
                            self.identity(root,owned);self.permit(owned);time.sleep(min(.05,max(0,deadline-time.monotonic())))
                        result={"status":"wait-completed"}
                    else:
                        token=self.write(root,owned,operation,arguments)
                        deadline=time.monotonic()+timeout
                        result=None
                        while time.monotonic()<deadline:
                            self.identity(root,owned);self.permit(owned)
                            for line in reversed(tail(root,"status.jsonl",200)):
                                try: row=json.loads(line)
                                except ValueError: continue
                                if isinstance(row,dict) and row.get("id")==token and row.get("status")!="warping":
                                    result=row;break
                            if result is not None:break
                            time.sleep(.05)
                        if result is None:raise KokiriError("A scenario action timed out without completion evidence.")
                        if result.get("status") not in {"completed","acknowledged","position","moved","arrived","already-here"}:
                            raise KokiriError("A scenario action was refused; inspect its private correlated reply.")
                    record["results"].append(result);atomic_json(destination,record)
                record["status"]="completed"
            except Exception as error:
                record["status"]="stopped";record["error"]=str(error)
            record["finished"]=time.time();atomic_json(destination,record)
            return record

    def reply(self, session_id: str, request_id: str) -> dict:
        if not isinstance(request_id, str) or not re.fullmatch(r"dev-[0-9a-f]{20}", request_id):
            raise KokiriError("Choose a development request ID returned by a typed command.")
        with self.locked(session_id) as (root, owned):
            self.identity(root, owned)
            for line in reversed(tail(root, "status.jsonl", 200)):
                try:
                    row = json.loads(line)
                    if isinstance(row, dict) and row.get("id") == request_id:
                        return {"session_id": session_id, "request_id": request_id, "reply": row}
                except ValueError:
                    continue
            return {"session_id": session_id, "request_id": request_id, "status": "pending"}

    def workshop(self, session_id: str, operation: str, **arguments) -> dict:
        from save_workshop import Workshop
        if operation not in {"snapshot","plan","apply","restore"}:
            raise KokiriError("Unsupported test-save operation.")
        with self.locked(session_id) as (root, owned):
            if not self.stopped(root, owned):
                raise KokiriError("Save editing requires a stopped owned test session.")
            try:
                workshop = Workshop(root/"profile", root/"save-state", stopped_check=lambda: self.stopped(root, owned))
                return getattr(workshop, operation)(**arguments)
            except ValueError as error:
                raise KokiriError(str(error)) from error
