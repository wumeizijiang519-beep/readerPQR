import asyncio
import json
import sys
import threading
from dataclasses import replace
from pathlib import Path

import httpx
import pymupdf
import pytest

from readerpqr.export import export_html, export_json
from readerpqr.models import Block, Paper
from readerpqr.pdf_engine import PDFError, PasswordRequired, Renderer, load_paper, normalize_text, reading_order
from readerpqr.smoke import create_sample
from readerpqr.storage import Cache, Settings, endpoint_url, load_settings, save_settings
from readerpqr.translate import (
    AITranslator, Cancelled, FormatError, Item, TranslationError,
    parse_response, protect, split_text, translate_paper,
)


@pytest.fixture
def pdf(tmp_path):
    path = tmp_path / "测试文献.pdf"
    create_sample(path)
    return path


def block(identity="a", text="A method for reading papers.", bbox=(20, 20, 250, 60)):
    return Block(identity, 0, bbox, text)


def test_pdf_extract_and_render(pdf):
    paper = load_paper(str(pdf))
    assert paper.page_count == 2
    assert len(paper.blocks) >= 5
    assert len({b.id for b in paper.blocks}) == len(paper.blocks)
    assert all(b.text and b.bbox[2] > b.bbox[0] for b in paper.blocks)
    renderer = Renderer(str(pdf))
    try:
        assert renderer.png(0).startswith(b"\x89PNG")
        assert renderer.png(0, bbox=paper.pages[0][0].bbox).startswith(b"\x89PNG")
    finally:
        renderer.close()


def test_rotated_pdf(tmp_path):
    path = tmp_path / "rotated.pdf"
    with pymupdf.open() as document:
        page = document.new_page()
        page.insert_text((40, 60), "Rotated page text")
        page.set_rotation(90)
        document.save(path)
    paper = load_paper(str(path))
    renderer = Renderer(str(path))
    try:
        boxes, size = renderer.boxes(0, paper.pages[0])
        assert size[0] > size[1]
        assert boxes[0][1][0] >= 0
        assert renderer.png(0, bbox=paper.blocks[0].bbox).startswith(b"\x89PNG")
    finally:
        renderer.close()


def test_password(tmp_path):
    path = tmp_path / "locked.pdf"
    with pymupdf.open() as doc:
        doc.new_page().insert_text((40, 50), "Password-protected article")
        doc.save(path, encryption=pymupdf.PDF_ENCRYPT_AES_256, owner_pw="owner", user_pw="secret")
    with pytest.raises(PasswordRequired):
        load_paper(str(path))
    assert load_paper(str(path), "secret").page_count == 1


def test_corrupt_and_missing(tmp_path):
    with pytest.raises(PDFError):
        load_paper(str(tmp_path / "missing.pdf"))
    bad = tmp_path / "bad.pdf"
    bad.write_bytes(b"not a PDF")
    with pytest.raises(PDFError):
        load_paper(str(bad))


def test_scan_and_cancel(tmp_path, pdf):
    blank = tmp_path / "scan.pdf"
    with pymupdf.open() as doc:
        doc.new_page().draw_rect((20, 20, 200, 200))
        doc.save(blank)
    assert load_paper(str(blank)).image_only_pages == [0]
    stop = threading.Event()
    stop.set()
    with pytest.raises(InterruptedError):
        load_paper(str(pdf), cancel=stop)


def test_columns():
    blocks = [block("r2", bbox=(320, 190, 560, 210)), block("l2", bbox=(40, 180, 270, 200)),
              block("r1", bbox=(320, 100, 560, 120)), block("l1", bbox=(40, 90, 270, 110)),
              block("title", bbox=(40, 20, 560, 45))]
    assert [b.id for b in reading_order(blocks, 600)] == ["title", "l1", "l2", "r1", "r2"]
    assert [b.id for b in reading_order(blocks, 600, "single")] == ["title", "l1", "r1", "l2", "r2"]


def test_normalize():
    assert normalize_text("a  line\nnew\tword\x00") == "a line new word"
    assert normalize_text("soft\u00ad\nhyphen") == "softhyphen"
    assert normalize_text("self-\nsupervised") == "self- supervised"


@pytest.mark.parametrize("value", ["https://example.org/v1", "http://localhost:8000/v1", "http://127.0.0.1:11434/v1", "http://[::1]:8000/v1"])
def test_endpoint(value):
    assert endpoint_url(value).endswith("/chat/completions")
    assert endpoint_url(endpoint_url(value)) == endpoint_url(value)


@pytest.mark.parametrize("value", ["http://example.org/v1", "https://user:secret@example.org/v1", "file:///tmp/x", "https://example.org/v1?key=secret", "https://example.org/v1#part"])
def test_unsafe_endpoint(value):
    with pytest.raises(ValueError):
        endpoint_url(value)


def test_settings_no_plaintext(tmp_path):
    settings = Settings(api_key="VERY_SECRET_TOKEN", remember_key=False)
    save_settings(settings, tmp_path)
    assert "VERY_SECRET_TOKEN" not in (tmp_path / "settings.json").read_text()
    assert "api_key" not in (tmp_path / "settings.json").read_text()
    assert load_settings(tmp_path).api_key == ""
    assert "VERY_SECRET_TOKEN" not in repr(settings)


@pytest.mark.skipif(sys.platform != "win32", reason="Windows DPAPI only")
def test_windows_dpapi(tmp_path):
    settings = Settings(api_key="dpapi-roundtrip-测试", remember_key=True)
    save_settings(settings, tmp_path)
    assert settings.api_key not in (tmp_path / "settings.json").read_text(encoding="utf-8")
    assert load_settings(tmp_path).api_key == settings.api_key


