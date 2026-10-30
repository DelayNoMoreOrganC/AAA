"""Bounded initial visual aids. Original files and text caches remain untouched.

Orientation is an observation, not a verified correction. Detail crops use only
already available OCR locations, never OCR this page merely to create a crop.
"""
import json
import math
from visual_page_view import PageView
from ocr_review import normalized_review_box

MAX_DETAIL_VIEWS = 2


def _rotation(row):
    value = (row.get('observation') or {}).get('suggested_rotation')
    return value if type(value) is int and value in (0,90,180,270) else 0


def _context_box(box):
    left,top,right,bottom = box
    x,y=(left+right)/2,(top+bottom)/2
    width,height=max(right-left+.04,.12),max(bottom-top+.02,.08)
    return [max(0,x-width/2),max(0,y-height/2),min(1,x+width/2),min(1,y+height/2)]


def prepare_reading_views(pages, selection, rows_by_id, *, allowed, preferred_boxes=None, previous_views=None):
    """Return per-page multimodal content, safe audit metadata and seen views."""
    if (not isinstance(selection,list) or not selection or len(selection)>4
            or any(type(k) is not str or k not in allowed or k not in pages.pages or k not in rows_by_id
                   or not isinstance(rows_by_id[k],dict) or rows_by_id[k].get('page_id')!=k for k in selection)
            or len(selection)!=len(set(selection))):
        raise ValueError('INITIAL_VIEW_SCOPE_INVALID')
    # Advisory model locations never establish a fact. Use original-page
    # coordinates and surrounding context, only for already authorized pages.
    candidates=[]
    preferred_boxes = preferred_boxes if isinstance(preferred_boxes,dict) else {}
    previous_views = previous_views if isinstance(previous_views,set) else set()
    for index,key in enumerate(selection):
        preferred = normalized_review_box(preferred_boxes.get(key))
        if preferred is not None:
            candidates.append((0,0,index,key,_context_box(preferred),'field_candidate_region'))
            continue  # Do not substitute an unrelated OCR region for this target.
        path,number=pages.pages[key]
        for review in getattr(pages,'ocr_review',[]) or []:
            if (not isinstance(review,dict) or review.get('source_path')!=path
                    or type(review.get('page')) is not int or review['page']!=number+1):
                continue
            for region in review.get('low_confidence_regions',[]) or []:
                if not isinstance(region,dict):continue
                box=normalized_review_box(region.get('box'))
                score=region.get('confidence')
                if (box is None or type(score) not in (int,float) or not math.isfinite(score) or not 0<=score<.75
                        or (box[2]-box[0])*(box[3]-box[1])>=.85):
                    continue
                candidates.append((1,score,index,key,_context_box(box),'cached_low_confidence_detail'))
    candidates.sort(key=lambda row:(row[0],row[1],row[2],row[4]))
    crops={}
    for _,_,_,key,box,purpose in candidates:
        if ('inspect_page',key,tuple(box),_rotation(rows_by_id[key])) in previous_views:
            continue
        if key not in crops and len(crops)<MAX_DETAIL_VIEWS:
            crops[key]=(box,purpose)
    content,metadata,executed={},{},set()
    for key in selection:
        rotation=_rotation(rows_by_id[key])
        views=[(PageView(rotation=rotation),'initial_full_page')]
        if key in crops:
            box,purpose=crops[key]
            views.append((PageView(box,rotation),purpose))
        content[key],metadata[key]=[],[]
        for view,purpose in views:
            signature=('inspect_page',key,view.box,view.rotation)
            if signature in previous_views or signature in executed:
                continue
            info={**view.metadata(key),'purpose':purpose,'orientation_basis':'model_observation' if rotation else 'original_display',
                  'status':'view_prepared_not_legibility_verified',
                  'note':'坐标映射到原页；图像是辅助查看，未证明识别正确。必要时可inspect_page旋转0查看原方向，或选择不同原页区域。'}
            options={'detail':True}
            if view.box!=(0,0,1,1):options['box']=list(view.box)
            if view.rotation:options['rotation']=view.rotation
            rendered=pages.image(key,**options)
            content[key].extend([{'type':'text','text':json.dumps(info,ensure_ascii=False)},rendered])
            metadata[key].append(info)
            executed.add(signature)
    return content,metadata,executed
