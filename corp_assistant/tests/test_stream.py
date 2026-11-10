from langchain_core.messages import AIMessage, AIMessageChunk

from corp_assistant import assistant


class _Agent:
    def __init__(self, events):
        self.events = events

    def stream(self, messages, config, stream_mode):
        assert stream_mode == ["messages", "updates"]
        yield from self.events


def test_iter_chat_events_streams_tokens_and_tools(monkeypatch):
    saved = {}

    def add_message(conversation_id, role, content):
        saved["message"] = (conversation_id, role, content)

    monkeypatch.setattr(assistant.store, "add_message", add_message)
    monkeypatch.setattr(assistant.store, "add_audit", lambda *args, **kwargs: saved.update(audit=args))

    tool_message = AIMessage(
        content="",
        tool_calls=[{"name": "search_knowledge", "args": {"query": "年假"}, "id": "call-1", "type": "tool_call"}],
    )
    agent = _Agent([
        ("messages", (AIMessageChunk(content="", additional_kwargs={"reasoning_content": "先查制度"}, id="a"), {})),
        ("updates", {"model": {"messages": [tool_message]}}),
        ("messages", (AIMessageChunk(content="年假", id="b"), {})),
        ("messages", (AIMessageChunk(content="五天", id="b"), {})),
    ])
    user = {"id": "E004"}
    events = list(assistant.iter_chat_events(user, "年假有几天", "conv-1", [], agent))

    assert events[0] == {"event": "meta", "conversation_id": "conv-1"}
    assert {"event": "reasoning", "text": "先查制度"} in events
    assert {"event": "tool", "name": "search_knowledge"} in events
    assert [item["text"] for item in events if item["event"] == "delta"] == ["年假", "五天"]
    done = events[-1]
    assert done["event"] == "done"
    assert done["answer"] == "年假五天"
    assert done["tools"] == [{"name": "search_knowledge", "args": {"query": "年假"}}]
    assert saved["message"] == ("conv-1", "assistant", "年假五天")


def test_encode_sse_keeps_unicode():
    text = assistant.encode_sse("delta", {"text": "年假"})
    assert text.startswith("event: delta\n")
    assert "年假" in text
    assert text.endswith("\n\n")
