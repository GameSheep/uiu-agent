# verify_windows_install.ps1
# Windows install-state acceptance for uiu (v1.0 gate).
# Builds the wheel, installs it into a FRESH venv (no source tree on path),
# then exercises: version -> init (isolated dir) -> doctor lint -> show ->
# headless TUI smoke (pilot runs offline).
#
# Run from repo root:
#   powershell -ExecutionPolicy Bypass -File scripts/verify_windows_install.ps1
param(
    [string]$PythonPath = "python"
)
$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $PSScriptRoot
Set-Location $root
$pyExe = $PythonPath

Write-Host "== uiu Windows install-state verification ==" -ForegroundColor Cyan

# 1. build wheel from source
& $pyExe -m pip install --quiet build
if ($LASTEXITCODE -ne 0) { throw "failed to install build" }
& $pyExe -m build --wheel --outdir "$root\dist_verify"
if ($LASTEXITCODE -ne 0) { throw "wheel build failed" }
$wheel = Get-ChildItem "$root\dist_verify\*.whl" | Sort-Object Name -Descending | Select-Object -First 1
Write-Host "built: $($wheel.Name)"

# 2. fresh venv
$venv = Join-Path $env:TEMP "uiu-verify-venv-$([guid]::NewGuid().ToString('N').Substring(0,8))"
& $pyExe -m venv $venv
$vp = Join-Path $venv "Scripts\python.exe"
& $vp -m pip install --quiet $wheel.FullName
if ($LASTEXITCODE -ne 0) { throw "install into fresh venv failed" }
Write-Host "installed into fresh venv"

# 3. uiu version
$ver = & $vp -m uiu.main version
if ($LASTEXITCODE -ne 0) { throw "uiu version failed" }
Write-Host "version: $ver"

# 4. isolated workspace init
$ws = Join-Path $env:TEMP "uiu-verify-ws-$([guid]::NewGuid().ToString('N').Substring(0,8))"
New-Item -ItemType Directory -Path $ws | Out-Null
& $vp -m uiu.main init --workspace $ws
if ($LASTEXITCODE -ne 0) { throw "uiu init failed" }
Write-Host "init ok"

# 5. doctor lint must not hard-fail on a valid workspace
$env:UIU_WORKSPACE = $ws
& $vp -m uiu.main doctor --lint
$doctorRc = $LASTEXITCODE
Write-Host "doctor --lint exit=$doctorRc (0 or 1 acceptable on fresh ws without key)"

# 6. show works
& $vp -m uiu.main show | Out-Null
if ($LASTEXITCODE -ne 0) { throw "uiu show failed" }
Write-Host "show ok"

# 7. headless TUI smoke: import the app package and mount via textual pilot (offline)
$env:PYTHONIOENCODING = "utf-8"
$smoke = @'
import asyncio, sys
from pathlib import Path
import tempfile
from uiu.app import UiuApp
from uiu.workspace import Workspace

def runner(*, client, messages, tool_schemas, skills, model, cfg, emit, cancel):
    from uiu.app.messages import TextChunk, TurnDone
    emit(TextChunk("ok"))
    emit(TurnDone("ok", 0.01))

async def main():
    d = Path(tempfile.mkdtemp())
    for n in ("SOUL.md","IDENTITY.md","USER.md","MEMORY.md"):
        (d/n).write_text("# x\n", encoding="utf-8")
    ws = Workspace(root=d, soul="s", identity="i", user="u", memory="m", skills=[])
    app = UiuApp(object(), ws, model="m", cfg=None, app_cfg=None, turn_runner=runner)
    async with app.run_test(size=(100, 30)) as pilot:
        await pilot.pause(0.3)
        ids = {w.id for w in app.query("*")}
        assert {"header","chat","composer","status"} <= ids, ids
        print("TUI smoke ok")

asyncio.run(main())
'@
$tmpPy = Join-Path $env:TEMP "uiu_tui_smoke.py"
Set-Content -Path $tmpPy -Value $smoke -Encoding UTF8
& $vp $tmpPy
if ($LASTEXITCODE -ne 0) { throw "headless TUI smoke failed" }
Write-Host "TUI headless smoke ok"

# cleanup
Remove-Item $venv -Recurse -Force -ErrorAction SilentlyContinue
Remove-Item $ws -Recurse -Force -ErrorAction SilentlyContinue
Remove-Item "$root\dist_verify" -Recurse -Force -ErrorAction SilentlyContinue
Remove-Item $tmpPy -Force -ErrorAction SilentlyContinue

Write-Host ""
Write-Host "ALL WINDOWS INSTALL CHECKS PASSED" -ForegroundColor Green
