# ClinicalExtractor 1.0

本地化临床检查/检验/病理报告结构化抽取工具。第一版不再以“疾病全文病历理解”为核心，而是专注 **报告单结构化提取 + 人工审核 + 科研数据导出**。

## 核心流程

PDF / JPG / PNG → 按每份报告所选配置处理：

- 表格式报告：**PP-OCRv5 → 坐标恢复行列**，通过结果数量核验后直接输出；未通过时才加载并调用 **SLANet_plus** 表格模型。再自动匹配全部已收录指标，无需选择血常规或肝肾功模板。
- 长文本报告：**PP-OCRv5 → LangExtract → 本地 Ollama**，提取结构化结果并保留原文 evidence。
- 统一进入 SQLite → 人工审核 → CSV / Excel

不加载完整文档版面、表格分类、单元格检测、方向分类和公式模型。保留文字坐标；模板帮助辨认指标，不能补填本次结果。无法确定的结果需人工核对。

全部表格指标统一维护在 `profiles/table_templates/lab_test_template.yaml`，包含血常规及肝肾功等已收录的 73 项指标。新增项目、别名、显示名称、单位和兼容参考范围均修改此文件即可。旧报告及转移包中的 `cbc`、`liver_kidney` 标识自动兼容统一指标库，无需另选模板。

## Windows 极简安装

### 1. 前置条件

- Windows 10/11 x64
- [uv](https://docs.astral.sh/uv/)（`start-windows.bat` 自动下载项目专属 Python 3.12）
- Ollama（仅处理长文本报告时需要）

先在 PowerShell 中准备一个本地模型，例如：

```powershell
ollama pull qwen3:8b
```

### 2. 一键启动

双击：

```text
start-windows.bat
```

它会自动创建/检查项目环境、安装依赖，并启动浏览器。浏览器访问：`http://127.0.0.1:8765`

> 首次运行会下载缺失的 PP-OCRv5、SLANet_plus 权重；已有缓存可复用。模型缓存完成后可离线使用。Ollama 推理完全在本地完成。

## 使用方法

1. 在首页批量导入 PDF/JPG/PNG。
2. 填写患者 ID，为每份文件选择表格式或长文本报告；表格式统一匹配全指标库。
3. 点击“全部运行”：跳过已审核、待审核、排队中和处理中的报告；其他报告排队运行 OCR。配置的 Ollama 模型可用时，OCR 完成后自动进入 AI 队列；否则仅完成 OCR。
4. 基础 OCR 只识别一次；表格式报告先按坐标恢复行列，失败时使用 SLANet_plus 回退，不再进行局部重识别。内部 `stage_timings` 记录 OCR、坐标恢复和表格模型耗时。
5. 表格直接结构化并校验模板；长文本送 LangExtract + Ollama。可分别排队运行 OCR 和 AI。
6. 在报告页逐条核对证据，修正结果并点击确认。
   AI 可在疑似错位的相邻行间选择原始 OCR 结果框和参考区间片段进行配对；不允许生成数字或重复使用来源。发生调整的行显示红色“AI重新配对”，校正记录保留调整前后内容及来源坐标，需要人工确认。手动编辑的 OCR 文本不套用旧图坐标。
   原图中已清晰一一对应的结果由程序锁定，AI 不得改选相邻行。粘连参考区间的拆分同时校验项目身份与模板兼容范围；独立区间仍以原图所在行为准，保留真实的仪器范围差异和异常结果，不为落入正常范围而换行。
7. 整份报告审核完后点击“全部确认”。
8. 顶部工具栏点击“导出”，下载 CSV。
9. 顶部“数据包迁移”默认折叠，点击后导入或导出 `.ceocr`。新报告逐条追加，重复报告默认保留本机内容；只有明确勾选才覆盖对应报告。

## 数据字段

统一长表主要字段：

- `patient_id`
- `report_date`
- `report_type`
- `source_kind`（table / text）
- `category`
- `item_original`
- `item_standard`
- `value`
- `value_num`
- `unit`
- `reference_low`
- `reference_high`
- `abnormal_flag`
- `evidence`
- `page`
- `reviewed`

## Profiles

`profiles/` 用 YAML 定义不同报告的抽取提示和 few-shot 示例。目前包含：

- `generic.yaml`：通用临床报告
- `pathology.yaml`：病理/免疫组化
- `imaging.yaml`：影像检查

以后新增肺癌、结直肠癌等无需复制整套软件，只需要增加 Profile 或标准化字典。

## 设置

网页“设置”中可修改：

- Ollama 地址（默认 `http://localhost:11434`）
- Ollama 模型（默认 `qwen3:8b`）
- OCR 设备（默认 `cpu`）
- OCR 线程数（0 为自动，最多 6 线程；也可手动设置，例如这台 12 逻辑线程电脑可填 11；下份任务生效）
- 单块最大文本长度
- mock 测试模式

### AMD Windows 说明

当前 OCR 默认使用 CPU。将设备改为 gpu 不会使 CPU 版 Paddle 自动支持 AMD 显卡。Ollama 的显卡使用与 OCR 独立。

## 开发运行

```bash
python -m venv .venv
# activate environment
pip install paddlepaddle==3.2.0 -i https://www.paddlepaddle.org.cn/packages/stable/cpu/
pip install -e ".[ocr,dev]"
python -m clinical_extractor.main
```

测试：

```bash
pytest
```

## Windows 便携包

运行设置保存在 `data/settings.json`；深色模式和报告排序保存在 `data/ui_preferences.json`，不依赖浏览器端口或浏览器缓存。移动便携版时保留整个 `data` 目录。未提交的上传文件选择、文本输入和展开状态属于临时界面内容，不保存。OCR 数据包合并不覆盖本机设置。

双击根目录的 `build-portable.bat`。它会完成环境检查、安装 PyInstaller、构建 Portable，并在 `dist\ClinicalExtractor` 写入启动页、图标和说明。

输出到 `dist\ClinicalExtractor`。构建时会准备 PP-OCRv5 和 SLANet_plus 模型并复制缓存到便携版；已有缓存可能仍含旧模型。最终用户直接双击 `ClinicalExtractor.exe`，正常 OCR 不需要联网。Ollama 模型不随包携带；长文本抽取时在目标电脑安装 Ollama 即可。源码更新后须重新构建，已有 EXE 不会自动更新。

## 当前版本边界

- 第一版重点是可运行的抽取框架，不声称临床级准确率。
- 表格自动映射依赖常见表头；不规则表格可在后续加入模板/Profile。
- LangExtract 的结果质量取决于 Ollama 模型和 Profile few-shot 示例。
- 人工审核仍是最终确认环节。
