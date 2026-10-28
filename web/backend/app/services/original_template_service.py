"""Fill retained law-firm templates in place; never reconstruct their tables.

Only document.xml text slots, fixed-cell typography, measured row-height locks, edit permissions
and standalone automatic footer page fields are changed. Other package members
remain identical to the Word conversion. Customer-provided originals do not use this filler.
PDFs must retain native reference pagination and table frames. Editable-cell
alignment is controlled separately from the retained frame geometry.
"""
from __future__ import annotations

from collections import Counter
from copy import deepcopy
from contextlib import contextmanager
from functools import wraps
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import tempfile
import unicodedata
from zipfile import ZipFile

from lxml import etree as ET

ROOT = Path(__file__).resolve().parents[4]
TEMPLATES = ROOT / 'templates' / 'workstation-originals'
RENDERER = 'lawfirm-original-v1'
W = 'http://schemas.openxmlformats.org/wordprocessingml/2006/main'
NS = {'w': W}
FILES = {
    '立案审批表': '立案审批表-归档用', '送达材料清单': '律师所送达材料清单',
    '档案卷宗': '律师业务档案卷宗（诉讼类）', '非诉封面': '律师业务档案卷宗（非诉讼类）',
    '结案报告表': '结案报告表--归档用', '质量监督卡': '律师办案质量监督卡+委托人须知（2021）',
}
# Physical XML cells, not the repeated python-docx grid cells of merged rows.
# Bounds are conservative input limits; native PDF geometry is the final gate.
SLOTS = {
 '立案审批表': [
  ('案件类别',0,1,12,''),('合同号',0,3,45,''),('委托人',1,1,60,''),('当事人',1,3,40,''),
  ('委托人电话',2,1,32,''),('传真',2,3,32,''),('收费标准',3,1,50,''),('地址',3,3,65,''),('对方当事人',4,1,100,''),
  ('案情简介',5,0,280,'案情简介：'),('立案审批日期',8,0,24,'立案日期：')],
 '档案卷宗': [
  ('案件类别',0,1,12,''),('合同号',0,3,45,''),('承办律师',1,1,70,''),('委托人',2,1,110,''),
  ('当事人',3,1,110,''),('对方当事人',4,1,110,''),('案由',5,1,200,''),('收案日期',6,1,24,''),
  ('结案日期',6,3,24,''),('审理法院',7,1,55,''),('审级',7,3,18,''),('法院收案号',8,1,100,''),
  ('审（办）结果',9,1,340,''),('归档日期',10,1,24,''),('立卷人',11,1,30,''),('__volume_pages',11,3,12,''),
  ('档案号',12,1,40,''),('保存期限',12,3,16,'')],
 '非诉封面': [
  ('案件类别',0,1,12,''),('合同号',0,3,45,''),('承办律师',1,1,70,''),('委托人',2,1,110,''),
  ('当事人',3,1,110,''),('对方当事人',4,1,110,''),('案由',5,1,200,''),('收案日期',6,1,24,''),
  ('结案日期',7,1,24,''),('审（办）结果',8,1,340,''),('归档日期',9,1,24,''),
  ('立卷人',10,1,30,''),('__volume_pages',10,3,12,''),('档案号',11,1,40,''),('保存期限',11,3,16,'')],
 '结案报告表': [
  ('案件类别',0,1,24,''),('委托人',1,1,110,''),('案件或项目名称',2,1,110,''),
  ('结案小结',3,1,320,''),('委托人对服务质量意见',4,1,320,''),('应收业务费',5,1,28,''),
  ('已收业务费',5,3,18,''),('尚欠业务费',6,1,28,''),('应退业务费',6,3,18,''),('结案日期',9,1,24,'')],
 '质量监督卡': [('律师事务所',0,1,100,''),('合同号',1,1,65,''),('承办律师',1,3,32,''),
  ('委托人联系地址及电话',2,1,90,'')],
}

# Fixed roles, never shrink-to-fit based on the current value. Narrative cells
# have room for readable leading; compact identity/date cells may wrap twice.
NARRATIVE_FIELDS = frozenset({'案情简介', '结案小结', '审（办）结果', '委托人对服务质量意见'})
FILL_FONT_HALF_POINTS = '24'


