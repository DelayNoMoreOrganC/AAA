"""Wholly fictional scanned loan case and independent expected facts; no model calls."""
from pathlib import Path
import hashlib, json, subprocess
from reportlab.pdfgen import canvas
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.lib.pagesizes import A4
from reportlab.lib.utils import ImageReader
from PIL import Image

ROOT=Path(__file__).resolve().parents[1]
OUT=ROOT/'artifacts/civil-loan-v53'
POPPLER=Path.home()/'.cache/codex-runtimes/codex-primary-runtime/dependencies/native/poppler/Library/bin/pdftoppm.exe'
P='虚构星桥银行股份有限公司'
D='虚构云禾科技有限公司'
CASE='（2026）粤0999民初5301号'
PAGES=[
('委托代理合同',[
f'委托人（甲方）：{P}。受托人（乙方）：虚构明序律师事务所。',
f'甲方委托乙方代理其诉{D}、虚构林甲、虚构陈乙金融借款合同纠纷一审案件。指派承办律师：虚构律师甲。',
'收费约定：一审基础律师费5000元；另按实际收回款项的2%收取风险代理费。基础费于合同订立后十日内支付，风险费于实际回款后结算。',
'合同载明签订日期：2026年1月5日。甲乙双方签字盖章区域未提供。本包未附律师费收款凭证。']),
('民事起诉状',[
f'原告：{P}，住所地虚构市样例路8号。',
f'被告一：{D}。被告二：虚构林甲。被告三：虚构陈乙。',
'案由：金融借款合同纠纷。',
'诉讼请求：一、判令被告一偿还借款本金1200000元及截至起诉时利息36000元；二、判令被告二、被告三对前述债务承担连带清偿责任；三、本案诉讼费用由三被告承担。',
'事实与理由详见本起诉状下一页。本页为起诉状第1页，共2页。']),
('事实与理由（续）',[
f'原告{P}与被告一{D}于2024年7月1日订立借款合同，借款金额1200000元，期限一年，约定年利率6%。',
'原告诉称已于2024年7月3日足额放款。借款到期后被告一未依约偿还本金，虽经催收仍拖欠；被告二虚构林甲、被告三虚构陈乙提供连带责任保证。',
'原告据此请求偿还本金1200000元、起诉时利息36000元及两名保证人承担责任。以上为起诉时主张，不是法院已认定事实。',
'此致：虚构市示例区人民法院。具状人：虚构星桥银行股份有限公司。起诉日期：2026年1月12日。',
'本页为前页民事起诉状第2页，共2页；无其他诉讼主体。']),
('证据材料清单',[
f'案号：{CASE}。提交人：{P}。',
'证据一：借款合同，1页，证明贷款金额、期限及利率。对应紧接本清单的第1页附件。',
'证据二：放款凭证，1页，证明原告向借款人发放贷款。对应紧接本清单的第2页附件。',
'后附两页均为本清单所列证据，不是律师事务所委托代理合同。']),
('借款合同',[
f'贷款人：{P}。借款人：{D}。',
'借款本金：人民币1200000元。借款用途：生产经营周转。借款期限：2024年7月1日至2025年6月30日。',
'借款年利率6%。保证人：虚构林甲、虚构陈乙，保证方式为连带责任保证。',
'这是前页证据清单中的证据一。仅作为案卷证据附件，无真实印章或签名。']),
('贷款发放凭证',[
f'付款方：{P}。收款方：{D}。',
'放款日期：2024年7月3日。发放金额：1200000元。款项用途：合同约定的借款发放。',
'这是证据清单中的证据二。该笔放款不是借款人还款、执行回款或律师费收款。账户号码未设置。']),
('开庭通知短信',[
'12368 虚构法院短信示例',
f'虚构市示例区人民法院通知：{CASE}金融借款合同纠纷案定于2026年5月20日9时在第一审判庭开庭审理，请准时到庭。',
'收信对象：虚构律师甲。本页仅展示通知内容，不证明实际送达或到庭。']),
('民事判决书',[
f'虚构市示例区人民法院  {CASE}',
f'原告：{P}。被告：{D}、虚构林甲、虚构陈乙。',
'本院于2026年5月20日公开开庭审理本案，原告委托诉讼代理人虚构律师甲到庭。本院收到原告提交的借款合同和放款凭证。',
'经审理查明，借款人此前已归还部分本金，尚欠本金1080000元。判决：被告一偿还本金1080000元及利息30000元；被告二、被告三承担连带清偿责任；驳回其他诉讼请求。',
'裁判日期：2026年6月30日。未附本判决生效证明、判后付款凭证或执行立案文书。判令支付不等于已经履行。'])]

