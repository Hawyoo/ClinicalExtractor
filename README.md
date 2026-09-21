# ClinicalExtractor 1.0

本地化临床检查/检验/病理报告结构化抽取工具。第一版不再以“疾病全文病历理解”为核心，而是专注 **报告单结构化提取 + 人工审核 + 科研数据导出**。

## 核心流程

PDF / JPG / PNG → **PP-StructureV3** → 区域分流：

- 表格区域：直接恢复表格并抽取 `项目 / 结果 / 单位 / 参考范围 / 异常标志`
- 长文本区域：**LangExtract → 本地 Ollama**，提取结构化结果并保留原文 evidence
- 统一进入 SQLite → 人工审核 → CSV / Excel

同一页可同时包含表格和长文本，两类区域分别处理后再合并。

## Windows 极简安装

### 1. 前置条件

- Windows 10/11 x64
- Python 3.11（推荐）
- Ollama

先在 PowerShell 中准备一个本地模型，例如：

```powershell
ollama pull qwen3:8b
```

### 2. 安装 ClinicalExtractor

右键 PowerShell 运行：

```powershell
powershell -ExecutionPolicy Bypass -File scripts\install-windows.ps1
```

安装脚本会创建项目内 `.venv`，安装 PaddlePaddle CPU、PP-StructureV3 所需 `paddleocr[doc-parser]`、LangExtract 和 Web UI 依赖。

### 3. 启动

双击：

```text
start-windows.bat
```

浏览器访问：`http://127.0.0.1:8765`

> 首次真正运行 PP-StructureV3 时，PaddleOCR 会下载对应模型权重，因此第一次需要联网。模型缓存完成后可离线使用。Ollama 推理完全在本地完成。

## 使用方法

1. 在首页批量导入 PDF/JPG/PNG。
2. 填写患者 ID、报告日期、报告类型，可选择通用/病理/影像 Profile。
3. 点击“处理”。
4. PP-StructureV3 对每页做 OCR、版面和表格解析。
5. 表格区域直接结构化；文字区域送 LangExtract + Ollama。
6. 在报告页逐条核对 evidence，修正结果并勾选确认。
7. 整份报告审核完后点击“全部确认并标记已审核”。
8. 导出 CSV 或 Excel。

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
- PP-StructureV3 设备（默认 `cpu`）
- 单块最大文本长度
- mock 测试模式

### AMD Windows 说明

第一版默认让 PP-StructureV3 使用 CPU，以降低 Windows AMD GPU 兼容问题。Ollama 是否使用 AMD GPU 取决于你的 Ollama/ROCm/驱动支持情况，两者互不影响。

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

在已经安装好的 Windows 环境执行：

```powershell
powershell -ExecutionPolicy Bypass -File scripts\build-portable.ps1
```

输出到 `dist\ClinicalExtractor`。注意 PaddleOCR 模型权重体积很大且由运行时缓存管理，本脚本默认不把模型权重硬塞进 EXE；若需要医院完全离线分发，后续应单独做“预下载模型缓存 + portable bundle”。

## 当前版本边界

- 第一版重点是可运行的抽取框架，不声称临床级准确率。
- 表格自动映射依赖常见表头；不规则表格可在后续加入模板/Profile。
- LangExtract 的结果质量取决于 Ollama 模型和 Profile few-shot 示例。
- 人工审核仍是最终确认环节。