class OriginalTemplateError(RuntimeError):
    def __init__(self, code='render', fields=()):
        self.code = code if code in {'overflow','render','missing','page_count','frame'} else 'render'
        allowed = {slot[0] for slots in SLOTS.values() for slot in slots} | {'法院文件清单'}
        self.fields = sorted({key for key in fields if key in allowed and not key.startswith('__')})
        messages = {'overflow':'原表字段内容超出固定格容量，请压缩对应简要内容',
            'render':'原表渲染失败，请检查本机 Word 环境', 'missing':'原始表单底稿缺失或校验失败',
            'page_count':'填写后页数超出原表，请压缩内容后重试', 'frame':'填写后原表框格发生移动，请压缩内容后重试'}
        super().__init__(messages[self.code])


def _with_template_context(operation):
    """Keep the known original form identity when native verification fails."""
    @wraps(operation)
    def run(name, *args, **kwargs):
        try:
            return operation(name, *args, **kwargs)
        except OriginalTemplateError as error:
            error.template_name = name if type(name) is str and name in FILES and name != '非诉封面' else None
            raise
    return run


def _selected(name, fields):
    if name not in FILES or name == '非诉封面': raise OriginalTemplateError('missing')
    category = str((fields or {}).get('案件类别') or '')
    return '非诉封面' if name == '档案卷宗' and any(value in category for value in ('非诉','顾问','仲裁','咨询','代书')) else name


def template_metadata(name, fields=None):
    key = _selected(name, fields)
    filename = FILES[key] + '.docx'
    try:
        records = json.loads((TEMPLATES/'word-conversion-index.json').read_text(encoding='utf-8-sig'))
        row = next(item for item in records if item['docx'] == filename)
        source = next(item for item in json.loads((TEMPLATES/'source-index.json').read_text(encoding='utf8'))
                      if item['name'] == FILES[key] + '.doc')
        path = TEMPLATES/'word-converted'/filename
        if hashlib.sha256(path.read_bytes()).hexdigest() != row['sha256']: raise ValueError()
        geometry = json.loads((TEMPLATES/'layout-geometry.json').read_text(encoding='utf8'))[key]
        reference = TEMPLATES/'word-reference-pdf'/(FILES[key]+'.pdf')
        if hashlib.sha256(reference.read_bytes()).hexdigest() != geometry['reference_pdf_sha256']: raise ValueError()
        return {'renderer':RENDERER, 'template_key':key, 'source_sha256':source['sha256'],
            'template_sha256':row['sha256'], 'expected_pages':row['pages'], 'historical_template':True,
            'row_height_policy':'freeze_native_reference', 'frame_tolerance_points':0.2,
            'filled_cell_typography':'songti_12pt_field_spacing_v2',
            'reference_pdf_sha256':geometry['reference_pdf_sha256']}
    except Exception:
        raise OriginalTemplateError('missing') from None


def _tag(name): return '{'+W+'}'+name
def _compact(value): return re.sub(r'[\s\u200b\ufeff]+','',unicodedata.normalize('NFKC',str(value)))


def _without_template_page_fields(content):
    """Remove standalone PAGE fields from generated templates, never plain numbers.

    Keep paragraph properties and section/footer references so the native frame
    and pagination stay unchanged. Mixed text, drawings and unknown fields stay.
    Archive assembly is the sole source of generated continuous page numbers.
    """
    root=ET.fromstring(content);changed=False
    def is_page(instruction):
        return re.fullmatch(r'\s*PAGE(?:\s+\\\*\s+MERGEFORMAT)?\s*',instruction,re.I) is not None
    for paragraph in root.iter(_tag('p')):
        children=[child for child in paragraph if child.tag!=_tag('pPr')]
        if len(children)==1 and children[0].tag==_tag('fldSimple'):
            field=children[0]
            if not is_page(field.get(_tag('instr'),'')):continue
            if any(n.tag not in {_tag(k) for k in ('r','rPr','t','sz','rFonts','lang','rStyle')}
                   for n in field.iterdescendants()):continue
            if not re.fullmatch(r'\s*\d*\s*',''.join(field.xpath('.//w:t/text()',namespaces=NS))):continue
        else:
            if not children or any(child.tag!=_tag('r') for child in children):continue
            tokens=[n for run in children for n in run if n.tag!=_tag('rPr')]
            state='start';instruction='';valid=True
            for node in tokens:
                if node.tag==_tag('fldChar'):
                    kind=node.get(_tag('fldCharType'))
                    if kind=='begin' and state=='start':state='instruction'
                    elif kind=='separate' and state=='instruction':state='result'
                    elif kind=='end' and state in ('instruction','result'):state='end'
                    else:valid=False;break
                elif node.tag==_tag('instrText') and state=='instruction':instruction+=node.text or ''
                elif node.tag==_tag('t') and state=='result' and re.fullmatch(r'\s*\d*\s*',node.text or ''):pass
                else:valid=False;break
            if not valid or state!='end' or not is_page(instruction):continue
        for child in children:paragraph.remove(child)
        changed=True
    return ET.tostring(root,encoding='UTF-8',xml_declaration=True,standalone=True) if changed else content


