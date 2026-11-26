#!/usr/bin/env python3
"""Generate fixtures-regression/: minimal distinguishing payloads, golden
streams from the official release binaries / native Zopfli, and the
manifest consumed by scripts/regression_check.py.

Every case is a minimal witness of a known output-equivalence class
boundary (see EQUIVALENCE.md) or a header/parameter identification
feature. The generator self-validates: after producing each golden it
runs the actual zlib-fingerprint search and asserts that the expected
substrings appear in the output, so the manifest can never encode a
stale expectation.

Cases where several classes honestly coincide in the one-shot producer
model (e.g. class D streams, or level-0 layouts shared across modern
generations) pin the *documented collapse* rather than a unique range.

Runs from the package or the enclosing zlib-fingerprint repository
(tools and reference binaries via refenv.py). The companion-engine
cases (Zopfli/miniz/zlib-ng) are regenerated only when their oracle is
available; otherwise the existing manifest entries are carried over
unchanged instead of being silently dropped. Standalone regeneration
without the search CLI requires --allow-no-search.
"""
import hashlib
import json
import os
import pathlib
import random
import subprocess
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import refenv

ROOT = refenv.PKG
FR = ROOT / "fixtures-regression"
FP = refenv.find_tool("zlib-fingerprint")
rng = random.Random(0x5E675E55)
text = b"The quick brown fox jumps over the lazy dog. " * 100
payloads = {
    "repeat-100": b"A" * 100,
    "repeat-65535": b"A" * 65535,
    "repeat-32": b"A" * 32,
    "periodic-131072": (b"abc123\x00\xff" * 16384),
    "periodic-1000": (b"abcdefgh" * 125),
    "text-4096": (text * 4)[:4096],
    "random-2000": rng.randbytes(2000),
    "empty": b"",
}
# Committed payload with no deterministic recipe: never regenerated,
# only read (the miniz/zlib-ng cases witness it).
MIXED = FR / "payloads" / "mixed-20k.bin"

# id, producer version, payload, [level, memLevel, strategy, windowBits],
# engine version for zcompress, expected search substrings (None = skip
# the search check, e.g. too slow or documented no-match), note
CASES = [
    ("a-stored", "1.0.5", "repeat-65535", [0, 8, 0, 15], "1.0.5",
     ["zlib class A", "zlib 0.99-1.0.5", "level=0"],
     "class A stored layout: first block is the full 65535 bytes"),
    ("a-wbits8-level0", "1.0.5", "periodic-1000", [0, 8, 0, 8], "1.0.5",
     None,
     "deterministic data-losing windowBits-8 stream; engine check only "
     "(the full search sweep over wbits is too slow for CI)"),
    ("b-truncate", "1.0.9", "periodic-131072", [3, 8, 0, 9], "1.0.9",
     ["zlib class B", "zlib 1.0.6-1.0.9", "windowBits=9"],
     "_tr_tally early-block-stop heuristic witness (2020 vs 2001 bytes)"),
    ("c-huff-only", "1.2.0", "text-4096", [6, 8, 2, 15], "1.2.0",
     ["zlib class C", "strategy=huffman-only"],
     "legacy huffman-only at a level whose FLEVEL is level-based"),
    ("c-no-heuristic", "1.2.0", "periodic-131072", [3, 8, 0, 9], "1.2.0",
     ["zlib 1.2.3-1.4", "level=3"],
     "class C output coincides with modern zlib here: honest collapse"),
    ("d-default", "1.2.2", "random-2000", [1, 8, 0, 15], "1.2.2",
     ["zlib 1.2.3-1.4", "level=0"],
     "class D is byte-identical to the modern class; level-1 expansion "
     "on incompressible data coincides with the stored layout"),
    ("e-rle", "1.2.3", "repeat-65535", [1, 8, 3, 15], "1.2.3",
     ["zlib 1.2.3", "strategy=rle"],
     "1.2.3 Z_RLE (deflate_fast + longest_match_fast): 150 bytes vs 85 "
     "from 1.2.4+ deflate_rle"),
    ("f-rle", "1.2.8", "repeat-65535", [1, 8, 3, 15], "1.2.8",
     ["strategy=rle", "zlib 1.2.4-1.4"],
     "dedicated deflate_rle path of 1.2.4+"),
    ("g-stored", "1.2.9", "repeat-100", [0, 8, 0, 15], "1.2.9",
     ["zlib 1.2.3-1.4", "level=0"],
     "1.2.9 stored layout coincides with the other generations on this "
     "payload; the one-shot-distinguishable 1.2.9 empty-input stream is "
     "truncated (invalid) and cannot be searched"),
    ("g-empty-truncated", "1.2.9", "empty", [0, 8, 0, 15], "1.2.9",
     ["inflate failed"],
     "the documented 1.2.9 bug: empty input at level 0 emits a truncated "
     "stored-block header; the search must fail honestly"),
    ("h-default", "1.2.11", "text-4096", [6, 8, 0, 15], "1.2.11",
     ["zlib 1.2.3-1.4", "level=6"],
     "modern default-level stream; whole modern range reproduces it"),
    ("h-wbits12", "1.2.11", "periodic-1000", [6, 8, 0, 12], "1.2.11",
     ["zlib 1.2.3-1.4", "windowBits=12"],
     "windowBits from CINFO identification"),
    ("h14-default", "1.4", "text-4096", [6, 8, 0, 15], "1.3.2",
     ["zlib 1.2.3-1.4", "level=6"],
     "zlib 1.4 (Nov 2026): byte-identical to 1.3.2 in the one-shot model; "
     "engine representative 1.3.2 reproduces it"),
]

