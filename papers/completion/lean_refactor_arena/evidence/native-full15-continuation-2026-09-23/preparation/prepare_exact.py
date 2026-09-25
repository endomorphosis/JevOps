"""One-shot trusted preparation payload; run only through arena_prepare.

Never edits existing projects. Sources/caches are independent copies at exact
lockfile revisions. Import scanning only prefetches caches; Lake and the native
verifier remain authoritative. No proof success is inferred from build success.
"""
import argparse
import json
import os
from pathlib import Path
import re
import subprocess


def run(*args, cwd=None):
    print("RUN", *map(str, args), flush=True)
    subprocess.run(list(map(str, args)), cwd=cwd, check=True)


def git(path, *args):
    return subprocess.check_output(["git", "-C", str(path), *args], text=True).strip()


def clone(url, commit, dest, source=None):
    if dest.exists():
        raise ValueError(f"refusing existing destination: {dest}")
    if not re.fullmatch(r"[0-9a-f]{40}", commit):
        raise ValueError("exact commit required")
    if source is not None:
        run("git", "clone", "--no-hardlinks", "--no-checkout", source, dest)
        run("git", "remote", "set-url", "origin", url, cwd=dest)
    else:
        run("git", "init", dest)
        run("git", "remote", "add", "origin", url, cwd=dest)
        run("git", "fetch", "--depth", "1", "origin", commit, cwd=dest)
    run("git", "checkout", "--detach", commit, cwd=dest)
    assert git(dest, "rev-parse", "HEAD") == commit


def dependencies(root, manifest, caches):
    directory = root / ".lake/packages"
    directory.mkdir(parents=True, exist_ok=True)
    roots = [root]
    for package in manifest["packages"]:
        name = package["name"].removeprefix("«").removesuffix("»")
        assert re.fullmatch(r"[A-Za-z_][A-Za-z_0-9-]*", name)
        assert package["type"] == "git"
        target = directory / name
        if target.exists():  # Only preinstalled Mathlib in a brand-new Putnam root.
            assert name == "mathlib" and git(target, "rev-parse", "HEAD") == package["rev"]
        else:
            match = None
            for cache in caches:
                path = cache / ".lake/packages" / name
                if path.is_dir() and git(path, "rev-parse", "HEAD") == package["rev"]:
                    assert not git(path, "status", "--porcelain", "--untracked-files=no")
                    match = path
                    break
            if match:
                run("cp", "-a", "--reflink=auto", match, target)
            else:
                clone(package["url"], package["rev"], target)
        assert not git(target, "status", "--porcelain", "--untracked-files=no")
        roots.append(target / package["subDir"] if package.get("subDir") else target)
    return roots


def external_imports(roots, modules):
    """Bounded conservative prefetch only, not a Lean parser/security boundary."""
    imports = re.compile(r"^\s*(?:(?:public|private|meta)\s+)*import\s+(?:all\s+)?([\w.]+)", re.M)
    cache_names = {"Mathlib", "Aesop", "Batteries", "Qq", "Plausible", "ProofWidgets", "LeanSearchClient", "ImportGraph"}
    pending, seen, external = list(modules), set(), set()
    while pending:
        module = pending.pop()
        if module in seen:
            continue
        seen.add(module)
        if len(seen) > 20000:
            raise ValueError("import prefetch bound")
        if module.split(".")[0] in cache_names:
            external.add(module)
            continue
        path = next((r / (module.replace(".", "/") + ".lean") for r in roots
                     if (r / (module.replace(".", "/") + ".lean")).is_file()), None)
        if path is not None:
            pending.extend(imports.findall(path.read_text()))
    return sorted(external)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--destination", type=Path, required=True)
    parser.add_argument("--tag", required=True)
    parser.add_argument("--commit", required=True)
    parser.add_argument("--repository")
    parser.add_argument("--source", type=Path)
    parser.add_argument("--cache", type=Path, action="append", default=[])
    parser.add_argument("--target", action="append", default=[])
    parser.add_argument("--putnam", action="store_true")
    args = parser.parse_args()
    root = args.destination
    assert re.fullmatch(r"v\d+\.\d+\.\d+", args.tag)
    assert not root.exists(), "destination must be new"
    os.environ["MATHLIB_NO_CACHE_ON_UPDATE"] = "1"
    if args.putnam:
        root.mkdir()
        package_root = root / ".lake/packages"
        package_root.mkdir(parents=True)
        clone("https://github.com/leanprover-community/mathlib4", args.commit, package_root / "mathlib")
        mathlib = package_root / "mathlib"
        assert (mathlib / "lean-toolchain").read_text().strip() == "leanprover/lean4:" + args.tag
        manifest = json.loads((mathlib / "lake-manifest.json").read_text())
        for entry in manifest["packages"]:
            entry["inherited"] = True
        manifest["packages"].insert(0, {"name": "mathlib", "type": "git", "subDir": None,
            "url": "https://github.com/leanprover-community/mathlib4", "rev": args.commit,
            "inputRev": args.commit, "inherited": False, "scope": "leanprover-community",
            "manifestFile": "lake-manifest.json", "configFile": "lakefile.lean"})
        manifest["name"] = "jevops_putnam"
        (root / "lake-manifest.json").write_text(json.dumps(manifest, indent=2) + "\n")
        (root / "lean-toolchain").write_text("leanprover/lean4:" + args.tag + "\n")
        (root / "lakefile.toml").write_text('name = "jevops_putnam"\n\n[[require]]\nname = "mathlib"\ngit = "https://github.com/leanprover-community/mathlib4"\nrev = "' + args.commit + '"\n')
    else:
        assert args.repository and args.source and args.target
        clone(args.repository, args.commit, root, args.source)
        manifest = json.loads((root / "lake-manifest.json").read_text())
    assert (root / "lean-toolchain").read_text().strip() == "leanprover/lean4:" + args.tag
    roots = dependencies(root, manifest, args.cache)
    cache_modules = ["Mathlib", "Aesop"] if args.putnam else external_imports(roots, args.target)
    print("PREFETCH", json.dumps(cache_modules), flush=True)
    before = (root / "lake-manifest.json").read_bytes()
    if cache_modules:
        run("lake", "--no-cache", "exe", "cache", "get", *cache_modules, cwd=root)
    if not args.putnam:
        run("lake", "--no-cache", "build", *("+" + m + ":deps" for m in args.target), cwd=root)
    assert (root / "lake-manifest.json").read_bytes() == before, "Lake changed pinned lockfile"
    print("PREPARATION_COMPLETED_NOT_PROOF", root, flush=True)


if __name__ == "__main__":
    main()