def _fill(element, value, prefix='', permission_id=1, *, editable=True, narrative=False, compact_card=False):
    """Preserve paragraphs/properties, replace only slot content and add a run."""
    paragraphs = [element] if element.tag == _tag('p') else element.findall(_tag('p'))
    if not paragraphs: raise OriginalTemplateError('missing')
    first = paragraphs[0]
    original_properties = first.find(_tag('r')+'/'+_tag('rPr'))
    if original_properties is None:
        original_properties = first.find(_tag('pPr')+'/'+_tag('rPr'))
    original_properties = deepcopy(original_properties) if original_properties is not None else None
    for paragraph in paragraphs:
        for child in list(paragraph):
            if child.tag != _tag('pPr'): paragraph.remove(child)
    # Empty padding paragraphs formerly held auto-height cells open. Native
    # measured row heights now hold the frame, so the space is available for
    # the filled paragraph instead of stacking content above blank padding.
    if element.tag!=_tag('p'):
        for paragraph in paragraphs[1:]:element.remove(paragraph)
    # Rows are already locked to their measured reference heights. Only those
    # cells can discard the old large-font strut; keeping it wastes the second
    # line and can clip otherwise fitting text. Outside-table paragraphs still
    # retain their original strut/spacing so later table positions do not move.
    row = element.getparent() if element.tag == _tag('tc') else None
    height = row.find(_tag('trPr')+'/'+_tag('trHeight')) if row is not None and row.tag == _tag('tr') else None
    fixed_cell = height is not None and height.get(_tag('hRule')) == 'exact'
    fixed = ET.SubElement(first,_tag('r'))
    if original_properties is not None:fixed.append(original_properties)
    # WPS can reserve advance width for U+200B in these converted templates.
    # A synthetic zero-width prefix therefore indents only the first line.
    text = ET.SubElement(fixed,_tag('t')); text.text = prefix
    if editable:
        start = ET.SubElement(first,_tag('permStart')); start.set(_tag('id'),str(permission_id));start.set(_tag('edGrp'),'everyone')
    run = ET.SubElement(first,_tag('r')); props = ET.SubElement(run,_tag('rPr'))
    fonts = ET.SubElement(props,_tag('rFonts'))
    for attribute in ('ascii','hAnsi','eastAsia','cs'):fonts.set(_tag(attribute),'宋体')
    for tag,value_attr in (('sz',FILL_FONT_HALF_POINTS),('szCs',FILL_FONT_HALF_POINTS),('color','000000')):
        child=ET.SubElement(props,_tag(tag));child.set(_tag('val'),value_attr)
    lines = str(value or '').split('\n')
    for index,line in enumerate(lines):
        if index:ET.SubElement(run,_tag('br'))
        text=ET.SubElement(run,_tag('t'));text.set('{http://www.w3.org/XML/1998/namespace}space','preserve');text.text=line or '\u200b'
    if editable:
        end = ET.SubElement(first,_tag('permEnd'));end.set(_tag('id'),str(permission_id))
    if fixed_cell:
        paragraph_properties = first.find(_tag('pPr'))
        if paragraph_properties is None:
            paragraph_properties = ET.Element(_tag('pPr')); first.insert(0, paragraph_properties)
        spacing = paragraph_properties.find(_tag('spacing'))
        if spacing is None:spacing = ET.SubElement(paragraph_properties, _tag('spacing'))
        line_height = '360' if narrative else '240' if compact_card else '280'
        for key, setting in (('line',line_height), ('lineRule','exact'), ('before','0'), ('after','0'),
                             ('beforeAutospacing','0'), ('afterAutospacing','0')):
            spacing.set(_tag(key), setting)
        for key in ('beforeLines', 'afterLines'):spacing.attrib.pop(_tag(key), None)
        # Blank-form first-line offsets were for handwriting, not filled dates
        # or page counts. They otherwise consume the limited cell width.
        for old in paragraph_properties.findall(_tag('ind')):paragraph_properties.remove(old)
        indent=ET.SubElement(paragraph_properties,_tag('ind'))
        for key in ('firstLine','firstLineChars','left','leftChars','right','rightChars'):
            indent.set(_tag(key),'0')
        for key in ('autoSpaceDE','autoSpaceDN','snapToGrid'):
            node=paragraph_properties.find(_tag(key))
            if node is None:node=ET.SubElement(paragraph_properties,_tag(key))
            node.set(_tag('val'),'0')
        alignment = paragraph_properties.find(_tag('jc'))
        if alignment is None:alignment = ET.SubElement(paragraph_properties, _tag('jc'))
        alignment.set(_tag('val'), 'left')
        cell_properties = element.find(_tag('tcPr'))
        if cell_properties is not None:
            vertical = cell_properties.find(_tag('vAlign'))
            if vertical is None:vertical = ET.SubElement(cell_properties, _tag('vAlign'))
            vertical.set(_tag('val'), 'top' if narrative else 'center')
        # Normalize the visible prefix and the zero-width/paragraph-end runs as
        # well as input text; no original literal label is removed.
        for target in [*first.findall(_tag('r')), paragraph_properties]:
            properties = target.find(_tag('rPr'))
            if properties is None:properties = ET.SubElement(target, _tag('rPr'))
            fonts = properties.find(_tag('rFonts'))
            if fonts is None:fonts = ET.SubElement(properties, _tag('rFonts'))
            for key in ('ascii','hAnsi','eastAsia','cs'):fonts.set(_tag(key), '宋体')
            for key in ('sz','szCs'):
                size = properties.find(_tag(key))
                if size is None:size = ET.SubElement(properties, _tag(key))
                size.set(_tag('val'), FILL_FONT_HALF_POINTS)


