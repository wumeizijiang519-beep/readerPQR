import asyncio
import json
import threading

import httpx
import pytest

from readerpqr.models import Block, Paper
from readerpqr.qa import ask_paper, paper_context
from readerpqr.storage import Settings, endpoint_url
from readerpqr.translate import Cancelled, TranslationError


def paper():
    return Paper("unused.pdf", "hash", "Example", 2, [
        [Block("a", 0, (0, 0, 1, 1), "First page evidence.")],
        [Block("b", 1, (0, 0, 1, 1), "Second page evidence.")]])


def settings():
    s = Settings(base_url="https://example.com/v1", model="test-model", api_key="test-only-key", extra_json="{}")
    s.consent_endpoint = endpoint_url(s.base_url)
    return s


def test_question_uses_configured_key_page_and_bounded_history():
    def handle(request):
        assert request.headers["authorization"] == "Bearer test-only-key"
        body = json.loads(request.content)
        assert body["model"] == "test-model" and body["stream"] is True
        assert len(body["messages"]) == 6
        context = json.loads(body["messages"][-1]["content"])
        assert "First page" not in context["paper_context"]
        assert "[第2页]" in context["paper_context"]
        assert context["question"] == "解释实验"
        assert "test-only-key" not in request.content.decode()
        return httpx.Response(200, json={"choices": [{"message": {"content": "实验依据 [第2页]"}, "finish_reason": "stop"}]})
    history = [{"role": "user" if i % 2 == 0 else "assistant", "content": str(i)} for i in range(10)]
    answer = asyncio.run(ask_paper(paper(), settings(), "解释实验", history, page=1, transport=httpx.MockTransport(handle)))
    assert answer == "实验依据 [第2页]"


def test_no_request_without_endpoint_consent():
    s = settings()
    s.consent_endpoint = ""
    def handle(request):
        pytest.fail("Network request without consent")
    with pytest.raises(TranslationError):
        asyncio.run(ask_paper(paper(), s, "问题", transport=httpx.MockTransport(handle)))


@pytest.mark.parametrize("status,payload", [(401, {"secret": "DO_NOT_SHOW"}), (400, {"error": "DO_NOT_SHOW"}),
    (200, {"choices": [{"message": {"content": ""}}]}), (200, {"unexpected": "DO_NOT_SHOW"})])
def test_errors_do_not_expose_response(status, payload):
    with pytest.raises(TranslationError) as error:
        asyncio.run(ask_paper(paper(), settings(), "问题", transport=httpx.MockTransport(lambda _: httpx.Response(status, json=payload))))
    assert "DO_NOT_SHOW" not in str(error.value)


def test_gpt_low_reasoning_respects_override():
    for extra, expected in [('{}', 'low'), ('{"reasoning_effort":"medium"}', 'medium')]:
        s = settings()
        s.model = 'gpt-5.6-sol'
        s.extra_json = extra
        def handle(request):
            body = json.loads(request.content)
            assert body['reasoning_effort'] == expected
            assert 'First page' in body['messages'][-1]['content']
            assert 'Second page' in body['messages'][-1]['content']
            return httpx.Response(200, json={'choices': [{'message': {'content': '完整回答'}, 'finish_reason': 'stop'}]})
        assert asyncio.run(ask_paper(paper(), s, '问题', transport=httpx.MockTransport(handle))) == '完整回答'


@pytest.mark.parametrize('failure', [429, 503, 'disconnect', 'timeout'])
def test_failures_are_never_automatically_replayed(failure):
    calls = []
    def handle(request):
        calls.append(1)
        if failure == 'disconnect':
            raise httpx.RemoteProtocolError('private upstream details')
        if failure == 'timeout':
            raise httpx.ReadTimeout('private upstream details')
        return httpx.Response(failure)
    with pytest.raises(TranslationError, match='未自动重发'):
        asyncio.run(ask_paper(paper(), settings(), '问题', transport=httpx.MockTransport(handle)))
    assert len(calls) == 1


class Stream(httpx.AsyncByteStream):
    def __init__(self, parts):
        self.parts = parts
        self.closed = False

    async def __aiter__(self):
        for part in self.parts:
            if isinstance(part, float):
                await asyncio.sleep(part)
            else:
                yield part

    async def aclose(self):
        self.closed = True


def event(text='', reason=None):
    obj = {'choices': [{'index': 0, 'delta': {'content': text}, 'finish_reason': reason}]}
    return ('data: ' + json.dumps(obj, ensure_ascii=False) + '\n\n').encode()


def run_stream(parts, **kwargs):
    response_stream = Stream(parts)
    transport = httpx.MockTransport(lambda _: httpx.Response(200,
        headers={'content-type': 'text/event-stream'}, stream=response_stream))
    return asyncio.run(ask_paper(paper(), settings(), '问题', transport=transport, **kwargs)), response_stream


