"""Fictional completed loan cases: summary never discards a disposition."""
from copy import deepcopy
from types import SimpleNamespace
import pytest
from court_report_summary import summarize, recall_report, current_support

FIELDS={'委托人':'星河演示公司','对方当事人':'虚构乙、虚构丙','案由':'金融借款合同纠纷',
        '案号':'（2026）粤0000民初123号','执行案号':'（2026）粤0000执88号','案件类别':'民事'}
HEADER='''虚构市示例区人民法院
民事判决书
（2026）粤0000民初123号
原告：星河演示公司，住所地虚构市演示路二号。
被告：虚构乙，住所地虚构市另一街二号。
被告：虚构丙，住所地虚构市另一街三号。
原告星河演示公司诉被告虚构乙、虚构丙金融借款合同纠纷一案，本院受理后，依法适用简易程序公开开庭进行了审理。
'''
OPERATIVE='''缺席判决如下：
一、被告虚构乙、虚构丙于本判决发生法律效力之日起三日内向原告星河演示公司偿还拖欠本金12000元、利息300元、罚息20元、复利5元（罚息、复利暂计至2026年3月1日，此后按判决所定标准计算）；
二、被告虚构乙、虚构丙于本判决发生法律效力之日起三日内向原告星河演示公司支付律师费损失800元；
三、原告星河演示公司对被告虚构乙、虚构丙提供抵押的位于虚构市演示路一号房的房地产在上述第一、二项判项确定的债权范围内享有优先受偿权；
四、驳回原告星河演示公司的其他诉讼请求。
被告如果未按本判决指定的期间履行给付金钱义务的，应当依照民事诉讼法相关规定，加倍支付迟延履行期间的债务利息。
本案案件受理费100元，由原告负担10元，被告负担90元。
如不服本判决，可提起上诉。
'''
NOTICE='''虚构市示例区人民法院
结案通知书
（2026）粤0000执88号
关于星河演示公司诉虚构乙、虚构丙金融借款合同纠纷一案，本院作出的（2026）粤0000民初123号民事判决书已于2026年5月1日发生法律效力。
根据上述生效判决书，被告应偿还拖欠本金12000元，支付律师费损失800元。
本院于2026年6月1日立案执行，本案执行费80元。
由于本院（2026）粤0000执88号案件已经拍卖了被执行人名下虚构市演示路一号房，
'''
ENDING='星河演示公司享有优先受偿权，拍卖款足以覆盖本案债务。本案已执行完毕。特此通知。'


def documents():
    return [
        {'kind':'judgment','source_path':'judgment.pdf','start_page':1,'end_page':2,
         'pages':[{'page':1,'quote':HEADER},{'page':2,'quote':OPERATIVE}]},
        {'kind':'execution','source_path':'notice.pdf','start_page':1,'end_page':2,
         'pages':[{'page':1,'quote':NOTICE},{'page':2,'quote':ENDING}]},
    ]


def run(fields=None, docs=None, manual=()):
    fields=deepcopy(FIELDS if fields is None else fields)
    docs=documents() if docs is None else deepcopy(docs)
    units=[SimpleNamespace(doc_type=d['kind'],title='民事判决书' if d['kind']=='judgment' else '结案通知书',
                           start_page=d['start_page']-1,end_page=d['end_page']-1,source_path=d['source_path'],confidence=.95) for d in docs]
    cache={(d['source_path'],p['page']):p['quote'] for d in docs for p in d['pages']}
    fields.setdefault('_provenance',{});fields.setdefault('_field_conflicts',[])
    count=recall_report(fields,fields['_provenance'],fields['_field_conflicts'],
        page_cache=cache,allowed_sources=set(cache),document_units=units,manual_fields=manual,fact_review=[])
    return fields,count,units,cache


def test_full_report_preserves_unfavorable_disposition_deadline_and_source_references():
    fields,count,_,_=run()
    assert count==1
    result=fields['结案小结']
    for text in ('简易程序','三日内','12000元','利息、罚息、复利','律师费损失800元','优先受偿',
                 '其他诉讼请求被驳回','迟延履行','案件费用分担详见判决','2026年6月1日','已拍卖','已执行完毕'):
        assert text in result
    assert not any(text in result for text in ('已到账','已收律师费','本所已结案'))
    assert len(result)<=320
    ref=fields['_provenance']['结案小结'][-1]
    assert len(current_support(ref,fields))==3
    assert ref['documents']==documents()