def frame_signature(document_xml):
    root=ET.fromstring(document_xml)
    # Alignment affects text placement, not the table frame. Native PDF frame
    # comparison still checks every retained boundary after export.
    for node in root.xpath('//w:tcPr/w:vAlign',namespaces=NS):node.getparent().remove(node)
    for node in root.xpath('//w:trPr/w:trHeight',namespaces=NS):node.getparent().remove(node)
    for node in root.xpath('//w:trPr',namespaces=NS):
        if not len(node) and not node.attrib:node.getparent().remove(node)
    expressions=('//w:sectPr','//w:tblPr','//w:tblGrid','//w:trPr','//w:tcPr')
    return tuple(ET.tostring(node,method='c14n') for expr in expressions for node in root.xpath(expr,namespaces=NS))


def _fill_delivery_identity(paragraph, client, lawyers):
    """Use the original 31.2pt header band for two readable 15.6pt lines.

    The old 16pt blank heading occupied two document-grid lines already. Two
    explicit lines keep that exact band and avoid name/lawyer collisions. Frame
    and complete-text verification remain mandatory after native export.
    """
    _fill(paragraph, client + '\n承办律师：' + lawyers, '委托方：', 231)
    properties = paragraph.find(_tag('pPr'))
    if properties is None:
        properties = ET.Element(_tag('pPr'));paragraph.insert(0, properties)
    spacing = properties.find(_tag('spacing'))
    if spacing is None:spacing = ET.SubElement(properties, _tag('spacing'))
    for key, value in (('line','312'),('lineRule','exact'),('before','0'),('after','0'),
                       ('beforeAutospacing','0'),('afterAutospacing','0')):
        spacing.set(_tag(key), value)
    for key in ('beforeLines','afterLines'):spacing.attrib.pop(_tag(key),None)
    grid = properties.find(_tag('snapToGrid'))
    if grid is None:grid = ET.SubElement(properties,_tag('snapToGrid'))
    grid.set(_tag('val'),'0')
    for target in [properties, *paragraph.findall(_tag('r'))]:
        props = target.find(_tag('rPr'))
        if props is None:props = ET.SubElement(target,_tag('rPr'))
        for key in ('sz','szCs'):
            size = props.find(_tag(key))
            if size is None:size = ET.SubElement(props,_tag(key))
            size.set(_tag('val'),FILL_FONT_HALF_POINTS)


def _values(name, fields, organization, derived):
    from .preview_fields import build_preview
    values={entry['key']:str(entry.get('display_value', entry['value']) or '') for entry in build_preview(name,fields)['fields']}
    # The account's organization is configuration, never evidence about this
    # case. The quality-card firm uses the same editable business field and
    # assurance as the preview; absent (including human-cleared) stays blank.
    number=(derived or {}).get('volume_page_count')
    values['__volume_pages']=str(number)+' 页' if type(number) is int and number > 0 else ''
    if name == '送达材料清单':
        from ..core.v4_bridge import load
        counts=load('form_drafts').court_inventory_page_counts(fields)
        for index,count in enumerate(counts):
            values[f'__delivery_pages_{index}']=str(count) if count is not None else ''
    return values


