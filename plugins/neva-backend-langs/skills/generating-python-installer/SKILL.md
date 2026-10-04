---
name: "generating-python-installer"
description: "Use when a Python desktop app must ship as a small, fast-starting Windows installer: Nuitka folder-mode compilation, dist slimming, DLL footprint analysis, and Inno Setup packaging. Not for basic script-to-exe conversion."
---

<!-- Adapted from affaan-m/ECC (MIT), commit d3b8a3e. Merged for Neva. -->

# Generating Python Installer (Production-Grade)

You are a **production-grade Python deployment expert**. Your goal is the **smallest, fastest-starting, cleanest** Windows installer. The core approach is **"Nuitka folder mode (dist) plus Inno Setup packaging"**, no single-file builds, no stray console window.

## When to Activate

Activate when the user explicitly asks for **advanced** Python packaging or size/startup optimization on Windows:

- Nuitka extreme / production-grade compilation, smallest-size or fastest-startup builds
- `dist` folder slimming, DLL footprint analysis, 32-bit vs 64-bit size tradeoffs
- Inno Setup packaging with full metadata and a clean, residue-free uninstall

This skill targets advanced size/startup optimization, not basic one-file "script to exe" conversion.

## How It Works

1. **Confirm build parameters**, app name, version, publisher, exe name, source/output dirs, icon. Never auto-fill; ask the user.
2. **Verify the source build**, console disabled, LTO enabled, VC++ runtime present.
3. **Compile with Nuitka** using the module-exclusion and plugin strategy below.
4. **Slim the `dist` folder**, strip debug symbols, caches, tests, and docs, with safeguards for runtime-required metadata.
5. **Analyze DLLs** to find and trim the largest dependencies.
6. **Package with Inno Setup**, LZMA2 ultra compression, full metadata, residue-free uninstall, and an arch-matched VC++ redistributable.

## Examples

- "Use Nuitka to turn this PySide2 project into the smallest possible installer" -> run the full workflow: recommend 32-bit, exclude WebEngine/3D/Charts, slim `dist`, package with Inno Setup.
- "My exe is 400 MB, how do I cut it in half" -> analyze DLLs, switch to `opencv-python-headless`, drop `opengl32sw`, apply `dist` slimming.
- "It will not open on a clean system after install" -> make sure the arch-matched VC++ redistributable is bundled in the Inno Setup script.

---

## Core Philosophy

Stick to the "Nuitka folder mode (dist) plus Inno Setup packaging" approach. No single-file builds, no stray console window.

---

## Real-World Reference Case (production PySide2 desktop app, 323 MB, includes OpenCV / Playwright)

### Project Overview
- **Total size**: 323 MB
- **Packaging tool**: PyInstaller 4.7 (32-bit)
- **Main dependencies**: PySide2 (22.52 MB), OpenCV (62.38 MB), Playwright (76.74 MB)
- **Python version**: Python 3.8 (32-bit)
- **DLL count**: 71, totaling 93.23 MB

### Key Optimization Strategies
1. PASS: **Use 32-bit Python** -> reduces size by 20-30%
2. PASS: **Compress the standard library into base_library.zip** -> 0.74 MB
3. PASS: **Trim module exclusions** -> no pytest/unittest/setuptools
4. PASS: **Trim Qt plugins** -> keep only what is needed

### Size Breakdown

| Component | Size | Share | Optimization suggestion |
|------|------|------|---------|
| playwright | 76.74 MB | 23.8% | Remove if not essential |
| OpenCV | 62.38 MB | 19.3% | Use opencv-python-headless |
| PySide2 | 22.52 MB | 7.0% | Exclude WebEngine/3D/Charts |
| Other dependencies | 161.36 MB | 49.9% | - |

### Expected Results by Project Type

| Project type | Raw Nuitka | Optimized | Reference project result |
|---------|------------|--------|----------------|
| Tkinter + standard library | 150-250 MB | **80-120 MB** | - |
| PyQt/PySide | 200-400 MB | **120-250 MB** | 323 MB (includes OpenCV etc.) |
| Includes numpy/pandas | 300-600 MB | **180-350 MB** | - |

---

## Core Workflow - WARNING: follow strictly

When the user requests packaging, follow these steps:

**Step 1: Mandatory parameter confirmation (FAIL: never use default values)**

> **WARNING: Important rule: every parameter below must be confirmed with the user one by one. Never auto-fill or use a default value.**

