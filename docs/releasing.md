# 发布说明

Git 只收源码、公开文档与测试。桌面安装包、CLI 压缩包及校验值通过 GitHub Releases 分发。工作空间数据库、缓存、checkpoint、`config.local.json`、内部设计与构建产物均不提交。下载版本以 GitHub Releases 为准；源码开发版本以 `pyproject.toml` 为准。

## 构建与自动验证

`.github/workflows/ci.yml` 在 Ubuntu 24.04、Windows Server 2025、macOS Apple Silicon 和 Intel 执行后端测试；前端测试、构建与 Chromium 回归在 Linux 执行。真正依赖远端 Linux `/proc`／进程管理的测试只在 Linux 运行，本地功能仍在四个平台验证，不连接真实 GPU。

`.github/workflows/build-platforms.yml` 在目标系统上构建，无跨系统冻结 Python。主分支相关代码变更、版本 tag 或手动触发都会运行；它只上传 Actions artifacts，不自动创建 Release。所有包和普通 CI 通过后，可手动触发 `publish-release.yml`，给出已存在的版本 tag、包构建 run ID 和是否预览；常规发布还需 `docs/releases/<tag>.md`。发布器核对同一 commit、四个平台及安装验收证据后才发布 Release。

| 构建环境 | 桌面 | CLI |
| --- | --- | --- |
| macOS 15 arm64 | Swift AppKit + WebKit，DMG | 冻结 Python，tar.gz |
| macOS 15 Intel | Swift AppKit + WebKit，DMG | 冻结 Python，tar.gz |
| Windows Server 2025 x64 | pywebview + EdgeChromium，NSIS 用户安装包 | 冻结 Python，ZIP |
| Ubuntu 24.04 x64 | pywebview + PySide6 QtWebEngine，deb | 冻结 Python，tar.gz |

包内包含构建后的网页、标准库远端代理、接入 SKILL、MIT 与第三方许可证。CLI 包必须保留整个目录。Linux 系统库通过 deb 的依赖声明安装；Windows 安装器包含官方 WebView2 引导器，验证其 Microsoft 签名后打包，首次安装需联网获取运行时。

冻结包验证在独立临时工作空间执行：从任意目录启动 CLI、启动／复用／认证停止服务、本地导入、缓存 Markdown、无显示器 PNG，并校验源指标没有变化。原生验证真正启动 WebKit／Edge／Qt，等待 React 根节点加载，不只检查进程存在。

**验证边界：**Windows Server CI 不能替代 Windows 11 桌面人工验收；Xvfb 下的 Qt 测试不能替代真实 Ubuntu 桌面文件选择、通知和显示缩放验收。所有包附 `human_acceptance: false` 记录；没有人类实测证据就不改为已验收。用户已确认的真机结果在版本发布说明中单独注明，不能覆盖自动测试报告的验收边界。Mac 包最低版本声明为 13，但 CI 在 15 构建和运行，旧版本仍需验收。

## 本地构建

在干净检出与专用虚拟环境执行，始终显式指定目标解释器：

```bash
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements-desktop.lock
.venv/bin/python -m pip install --no-deps -e .
.venv/bin/python -m pip install PyInstaller==6.22.3
npm --prefix web ci
npm --prefix web run build
```

Windows 用 `py -3.12 -m venv .venv` 创建环境，将虚拟环境路径改为 `.venv/Scripts/python.exe`。目标系统命令：

- Mac：安装 Xcode Command Line Tools，运行 `.venv/bin/python scripts/build_macos.py --arch arm64`；Intel 用 `x86_64` 并在 Intel runner／Python 构建。
- Windows：安装 NSIS，运行 `.venv/Scripts/python.exe scripts/build_desktop.py`。
- Ubuntu：安装 Qt 系统依赖与 `dpkg-deb`，运行 `.venv/bin/python scripts/build_desktop.py`。完整 apt 依赖以 workflow 和 deb control 为准。

产物位于 `dist/releases/`。验证和校验命令：

```bash
.venv/bin/python scripts/smoke_platform.py --executable dist/frozen/ai-experiment/ai-experiment --report dist/verification/local-cli.json
.venv/bin/python scripts/package_checksums.py
```

Ubuntu 原生验证加 `--desktop` 并使用 Xvfb；Mac 原生验证加 `--mac-app "dist/AI Experiment.app/Contents/MacOS/AIExperiment"`。Windows 可执行文件带 `.exe`。

## 发布检查

1. 统一 `pyproject.toml`、前端、API、构建脚本与 Swift 的版本，检查 README 命令和下载文件名。
2. 等目标 commit 的普通 CI 与四平台包验证都通过。下载对应 artifacts，合并 `SHA256SUMS.txt`，保留分平台验收 JSON。
3. 扫描 Git 的所有公开引用与安装包内容，不包含个人路径、认证信息、用户配置或实验缓存；压缩的 Python 模块也要检查。不要把未清理的旧历史重新合并或上传私人备份。
4. 创建版本 tag 和 Release，上传四种桌面包、四种 CLI 包、校验文件与自动验证记录；写明签名及人工验收边界。
5. 在有目标机器后补首次安装／升级／卸载、文件选择、SSH、通知与屏幕缩放人工验收，再提高支持等级。

Mac 当前 ad-hoc 签名，未做 Developer ID 公证；Windows 安装器未做发行者代码签名。发布签名、主分支保护、依赖／密钥扫描和更多发行版验收可继续完善。

## 中性构建环境

仅移动源码目录不足以清除 Python 构建配置中的个人路径。公开本机构建使用新建中性临时目录、干净检出与中性 Python。可将 Python 安装在中性目录，再用该解释器创建虚拟环境；下面是使用可选开发工具 uv 的一种方式（用户安装／运行不需要 uv）：

```bash
uv python install --install-dir /tmp/ai-exp-public-python --no-bin 3.12.12
UV_PYTHON_INSTALL_DIR=/tmp/ai-exp-public-python uv venv --managed-python --python 3.12.12
```

随后按上文显式指定该环境安装、构建。CI 使用干净的 runner。检查包内普通文件和 PyInstaller 压缩模块；只搜索原始二进制字节会漏掉压缩内容。包内许可证清单可能包含构建使用但未实际打包的依赖，第三方仍保留其原许可证。
