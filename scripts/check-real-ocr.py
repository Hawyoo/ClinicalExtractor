"""Read-only smoke test of actual OCR, without modifying report records."""
from pathlib import Path
import sys
import json
import time

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from clinical_extractor.parser import PPStructureParser

if __name__ == "__main__":
    import argparse
    args = argparse.ArgumentParser()
    args.add_argument('image')
    args.add_argument('--isolated', action='store_true')
    args.add_argument('--repeat', type=int, default=1)
    args.add_argument('--text-only', action='store_true')
    args.add_argument('--output', help='Optional JSON snapshot for local inspection')
    args.add_argument('--cpu-threads', type=int, help='Read-only standalone benchmark thread count')
    args.add_argument('--mkldnn', action='store_true', help='Retry oneDNN in this standalone test process')
    opts = args.parse_args()
    from clinical_extractor.ocr_process import OCR_PARSER
    if opts.isolated and (opts.cpu_threads or opts.mkldnn):
        args.error('Benchmark options use standalone mode, which already runs in a separate process')
    parser = OCR_PARSER if opts.isolated else PPStructureParser(cpu_threads=opts.cpu_threads, enable_mkldnn=opts.mkldnn)
    try:
        for index in range(opts.repeat):
            started = time.perf_counter()
            document = parser.parse(opts.image, table_mode=not opts.text_only)
            from clinical_extractor.table_extractor import extract_table_rows
            count = sum(len(extract_table_rows(table)) for table in document.tables)
            print(f"OCR_OK run={index+1} seconds={time.perf_counter()-started:.1f} characters={len(document.raw_text)} tables={len(document.tables)} result_rows={count}", flush=True)
            if opts.output:
                Path(opts.output).write_text(json.dumps(document.parser_json, ensure_ascii=False, indent=2), encoding='utf-8')
            if not document.raw_text.strip():
                raise RuntimeError("Actual image produced empty OCR text")
    finally:
        OCR_PARSER.close()
