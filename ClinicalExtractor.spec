from pathlib import Path
from importlib.metadata import requires
from packaging.requirements import Requirement

from PyInstaller.utils.hooks import collect_all, copy_metadata


root = Path(SPECPATH)
datas = [
    (str(root / "templates"), "templates"),
    (str(root / "static"), "static"),
    (str(root / "profiles"), "profiles"),
]
binaries, hiddenimports = [], []
for package in ("paddle", "paddlex", "langextract"):
    package_datas, package_binaries, package_hidden = collect_all(package)
    datas += package_datas
    binaries += package_binaries
    hiddenimports += package_hidden
ocr_dependencies = {Requirement(item).name for item in requires('paddlex')
                    if Requirement(item).marker is None or Requirement(item).marker.evaluate({'extra':'ocr'})}
for distribution in sorted(ocr_dependencies):
    datas += copy_metadata(distribution)

a = Analysis([str(root / "clinical_extractor" / "native_entry.py")], pathex=[str(root)], binaries=binaries, datas=datas, hiddenimports=hiddenimports, excludes=["pytest", "paddleocr"], noarchive=False)
pyz = PYZ(a.pure)
exe = EXE(pyz, a.scripts, [], exclude_binaries=True, name="ClinicalExtractor", console=False, icon=str(root / "static" / "clinical-extractor.ico"))
coll = COLLECT(exe, a.binaries, a.datas, name="ClinicalExtractor")
