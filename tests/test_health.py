"""`/health` 接口测试：用 monkeypatch 模拟 Ollama 状态，不访问网络。"""

import httpx

import app.main as main_module
from app import __version__


def _client(app) -> httpx.AsyncClient:
    return httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test")


async def test_health_ok_when_ollama_reachable(monkeypatch):
    """Ollama 可达时必须报告 ok 和版本号，部署方据此判断服务完整可用。"""

    async def fake_check(base_url: str) -> bool:
        return True

    monkeypatch.setattr(main_module, "check_ollama", fake_check)
    async with _client(main_module.create_app()) as client:
        resp = await client.get("/health")
    assert resp.status_code == 200
    assert resp.json() == {"status": "ok", "version": __version__, "ollama": True}


async def test_health_degraded_not_500_when_ollama_down(monkeypatch):
    """Ollama 不可达时必须返回 200 和 degraded 而不是 500：
    健康检查本身不能因为下游故障而崩溃，否则无法区分"服务挂了"和"模型不可用"。"""

    async def fake_check(base_url: str) -> bool:
        return False

    monkeypatch.setattr(main_module, "check_ollama", fake_check)
    async with _client(main_module.create_app()) as client:
        resp = await client.get("/health")
    assert resp.status_code == 200
    assert resp.json()["status"] == "degraded"
    assert resp.json()["ollama"] is False


async def test_check_ollama_swallows_connection_error(monkeypatch):
    """连接异常必须被吞掉并返回 False，这是 /health 不报 500 的前提。"""

    async def raise_connect(self, url, **kwargs):
        raise httpx.ConnectError("connection refused")

    monkeypatch.setattr(httpx.AsyncClient, "get", raise_connect)
    assert await main_module.check_ollama("http://localhost:11434") is False
