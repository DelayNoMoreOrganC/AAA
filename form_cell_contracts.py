"""Cell purposes and source plans shared by generation and form QA.

Contains no client examples. A content component is required only when its
supporting material exists; this is not a license to invent missing facts.
"""
from copy import deepcopy
from form_field_policy import NARRATIVES, RULES, ALIASES

OPTIONAL_FACT_FIELDS = frozenset(('收费标准','立案审批日期','收案日期','结案日期'))

def optional_output(field, value, fields):
    """Presentation only: keep evidence/history, leave uncertain cells blank.

    This does not certify model accuracy or mutate an original signed form.
    Provider confidence scores alone never make a value printable.
    """
    if field=='合同号':
        return {'value':'','code':'intentional_blank','reason':'按使用约定，内部合同号留空。'}
    if field not in OPTIONAL_FACT_FIELDS:return None
    blank={'value':'','code':'optional_blank','reason':'依据不明确，按使用约定留空；不强制补填。'}
    if not value:return blank
    if any(isinstance(c,dict) and c.get('field')==field and not c.get('resolved')
           for c in fields.get('_field_conflicts',[])):return blank
    refs=(fields.get('_provenance') or {}).get(field) or []
    refs=[refs] if isinstance(refs,dict) else refs
    supported=False
    from fact_evidence import validate_fact
    for ref in refs:
        if not isinstance(ref,dict) or ref.get('value')!=value:continue
        if ref.get('method')=='human':supported=True;break
        if ref.get('method') not in ('local_agent','visual_agent_local_evidence'):continue
        if ref.get('binding')=='intake_contract_date_default':
            from intake_contract_date import current_support
            supported=current_support(ref,fields) is not None
        elif ref.get('binding')=='batch_engagement_intake':
            from engagement_intake import current_support
            supported=current_support(ref,fields) is not None
        elif ref.get('derivation')=='selected_notice_fee':
            from source_fee_notice import reference_supported
            supported=reference_supported(field,value,ref,fields)
        elif not ref.get('binding') and not ref.get('derivation'):
            quote=ref.get('quote','')
            supported=bool(quote and validate_fact(field,value,quote,quote))
        if supported:break
    if not supported:return blank
    if field=='收费标准':
        from fee_display import current
        display=current(fields)
        if len(display['value'] if display else str(value))>50:
            return dict(blank,reason='收费条款无法在原表内准确简述，留空并保留卷内原合同。')
    return {'value':value,'code':'supported_optional','reason':''}

BUSINESS = {
    'civil': {
        '案情简介': ['诉状中的法律关系及交易背景', '争议经过或违约事实', '主要请求及条件；原告主张不得写成认定事实'],
        '案件或项目名称': ['诉状全部原告', '诉状全部被告', '对应案由；已有纠纷二字不重复'],
        '审（办）结果': ['关键审级变化', '有效裁判的支持及未支持事项', '执行有据进展或履行结果'],
        '结案小结': ['本所接受何方何事项委托', '有记录的起诉、答辩、出庭或其他代理工作', '审判及执行关键节点', '现有结果及有据的未完事项'],
    },
    'criminal': {
        '案情简介': ['委托人与被追诉人分别列明', '起诉书所载涉嫌行为及指控罪名', '本次接受辩护的程序阶段；不倒填终审结论'],
        '案件或项目名称': ['被追诉人姓名', '涉嫌或被指控事项', '本次辩护事项；签约家属不得替代被追诉人'],
        '审（办）结果': ['依日期和关联案号排列原审、撤销发回、重审、再上诉', '区分指控罪名和最终认定罪名', '最后有效判项；旧刑期须标明所处阶段'],
        '结案小结': ['委托家属与接受辩护的当事人', '实际辩护工作与有记录的意见', '发回或改判等关键转折', '最终处理；不得仅凭裁判变化声称辩护意见获采纳'],
    },
    'nonlit': {
        '案情简介': ['共同委托人和实际服务对象分别确定', '合同约定的具体事项', '接案时服务目的及范围'],
        '案件或项目名称': ['实际服务对象', '具体非诉事项；受益人不自动等于委托人或服务对象'],
        '审（办）结果': ['有记录的办理进展', '实际出具的成果及办理机构', '完成的具体事项；一个成果不证明所有合同义务完成'],
        '结案小结': ['受托事项及服务对象', '材料证明的咨询、起草、修改、申请或协调工作', '对应成果及日期', '已完成范围；不虚构遗嘱生效或财产已转移'],
    },
    'counsel': {
        '案情简介': ['顾问单位', '本期顾问起止期间', '合同约定的主要服务范围；不写成本期已完成工作'],
        '案件或项目名称': ['顾问单位及常年或专项顾问事项', '本期服务范围；不要混入其他年度'],
        '审（办）结果': ['本期材料记录的服务类别与成果', '具体处理结果', '协议实际存续或终止情况；届满不等于结清或满意'],
        '结案小结': ['本期委托范围与期间', '按实际函件、审改稿、咨询记录归纳工作', '有据的成果与反馈', '未完事项或续期记录；没有证据不要写全部完成'],
    },
    'administrative': {
        '案情简介': ['被诉行政行为或不履职事项', '诉状中的事实与理由', '撤销、履职、确认违法等实际诉求'],
        '案件或项目名称': ['实际原告', '行政被告', '被诉行政事项；第三人不自动转为被告'],
        '审（办）结果': ['复议和诉讼各自程序', '有效裁判及支持范围', '行政机关实际履行依据'],
        '结案小结': ['本所代理立场', '材料证明的代理工作', '程序变化及裁判', '后续执行或履行进展'],
    },
}
CASE_ALIASES = {'民事':'civil','刑事':'criminal','刑事诉讼':'criminal','非诉':'nonlit',
                '顾问':'counsel','法律顾问':'counsel','行政':'administrative','admin':'administrative'}

