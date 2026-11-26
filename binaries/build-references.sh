#!/usr/bin/env bash
# Build the official stock-zlib reference wrappers used by the
# zlib-replicant differential suites:
#
#   zlib-<version>     one-shot wrapper  (diff_engine.py, audit_native_port.py,
#                      equivalence_matrix.py, regression corpus ...)
#   zstream-<version>  streaming-API wrapper (stream_matrix.py,
#                      probe_boundaries.py, asan_unstable.py ...)
#
# Every release from 1.0.1 through 1.4 is built from the official upstream
# sources (vendored on demand into vendor/). Linking the wrapper against the
# real version-specific static library is what makes the wrapper genuinely
# reproduce that release's bitstream behavior; linking -lz against the
# system library would silently fake the version.
#
# Output directory: $OUT_DIR (default: this script's directory, i.e. the
# package's binaries/). Vendor trees: $VENDOR_DIR (default: $OUT_DIR/vendor).
# The enclosing zlib-fingerprint repository calls this script with both
# pointing at its own binaries/ directory.
set -e

PDIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
OUT_DIR="${OUT_DIR:-$PDIR}"
VENDOR_DIR="${VENDOR_DIR:-$OUT_DIR/vendor}"
mkdir -p "$VENDOR_DIR"

if [[ "$OSTYPE" == "msys" || "$OSTYPE" == "cygwin" ]]; then
    EXT=".exe"
else
    EXT=""
fi

check_binary() {
    local name="$1"
    local bin_file="$OUT_DIR/$name$EXT"
    if [ -f "$bin_file" ]; then
        echo "-> [SKIP] $bin_file already exists."
        return 0
    fi
    return 1
}

fetch() { # fetch <url> <dest-file> (atomic: partial downloads never persist)
    if [ -f "$2" ]; then
        return 0
    fi
    echo "   downloading $(basename "$2")..."
    curl -fsSL --retry 2 --max-time 180 -o "$2.part" "$1" && mv "$2.part" "$2" || {
        rm -f "$2.part" "$2"
        return 1
    }
}

build_zlib() { # build_zlib <version> <url>
    local ver="$1" url="$2"
    if check_binary "zlib-$ver"; then return 0; fi
    echo "[zlib] Building zlib $ver..."
    local dir
    if [ -d "$VENDOR_DIR/zlib-$ver" ]; then
        dir="$VENDOR_DIR/zlib-$ver"
    elif [ -d "$VENDOR_DIR/zlib-v$ver" ]; then
        dir="$VENDOR_DIR/zlib-v$ver"
    else
        fetch "$url" "$VENDOR_DIR/zlib-$ver.tar.gz"
        tar -xzf "$VENDOR_DIR/zlib-$ver.tar.gz" -C "$VENDOR_DIR"
        if [ -d "$VENDOR_DIR/zlib-v$ver" ]; then dir="$VENDOR_DIR/zlib-v$ver"; else dir="$VENDOR_DIR/zlib-$ver"; fi
    fi
    # Build the REAL version library first; linking against it is what makes
    # the wrapper genuinely reproduce this version's bitstream behavior
    # (linking -lz against the system lib would silently fake the version).
    ( cd "$dir" \
      && ./configure --static >/dev/null 2>&1 \
      && make -j"$(nproc)" libz.a >/dev/null 2>&1 )
    ( cd "$dir" && gcc -O3 "$PDIR/zlib_wrapper.c" -I. -L. -lz -o "$OUT_DIR/zlib-$ver$EXT" )
    echo "-> built $OUT_DIR/zlib-$ver$EXT"
}

# Scenario-driven streaming wrapper (chunked input, flush operations, capped
# avail_out, deflateParams/SetDictionary/Reset/Copy) around the same
# version-specific static library.
build_zstream() { # build_zstream <version> <url>
    local ver="$1" url="$2"
    if check_binary "zstream-$ver"; then return 0; fi
    echo "[zstream] Building zstream $ver..."
    local dir
    if [ -d "$VENDOR_DIR/zlib-$ver" ]; then
        dir="$VENDOR_DIR/zlib-$ver"
    elif [ -d "$VENDOR_DIR/zlib-v$ver" ]; then
        dir="$VENDOR_DIR/zlib-v$ver"
    else
        fetch "$url" "$VENDOR_DIR/zlib-$ver.tar.gz"
        tar -xzf "$VENDOR_DIR/zlib-$ver.tar.gz" -C "$VENDOR_DIR"
        if [ -d "$VENDOR_DIR/zlib-v$ver" ]; then dir="$VENDOR_DIR/zlib-v$ver"; else dir="$VENDOR_DIR/zlib-$ver"; fi
    fi
    ( cd "$dir" \
      && ./configure --static >/dev/null 2>&1 \
      && make -j"$(nproc)" libz.a >/dev/null 2>&1 )
    ( cd "$dir" && gcc -O2 "$PDIR/zstream_wrapper.c" -I. -L. -lz -o "$OUT_DIR/zstream-$ver$EXT" )
    echo "-> built $OUT_DIR/zstream-$ver$EXT"
}

GITHUB_ZLIB="https://github.com/madler/zlib/archive/refs/tags"
# Historical, potentially bitstream-distinct releases. These are deliberately
# NOT marked covered by the integrated 1.2.3+ engine. All versions are
# fetched from the upstream GitHub mirror (faster than zlib.net/fossils and
# serving identical release sources); the only tag missing there is v1.0.6,
# which keeps the fossils URL.
for ver in 1.0.1 1.0.2 1.0.4 1.0.5 1.0.7 1.0.8 1.0.9 \
           1.1.0 1.1.1 1.1.2 1.1.3 1.1.4; do
    build_zlib "$ver" "$GITHUB_ZLIB/v$ver.tar.gz"
    build_zstream "$ver" "$GITHUB_ZLIB/v$ver.tar.gz"
done
build_zlib    "1.0.6" "https://zlib.net/fossils/zlib-1.0.6.tar.gz"
build_zstream "1.0.6" "https://zlib.net/fossils/zlib-1.0.6.tar.gz"
for ver in 1.2.0 1.2.1 1.2.2; do
    build_zlib "$ver" "$GITHUB_ZLIB/v$ver.tar.gz"
    build_zstream "$ver" "$GITHUB_ZLIB/v$ver.tar.gz"
done
for ver in 1.2.3 1.2.4 1.2.5 1.2.6 1.2.7 1.2.8 1.2.9 1.2.10 1.2.11 \
           1.2.12 1.2.13 1.3; do
    build_zlib "$ver" "$GITHUB_ZLIB/v$ver.tar.gz"
    build_zstream "$ver" "$GITHUB_ZLIB/v$ver.tar.gz"
done
build_zlib    "1.3.1" "https://github.com/madler/zlib/releases/download/v1.3.1/zlib-1.3.1.tar.gz"
build_zstream "1.3.1" "https://github.com/madler/zlib/releases/download/v1.3.1/zlib-1.3.1.tar.gz"
build_zlib    "1.3.2" "$GITHUB_ZLIB/v1.3.2.tar.gz"
build_zstream "1.3.2" "$GITHUB_ZLIB/v1.3.2.tar.gz"
build_zlib    "1.4" "$GITHUB_ZLIB/v1.4.tar.gz"
build_zstream "1.4" "$GITHUB_ZLIB/v1.4.tar.gz"

echo "=== zlib-replicant reference wrappers ready in: $OUT_DIR ==="
