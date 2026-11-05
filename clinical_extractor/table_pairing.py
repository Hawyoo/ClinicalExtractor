"""AI may move existing OCR cells by ID; it cannot supply replacement numbers."""
from copy import deepcopy
from collections import Counter
from statistics import median
import json
import re

from .jobs import emit
from .report_templates import _key, _name_parts, _ambiguous_reference, table_templates, _candidate, _range_pair
from .table_extractor import is_column_header, _split_reference, _value_num

NUMBER = r'[<>≤≥]?\s*[+-]?\d+(?:\.\d+)?(?:[eE][+-]?\d+)?'
RANGE = r'[<>≤≥]=?\s*\d+(?:\.\d+)?|\d+(?:\.\d+)?\s*[-~～—–至]\s*\d+(?:\.\d+)?'


def same_row_token(anchor, pool, items, gap):
    """A cell must belong uniquely to this physical row, not just a neighbor."""
    hits=[]
    for token in pool:
        distance=abs(token['y']-anchor['y'])
        others=[abs(token['y']-item['y']) for item in items if item['id']!=anchor['id']]
        if distance<=gap*.45 and (not others or min(others)-distance>=gap*.2):
            hits.append(token)
    return hits[0] if len(hits)==1 else None


def reference_fits_row(token, anchor, items, gap, definition):
    if _ambiguous_reference(token.get('original_text','')):
        # Several intervals share one OCR box: geometry cannot distinguish its
        # fragments. Require an identity-matched template interval as well.
        if definition is None:return False
        allowed=[_range_pair(r) for r in [definition.get('reference_range',''),*definition.get('alternative_reference_ranges',[])]]
        return _range_pair(token['text']) in [r for r in allowed if r is not None]
    return same_row_token(anchor,[token],items,gap) is not None


def restore_invalid_pairing(record, pages):
    """Recover an unreviewed AI change only when its own audit and pixels agree.

    Never overwrite reviewed results or subsequent manual edits. The rejected
    assignment remains in the payload for traceability.
    """
    row=deepcopy(record)
    payload=row.get('payload_json') or {}
    if isinstance(payload,str):payload=json.loads(payload)
    audit=payload.get('ai_pairing')
    if row.get('reviewed') or not isinstance(audit,dict):return None
    before,after=audit.get('before',{}),audit.get('after',{})
    if (str(row.get('value',''))!=str(after.get('value','')) or
            str(payload.get('reference_raw',''))!=str(after.get('reference',''))):return None
    source=audit.get('value_source') or {}
    for page in pages:
        if row.get('page') not in (page.get('page_index'),None):continue
        items,values,_=sources(page)
        anchors=[t for t in items if _key(_name_parts(t['text'])[0])==_key(_name_parts(row.get('item_original',''))[0])]
        if len(anchors)!=1:continue
        centers=sorted(t['y'] for t in items)
        gaps=[b-a for a,b in zip(centers,centers[1:]) if b>a]
        if not gaps:continue
        reliable=same_row_token(anchors[0],values,items,median(gaps))
        claimed=[v for v in values if v['id']==source.get('id') and v['box']==source.get('box') and v['text']==source.get('text')]
        if (reliable is None or not claimed or reliable['id']==claimed[0]['id']
                or reliable['text']!=str(before.get('value',''))):continue
        row['value']=reliable['text'];row['value_num']=_value_num(row['value'])
        ref=str(before.get('reference',''))
        payload['reference_raw']=ref
        row['reference_low'],row['reference_high']=_split_reference(ref)
        row['evidence']=str(before.get('evidence') or row.get('evidence',''))
        payload['rejected_ai_pairing']=payload.pop('ai_pairing')
        payload['ai_review_warning']='已撤回与原图行位置冲突的AI配对，恢复调整前的OCR结果，请核对'
        payload.pop('template_warning',None)
        if not _ambiguous_reference(ref):payload.pop('reference_warning',None)
        row['payload_json']=payload
        return row
    return None


