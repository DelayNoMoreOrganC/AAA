"""Export supplied forms within the current case manifest without refilling them."""
from pathlib import Path
import os
import fitz
from ..core.v4_bridge import load


def original_form_sources(fields,name):
    return load('source_form_policy').original_form_sources(fields,name)


def form_fields_preserved(fields,name):
    return load('source_form_policy').form_fields_preserved(fields,name)


def all_original_form_refs(units, manifest, case_type):
    policy=load('source_form_policy')
    from archive_catalog import get_catalog
    norm=lambda p:os.path.normcase(os.path.abspath(p))
    scope={norm(r['path']):r for r in manifest or [] if r.get('path')}
    result={};seen=set()
    for item in get_catalog(case_type):
        selected=policy.source_units_for_item(item,units)
        if not selected:continue
        refs=[]
        for u in selected:
            row=scope.get(norm(u.source_path))
            if (not row or type(u.start_page) is not int or type(u.end_page) is not int
                    or type(row.get('pages')) is not int or not 0<=u.start_page<=u.end_page<row['pages']):
                raise ValueError('原始表单来源范围不一致')
            for page in range(u.start_page,u.end_page+1):
                anchor=(norm(u.source_path),page)
                if anchor in seen:raise ValueError('原始表单来源页重叠')
                seen.add(anchor)
            ref=dict(file_id=row['file_id'],filename=row.get('filename','原始表单'),
                     page=u.start_page+1,page_end=u.end_page+1)
            if item.templates[0]=='质量监督卡':ref['component']=u.doc_type
            refs.append(ref)
        result[item.templates[0]]=refs
    return result


def original_form_refs(units,manifest,case_type):
    refs=all_original_form_refs(units,manifest,case_type)
    if load('source_form_policy').missing_quality_components(refs.get('质量监督卡')):
        refs.pop('质量监督卡',None)
    return refs


def quality_component_refs(units,manifest,case_type):
    return all_original_form_refs(units,manifest,case_type).get('质量监督卡',[])


def export_original_form(name,units,output_dir,manifest,case_type):
    policy=load('source_form_policy')
    from archive_catalog import catalog_item_for_template
    if name not in policy.FORM_TYPES and name!='质量监督卡':raise ValueError('不支持的原始表单')
    refs=all_original_form_refs(units,manifest,case_type).get(name)
    if not refs:raise ValueError('未找到原始表单')
    selected=policy.source_units_for_item(catalog_item_for_template(case_type,name),units)
    with fitz.open() as result:
        for u in selected:
            with fitz.open(u.source_path) as source:
                result.insert_pdf(source,from_page=u.start_page,to_page=u.end_page)
        path=Path(output_dir)/(name+'_原件.pdf');result.save(path)
    return str(path)