def test_stream_handles_utf8_chunk_boundaries_and_completion():
    data = event('中文') + event(' [第2页]', 'stop') + b'data: [DONE]\n\n'
    chunks = []
    answer, stream = run_stream([data[i:i+1] for i in range(len(data))], on_chunk=chunks.append)
    assert answer == '中文 [第2页]' and ''.join(chunks) == answer and stream.closed


def test_partial_stream_is_not_success_and_is_not_replayed():
    chunks = []
    with pytest.raises(TranslationError, match='提前关闭'):
        run_stream([event('保留内容')], on_chunk=chunks.append)
    assert chunks == ['保留内容']


def test_idle_timeout_ignores_heartbeat_and_keeps_partial():
    chunks = []
    with pytest.raises(TranslationError, match='输出已中断'):
        run_stream([event('第一段'), 0.02, b': heartbeat\n\n', 0.1],
            on_chunk=chunks.append, idle_timeout=0.05)
    assert chunks == ['第一段']


def test_first_content_uses_total_budget_not_idle_timeout():
    answer, _ = run_stream([0.05, event('回答', 'stop'), b'data: [DONE]\n\n'], idle_timeout=0.01)
    assert answer == '回答'


def test_terminal_finish_reason_does_not_wait_for_connection_close():
    answer, stream = run_stream([event('回答', 'stop'), 1.0], idle_timeout=0.01)
    assert answer == '回答' and stream.closed


def test_total_deadline_stops_heartbeat_only_stream(monkeypatch):
    s = settings()
    monkeypatch.setattr(s, 'validate', lambda: None)
    s.timeout = 0.05
    response_stream = Stream([b': heartbeat\n\n', 0.2])
    with pytest.raises(TranslationError, match='总时限'):
        asyncio.run(ask_paper(paper(), s, '问题', transport=httpx.MockTransport(lambda _: httpx.Response(200,
            headers={'content-type': 'text/event-stream'}, stream=response_stream))))
    assert response_stream.closed


def test_cancel_during_stream_closes_connection():
    stop = threading.Event()
    chunks = []
    def on_chunk(text):
        chunks.append(text)
        stop.set()
    with pytest.raises(Cancelled):
        run_stream([event('第一段'), 1.0], on_chunk=on_chunk, stop=stop)
    assert chunks == ['第一段']


def test_nonstream_compatibility_has_full_timeout():
    s = settings()
    s.timeout = 300
    def handle(request):
        assert json.loads(request.content)['stream'] is False
        assert request.extensions['timeout']['read'] == 300
        return httpx.Response(200, json={'choices': [{'message': {'content': '回答'}, 'finish_reason': 'stop'}]})
    assert asyncio.run(ask_paper(paper(), s, '问题', stream=False, transport=httpx.MockTransport(handle))) == '回答'


def test_filtered_response_is_not_success():
    with pytest.raises(TranslationError, match='未能正常完成'):
        asyncio.run(ask_paper(paper(), settings(), '问题', transport=httpx.MockTransport(lambda _: httpx.Response(200,
            json={'choices': [{'message': {'content': '部分回答'}, 'finish_reason': 'content_filter'}]}))))


def test_cancellation_interrupts_inflight_request():
    async def run():
        stop = threading.Event()
        async def handle(request):
            stop.set()
            await asyncio.sleep(10)
            return httpx.Response(200)
        with pytest.raises(Cancelled):
            await asyncio.wait_for(ask_paper(paper(), settings(), "问题", stop=stop,
                transport=httpx.MockTransport(handle)), timeout=2)
    asyncio.run(run())


def test_context_never_silently_truncates():
    p = paper()
    p.pages[0] = [Block("a", 0, (0, 0, 1, 1), "x" * 120001)]
    with pytest.raises(ValueError, match="上限"):
        paper_context(p)
    assert "Second page" in paper_context(p, 1)
    with pytest.raises(ValueError):
        paper_context(p, 2)


def test_chat_removes_translation_json_response_constraint():
    s = settings()
    s.extra_json = '{"response_format":{"type":"json_object"}}'
    def handle(request):
        assert "response_format" not in json.loads(request.content)
        return httpx.Response(200, json={"choices": [{"message": {"content": "简要回答"}, "finish_reason": "length"}]})
    answer = asyncio.run(ask_paper(paper(), s, "问题", transport=httpx.MockTransport(handle)))
    assert "截断" in answer


@pytest.mark.parametrize("exception,expected", [(httpx.ReadTimeout, "等待模型回答"),
    (httpx.ConnectTimeout, "连接 API"), (httpx.WriteTimeout, "发送论文文字")])
def test_timeout_explains_which_stage_failed(exception, expected):
    s = settings()
    s.timeout = 300
    def handle(request):
        assert request.extensions["timeout"]["read"] == 300
        raise exception("DO_NOT_SHOW")
    with pytest.raises(TranslationError) as error:
        asyncio.run(ask_paper(paper(), s, "问题", transport=httpx.MockTransport(handle)))
    assert expected in str(error.value)
    assert "DO_NOT_SHOW" not in str(error.value)
