# uiu-agent — npm 安装壳

让用户**只装 npm、不装 Python** 就能用 uiu（Python 由本包自动安装）。

> npm 包名是 **`uiu-agent`**（`uiu` 裸名 2020 年被占坑）；安装后命令仍是 `uiu`。

## 原理

`npm install -g uiu-agent` 触发 `postinstall`，自动完成三步：

1. **找 Python**：系统 Python 在 **CI 覆盖过的版本区间**（3.10–3.13）内就直接用；
   若只有更新的 major（如 3.14），**不冒险**——因为 uiu 的依赖（pyautogui 生态等）在新版本上
   常常没有 wheel，pip 会去源码编译然后失败。此时回落到下载
   [python-build-standalone](https://github.com/astral-sh/python-build-standalone)
   的嵌入式 CPython 到 `~/.uiu/runtime/`（uv/ruff 同款方案，30MB 级，只下一次）
2. **建 venv**：`~/.uiu/venv/`；若 `python -m venv` 失败（杀软/受限 ACL/老 Python 的
   ensurepip 问题），自动退化成 `venv --without-pip` + 显式 `ensurepip` 自举
3. **装 uiu 包体**：`pip install uiu==<npm 版本>`（从 PyPI，版本与 npm 包锁步）

> 落地过程中的两个真实修复（端到端跑出来的）：GitHub release 下载**必然 302 到 CDN**，
> 旧下载器只认 200、于是「没有系统 Python」的用户 100% 失败；另外系统 Python 探测原先抓 stdout，
> 在禁止 Node 建管道的受限环境里会抛异常并被吞掉——现在改成只看退出码 + 写临时文件。

`uiu` 命令（`bin/uiu.js`）只是薄启动器，把所有参数转发给 venv 里的 Python。

## 用户视角

```bash
npm install -g uiu-agent   # 唯一安装步骤（首次会后台下 Python，稍等）
uiu                        # 直接用
uiu update self            # 升级 Python 包体（pip 升级）
npm update -g uiu-agent    # 升级 npm 壳本身
```

## 发布（作者）

```bash
npm adduser                # 首次：注册/登录 npm（浏览器或账号密码）
cd npm
npm publish                # 发版（version 与 PyPI 包版本一致）
```

## 环境变量（可选）

| 变量 | 作用 |
|---|---|
| `UIU_PYTHON_MIRROR` | python-build-standalone 下载镜像（大陆用户可用 ghproxy 前缀） |
| `UIU_PIP_INDEX` | pip 镜像（如 `https://pypi.tuna.tsinghua.edu.cn/simple`） |
| `UIU_HOME` | 运行时目录（默认 `~/.uiu`），测试/多用户隔离用 |
| `UIU_SKIP_BOOTSTRAP` | 设任意值跳过安装（打包场景） |

## 发布步骤（每次发版）

1. `uiu publish` 发 PyPI（先确保 `uiu==<version>` 能正常 pip 装，见依赖坑）
2. 改 `npm/package.json` 的 `version` 与 Python 包版本一致
3. `cd npm && npm publish`

## 已验证

- 首次安装（系统 Python 路径）：venv 创建 + pip 装包 ✅
- 幂等：重复 install 直接 skip ✅
- `uiu <子命令>` 透传调起 ✅
- 隔离 `UIU_HOME` 测试 ✅

## 已知坑

- **PyPI 包依赖必须可装**：曾出现 PyPI 上 `rapidocr-onnxruntime>=1.3.0` 但 PyPI 无此版本导致安装失败——发布前务必在干净 venv 里 `pip install uiu==<version>` 验证。
- 首次安装需下载 ~30MB Python（无系统 Python 时）；`rapidocr` 等依赖额外 ~100MB。
