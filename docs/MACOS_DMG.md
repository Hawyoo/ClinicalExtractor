# ClinicalExtractor macOS DMG

## 构建

在 Apple Silicon（M 系列）Mac 上，将完整源码文件夹复制或克隆到本机，在该文件夹的终端执行：

```bash
bash build-macos.command
```

脚本在项目内准备 uv 和独立的 Python 3.12 环境，安装当前固定的 PaddlePaddle 3.3.1、PaddleX 3.7.2 及打包依赖，准备 PP-OCRv5 检测、识别、SLANet_plus 三个模型，然后生成 `.app` 和压缩 DMG。首次构建需要联网和足够的磁盘空间。已有 uv 可直接复用；不会改动 Windows `.venv` 或现有项目数据。

输出位于 `dist/macos/<构建时间>/`，DMG 文件名包含版本、arm64 和构建时间，旁边附 SHA-256 校验文件。每次使用独立目录，不覆盖先前发布包。构建日志保存在 `build/macos/<构建时间>/build.log`。

打包脚本仅支持原生 arm64 构建。当前固定版本在 PyPI 提供 macOS arm64 的 Python 3.12 wheel，未提供对应的 Intel macOS wheel，因此不以 Rosetta 或替换旧版 OCR 引擎的方式拼接 Intel 包。macOS 最低版本按构建机记录；其他系统版本仍需实机验证。

Windows 上不能直接运行该脚本生成可用的 Mac DMG，需要 Mac 本机或 macOS 构建机器。

## 安装和启动

打开 DMG，将 `ClinicalExtractor.app` 拖到 `Applications`，然后双击启动。应用会在本地启动服务，就绪后只打开一次默认浏览器。再次打开应用会复用已有服务。网页顶部“退出程序”关闭本地服务。Ollama 及其大模型不包含在 DMG 内，请单独安装或连接已有的 Ollama 服务。

DMG 包含三个离线 OCR 模型。首次启动将模型复制到可写的用户缓存，后续复用；不会向只读 DMG 或签名后的 `.app` 写入项目和配置。

用户目录：`~/Library/Application Support/ClinicalExtractor/`

- `data/projects/`：各项目的数据库、图片、审核和导出数据。
- `data/table_templates/`：共用自定义检验模板。
- `data/settings.json`、`data/ui_preferences.json`：Ollama、OCR 和界面设置。
- `models/paddlex-cache/`：可写的 OCR 模型缓存。
- `logs/launcher.log`：启动及服务日志。
- `DELETE/`：删除项目时保留的恢复文件。

第一次进入网页先创建或打开项目，不自动创建默认项目。跨电脑或 Windows/Mac 之间使用“数据包迁移”导入 `.ceocr`，新报告追加，重复报告按现有规则处理。更新或替换 `.app` 不会覆盖上述用户目录。打包不会包含你的患者数据或 Ollama 设置。

## 签名和公证（对外分发）

未配置 Apple Developer 身份时，PyInstaller 使用本地临时签名；这不等于 Apple Developer ID 签名或公证，也不保证通过其他 Mac 的 Gatekeeper 检查。脚本不关闭系统安全检查。

正式发布时，在已配置好 Developer ID Application 证书及 `notarytool` 钥匙串凭据的 Mac 上运行：

```bash
export CE_CODESIGN_IDENTITY='Developer ID Application: Your Name (TEAMID)'
export CE_NOTARY_PROFILE='your-notarytool-keychain-profile'
bash build-macos.command
```

脚本将签名应用和 DMG，提交公证并附加公证票据。请使用真实证书与已保存的钥匙串配置；不要在源码中填写 Apple 密码。仍须在目标 Mac 上验证安装、真实报告 OCR、Ollama、退出及重新启动。本仓库的 Windows 检查不能替代这一步。

## 来源

- [PyInstaller 多平台打包说明](https://www.pyinstaller.org/en/stable/usage.html)
- [PyInstaller macOS 签名说明](https://www.pyinstaller.org/en/stable/feature-notes.html)
- [PaddlePaddle 3.3.1 发布文件](https://pypi.org/project/paddlepaddle/3.3.1/)
