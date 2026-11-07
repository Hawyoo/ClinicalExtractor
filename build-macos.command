#!/bin/bash
# Run on an Apple Silicon Mac: bash build-macos.command
set -euo pipefail
ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
cd "$ROOT"
if [[ "$(uname -s)" != Darwin ]]; then
  echo "请在 Mac 上运行此脚本，Windows 不能直接生成可运行的 macOS 应用。" >&2
  exit 1
fi
if [[ "$(uname -m)" != arm64 ]]; then
  echo "本流程使用 PaddlePaddle 3.3.1 的 arm64 包，需要 M 系列 Mac 和原生 arm64 终端；不支持 Intel 或 Rosetta 构建。" >&2
  exit 1
fi
for tool in curl hdiutil ditto codesign iconutil; do
  command -v "$tool" >/dev/null || { echo "缺少 macOS 构建工具：$tool" >&2; exit 1; }
done
if [[ -n "${CE_NOTARY_PROFILE:-}" && -z "${CE_CODESIGN_IDENTITY:-}" ]]; then
  echo "公证构建需要同时设置 CE_CODESIGN_IDENTITY（Developer ID Application 证书）。" >&2
  exit 1
fi
# Unique build/output folders preserve previous builds and all user data.
STAMP="$(date +%Y%m%d-%H%M%S)-$$"
WORK="$ROOT/build/macos/$STAMP"
OUTPUT="$ROOT/dist/macos/$STAMP"
mkdir -p "$WORK" "$OUTPUT"
trap 'echo "构建失败，日志和中间文件保留在：$WORK" >&2' ERR
export UV_CACHE_DIR="$ROOT/.uv-cache/macos"
if command -v uv >/dev/null; then
  UV="$(command -v uv)"
elif [[ -x "$ROOT/.uv-tools/bin/uv" ]]; then
  UV="$ROOT/.uv-tools/bin/uv"
else
  echo "[1/7] 在项目内准备 uv..."
  curl --fail --location --silent --show-error https://astral.sh/uv/install.sh -o "$WORK/uv-install.sh"
  UV_INSTALL_DIR="$ROOT/.uv-tools/bin" UV_NO_MODIFY_PATH=1 sh "$WORK/uv-install.sh"
  UV="$ROOT/.uv-tools/bin/uv"
fi
echo "[1/7] 准备独立的 macOS Python 3.12 环境..."
"$UV" python install 3.12
if [[ ! -x "$ROOT/.venv-macos/bin/python" ]]; then
  "$UV" venv --python 3.12 "$ROOT/.venv-macos"
fi
PYTHON="$ROOT/.venv-macos/bin/python"
"$PYTHON" -c 'import platform,sys; assert platform.machine()=="arm64" and sys.version_info[:2]==(3,12), "请移动旧 .venv-macos 后重试：必须使用 arm64 Python 3.12"'
echo "[2/7] 安装 OCR 和打包依赖..."
"$UV" pip install --python "$PYTHON" --editable "${ROOT}[ocr,portable]" pillow
"$PYTHON" -c 'import paddle,paddlex; paddle.utils.run_check()'
echo "[3/7] 准备三个离线 OCR 模型..."
export CLINICAL_EXTRACTOR_DATA="$WORK/source-check-data"
export PADDLE_PDX_CACHE_HOME="${CE_MODEL_CACHE:-$ROOT/.portable-model-cache}"
export PADDLE_PDX_DISABLE_MODEL_SOURCE_CHECK=True
export FLAGS_use_mkldnn=0
"$PYTHON" scripts/warm-ocr-models.py
"$PYTHON" scripts/copy-portable-models.py "$PADDLE_PDX_CACHE_HOME/official_models" "$WORK/models/paddlex-cache/official_models"
echo "[4/7] 转换应用图标并构建 .app..."
"$PYTHON" scripts/make-macos-icon.py static/clinical-extractor.ico "$WORK/ClinicalExtractor.icns"
export CE_MAC_BUILD_ROOT="$WORK"
"$PYTHON" -m PyInstaller --noconfirm --clean --workpath "$WORK/pyinstaller" --distpath "$OUTPUT" ClinicalExtractor-macos.spec 2>&1 | tee "$WORK/build.log"
APP="$OUTPUT/ClinicalExtractor.app"
echo "[5/7] 检查签名及打包后的 OCR 环境..."
codesign --verify --deep --strict --verbose=2 "$APP"
CLINICAL_EXTRACTOR_MAC_HOME="$WORK/frozen-check-home" "$APP/Contents/MacOS/ClinicalExtractor" --self-check
echo "[6/7] 生成拖入 Applications 安装的 DMG..."
STAGE="$WORK/dmg-stage"
mkdir -p "$STAGE"
ditto "$APP" "$STAGE/ClinicalExtractor.app"
ln -s /Applications "$STAGE/Applications"
cp docs/MACOS_DMG.md "$STAGE/使用说明.md"
VERSION="$("$PYTHON" -c 'import tomllib; print(tomllib.load(open("pyproject.toml","rb"))["project"]["version"])')"
DMG="$OUTPUT/ClinicalExtractor-$VERSION-arm64-$STAMP.dmg"
hdiutil create -volname ClinicalExtractor -srcfolder "$STAGE" -format UDZO "$DMG"
if [[ -n "${CE_CODESIGN_IDENTITY:-}" ]]; then
  codesign --force --sign "$CE_CODESIGN_IDENTITY" --timestamp "$DMG"
fi
echo "[7/7] 校验 DMG..."
if [[ -n "${CE_NOTARY_PROFILE:-}" ]]; then
  xcrun notarytool submit "$DMG" --keychain-profile "$CE_NOTARY_PROFILE" --wait
  xcrun stapler staple "$DMG"
fi
hdiutil verify "$DMG"
shasum -a 256 "$DMG" > "$DMG.sha256"
echo "完成：$DMG"
echo "用户数据未打入 DMG，现有项目和配置未被更改。"
if [[ -z "${CE_NOTARY_PROFILE:-}" ]]; then
  echo "此构建未经 Apple 公证；对外发布建议使用 Developer ID 签名及公证，参见 docs/MACOS_DMG.md。"
fi
