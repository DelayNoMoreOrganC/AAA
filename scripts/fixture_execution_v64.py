"""Authored, hash-locked full-catalog civil fixture; not recognition accuracy."""
from pathlib import Path
import hashlib,json,sys
ROOT=Path(__file__).resolve().parents[1]
BASE=ROOT/'artifacts/civil-execution-v64'
TRIAL='(2026)粤0999民初6401号'
EXEC='(2026)粤0999执6402号'
CLIENT='虚构甲银行';OTHER='虚构乙公司、虚构丙'
ROWS=[
 (2,'invoice','律师费收款凭证','虚构甲银行支付基础代理费5000元，虚构明序律师事务所出具本收款记录。日期：2026年1月5日。'),
 (3,'contract','委托代理合同','委托人（甲方）：虚构甲银行。受托人（乙方）：虚构明序律师事务所。甲方委托乙方代理其诉虚构乙公司、虚构丙金融借款合同纠纷一审、执行案件。承办律师：虚构律师甲。基础代理费5000元，按实际回款金额另收2%。合同签订日期：2026年1月5日。'),
 (4,'poa','授权委托书','委托人：虚构甲银行。受托人：虚构律师甲，虚构明序律师事务所律师。委托代理本案一审及执行程序。'),
 (5,'complaint','民事起诉状','原告：虚构甲银行。被告：虚构乙公司、虚构丙。诉讼请求：判令被告乙公司偿还借款1000元及利息100元，被告丙承担连带责任。事实与理由：原告与被告乙公司订立借款合同并放款1000元，被告丙提供保证，借款到期未还。此致示例法院。'),
 (6,'review_record','会见当事人谈话笔录','2026年1月6日，虚构律师甲与虚构甲银行代表核对借款合同、放款凭证和催收情况。委托人表示借款到期未偿还。'),
 (7,'evidence','证据材料清单','证据一：虚构甲银行与虚构乙公司借款合同，金额1000元。证据二：放款记录1000元。证据三：虚构丙保证承诺。此页为虚构证据摘要，不模拟真实签章。'),
 (8,'preservation','财产保全申请书','申请人：虚构甲银行。被申请人：虚构乙公司。申请冻结被申请人财产1100元。本申请不证明法院已实施保全。'),
 (9,'agent_opinion','承办律师代理意见','虚构律师甲审查本案借款合同及放款记录，建议围绕到期未还、保证范围举证；利息以法院认定为准。'),
 (10,'group_discussion','集体讨论记录','2026年1月8日，虚构律师甲与虚构律师乙讨论本案借款和保证证据，决定补充核对催收材料。'),
 (11,'plea','代理词','原告虚构甲银行委托诉讼代理人虚构律师甲：请求依法审查借款合同、放款凭证及保证约定，支持诉状请求。'),
 (12,'summons','传票',TRIAL+'\n虚构区人民法院通知原告虚构甲银行于2026年2月1日到第一法庭参加开庭审理。'),
 (13,'court_record','庭审笔录',TRIAL+'\n2026年2月1日，虚构区人民法院开庭审理本案。原告代理人虚构律师甲出庭，双方围绕放款及保证范围发表意见。'),
 (14,'judgment','民事判决书','虚构区人民法院\n'+TRIAL+'\n原告：虚构甲银行。被告：虚构乙公司、虚构丙。\n本院于2026年2月1日公开开庭审理本案，原告委托诉讼代理人虚构律师甲到庭。判决：被告乙公司偿还本金1000元及利息100元；被告丙承担连带清偿责任。\n裁判日期：2026年3月1日。'),
 (15,'execution','执行裁定书','虚构区人民法院\n'+EXEC+'\n申请执行人：虚构甲银行。被执行人：虚构乙公司、虚构丙。\n本院裁定如下：终结本次执行程序。未附回款或款项发放凭证。')]

def build():
    import fitz
    BASE.mkdir(exist_ok=False)
    path=BASE/'虚构金融借款全目录及终本.pdf'
    with fitz.open() as pdf:
        for seq,kind,title,body in ROWS:
            p=pdf.new_page(width=595,height=842)
            text=title+'\n'+body+'\n完全虚构验收材料，无真实身份或印章。'
            assert p.insert_textbox(fitz.Rect(52,52,543,760),text,fontname='china-s',fontsize=14,lineheight=1.5)>=0
        pdf.save(path)
    (BASE/'registry.json').write_text(json.dumps({'sha256':hashlib.sha256(path.read_bytes()).hexdigest(),'pages':len(ROWS),'recognition':'authored segmentation and identity; no model'},indent=2),encoding='utf8')
    with fitz.open(path) as pdf:
        for i in (3,12,13):pdf[i].get_pixmap().save(BASE/f'source-{i+1}.png')

def analyze(paths,case_type,data):
    import fitz
    sys.path.insert(0,str(ROOT))
    import archive_pipeline as p
    from archive_catalog import get_catalog
    from pdf_doc_locator import DocumentUnit
    from case_timeline import collect
    if case_type!='civil' or len(paths)!=1 or not Path(paths[0]).resolve().is_relative_to(data):raise ValueError('Fixture scope')
    registry=json.loads((BASE/'registry.json').read_text(encoding='utf8'))
    if hashlib.sha256(Path(paths[0]).read_bytes()).hexdigest()!=registry['sha256']:raise ValueError('Unregistered input')
    with fitz.open(paths[0]) as pdf:
        assert len(pdf)==len(ROWS)
        cache={(paths[0],i+1):page.get_text(sort=True) for i,page in enumerate(pdf)}
    units=[DocumentUnit(i,kind,i,i,title,catalog_seq=seq,source_path=paths[0],confidence=.95) for i,(seq,kind,title,body) in enumerate(ROWS)]
    fields={'案号':TRIAL,'执行案号':EXEC,'案件类别':'民事','委托人':CLIENT,'对方当事人':OTHER,'案由':'金融借款合同纠纷','律师事务所':'虚构明序律师事务所','承办律师':'虚构律师甲',
        '案件或项目名称':'虚构甲银行诉虚构乙公司、虚构丙的金融借款合同纠纷','_fixture_scope':'Authored complete-catalog recognition candidates; no automatic legal necessity/signature findings'}
    refs={};assert collect(fields,refs,[],page_cache=cache,allowed_sources=set(cache),document_units=units)==2
    fields['_provenance']=refs
    assert '终结本次' in fields['结案小结'] and '不据终本认定债务已清偿' in fields['结案小结']
    catalog=get_catalog('civil');found=p.compute_found_seqs(catalog,units,{})|{r.seq for r in catalog if r.source=='system'}
    missing=p.compute_missing_items('civil',catalog,found)
    assert not missing,missing
    return p.ArchiveAnalysis('civil',paths[0],fields,{},units,found,missing,source_paths=paths)

if __name__=='__main__':build()