You must ask the user for, and confirm, the following information (*wait for an explicit reply before continuing*):

| Parameter | Description | Example |
|------|------|------|
| **App Name** | Display name of the software | `MyApp` |
| **Version** | Semantic version number | `1.0.0` |
| **Publisher / Company** | Publisher shown in Control Panel | `YourCompany` |
| **Exe Name** | Main executable filename | `MyApp.exe` |
| **Source Dir** | Absolute path to the Nuitka dist folder | `D:\project\dist` |
| **Output Dir** | Where the installer is generated | `D:\project\output` |
| **Icon Path** | Absolute path to the .ico file (optional but recommended) | `D:\project\icon.ico` |
| **URL** | Optional, used for the Control Panel link | `https://example.com` |

**Confirmation prompt template:**
> "Please provide the following build parameters, I need you to confirm each one:
> 1. App name:
> 2. Version number:
> 3. Publisher / company name:
> 4. Main executable filename (e.g. xxx.exe):
> 5. Source path (Nuitka dist folder):
> 6. Output path (where to save the installer):
> 7. Icon path (.ico file, can be left blank):
> 8. Website URL (can be left blank):
>
> Fill them in one by one, or reply "skip" to use blank values."

**Step 2: Source build quality and compile check (critical)**

Before generating any code, you must send the user this **critical confirmation** (Inno Setup is only a packaging tool, it cannot change the program's own runtime behavior):

> "WARNING: **Compile parameter check**:
> 1. **No console window**: confirm your dist folder was built with `nuitka --windows-console-mode=disable`. (Otherwise a black console window still appears after install.)
> 2. **Performance**: confirm whether `--lto=yes` was used. (Otherwise startup speed may be poor.)
> 3. **Runtime**: confirm the dist folder already includes the necessary VC++ runtime, so it also runs on a clean system.
>
> **Reply "confirmed" once the source build is ready, otherwise recompile first.**"

**Step 3: Generate the code**
Once the user confirms, output code that includes **full metadata** and the **uninstall icon fix**.

---

## Nuitka Extreme Optimization Compilation (based on the reference project's experience)

### 1. 32-bit vs 64-bit Selection Strategy

**Why the reference project uses 32-bit Python:**

| Component | 64-bit size | 32-bit size | Savings |
|------|---------|---------|------|
| python3x.dll | ~4.5 MB | ~3.8 MB | 15% |
| Qt5Core.dll | ~8 MB | ~5 MB | 37% |
| numpy | ~30 MB | ~20 MB | 33% |
| **Overall** | baseline | **-20 to 30%** | - |

**Recommended conditions for using 32-bit:**
- PASS: Memory usage under 2GB
- PASS: Does not process very large files (< 2GB)
- PASS: Target users are on ordinary office PCs

**How to compile 32-bit:**
```bash
# 1. Install 32-bit Python (can coexist with 64-bit)
# Download: https://www.python.org/downloads/windows/

# 2. Install dependencies with 32-bit Python
py -3.12-32 -m pip install -r requirements.txt

# 3. Compile with 32-bit Python
py -3.12-32 -m nuitka --standalone ...your arguments
```

### 2. Module Exclusion List (validated by the reference project)

**Safe exclusion list** (not needed at runtime):
```
unittest,test,pytest,_pytest,doctest,pdb,pdbpp,
setuptools,pip,distutils,pkg_resources,
email.mime,http.server,xmlrpc,pydoc
```

**Expected effect**: saves **30-50 MB**

### 3. GUI-Framework-Specific Optimization

#### Tkinter Extreme Optimization (recommended, lightest)
```bash
nuitka --standalone --windows-console-mode=disable ^
    --lto=yes ^
    --jobs=8 ^
    --enable-plugin=tk-inter ^
    --enable-plugin=anti-bloat ^
    --noinclude-pytest-mode=nofollow ^
    --noinclude-setuptools-mode=nofollow ^
    --nofollow-import-to=unittest,test,pytest,_pytest,doctest,pdb,pdbpp ^
    --nofollow-import-to=setuptools,pip,distutils,pkg_resources ^
    --nofollow-import-to=email.mime,http.server,xmlrpc,pydoc ^
    --python-flag=no_docstrings ^
    --output-dir=dist ^
    --windows-icon-from-ico=icon.ico ^
    --remove-output ^
    main.py
```

**Expected size**: 80-120 MB (after optimization)

#### PyQt5 / PySide2 Optimization
```bash
nuitka --standalone --windows-console-mode=disable ^
    --lto=yes ^
    --jobs=8 ^
    --enable-plugin=pyqt5 ^
    --enable-plugin=anti-bloat ^
    --noinclude-pytest-mode=nofollow ^
    --noinclude-setuptools-mode=nofollow ^
    --nofollow-import-to=unittest,test,pytest,_pytest,doctest,pdb ^
    --nofollow-import-to=setuptools,pip,distutils,pkg_resources ^
    --nofollow-import-to=PyQt5.QtWebEngine,PyQt5.QtWebEngineWidgets ^
    --nofollow-import-to=PyQt5.Qt3D,PyQt5.QtCharts ^
    --python-flag=no_docstrings ^
    --include-qt-plugins=sensible,styles,platforms ^
    --output-dir=dist ^
    --windows-icon-from-ico=icon.ico ^
    --remove-output ^
    main.py
```

**Expected size**: 120-250 MB (after optimization)

### 4. One-Click Build Script Template

**Save as `build_optimized.bat` (project root)**:

```batch
@echo off
chcp 65001 >nul
setlocal enabledelayedexpansion

echo ========================================
echo Nuitka extreme optimization build (reference project method)
echo ========================================

REM === Configuration (edit to your actual values) ===
set APP_NAME=YourAppName
set MAIN_FILE=main.py
set ICON_FILE=icon.ico

REM === Auto-detect CPU core count ===
REM Uses Windows' own environment variable (wmic was removed in Win11 22H2+; if detection fails, --jobs=0 falls back to single-threaded)
set CPU_CORES=%NUMBER_OF_PROCESSORS%
if not defined CPU_CORES set CPU_CORES=4
set /a BUILD_JOBS=%CPU_CORES%

REM === Reference project's module exclusion list ===
set EXCLUDE_MODULES=unittest,test,pytest,_pytest,doctest,pdb,pdbpp
set EXCLUDE_MODULES=%EXCLUDE_MODULES%,setuptools,pip,distutils,pkg_resources
set EXCLUDE_MODULES=%EXCLUDE_MODULES%,email.mime,http.server,xmlrpc,pydoc

echo.
echo [1/4] Cleaning previous build...
if exist dist rd /s /q dist
if exist build rd /s /q build

echo.
echo [2/4] Compiling with Nuitka (applying reference project optimization strategy)...
echo - CPU cores: %CPU_CORES% (using %BUILD_JOBS% threads)
echo - Excluded modules: %EXCLUDE_MODULES%
echo.

nuitka --standalone ^
    --windows-console-mode=disable ^
    --lto=yes ^
    --jobs=%BUILD_JOBS% ^
    --enable-plugin=anti-bloat ^
    --enable-plugin=tk-inter ^
    --noinclude-pytest-mode=nofollow ^
    --noinclude-setuptools-mode=nofollow ^
    --nofollow-import-to=%EXCLUDE_MODULES% ^
    --python-flag=no_docstrings ^
    --output-dir=dist ^
    --windows-icon-from-ico=%ICON_FILE% ^
    --remove-output ^
    %MAIN_FILE%

if %errorlevel% neq 0 (
    echo.
    echo [Error] Build failed!
    pause
    exit /b 1
)

echo.
echo [3/4] Measuring build output...
for /f %%a in ('powershell -NoProfile -Command "(Get-ChildItem -LiteralPath 'dist\%APP_NAME%.dist' -Recurse -File | Measure-Object -Property Length -Sum).Sum"') do set TOTAL_SIZE=%%a
set TOTAL_SIZE=%TOTAL_SIZE:,=%
set /a SIZE_MB=%TOTAL_SIZE% / 1048576
echo - Build size: %SIZE_MB% MB

echo.
echo [4/4] Running slimming cleanup (reference project strategy)...
powershell -ExecutionPolicy Bypass -File slim_dist.ps1 -DistPath "dist\%APP_NAME%.dist"

echo.
echo ========================================
echo Build complete!
echo ========================================
pause
```

### 5. Dist Slimming Script (reference-project-level cleanup)

**Save as `slim_dist.ps1` (same directory as build_optimized.bat)**:

```powershell
param(
    [string]$DistPath
)

$ErrorActionPreference = "Continue"  # Do not swallow errors silently: deletion failures will show up, avoiding false success

Write-Host "`n========================================" -ForegroundColor Cyan
Write-Host "dist folder slimming cleanup (reference project strategy)" -ForegroundColor Cyan
Write-Host "========================================" -ForegroundColor Cyan

if (-not (Test-Path $DistPath)) {
    Write-Host "[Error] Directory not found: $DistPath" -ForegroundColor Red
    exit 1
}

# Measure initial size
$InitialSize = (Get-ChildItem -Path $DistPath -Recurse -File | Measure-Object -Property Length -Sum).Sum / 1MB
Write-Host "`nInitial size: $([math]::Round($InitialSize, 2)) MB" -ForegroundColor Yellow

# Reference project trait: no .pdb, .pyi, __pycache__, test directories, etc.
Write-Host "`n[Applying reference project cleanup strategy...]" -ForegroundColor Green

# 1. Remove debug symbols
Write-Host "`n[1/7] Removing .pdb debug symbols..." -ForegroundColor Green
$pdbFiles = Get-ChildItem -Path $DistPath -Recurse -Include *.pdb -File
$pdbSize = ($pdbFiles | Measure-Object -Property Length -Sum).Sum / 1MB
if ($pdbFiles.Count -gt 0) {
    $pdbFiles | Remove-Item -Force
    Write-Host "  Removed $($pdbFiles.Count) files, saved $([math]::Round($pdbSize, 2)) MB"
} else {
    Write-Host "  No .pdb files found (already clean)" -ForegroundColor Gray
}

# 2. Remove type stubs
Write-Host "`n[2/7] Removing .pyi type stubs..." -ForegroundColor Green
$pyiFiles = Get-ChildItem -Path $DistPath -Recurse -Include *.pyi -File
$pyiSize = ($pyiFiles | Measure-Object -Property Length -Sum).Sum / 1MB
if ($pyiFiles.Count -gt 0) {
    $pyiFiles | Remove-Item -Force
    Write-Host "  Removed $($pyiFiles.Count) files, saved $([math]::Round($pyiSize, 2)) MB"
} else {
    Write-Host "  No .pyi files found (already clean)" -ForegroundColor Gray
}

# 3. Remove __pycache__
Write-Host "`n[3/7] Removing __pycache__ caches..." -ForegroundColor Green
$pycacheDirs = Get-ChildItem -Path $DistPath -Recurse -Directory -Filter "__pycache__"
$pycacheSize = 0
foreach ($dir in $pycacheDirs) {
    $size = (Get-ChildItem -Path $dir.FullName -Recurse -File | Measure-Object -Property Length -Sum).Sum
    $pycacheSize += $size
    Remove-Item -Path $dir.FullName -Recurse -Force
}
if ($pycacheDirs.Count -gt 0) {
    Write-Host "  Removed $($pycacheDirs.Count) directories, saved $([math]::Round($pycacheSize / 1MB, 2)) MB"
} else {
    Write-Host "  No __pycache__ found (already clean)" -ForegroundColor Gray
}

# 4. Remove test directories
Write-Host "`n[4/7] Removing test/tests directories..." -ForegroundColor Green
$testDirs = Get-ChildItem -Path $DistPath -Recurse -Directory | Where-Object { $_.Name -match '^tests?$' }
$testSize = 0
foreach ($dir in $testDirs) {
    $size = (Get-ChildItem -Path $dir.FullName -Recurse -File | Measure-Object -Property Length -Sum).Sum
    $testSize += $size
    Remove-Item -Path $dir.FullName -Recurse -Force
}
if ($testDirs.Count -gt 0) {
    Write-Host "  Removed $($testDirs.Count) directories, saved $([math]::Round($testSize / 1MB, 2)) MB"
} else {
    Write-Host "  No test directories found (already clean)" -ForegroundColor Gray
}

# 5. Remove docs and examples
Write-Host "`n[5/7] Removing docs/examples directories..." -ForegroundColor Green
$docDirs = Get-ChildItem -Path $DistPath -Recurse -Directory | Where-Object { $_.Name -match '^(docs|examples|samples|demo)$' }
$docSize = 0
foreach ($dir in $docDirs) {
    $size = (Get-ChildItem -Path $dir.FullName -Recurse -File | Measure-Object -Property Length -Sum).Sum
    $docSize += $size
    Remove-Item -Path $dir.FullName -Recurse -Force
}
if ($docDirs.Count -gt 0) {
    Write-Host "  Removed $($docDirs.Count) directories, saved $([math]::Round($docSize / 1MB, 2)) MB"
} else {
    Write-Host "  No doc directories found (already clean)" -ForegroundColor Gray
}

# 6. Remove .pyc files
Write-Host "`n[6/7] Removing .pyc bytecode..." -ForegroundColor Green
$pycFiles = Get-ChildItem -Path $DistPath -Recurse -Include *.pyc -File
$pycSize = ($pycFiles | Measure-Object -Property Length -Sum).Sum / 1MB
if ($pycFiles.Count -gt 0) {
    $pycFiles | Remove-Item -Force
    Write-Host "  Removed $($pycFiles.Count) files, saved $([math]::Round($pycSize, 2)) MB"
} else {
    Write-Host "  No .pyc files found (already clean)" -ForegroundColor Gray
}

# 7. Trim .dist-info metadata
Write-Host "`n[7/7] Trimming .dist-info metadata..." -ForegroundColor Green
$distInfoDirs = Get-ChildItem -Path $DistPath -Recurse -Directory -Filter "*.dist-info"
$removedCount = 0
$removedSize = 0
foreach ($infoDir in $distInfoDirs) {
    # Only remove install-time bookkeeping files; keep METADATA and entry_points.txt (read at runtime by importlib.metadata, removing them breaks plugin discovery)
    $filesToRemove = @("RECORD", "INSTALLER", "direct_url.json")
    foreach ($fileName in $filesToRemove) {
        $file = Join-Path $infoDir.FullName $fileName
        if (Test-Path $file) {
            $size = (Get-Item $file).Length
            $removedSize += $size
            Remove-Item $file -Force
            $removedCount++
        }
    }
}
if ($removedCount -gt 0) {
    Write-Host "  Removed $removedCount metadata files, saved $([math]::Round($removedSize / 1MB, 2)) MB"
} else {
    Write-Host "  Nothing to clean (already clean)" -ForegroundColor Gray
}

# Measure final size
$FinalSize = (Get-ChildItem -Path $DistPath -Recurse -File | Measure-Object -Property Length -Sum).Sum / 1MB
$SavedSize = $InitialSize - $FinalSize
$SavedPercent = if ($InitialSize -gt 0) { ($SavedSize / $InitialSize) * 100 } else { 0 }

Write-Host "`n========================================" -ForegroundColor Cyan
Write-Host "Cleanup complete!" -ForegroundColor Green
Write-Host "========================================" -ForegroundColor Cyan
Write-Host "Initial size: $([math]::Round($InitialSize, 2)) MB" -ForegroundColor Yellow
Write-Host "Final size: $([math]::Round($FinalSize, 2)) MB" -ForegroundColor Green
Write-Host "Space saved: $([math]::Round($SavedSize, 2)) MB ($([math]::Round($SavedPercent, 1))%)" -ForegroundColor Cyan
Write-Host "========================================`n" -ForegroundColor Cyan

# Compare to reference project
Write-Host "[Reference comparison]" -ForegroundColor Yellow
Write-Host "Reference project total size: 323 MB (includes PyQt, OpenCV, Playwright and other heavyweight libraries)" -ForegroundColor Gray
Write-Host "If your project is pure Tkinter plus standard library, target 80-150 MB" -ForegroundColor Gray
```

**Expected effect**: saves **15-30%** of size

### 6. DLL Dependency Analysis Tool

**Save as `analyze_dlls.py` (used to find the biggest size contributors)**:

```python
"""
DLL dependency analysis tool
Following the reference project's DLL management strategy, helps identify the biggest contributors to size and gives optimization suggestions
"""
import sys
from pathlib import Path

def analyze_dlls(dist_path: str):
    """Analyze DLL dependencies inside a dist directory"""
    dist_dir = Path(dist_path)

    if not dist_dir.exists():
        print(f"[Error] Directory not found: {dist_path}")
        return

    print("=" * 70)
    print("DLL dependency analysis (reference project strategy)")
    print("=" * 70)

    # Collect all DLLs
    dll_files = list(dist_dir.rglob("*.dll"))

    if not dll_files:
        print("\nNo DLL files found")
        return

    # Sort by size
    dll_data = [(dll, dll.stat().st_size) for dll in dll_files]
    dll_data.sort(key=lambda x: x[1], reverse=True)

    total_size = sum(size for _, size in dll_data)

    print(f"\nTotal DLL count: {len(dll_files)}")
    print(f"Total DLL size: {total_size / 1024 / 1024:.2f} MB\n")

    # Reference project comparison
    print("[Reference comparison] Reference project's DLL footprint:")
    print("  - Count: 71")
    print("  - Total size: 93.23 MB")
    print("  - Largest: libopenblas (26.85 MB), opengl32sw (15.25 MB)\n")

    # Analyze DLLs larger than 3 MB
    large_dlls = [(dll, size) for dll, size in dll_data if size > 3 * 1024 * 1024]

    if large_dlls:
        print("=" * 70)
        print("WARNING: DLLs larger than 3 MB (worth closer attention)")
        print("=" * 70)

        for dll, size in large_dlls:
            size_mb = size / 1024 / 1024
            relative_path = dll.relative_to(dist_dir)
            name_lower = dll.name.lower()

            print(f"\n{size_mb:8.2f} MB  {dll.name}")
            print(f"           Location: {relative_path.parent}")

            # Optimization suggestions
            suggestions = get_optimization_suggestion(name_lower)
            if suggestions:
                for suggestion in suggestions:
                    print(f"            {suggestion}")

    # Check for redundant DLLs
    print("\n" + "=" * 70)
    print("Redundancy check")
    print("=" * 70)

    # Check for debug builds
    debug_dlls = [dll for dll, _ in dll_data if dll.stem.endswith('d')]
    if debug_dlls:
        print(f"\nWARNING: Found {len(debug_dlls)} debug-build DLLs (safe to remove):")
        for dll in debug_dlls:
            print(f"  - {dll.name}")
    else:
        print("\nPASS: No debug-build DLLs found (already clean)")

    # VC++ Runtime
    vc_runtimes = [dll for dll, _ in dll_data if 'vcruntime' in dll.name.lower() or 'msvcp' in dll.name.lower()]
    if vc_runtimes:
        print(f"\n[VC++ Runtime libraries] Found {len(vc_runtimes)}:")
        for dll in vc_runtimes:
            size_mb = dll.stat().st_size / 1024 / 1024
            print(f"  - {dll.name} ({size_mb:.2f} MB)")
        print("   These are required; the reference project ships them too")

    # Full DLL list
    print("\n" + "=" * 70)
    print("Full DLL list (sorted by size, top 20)")
    print("=" * 70)
    print(f"\n{'Size (MB)':>10}  {'Filename':<30}  Location")
    print("-" * 70)

    for dll, size in dll_data[:20]:
        size_mb = size / 1024 / 1024
        relative_path = dll.relative_to(dist_dir)
        location = str(relative_path.parent) if relative_path.parent != Path('.') else "root"
        print(f"{size_mb:10.2f}  {dll.name:<30}  {location}")

    if len(dll_data) > 20:
        remaining_size = sum(size for _, size in dll_data[20:]) / 1024 / 1024
        print(f"... {len(dll_data) - 20} more DLLs, totaling {remaining_size:.2f} MB")


def get_optimization_suggestion(dll_name: str) -> list:
    """Return optimization suggestions based on the DLL name"""
    suggestions = []

    if "openblas" in dll_name or "mkl" in dll_name:
        suggestions.append("Math library; the reference project's libopenblas is 26.85 MB")
        suggestions.append("If you do not need high-performance computing, consider a lighter build")

    elif "opencv" in dll_name or "ffmpeg" in dll_name:
        suggestions.append("OpenCV-related; the reference project's opencv_videoio_ffmpeg is 18.48 MB")
        suggestions.append("Consider switching to opencv-python-headless")

    elif "qt5" in dll_name or "qt6" in dll_name or "pyside" in dll_name:
        suggestions.append("Qt library; the reference project's Qt5Core is 5.13 MB")
        suggestions.append("Exclude modules you do not need (WebEngine, 3D, Charts)")

    elif "opengl" in dll_name and "sw" in dll_name:
        suggestions.append("OpenGL software renderer; the reference project kept 15.25 MB of it")
        suggestions.append("Usually safe to delete (falls back to hardware rendering)")

    elif "d3dcompiler" in dll_name:
        suggestions.append("DirectX compiler; the reference project's is 3.53 MB")

    elif "mfc140" in dll_name:
        suggestions.append("MFC library; the reference project's is 4.89 MB")

    return suggestions


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python analyze_dlls.py <dist directory path>")
        print("Example: python analyze_dlls.py dist/main.dist")
        sys.exit(1)

    analyze_dlls(sys.argv[1])
```

**Usage**:
```bash
python analyze_dlls.py dist/YourAppName.dist
```

---

## Complete Optimization Workflow

### Step 1: Edit the build script configuration

Edit `build_optimized.bat` and change these 3 lines:

```batch
set APP_NAME=YourAppName      REM change to the actual name
set MAIN_FILE=main.py        REM your main script file
set ICON_FILE=icon.ico       REM your icon file
```

### Step 2: One-click build and slim

Run from the project root:

```bash
build_optimized.bat
```

### Step 3: Analyze DLL dependencies

```bash
python analyze_dlls.py dist/YourAppName.dist
```

### Step 4: Optimize based on the analysis

**If you use OpenCV** -> switch to the headless build
```bash
pip uninstall opencv-python
pip install opencv-python-headless
```

**If you use Qt** -> exclude modules you do not need
```batch
# Add to the compile command
--nofollow-import-to=PyQt5.QtWebEngine,PyQt5.Qt3D,PyQt5.QtCharts
```

**Remove the software renderer** (if not needed)
```powershell
# Run inside the dist directory
Remove-Item "opengl32sw.dll" -Force
```

---

## VC++ Runtime Handling

### Option 1: Static linking (recommended)
```bash
nuitka --static-libpython=yes ...
```

### Option 2: Bundle a runtime installer (recommended for production releases)
Add to the Inno Setup script:

```iss
; WARNING: The VC++ runtime architecture must match the Python/Nuitka build architecture.
; This skill recommends 32-bit Python, so it bundles vc_redist.x86.exe by default;
; if you compile with 64-bit Python, change both lines below to vc_redist.x64.exe.
[Files]
Source: "{#MySourceDir}\..\vc_redist.x86.exe"; DestDir: "{tmp}"; Flags: deleteafterinstall

[Run]
Filename: "{tmp}\vc_redist.x86.exe"; Parameters: "/quiet /norestart"; StatusMsg: "Installing runtime library..."; Flags: waituntilterminated
```

> Download: [Microsoft Visual C++ Redistributable](https://learn.microsoft.com/en-us/cpp/windows/latest-supported-vc-redist)

---

## Inno Setup Script Template (Production Final Version)

```iss
; =====================================================================
;  WARNING: Production-grade Python installer script (Inno Setup 6.x)
;  Features: LZMA2 ultra compression | full metadata | residue-free uninstall
;  Reference: the reference project (323 MB, LZMA2 compression)
; =====================================================================

; --- 1. Parameter definitions ---
#define MyAppName        "{{APP_NAME}}"
#define MyAppVersion     "{{APP_VERSION}}"
#define MyAppPublisher   "{{PUBLISHER}}"
#define MyAppURL         "{{APP_URL}}"
#define MyAppExeName     "{{EXE_NAME}}"
#define MySourceDir      "{{SOURCE_DIR}}"
#define MyOutputDir      "{{OUTPUT_DIR}}"
;#define MyIconPath      "{{ICON_PATH}}"

[Setup]
; --- Identity ---
AppId={{GENERATE_RANDOM_GUID}}
AppName={#MyAppName}
AppVersion={#MyAppVersion}
AppPublisher={#MyAppPublisher}
AppPublisherURL={#MyAppURL}
AppSupportURL={#MyAppURL}
AppUpdatesURL={#MyAppURL}

; --- Install path and privileges ---
DefaultDirName={autopf}\{#MyAppName}
DefaultGroupName={#MyAppName}
DisableDirPage=no
DisableProgramGroupPage=no
PrivilegesRequired=admin

; --- Output settings ---
OutputDir={#MyOutputDir}
OutputBaseFilename=Setup_{#MyAppName}_v{#MyAppVersion}

; --- Visual experience ---
WizardStyle=modern
#ifdef MyIconPath
SetupIconFile={#MyIconPath}
UninstallDisplayIcon={app}\{#MyAppExeName}
#endif

; --- Core compression (reference project) ---
Compression=lzma2/ultra64
SolidCompression=yes
LZMAUseSeparateProcess=yes

; --- Architecture ---
; Note: only set this for a 64-bit Python build. This skill recommends 32-bit Python,
; so leave it commented out for a 32-bit build, matching the vc_redist.x86.exe bundled above.
; Uncomment only when compiling with 64-bit Python.
;ArchitecturesInstallIn64BitMode=x64compatible

[Languages]
Name: "english"; MessagesFile: "compiler:Default.isl"

[Files]
Source: "{#MySourceDir}\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[UninstallDelete]
Type: filesandordirs; Name: "{app}\*"

[Icons]
Name: "{autodesktop}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"; Tasks: desktopicon
Name: "{group}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"
Name: "{group}\Uninstall {#MyAppName}"; Filename: "{uninstallexe}"

[Tasks]
Name: "desktopicon"; Description: "{cm:CreateDesktopIcon}"; GroupDescription: "{cm:AdditionalIcons}"; Flags: unchecked

[Run]
Filename: "{app}\{#MyAppExeName}"; Description: "{cm:LaunchProgram,{#MyAppName}}"; Flags: nowait postinstall skipifsilent
```

---

## Placeholder Reference

| Placeholder | Description | Example value |
|--------|------|--------|
| `{{APP_NAME}}` | Display name of the app | `MyApp` |
| `{{APP_VERSION}}` | Version number | `1.0.0` |
| `{{PUBLISHER}}` | Publisher / company name | `MyCompany` |
| `{{APP_URL}}` | Website URL | `https://example.com` |
| `{{EXE_NAME}}` | Main executable filename | `MyApp.exe` |
| `{{SOURCE_DIR}}` | Path to the Nuitka dist folder | `D:\project\dist\MyApp.dist` |
| `{{OUTPUT_DIR}}` | Installer output path | `D:\project\output` |
| `{{ICON_PATH}}` | Icon file path | `D:\project\icon.ico` |
| `{{GENERATE_RANDOM_GUID}}` | **Must generate a unique GUID** | Use Inno Setup "Tools > Generate GUID" |

---

## FAQ

### Q1: Double-clicking the installed program does nothing?
1. Open CMD and run the exe manually to see the error message
2. Check whether the VC++ runtime is missing
3. Check whether the Nuitka build succeeded

### Q2: Installer size too large?
**Optimization steps**:
1. Compile with 32-bit Python (saves 20-30%)
2. Apply the reference project's module exclusion list
3. Enable the Anti-Bloat plugin
4. Run the dist folder slimming script
5. Analyze DLLs and remove unnecessary large files

### Q3: Antivirus false positive?
**Solutions**:
- Submit the binary to major antivirus vendors for allowlisting
- Purchase a code-signing certificate (Sectigo, DigiCert recommended)
- Avoid UPX compression

### Q4: Installer shows "Windows protected your PC"?
- Purchase an EV code-signing certificate (grants trust immediately)
- A standard code-signing certificate builds trust gradually as install counts accumulate

---

## Field Issue Log (updated 2026-02-07)

- **Missing python3xx.dll after install**: must use Nuitka `--standalone`; confirm the dll exists in dist; never ship the single-file build.
- **No reaction on click after install**: heavy imports can block GUI startup; defer heavy dependencies until "export starts", then import them; add logging to diagnose.
- **Nuitka + MinGW errors on non-ASCII paths**: copy the source into an ASCII-only directory before compiling; set `PYTHONIOENCODING=utf-8`.
- **Inno Setup warns that `x64` is deprecated (only matters for 64-bit builds that need 64-bit install mode)**: switch to `ArchitecturesInstallIn64BitMode=x64compatible`; not needed for a 32-bit build.
- **`--disable-console` is deprecated**: use `--windows-console-mode=disable` instead.
- **`_nuitka_temp.exe` shows up in dist**: exclude it in `[Files]`.

---

## Expected Optimization Results

| Optimization combo | Size reduction | Startup improvement | Risk |
|----------|----------|----------|----------|
| Baseline build | baseline | baseline | none |
| + `--lto=yes` | 5-10% | 10-20% | PASS: none |
| + anti-bloat | 15-25% | - | PASS: none |
| + module exclusion | 20-35% | 5% | PASS: none |
| + dist slimming | 25-40% | - | PASS: none |
| + 32-bit build | 40-60% | - | PASS: none |
| **Full combination** | **45-65%** | **15-25%** | PASS: **no risk** |

> WARNING: **UPX compression is not recommended.** It reduces size further but is very likely to trigger antivirus false positives.

---

**Optimized from real-world reference-project experience, built to help you ship production-grade installers.**
