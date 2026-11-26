#!/usr/bin/env python3
"""End-to-end regression check over fixtures-regression/.

For every case in the manifest this asserts that

  1. the golden stream file still matches its recorded SHA-256;
  2. the official release wrapper (zlib-<ver>, when present)
     reproduces the golden byte for byte — validates the environment;
  3. the native engine (zig-out/bin/zcompress, zzopfli, zminiz or
     zzlibng) reproduces the golden byte for byte — catches any engine
     regression;
  4. the zlib-fingerprint search output (when the CLI is available in
     the enclosing repository) contains every expected substring —
     catches search-order, header-prediction and candidate-generation
     regressions.

Runs from the package or the enclosing zlib-fingerprint repository
(tools and reference wrappers are located via refenv.py). In the
standalone package the companion-engine cases (zzopfli/zminiz/zzlibng)
and the search expectations are skipped with a notice; the engine cases
(zcompress) and the golden integrity checks always run.

Exit code 0 iff every check that could run passes. Use --skip-official
on CI runners without the reference binaries, --skip-search to check
only the compression engines.
"""
import argparse
import hashlib
import json
import os
import pathlib
import subprocess
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import refenv

FR = refenv.PKG / "fixtures-regression"


def check(condition, failures, case, what):
    if not condition:
        failures.append(f"{case}: {what}")
    return condition


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--skip-official", action="store_true")
    parser.add_argument("--skip-engine", action="store_true")
    parser.add_argument("--skip-search", action="store_true")
    parser.add_argument("--timeout", type=float, default=300.0)
    args = parser.parse_args()

    manifest = json.loads((FR / "manifest.json").read_text(encoding="utf-8"))
    failures = []
    passed = skipped = 0
    engine_skips = {}
    search_available = refenv.find_tool("zlib-fingerprint") is not None
    if not search_available and not args.skip_search:
        print("note: zlib-fingerprint search CLI not built; the search "
              "expectation checks will be skipped")
    if not args.skip_official:
        try:
            refenv.ref_dir()
        except SystemExit as e:
            print(f"note: {e}; the official-wrapper checks will be skipped")
            args.skip_official = True

    for case in manifest:
        cid = case["id"]
        golden_path = FR / case["golden"]
        payload_path = FR / case["payload"]

        # 1. golden integrity
        if not check(golden_path.exists(), failures, cid, "golden missing"):
            continue
        golden = golden_path.read_bytes()
        digest = hashlib.sha256(golden).hexdigest()
        if not check(digest == case["golden_sha256"], failures, cid,
                     "golden sha256 mismatch"):
            continue
        payload = payload_path.read_bytes()

        # 2. official wrapper reproduction
        producer = case["producer"]
        official = None
        if producer["implementation"] == "zlib" and not args.skip_official:
            official = refenv.wrapper(producer["version"])
        if official is not None:
            if official.exists():
                proc = subprocess.run(
                    [str(official), *map(str, producer["params"])],
                    input=payload, stdout=subprocess.PIPE,
                    stderr=subprocess.DEVNULL, timeout=args.timeout)
                if check(proc.returncode == 0, failures, cid,
                         f"official wrapper rc={proc.returncode}"):
                    check(proc.stdout == golden, failures, cid,
                          "official wrapper output differs from golden")
                    passed += 1
            else:
                skipped += 1

        # 3. native engine reproduction
        if not args.skip_engine:
            engine = case["engine"]
            tool_name = engine["tool"]
            exe = refenv.find_tool(tool_name)
            if exe is None:
                if tool_name == "zcompress":
                    # the package's own tool must always be available
                    check(False, failures, cid,
                          f"{tool_name} not built (zig build)")
                    continue
                engine_skips.setdefault(tool_name, []).append(cid)
                continue
            proc = subprocess.run([str(exe), *engine["args"]],
                                  input=payload, stdout=subprocess.PIPE,
                                  stderr=subprocess.DEVNULL,
                                  timeout=args.timeout)
            if check(proc.returncode == 0, failures, cid,
                     f"engine rc={proc.returncode}"):
                check(proc.stdout == golden, failures, cid,
                      "native engine output differs from golden")
                passed += 1

        # 4. search identification
        expects = case.get("search_expects")
        if expects and not args.skip_search:
            fp = refenv.find_tool("zlib-fingerprint")
            if fp is None:
                engine_skips.setdefault(
                    "zlib-fingerprint", []).append(cid)
                continue
            proc = subprocess.run([str(fp), str(golden_path)],
                                  stdout=subprocess.PIPE,
                                  stderr=subprocess.DEVNULL,
                                  timeout=args.timeout)
            out = proc.stdout.decode("utf-8", "replace")
            for expect in expects:
                check(expect in out, failures, cid,
                      f"search output missing {expect!r}")
            passed += 1

    print(f"{len(manifest)} cases: {passed} checks passed, "
          f"{skipped} official-wrapper checks skipped (binary absent)")
    for tool_name, cids in sorted(engine_skips.items()):
        print(f"  skipped {len(cids)} case(s) needing {tool_name} "
              "(companion tool/search CLI not built in this checkout)")
    if failures:
        print("FAILURES:")
        for f in failures:
            print(f"  - {f}")
        sys.exit(1)
    print("All available regression checks passed.")


if __name__ == "__main__":
    main()
