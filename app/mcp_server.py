"""MCP 服务：通过 MCP 协议把问答能力提供给支持 MCP 的客户端。

工具与 HTTP 接口一一对应：ask ↔ /chat，answer_clarification ↔ /chat/{thread_id}/resume，
list_sources ↔ /sources。业务逻辑全部复用 ChatService，这里只做协议适配，
参数校验沿用接口层的 Text 和 ThreadId，两个入口的输入规则保持一致。
"""

from typing import Any

from anyio import to_thread
from mcp.server import MCPServer
from mcp.server.mcpserver.exceptions import ToolError

from app import __version__
from app.api.schemas import Text, ThreadId
from app.api.service import ChatService, ServiceError

INSTRUCTIONS = (
    "KiwiGuide 回答新西兰留学生关于租房、打工与劳动权益、学生签证、税务的问题，并附官方出处。"
    "先调用 ask；返回 status 为 needs_clarification 时，把 clarification_question 转述给用户，"
    "再用同一个 thread_id 调用 answer_clarification。同一个 thread_id 下的多次提问共享会话记忆。"
)


def create_mcp_server(service: ChatService) -> MCPServer:
    server = MCPServer(name="kiwiguide", version=__version__, instructions=INSTRUCTIONS)

    # Agent 和存储都是同步代码，放进线程里执行，不阻塞协议的事件循环
    @server.tool()
    async def ask(question: Text, thread_id: ThreadId | None = None) -> dict[str, Any]:
        """向 KiwiGuide 提问。不传 thread_id 时新建会话，返回结果里带有 thread_id，用于追问。"""
        return await to_thread.run_sync(service.chat, question, thread_id)

    @server.tool()
    async def answer_clarification(thread_id: ThreadId, answer: Text) -> dict[str, Any]:
        """回答 ask 返回的反问，在同一个会话里从断点继续生成回答。"""
        try:
            return await to_thread.run_sync(service.resume, thread_id, answer)
        except ServiceError as e:
            # 必须用 ToolError：其他异常的说明只记在服务端日志里，客户端只能看到笼统的出错提示
            raise ToolError(e.detail) from e

    @server.tool()
    async def list_sources() -> list[dict[str, Any]]:
        """列出知识库收录的官方来源：主题、标题、链接和抓取日期。"""
        return await to_thread.run_sync(service.sources)

    return server
