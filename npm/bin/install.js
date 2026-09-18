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

const { spawnSync } = require("child_process");
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

function download(url, dest, redirectsLeft = 6) {
  // GitHub release 下载**必然** 302 到 CDN（objects.githubusercontent.com），
  // 早先这里只接受 200，导致 embedded Python 这条路对所有人都失败。
  return new Promise((resolve, reject) => {
    const req = https.get(url, { headers: { "User-Agent": "uiu-npm-installer" } }, (res) => {
      const code = res.statusCode || 0;
      if (code >= 300 && code < 400 && res.headers.location) {
        res.resume();
        if (redirectsLeft <= 0) {
          reject(new Error(`too many redirects downloading ${url}`));
          return;
        }
        const next = new URL(res.headers.location, url).toString();
        download(next, dest, redirectsLeft - 1).then(resolve, reject);
        return;
      }
      if (code !== 200) {
        reject(new Error(`HTTP ${code} downloading ${url}`));
        res.resume();
        return;
      }
      const file = fs.createWriteStream(dest);
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

// 系统 Python 探测：**只看退出码**，不抓 stdout。
// 抓 stdout 需要管道，而受限环境（容器/沙箱）常常禁止 Node 建管道；
// 更糟的是旧实现把异常吞掉，于是"有 Python 也当作没有"，白白去下 100MB。
const PY_CANDIDATES = process.platform === "win32"
  ? [{ cmd: "python", args: [] }, { cmd: "py", args: ["-3"] }, { cmd: "python3", args: [] }]
  : [{ cmd: "python3", args: [] }, { cmd: "python", args: [] }];
// uiu 自身要求 >=3.10，但**依赖**（pyautogui 生态等）在新 major 上常常没有 wheel。
// 所以只把 CI 覆盖过的版本当首选；更激进的新版本（如 3.14）会让 pip 去源码编译而失败，
// 这时宁可走内置运行时（这也是「零前置」承诺的本来含义）。
const PREFERRED_PY = ["3.12", "3.13", "3.11", "3.10"];
// 探测把版本写到文件里（不用管道：受限环境禁止 Node 建管道）
const PROBE = [
  "import sys, importlib.util",
  "open(sys.argv[1], 'w').write('%d.%d' % sys.version_info[:2])",
  "sys.exit(0 if (sys.version_info >= (3, 10) and importlib.util.find_spec('venv')) else 1)",
].join("; ");

function probePython(cand) {
  const out = path.join(os.tmpdir(), `uiu-pyprobe-${process.pid}.txt`);
  try { fs.unlinkSync(out); } catch (_) {}
  try {
    const r = spawnSync(cand.cmd, [...cand.args, "-c", PROBE, out], { stdio: "ignore" });
    if (r.status !== 0) return null;
    return fs.readFileSync(out, "utf8").trim();
  } catch (_) {
    return null;
  } finally {
    try { fs.unlinkSync(out); } catch (_) {}
  }
}

function systemPython() {
  const found = [];
  for (const cand of PY_CANDIDATES) {
    const version = probePython(cand);
    if (version) found.push({ cand, version });
  }
  const preferred = found.find((f) => PREFERRED_PY.includes(f.version));
  if (preferred) {
    return { python: [preferred.cand.cmd, ...preferred.cand.args],
             embedded: false, version: preferred.version };
  }
  if (found.length) {
    log(`found Python ${found.map((f) => f.version).join("/")} but none in the tested range ` +
        `${PREFERRED_PY.join("/")} — using the embedded runtime instead`);
  } else {
    log("no system Python >=3.10 with venv — using the embedded runtime");
  }
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
    log("using system Python: " + sys.python.join(" "));
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

// python 既可能是路径字符串（embedded），也可能是 argv 前缀数组（py -3）
function asArgv(spec) {
  return Array.isArray(spec) ? spec : [spec];
}

async function ensureVenv(python) {
  if (fs.existsSync(VENV_PYTHON())) return VENV_PYTHON();
  const argv = asArgv(python);
  log("creating venv…");
  let r = spawnSync(argv[0], [...argv.slice(1), "-m", "venv", VENV_DIR], { stdio: "inherit" });
  if (r.status !== 0) {
    // 某些机器上 venv 自带的 ensurepip 会失败（杀软 / 受限 ACL / 老版本 Python）。
    // 退化成「先建空 venv，再显式自举 pip」——实测这条路在那些机器上是通的。
    log("plain venv failed — retrying with --without-pip + ensurepip (self-bootstrap)");
    fs.rmSync(VENV_DIR, { recursive: true, force: true });
    r = spawnSync(argv[0], [...argv.slice(1), "-m", "venv", "--without-pip", VENV_DIR],
                  { stdio: "inherit" });
    if (r.status !== 0) throw new Error(`venv creation failed (status ${r.status})`);
    const boot = spawnSync(VENV_PYTHON(), ["-m", "ensurepip", "--upgrade", "--default-pip"],
                           { stdio: "inherit" });
    if (boot.status !== 0) throw new Error(`ensurepip failed (status ${boot.status})`);
  }
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
