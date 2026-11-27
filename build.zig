const std = @import("std");

pub fn build(b: *std.Build) void {
    const target = b.standardTargetOptions(.{});
    const optimize = b.standardOptimizeOption(.{});

    // The single importable module of this package: the integrated
    // historical-zlib deflate engine (classes A-H, zlib 1.0.1-1.4).
    const engine = b.addModule("zlib-replicant", .{
        .root_source_file = b.path("src/deflate.zig"),
        .target = target,
        .optimize = optimize,
    });

    // Differential harness: compress stdin -> stdout exactly like the
    // historical zlib-<version> wrapper binaries. This is the executable
    // the differential suites (scripts/) drive; consumers of the package
    // can fetch it via `dependency.artifact("zcompress")`.
    const zcompress = b.addExecutable(.{
        .name = "zcompress",
        .root_module = b.createModule(.{
            .root_source_file = b.path("tools/zcompress.zig"),
            .target = target,
            .optimize = optimize,
        }),
    });
    zcompress.root_module.addImport("zlib-replicant", engine);
    b.installArtifact(zcompress);

    // Oracle tool: the four original C cores (classes A-D) statically
    // linked with per-generation symbol prefixes, wrapped by
    // legacy/legacy.zig + legacy/bridge.c. Independent in-repo oracle for
    // the native classes A-D of the engine.
    const legacy_mod = b.createModule(.{
        .root_source_file = b.path("legacy/legacy.zig"),
        .target = target,
        .optimize = optimize,
    });
    addLegacySources(b, legacy_mod);
    const zlegacy = b.addExecutable(.{
        .name = "zlegacy",
        .root_module = b.createModule(.{
            .root_source_file = b.path("tools/zlegacy.zig"),
            .target = target,
            .optimize = optimize,
        }),
    });
    zlegacy.root_module.addImport("legacy", legacy_mod);
    b.installArtifact(zlegacy);

    // Golden-vector and equivalence tests of the engine itself.
    const engine_tests = b.addTest(.{
        .root_module = b.createModule(.{
            .root_source_file = b.path("src/deflate.zig"),
            .target = target,
            .optimize = optimize,
        }),
    });
    const run_engine_tests = b.addRunArtifact(engine_tests);

    // The C-core oracle adapters must keep working too (they exercise the
    // exact build recipe the differential suites rely on).
    const legacy_tests = b.addTest(.{ .root_module = legacy_mod });
    const run_legacy_tests = b.addRunArtifact(legacy_tests);

    const test_step = b.step("test", "Run the zlib-replicant engine tests");
    test_step.dependOn(&run_engine_tests.step);
    test_step.dependOn(&run_legacy_tests.step);
}

/// Compile the four historical zlib generations (classes A-D) into the
/// `zlegacy` oracle tool and the legacy test binary ONLY. The engine
/// itself runs every class natively; these C cores are retained as
/// independent differential oracles. Exported and cross-TU names are
/// prefixed per generation so the original 1996-2004 deflate
/// implementations never collide at link time.
fn addLegacySources(b: *std.Build, module: *std.Build.Module) void {
    module.link_libc = true;
    const symbols = [_][]const u8{
        "adler32", "deflate", "deflateInit_", "deflateInit2_", "deflateEnd",
        "deflateReset", "deflateParams", "deflateSetDictionary", "deflateCopy",
        "deflateBound", "deflatePrime", "_tr_init", "_tr_stored_block",
        "_tr_flush_block", "_tr_align", "_tr_tally", "zlibVersion",
        "zlibCompileFlags", "zError", "zcalloc", "zcfree", "z_errmsg",
        "deflate_copyright", "_dist_code", "_length_code",
        "compress", "compress2", "compressBound", "crc32", "get_crc_table", "crc32_combine",
    };
    for ([_][]const u8{ "a", "b", "c", "d" }) |class| {
        var flags: [symbols.len + 3][]const u8 = undefined;
        // The include path must be absolute. Raw -I flags are handed to
        // clang verbatim, and clang resolves a relative include path
        // against the cwd of the compiler process, which is the directory
        // the *consumer* invoked `zig build` from — not this package's
        // root. That works only when building this package standalone
        // from its own directory (cwd == package root), and breaks for
        // every fetched copy living in a package cache. On top of that, a
        // relative -I that resolves nowhere makes bridge.c fall back to
        // any system zlib.h (e.g. /usr/include/zlib.h on a dev machine),
        // silently compiling the oracle against the wrong header.
        flags[0] = b.fmt("-I{s}", .{b.pathFromRoot(b.fmt("legacy/vendor/{s}", .{class}))});
        flags[1] = b.fmt("-DZF_ENTRY=zf_legacy_{s}", .{class});
        flags[2] = "-O2";
        for (symbols, 0..) |symbol, i| {
            flags[i + 3] = b.fmt("-D{s}=zf_{s}_{s}", .{ symbol, class, symbol });
        }
        module.addCSourceFiles(.{
            .files = &.{
                b.fmt("legacy/vendor/{s}/adler32.c", .{class}),
                b.fmt("legacy/vendor/{s}/compress.c", .{class}),
                b.fmt("legacy/vendor/{s}/crc32.c", .{class}),
                b.fmt("legacy/vendor/{s}/deflate.c", .{class}),
                b.fmt("legacy/vendor/{s}/trees.c", .{class}),
                b.fmt("legacy/vendor/{s}/zutil.c", .{class}),
                "legacy/bridge.c",
            },
            .flags = &flags,
        });
    }
}
