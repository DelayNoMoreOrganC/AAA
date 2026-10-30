"""Export the values actually mapped into original forms and their current sources.

No extraction, model calls, field edits or approval decisions. A blank is not
evidence that the user failed to provide a document.
"""
import html
import os
import re

from .analysis_snapshot import SYSTEM_TEMPLATE_NAMES
from .preview_fields import build_preview
from .original_template_service import SLOTS, _selected


BLANK_REASONS = {
    "立案审批日期": "未取得本案委托代理合同明确签订日期或日期有冲突；请补填，仅用于本审批表。",
    "合同号": "尚未取得委托合同编号；借款合同编号不能替代。",
    "委托人电话": "尚未取得明确归属委托人的电话；不能采用代理律师电话。",
    "传真": "尚未取得明确归属委托人的传真。",
    "收案日期": "须有律所收案记录；法院立案日期不能替代。",
    "结案日期": "须有律所结案记录；执行完毕不能推定内部结案日期。",
    "归档日期": "须有实际归档日期；不以草稿生成日期替代。",
    "立卷人": "尚未指定本次立卷人。",
    "档案号": "尚未取得律所分配的档案编号。",
    "保存期限": "尚未取得本卷适用且经核验的保存期限。",
    "委托人对服务质量意见": "须依据客户实际反馈，不由模型代评。",
    "应收业务费": "须有完整收费、结算依据；判决律师费损失不能替代。",
    "已收业务费": "须有实际收款依据；执行完毕不等于律师费到账。",
    "尚欠业务费": "尚无足够的应收、实收和结算依据计算欠费。",
    "应退业务费": "尚无退款或完整结算依据，不按空白推定为零。",
}
LABELS = {"source_supported": "原文支持", "derived_draft": "材料摘要",
          "convention_default": "律所约定默认值（仅审批表）",
          "human_confirmed": "人工填写或确认", "configured": "案件设置",
          "conflict": "存在冲突", "unverified": "依据待核验", "missing": "留空"}

GAP_LABELS = {
    'filled':'已有内容', 'human_blank':'人工保留空白', 'human_record':'实际签署或反馈',
    'configuration':'律所设置', 'output_pending':'出卷时计算', 'conflict':'集中核对来源冲突',
    'source_candidate_not_applied':'已有依据，系统待补填',
    'generation_pending':'综合撰写待完成', 'source_review_needed':'已有候选，系统待核查',
    'policy_review_needed':'填写规则已更新，旧内容待复核',
    'not_found_in_read_material':'已读材料暂未取得',
    'intentional_blank':'按约定留空', 'optional_blank':'不确定则留空',
}

def gap_diagnosis(row, fields, manifest):
    """Distinguish a mapping/extraction defect from a request for more material.

    A retained candidate is not automatically trusted. Test the same source
    assurance as actual filling; never adopt a candidate or overwrite a human.
    """
    output_policy=row.get('output_policy') or {}
    if output_policy.get('code') in ('intentional_blank','optional_blank'):
        code=output_policy['code']
        return {'code':code,'label':GAP_LABELS[code],'action':'retain'}
    from ..core.v4_bridge import load
    from .field_assurance import field_assurance
    policy=load('form_field_policy');key=policy.ALIASES.get(row['field'],row['field'])
    rule=policy.policy(key);mode=rule[0] if rule else None
    status=row['status'];value=row.get('value')
    if status=='conflict':code='conflict'
    elif value:code='filled'
    elif status=='human_confirmed':code='human_blank'
    elif mode=='human' or status=='manual_area':code='human_record'
    elif mode=='configured':code='configuration'
    elif mode=='system' or key=='卷内页数':code='output_pending'
    else:
        refs=(fields.get('_provenance') or {}).get(key) or []
        refs=[refs] if isinstance(refs,dict) else refs
        candidate=False
        for ref in refs:
            if not isinstance(ref,dict) or not ref.get('value') or ref.get('method')=='human':continue
            candidate=True
            probe=dict(fields,**{key:ref['value']})
            check=field_assurance(key,ref['value'],probe,source_manifest=manifest)
            if check['status']=='source_supported':
                return {'code':'source_candidate_not_applied','label':GAP_LABELS['source_candidate_not_applied'],
                        'action':'repair_before_requesting_material','anchors':check['anchors']}
        generation=(fields.get('_form_synthesis_status') or {}).get('fields',{}).get(key)
        if generation=='policy_review_required':code='policy_review_needed'
        elif generation and generation!='generated':code='generation_pending'
        elif candidate:code='source_review_needed'
        else:code='not_found_in_read_material'
    return {'code':code,'label':GAP_LABELS[code], 'action':
        'system_review_first' if code in ('generation_pending','source_review_needed','not_found_in_read_material','policy_review_needed')
        else 'retain' if code in ('filled','human_blank') else 'single_consolidated_review'}


