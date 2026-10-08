"""以 stdio 方式运行 KiwiGuide 的 MCP 服务，供支持 MCP 的客户端连接。

用法：uv run python scripts/mcp_server.py
标准输出用于 MCP 协议通信，日志写到标准错误。
与 API 服务一样会打开本地 Qdrant，两者不能同时运行。
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.api.service import build_service  # noqa: E402
from app.config import get_settings  # noqa: E402
from app.logging_config import setup_logging  # noqa: E402
from app.mcp_server import create_mcp_server  # noqa: E402


def main() -> int:
    settings = get_settings()
    setup_logging(settings.log_level)
    service = build_service(settings)
    try:
        create_mcp_server(service).run("stdio")
    finally:
        service.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
