# 端到端验证 npm 安装壳（不碰真实 ~/.uiu，用 UIU_HOME 隔离）
#
#   powershell -ExecutionPolicy Bypass -File scripts/verify_npm_install.ps1
#
# 验证链：系统 Python 探测 → 建 venv（含失败退化）→ pip install uiu==<npm 版本> → 写 marker → 启动器
$ErrorActionPreference = "Stop"
$repo = Split-Path -Parent $PSScriptRoot
$home2 = Join-Path $repo "npm_e2e_home"

$env:UIU_HOME = $home2
if (-not $env:UIU_PIP_INDEX) { $env:UIU_PIP_INDEX = "https://pypi.tuna.tsinghua.edu.cn/simple" }
Remove-Item -Recurse -Force $home2 -ErrorAction SilentlyContinue

Write-Host "=== node npm/bin/install.js (UIU_HOME=$home2) ==="
node (Join-Path $repo "npm/bin/install.js")
if ($LASTEXITCODE -ne 0) { Write-Error "install failed"; exit 1 }

Write-Host "=== node npm/bin/uiu.js version ==="
$out = node (Join-Path $repo "npm/bin/uiu.js") version
Write-Host $out
if ($LASTEXITCODE -ne 0) { Write-Error "launcher failed"; exit 1 }
if ($out -notmatch "^uiu ") { Write-Error "unexpected version output: $out"; exit 1 }

$marker = Join-Path $home2 "installed.json"
if (-not (Test-Path $marker)) { Write-Error "marker missing: $marker"; exit 1 }
Write-Host "=== ok ==="
Get-Content $marker