def approval_custom_value(fields, row):
    """Explicit custom content, including an intentional blank, wins."""
    custom=((fields or {}).get('_preview_custom_values') or {}).get('立案审批表') or {}
    key=f'p0-b0-r{row}-c0'
    if key in custom:
        return str(custom[key] or ''), False
    if row == 9:
        from ..core.v4_bridge import load
        fee=load('form_cell_contracts').optional_output('收费标准',(fields or {}).get('收费标准',''),fields or {})
        if fee and not fee['value']:return '',False
        presentation=load('fee_display').current(fields)
        if presentation:return presentation['note'], True
        note=load('source_fee_notice').reference_note(fields)
        if not note:
            refs=(fields.get('_provenance') or {}).get('收费标准') or []
            refs=[refs] if isinstance(refs,dict) else refs
            if any(load('engagement_intake').current_support(ref,fields) is not None for ref in refs):
                note='风险代理费的比例、条件及上限详卷内委托代理合同第四条。'
        return note, bool(note)
    return '', False


def _explicit_body_grid(root, key):
    """Resolve inherited line-grid spacing without changing cells or fonts.

    These templates use a 15.6pt grid. LibreOffice rounds automatic line boxes
    up to TWO grid lines where WPS uses one, pushing the notice onto page 3.
    Keep the original text/blank signing paragraphs and explicit heading bands.
    Only out-of-table explanatory text is normalized; no form frame is moved.
    """
    # WPS resolves the legacy *_GB2312 aliases to installed FangSong/KaiTi.
    # LibreOffice otherwise substitutes wider YaHei and changes line wraps.
    for fonts in root.xpath('//w:rFonts',namespaces=NS):
        for attr,value in list(fonts.attrib.items()):
            if value in ('仿宋_GB2312','楷体_GB2312'):
                fonts.set(attr,{'仿宋_GB2312':'仿宋','楷体_GB2312':'楷体'}[value])
    paragraphs=root.find(_tag('body')).findall(_tag('p'))
    active=False
    for paragraph in paragraphs:
        text=''.join(paragraph.xpath('.//w:t/text()',namespaces=NS))
        if key=='质量监督卡' and re.sub(r'\s+','',text)=='委托人须知':
            active=True
            previous=paragraph.getprevious()
            # A separate empty paragraph containing a page-break leaves an
            # extra blank band in LO. Attach that same break to the title.
            if (previous is not None and previous.tag==_tag('p')
                    and not ''.join(previous.xpath('.//w:t/text()',namespaces=NS)).strip()
                    and not previous.xpath('.//w:t|.//w:sectPr|.//w:drawing|.//w:object|.//w:fldChar|.//w:instrText|.//w:bookmarkStart',namespaces=NS)):
                props=paragraph.find(_tag('pPr'))
                if props is None:props=ET.Element(_tag('pPr'));paragraph.insert(0,props)
                br=ET.SubElement(props,_tag('pageBreakBefore'));br.set(_tag('val'),'1')
                previous.getparent().remove(previous)
        selected=(key=='质量监督卡' and active) or (key=='送达材料清单' and text.startswith('律师在接办案件中填写'))
        if not selected:continue
        props=paragraph.find(_tag('pPr'))
        if props is None:props=ET.Element(_tag('pPr'));paragraph.insert(0,props)
        spacing=props.find(_tag('spacing'))
        if spacing is not None and spacing.get(_tag('lineRule'))=='exact':
            # The empty separator after the notice's revision heading used a
            # 28pt title strut. Keep one normal blank line (15.6pt), preserving
            # all later signature/date blanks and every printed character.
            if key=='质量监督卡' and active and not text.strip() and spacing.get(_tag('line'))=='560':
                spacing.set(_tag('line'),'312')
            continue
        if spacing is None:spacing=ET.SubElement(props,_tag('spacing'))
        for k,v in (('line','312'),('lineRule','exact'),('before','0'),('after','0')):spacing.set(_tag(k),v)
        grid=props.find(_tag('snapToGrid'))
        if grid is None:grid=ET.SubElement(props,_tag('snapToGrid'))
        grid.set(_tag('val'),'0')