def main():
    if OUT.exists():raise SystemExit('Refuse to overwrite a benchmark')
    OUT.mkdir(parents=True)
    pdfmetrics.registerFont(TTFont('Song',r'C:\Windows\Fonts\simsun.ttc',subfontIndex=0))
    pdfmetrics.registerFont(TTFont('Hei',r'C:\Windows\Fonts\simhei.ttf'))
    text_pdf=OUT/'source-text.pdf'
    c=canvas.Canvas(str(text_pdf),pagesize=A4,invariant=1)
    for number,(title,paragraphs) in enumerate(PAGES,1):
        c.setFont('Hei',21);c.drawCentredString(A4[0]/2,786,title)
        c.setFont('Song',9);c.drawCentredString(A4[0]/2,758,'完全虚构验收材料 - 非真实法律文书 - 无真实身份或印章')
        y=720;c.setFont('Song',13)
        for paragraph in paragraphs:
            line=''
            for char in paragraph:
                if pdfmetrics.stringWidth(line+char,'Song',13)>475:
                    c.drawString(60,y,line);y-=23;line=''
                line+=char
            if line:c.drawString(60,y,line);y-=23
            y-=12
        if y<80:raise ValueError('Source fixture overflow')
        c.setFont('Song',9);c.drawString(60,42,f'虚构民事样例V53  材料页 {number}/8')
        c.showPage()
    c.save()
    subprocess.run([str(POPPLER),'-r','130','-png',str(text_pdf),str(OUT/'page')],check=True,capture_output=True)
    scanned=OUT/'虚构金融借款案_八页扫描件.pdf';c=canvas.Canvas(str(scanned),pagesize=A4,invariant=1)
    pictures=sorted(OUT.glob('page-*.png'))
    assert len(pictures)==8
    for picture in pictures:
        c.drawImage(ImageReader(str(picture)),0,0,width=A4[0],height=A4[1]);c.showPage()
    c.save()
    thumbs=[]
    for picture in pictures:
        with Image.open(picture) as source:
            image=source.convert('RGB');image.thumbnail((420,594));thumbs.append(image)
    sheet=Image.new('RGB',(420*4,594*2),'#dddddd')
    for i,image in enumerate(thumbs):sheet.paste(image,((i%4)*420,(i//4)*594))
    sheet.save(OUT/'contact-sheet.png')
    expected=dict(synthetic=True,source_sha256=hashlib.sha256(scanned.read_bytes()).hexdigest(),pages=8,
      purpose='Independent benchmark, never feed expected answers to recognition',
      documents=[dict(pages=[1],type='contract'),dict(pages=[2,3],type='complaint'),dict(pages=[4,5,6],type='evidence',group='evidence list and attachments; preserve document subtypes'),dict(pages=[7],type='summons'),dict(pages=[8],type='judgment')],
      facts=dict(plaintiff=P,defendants=[D,'虚构林甲','虚构陈乙'],client=P,lawyer='虚构律师甲',cause='金融借款合同纠纷',case_number=CASE,
      contract_date='2026-01-05',fee=['5000元','实际收回款项','2%'],claimed_principal='1200000元',claimed_interest='36000元',judged_principal='1080000元',judged_interest='30000元',hearing_date='2026-05-20',judgment_date='2026-06-30'),
      intake_must_include=['借款','到期','1200000','36000','保证'],intake_must_not_include=['1080000','30000','判决'],
      closure_must_cover=['委托','起诉','开庭','判决'],forbidden_assertions=['已签署委托合同','律师费已到账','判决已生效','已执行完毕','判后已还款'],
      expected_catalog_rows=17,execution_material=False,full_legal_completeness=False)
    (OUT/'expected.json').write_text(json.dumps(expected,ensure_ascii=False,indent=2),encoding='utf-8')
    (OUT/'source-transcript.json').write_text(json.dumps(PAGES,ensure_ascii=False,indent=2),encoding='utf-8')
    print(str(scanned))

if __name__=='__main__':main()
