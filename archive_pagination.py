"""Number the assembled volume in an added band without covering source content."""
import fitz
import re


def _balanced_page_stream(data):
    """Conservative PDF token scan: strings/resources cannot fake q/Q balance.

    Unsupported syntax (including inline BI binary payloads) fails closed. The
    narrow preservation path keeps a separately verified static stamp and its
    page content intact; neither may be rewritten by bake().
    """
    if len(data) > 2_000_000:
        return False
    operators = set(b"q Q cm w J j M d ri i gs m l c v y h re S s f F f* B B* b b* n W W* BT ET Tc Tw Tz TL Tf Tr Ts Td TD Tm T* Tj TJ ' \" d0 d1 CS cs SC SCN sc scn G g RG rg K k sh Do MP DP BMC BDC EMC BX EX".split())
    number = re.compile(rb"[+-]?(?:\d+(?:\.\d*)?|\.\d+)\Z")
    delimiters = b" \t\r\n\f\0()<>[]{}/%"
    stack, depth, text, i = [], 0, False, 0
    try:
        while i < len(data):
            c = data[i]
            if c in b" \t\r\n\f\0": i += 1; continue
            if c == 37:
                while i < len(data) and data[i] not in b"\r\n": i += 1
                continue
            if c == 40:
                nesting = 1; i += 1
                while i < len(data) and nesting:
                    if data[i] == 92: i += 2; continue
                    if data[i] == 40: nesting += 1
                    elif data[i] == 41: nesting -= 1
                    i += 1
                if nesting: return False
                continue
            if data[i:i+2] in (b"<<", b">>"):
                token = data[i:i+2]; i += 2
                if token == b"<<": stack.append(b">>")
                elif not stack or stack.pop() != b">>": return False
                continue
            if c == 60:
                end = data.find(b">", i+1)
                if end < 0 or re.search(rb"[^0-9A-Fa-f\s]", data[i+1:end]): return False
                i = end+1; continue
            if c in (91,93):
                i += 1
                if c == 91: stack.append(b"]")
                elif not stack or stack.pop() != b"]": return False
                continue
            if c == 47:
                i += 1
                while i < len(data) and data[i] not in delimiters: i += 1
                continue
            start = i
            while i < len(data) and data[i] not in delimiters: i += 1
            if start == i: return False
            token = data[start:i]
            if number.fullmatch(token) or token in (b"true",b"false",b"null"): continue
            if stack or token not in operators: return False
            if token == b"q": depth += 1
            elif token == b"Q":
                depth -= 1
                if depth < 0: return False
            elif token == b"BT":
                if text: return False
                text = True
            elif token == b"ET":
                if not text: return False
                text = False
        return not stack and depth == 0 and not text
    except Exception:
        return False


def _passive_pdf_object(obj):
    """Reject executable, external-file and interactive objects in the AP graph."""
    pdf = fitz.mupdf
    prohibited = {"A","AA","JS","JavaScript","OpenAction","FS","EF","EmbeddedFiles",
                  "RichMediaContent","RichMediaSettings","Sound","Movie","3DD","3DA","Ref","XFA"}
    seen, budget = set(), [2048]
    def visit(value, depth=0):
        budget[0] -= 1
        if budget[0] < 0 or depth > 32:return False
        if pdf.pdf_is_indirect(value):
            number = pdf.pdf_to_num(value)
            if number in seen:return True
            seen.add(number)
        if pdf.pdf_is_dict(value):
            keys = [pdf.pdf_to_name(pdf.pdf_dict_get_key(value,i)) for i in range(pdf.pdf_dict_len(value))]
            if set(keys) & prohibited or pdf.pdf_is_stream(value) and "F" in keys:return False
            if pdf.pdf_to_name(pdf.pdf_dict_gets(value,"Type")) in {"Action","Filespec","EmbeddedFile"}:return False
            if pdf.pdf_to_name(pdf.pdf_dict_gets(value,"Subtype")) in {"PS","RichMedia","Movie","Sound","3D","Screen","Widget","FileAttachment"}:return False
            if pdf.pdf_to_name(pdf.pdf_dict_gets(value,"S")) in {"JavaScript","Launch","GoToR","GoToE","URI","SubmitForm","ImportData","Rendition"}:return False
            # /P is the annotation's owning-page backlink, not an AP resource.
            # Links on that page are handled separately and excluded on copy.
            return all(visit(pdf.pdf_dict_gets(value,key),depth+1) for key in keys if not (depth == 0 and key == "P"))
        if pdf.pdf_is_array(value):
            return all(visit(pdf.pdf_array_get(value,i),depth+1) for i in range(pdf.pdf_array_len(value)))
        return True
    return visit(obj)


