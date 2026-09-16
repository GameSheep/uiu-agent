#!/usr/bin/env node
/**
 * uiu npm installer — ensures an embedded Python runtime + venv + uiu package.
 *
 * Strategy (same as uv/ruff's npm distribution):
 *   1. Prefer a system Python (>=3.10) if one exists.
 *   2. Otherwise download python-build-standalone (CPython, official
 *      astral-sh builds) into ~/.uiu/runtime/<platform> — cached, reused.
 *   3. Create ~/.uiu/venv and `pip install -u uiu`.
 *
 * Env overrides:
 *   UIU_PYTHON_MIRROR  — alternate base URL for the python-build-standalone release
 *   UIU_PIP_INDEX      — alternate pip index (e.g. a China mirror)
 *   UIU_SKIP_BOOTSTRAP — skip install entirely (for packagers)
 */
"use strict";

const { execFileSync, spawnSync } = require("child_process");
const fs = require("fs");
const os = require("os");
const path = require("path");
const https = require("https");

const HOME = os.homedir();
// UIU_HOME lets tests / power users relocate the runtime (default ~/.uiu)
const UIU_HOME = process.env.UIU_HOME || path.join(HOME, ".uiu");
const RUNTIME_DIR = path.join(UIU_HOME, "runtime");
const VENV_DIR = path.join(UIU_HOME, "venv");
const MARKER = path.join(UIU_HOME, "installed.json");

// python-build-standalone release — bump together with uiu releases when needed
const PBS_RELEASE = process.env.UIU_PYTHON_VERSION || "20260901";
const PY_VERSION = "3.10.21"; // must match a cpython asset on that release
const PY_TAG = `cpython-${PY_VERSION}+${PBS_RELEASE}`;

function platformTriple() {
  // node process.platform: win32/darwin/linux
  const arch = process.arch === "x64" ? "x86_64" : process.arch === "arm64" ? "aarch64" : process.arch;
  const osName = { win32: "pc-windows-msvc", darwin: "apple-darwin", linux: "unknown-linux-gnu" }[process.platform];
  if (!osName) throw new Error(`unsupported platform: ${process.platform}`);
  return `${arch}-${osName}`;
}

function log(msg) {
  console.log(`[uiu] ${msg}`);
}

function logErr(msg) {
  console.error(`[uiu] ${msg}`);
}

function download(url, dest) {
  return new Promise((resolve, reject) => {
    const file = fs.createWriteStream(dest);
    const req = https.get(url, { headers: { "User-Agent": "uiu-npm-installer" } }, (res) => {
      if (res.statusCode !== 200) {
        reject(new Error(`HTTP ${res.statusCode} downloading ${url}`));
        res.resume();
        return;
      }
      res.pipe(file);
      file.on("finish", () => file.close(() => resolve()));
    });
    req.on("error", (e) => {
      fs.unlink(dest, () => {});
      reject(e);
    });
  });
}

function extractTarGz(tarball, destDir) {
  // tar is available on win10+ (bsdtar) and always on mac/linux
  fs.mkdirSync(destDir, { recursive: true });
  const args = process.platform === "win32"
    ? ["-xf", tarball, "-C", destDir]
    : ["-xzf", tarball, "-C", destDir];
  const r = spawnSync("tar", args, { stdio: "inherit" });
  if (r.status !== 0) throw new Error(`tar extraction failed (status ${r.status})`);
}

function findPythonInDir(dir) {
  const cand = process.platform === "win32"
    ? [path.join(dir, "python.exe"), path.join(dir, "python", "python.exe")]
    : [path.join(dir, "bin", "python3"), path.join(dir, "bin", "python")];
  for (const c of cand) {
    if (fs.existsSync(c)) return c;
  }
  // PBS layout: <dir>/python/ (install_only tarballs extract to ./python)
  const nested = process.platform === "win32"
    ? path.join(dir, "python", "python.exe")
    : path.join(dir, "python", "bin", "python3");
  return fs.existsSync(nested) ? nested : null;
}

function systemPython() {
  const cmd = process.platform === "win32" ? "python" : "python3";
  try {
    const r = execFileSync(cmd, ["-c", "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}')"], { stdio: ["ignore", "pipe", "ignore"] });
    const v = r.toString().trim().split(".").map(Number);
    if (v[0] >= 3 && v[1] >= 10) return { python: cmd, embedded: false };
  } catch (_) {}
  return null;
}

