"""A positive provenance explanation is not an incompleteness warning."""
from copy import deepcopy
from form_drafts import draft_review_summary,draft_review_message


def fields():
    return {'_form_drafts':{'fields':{
        '案情简介':dict(status='generated',reason_codes=['attributed_pleading_excerpt'],source_count=2),
        '案件或项目名称':dict(status='generated',reason_codes=['explicit_project_name_preserved']),
        '委托人联系地址及电话':dict(status='generated',reason_codes=['partial_contact']),
    }}}


def test_successful_source_derivation_does_not_claim_missing_information():
    data=fields();before=deepcopy(data)
    summary=draft_review_summary(data)
    assert summary['review_fields']==['委托人联系地址及电话']
    message,_=draft_review_message(data)
    assert '信息可能不完整：委托人联系地址及电话' in message
    assert '仍需核对' not in message and data==before


def test_real_or_unknown_cautions_remain_even_alongside_success_reason():
    for reason in ('identity_only_brief_no_pleading_narrative','unrecognized_caution'):
        data=fields();data['_form_drafts']['fields']['案情简介']['reason_codes'].append(reason)
        assert '案情简介' in draft_review_summary(data)['review_fields']


def test_missing_and_layout_failures_are_still_actionable():
    data=fields();status=data['_form_drafts']['fields']
    status['案情简介']=dict(status='insufficient',reason_codes=['draft_too_long_for_original_cell'])
    status['立案审批日期']=dict(status='insufficient',reason_codes=['contract_date_unavailable_or_conflicting'])
    summary=draft_review_summary(data)
    assert summary['layout_review_fields']==['案情简介']
    assert summary['insufficient_fields']==['立案审批日期']
