"""Display pixels from the verified original PDF, without browser PDF plugins."""
import math
import fitz


def raster_template_page(path, page):
    with fitz.open(path) as document:
        if not 1 <= page <= len(document):
            raise IndexError('page outside document')
        rect=document[page-1].rect
        if rect.width<=0 or rect.height<=0 or not math.isfinite(rect.width*rect.height):
            raise ValueError('invalid page dimensions')
        scale=min(1.6,2000/max(rect.width,rect.height))
        return document[page-1].get_pixmap(matrix=fitz.Matrix(scale,scale),alpha=False).tobytes('png'),len(document)