def build_form_fill_audit(fields, manifest, *, issues=(), derived_output=None):
    fields, derived_output = fields or {}, derived_output or {}
    filenames = {row.get("file_id"): row.get("filename", "原材料") for row in manifest or []}
    rows = []
    for template in SYSTEM_TEMPLATE_NAMES:
        from .source_forms import form_fields_preserved
        if form_fields_preserved(fields,template):
            continue  # Original source is audited as a document, not an empty generated form.
        selected = _selected(template, fields)
        specs = {entry["key"]: entry for entry in build_preview(template, fields,
            source_manifest=manifest, issues=issues)["fields"]}
        slots = SLOTS.get(selected, [])
        if template == "送达材料清单":
            # These fields occupy paragraphs / repeated name rows in the
            # original form, rather than the ordinary fixed-cell map.
            slots = [(key, None, None, 0, "") for key in specs]
        for key, row, cell, *_ in slots:
            if key == "__volume_pages":
                count = derived_output.get("volume_page_count")
                value = f"{count} 页" if type(count) is int and count > 0 else ""
                entry = {"key": "卷内页数", "label": "卷内页数", "value": value,
                         "assurance": {"status": "output_measurement", "anchors": []}}
            else:
                entry = specs[key]
                value = str(entry["value"] or "")
            saved_value = value
            if isinstance(entry.get('display_value'), str):
                value = entry['display_value']
            if template == "送达材料清单" and key == "法院文件清单":
                value = "\n".join(re.sub(r"（原材料第[0-9—\-]+页）$", "", line.strip())
                                  for line in value.splitlines() if line.strip())
            assurance = entry["assurance"]
            status = assurance["status"]
            reason = ""
            if isinstance(entry.get('display_value'), str):
                reason = (entry.get('display_note','') if key=='立案审批日期' else
                    '表内为简写；完整收费条款保留在填写数据及卷内合同，付款条件见原表备注。')
            if status == "conflict":
                reason = "来源仍有冲突；保存核对说明不代表已确定字段内容。"
            elif status == "human_confirmed" and not value:
                reason = "已保存的人工留空，系统不从旧别名补回。"
            elif not value:
                draft = ((fields.get("_form_drafts") or {}).get("fields") or {}).get(key) or {}
                codes = draft.get("reason_codes") or []
                reason = ("摘要超出原表容量，需保留要点后简要填写。" if "draft_too_long_for_original_cell" in codes
                          else BLANK_REASONS.get(key, "尚未取得可采纳值；须先检查识别和映射，不能据空白认定缺件。"))
            elif status == "unverified":
                reason = "内容已填写，但当前来源尚不足以核验。"
            if key == "__volume_pages":
                reason = "整卷PDF总页数，包含封面、目录和系统表。" if value else "整卷页数尚未测定。"
            anchors = [{"filename": filenames.get(anchor["file_id"], "原材料"), "page": anchor["page"]}
                       for anchor in assurance.get("anchors", [])]
            rows.append({"template": template, "field": entry["key"], "label": entry["label"],
                "value": value, "saved_value": saved_value, "status": status,
                "status_label": "程序测量" if status == "output_measurement" else LABELS.get(status, "待核验"),
                "reason": reason, "sources": anchors,
                "position": {"table": 1, "physical_row": row + 1, "physical_cell": cell + 1}
                    if row is not None else {"region": "清单抬头或文书名称行"}})
            if entry.get('output_policy'):
                rows[-1]['output_policy']=entry['output_policy']
                if entry['output_policy'].get('reason'):rows[-1]['reason']=entry['output_policy']['reason']
        if template == "送达材料清单":
            from ..core.v4_bridge import load
            counts = load('form_drafts').court_inventory_page_counts(fields)
            names = [re.sub(r"（原材料第[0-9—\-]+页）$", "", line.strip())
                     for line in str(specs['法院文件清单']['value'] or '').splitlines() if line.strip()]
            refs = (fields.get('_form_draft_sources') or {}).get('法院文件清单') or []
            norm = lambda path: os.path.normcase(os.path.abspath(path)) if isinstance(path, str) and path else ''
            source_paths = {norm(item.get('path')): item for item in manifest or [] if norm(item.get('path'))}
            for index, name in enumerate(names):
                count = counts[index] if index < len(counts) else None
                ref = refs[index] if count is not None and index < len(refs) else {}
                source = source_paths.get(norm(ref.get('source_path')))
                anchors = []
                if source and type(source.get('pages')) is int and 1 <= ref['page'] <= ref['page_end'] <= source['pages']:
                    anchors = [{'filename':source.get('filename','原材料'),'page':page}
                               for page in sorted({ref['page'],ref['page_end']})]
                rows.append({'template':template,'field':f'文书{index+1}页数','label':name+' · 页数',
                    'value':str(count) if count is not None else '', 'saved_value':str(count) if count is not None else '',
                    'status':'output_measurement' if count is not None else 'missing',
                    'status_label':'原材料页数' if count is not None else '留空', 'sources':anchors,
                    'reason':'按原材料起止页计算；不证明实际送达份数或签收情况。' if count is not None else
                             '缺少与当前清单逐项对应的自动页段依据，不从手填名称或页码文字推算。',
                    'position':{'table':1,'physical_row':index+2,'physical_cell':3}})
        if template == "立案审批表":
            from .original_template_service import approval_custom_value
            for row, label in ((6, "承办律师意见"), (7, "主任审批意见"), (9, "备注")):
                value, automatic = approval_custom_value(fields, row)
                fee = next((entry for entry in rows if entry['template']==template and entry['field']=='收费标准'), {})
                rows.append({"template": template, "field": label, "label": label,
                    "value": value, "saved_value": '' if automatic else value,
                    "status": "source_reference" if automatic else "manual_entry" if value else "manual_area",
                    "status_label": "收费原文指引" if automatic else "人工填写" if value else "人工填写区域",
                    "sources": fee.get('sources', []) if automatic else [],
                    "reason": ("依据当前收费条款自动生成的原文指引；不能据此认定实际应收、实收或已签署。" if automatic
                               else "文字填写不证明已审批或签署。" if value else "按实际办理情况填写；系统不代作审批或签名。"),
                    "position": {"table": 1, "physical_row": row + 1, "physical_cell": 1}})
    from ..core.v4_bridge import load
    contracts=load('form_cell_contracts')
    for template,names in contracts.MANUAL_AREAS.items():
        from .source_forms import form_fields_preserved
        if form_fields_preserved(fields,template):continue
        for name in names:
            if any(r['template']==template and r['field']==name for r in rows):continue
            rows.append({'template':template,'field':name,'label':name,'value':'','saved_value':'',
                'status':'manual_area','status_label':'预留手填','sources':[],
                'reason':'由实际办理、审批、评价或签收人填写；不得复制参考答案或由模型代填。',
                'position':{'region':'原表中的签署、意见或勾选区域'}})
    for row in rows:
        row['gap'] = gap_diagnosis(row, fields, manifest)
        if row['gap']['code'] == 'policy_review_needed':
            row['reason'] = '保存的自动内容及来源仍在历史候选中，填写规则更新后需复核；不能据此认定缺件或要求重复上传。'
        selected=_selected(row['template'],fields)
        limit=next((s[3] for s in SLOTS.get(selected,[]) if s[0]==row['field']),None)
        row['specification']=contracts.cell_spec(row['field'],template=row['template'],max_chars=limit,
            position=row['position'],case_type=fields.get('案件类别',''))
    from ..core.v4_bridge import load
    synthesis=load('form_synthesis')
    if synthesis.scope_supported(fields,manifest):
        bundle=fields.get('_model_form_synthesis') or {}
        lookup={s['id']:s for s in bundle.get('sources',[])}
        file_lookup={os.path.normcase(os.path.abspath(m['path'])):m for m in manifest or [] if m.get('path')}
        for warning in (bundle.get('case_facts') or {}).get('conflicts',[]):
            evidence=[]
            for item in warning['evidence']:
                source=lookup.get(item['source_id'],{})
                meta=file_lookup.get(os.path.normcase(os.path.abspath(source.get('source_path',''))),{})
                if meta:evidence.append({'filename':meta.get('filename','原材料'),'file_id':meta.get('file_id'),
                    'page':item['page'],'value':item['value'],'role':item['role']})
            for row in rows:
                if row['field']==warning['field']:
                    row.setdefault('source_issues',[]).append({'code':warning['code'],'evidence':evidence,
                        'message':'诉状内部本金记载不同，简介暂不写该金额；请在同一处对照原页，不以裁判金额覆盖诉请。'})
    return rows