ZOPFLI_CASES = [
    ("zopfli-100", "text-4096", 15, "1.0.0", ["zopfli 1.0.0"],
     "header 78 01, fixed-RLE tree encoder"),
    ("zopfli-101", "text-4096", 15, "1.0.1", ["zopfli 1.0.1"],
     "header 78 01, always-RLE histogram"),
    ("zopfli-103", "text-4096", 15, "1.0.3", ["zopfli 1.0.2-1.0.3"],
     "header 78 da, auto block types"),
]

# Golden produced by the official miniz-3.1.2 wrapper; engine witness is
# the native tdefl port (zminiz) checked at regression time.
MINIZ_CASES = [
    ("miniz-greedy1", "mixed-20k", 1, ["miniz 3.1.2", "level=1"],
     "miniz 3.1.2 tdefl greedy level 1 (probes=1; the released scalar "
     "build runs compress_normal, not compress_fast)"),
    ("miniz-lazy4", "mixed-20k", 4, ["miniz 3.1.2 (in-process)", "level=2"],
     "miniz 3.1.2 tdefl level 4 stream (identical to level 2 on this "
     "payload: probes 6/16 find no matches here, honest reproducer is "
     "level 2)"),
]

# Golden produced by the official zlib-ng-2.2.1 wrapper; engine witness
# is the native zlib-ng port (zzlibng) checked at regression time.
ZLIBNG_CASES = [
    ("zlibng-quick1", "mixed-20k", [1, 8, 0, 15],
     ["zlib-ng 2.2.1 (in-process)", "level=1"],
     "zlib-ng 2.2.1 (compat) deflate_quick level 1: static-tree quick "
     "path unique to zlib-ng"),
    ("zlibng-medium6", "mixed-20k", [6, 8, 0, 15], [],
     "zlib-ng 2.2.1 (compat) deflate_medium level 6 (default); "
     "byte-identical to stock zlib 6 on this payload: honest collapse to "
     "the integrated engine first"),
]


def sha256(data):
    return hashlib.sha256(data).hexdigest()


def payload_bytes(name):
    if name == "mixed-20k":
        if not MIXED.exists():
            sys.exit("payloads/mixed-20k.bin is a committed fixture payload "
                     "(no deterministic recipe); it is missing")
        return MIXED.read_bytes()
    return payloads[name]


