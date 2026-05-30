from pathlib import Path

from server.agent_runtime.sdk_tools._context import compact_tool_text, tool_error


def test_compact_tool_text_truncates_with_source_path(tmp_path: Path):
    source = tmp_path / "prompt.txt"
    text = "x" * 128

    compacted = compact_tool_text(text, label="DRY RUN prompt", source_path=source, max_bytes=16)

    assert "DRY RUN prompt过大" in compacted
    assert str(source) in compacted
    assert "--- 预览开始 ---" in compacted
    assert len(compacted.encode("utf-8")) < len(text.encode("utf-8")) + 256


def test_tool_error_truncates_large_log(monkeypatch):
    monkeypatch.setenv("ASSISTANT_MCP_TOOL_TEXT_MAX_BYTES", "32768")

    result = tool_error("demo", RuntimeError("boom"), ["x" * 40000])

    assert result["is_error"] is True
    text = result["content"][0]["text"]
    assert "demo 错误输出过大" in text
    assert len(text.encode("utf-8")) < 36000
