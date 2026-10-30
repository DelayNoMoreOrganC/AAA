"""Coordinate-safe first-pass OCR views selected by visual observations."""
from io import BytesIO
from PIL import Image
from visual_page_view import PageView
from ocr_review import normalized_review_box


def ocr_input(pix, rotation):
    view=PageView(rotation=rotation)
    if not rotation:
        return pix.tobytes('png'),pix.width,pix.height,view
    image=Image.frombytes('RGB',(pix.width,pix.height),pix.samples)
    rotated=view.apply(image)
    output=BytesIO();rotated.save(output,format='PNG')
    return output.getvalue(),rotated.width,rotated.height,view


def original_box(points,width,height,view):
    if (not isinstance(points,(list,tuple)) or len(points)<4
            or any(not isinstance(point,(list,tuple)) or len(point)!=2
                   or any(type(v) not in (int,float) for v in point) for point in points)):
        return None
    try:
        mapped=[view.to_source(x/width,y/height) for x,y in points]
    except (TypeError,ValueError,ZeroDivisionError):
        return None
    return normalized_review_box([min(p[0] for p in mapped),min(p[1] for p in mapped),
                                  max(p[0] for p in mapped),max(p[1] for p in mapped)])
