"""Export a readable, offline reference from current cell rules. No case I/O."""
from pathlib import Path
import sys
import html
import json
import re

ROOT=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(ROOT),str(ROOT/'web/backend')]
from app.services.original_template_service import SLOTS
from form_cell_contracts import cell_spec, MANUAL_AREAS, OPTIONAL_FACT_FIELDS, BUSINESS

OUT=ROOT/'docs'/'AAA卷小助_各格填写规格_20261028.html'
MODE={'configured':'按设置填写','literal':'据原文提取','synthesis':'综合撰写',
      'derived':'按规则整理','system':'系统计算','human':'预留手填','reserved_blank':'固定留空'}
SOURCE={'intake_approval':'已有立案审批表','contract':'委托合同及适用补充条款','poa':'授权材料',
 'complaint':'诉状','indictment':'起诉书','judgment':'判决书','ruling':'裁定书','court_notice':'法院通知',
 'execution':'执行材料','closure_report':'已有结案报告','work_record':'实际工作记录',
 'client_talk':'客户会谈记录','fee_notice':'收费通知','fee_settlement':'结算及收款记录',
 'legal_work':'实际法律服务材料','court_record':'庭审记录','meeting_record':'会议记录',
 'agreement_status':'协议存续或终止记录','mediation':'调解书','plea':'辩护词',
 'agent_opinion':'代理意见','accepted_client_address':'已核实委托人地址','accepted_client_phone':'已核实委托人电话'}
NAMES={'档案卷宗':'档案封面（诉讼类）','非诉封面':'档案封面（非诉／顾问类）'}
esc=lambda v:html.escape(str(v or ''))

def collect():
    specs=[]
    for name,slots in SLOTS.items():
        for field,row,col,limit,_ in slots:
            specs.append(cell_spec(field,template=name,max_chars=limit,position={'row':row+1,'cell':col+1}))
    # Paragraph headings and repeating delivery rows are outside SLOTS.
    for field,limit in [('合同号',80),('委托人',45),('承办律师',25),('送达材料名称',26),('送达材料页数',None)]:
        s=cell_spec(field,template='送达材料清单',max_chars=limit,position={'region':'抬头或清单行'})
        if field=='送达材料名称':
            s['instruction']='当前版本按已识别法院文书逐项生成名称，续页合为同一文书；最多18行、每行名称不超过26字。清单不证明实际送达。其他交付材料可手动补充。'
        specs.append(s)
    for name,fields in MANUAL_AREAS.items():
        for field in fields:
            if not any(s['template']==name and s['field']==field for s in specs):
                specs.append(cell_spec(field,template=name,position={'region':'原表手填区域'}))
    for name in ('立案审批表','档案卷宗','非诉封面','结案报告表'):
        s=cell_spec('备注',template=name,position={'region':'原表备注栏'})
        if name=='立案审批表':s['instruction']='人工备注优先；只有收费标准已获支持并采用简写时，系统可注明完整收费条件见卷内合同。'
        specs.append(s)
    return specs

def render_table(specs):
    rows=[]
    for s in specs:
        mode='明确才填' if s['field'] in OPTIONAL_FACT_FIELDS else MODE.get(s['mode'],s['mode'])
        instruction=s['instruction']
        if s['mode']=='human':instruction='新生成表单预留空白，不从参考实例或模型输出代填；本人明确录入内容及已签署原件保留。 '+instruction
        source='、'.join(SOURCE.get(k,k) for k in s['source_priority'])
        if s['mode'] in ('human','reserved_blank'):source='—'
        label='卷内页数' if s['field']=='__volume_pages' else s['field']
        if s['field']=='合同号' and s['template'] in ('质量监督卡','送达材料清单'):label='案号（律所内部编号）'
        limit='留空' if s['mode']=='reserved_blank' else '手填区' if s['mode']=='human' else s['max_chars'] or '按实际数据'
        location=s['position'] or {}
        location=f"第{location['row']}行／物理格{location['cell']}" if 'row' in location else location.get('region','')
        rows.append('<tr>'+''.join('<td>'+esc(v)+'</td>' for v in [label,mode,instruction,source,limit])+f'</tr>')
    return '<table><thead><tr><th>栏目</th><th>填写方式</th><th>填写规则</th><th>优先核对的来源</th><th>容量参考</th></tr></thead><tbody>'+''.join(rows)+'</tbody></table>'

