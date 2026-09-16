#!/usr/bin/env node
/**
 * uiu CLI launcher — forwards all args to the venv's uiu.
 */
"use strict";

const { spawnSync } = require("child_process");
const fs = require("fs");
const os = require("os");
const path = require("path");

const HOME = os.homedir();
const UIU_HOME = process.env.UIU_HOME || path.join(HOME, ".uiu");
const VENV_PY = process.platform === "win32"
  ? path.join(UIU_HOME, "venv", "Scripts", "python.exe")
  : path.join(UIU_HOME, "venv", "bin", "python");

if (!fs.existsSync(VENV_PY)) {
  console.error("[uiu] runtime not installed yet — run: npm rebuild uiu");
  process.exit(1);
}

// launch python -m uiu.main with the same argv
const r = spawnSync(VENV_PY, ["-m", "uiu.main", ...process.argv.slice(2)], {
  stdio: "inherit",
  env: process.env,
});
if (r.error) {
  console.error("[uiu] failed to launch:", r.error.message);
  process.exit(1);
}
process.exit(r.status === null ? 1 : r.status);
