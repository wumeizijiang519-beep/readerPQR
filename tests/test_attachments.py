import asyncio
import json
import threading
import fitz
import httpx
import pytest
from readerpqr.attachments import load_attachments, validate_paths
from readerpqr.qa import ask_paper
from readerpqr.translate import Cancelled
from test_qa import paper, settings


def test_extract_pdf_pages_and_text_encoding(tmp_path):
    pdf = tmp_path / 'extra.pdf'
    with fitz.open() as doc:
        for text in ['First evidence', 'Second evidence']:
            page = doc.new_page()
            page.insert_text((72,72), text)
        doc.save(pdf)
    txt = tmp_path / 'notes.txt'
    txt.write_bytes('实验补充'.encode('gb18030'))
    rows = load_attachments([pdf,txt,pdf])
    assert len(rows) == 2
    assert '[第2页]' in rows[0]['text'] and 'Second evidence' in rows[0]['text']
    assert rows[1]['text'] == '实验补充'
    assert rows[0]['name'] == 'extra.pdf'


def test_attachment_payload_and_no_local_path(tmp_path):
    txt = tmp_path / 'notes.md'
    txt.write_text('unique supplementary evidence',encoding='utf-8')
    def handle(request):
        body = json.loads(request.content)
        content = json.loads(body['messages'][-1]['content'])
        assert content['attachments'] == [{'id':'附件1','name':'notes.md','text':'unique supplementary evidence'}]
        assert str(tmp_path) not in body['messages'][-1]['content']
        return httpx.Response(200,json={'choices':[{'message':{'content':'依据 [附件1 notes.md]'}}]})
    assert '附件1' in asyncio.run(ask_paper(paper(),settings(),'补充说明',attachments=[txt],transport=httpx.MockTransport(handle)))


def test_attachment_limits_and_unreadable_files(tmp_path):
    txt = tmp_path / 'notes.txt'
    txt.write_bytes(b'')
    with pytest.raises(ValueError,match='没有可提取'):
        load_attachments([txt])
    with pytest.raises(ValueError,match='最多'):
        validate_paths([tmp_path / f'{i}.txt' for i in range(6)])
    txt.write_bytes(b'a' * (10*1024*1024+1))
    with pytest.raises(ValueError,match='10 MB'):
        load_attachments([txt])
    pdf = tmp_path / 'broken.pdf'
    pdf.write_bytes(b'not a PDF')
    with pytest.raises(ValueError,match='损坏'):
        load_attachments([pdf])


def test_combined_context_limit_prevents_network(tmp_path):
    txt = tmp_path / 'notes.txt'
    txt.write_text('a'*119999,encoding='utf-8')
    with pytest.raises(ValueError,match='合计'):
        asyncio.run(ask_paper(paper(),settings(),'问题',attachments=[txt],
            transport=httpx.MockTransport(lambda _:pytest.fail('Should not send'))))


def test_cancel_attachment_extraction(tmp_path):
    txt = tmp_path / 'notes.txt'
    txt.write_text('evidence')
    stop = threading.Event()
    stop.set()
    with pytest.raises(Cancelled):
        load_attachments([txt],stop)


def test_scan_and_image_use_visual_content_not_fake_ocr(tmp_path):
    image = tmp_path/'figure.png'
    scan = tmp_path/'scan.pdf'
    with fitz.open() as doc:
        page = doc.new_page(width=200,height=100)
        page.insert_text((20,40),'Image evidence')
        raw = page.get_pixmap().tobytes('png')
    image.write_bytes(raw)
    with fitz.open() as doc:
        doc.new_page(width=200,height=100).insert_image(fitz.Rect(0,0,200,100),stream=raw)
        doc.save(scan)
    rows = load_attachments([image,scan])
    assert all(row['text'] == '' for row in rows)
    assert all(row['images'][0]['page']==1 for row in rows)
    def handle(request):
        body = json.loads(request.content)
        content = body['messages'][-1]['content']
        pictures = [part for part in content if part['type']=='image_url']
        assert len(pictures)==2
        assert all(part['image_url']['url'].startswith('data:image/jpeg;base64,') for part in pictures)
        metadata = json.loads(content[0]['text'])
        assert all('images' not in row for row in metadata['attachments'])
        assert '附件2 scan.pdf 第1页' in content[3]['text']
        assert str(tmp_path) not in json.dumps(content,ensure_ascii=False)
        return httpx.Response(200,json={'choices':[{'message':{'content':'图像识别成功'}}]})
    assert asyncio.run(ask_paper(paper(),settings(),'读图',attachments=[image,scan],transport=httpx.MockTransport(handle)))=='图像识别成功'


def test_scan_page_limit_is_explicit(tmp_path):
    path=tmp_path/'long-scan.pdf'
    with fitz.open() as doc:
        for _ in range(21):doc.new_page(width=20,height=20)
        doc.save(path)
    with pytest.raises(ValueError,match='20张'):
        load_attachments([path])


def test_corrupt_image_is_rejected(tmp_path):
    path=tmp_path/'bad.png'
    path.write_bytes(b'invalid')
    with pytest.raises(ValueError,match='损坏'):
        load_attachments([path])
