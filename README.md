# zlib-replicant

The integrated historical-zlib deflate engine, extracted from the
zlib-fingerprint project into a standalone package.

A byte-exact, dependency-free Zig reimplementation of the zlib (RFC 1950)
**deflate** compressor covering the whole historical release range **1.0.1
through 1.4** — all eight empirical output-equivalence classes of stock
zlib:

| Class | Releases | What differs |
|---|---|---|
| A | 1.0.1–1.0.5 | 0xffff-clamped stored blocks, no pending-size cap |
| B | 1.0.6–1.0.9 | pending-size-capped stored blocks + `_tr_tally` early-block-stop heuristic |
| C | 1.1.0–1.2.0 | B minus the heuristic (TRUNCATE_BLOCK off) |
| D | 1.2.1–1.2.2 | 1.2.3 algorithm with earlier API limits |
| E | 1.2.3 | strategy dispatch inside deflate_fast/slow, legacy stored |
| F | 1.2.4–1.2.8 | dedicated deflate_huff/deflate_rle |
| G | 1.2.9 | rewritten deflate_stored (no final block for empty input) |
| H | 1.2.10–1.4 | modern deflate_stored |

Everything that never changed the compressed bytes across the range
(longest_match, fill_window, trees/Huffman coding, tables, adler32,
RFC 1950 framing) is shared code serving every version; the
class-specific behavior lives in dedicated modules
(`stored_1_0_x`, `stored_legacy`, `stored_1_2_9`, `stored`,
`fast_1_2_3`/`slow_1_2_3`, `rle`, `huff`, plus the legacy
FLEVEL/fill_window modes of `state`).

## API

