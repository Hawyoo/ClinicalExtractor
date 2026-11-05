"""Read-only CPU benchmark; each configuration has its own native process."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import time
import requests

ROOT=Path(__file__).resolve().parent.parent
sys.path.insert(0,str(ROOT))


def application_busy():
    try:
        data=requests.get('http://127.0.0.1:8765/jobs',timeout=1).json()
        return any(j['state'] in ('queued','running') for j in data.get('jobs',[]))
    except (requests.RequestException,ValueError):
        return False


def stop_test_process(process):
    if os.name=='nt':
        subprocess.run(['taskkill','/PID',str(process.pid),'/T','/F'],capture_output=True)
    else:
        process.kill()
    process.communicate()


def worker(args):
    from clinical_extractor.parser import PPStructureParser
    from clinical_extractor.table_extractor import extract_table_rows
    parser=PPStructureParser(cpu_threads=args.worker)
    start=time.perf_counter()
    parser._get_pipeline(True)
    output={'threads':args.worker,'load_seconds':round(time.perf_counter()-start,2),'runs':[]}
    for image in args.images:
        for repeat in range(args.repeat):
            start=time.perf_counter()
            document=parser.parse(image)
            rows=[r for t in document.tables for r in extract_table_rows(t)]
            signature=[(r['item_original'],r['value'],r['unit']) for r in rows]
            output['runs'].append(dict(image=Path(image).name,repeat=repeat+1,
                seconds=round(time.perf_counter()-start,2),rows=len(rows),
                pipelines=[p.get('ocr_pipeline') for p in document.parser_json],
                stage_timings=[p.get('stage_timings',{}) for p in document.parser_json],
                digest=hashlib.sha256(json.dumps(signature,ensure_ascii=False).encode()).hexdigest()))
            Path(args.output).write_text(json.dumps(output,ensure_ascii=False,indent=2),encoding='utf-8')
    Path(args.output).write_text(json.dumps(output,ensure_ascii=False,indent=2),encoding='utf-8')


def main():
    cli=argparse.ArgumentParser()
    cli.add_argument('images',nargs='+')
    cli.add_argument('--threads',type=int,nargs='+',default=[2,4,6,11])
    cli.add_argument('--repeat',type=int,default=2)
    cli.add_argument('--worker',type=int)
    cli.add_argument('--output',required=True)
    args=cli.parse_args()
    if args.repeat<1 or any(t<1 for t in args.threads) or (args.worker is not None and args.worker<1):
        cli.error('threads and repeat must be positive')
    if args.worker is not None:
        worker(args)
        return
    directory=Path(args.output)
    directory.mkdir(parents=True,exist_ok=True)
    env=dict(os.environ,PYTHONDONTWRITEBYTECODE='1',PADDLE_PDX_DISABLE_MODEL_SOURCE_CHECK='True',
             PADDLE_PDX_CACHE_HOME=str(ROOT/'.portable-model-cache'))
    summaries=[]
    for threads in args.threads:
        output=directory/f'threads-{threads}.json'
        command=[sys.executable,__file__,*args.images,'--worker',str(threads),
                 '--repeat',str(args.repeat),'--output',str(output)]
        while True:
            announced=False
            while application_busy():
                if not announced:
                    print('WAITING: application OCR/AI queue is active',flush=True)
                    announced=True
                time.sleep(1)
            print(f'TESTING threads={threads}',flush=True)
            process=subprocess.Popen(command,env=env,stdout=subprocess.PIPE,stderr=subprocess.PIPE)
            started=time.monotonic()
            interrupted=False
            while True:
                try:
                    stdout,stderr=process.communicate(timeout=1)
                    break
                except subprocess.TimeoutExpired:
                    if application_busy():
                        stop_test_process(process)
                        interrupted=True
                        print('DEFERRED: application received a processing task',flush=True)
                        break
                    if time.monotonic()-started>480:
                        stop_test_process(process)
                        stdout,stderr=b'',b'benchmark timeout'
                        break
            if interrupted:
                continue
            (directory/f'threads-{threads}.log').write_bytes(stdout+stderr)
            if process.returncode or not output.exists():
                summaries.append(dict(threads=threads,error=f'exit {process.returncode}'))
                print(f'FAILED threads={threads} exit={process.returncode}',flush=True)
            else:
                summary=json.loads(output.read_text(encoding='utf-8'))
                summaries.append(summary)
                print('RESULT '+json.dumps(summary,ensure_ascii=True),flush=True)
            break
        (directory/'summary.json').write_text(json.dumps(summaries,ensure_ascii=False,indent=2),encoding='utf-8')


if __name__=='__main__':
    main()
