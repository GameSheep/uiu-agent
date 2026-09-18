/**
 * npm(semver) → PyPI(PEP 440) 版本号映射。
 *
 * 为什么需要它：npm 的预发布版本必须写成 `0.2.0-b1`（需要那个连字符），
 * 而 PyPI 只接受 `0.2.0b1`。install.js 用 npm 的版本去 pin Python 包
 * （`pip install uiu==<version>`），不做映射就会在**发预发布版时全员安装失败**：
 *
 *     pip install uiu==0.2.0-b1   → ERROR: No matching distribution found
 *
 * 规则（够用且可预测）：
 *   0.2.0        → 0.2.0        （正式版原样）
 *   0.2.0-b1     → 0.2.0b1
 *   0.2.0-beta.1 → 0.2.0b1
 *   1.0.0-rc.2   → 1.0.0rc2
 *   1.0.0-alpha  → 1.0.0a0      （缺编号补 0）
 *   0.2.0-dev.5  → 0.2.0.dev5   （其它后缀：去掉非字母数字，按 PEP 440 dev 段处理）
 */
"use strict";

const SUFFIX = [
  [/^(?:a|alpha)\.?(\d*)$/i, (n) => "a" + (n || "0")],
  [/^(?:b|beta)\.?(\d*)$/i, (n) => "b" + (n || "0")],
  [/^(?:rc)\.?(\d*)$/i, (n) => "rc" + (n || "0")],
  [/^(?:dev)\.?(\d*)$/i, (n) => ".dev" + (n || "0")],
];

function pep440(version) {
  const raw = String(version).trim();
  const m = /^(\d+\.\d+\.\d+)(?:[-+]?(.+))?$/.exec(raw);
  if (!m) throw new Error(`unrecognised version: ${raw}`);
  const [, base, suffix] = m;
  if (!suffix) return base;
  for (const [re, build] of SUFFIX) {
    const hit = re.exec(suffix);
    if (hit) return base + build(hit[1]);
  }
  // 兜底：去掉非字母数字，交给 pip 当 dev 段（例如 -nightly.3 → .devnightly3）
  const cleaned = suffix.replace(/[^0-9a-z]/gi, "");
  if (!cleaned) return base;
  process.stderr.write(`[uiu] 未知的预发布后缀 '${suffix}'，按 PEP 440 兜底处理为 ${base}.dev${cleaned}\n`);
  return `${base}.dev${cleaned}`;
}

module.exports = { pep440 };

if (require.main === module) {
  // 自检：node npm/lib/version.js
  const table = [
    ["0.2.0", "0.2.0"],
    ["0.2.0-b1", "0.2.0b1"],
    ["0.2.0-beta.1", "0.2.0b1"],
    ["1.0.0-rc.2", "1.0.0rc2"],
    ["1.0.0-alpha", "1.0.0a0"],
    ["0.2.0-dev.5", "0.2.0.dev5"],
  ];
  let bad = 0;
  for (const [input, want] of table) {
    const got = pep440(input);
    const ok = got === want;
    if (!ok) bad++;
    console.log(`${ok ? "ok  " : "FAIL"} ${input.padEnd(16)} -> ${got}  (want ${want})`);
  }
  process.exit(bad ? 1 : 0);
}
