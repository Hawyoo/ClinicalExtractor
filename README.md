# ClinicalExtractor

本地临床报告整理工具，支持 Windows 源码启动、离线 OCR 便携版，以及 Apple Silicon macOS DMG 构建。

## 当前流程

- 表格式报告：PP-OCRv5 识字 → 坐标恢复行列 → 必要时 SLANet_plus 回退 → 统一检验模板校验 → Ollama 核对名称及疑难配对。
- 长文本报告：PP-OCRv5 识字 → LangExtract + Ollama 提取原文明示的结果。
- OCR 与 AI 两条独立串行队列并行运行。无 Ollama 时仍可导入、OCR、审核和迁移数据。
- OCR 只识别一次，不做局部重新识别。结果必须来自原文，清晰的行对应由程序锁定；AI 调整过的配对标红并保留来源记录。

## 使用

1. 批量导入图片、PDF 或已有 OCR 文本，填写患者 ID，并为每个文件选择“表格式报告”或“长文本报告”。
2. 点击“全部运行”。已审核、待审核、排队中和处理中的报告会跳过；配置的 Ollama 模型可用时，OCR 完成后自动进入 AI 队列。
3. 在报告页检查和修改结果、编辑 OCR 文本、补充遗漏项目。逐行确认或“全部确认”，页面保持原处。
4. 顶部“导出”下载当前项目的 CSV，文件名包含导出时间，例如 `clinical_extractor-20261105-223000.csv`。列名为 `patient_id,report_type,file_name,item_name,item_abbr,result,unit,reviewed`。
5. 顶部“数据包迁移”可导入或导出 `.ceocr`，包含原图及已有结果；未 OCR 的图片也可打包。新报告追加，重复报告默认跳过，只有明确勾选才覆盖。

默认按状态实时排序：未处理 → 待审核 → 失败 → OCR已完成 → AI处理中 → AI排队中 → OCR处理中 → OCR排队中 → 已审核。同状态按添加顺序排列。

## 模板与数据

内置统一检验模板为 `profiles/table_templates/lab_test_template.yaml`，包含 73 项及常见分区。审核页的“新增 / 修改检验模板”支持修改展示名称、兼容名称、CSV 英文缩写、多个参考范围、单位和所属分区，也可新建指标；所属分区使用实时下拉框，旁边“新建分类”可独立保存新分类。分区只用于整理，不限制自动匹配。 英文全称可填写在项目兼容名称中，不另设英文名称字段。

自定义内容保存在 `data/table_templates/custom.yaml`，历史版本保存在旁边的 `history` 目录；对所有项目共用，升级或重新打包时随 `data` 保留，并与内置模板合并使用。模板保存不改写报告结果、不重置审核状态，也不会刷新并丢弃当前审核输入。名称及 CSV 缩写在下次刷新/导出时使用新设置；需要重新识别旧的未匹配项目时，执行该报告的 AI 处理。模板只辅助辨认，不补缺失结果。长文本抽取配置为 `profiles/generic.yaml`。

- `data/projects/<项目ID>/project.json`：项目名称及标识。
- `data/projects/<项目ID>/clinical_extractor.sqlite3`：该项目的报告、结果与审核记录。
- `data/projects/<项目ID>/uploads`、`exports`：该项目的原图和导出文件。
- `data/projects.json`：项目列表及上次打开的项目。
- `data/settings.json`：Ollama、OCR 线程等运行设置。
- `data/ui_preferences.json`：深色模式与排序偏好，跨启动端口保存。

移动便携版时保留整个 `data`。数据包合并不覆盖本机设置。未提交输入及文件选择属于临时状态。

顶部“当前项目”下拉框用于切换；“项目管理”可新建项目，或填写已有项目文件夹路径打开。列表、队列、CSV 和数据包迁移只针对当前项目。模型、模板、Ollama 设置及深色模式共用。切换前须等待 OCR/AI 队列完成。

首次启动先创建或打开项目，不会自动创建“默认项目”。检测到旧版数据时，可在创建项目时主动勾选导入，保留审核状态及原文件备份。以后启动记住最后选择的有效项目；文件夹被删除或移动后，自动移除失效登记并回到项目选择页。项目管理支持删除当前项目，文件夹移入根目录 `DELETE`，可通过“打开已有项目”恢复。跨项目迁移时，先导出 `.ceocr`，切换目标项目再导入；完整搬迁也可在关闭程序后复制项目文件夹，再在另一台电脑打开。

## Windows 启动与打包

- 源码启动：双击 `start-windows.bat`，自动用 uv 准备 Python 3.12 并检查依赖。
- 打包：双击 `build-portable.bat`。需要已安装 uv，并在首次准备依赖和模型时联网。
- 便携版：输出在 `dist/ClinicalExtractor`，双击 `ClinicalExtractor.exe`，启动窗口就绪后打开默认浏览器。

便携版只携带三个模型：`PP-OCRv5_server_det`、`PP-OCRv5_server_rec`、`SLANet_plus`。保留离线 OCR 与表格回退。Ollama 服务与其模型由用户另行准备，例如 `qwen3:8b`。

OCR 使用 CPU，自动最多 6 个线程；运行设置支持手动调整。设置 `gpu` 不能让 CPU Paddle 使用 AMD GPU。当前固定 PaddlePaddle 3.3.1 与 PaddleX 3.7.2，oneDNN 关闭。

构建前会保留既有便携版数据；归档文件位于根目录 `DELETE`，不进入运行或发布包。源码变化后须重新构建 EXE。

## macOS 打包

在 M 系列 Mac 的项目目录执行 `bash build-macos.command`。脚本自动准备独立 Python 3.12、当前 OCR 依赖和三个离线模型，构建 `.app` 并生成带版本与时间的 DMG，输出到 `dist/macos/<构建时间>/`。不能在 Windows 上直接交叉构建，也不支持用当前依赖生成 Intel Mac 包。

安装后双击应用打开默认浏览器；数据保存在 `~/Library/Application Support/ClinicalExtractor/`，更新应用不会覆盖项目、模板或设置。Ollama 需另行安装或连接。可配置 Developer ID 签名及 Apple 公证；具体操作见 [macOS 使用与发布说明](docs/MACOS_DMG.md)。Mac 安装、OCR 与 Ollama 仍需实机验证。

## 开发验证

安装开发依赖后执行 `python -m pytest`；前端检查位于 `tests/js`。`scripts/check-real-ocr.py` 与 `scripts/benchmark-ocr.py` 用于只读验证，后者会避开正在运行的应用队列。

人工审核是最终确认环节。软件不根据“结果是否正常”改写或交换真实数值。