@_with_template_context
def fill_original_docx(name, fields, organization_name, output_path, *, derived_output=None):
    fields=fields or {}
    metadata=template_metadata(name,fields);key=metadata['template_key']
    source=TEMPLATES/'word-converted'/(FILES[key]+'.docx')
    values=_values(name,fields,organization_name,derived_output)
    with ZipFile(source) as package:
        original=package.read('word/document.xml');root=ET.fromstring(original)
        table=root.find('.//'+_tag('body')+'/'+_tag('tbl'))
        try:
            geometry=json.loads((TEMPLATES/'layout-geometry.json').read_text(encoding='utf8'))[key]
            rows=table.findall(_tag('tr'))
            if len(rows)!=len(geometry['native_row_heights_twips']):raise ValueError()
            for row,height in zip(rows,geometry['native_row_heights_twips']):
                properties=row.find(_tag('trPr'))
                if properties is None:
                    properties=ET.Element(_tag('trPr'));row.insert(0,properties)
                for old in properties.findall(_tag('trHeight')):properties.remove(old)
                fixed=ET.SubElement(properties,_tag('trHeight'));fixed.set(_tag('val'),str(height));fixed.set(_tag('hRule'),'exact')
        except Exception:raise OriginalTemplateError('missing') from None
        over=[field for field,_,_,limit,_ in SLOTS.get(key,[]) if len(values.get(field,''))>limit]
        if over:raise OriginalTemplateError('overflow',over)
        for identifier,(field,row,col,_,prefix) in enumerate(SLOTS.get(key,[]),1):
            cell=table.findall(_tag('tr'))[row].findall(_tag('tc'))[col]
            _fill(cell,values.get(field,''),prefix,identifier,editable=not field.startswith('__'),
                  narrative=field in NARRATIVE_FIELDS, compact_card=key=='质量监督卡')
        if key=='立案审批表':
            for row,label in ((6,'承办律师意见：'),(7,'主任审批意见：'),(9,'备  注：')):
                text,_=approval_custom_value(fields,row)
                # Custom opinion cells are not the case-summary field. Keep the
                # form target without directing an edit to an unrelated value.
                if len(text)>200:raise OriginalTemplateError('overflow')
                _fill(table.findall(_tag('tr'))[row].findall(_tag('tc'))[0],text,label,100+row,narrative=True)
        if key=='送达材料清单':
            lines=[line.strip() for line in values.get('法院文件清单','').splitlines() if line.strip()]
            # Citation annotations are retained in field provenance, outside the
            # fixed short name cells. No title or document is silently removed.
            lines=[re.sub(r'（原材料第[0-9—\-]+页）$','',line) for line in lines]
            if len(lines)>18 or any(len(line)>26 for line in lines):raise OriginalTemplateError('overflow',['法院文件清单'])
            for index in range(18):
                cells=table.findall(_tag('tr'))[index+1].findall(_tag('tc'))
                _fill(cells[1],lines[index] if index<len(lines) else '',permission_id=200+index)
                _fill(cells[2],values.get(f'__delivery_pages_{index}',''),permission_id=250+index)
            paragraphs=root.find(_tag('body')).findall(_tag('p'))
            for field,limit in (('合同号',80),('委托人',45),('承办律师',25)):
                if len(values.get(field,''))>limit:raise OriginalTemplateError('overflow',[field])
            _fill(paragraphs[1],values.get('合同号',''), '案号：', 230)
            _fill_delivery_identity(paragraphs[2],values.get('委托人',''),values.get('承办律师',''))
        # Converted templates can end with a bare paragraph after the firm
        # credit. LibreOffice moves that empty paragraph to a second page.
        # Remove only structurally empty trailing paragraphs, never content,
        # paragraph properties, section breaks or the required post-table p.
        body = root.find(_tag('body'))
        tail = len(body) - 2 if body[-1].tag == _tag('sectPr') else len(body) - 1
        while tail > 0 and body[tail].tag == _tag('p') and len(body[tail]) == 0 and not (body[tail].text or '').strip() and body[tail-1].tag == _tag('p'):
            body.remove(body[tail]); tail -= 1
        _explicit_body_grid(root,key)
        edited=ET.tostring(root,encoding='UTF-8',xml_declaration=True,standalone=True)
        if frame_signature(original)!=frame_signature(edited):raise OriginalTemplateError('frame')
        output=Path(output_path);output.parent.mkdir(parents=True,exist_ok=True)
        settings=ET.fromstring(package.read('word/settings.xml'))
        for old in settings.findall(_tag('documentProtection')):settings.remove(old)
        protection=ET.SubElement(settings,_tag('documentProtection'));protection.set(_tag('edit'),'readOnly');protection.set(_tag('enforcement'),'1')
        with ZipFile(output,'w') as result:
            for entry in package.infolist():
                content=edited if entry.filename=='word/document.xml' else ET.tostring(settings,encoding='UTF-8',xml_declaration=True,standalone=True) if entry.filename=='word/settings.xml' else package.read(entry.filename)
                if re.fullmatch(r'word/footer\d+\.xml',entry.filename):
                    content=_without_template_page_fields(content)
                result.writestr(entry,content)
    return str(output)


