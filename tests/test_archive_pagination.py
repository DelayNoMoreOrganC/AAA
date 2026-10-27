import fitz
import io
import pytest
from PIL import Image
from archive_pagination import numbered_volume, _can_extend_scan_page, _can_preserve_static_stamp_page, _balanced_page_stream


def test_numbering_preserves_visible_content_rotation_navigation_and_page_count(tmp_path):
    original = fitz.open()
    for rotation in (0,90,180,270):
        page=original.new_page(width=300,height=420)
        page.insert_text((35,60),"Source content, unchanged.",fontsize=12)
        page.draw_rect(fitz.Rect(10,350,290,400),color=(1,0,0),fill=(1,.9,.9))
        page.set_rotation(rotation)
    original[0].insert_link({'kind':fitz.LINK_GOTO,'from':fitz.Rect(20,70,150,95),'page':3,'to':fitz.Point(0,0)})
    original.set_toc([[1,'First',1],[1,'Fourth',4]])
    # Reload links written to the in-memory PDF before capturing them.
    original=fitz.open(stream=original.tobytes(),filetype='pdf')
    before=[p.get_pixmap().samples for p in original]
    bounds=[p.rect for p in original]
    numbered=numbered_volume(original)
    path=tmp_path/'numbered.pdf';numbered.save(path);numbered.close()
    with fitz.open(path) as final:
        assert len(final)==4
        assert final.get_toc()==[[1,'First',1],[1,'Fourth',4]]
        assert final[0].get_links()[0]['page']==3
        for index,page in enumerate(final):
            assert f'GD  {index+1} / 4' in page.get_text()
            assert page.get_pixmap(clip=bounds[index]).samples==before[index]
            assert page.get_label()==str(index+1)


def test_numbering_keeps_annotation_appearance(tmp_path):
    source=fitz.open();page=source.new_page(width=300,height=400)
    page.insert_text((40,50),'Annotated source')
    note=page.add_rect_annot(fitz.Rect(20,20,100,80));note.set_colors(stroke=(1,0,0));note.update()
    before=page.get_pixmap().samples
    final=numbered_volume(source)
    assert final[0].get_pixmap(clip=fitz.Rect(0,0,300,400)).samples==before
    final.close();source.close()


def scan_source(width=594.36,height=842.04,mode="L"):
    # A nonwhite last row makes fractional clipping/sampling changes observable.
    image=Image.new(mode,(1651,2339),0 if mode=="1" else 97)
    stream=io.BytesIO();image.save(stream,format="PNG")
    document=fitz.open();page=document.new_page(width=width,height=height)
    page.insert_image(page.rect,stream=stream.getvalue(),keep_proportion=False)
    return fitz.open(stream=document.tobytes(),filetype="pdf")


@pytest.mark.parametrize("size,mode",[((594.36,842.04),"L"),((590.04,837),"1"),((594.72,843.12),"1"),((595.44,842.76),"L")])
def test_fractional_scan_pages_keep_pixels_streams_and_navigation(tmp_path,size,mode):
    source=scan_source(*size,mode)
    source[0].insert_link({"kind":fitz.LINK_URI,"from":fitz.Rect(10,10,100,40),"uri":"https://example.invalid/fictional"})
    source.set_toc([[1,"Synthetic scan",1]])
    source=fitz.open(stream=source.tobytes(),filetype="pdf")
    assert _can_extend_scan_page(source[0])
    bounds=source[0].rect
    fitz.TOOLS.store_shrink(100)
    pixels=source[0].get_pixmap(alpha=False).samples
    image=source.xref_stream(source[0].get_images()[0][0])
    contents=b"".join(source.xref_stream(x) for x in source[0].get_contents())
    result=numbered_volume(source)
    result=fitz.open(stream=result.tobytes(garbage=3,deflate=True),filetype="pdf")
    fitz.TOOLS.store_shrink(100)
    assert result[0].get_pixmap(clip=bounds,alpha=False).samples==pixels
    # Saving with deflate may change compression, never decoded image samples.
    assert result.xref_stream(result[0].get_images()[0][0])==image
    assert contents in b"".join(result.xref_stream(x) for x in result[0].get_contents())
    assert not result[0].get_xobjects()
    assert result[0].get_links()[0]["uri"]=="https://example.invalid/fictional"
    assert result.get_toc()==[[1,"Synthetic scan",1]] and result[0].get_label()=="1"


@pytest.mark.parametrize("change",["cropped_image","hidden_text","annotation","widget","rotation","cropbox","unsupported_stream"])
def test_complex_or_hidden_content_never_uses_scan_extension(change):
    source=scan_source();page=source[0]
    if change=="cropped_image":
        x=page.get_contents()[0]
        source.update_stream(x,b"q 594.36 0 0 900 0 -40 cm /"+page.get_images()[0][7].encode()+b" Do Q")
    elif change=="hidden_text":page.insert_text((40,860),"HIDDEN_FICTIONAL_CONTENT")
    elif change=="annotation":page.add_rect_annot(fitz.Rect(20,20,60,60)).update()
    elif change=="widget":
        widget=fitz.Widget();widget.field_name="synthetic";widget.field_type=fitz.PDF_WIDGET_TYPE_TEXT;widget.rect=fitz.Rect(20,20,100,50);page.add_widget(widget)
    elif change=="rotation":page.set_rotation(90)
    elif change=="cropbox":page.set_cropbox(fitz.Rect(10,10,500,800))
    elif change=="unsupported_stream":
        x=page.get_contents()[0];source.update_stream(x,source.xref_stream(x)+b"\n0 0 m 5 5 l S")
    assert not _can_extend_scan_page(page)
    result=numbered_volume(source)
    assert result[0].get_xobjects(),"unsupported input must retain the clipping path"
    assert "HIDDEN_FICTIONAL_CONTENT" not in result[0].get_text()


