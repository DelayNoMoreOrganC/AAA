"""Read-only review guidance; suggestions never mutate a saved document."""
import math
import re
import os


def guidance(unit, analysis, options):
    title = str(getattr(unit, 'title', '') or '')
    kind = unit.doc_type
    score = getattr(unit, 'confidence', None)
    score = score if type(score) in (int, float) and math.isfinite(score) and 0 <= score <= 1 else None
    uncertain = any(str(r.get('doc_id')) == str(unit.doc_id) for r in analysis.low_confidence_items or [])
    reviews = (analysis.fields or {}).get('_visual_classification_review')
    reviews = reviews if isinstance(reviews, list) else []
    verified = any(isinstance(r, dict)
                   and (r.get('independent_title_verified') is True or r.get('independent_context_verified') is True)
                   and r.get('effective_doc_type') == kind
                   and r.get('page') == unit.start_page + 1
                   and os.path.normcase(str(r.get('source_path'))) == os.path.normcase(str(unit.source_path))
                   for r in reviews)
    direct = any(o['doc_type'] == kind and o['catalog_seq'] == unit.catalog_seq for o in options) and kind != 'unknown'
    human = unit.manual_catalog_seq is not None
    tier = 'confirmed' if human or (direct and verified and not uncertain and score is not None and score >= .8) else (
        'suggested' if direct and not uncertain and score is not None and score >= .8 else 'pending')
    hints = []
    if re.search('律师事务所函', title): hints = ['firm_letter']
    elif re.search('受理.*通知|通知.*受理', title): hints = ['execution'] if '执行' in title else ['acceptance_notice']
    elif re.search('传票|开庭|出庭', title): hints = ['summons']
    elif re.search('裁定', title): hints = ['execution'] if '执行' in title else ['preservation', 'ruling'] if '保全' in title else ['ruling', 'preservation']
    elif re.search('工作报告|办理报告', title): hints = ['agent_opinion', 'evidence']
    if kind not in ('unknown', 'other') and kind not in hints: hints.append(kind)
    if tier == 'pending': hints.append('unknown')
    suggestions = []
    for hint in dict.fromkeys(hints):
        option = next((o for o in options if o['doc_type'] == hint), None)
        if option:
            suggestions.append(dict(option, reason='根据原文核对后选择：' + option['label']))
    return dict(title=title, match_score=score, score_is_probability=False,
                match_tier=tier, suggestions=suggestions[:3])
