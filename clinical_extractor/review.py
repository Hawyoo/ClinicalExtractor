"""Presentation-only triage of extraction corrections and unresolved checks."""
import json


def attention_for(item):
    try:
        payload = item.get('payload_json') or {}
        if isinstance(payload, str):
            payload = json.loads(payload)
        if not isinstance(payload, dict):
            raise ValueError('invalid audit data')
    except (ValueError, TypeError):
        payload = {'template_warning': '校正记录无法读取，请核对原文'}
    warnings = [str(payload[key]).strip() for key in
                ('ai_review_warning', 'unit_warning', 'template_warning', 'reference_warning')
                if payload.get(key) and str(payload[key]).strip()]
    checks = payload.get('warnings') or []
    warnings.extend([str(w) for w in checks] if isinstance(checks, list) else [str(checks)])
    # Free-form model explanations can contradict the validated template match.
    # Show the actual correction and deterministic matching evidence instead.
    corrections = [str(payload[key]).strip() for key in
                   ('item_correction',)
                   if payload.get(key) and str(payload[key]).strip()]
    if corrections and payload.get('template_match') and payload.get('template_alignment'):
        corrections.append(str(payload['template_alignment']))
    pairing = payload.get('ai_pairing')
    if isinstance(pairing,dict):
        before,after=pairing.get('before',{}),pairing.get('after',{})
        corrections.append(f"AI配对调整：结果 {before.get('value','')} → {after.get('value','')}；参考区间 {before.get('reference','')} → {after.get('reference','')}")
        warnings.insert(0,'AI调整过原文对应关系，请对照原图确认')
    warnings = list(dict.fromkeys(warnings))
    corrections = list(dict.fromkeys(corrections))
    return dict(visible=bool(warnings or corrections), priority=-1 if pairing else 0 if warnings else 1, pairing=bool(pairing),
                warnings=warnings, corrections=corrections,
                label='AI重新配对' if pairing else ('待核对 · 已纠错' if corrections else '待核对') if warnings else '智能纠错')
