"""Parse user-edited table text without asking a model to generate result cells."""
import re
from html import escape
from .parser import TableBlock
from .table_extractor import HEADER_ALIASES, _find_col, _result_col


def edited_table(text):
    rows=[]
    for line in str(text).splitlines():
        if not line.strip():
            continue
        if '\t' in line:
            cells=line.split('\t')
        elif '|' in line:
            line=line.strip()
            if line.startswith('|') and line.endswith('|'):
                line=line[1:-1]
            cells=line.split('|')
        else:
            cells=re.split(r' {2,}',line.strip())
        cells=[cell.strip() for cell in cells]
        if cells and all(re.fullmatch(r'[:\- ]*',cell) for cell in cells):
            continue
        rows.append(cells)
    header=next((index for index,row in enumerate(rows)
                 if _find_col(row,HEADER_ALIASES['item']) is not None and _result_col(row) is not None),None)
    if header is None:
        raise ValueError('请保留“项目名称、结果”等表头，并用 Tab 或竖线 | 分隔各列；不能从项目名单猜测数值。')
    rows=rows[header:]
    html='<table>'+''.join('<tr>'+''.join('<td>'+escape(cell)+'</td>' for cell in row)+'</tr>' for row in rows)+'</table>'
    return TableBlock(page=None,html=html,rows=rows)