def test_profile_cache_invalidation(tmp_path):
    settings = Settings()
    profile = settings.profile_id()
    assert replace(settings, api_key="another-key").profile_id() == profile
    for changed in (replace(settings, model="other"), replace(settings, glossary="new"),
                    replace(settings, base_url="https://other.example/v1"), replace(settings, extra_json="{}")):
        assert changed.profile_id() != profile
    with Cache(tmp_path) as cache:
        cache.put("doc", profile, "id", "source", "译文")
        assert cache.get("doc", profile, "id", "source") == "译文"
        assert cache.get("doc", profile, "id", "changed") is None
        assert cache.get("doc", "other", "id", "source") is None
    with Cache(tmp_path) as cache:
        assert cache.get("doc", profile, "id", "source") == "译文"


@pytest.mark.parametrize("extra", ['[]', '{bad}', '{"messages":[]}', '{"tools":[]}'])
def test_invalid_extra(extra):
    with pytest.raises(ValueError):
        Settings(extra_json=extra).validate()


def test_parse_protected_response():
    text, tokens = protect("Loss $L=x+y$ follows [1, 2].")
    assert len(tokens) == 2
    item = Item("a", text, tokens)
    response = json.dumps({"translations": [{"id": "a", "text": "损失 " + text}]})
    parsed = parse_response("```json\n" + response + "\n```", [item])
    assert "$L=x+y$" in parsed["a"] and "[1, 2]" in parsed["a"]
    with pytest.raises(FormatError):
        parse_response(response.replace("__PQR_KEEP_0000__", "bad"), [item])


@pytest.mark.parametrize("rows", [[], [{"id": "a", "text": ""}], [{"id": "wrong", "text": "错位"}],
                                  [{"id": "a", "text": "重复"}, {"id": "a", "text": "重复"}]])
def test_reject_bad_ids(rows):
    with pytest.raises(FormatError):
        parse_response(json.dumps({"translations": rows}), [Item("a", "text", {})])


def test_split_long():
    text = "This is a long scientific paragraph. " * 400
    parts = split_text(text, 500)
    assert len(parts) > 1 and all(len(x) <= 500 for x in parts)
    assert " ".join(parts).split() == text.split()


def good_transport(calls):
    def respond(request):
        payload = json.loads(request.content)
        assert payload["stream"] is False and "tools" not in payload
        values = json.loads(payload["messages"][-1]["content"])["items"]
        calls.append(values)
        content = json.dumps({"translations": [{"id": x["id"], "text": "中文 " + x["text"]} for x in values]})
        return httpx.Response(200, json={"choices": [{"message": {"content": content}, "finish_reason": "stop"}]})
    return httpx.MockTransport(respond)


def test_async_translation_large_block():
    async def run():
        calls = []
        engine = AITranslator(Settings(extra_json="{}", batch_chars=600), transport=good_transport(calls))
        try:
            result = await engine.translate([block(text="A scientific sentence. " * 130)])
            assert "中文" in result["a"] and len(calls) > 1
        finally:
            await engine.close()
    asyncio.run(run())


def test_auth_failure_sanitized():
    async def run():
        engine = AITranslator(Settings(api_key="TOP_SECRET"), transport=httpx.MockTransport(lambda _: httpx.Response(401, text="TOP_SECRET")))
        try:
            with pytest.raises(TranslationError) as error:
                await engine.translate([block()])
            assert "TOP_SECRET" not in str(error.value)
        finally:
            await engine.close()
    asyncio.run(run())


def test_cancel_inflight():
    async def run():
        stop = threading.Event()
        async def slow(request):
            await asyncio.sleep(30)
            return httpx.Response(500)
        engine = AITranslator(Settings(), stop, httpx.MockTransport(slow))
        asyncio.get_running_loop().call_later(0.05, stop.set)
        try:
            with pytest.raises(Cancelled):
                await asyncio.wait_for(engine.translate([block()]), 2)
        finally:
            await engine.close()
    asyncio.run(run())


def test_paper_resume_and_consent(tmp_path):
    async def run():
        paper = Paper("test.pdf", "hash", "test", 1, [[block(), block("b", "Another paragraph.")]])
        settings = Settings(base_url="http://127.0.0.1:8000/v1", extra_json="{}")
        calls, results, errors = [], [], []
        transport = good_transport(calls)
        with pytest.raises(TranslationError):
            await translate_paper(paper, settings, threading.Event(), lambda *x: results.append(x), lambda *x: errors.append(x), cache_dir=tmp_path, transport=transport)
        settings.consent_endpoint = endpoint_url(settings.base_url)
        first = await translate_paper(paper, settings, threading.Event(), lambda *x: results.append(x), lambda *x: errors.append(x), cache_dir=tmp_path, transport=transport)
        count = len(calls)
        second = await translate_paper(paper, settings, threading.Event(), lambda *x: results.append(x), lambda *x: errors.append(x), cache_dir=tmp_path, transport=transport)
        assert first["translated"] == 2 and second["cached"] == 2
        assert len(calls) == count and not errors
    asyncio.run(run())


def test_export_escapes_and_marks_missing(tmp_path):
    paper = Paper("private.pdf", "hash", "<script>bad</script>", 1, [[block(text="<img src=x onerror=bad>"), block("b")]])
    export_html(paper, {"a": "<script>bad()</script>"}, str(tmp_path / "test.html"))
    html = (tmp_path / "test.html").read_text(encoding="utf-8")
    assert "<script>" not in html and "&lt;script&gt;" in html
    assert "尚未翻译" in html and "Content-Security-Policy" in html
    export_json(paper, {}, str(tmp_path / "test.json"))
    data = json.loads((tmp_path / "test.json").read_text(encoding="utf-8"))
    assert data["pages"][0][0]["translation"] is None
    assert "private.pdf" not in json.dumps(data)
