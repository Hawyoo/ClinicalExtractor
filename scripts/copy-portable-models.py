"""Copy only the configured OCR and fallback table models into a new build."""
from pathlib import Path
import shutil
import sys

ROOT=Path(__file__).resolve().parent.parent
sys.path.insert(0,str(ROOT))
from clinical_extractor.parser import lightweight_pipeline_config


def required_models():
    config=lightweight_pipeline_config(True)
    ocr=config['SubPipelines']['GeneralOCR']['SubModules']
    return [module['model_name'] for module in ocr.values()]+[
        config['SubModules']['TableStructureRecognition']['model_name']]


def copy_models(source: Path, destination: Path):
    names=required_models()
    unexpected=[p.name for p in destination.iterdir() if p.is_dir() and p.name not in names] if destination.exists() else []
    if unexpected:
        raise RuntimeError('Destination contains old models; create a fresh portable build first: '+', '.join(unexpected))
    for name in names:
        folder=source/name
        if not folder.is_dir() or not (folder/'inference.pdiparams').is_file():
            raise RuntimeError(f'Required offline model missing or incomplete: {name}')
    destination.mkdir(parents=True,exist_ok=True)
    for name in names:
        shutil.copytree(source/name,destination/name,dirs_exist_ok=True)
    return names


if __name__=='__main__':
    import argparse
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('source',type=Path)
    parser.add_argument('destination',type=Path)
    args=parser.parse_args()
    names=copy_models(args.source,args.destination)
    print('Offline models copied: '+', '.join(names))