def _pdf_frames(document):
    frames=[]
    for page in document:
        lines=[]
        for drawing in page.get_drawings():
            for item in drawing.get('items',[]):
                if item[0]=='l':
                    p,q=item[1:3]
                    if abs(p.x-q.x)<.2 or abs(p.y-q.y)<.2:
                        if abs(p.x-q.x)+abs(p.y-q.y)>15:lines.append(tuple(round(v,1) for v in (p.x,p.y,q.x,q.y)))
                elif item[0]=='re':lines.append(tuple(round(v,1) for v in item[1]))
        frames.append(sorted(lines))
    return frames


def _field_regions(meta, values, custom_values=None):
    """Locate editable cells from the native reference, including merged cells."""
    import fitz
    key=meta['template_key']
    geometry=json.loads((TEMPLATES/'layout-geometry.json').read_text(encoding='utf8'))[key]
    boundaries=geometry['reference_row_boundaries_pt']
    with fitz.open(TEMPLATES/'word-reference-pdf'/(FILES[key]+'.pdf')) as reference:
        frame=_pdf_frames(reference)[0]
    slots=[(field,row,col,values.get(field,'')) for field,row,col,*_ in SLOTS.get(key,[])]
    if key=='立案审批表':
        # These are manual opinion slots, not the case-summary field. Fail at
        # form level rather than asking the user to change an unrelated fact.
        slots.extend(('',row,0,str((custom_values or {}).get(f'p0-b0-r{row}-c0') or ''))
                     for row in (6,7,9))
    if key=='送达材料清单':
        lines=[re.sub(r'（原材料第[0-9—\-]+页）$','',line.strip())
               for line in values.get('法院文件清单','').splitlines() if line.strip()]
        slots=[('法院文件清单',index+1,1,line) for index,line in enumerate(lines)]
        slots.extend(('法院文件清单',index+1,2,values.get(f'__delivery_pages_{index}','')) for index in range(len(lines)))
    regions=[]
    for field,row,col,value in slots:
        if not _compact(value):continue
        top,bottom=boundaries[row:row+2];middle=(top+bottom)/2
        xs=sorted({round(a,1) for a,b,c,d in frame
                   if abs(a-c)<.2 and min(b,d)<=middle<=max(b,d)})
        if col+1>=len(xs):raise OriginalTemplateError('missing')
        regions.append({'field':field,'page':0,'rect':(xs[col],top,xs[col+1],bottom),'text':value})
    return regions


def verify_original_pdf(path, *, expected_pages, reference_pdf=None, expected_texts=(), field_texts=None, field_regions=()):
    import fitz
    try:
        with fitz.open(path) as document:
            if len(document)!=expected_pages:raise OriginalTemplateError('page_count')
            text=_compact(''.join(page.get_text() for page in document))
            missing=[value for value in expected_texts if _compact(value) and _compact(value) not in text]
            if missing:
                fields=[key for key,values in (field_texts or {}).items()
                    if any(_compact(value) in {_compact(item) for item in missing} for value in values)]
                raise OriginalTemplateError('overflow',fields)
            # PDF text extraction can include text clipped by an exact-height
            # table row. Presence anywhere on the page is not proof of fit.
            failed=[]
            for region in field_regions:
                left,top,right,bottom=region['rect'];parts=[]
                for block in document[region['page']].get_text('rawdict',sort=True)['blocks']:
                    for line in block.get('lines',[]):
                        for span in line.get('spans',[]):
                            for char in span.get('chars',[]):
                                x0,y0,x1,y1=char['bbox']
                                # A sub-point font box overhang is normal; the
                                # old cropped second line exceeded 3 points.
                                if x0>=left-.6 and x1<=right+.6 and y0>=top-.6 and y1<=bottom+.6:
                                    parts.append(char['c'])
                if _compact(region['text']) not in _compact(''.join(parts)):
                    failed.append(region['field'])
            if failed:raise OriginalTemplateError('overflow',failed)
            if reference_pdf:
                with fitz.open(reference_pdf) as reference:
                    actual,expected=_pdf_frames(document),_pdf_frames(reference)
                    if len(actual)!=len(expected) or any(len(a)!=len(b) or any(
                        len(x)!=len(y) or any(abs(v-w)>.201 for v,w in zip(x,y)) for x,y in zip(a,b))
                        for a,b in zip(actual,expected)):raise OriginalTemplateError('frame')
    except OriginalTemplateError:raise
    except Exception:raise OriginalTemplateError('render') from None


