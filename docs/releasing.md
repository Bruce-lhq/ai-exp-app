# 发布说明

源码发布与安装包分开：Git 仓库只收代码、公开文档和测试，GitHub Releases 收 DMG 和校验值。内部设计与验收记录、工作空间数据库、缓存、checkpoint、config.local.json 和构建产物均不提交。

## 首次发布

1. 确认 README 的仓库拥有者占位符已换成最终地址，配置文档仍保留中性路径示例。
2. 配置 GitHub 远端并上传源码。应使用完成脱敏的历史；私人备份不能作为分支或附件上传。
3. 等 GitHub Actions 的 backend、frontend 两项通过。本地测试通过不等同于云端 CI 已验证。
4. 当前 Python、前端、API 和 Mac 构建版本已统一为 `0.3.0`。创建 tag 时使用相应版本；后续发布同步更新这些版本。
5. 在干净源码检出中按 README 安装依赖，在目标架构的 Mac 上构建。公开包的 Python 也安装到中性临时目录，避免冻结的 `_sysconfigdata` 带入本机用户名。旧自用包不要作为首个公开附件，使用中性应用标识重新构建。
6. 在新用户或独立工作空间验收首次设置、本地历史导入、绘图与列表，以及目标远端连接；安装包不应包含用户配置、缓存或私有数据。
7. 创建 GitHub Release，附上 DMG、SHA-256、平台／架构、最低系统版本、签名状态和已知限制。当前为 ad-hoc 签名，正式公开发行建议完成 Developer ID 签名与公证。

生成校验文件：

```bash
cd dist
shasum -a 256 AI-Experiment-macOS.dmg > SHA256SUMS.txt
```

在 Release 页面上传 `AI-Experiment-macOS.dmg` 与 `SHA256SUMS.txt`，不需要把它们添加到 Git。当前没有自动发布流程，CI 不会创建 tag、发布 Release 或访问 GPU。

## 公开包的中性 Python 环境

只更换源码目录不足以消除 Python 构建配置中的个人路径。公开构建可在干净检出中使用：

```bash
uv python install --install-dir /tmp/ai-exp-public-python --no-bin 3.12.12
UV_PYTHON_INSTALL_DIR=/tmp/ai-exp-public-python uv venv --managed-python --python 3.12.12
uv pip sync requirements.lock
uv pip install --no-deps -e .
uv pip install pyinstaller==6.22.3
npm --prefix web ci
.venv/bin/python scripts/build_macos.py
```

使用新建的构建工作空间，不覆盖日常开发的虚拟环境。发布前同时检查包内普通文件和 PyInstaller 的压缩 Python 模块；仅搜索原始二进制字节可能漏掉压缩内容。

## 私有与公开文件

| 内容 | 发布方式 |
| --- | --- |
| 源码、README、LICENSE、运行时配置说明 | Git |
| DMG 与校验文件 | GitHub Releases |
| `docs/superpowers/`、`docs/validation/` | 本地保留，忽略 |
| `config.local.json`、`.local/`、`gpu_downloads/` | 本地保留，忽略 |
| `.app`、`dist/`、依赖目录、缓存与生成文件 | 忽略 |

仓库只应上传公开 Git 引用。历史脱敏会改变 commit ID；不要把未清理的旧历史再合并回来。如果之后需要变更脱敏规则，应先备份，再扫描完整历史，而不只修改最新提交。

## 后续建议

- 配置主分支保护，要求两项 CI 通过后合并。
- 使用 GitHub 的密钥扫描；定期审查依赖与 GitHub Actions 固定版本。
- 增加第三方许可证清单与公开包验收，尤其是打包的 Python／前端依赖。
- 继续按项目协议和接入 SKILL 扩展适配覆盖；公开说明区分已实测功能、可配置扩展和未验收环境。

## 本次依赖审计

Vitest 已升级至 `4.1.11`，修复此前开发依赖的[已知中危问题](https://github.com/vitest-dev/vitest/security/advisories/GHSA-82fw-gwwq-j7x9)。本地单元测试、前端构建和浏览器回归通过，`npm audit`（包含开发依赖）报告零项漏洞；后续仍需定期检查。

Mac 构建将项目 MIT License、构建环境的 Python 包许可证、前端生产依赖许可证及 Python 许可证写入应用 `Contents/Resources/`。清单可能包含构建时使用但未实际打包的依赖。
