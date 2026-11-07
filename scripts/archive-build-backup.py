"""Keep restored build backups recoverable under the project DELETE directory."""
from pathlib import Path
import json
from uuid import uuid4

root=Path(__file__).resolve().parent.parent
source=(root/'.portable-data-backup').resolve()
target=(root/'DELETE'/('portable-data-backup-'+uuid4().hex[:8])).resolve()
if source.parent!=root or root not in target.parents:
    raise RuntimeError('Build backup path is outside the project')
if source.exists():
    target.parent.mkdir(parents=True,exist_ok=True)
    source.rename(target)
    (target/'archive-manifest.json').write_text(json.dumps({'original':str(source),'reason':'Restored portable data backup'},indent=2),encoding='utf-8')