@contextmanager
def _word_render_lock():
    """One native Word export across threads AND workstation processes."""
    if os.name!='nt':raise OriginalTemplateError('render')
    import ctypes
    from ctypes import wintypes
    kernel=ctypes.WinDLL('kernel32',use_last_error=True)
    kernel.CreateMutexW.argtypes=[ctypes.c_void_p,wintypes.BOOL,wintypes.LPCWSTR]
    kernel.CreateMutexW.restype=wintypes.HANDLE
    kernel.WaitForSingleObject.argtypes=[wintypes.HANDLE,wintypes.DWORD]
    kernel.ReleaseMutex.argtypes=[wintypes.HANDLE]
    kernel.CloseHandle.argtypes=[wintypes.HANDLE]
    handle=kernel.CreateMutexW(None,False,'Local\\GDWorkstationOriginalWordRendering')
    if not handle:raise OriginalTemplateError('render')
    acquired=False
    try:
        acquired=kernel.WaitForSingleObject(handle,120000) in (0,0x80)
        if not acquired:raise OriginalTemplateError('render')
        yield
    finally:
        if acquired:kernel.ReleaseMutex(handle)
        kernel.CloseHandle(handle)


def convert_docx_to_pdf(docx_path, output_pdf, *, expected_pages, reference_pdf=None, expected_texts=(), field_texts=None, field_regions=()):
    output=Path(output_pdf);output.parent.mkdir(parents=True,exist_ok=True)
    fd,temporary=tempfile.mkstemp(suffix='.pdf',prefix='original-',dir=output.parent);os.close(fd);Path(temporary).unlink()
    try:
        worker=Path(__file__).with_name('original_template_worker.py')
        with _word_render_lock():
            result=subprocess.run([sys.executable,str(worker),str(docx_path),temporary],stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL,
                timeout=90,creationflags=subprocess.CREATE_NO_WINDOW if os.name=='nt' else 0)
        if result.returncode or not Path(temporary).is_file():raise OriginalTemplateError('render')
        verify_original_pdf(temporary,expected_pages=expected_pages,reference_pdf=reference_pdf,expected_texts=expected_texts,field_texts=field_texts,field_regions=field_regions)
        os.replace(temporary,output)
        return str(output)
    except OriginalTemplateError:raise
    except Exception:raise OriginalTemplateError('render') from None
    finally:Path(temporary).unlink(missing_ok=True)


@_with_template_context
def render_original_pdf(name, fields, organization_name, output_pdf, *, derived_output=None):
    meta=template_metadata(name,fields)
    docx=fill_original_docx(name,fields,organization_name,str(Path(output_pdf).with_suffix('.docx')),derived_output=derived_output)
    reference=TEMPLATES/'word-reference-pdf'/(FILES[meta['template_key']]+'.pdf')
    if not reference.is_file():raise OriginalTemplateError('missing')
    with ZipFile(docx) as package:
        root=ET.fromstring(package.read('word/document.xml'))
        expected=[]
        for start in root.xpath('//w:permStart',namespaces=NS):
            parts=[]
            for sibling in start.itersiblings():
                if sibling.tag==_tag('permEnd'):break
                parts.extend(sibling.xpath('.//w:t/text()',namespaces=NS))
            if _compact(''.join(parts)):expected.append(''.join(parts))
    # Derived/admin-owned values are read-only but must also be visible.
    values=_values(name,fields,organization_name,derived_output)
    expected.extend(values.get(field,'') for field,*_ in SLOTS.get(meta['template_key'],[]) if field.startswith('__'))
    field_texts={field:[values.get(field,'')] for field,*_ in SLOTS.get(meta['template_key'],[])}
    if name=='送达材料清单':
        field_texts['法院文件清单']=[re.sub(r'（原材料第[0-9—\-]+页）$','',line.strip())
            for line in values.get('法院文件清单','').splitlines() if line.strip()]
    return convert_docx_to_pdf(docx,output_pdf,expected_pages=meta['expected_pages'],reference_pdf=reference,expected_texts=expected,field_texts=field_texts,
                               field_regions=_field_regions(meta,values,((fields or {}).get('_preview_custom_values') or {}).get(name)))