# These are acts/opinions of a person, not prose-generation opportunities.
# Existing signed source PDFs are preserved by source_form_policy, not redrawn.
MANUAL_AREAS = {
    '立案审批表': ('承办律师意见','主任审批意见'),
    '结案报告表': ('委托人对服务质量意见','承办律师意见','主任审批意见'),
    '质量监督卡': ('质量监督选择项1—9','客户意见和建议','委托人签名','签收日期'),
    '送达材料清单': ('送达时间','送达人','接收人','签收备注'),
}

def explicit_human_value(fields, field):
    refs=(fields.get('_provenance') or {}).get(field) or []
    refs=[refs] if isinstance(refs,dict) else refs
    value=fields.get(field)
    return value or '' if any(isinstance(r,dict) and r.get('method')=='human'
        and r.get('value')==value for r in refs) else ''

SOURCE_PRIORITY = {
    '案情简介': ('complaint','indictment','contract','client_talk'),
    '案件或项目名称': ('complaint','indictment','contract','judgment'),
    '审（办）结果': ('judgment','ruling','mediation','execution','agreement_status','legal_work','work_record'),
    '结案小结': ('contract','legal_work','work_record','plea','agent_opinion','court_record',
                 'meeting_record','client_talk','judgment','ruling','mediation','execution','agreement_status'),
}

LITERAL_SOURCES = {
    '合同号': ('intake_approval','contract'),
    '委托人': ('contract','poa','intake_approval'),
    '当事人': ('poa','contract','complaint','indictment'),
    '对方当事人': ('complaint','indictment','judgment'),
    '委托人电话': ('contract','intake_approval','client_talk'),
    '委托人传真': ('contract','intake_approval'),
    '地址': ('contract','intake_approval','complaint','judgment'),
    '收费标准': ('contract','fee_notice','intake_approval'),
    '承办律师': ('poa','contract','judgment'),
    '律师事务所': ('contract','poa'),
    '案由': ('complaint','indictment','contract','judgment'),
    '案号': ('judgment','ruling','court_notice'),
    '执行案号': ('execution',),
    '收案日期': ('intake_approval','work_record'),
    '立案审批日期': ('intake_approval','contract'),
    '结案日期': ('closure_report','work_record'),
    '审理法院': ('judgment','ruling','court_notice'),
    '审级': ('judgment','ruling','execution'),
    '应收业务费': ('fee_settlement','closure_report'),
    '已收业务费': ('fee_settlement','closure_report'),
    '尚欠业务费': ('fee_settlement','closure_report'),
    '应退业务费': ('fee_settlement','closure_report'),
    '阶段工作情况': ('legal_work','work_record','court_record','meeting_record'),
    '顾问协议状态': ('agreement_status','contract'),
    '法院文件清单': ('judgment','ruling','mediation','execution','court_notice'),
    '委托人联系地址及电话': ('accepted_client_address','accepted_client_phone'),
}

def writing_rules(case_type, targets):
    business = BUSINESS.get(CASE_ALIASES.get(case_type, case_type), {})
    result = {}
    for field in targets:
        rule = deepcopy(NARRATIVES[field])
        rule.update(content_components=business.get(field, []), source_priority=list(SOURCE_PRIORITY[field]),
                    missing_policy='有据部分先写；逐项缺口放missing。不得因为一个金额或日期不清而清空整个栏目。',
                    compression_order='删重复身份、冗长案号、地址、逐项计算和套话；保留主体、阶段、主要行为、条件及结果。不得截断句子或删除共同当事人。')
        result[field] = rule
    return result

def source_plan(sources, case_type, targets):
    """Explicit relevant source IDs; these are reading directions, not evidence."""
    rules = writing_rules(case_type, targets)
    return {field: {'source_ids': [s['id'] for kind in rule['source_priority']
                for s in sources if s['kind']==kind],
            'components': rule['content_components'],
            'scope': '仅已读片段；文书末页缺失或文本被截取时不认定完整'}
            for field,rule in rules.items()}

def cell_spec(field, *, template, max_chars=None, position=None, case_type=''):
    """Specification for a physical cell, including deliberately human cells."""
    key=ALIASES.get(field,field)
    mode,instruction=RULES.get(key,('human','仅依据实际记录或人工填写，不自动推定。'))
    if key=='合同号':
        mode,instruction='reserved_blank','内部合同号统一留空，不以法院案号或银行编号替代。'
    elif key in OPTIONAL_FACT_FIELDS:
        instruction+=' 有明确依据才填写；缺失、歧义、冲突或不能准确简述时留空，不强制用户补填。'
    return dict(field=field, template=template, mode=mode, instruction=instruction,
                max_chars=max_chars, position=position,
                source_priority=list(SOURCE_PRIORITY.get(key,LITERAL_SOURCES.get(key,()))),
                writing=writing_rules(case_type,[key]).get(key) if key in NARRATIVES else None,
                format={'font':'宋体','size_pt':12,'overflow':'不得缩小字体、扩框或截断；保留原值并列出容量问题'},
                conflict='保留原件及人工决定；主体或来源冲突集中核对，不以最后出现者覆盖',
                empty='先查已提供来源及映射；签署、评价、审批不得代填')
