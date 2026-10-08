"""MCP 服务测试：经 MCP 客户端在进程内调用工具，不访问网络。

用假模型和假检索器组装真实的 Agent 图，与接口测试共用同一套数据。
"""

from mcp.client import Client

from app.mcp_server import create_mcp_server
from tests.fakes import FakeChatModel
from tests.test_api import ANSWER, BOND, GRADE_OK, SOURCES, make_service, rewrite_reply


async def test_lists_tools_matching_http_api():
    """客户端靠工具列表决定能做什么：提问、回答反问、查看来源三项缺一项，
    MCP 客户端就无法完成和网页端相同的问答流程。"""
    server = create_mcp_server(make_service(FakeChatModel([])))
    async with Client(server) as client:
        tools = {t.name for t in (await client.list_tools()).tools}
    assert tools == {"ask", "answer_clarification", "list_sources"}


async def test_ask_returns_answer_with_citations():
    """ask 必须返回与 /chat 相同的结构化结果：回答、出处和 thread_id，
    客户端才能展示官方出处并在同一会话里追问。"""
    server = create_mcp_server(make_service(FakeChatModel([rewrite_reply(), GRADE_OK, ANSWER])))
    async with Client(server) as client:
        result = await client.call_tool("ask", {"question": "押金最多多少？"})
    assert not result.is_error
    data = result.structured_content
    assert data["status"] == "answered"
    assert data["thread_id"]
    assert data["answer"].startswith(ANSWER)
    assert data["citations"][0]["url"] == BOND.parent.url


async def test_clarification_then_answer_in_same_thread():
    """缺少关键信息时 ask 必须返回反问而不是硬答；用 answer_clarification 回答后
    要在同一会话里从断点继续，否则 MCP 客户端无法完成反问流程。"""
    question = "请问你是正式租客、合租房客还是寄宿？"
    llm = FakeChatModel([
        rewrite_reply(clarification=question),
        rewrite_reply("boarder bond"), GRADE_OK, ANSWER,
    ])
    server = create_mcp_server(make_service(llm))
    async with Client(server) as client:
        first = await client.call_tool("ask", {"question": "要涨租了怎么办？", "thread_id": "t-1"})
        second = await client.call_tool(
            "answer_clarification", {"thread_id": "t-1", "answer": "寄宿"}
        )
    assert first.structured_content["status"] == "needs_clarification"
    assert first.structured_content["clarification_question"] == question
    assert second.structured_content["status"] == "answered"
    assert second.structured_content["thread_id"] == "t-1"


async def test_answer_without_pending_question_reports_reason():
    """没有反问的会话不能恢复，且错误里必须带中文原因：只给笼统的出错提示，
    客户端无法判断应该改为直接提问。"""
    server = create_mcp_server(make_service(FakeChatModel([])))
    async with Client(server) as client:
        result = await client.call_tool(
            "answer_clarification", {"thread_id": "unknown", "answer": "学生签证"}
        )
    assert result.is_error
    assert "没有等待回答的反问" in result.content[0].text


async def test_rejects_invalid_arguments_like_http_api():
    """输入规则要和 HTTP 接口一致：空问题和非法 thread_id 必须在进入 Agent 前被拒绝，
    否则会白白调用模型，或者写出非法的会话记录。"""
    server = create_mcp_server(make_service(FakeChatModel([])))
    async with Client(server) as client:
        blank = await client.call_tool("ask", {"question": "   "})
        bad_thread = await client.call_tool("ask", {"question": "押金", "thread_id": "a b"})
    assert blank.is_error
    assert bad_thread.is_error


async def test_list_sources():
    """list_sources 必须返回知识库收录的来源，用户才能核对回答依据的是哪些官方页面。"""
    server = create_mcp_server(make_service(FakeChatModel([])))
    async with Client(server) as client:
        result = await client.call_tool("list_sources", {})
    assert not result.is_error
    assert result.structured_content == {"result": SOURCES}
