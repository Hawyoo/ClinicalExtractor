"""Portable UI preferences independent of browser profile, origin and port."""
import json
import os
import tempfile
from threading import RLock
from .config import DATA_DIR

PREFERENCES_PATH = DATA_DIR / 'ui_preferences.json'
_lock=RLock()
ALLOWED={'theme':{'light','dark'},'report_sort':{'status','added'}}


def load_preferences():
    with _lock:
        try:
            raw=json.loads(PREFERENCES_PATH.read_text(encoding='utf-8'))
        except (FileNotFoundError,ValueError):
            raw={}
        return {key:raw.get(key) if isinstance(raw,dict) and isinstance(raw.get(key),str) and raw.get(key) in values else None
                for key,values in ALLOWED.items()}


def save_preferences(patch):
    if any(key not in ALLOWED or value not in ALLOWED[key] for key,value in patch.items()):
        raise ValueError('无效的界面设置')
    with _lock:
        current=load_preferences()
        current.update(patch)
        PREFERENCES_PATH.parent.mkdir(parents=True,exist_ok=True)
        fd,name=tempfile.mkstemp(prefix='.ui-preferences-',suffix='.tmp',dir=PREFERENCES_PATH.parent)
        try:
            with os.fdopen(fd,'w',encoding='utf-8') as out:
                json.dump(current,out,ensure_ascii=False,indent=2)
                out.flush();os.fsync(out.fileno())
            os.replace(name,PREFERENCES_PATH)
        finally:
            if os.path.exists(name):os.unlink(name)
        return current