def main():
    specs=collect()
    groups=[]
    for i,name in enumerate(['立案审批表','档案卷宗','非诉封面','结案报告表','质量监督卡','送达材料清单']):
        groups.append(f'<section class="form" id="form-{i}"><h2>{esc(NAMES.get(name,name))}</h2>'+render_table([s for s in specs if s['template']==name])+'</section>')
    business=[]
    for kind,label in [('civil','民事'),('criminal','刑事'),('nonlit','非诉'),('counsel','法律顾问'),('administrative','行政')]:
        rows=''.join('<tr><td>'+esc(field)+'</td><td>'+esc('；'.join(parts))+'</td></tr>' for field,parts in BUSINESS[kind].items())
        business.append(f'<h3>{label}</h3><table><thead><tr><th>栏目</th><th>内容要点（有依据才写）</th></tr></thead><tbody>{rows}</tbody></table>')
    style='''body{max-width:1180px;margin:40px auto;padding:0 24px;font:15px/1.7 "Microsoft YaHei",system-ui;color:#24262b;background:#f5f5f7}h1{font-size:30px;margin-bottom:6px}h2{font-size:23px}h3{margin-top:28px}.meta{color:#626771}.card,section{padding:24px;background:white;border:1px solid #e4e6ea;border-radius:14px;margin:22px 0}table{border-collapse:collapse;width:100%;table-layout:fixed;font-size:14px}th,td{border:1px solid #d9dde3;padding:12px;text-align:left;vertical-align:top;overflow-wrap:anywhere}th{background:#f2f4f7}th:nth-child(1){width:13%}th:nth-child(2){width:12%}th:nth-child(3){width:43%}th:nth-child(4){width:21%}th:nth-child(5){width:11%}a{color:#1266ba}nav{display:flex;gap:16px;flex-wrap:wrap}button{border:1px solid #bbb;border-radius:7px;background:white;padding:8px 16px;cursor:pointer}.notice{border-left:4px solid #4184c5}.business table th:first-child{width:20%}.business table th:last-child{width:80%}@media print{@page{size:A4 landscape;margin:12mm}body{background:white;margin:0;padding:0;font-size:11pt}.tools,nav{display:none}section,.card{border:0;padding:0;margin:12pt 0;box-shadow:none}section.form{break-before:page}table{font-size:10pt}td,th{padding:7pt}tr{break-inside:avoid}thead{display:table-header-group}h2,h3{break-after:avoid}a{color:inherit;text-decoration:none}}'''
    nav=''.join(f'<a href="#form-{i}">{esc(NAMES.get(n,n))}</a>' for i,n in enumerate(['立案审批表','档案卷宗','非诉封面','结案报告表','质量监督卡','送达材料清单']))
    page=f'''<!doctype html><html lang="zh-CN"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1"><title>AAA卷小助 各格填写规格 2026-10-28</title><style>{style}</style></head><body>
<header><h1>AAA 卷小助 · 各格填写规格</h1><p class="meta">更新：2026年10月28日 · 留白约定修订版 · 从当前候选代码导出</p><div class="tools"><button onclick="window.print()">打印 / 另存为 PDF</button></div></header>
<div class="card notice"><strong>本次更新</strong><ul><li>内部合同号：统一留空；质量卡、送达清单中对应的律所内部编号也留空。封面的法院收案号仍据材料填写。</li><li>风险收费：能准确识别且能完整保留关键条件时填写；歧义、冲突或无法准确简述时留空，不强制补填。</li><li>日期：明确才填写，不确定留空；不混用合同签订、律所收案、法院立案、裁判和结案日期。</li><li>签名、审批意见、客户评价、勾选项及实际签收信息：新表预留手填，不照抄实例。</li></ul><p>这是软件的填写规格，不是律协发布的正式规范，也不代表所有识别场景已经验收通过。本文件描述当前源码快照，不证明任何运行站点已经更新或完成全部验收。</p></div>
<div class="card"><h2>如何阅读</h2><p>“据原文提取”要求主体及来源对应；“综合撰写”要求组织有据的事实和办理过程；“明确才填”允许留空。“按设置填写”和“系统计算”不交给模型猜测。</p><p>容量是当前原表的保守字数限制，不是必须写满的字数。填写文字通常为宋体12磅，仍须通过实际版式检查；不为塞入文字缩小字体、扩框或截断。原表标题和印刷标签沿用原样。</p><p>已有签署原件原样保留。留白约定不删除后台候选及历史记录，不代表缺少整份材料，也不证明已完成审批、送达或法律合规。</p><nav>{nav}<a href="#business">各业务摘要规则</a></nav></div>
{''.join(groups)}<section class="business" id="business"><h2>各业务的综合撰写要点</h2><p>这些是取材和写作要求。四份实例用于参考；行政类没有本轮对应实例验收。没有依据的要点不补造，仅缺局部信息时保留其余有据内容。</p>{''.join(business)}</section>
<section><h2>共同处理规则</h2><ul><li>案情简介立足接案时；审办结果与结案小结结合实际办理过程，不能把判决主文复制两遍。</li><li>合同约定不等于实际完成；判决不等于履行；裁定拍卖不等于已成交；发票不等于本案累计已收。</li><li>同一文书的识别与归类疑问合并查看，保留来源页码。来源冲突不采用“最后出现的值覆盖前值”。</li><li>收费与日期的不确定留白按本次约定处理；其他关键主体或结果冲突仍须保留核对入口。</li><li>本文只含规则，不含客户案卷内容、密钥或个人案件信息。</li></ul></section></body></html>'''
    OUT.write_text(page,encoding='utf8')
    (ROOT/'docs/FORM_CELL_SPECIFICATIONS.json').write_text(json.dumps(specs,ensure_ascii=False,indent=2),encoding='utf8')
    print(json.dumps({'file':str(OUT),'entries':len(specs),'groups':len(groups)},ensure_ascii=False))

if __name__=='__main__':main()