def static_stamp_source():
    source=fitz.open();page=source.new_page(width=300.36,height=400.04)
    page.insert_text((30,50),'Fictional static seal page')
    # Hidden content lies in the future footer band and must stay clipped.
    page.draw_rect(fitz.Rect(10,405,90,415),color=(1,0,0),fill=(1,0,0))
    stamp=page.add_stamp_annot(fitz.Rect(40,200,180,260),stamp=0)
    stamp.set_flags(4);stamp.update()
    source.xref_set_key(stamp.xref,'Subtype','/FictionalStaticSeal')
    return fitz.open(stream=source.tobytes(),filetype='pdf')


def test_passive_nonstandard_stamp_preserves_pixels_and_clips_original_page():
    source=static_stamp_source();page=source[0]
    assert page.first_annot.type[0]==-1 and not list(page.annots())
    assert _can_preserve_static_stamp_page(page)
    page.insert_link({'kind':fitz.LINK_GOTO,'from':fitz.Rect(10,10,60,30),'page':0})
    source.set_toc([[1,'Fictional static stamp',1]])
    source=fitz.open(stream=source.tobytes(),filetype='pdf');bounds=fitz.Rect(source[0].rect)
    fitz.TOOLS.store_shrink(100);before=source[0].get_pixmap(alpha=False).samples
    original_contents=[source.xref_stream(x) for x in source[0].get_contents()]
    result=numbered_volume(source)
    result=fitz.open(stream=result.tobytes(garbage=3,deflate=True),filetype='pdf')
    fitz.TOOLS.store_shrink(100)
    assert result[0].get_pixmap(clip=bounds,alpha=False).samples==before
    page=result[0]
    assert page.first_annot.type[0]==-1 and page.first_annot.flags==4
    assert result.get_toc()==[[1,'Fictional static stamp',1]] and result[0].get_links()[0]['page']==0
    combined=b'\n'.join(result.xref_stream(x) for x in result[0].get_contents())
    assert all(content in combined for content in original_contents)
    # Avoid the centered page-number ink: this area used to contain hidden red.
    pixels=result[0].get_pixmap(clip=fitz.Rect(10,405,90,415),alpha=False).samples
    assert all(value==255 for value in pixels)


@pytest.mark.parametrize('change',['action','additional_action','attachment','nested_filespec','nested_action','nested_postscript','appearance_action','rollover','rotation','outside','invalid_stream'])
def test_nonstandard_stamp_preservation_fails_closed_for_active_or_unbounded_content(change):
    source=static_stamp_source();page=source[0];stamp=page.first_annot
    if change=='action':source.xref_set_key(stamp.xref,'A','<</S/JavaScript/JS(unsafe fictional)>>')
    elif change=='additional_action':source.xref_set_key(stamp.xref,'AA','<</E<</S/JavaScript/JS(unsafe fictional)>>>>')
    elif change=='attachment':source.xref_set_key(stamp.xref,'FS','<</Type/Filespec/F(fictional.txt)>>')
    elif change=='nested_filespec':source.xref_set_key(stamp.xref,'Info','<</Payload<</Type/Filespec/F(fictional.txt)>>>>')
    elif change=='nested_action':source.xref_set_key(stamp.xref,'Info','<</Payload<</Type/Action/S/Launch/F(fictional.txt)>>>>')
    elif change=='nested_postscript':source.xref_set_key(stamp.xref,'Info','<</Payload<</Subtype/PS>>>>')
    elif change=='appearance_action':
        ap=int(source.xref_get_key(stamp.xref,'AP/N')[1].split()[0]);source.xref_set_key(ap,'AA','<</E<</S/JavaScript/JS(unsafe fictional)>>>>')
    elif change=='rollover':
        value=source.xref_get_key(stamp.xref,'AP/N')[1];source.xref_set_key(stamp.xref,'AP/R',value)
    elif change=='rotation':page.set_rotation(90)
    elif change=='outside':
        source.xref_set_key(stamp.xref,'Rect','[40 -50 180 10]');page=source.reload_page(page)
    else:
        x=page.get_contents()[0];source.update_stream(x,b'Q\n'+source.xref_stream(x))
    assert not _can_preserve_static_stamp_page(page)


@pytest.mark.parametrize('data',[b'Q',b'q',b'q INVALID_OPERATOR Q',b'q (unterminated',b'BI /W 1 ID x EI',b'BT BT ET',b'q [Q] Q'])
def test_invalid_stream_cannot_escape_added_clip(data):
    assert not _balanced_page_stream(data)


def test_strings_comments_and_arrays_do_not_count_as_graphics_state_operators():
    assert _balanced_page_stream(b'q % Q is only a comment\nBT /F1 12 Tf [(q Q) -2 <7151>] TJ ET Q')