async function ensureRuntime() {
  // 0. marker says installed — quick verify venv python exists; fully skip
  if (fs.existsSync(MARKER)) {
    const py = VENV_PYTHON();
    if (fs.existsSync(py)) {
      return { python: py, embedded: true, fresh: false };
    }
    fs.unlinkSync(MARKER); // stale marker — reinstall
  }

  // 1. system python?
  const sys = systemPython();
  if (sys) {
    log("using system Python " + sys.python);
    return sys;
  }

  // 2. download embedded python
  const triple = platformTriple();
  const dir = path.join(RUNTIME_DIR, triple);
  const py = findPythonInDir(dir);
  if (!py) {
    const base = process.env.UIU_PYTHON_MIRROR || "https://github.com/astral-sh/python-build-standalone/releases/download";
    const url = `${base}/${PBS_RELEASE}/${PY_TAG}-${triple}-install_only.tar.gz`;
    log(`downloading embedded Python ${PY_VERSION} (${triple})…`);
    log(`  ${url}`);
    const tmpTar = path.join(os.tmpdir(), `uiu-python-${triple}.tar.gz`);
    await download(url, tmpTar);
    extractTarGz(tmpTar, dir);
    fs.unlinkSync(tmpTar);
    log("embedded Python downloaded & extracted");
  } else {
    log("using cached embedded Python");
  }
  const found = findPythonInDir(dir);
  if (!found) throw new Error("embedded python not found after install");
  return { python: found, embedded: true, fresh: true };
}

function VENV_PYTHON() {
  return process.platform === "win32"
    ? path.join(VENV_DIR, "Scripts", "python.exe")
    : path.join(VENV_DIR, "bin", "python");
}

async function ensureVenv(python) {
  if (fs.existsSync(VENV_PYTHON())) return VENV_PYTHON();
  log("creating venv…");
  const r = spawnSync(python, ["-m", "venv", VENV_DIR], { stdio: "inherit" });
  if (r.status !== 0) throw new Error(`venv creation failed (status ${r.status})`);
  return VENV_PYTHON();
}

function ensureUiuPackage(venvPython) {
  // pip install uiu pinned to the npm package version (npm & PyPI release in lockstep)
  const index = process.env.UIU_PIP_INDEX;
  const pkg = process.env.UIU_PIP_PACKAGE || `uiu==${require("../package.json").version}`;
  const args = ["-m", "pip", "install", "--quiet", "--disable-pip-version-check"];
  if (index) args.push("-i", index);
  args.push(pkg);
  log(`installing uiu package (${pkg})…`);
  const r = spawnSync(venvPython, args, { stdio: "inherit" });
  if (r.status !== 0) throw new Error(`pip install failed (status ${r.status})`);
}

function writeMarker(python, embedded) {
  fs.mkdirSync(path.dirname(MARKER), { recursive: true });
  fs.writeFileSync(MARKER, JSON.stringify({
    python: python,
    embedded: embedded,
    installedAt: new Date().toISOString(),
    version: require("../package.json").version,
  }, null, 2));
}

async function main() {
  if (process.env.UIU_SKIP_BOOTSTRAP) {
    log("UIU_SKIP_BOOTSTRAP set — skipping install");
    return 0;
  }
  // already installed & healthy → no-op (npm install/rebuild is idempotent)
  if (fs.existsSync(MARKER) && fs.existsSync(VENV_PYTHON())) {
    log("already installed — skipping");
    return 0;
  }
  try {
    const runtime = await ensureRuntime();
    const venvPy = await ensureVenv(runtime.python);
    ensureUiuPackage(venvPy);
    writeMarker(venvPy, runtime.embedded);
    log("installed. run: uiu");
    return 0;
  } catch (e) {
    logErr(`install failed: ${e.message}`);
    logErr("如果你在中国大陆，试试设置镜像:");
    logErr('  set UIU_PYTHON_MIRROR=https://ghproxy.com/https://github.com/astral-sh/python-build-standalone/releases/download');
    logErr("  set UIU_PIP_INDEX=https://pypi.tuna.tsinghua.edu.cn/simple");
    return 1;
  }
}

main().then((code) => process.exit(code));
