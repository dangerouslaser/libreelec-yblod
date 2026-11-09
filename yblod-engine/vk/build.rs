// Compiles shaders/*.comp to SPIR-V with the system glslc (shaderc).
use std::{env, fs, path::PathBuf, process::Command};

fn main() {
    let out = PathBuf::from(env::var("OUT_DIR").unwrap());
    let glslc = env::var("GLSLC").unwrap_or_else(|_| "glslc".into());
    println!("cargo:rerun-if-env-changed=GLSLC");
    println!("cargo:rerun-if-changed=shaders");
    let mut names = Vec::new();
    for entry in fs::read_dir("shaders").unwrap() {
        let path = entry.unwrap().path();
        if path.extension().and_then(|e| e.to_str()) != Some("comp") {
            continue;
        }
        let stem = path.file_stem().unwrap().to_str().unwrap().to_owned();
        let spv = out.join(format!("{stem}.spv"));
        let status = Command::new(&glslc)
            .args(["--target-env=vulkan1.3", "-O", "-Werror", "-Ishaders/common"])
            .arg(&path)
            .arg("-o")
            .arg(&spv)
            .status()
            .expect("run glslc (shaderc)");
        assert!(status.success(), "glslc failed on {}", path.display());
        names.push(stem);
    }
    names.sort();
    let mut table = String::from("pub static SHADERS: &[(&str, &[u8])] = &[\n");
    for n in &names {
        table.push_str(&format!("    (\"{n}\", include_bytes!(concat!(env!(\"OUT_DIR\"), \"/{n}.spv\"))),\n"));
    }
    table.push_str("];\n");
    fs::write(out.join("shaders.rs"), table).unwrap();
    // yblod's host code (tables, metadata, packets) and yblod/plan.c, from
    // the same patched yblod-engine tree yblod-engine's PKGBUILD builds.
    let yblod = PathBuf::from(env::var("YBLOD_ENGINE_SRC").expect("YBLOD_ENGINE_SRC: yblod-engine/src, patched"));
    println!("cargo:rerun-if-changed={}", yblod.display());
    println!("cargo:rerun-if-env-changed=YBLOD_ENGINE_SRC");
    println!("cargo:rerun-if-changed=yblod");
    println!("cargo:rerun-if-changed=include");
    let mut c = cc::Build::new();
    c.std("gnu11")
        .flag("-ffp-contract=off")
        .define("DV_FFMPEG_RAW_EXTENSIONS", None)
        .define("DV_PREPARED_CHROMA", None)
        .define("DV_ENCODE_STEPS", "256")
        .define("DV_COLOUR_LUT", None)
        .include(&yblod)
        .include("include")
        .file("yblod/plan.c")
        .file("yblod/cb1_overlay.c")
        .file("yblod/dm_cm4.c")
        .warnings(false);
    for f in [
        "dv_ffmpeg_metadata.c",
        "dv_cm4.c",
        "single_reshape.c",
        "single_reshape_ffmpeg.c",
        "mmr_prepare.c",
        "pixel_luma.c",
        "pixel_chroma_final.c",
        "pixel_spatial.c",
        "source_geometry.c",
        "source_overlay.c",
        "pixel_colour.c",
        "colour_lut.c",
    ] {
        c.file(yblod.join(f));
    }
    if let Ok(inc) = env::var("FFMPEG_INCLUDE") {
        c.include(inc);
    }
    c.compile("yblod_host");
    // The output colour mapping (include/dvvk_map.h): yblod/dv_map.c and the
    // part of libplacebo it uses (yblod/placebo: CB1's patched libplacebo
    // e2972fdd, colour spaces, tone and gamut mapping), every symbol hidden
    // (mpv loads its own libplacebo into the same process).
    println!("cargo:rerun-if-changed=yblod/placebo");
    let mut m = cc::Build::new();
    m.std("gnu11")
        .flag("-fvisibility=hidden")
        .include("yblod/placebo")
        .include("yblod/placebo/include")
        .include("include")
        .file("yblod/dv_map.c")
        .file("yblod/placebo/common.c")
        .file("yblod/placebo/colorspace.c")
        .file("yblod/placebo/tone_mapping.c")
        .file("yblod/placebo/gamut_mapping.c")
        .warnings(false);
    // HDR10+ (YBLOD 0.4.0): CroqueMr's CB1 HDR10+ host code, ported into
    // yblod-engine/src (pinned commit in each file), and its glue; its
    // creative resolver uses the same libplacebo subset.
    m.include(&yblod);
    for f in [
        "cb1_hdr10plus.c",
        "cb1_hdr10plus_curve.c",
        "cb1_hdr10plus_analysis.c",
        "cb1_dv_hdr10plus.c",
        "cb1_hdr10plus_dovi.c",
        "dvbridge_creative.c",
        "dvbridge_policy.c",
        "yblod_hdr10plus.c",
    ] {
        m.file(yblod.join(f));
        println!("cargo:rerun-if-changed={}", yblod.join(f).display());
    }
    if let Ok(inc) = env::var("FFMPEG_INCLUDE") {
        m.include(inc);
    }
    m.compile("dvvk_map");
    // The HDR10+ C tests `cargo test` runs (src/hdr10plus.rs): CB1's, ported
    // unchanged (yblod/tests/cb1), and YBLOD's. Nothing in the library
    // references them, so the shared library doesn't link them in.
    println!("cargo:rerun-if-changed=yblod/tests");
    let mut t = cc::Build::new();
    t.std("gnu11")
        .include("yblod/tests") // its assert.h first
        .include(&yblod)
        .include("yblod/placebo")
        .include("yblod/placebo/include")
        .include("include")
        .warnings(false);
    for f in ["shims.c", "run_transport.c", "run_curve.c", "run_dv_hdr10plus.c", "run_dovi.c", "describe.c", "yblod.c"] {
        t.file(format!("yblod/tests/{f}"));
    }
    if let Ok(inc) = env::var("FFMPEG_INCLUDE") {
        t.include(inc);
    }
    t.compile("yblod_tests");
    // The C ABI's soname: DVVK_LIBRARY in include/dv_engine_vk.h, the one
    // place it is written (mpv-yblod dlopens it by that macro).
    let header = fs::read_to_string("include/dv_engine_vk.h").unwrap();
    let soname = header
        .lines()
        .find_map(|l| l.strip_prefix("#define DVVK_LIBRARY "))
        .map(|v| v.trim().trim_matches('"').to_owned())
        .expect("DVVK_LIBRARY in include/dv_engine_vk.h");
    println!("cargo:rustc-env=DVVK_LIBRARY={soname}");
    println!("cargo:rustc-cdylib-link-arg=-Wl,-soname,{soname}");
    // libva for surface export (interop/va.rs); libgbm only for the test tools.
    println!("cargo:rustc-link-lib=va");
    println!("cargo:rustc-link-lib=va-drm");
}
