import importlib.util
from pathlib import Path

import pytest

spec=importlib.util.spec_from_file_location('copy_portable_models',Path(__file__).resolve().parents[1]/'scripts'/'copy-portable-models.py')
module=importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


def test_packaging_only_copies_models_used_by_runtime(tmp_path):
    names=module.required_models()
    assert set(names)=={'PP-OCRv5_server_det','PP-OCRv5_server_rec','SLANet_plus'}
    source=tmp_path/'cache';destination=tmp_path/'portable'
    for name in [*names,'SLANeXt_wired','PP-DocLayout_plus-L']:
        folder=source/name;folder.mkdir(parents=True)
        (folder/'inference.pdiparams').write_bytes(name.encode())
    module.copy_models(source,destination)
    assert {p.name for p in destination.iterdir()}==set(names)
    for name in names:
        assert (destination/name/'inference.pdiparams').read_bytes()==name.encode()
    assert (source/'SLANeXt_wired').exists()


def test_incomplete_cache_fails_before_creating_a_partial_portable(tmp_path):
    with pytest.raises(RuntimeError,match='missing or incomplete'):
        module.copy_models(tmp_path/'missing',tmp_path/'portable')
    assert not (tmp_path/'portable').exists()
