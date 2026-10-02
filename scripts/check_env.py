"""环境检查：Ollama 服务是否运行，对话模型和向量模型是否已安装。

用法：uv run python scripts/check_env.py
缺少向量模型时会自动执行 `ollama pull`。
"""

import subprocess
import sys
from pathlib import Path

import httpx

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.config import get_settings  # noqa: E402


def normalize(name: str) -> str:
    """不带标签的模型名等价于 `:latest`。"""
    return name if ":" in name else f"{name}:latest"


def is_installed(model: str, installed: list[str]) -> bool:
    """判断模型是否在已安装列表中。"""
    return normalize(model) in {normalize(m) for m in installed}


def list_models(base_url: str) -> list[str] | None:
    """返回已安装的模型名；服务不可达时返回 None。"""
    try:
        resp = httpx.get(f"{base_url.rstrip('/')}/api/tags", timeout=5)
        resp.raise_for_status()
    except httpx.HTTPError as exc:
        print(f"[失败] 无法连接 Ollama（{base_url}）：{exc}")
        return None
    return [m["name"] for m in resp.json().get("models", [])]


def main() -> int:
    settings = get_settings()
    models = list_models(settings.ollama_base_url)
    if models is None:
        print("请先启动 Ollama 服务后重试。")
        return 1
    print(f"[正常] Ollama 服务运行中（{settings.ollama_base_url}），已安装 {len(models)} 个模型")

    ok = True
    for label, model in [
        ("对话模型", settings.llm_model),
        ("备用模型", settings.fallback_llm_model),
    ]:
        if is_installed(model, models):
            print(f"[正常] {label} {model} 已安装")
        else:
            print(f"[缺失] {label} {model} 未安装，请运行：ollama pull {model}")
            ok = False

    embed = settings.embed_model
    if is_installed(embed, models):
        print(f"[正常] 向量模型 {embed} 已安装")
    else:
        print(f"[缺失] 向量模型 {embed} 未安装，正在执行 ollama pull {embed} ……")
        result = subprocess.run(["ollama", "pull", embed], check=False)
        if result.returncode == 0:
            print(f"[正常] 向量模型 {embed} 下载完成")
        else:
            print(f"[失败] 向量模型 {embed} 下载失败（退出码 {result.returncode}）")
            ok = False

    print("环境检查通过。" if ok else "环境检查未通过，请按上面的提示处理。")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
