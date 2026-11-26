# Reference binaries (`binaries/`)

This directory holds the **official stock-zlib differential oracles** of
the package and the scripts to build them:

| File | Role |
|---|---|
| `zlib_wrapper.c` | one-shot stdin->stdout wrapper (`deflateInit2_` + one `Z_FINISH`), linked against a specific version's statically built `libz.a` |
| `zstream_wrapper.c` | streaming-API wrapper (chunked input, flush operations, capped `avail_out`, `deflateParams`/`SetDictionary`/`Reset`/`Copy`) |
| `build-references.sh` | builds `zlib-<ver>` and `zstream-<ver>` for **every release 1.0.1 through 1.4** from the official upstream sources |

The wrappers are compiled against the real, version-specific static
library — never the system `-lz` — which is what makes each wrapper
genuinely reproduce that release's bitstream. The upstream sources are
vendored on demand into `binaries/vendor/` (re-downloadable; not part of
the package).

Usage (standalone package):

```sh
cd binaries && ./build-references.sh     # or bash build-references.sh
```

The enclosing zlib-fingerprint repository calls the same script with
`OUT_DIR`/`VENDOR_DIR` pointing at its own `binaries/`, so one shared set
of reference wrappers serves both the package suites and the repository's
`--external-zlib` audit mode.

The resulting binaries are the oracles for the differential suites in
`../scripts/` (`diff_engine.py`, `diff_native_legacy.py`,
`equivalence_matrix.py`, `stream_matrix.py`, `audit_native_port.py`,
`regression_check.py`, ...). Missing wrappers are resolved through
`scripts/refenv.py`: `$ZLIB_REF_BINARIES`, the enclosing repository's
`binaries/`, then this directory.