def content_preflight(rows):
    """Consolidated content gaps; technical PDF success is not content accuracy."""
    core = {'委托人','当事人','案情简介','案件或项目名称','审（办）结果','结案小结'}
    grouped = {}
    for row in rows:
        if row['field'] not in core or row.get('value') and row.get('status') not in ('conflict','unverified'):
            continue
        entry = grouped.setdefault(row['field'], {'field':row['field'],'templates':[],
            'status':row.get('status'),'reason':row.get('reason') or '核心内容依据待核验。'})
        if row['template'] not in entry['templates']:entry['templates'].append(row['template'])
    return {'status':'needs_review' if grouped else 'core_content_present',
        'items':list(grouped.values()),'accuracy_independently_verified':False,
        'manual_approval_areas_excluded':True,
        'source_warnings':[dict(field=row['field'],**issue) for row in rows for issue in row.get('source_issues',[])],
        'system_repairs':list(dict.fromkeys(row['field'] for row in rows
            if (row.get('gap') or {}).get('code') in ('source_candidate_not_applied','generation_pending','source_review_needed','policy_review_needed')))}


def render_form_fill_audit(rows):
    esc = lambda value: html.escape(str(value or ""))
    body = []
    for row in rows:
        sources = "；".join(f"{item['filename']} 第 {item['page']} 页" for item in row["sources"])
        position = row["position"]
        location = (f"表{position['table']}／第{position['physical_row']}行／物理格{position['physical_cell']}"
                    if "table" in position else position["region"])
        values = [row["template"], row["label"], row["value"] or "（空白）",
                  row["status_label"]+' / '+(row.get('gap') or {}).get('label',''), sources or row["reason"], location]
        body.append("<tr>" + "".join("<td>" + esc(value).replace("\n", "<br>") + "</td>" for value in values) + "</tr>")
        if sources and row["reason"]:
            body.append('<tr><td colspan="6">' + esc(row["reason"]) + '</td></tr>')
        for issue in row.get('source_issues',[]):
            evidence='；'.join(f"{x['filename']} 第{x['page']}页：{x['value']}（{x['role']}）" for x in issue['evidence'])
            body.append('<tr><td colspan="6">'+esc(issue['message']+' '+evidence)+'</td></tr>')
    return ('<h2>原表字段填写与来源对照</h2><p>按本次原表实际填写位置列出。来源定位不等于独立证实事实；签章、审批和实际送达仍须真实办理记录。物理格按原表合并单元格结构计数。</p>'
            '<table><tr><th>原表</th><th>字段</th><th>填写内容</th><th>依据状态</th><th>来源／留空原因</th><th>原表位置</th></tr>'
            + "".join(body) + "</table>")