def sources(page):
    ocr = page.get('overall_ocr_res') or {}
    entries = [(str(t).strip(),list(map(float,b))) for t,b in zip(ocr.get('rec_texts',[]),ocr.get('rec_boxes',[])) if str(t).strip()]
    groups=[]
    for text,box in entries:
        if not is_column_header(text,'item'):continue
        near=[(t,b) for t,b in entries if abs((b[1]+b[3]-box[1]-box[3])/2)<max(1,box[3]-box[1])*1.5]
        columns=[]
        for role in ('item','value','reference','unit'):
            hits=[(t,b) for t,b in near if is_column_header(t,role)]
            if len(hits)==1:columns.append((role,hits[0][1]))
        if {'item','value'}.issubset({r for r,_ in columns}):
            for t,b in near:
                if any(w in t.casefold() for w in ('历史','既往','上次','history','previous','异常','标志')):columns.append(('ignore',b))
            groups.append(columns)
    if len(groups)!=1:return [],[],[]
    columns=sorted(groups[0],key=lambda c:c[1][0])
    boundaries=[(a[1][0]+b[1][0])/2 for a,b in zip(columns,columns[1:])]
    item_header=next(b for r,b in columns if r=='item')
    heights=[b[3]-b[1] for _,b in entries if b[3]>b[1]]
    typical_height=median(heights) if heights else 1
    items,values,refs=[],[],[]
    for index,(text,box) in enumerate(entries):
        column=sum((box[0]+box[2])/2>x for x in boundaries)
        role,header=columns[column]
        if (box[1]+box[3])/2<=header[3]:continue
        if box[3]-box[1]>=typical_height*1.8:continue
        y=(item_header[1]+item_header[3])/2+(box[1]+box[3]-header[1]-header[3])/2
        token=dict(id=str(index),text=text,box=box,y=y)
        if role=='item' and re.search('[A-Za-z\u4e00-\u9fff]',text):items.append(token)
        elif role=='value' and re.fullmatch(NUMBER+r'\s*[↑↓]?',text):
            token['text']=text.replace('↑','').replace('↓','').strip();values.append(token)
        elif role=='reference':
            for j,match in enumerate(re.finditer(RANGE,text)):
                refs.append(dict(token,id=f'{index}:{j}',text=match[0],span=list(match.span()),original_text=text))
    return items,values,refs


