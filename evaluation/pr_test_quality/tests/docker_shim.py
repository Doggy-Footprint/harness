SHIM = r'''#!%(python)s
import json, os, subprocess, sys, shutil
from pathlib import Path

root = Path(os.environ["SHIM_DIR"])
state_path = root / "state.json"
state = json.loads(state_path.read_text()) if state_path.exists() else {"containers": {}, "networks": [], "log": []}
args = sys.argv[1:]
state["log"].append(args)


def save():
    state_path.write_text(json.dumps(state))


def files(cid):
    d = root / "files" / cid
    d.mkdir(parents=True, exist_ok=True)
    return d


def resolve(ref):
    for name, c in state["containers"].items():
        if ref in (name, c["id"]):
            return name, c
    return None, None


def fail(msg, code=1):
    save()
    sys.stderr.write(msg + "\n")
    sys.exit(code)


cmd = args[0] if args else ""
if cmd in ("info", "version"):
    save()
    print("ok")
elif cmd == "image" and args[1] == "inspect":
    missing = (root / "missing").read_text().split() if (root / "missing").exists() else []
    if args[-1] in missing:
        fail("Error: No such image: " + args[-1])
    save()
    print("sha256:" + "ab" * 16 + "-" + args[-1])
elif cmd == "container" and args[1] == "inspect":
    name, c = resolve(args[-1])
    if c is None:
        fail("Error: No such container: " + args[-1])
    save()
    print(json.dumps({"Id": c["id"], "Name": "/" + name, "State": {"Running": c["running"], "Status": "running" if c["running"] else "created"},
                      "Config": {"Labels": c["labels"]}}))
elif cmd == "network" and args[1] == "inspect":
    if args[-1] not in state["networks"]:
        fail("Error: No such network")
    save()
    print("[]")
elif cmd == "network" and args[1] == "create":
    state["networks"].append(args[-1])
    save()
    print("netid")
elif cmd in ("run", "create"):
    name = args[args.index("--name") + 1]
    labels = {}
    for i, a in enumerate(args):
        if a == "--label":
            k, _, v = args[i + 1].partition("=")
            labels[k] = v
    cid = "cid-" + name
    state["containers"][name] = {"id": cid, "running": cmd == "run", "labels": labels, "args": args}
    save()
    print(cid)
elif cmd in ("start", "stop"):
    name, c = resolve(args[-1])
    if c is None:
        fail("Error: No such container")
    c["running"] = cmd == "start"
    save()
    print(args[-1])
elif cmd == "rm":
    name, c = resolve(args[-1])
    if c is not None:
        del state["containers"][name]
        shutil.rmtree(root / "files" / c["id"], ignore_errors=True)
    save()
elif cmd == "exec":
    rest = args[1:]
    while rest and rest[0] in ("-u", "-w"):
        rest = rest[2:]
    name, c = resolve(rest[0])
    if c is None or not c["running"]:
        fail("Error: container is not running", 1)
    save()
    sys.exit(subprocess.run(rest[1:]).returncode)
elif cmd == "cp":
    src, dst = args[1], args[2]
    if ":" in dst and not dst.startswith("/"):
        cref, _, path = dst.partition(":")
        name, c = resolve(cref)
        if c is None:
            fail("Error: No such container")
        target = files(c["id"]) / path.lstrip("/")
        target.parent.mkdir(parents=True, exist_ok=True)
        if Path(src).is_dir():
            shutil.copytree(src, target, dirs_exist_ok=True)
        else:
            shutil.copy(src, target)
    else:
        cref, _, path = src.partition(":")
        name, c = resolve(cref)
        if c is None:
            fail("Error: No such container")
        origin = files(c["id"]) / path.lstrip("/").rstrip(".").rstrip("/")
        if not origin.exists():
            fail("Error: Could not find the file " + path + " in container")
        if origin.is_dir():
            shutil.copytree(origin, dst, dirs_exist_ok=True)
        else:
            Path(dst).parent.mkdir(parents=True, exist_ok=True)
            shutil.copy(origin, dst)
    save()
elif cmd == "build":
    ctx = Path(args[-1])
    save()
    if (ctx / "FAIL").exists():
        print("step 1\nstep 2\nboom: build failed")
        sys.exit(1)
    print("built ok")
else:
    save()
'''