def search_output(golden_path):
    proc = subprocess.run([str(FP), str(golden_path)],
                          stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
                          cwd=ROOT, timeout=600)
    return proc.returncode, proc.stdout.decode("utf-8", "replace")


def validate_search(cid, golden_path, expects, failures):
    if expects is None:
        return
    if FP is None:
        print(f"  .. {cid}: search validation skipped (no search CLI)")
        return
    rc, out = search_output(golden_path)
    missing = [s for s in expects if s not in out]
    if missing:
        failures.append((cid, missing, rc))
        print(f"  !! {cid}: search output missing {missing} (rc={rc})")
    else:
        print(f"  ok {cid}: search matched all {len(expects)} expects")


def existing_manifest():
    path = FR / "manifest.json"
    if not path.exists():
        return {}
    try:
        return {c["id"]: c for c in json.loads(path.read_text())}
    except (json.JSONDecodeError, KeyError):
        return {}


def carry_over(cid, existing, manifest):
    if cid in existing:
        manifest.append(existing[cid])
        print(f"  .. {cid}: carried over from the existing manifest "
              "(oracle/tool unavailable)")
        return True
    print(f"  ?? {cid}: skipped (oracle/tool unavailable and no existing "
          "manifest entry)")
    return False


def main():
    allow_no_search = "--allow-no-search" in sys.argv
    if FP is None and not allow_no_search:
        sys.exit("the zlib-fingerprint search CLI is not built; regeneration "
                 "without its self-validation requires --allow-no-search")

    (FR / "payloads").mkdir(parents=True, exist_ok=True)
    (FR / "golden").mkdir(parents=True, exist_ok=True)
    for name, data in payloads.items():
        (FR / "payloads" / f"{name}.bin").write_bytes(data)

    existing = existing_manifest()
    manifest = []
    failures = []
    for cid, ver, fix, params, engine, expects, note in CASES:
        data = payload_bytes(fix)
        wrapper = refenv.wrapper(ver)
        if not wrapper.is_file():
            sys.exit(f"official zlib-{ver} reference wrapper not found; "
                     "build the wrappers first (binaries/build-references.sh)")
        proc = subprocess.run(
            [str(wrapper), *[str(x) for x in params]],
            input=data, stdout=subprocess.PIPE, cwd=ROOT)
        if proc.returncode != 0:
            sys.exit(f"official wrapper failed for {cid}")
        golden = proc.stdout
        (FR / "golden" / f"{cid}.zlib").write_bytes(golden)
        entry = {
            "id": cid,
            "description": note,
            "payload": f"payloads/{fix}.bin",
            "producer": {"implementation": "zlib", "version": ver,
                         "params": params},
            "golden": f"golden/{cid}.zlib",
            "golden_sha256": sha256(golden),
            "engine": {"tool": "zcompress", "version": engine,
                       "args": [engine, *map(str, params)]},
            "search_expects": expects,
        }
        validate_search(cid, FR / "golden" / f"{cid}.zlib", expects, failures)
        manifest.append(entry)
        print(f"{cid:18s} zlib {ver:6s} {fix:16s} {params} -> "
              f"{len(golden):6d}B {sha256(golden)[:12]}")

    zzopfli = refenv.find_tool("zzopfli")
    for cid, fix, iters, rel, expects, note in ZOPFLI_CASES:
        if zzopfli is None:
            carry_over(cid, existing, manifest)
            continue
        data = payload_bytes(fix)
        proc = subprocess.run([str(zzopfli), str(iters), rel], input=data,
                              stdout=subprocess.PIPE, cwd=ROOT)
        if proc.returncode != 0:
            sys.exit(f"zzopfli failed for {cid}")
        golden = proc.stdout
        (FR / "golden" / f"{cid}.zlib").write_bytes(golden)
        validate_search(cid, FR / "golden" / f"{cid}.zlib", expects, failures)
        manifest.append({
            "id": cid,
            "description": note,
            "payload": f"payloads/{fix}.bin",
            "producer": {"implementation": "zopfli", "version": rel,
                         "params": [iters]},
            "golden": f"golden/{cid}.zlib",
            "golden_sha256": sha256(golden),
            "engine": {"tool": "zzopfli", "version": rel,
                       "args": [str(iters), rel]},
            "search_expects": expects,
        })
        print(f"{cid:18s} zopfli {rel} it={iters} -> "
              f"{len(golden):6d}B {sha256(golden)[:12]}")

    def companion_oracle(binary_name, vendor_sub=""):
        for base in ([refenv.REPO] if refenv.REPO else []) + [refenv.PKG]:
            exe = base / "binaries" / binary_name
            if exe.is_file():
                lib_dir = base / "binaries" / "vendor" / vendor_sub \
                    if vendor_sub else None
                return exe, lib_dir
        return None, None

    miniz_bin, _ = companion_oracle("miniz-3.1.2")
    for cid, fix, level, expects, note in MINIZ_CASES:
        if miniz_bin is None:
            carry_over(cid, existing, manifest)
            continue
        data = payload_bytes(fix)
        proc = subprocess.run([str(miniz_bin), str(level)], input=data,
                              stdout=subprocess.PIPE, cwd=ROOT)
        if proc.returncode != 0:
            sys.exit(f"miniz wrapper failed for {cid}")
        golden = proc.stdout
        (FR / "golden" / f"{cid}.zlib").write_bytes(golden)
        validate_search(cid, FR / "golden" / f"{cid}.zlib", expects, failures)
        manifest.append({
            "id": cid,
            "description": note,
            "payload": f"payloads/{fix}.bin",
            "producer": {"implementation": "miniz", "version": "3.1.2",
                         "params": [level]},
            "golden": f"golden/{cid}.zlib",
            "golden_sha256": sha256(golden),
            "engine": {"tool": "zminiz", "version": "3.1.2",
                       "args": [str(level)]},
            "search_expects": expects,
        })
        print(f"{cid:18s} miniz 3.1.2 lvl={level} -> "
              f"{len(golden):6d}B {sha256(golden)[:12]}")

    zlibng_bin, zlibng_lib = companion_oracle("zlib-ng-2.2.1",
                                               "zlib-ng-2.2.1")
    for cid, fix, params, expects, note in ZLIBNG_CASES:
        if zlibng_bin is None:
            carry_over(cid, existing, manifest)
            continue
        data = payload_bytes(fix)
        env = dict(os.environ)
        if zlibng_lib is not None:
            env["LD_LIBRARY_PATH"] = str(zlibng_lib) + (
                ":" + env["LD_LIBRARY_PATH"] if env.get("LD_LIBRARY_PATH")
                else "")
        proc = subprocess.run(
            [str(zlibng_bin), *map(str, params)], input=data,
            stdout=subprocess.PIPE, cwd=ROOT, env=env)
        if proc.returncode != 0:
            sys.exit(f"zlib-ng wrapper failed for {cid}")
        golden = proc.stdout
        (FR / "golden" / f"{cid}.zlib").write_bytes(golden)
        validate_search(cid, FR / "golden" / f"{cid}.zlib", expects, failures)
        manifest.append({
            "id": cid,
            "description": note,
            "payload": f"payloads/{fix}.bin",
            "producer": {"implementation": "zlib-ng", "version": "2.2.1",
                         "params": params},
            "golden": f"golden/{cid}.zlib",
            "golden_sha256": sha256(golden),
            "engine": {"tool": "zzlibng", "version": "2.2.1",
                       "args": list(map(str, params))},
            "search_expects": expects,
        })
        print(f"{cid:18s} zlib-ng 2.2.1 {params} -> "
              f"{len(golden):6d}B {sha256(golden)[:12]}")

    (FR / "manifest.json").write_text(json.dumps(manifest, indent=2),
                                      encoding="utf-8")
    print(f"{len(manifest)} cases -> {FR / 'manifest.json'}")
    if failures:
        print("\nSEARCH EXPECTATION FAILURES:")
        for cid, missing, rc in failures:
            print(f"  {cid}: missing {missing} (rc={rc})")
        sys.exit(1)


if __name__ == "__main__":
    main()
