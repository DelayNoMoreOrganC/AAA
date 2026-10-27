"""Author two explicitly fictional date cases; never read client materials."""
from pathlib import Path
import hashlib,json
import fitz
from reportlab.pdfgen import canvas
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.lib.pagesizes import A4

ROOT=Path(__file__).resolve().parents[1]
OUT=ROOT/'artifacts/intake-date-v56'


def page(path,title,paragraphs):
    c=canvas.Canvas(str(path),pagesize=A4,invariant=1)
    c.setFont('Song',20);c.drawCentredString(A4[0]/2,790,title)
    c.setFont('Song',10);c.drawString(55,760,'完全虚构验收材料；无真实客户、身份、签名或印章。')
    c.setFont('Song',13);y=720
    for paragraph in paragraphs:
        line=''
        for char in paragraph:
            if pdfmetrics.stringWidth(line+char,'Song',13)>480:
                c.drawString(55,y,line);y-=23;line=''
            line+=char
        if line:c.drawString(55,y,line);y-=23
        y-=12
    assert y>80
    c.showPage();c.save()


def main():
    OUT.mkdir(exist_ok=False)
    pdfmetrics.registerFont(TTFont('Song',r'C:\Windows\Fonts\simsun.ttc',subfontIndex=0))
    title,paragraphs=json.loads((ROOT/'artifacts/civil-loan-v53/source-transcript.json').read_text(encoding='utf8'))[0]
    paragraphs=[p.replace('合同载明签订日期：2026年1月5日。','合同签订日期：____年__月__日。') for p in paragraphs]
    first=OUT/'missing-date-contract.pdf';page(first,title,paragraphs)
    source=fitz.open(ROOT/'artifacts/civil-loan-v53/虚构金融借款案_八页扫描件.pdf')
    target=fitz.open(first);target.insert_pdf(source,from_page=1)
    missing=OUT/'虚构金融借款案_缺合同日期.pdf';target.save(missing)
    supplement=OUT/'虚构补充合同_不同日期.pdf'
    page(supplement,title,[paragraphs[0],paragraphs[1],paragraphs[2],
        '合同载明签订日期：2026年2月1日。与先前提供合同的日期不同，需核对。签字盖章区域未提供。'])
    records={}
    for kind,p in [('missing',missing),('supplement',supplement)]:
        d=fitz.open(p);d[0].get_pixmap(matrix=fitz.Matrix(1.5,1.5)).save(OUT/(kind+'.png'))
        records[kind]={'path':str(p),'sha256':hashlib.sha256(p.read_bytes()).hexdigest(),'pages':len(d),'first_page':d[0].get_text()}
    (OUT/'registry.json').write_text(json.dumps(records,ensure_ascii=False,indent=2),encoding='utf8')
    print(json.dumps({k:{a:v[a] for a in ('path','sha256','pages')} for k,v in records.items()},ensure_ascii=False))


if __name__=='__main__':main()