def _can_preserve_static_stamp_page(page):
    """Only one nonstandard print-only, action-free static AP may skip baking.

    Some seal producers use a proprietary annotation subtype excluded by
    Page.annots(). Inspect first_annot explicitly; never treat an empty iterator
    as proof that the page has no appearance objects.
    """
    try:
        if page.rotation or page.first_widget:
            return False
        if page.mediabox != page.rect or page.cropbox != page.rect:
            return False
        if page.parent.xref_get_key(page.xref,"UserUnit")[1] not in ("null","1"):
            return False
        annotation, candidates, count = page.first_annot, [], 0
        while annotation is not None:
            count += 1
            if count > 128:return False
            if annotation.type[0] != fitz.PDF_ANNOT_LINK:candidates.append(annotation)
            annotation = annotation.next
        # Internal navigation is copied separately, never retained as an action
        # in the static AP snapshot. Other active links retain the legacy path.
        if any(link['kind'] != fitz.LINK_GOTO for link in page.get_links()):return False
        if len(candidates) != 1:return False
        annotation = candidates[0]
        if annotation.type[0] != -1 or annotation.flags != 4:return False
        if annotation.rect.is_empty or not page.rect.contains(annotation.rect):return False
        pdf = fitz.mupdf
        obj = pdf.pdf_annot_obj(annotation.this)
        if not _passive_pdf_object(obj):return False
        ap = pdf.pdf_dict_gets(obj,"AP")
        if not pdf.pdf_is_dict(ap) or pdf.pdf_dict_len(ap) != 1 or pdf.pdf_to_name(pdf.pdf_dict_get_key(ap,0)) != "N":return False
        normal = pdf.pdf_dict_gets(ap,"N")
        if not pdf.pdf_is_stream(normal) or pdf.pdf_to_name(pdf.pdf_dict_gets(normal,"Subtype")) != "Form":return False
        return _balanced_page_stream(b"\n".join(page.parent.xref_stream(x) for x in page.get_contents()))
    except Exception:
        return False


def _clip_preserved_page(page, width, height):
    doc = page.parent
    streams = page.get_contents()
    first, last = doc.get_new_xref(), doc.get_new_xref()
    doc.update_object(first,"<<>>"); doc.update_stream(first,f"q\n0 0 {width:.8f} {height:.8f} re W n\n".encode("ascii"))
    doc.update_object(last,"<<>>"); doc.update_stream(last,b"\nQ\n")
    doc.xref_set_key(page.xref,"Contents","["+" ".join(f"{x} 0 R" for x in [first,*streams,last])+"]")
    page.set_mediabox(fitz.Rect(0,-24,width,height))


def _can_extend_scan_page(page):
    """Only an unrotated, full-page image with no hidden drawing can skip Forms.

    Expanding a general PDF page could expose previously clipped content. Keep
    the established clipping path unless both syntax and geometry are proven.
    """
    try:
        if page.rotation or page.first_annot or page.first_widget:
            return False
        if page.mediabox != page.rect or page.cropbox != page.rect:
            return False
        if page.parent.xref_get_key(page.xref, "UserUnit")[1] not in ("null", "1"):
            return False
        images = page.get_images(full=True)
        if len(images) != 1:
            return False
        image = images[0]
        rectangles = page.get_image_rects(image[0])
        if len(rectangles) != 1 or not page.rect.contains(rectangles[0]):
            return False
        # Do not interpret text, inline images, clipping, arbitrary PDF names,
        # forms, or unsupported operators as a safe single scan.
        stream = b"\n".join(page.parent.xref_stream(x) for x in page.get_contents())
        stream = re.sub(rb"%[^\r\n]*", b"", stream).strip()
        number = rb"[+-]?(?:\d+(?:\.\d*)?|\.\d+)"
        matrix = rb"(?:" + number + rb"\s+){6}cm"
        name = re.escape(image[7].encode("ascii"))
        draw = rb"/" + name + rb"\s+Do"
        token = rb"(?:q|Q|" + matrix + rb"|" + draw + rb")"
        if not re.fullmatch(token + rb"(?:\s+" + token + rb")*", stream):
            return False
        if len(re.findall(draw, stream)) != 1:
            return False
        depth = 0
        for value in re.findall(rb"(?<!\S)[qQ](?!\S)", stream):
            depth += 1 if value == b"q" else -1
            if depth < 0:
                return False
        return depth == 0
    except Exception:
        return False


