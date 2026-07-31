# PyInstaller spec for the NeuroNarrative desktop build.
#
# Build via scripts/build_desktop.sh (which also builds the frontend and, by default,
# stages the ASR model). Run directly with:
#     cd backend && pyinstaller ../packaging/neuronarrative.spec --noconfirm
#
# onedir, not onefile: onefile unpacks every native library to a temp dir on each launch,
# which is slow and trips up ctranslate2/onnxruntime dylib loading.

import sys
from pathlib import Path

from PyInstaller.utils.hooks import collect_all, collect_data_files, collect_submodules

SPEC_DIR = Path(SPECPATH).resolve()
REPO_ROOT = SPEC_DIR.parent
BACKEND = REPO_ROOT / "backend"
FRONTEND_DIST = REPO_ROOT / "frontend" / "dist"
# Staged by build_desktop.sh; absent for a --no-model build.
STAGED_MODELS = SPEC_DIR / "build" / "asr_models"

datas = []
binaries = []
hiddenimports = []

# Native/data-heavy dependencies. collect_all pulls submodules, data files and dylibs;
# missing any one of these is the usual cause of a bundle that builds but won't run.
for package in (
    "faster_whisper",
    "ctranslate2",
    "onnxruntime",
    "av",
    "soundfile",
    "tokenizers",
    "webview",  # pywebview: native window via the OS webview
):
    try:
        pkg_datas, pkg_binaries, pkg_hidden = collect_all(package)
    except Exception as exc:  # optional/platform-specific package not installed
        print(f"[spec] skipping {package}: {exc}")
        continue
    datas += pkg_datas
    binaries += pkg_binaries
    hiddenimports += pkg_hidden

# Apple silicon GPU backend; absent elsewhere, so the same tolerant loop applies.
for package in ("mlx", "mlx_whisper"):
    try:
        pkg_datas, pkg_binaries, pkg_hidden = collect_all(package)
    except Exception as exc:
        print(f"[spec] MLX backend not bundled ({package}: {exc})")
        continue
    datas += pkg_datas
    binaries += pkg_binaries
    hiddenimports += pkg_hidden

# uvicorn resolves its loop/protocol implementations by string at runtime, so static
# analysis cannot see them.
hiddenimports += collect_submodules("uvicorn")
hiddenimports += ["app.main", "app.api.routes", "encodings.idna"]

# pywebview picks its GUI backend at runtime by string.
if sys.platform == "darwin":
    hiddenimports += ["webview.platforms.cocoa", "objc", "Foundation", "AppKit", "WebKit"]
elif sys.platform == "win32":
    hiddenimports += ["webview.platforms.edgechromium", "webview.platforms.winforms"]
else:
    hiddenimports += ["webview.platforms.gtk", "webview.platforms.qt"]

# scipy.signal.resample_poly and pandas' CSV reader both load extension modules lazily.
datas += collect_data_files("scipy", includes=["**/*.pyi"])

if (FRONTEND_DIST / "index.html").exists():
    datas.append((str(FRONTEND_DIST), "frontend_dist"))
else:
    raise SystemExit(
        f"Frontend build not found at {FRONTEND_DIST}.\n"
        "Run `npm run build` in frontend/ first, or use scripts/build_desktop.sh."
    )

if STAGED_MODELS.is_dir() and any(STAGED_MODELS.glob("models--*")):
    datas.append((str(STAGED_MODELS), "asr_models"))
    print(f"[spec] bundling ASR model from {STAGED_MODELS}")
else:
    print("[spec] no staged ASR model; the app will download it on first use")

a = Analysis(
    [str(BACKEND / "app" / "desktop.py")],
    pathex=[str(BACKEND)],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    runtime_hooks=[],
    # Trim test/dev-only weight that would otherwise ride along.
    excludes=["pytest", "_pytest", "tkinter", "matplotlib", "IPython", "requests"],
    noarchive=False,
)

pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="NeuroNarrative",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,  # UPX corrupts signed dylibs on macOS
    console=True,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)

coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=False,
    upx_exclude=[],
    name="NeuroNarrative",
)

# macOS: wrap the onedir output in a double-clickable .app so no terminal is involved.
if sys.platform == "darwin":
    app = BUNDLE(
        coll,
        name="NeuroNarrative.app",
        icon=None,
        bundle_identifier="dev.neuronarrative.app",
        info_plist={
            "CFBundleName": "NeuroNarrative",
            "CFBundleDisplayName": "NeuroNarrative",
            "CFBundleShortVersionString": "0.1.0",
            "NSHighResolutionCapable": True,
            # No server sockets are exposed off-device; loopback only.
            "LSBackgroundOnly": False,
        },
    )
