from pathlib import Path
from importlib.metadata import requires
import os
import platform
import tomllib
from packaging.requirements import Requirement
from PyInstaller.utils.hooks import collect_all, copy_metadata

root = Path(SPECPATH)
work = Path(os.environ['CE_MAC_BUILD_ROOT'])
identity = os.environ.get('CE_CODESIGN_IDENTITY') or None
version = tomllib.loads((root / 'pyproject.toml').read_text(encoding='utf-8'))['project']['version']
datas = [(str(root / name), name) for name in ('templates', 'static', 'profiles')]
datas += [(str(work / 'models'), 'models')]
datas += [(str(root / name), '.') for name in ('LICENSE', 'THIRD_PARTY.md')]
binaries, hiddenimports = [], []
for package in ('paddle', 'paddlex', 'langextract'):
    package_data, package_binaries, package_hidden = collect_all(package)
    datas += package_data
    binaries += package_binaries
    hiddenimports += package_hidden
for name in sorted({Requirement(item).name for item in requires('paddlex')
                    if Requirement(item).marker is None or Requirement(item).marker.evaluate({'extra':'ocr'})}):
    datas += copy_metadata(name)

analysis = Analysis([str(root / 'clinical_extractor' / 'macos_entry.py')], pathex=[str(root)],
                    binaries=binaries, datas=datas, hiddenimports=hiddenimports,
                    excludes=['pytest', 'paddleocr'], noarchive=False)
pyz = PYZ(analysis.pure)
exe = EXE(pyz, analysis.scripts, [], exclude_binaries=True, name='ClinicalExtractor',
          console=False, target_arch='arm64', codesign_identity=identity,
          entitlements_file=str(root / 'scripts' / 'macos-entitlements.plist'))
collection = COLLECT(exe, analysis.binaries, analysis.datas, name='ClinicalExtractor',
                     target_arch='arm64', codesign_identity=identity,
                     entitlements_file=str(root / 'scripts' / 'macos-entitlements.plist'))
app = BUNDLE(collection, name='ClinicalExtractor.app', icon=str(work / 'ClinicalExtractor.icns'),
             bundle_identifier='org.clinicalextractor.desktop', codesign_identity=identity,
             entitlements_file=str(root / 'scripts' / 'macos-entitlements.plist'),
             info_plist={'CFBundleShortVersionString':version, 'CFBundleVersion':version,
                         'NSHighResolutionCapable':True, 'LSUIElement':True,
                         'LSMinimumSystemVersion':os.environ.get('MACOSX_DEPLOYMENT_TARGET', platform.mac_ver()[0])})