def verify_volume_pagination(document, pagination):
    """Check logical body numbering independently of physical PDF positions."""
    mode, start = pagination.get("mode"), pagination.get("body_start")
    if mode not in ("draft", "body") or type(start) is not int or not 0 < start < len(document):
        raise ValueError("归档页码范围无效")
    for index, page in enumerate(document):
        expected = str(index-start+1) if mode == "body" and index >= start else ""
        if page.get_label() != expected:
            raise ValueError(f"PDF第{index+1}页标签与归档页码不一致")
        if not expected:
            continue
        band = fitz.Rect(0, page.rect.height-24, page.rect.width, page.rect.height)
        words = page.get_text("words", clip=band)
        if len(words) != 1 or words[0][4] != expected:
            raise ValueError(f"PDF第{index+1}页缺少正确的底部页码")
        x0, y0, x1, y1 = words[0][:4]
        if abs((x0+x1)/2 - page.rect.width/2) > 1 or y0 < band.y0 or y1 > band.y1:
            raise ValueError(f"PDF第{index+1}页页码未在底部居中")


def numbered_volume(source, *, start_page=0, style="legacy"):
    if type(start_page) is not int or not 0 <= start_page < len(source):
        raise ValueError("页码起始页无效")
    if style not in ("legacy", "body"):
        raise ValueError("未知页码样式")
    direct_scans = [_can_extend_scan_page(page) for page in source]
    # Nonstandard static seal APs can change pixels when bake() turns them into
    # page XObjects. Retain only explicitly verified passive APs before baking
    # ordinary annotations; preserve both the page and its original AP streams.
    preserved = {}
    for index,page in enumerate(source):
        if _can_preserve_static_stamp_page(page):
            with fitz.open() as copy:
                copy.insert_pdf(source,from_page=index,to_page=index,links=False,annots=True,widgets=False)
                preserved[index] = copy.tobytes()
    for page in source:
        if page.rotation:
            page.remove_rotation()
    links = [page.get_links() for page in source]
    toc = source.get_toc()
    # Flatten visible annotation/form appearances into the derived volume only.
    # Originals stored by the importer are never changed.
    source.bake(annots=True, widgets=True)
    result = fitz.open()
    count = len(source)
    for index, original in enumerate(source):
        width, height = original.rect.width, original.rect.height
        if index < start_page:
            result.insert_pdf(source, from_page=index, to_page=index, links=False, annots=False, widgets=False)
            continue
        if index in preserved:
            with fitz.open(stream=preserved[index],filetype="pdf") as copy:
                result.insert_pdf(copy,links=False,annots=True,widgets=False)
            page = result[-1]
            _clip_preserved_page(page,width,height)
        elif direct_scans[index]:
            # Retain the original image/content streams and their sampling.
            # Extending the PDF-coordinate bottom keeps its top/CTM unchanged.
            result.insert_pdf(source, from_page=index, to_page=index, links=False, annots=False, widgets=False)
            page = result[-1]
            page.set_mediabox(fitz.Rect(0, -24, width, height))
        else:
            page = result.new_page(width=width, height=height+24)
            page.show_pdf_page(fitz.Rect(0,0,width,height), source, index)
        label = str(index-start_page+1) if style == "body" else f"GD  {index+1} / {count}"
        page.insert_textbox(fitz.Rect(0,height+5,width,height+21), label,
                            fontname="helv", fontsize=9, align=1, color=(.25,.25,.25))
    for index, entries in enumerate(links):
        for link in entries:
            data = {key: value for key,value in link.items() if key not in ("xref","id")}
            result[index].insert_link(data)
    result.set_toc(toc)
    labels = [{"startpage":start_page,"prefix":"","style":"D","firstpagenum":1}]
    if start_page:
        labels.insert(0, {"startpage":0,"prefix":"","style":""})
    result.set_page_labels(labels)
    result.set_metadata(dict(source.metadata, producer="GD Workstation - continuous volume pagination"))
    return result
