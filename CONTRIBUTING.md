# 贡献指南

欢迎通过 GitHub Issues 报告问题，或提交 Pull Request。反馈请包含系统版本、应用版本、复现步骤和已脱敏的错误信息；不要上传密码、私钥、个人配置或完整实验缓存。

开发前按 [README 的源码安装步骤](README.md#从源码运行)准备专用环境。先复现问题，再做相关范围内的修改，并运行适用的检查。前端开发使用 `npm --prefix web run dev`。跨平台构建必须在目标系统与架构执行；完整发布流程见 [发布说明](docs/releasing.md)。

## 运行测试

```bash
.venv/bin/python -m pytest -q
npm --prefix web test
npm --prefix web run build
cd web
npx playwright install chromium webkit
npm run test:e2e
npm run test:e2e -- --browser=webkit tests/mobile_workbench.spec.ts
```

CI 使用临时目录、模拟远端接口和小型普通命令测试，不需要连接真实 GPU 或配置 SSH。GitHub Actions 在 Linux、Windows Server、两种 Mac 架构执行后端测试，Linux 执行前端测试与 Chromium 回归；包构建流程另测冻结 CLI、离线导出与真实原生渲染器。Windows Server CI 不等同于 Windows 11 人工验收。

## 构建桌面与 CLI

在目标系统／架构上构建，不能在 Mac 上冻结 Windows 或 Linux 可执行文件。先安装对应桌面依赖和 PyInstaller：

```bash
.venv/bin/python -m pip install -r requirements-desktop.lock
.venv/bin/python -m pip install --no-deps -e .
.venv/bin/python -m pip install PyInstaller==6.22.3
```

Mac 安装 Xcode Command Line Tools 后运行 `.venv/bin/python scripts/build_macos.py`；Windows 安装 NSIS 后运行 `.venv/Scripts/python.exe scripts/build_desktop.py`；Ubuntu 安装包流程见 [发布说明](docs/releasing.md)。产物位于 `dist/releases/`，发布到 GitHub Releases，不进入 Git。