```zig
const std = @import("std");
const replicant = @import("zlib-replicant");

pub fn main() !void {
    var c = try replicant.Compressor.init(std.heap.page_allocator);
    defer c.deinit();

    const input = "The quick brown fox jumps over the lazy dog. " ** 16;
    const out = try std.heap.page_allocator.alloc(
        u8, replicant.Compressor.requiredOutputLen(input.len));
    defer std.heap.page_allocator.free(out);

    // Byte-identical to zlib 1.2.11 `deflateInit2(level=6, memLevel=8,
    // strategy=Z_DEFAULT_STRATEGY, windowBits=15)` + one Z_FINISH call.
    const n = try c.compress(.v1_2_11, 6, 8, 0, 15, input, out);
    _ = n;
}
```

* `Compressor.compress(version, level, memLevel, strategy, windowBits,
  input, output)` — one-shot compression exactly like the historical
  `zlib-<version>` wrapper binaries (and `zlib.compress` in Python,
  `deflateSync` in Node, ...). Returns the compressed length.
* `Compressor.compressExpect(...)` — same, with an early-abort
  reference stream (`error.OutputMismatch` on the first divergence).
* `Compressor.requiredOutputLen(input_len)` — safe output-buffer size.
* `Version` / `all_versions` — the 19 selectable zlib versions
  (`1.0.5` .. `1.4`), displayed via `Version.name()`.
* `Variant` / `all_variants` — the seven distinct compressed-output
  behaviors (classes A–H; D shares E's dispatch) with
  `Variant.of(version)`, `Variant.rangeName()`, `Variant.covers()`.
* `pump(s, flush, variant)` — the low-level `deflate()` driver over a
  `DeflateState`, for stream-level control.

Per-release parameter limits (strategies 0–2 for A–C, no Z_FIXED for D,
the windowBits 8 acceptance rules of 1.0.x, the windowBits 8→9 remap of
1.2.1+) are enforced with `error.InvalidParams`, mirroring each release's
`deflateInit2_` validation.

## Differential-testing infrastructure

The package is **self-contained for differential verification**: `zig
build` produces the harness tools, `zig build test` runs the in-package
tests, and `scripts/` holds the suites that verify the engine against
independent oracles. Everything locates its tools and reference binaries
through `scripts/refenv.py`, which understands both this standalone
package and the enclosing zlib-fingerprint repository layout (and the
`$ZLIB_REF_BINARIES` override).

### Harness tools (`zig build` installs both)

| Tool | Role |
|---|---|
| `zcompress <version> <level> <memLevel> <strategy> <windowBits>` | compress stdin exactly like the historical `zlib-<version>` one-shot wrapper — the executable every suite drives |
| `zlegacy <a\|b\|c\|d> <level> <memLevel> <strategy> <windowBits>` | the **original C cores** (classes A–D: zlib 1.0.5 / 1.0.9 / 1.2.0 / 1.2.2 sources under `legacy/vendor/`), symbol-prefixed and statically linked — in-repo oracles, no downloads needed |

### Reference binaries (`binaries/`)

`binaries/build-references.sh` builds the official stock-zlib oracles for
**every release 1.0.1–1.4**: `zlib-<ver>` one-shot wrappers and
`zstream-<ver>` streaming-API wrappers, each linked against the real
version-specific static `libz.a` (sources vendored on demand). They are
the ground truth every "official" comparison uses.

### Differential suites (`scripts/`)

| Suite | What it proves |
|---|---|
| `diff_engine.py` | engine vs the official 1.2.3–1.3.1 wrappers (levels/memLevel/strategies/windowBits × payloads, level 0 in full depth) |
| `diff_native_legacy.py` | classes A–C vs the in-repo C cores (`zlegacy`) **and** every official class-member release binary; round-trip decompression of every stream |
| `diff_legacy_native.py` | the C-core oracles themselves vs genuine release binaries (oracle validation) |
| `diff_native_class_d.py` | class D vs the original 1.2.2 oracle |
| `audit_native_port.py` | version-wide one-shot audit, 15 releases (1.2.2–1.3.2), ~22,500 comparisons |
| `equivalence_matrix.py` | empirical byte-stream equivalence census over all available releases (the experiment that established the classes) |
| `stream_matrix.py` | streaming-API + full-depth one-shot differential across all 31 releases (`stream` / `oneshot` subcommands) |
| `probe_boundaries.py` | class-boundary witnesses across `avail_out` sizes |
| `build_options_check.py` | `-O0`/`-O3`/`UNALIGNED_OK`/`DEBUG` builds are byte-identical; `-DFASTEST` is the one legitimate difference |
| `asan_unstable.py` | ASan/UBSan validation of the documented unsafe paths of the originals |
| `analyze_splits.py` | follow-up analysis of `results/stream-matrix.json` |
| `regression_check.py` | end-to-end regression over the golden corpus (below): golden SHA-256, official-wrapper reproduction, engine reproduction, and — when the fingerprint search is present in the enclosing repository — search expectations |
| `gen_regression_fixtures.py` | regenerates the golden corpus (self-validating against the search when available) |

Run any of them directly, e.g.:

```sh
zig build                          # builds zcompress + zlegacy
python3 scripts/diff_native_legacy.py          # classes A-C vs C cores
python3 scripts/regression_check.py --skip-official
bash binaries/build-references.sh            # then: diff_engine.py etc.
```

### Golden regression corpus (`fixtures-regression/`)

20 minimal witnesses (one per equivalence-class boundary or identification
feature) with payloads, golden streams and SHA-256s in `manifest.json`.
The 13 engine cases cover classes A–H (stored layouts, the `_tr_tally`
heuristic, legacy huffman-only, Z_RLE generations, the 1.2.9 empty-input
bug, windowBits identification); the 7 companion cases (zopfli, miniz,
zlib-ng goldens) verify the sibling engines of the enclosing
zlib-fingerprint repository and are skipped automatically when those
tools are absent.

### Recorded evidence (`results/`)

The machine-readable results of the recorded experiments:
`equivalence-results.json`, `boundary-results.json`,
`stream-matrix.json`, `oneshot-ext-results.json`,
`build-options-results.json`, `asan-results.json`,
`native-port-audit.json`. Regenerating a report overwrites the file in
place. The full narrative of the experiments lives in
zlib-fingerprint's `EQUIVALENCE.md` (the repository this package was
extracted from): a 580,000+-invocation differential matrix over 31
statically linked releases (one-shot and streaming), boundary experiments
with varying `avail_out`, decompression round-trips of every produced
stream, and golden-vector tests.

## Building

```sh
zig build            # zcompress + zlegacy into zig-out/bin/
zig build test       # engine golden-vector tests + C-core oracle adapter tests
zig build -Doptimize=ReleaseFast
```

## Known limits (as verified)

* The modeled producer is the one-shot `Z_FINISH` wrapper call
  pattern; arbitrary mid-stream `deflateParams`/dictionary sequences are
  not reproduced.
* Class A level 0 with memLevel < 8 overruns zlib's own pending buffer
  (the originals crash or corrupt — reproduced faithfully at memLevel 8
  where the original survives on allocator slack).
* windowBits 8 at level >= 1 in classes A/B follows the originals into
  out-of-bounds reads and is refused with `error.InvalidParams`.

## Origin

Extracted from zlib-fingerprint's `src/deflate/` (commit `7b88abc` and
successors). The fingerprint search itself, the zlib-ng/miniz/Zopfli
ports and their wrappers remain in zlib-fingerprint; this package
carries the stock-zlib engine and its full differential stack.
