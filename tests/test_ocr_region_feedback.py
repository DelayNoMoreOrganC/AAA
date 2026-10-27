"""Local OCR geometry feeds existing bounded tools; no live API or OCR."""
import json
from types import SimpleNamespace
import pytest
from ocr_review import find_ocr_review_issues,normalized_review_box,ocr_read_payload
from visual_document_workflow import _tool_result,OperationValidationError


@pytest.mark.parametrize('box',[None,[],[0,0,1],[0,0,1,1,1],[0,0,0,1],
    [0,.8,1,.2],[-.1,0,1,1],[0,0,1,1.01],[False,0,1,1],
    [0,0,float('nan'),1],[0,0,float('inf'),1],['0',0,1,1]])
def test_bad_geometry_does_not_create_a_trusted_crop(box):
    assert normalized_review_box(box) is None


def test_regions_are_bounded_and_never_contain_ocr_text():
    text='虚构保密正文，不应复制进问题详情。'
    blocks=[dict(page_idx=0,text=text,confidence=.5,normalized_box=[.1,.2,.4,.3]) for _ in range(14)]
    blocks.append(dict(page_idx=0,text=text,confidence=.4,normalized_box=[0,0,float('nan'),1]))
    row,=find_ocr_review_issues({'fiction.pdf':[text]},{'fiction.pdf':blocks})
    assert row['low_confidence_blocks']==15 and row['unlocated_low_confidence_blocks']==1
    assert len(row['low_confidence_regions'])==12 and row['regions_truncated'] is True
    assert text not in json.dumps(row,ensure_ascii=False)
    assert row['reason_codes']==['low_confidence']


def test_legacy_geometry_stays_unknown_not_cleared():
    row,=find_ocr_review_issues({'a':['虚构测试正文']},{'a':[dict(page_idx=0,text='虚构测试正文',confidence=.5)]})
    assert row['low_confidence_regions']==[] and row['unlocated_low_confidence_blocks']==1
    assert row['reason_codes']==['sparse_ocr','low_confidence']


def pages():
    reads=[]
    p=SimpleNamespace(pages={'a':('private-path-a',1),'b':('private-path-b',1)},
        read=lambda key:reads.append(key) or '虚构正文',ocr_review=[
        dict(source_path='private-path-a',page=2,reason_codes=['low_confidence'],
             low_confidence_regions=[dict(box=[.1,.2,.4,.3],confidence=.5,characters=4)]),
        dict(source_path='private-path-b',page=2,reason_codes=['empty_text']),
        dict(source_path='private-path-a',page=3,reason_codes=['sparse_ocr'])])
    return p,reads


def test_same_page_feedback_is_available_without_extra_reads_or_paths():
    p,reads=pages()
    payload=ocr_read_payload(p,['a','a'])
    assert reads==['a']
    assert list(payload['本地识别定位提示'])==['a']
    assert payload['本地识别定位提示']['a'][0]['reason_codes']==['low_confidence']
    assert 'private-path' not in json.dumps(payload)


def test_existing_tool_can_inspect_feedback_crop_with_same_scope():
    p,reads=pages();images=[]
    p.image=lambda key,**args:images.append((key,args)) or {'type':'image_url','image_url':{'url':'fiction'}}
    result,keys=_tool_result({'tool':'read_text','page_ids':['a']},p,{'a'},{'a'})
    region=json.loads(result[0]['text'])['本地识别定位提示']['a'][0]['low_confidence_regions'][0]
    _tool_result({'tool':'inspect_page','page_id':'a','box':region['box']},p,{'a'},{'a'})
    assert reads==['a'] and images==[('a',dict(detail=True,box=[.1,.2,.4,.3],context_only=False))]


def test_cross_source_request_fails_before_reading_even_valid_page():
    p,reads=pages()
    with pytest.raises(OperationValidationError):
        _tool_result({'tool':'read_text','page_ids':['a','b']},p,{'a'},{'a'})
    assert reads==[]