def repair_pairings(records, pages, template_id='all'):
    from .config import load_settings
    settings=load_settings()
    if settings.mock_mode:return records
    output=deepcopy(records)
    model=None
    definitions=table_templates().get(template_id,{}).get('items',[])
    for page in pages:
        items,values,refs=sources(page)
        if len(items)<2 or not values:continue
        items.sort(key=lambda t:t['y'])
        gaps=[b['y']-a['y'] for a,b in zip(items,items[1:]) if b['y']>a['y']]
        if not gaps:continue
        gap=median(gaps)
        page_no=page.get('page_index')
        anchors={}
        for i,row in enumerate(output):
            if row.get('page') not in (page_no,None):continue
            name=_key(_name_parts(row.get('item_original',''))[0])
            hits=[t for t in items if _key(_name_parts(t['text'])[0])==name]
            if len(hits)==1:anchors[i]=hits[0]
        if not anchors:continue
        ordered=sorted(anchors,key=lambda i:anchors[i]['y'])
        identities={}
        for i in ordered:
            identity=dict(output[i],reference_low='',reference_high='',payload_json={})
            choices=sorted((c for t in definitions if (c:=_candidate(identity,t)) is not None),key=lambda c:c['score'],reverse=True)
            if choices and (len(choices)==1 or choices[0]['score']-choices[1]['score']>=.1):
                identities[i]=choices[0]['item']
        reliable_values={i:same_row_token(anchors[i],values,items,gap) for i in ordered}
        suspect=set()
        warning_values={str(w.get('value','')) for w in page.get('row_warnings',[])}
        for pos,i in enumerate(ordered):
            row=output[i];payload=row.get('payload_json') or {}
            matches=[v for v in values if v['text']==str(row.get('value',''))]
            displaced=matches and min(abs(v['y']-anchors[i]['y']) for v in matches)>gap*.55
            ref=payload.get('reference_raw','')
            nearby_ref=any(abs(t['y']-anchors[i]['y'])<gap*.55 for t in refs)
            if displaced or str(row.get('value','')) in warning_values or _ambiguous_reference(ref) or (not ref and nearby_ref):
                suspect.update(ordered[max(0,pos-1):pos+2])
        # Keep prompts local. An unmodified row outside each group reserves its cells.
        selected=sorted(suspect,key=lambda i:anchors[i]['y'])
        for start in range(0,len(selected),8):
            group=selected[start:start+8]
            if not group:continue
            reserved_values=set();reserved_refs=set()
            for i in ordered:
                if i in group:continue
                for pool,field,reserved in [(values,str(output[i].get('value','')),reserved_values),
                    (refs,str((output[i].get('payload_json') or {}).get('reference_raw','')),reserved_refs)]:
                    hits=[t for t in pool if t['text']==field and abs(t['y']-anchors[i]['y'])<gap*.55]
                    if len(hits)==1:reserved.add(hits[0]['id'])
            low=min(anchors[i]['y'] for i in group)-gap*.55
            high=max(anchors[i]['y'] for i in group)+gap*.55
            vp={v['id']:v for v in values if low<=v['y']<=high and v['id'] not in reserved_values}
            rp={r['id']:r for r in refs if low<=r['y']<=high and r['id'] not in reserved_refs}
            if not vp:continue
            if model is None:
                from .text_extractor import _progress_model
                model=_progress_model(settings)
            request=dict(rows=[dict(row_id=str(i),name=output[i]['item_original'],box=anchors[i]['box'],
                                   locked_value_id=reliable_values[i]['id'] if reliable_values[i] else None,
                                   current_value=output[i].get('value',''),current_reference=(output[i].get('payload_json') or {}).get('reference_raw','')) for i in group],
                         value_cells=list(vp.values()),reference_cells=list(rp.values()),
                         templates=[t for t in definitions
                                    if any(_candidate(output[i],t) is not None for i in group)])
            prompt=('仅配对本张图片已有OCR文字框，不重新识别，不生成或修改文字、数字。'
                    'locked_value_id是原图中清晰属于该行的结果，不能更换。'
                    '结合原图坐标、项目名、单位与参考范围交叉核验；量级严重冲突时重新核对来源，不能主观跨行分配。'
                    '同一原图行的异常结果也必须保留，不能为了落入正常范围换行。'
                    '每个来源ID最多使用一次；不确定则不返回该行。value_id只能选value_cells，reference_id只能选reference_cells或null。'
                    '只返回JSON：{"matches":[{"row_id":"行ID","value_id":"来源ID","reference_id":null}]}。\n'+json.dumps(request,ensure_ascii=False))
            emit('AI 正在核对疑似错位的结果与参考区间')
            try:
                batches=list(model.infer([prompt]));raw=batches[0][0].output
                matches=json.loads(re.sub(r'^```(?:json)?\s*|\s*```$','',str(raw).strip(),flags=re.I)).get('matches',[])
                if not isinstance(matches,list):continue
                proposals={};used_v=set();used_r=set();invalid=False
                for match in matches:
                    if not isinstance(match,dict) or set(match)!={'row_id','value_id','reference_id'}:invalid=True;break
                    i=int(match['row_id']);vid=match['value_id'];rid=match['reference_id']
                    if i not in group or i in proposals or vid not in vp or vid in used_v or (rid is not None and (rid not in rp or rid in used_r)):
                        invalid=True;break
                    if abs(vp[vid]['y']-anchors[i]['y'])>gap*1.5 or (rid is not None and abs(rp[rid]['y']-anchors[i]['y'])>gap*1.5):invalid=True;break
                    locked=reliable_values[i]
                    if ((locked is not None and vid!=locked['id']) or
                            (locked is None and vp[vid]['text']!=str(output[i].get('value',''))) or
                            (rid is not None and not reference_fits_row(rp[rid],anchors[i],items,gap,identities.get(i)))):
                        output[i].setdefault('payload_json',{})['ai_review_warning']='AI建议与原图行位置或参考范围依据不符，已拒绝调整并保留OCR原结果'
                        invalid=True;break
                    proposals[i]=(vp[vid],rp.get(rid));used_v.add(vid)
                    if rid is not None:used_r.add(rid)
                if invalid:continue
                # Unreturned rows also reserve their existing result/reference cells.
                untouched=[i for i in group if i not in proposals]
                if any(any(t['id'] in used_v and t['text']==str(output[i].get('value','')) and abs(t['y']-anchors[i]['y'])<gap*.55 for t in values) or
                       any(t['id'] in used_r and t['text']==(output[i].get('payload_json') or {}).get('reference_raw','') and abs(t['y']-anchors[i]['y'])<gap*.55 for t in refs) for i in untouched):continue
                claimed_refs=Counter()
                for i in group:
                    chosen=proposals.get(i)
                    if chosen and chosen[1] is not None:
                        claimed_refs[chosen[1]['id']]+=1
                    else:
                        old=str((output[i].get('payload_json') or {}).get('reference_raw',''))
                        for token in refs:
                            if token['text'] in old and abs(token['y']-anchors[i]['y'])<gap*.55:
                                claimed_refs[token['id']]+=1
                if any(count>1 for count in claimed_refs.values()):continue
                after=Counter(str(proposals[i][0]['text'] if i in proposals else output[i].get('value','')) for i in ordered)
                if after-Counter(v['text'] for v in values):continue
                for i,(value,ref) in proposals.items():
                    row=output[i];payload=row.setdefault('payload_json',{})
                    old_value=str(row.get('value',''));old_ref=str(payload.get('reference_raw',''))
                    new_ref=ref['text'] if ref is not None else old_ref
                    if value['text']==old_value and new_ref==old_ref:continue
                    before=dict(value=old_value,reference=old_ref,evidence=row.get('evidence',''))
                    row['value']=value['text'];row['value_num']=_value_num(value['text'])
                    payload['reference_raw']=new_ref
                    row['reference_low'],row['reference_high']=_split_reference(new_ref)
                    row['abnormal_flag']=''
                    payload.pop('reference_warning',None)
                    payload['ai_pairing']=dict(before=before,after=dict(value=value['text'],reference=new_ref),value_source=value,reference_source=ref)
                    row['evidence']=f"{row['item_original']} | {value['text']} | {new_ref} | {row.get('unit','')}"
            except (ValueError,TypeError,KeyError,IndexError,AttributeError):
                continue
    return output
