import fitz
from local_ocr import ordered_text_layer
from pdf_doc_locator import segment_by_catalog


def test_office_fallback_font_run_is_sorted_on_baseline():
    document=fitz.open();p=document.new_page()
    p.insert_text((50,80),'民事起',fontname='china-s',fontsize=26)
    p.insert_text((154,80),'状',fontname='china-s',fontsize=26)
    p.insert_text((128,80),'诉',fontname='china-s',fontsize=26)
    assert '民事起诉状' in ordered_text_layer(p)


def test_independent_poa_first_page_not_suppressed_by_nonheading_ocr_blocks():
    text='授权委托书\n委托人：星河演示贸易有限公司\n受托人：陈示例律师\n授权范围：代为提交材料。'
    units=segment_by_catalog([text],'civil',config={},layout_blocks=[{'page_idx':0,'type':'text','text':text}],log=lambda _:None)
    assert [(u.doc_type,u.catalog_seq,u.start_page,u.end_page) for u in units]==[('poa',4,0,0)]