@pytest.mark.parametrize('before,after',[
    ('四、驳回原告星河演示公司的其他诉讼请求。',''),
    ('四、驳回','五、另行判令提供担保。四、驳回'),
    ('偿还拖欠本金12000元','仅在抵押物价值范围内偿还拖欠本金12000元'),
    ('优先受偿权','不享有优先受偿权'),
    ('此后按判决所定标准计算','但如另有回款应扣减'),
    ('律师费损失800元','律师费损失800元及其他费用'),
    ('判决如下','原告诉请如下'),
])
def test_unknown_or_incomplete_operative_clause_is_not_partially_summarized(before,after):
    docs=documents();docs[0]['pages'][1]['quote']=OPERATIVE.replace(before,after)
    assert summarize(docs,FIELDS) is None


@pytest.mark.parametrize('change',['header','client','case_number','execution_number','missing_end','missing_header',
                                 'missing_middle','conditional','not_sold','other_property','uncompleted','bad_date','different_amount'])
def test_cross_case_incomplete_or_nonfinal_evidence_stays_for_review(change):
    docs=documents();fields=deepcopy(FIELDS)
    if change=='header':docs[0]['pages'][0]['quote']='参考模板\n'+HEADER
    if change=='client':fields['委托人']='另一虚构公司'
    if change=='case_number':fields['案号']='（2026）粤0000民初124号'
    if change=='execution_number':fields['执行案号']='（2026）粤0000执89号'
    if change=='missing_end':docs[0]['pages']=docs[0]['pages'][:1]
    if change=='missing_header':docs[0]['pages']=docs[0]['pages'][1:]
    if change=='missing_middle':docs[1]['end_page']=3;docs[1]['pages'][1]['page']=3
    if change=='conditional':docs[1]['pages'][1]['quote']=ENDING.replace('本案已执行完毕。','若付款则本案已执行完毕。')
    if change=='not_sold':docs[1]['pages'][0]['quote']=NOTICE.replace('已经拍卖了','拟拍卖')
    if change=='other_property':docs[1]['pages'][0]['quote']=NOTICE.replace('一号房','九号房')
    if change=='uncompleted':docs[1]['pages'][1]['quote']=ENDING.replace('本案已执行完毕','本案尚未执行完毕')
    if change=='bad_date':docs[1]['pages'][0]['quote']=NOTICE.replace('6月1日','99月1日')
    if change=='different_amount':docs[1]['pages'][0]['quote']=NOTICE.replace('本金12000','本金120000')
    assert summarize(docs,fields) is None


def test_existing_fact_human_blank_alias_and_conflict_are_not_overwritten():
    for fields,manual in [({**FIELDS,'结案小结':'人工已核验的完整报告'},()),(FIELDS,('结案小结',)),
                          ({**FIELDS,'审（办）结果':'本案已执行完毕。'},()),
                          ({**FIELDS,'_field_conflicts':[{'field':'案号'}]},())]:
        result,count,_,_=run(fields,manual=manual)
        assert count==0 and result.get('结案小结')==fields.get('结案小结')


def test_short_automatic_outcome_is_enriched_with_old_evidence_retained():
    old={'method':'local_agent','value':'本案已执行完毕。','quote':ENDING,'source_path':'notice.pdf','page':2}
    fields={**FIELDS,'结案小结':old['value'],'_provenance':{'结案小结':[old]}}
    result,count,_,_=run(fields)
    assert count==1 and result['_provenance']['结案小结'][0]==old
    assert run(result)[1]==0


def test_two_different_supported_reports_do_not_pick_the_first():
    docs=documents();second=deepcopy(docs[1]);second['source_path']='another-notice.pdf'
    second['pages'][0]['quote']=NOTICE.replace('6月1日','6月2日')
    fields,count,_,_=run(docs=docs+[second])
    assert count==0 and fields['_field_conflicts'][0]['reason_code']=='court_report_sources_conflict'


def test_later_identity_or_source_edit_invalidates_summary():
    fields,_,_,_=run();ref=fields['_provenance']['结案小结'][-1]
    changed=deepcopy(fields);changed['执行案号']='（2026）粤0000执89号'
    assert current_support(ref,changed) is None
    ref['documents'][0]['pages'][1]['quote']=OPERATIVE.replace('其他诉讼请求','全部诉讼请求')
    assert current_support(ref,fields) is None
