"""环境检查脚本的模型名匹配测试。"""

from scripts.check_env import is_installed


def test_model_without_tag_matches_latest():
    """Ollama 把不带标签的模型记为 `:latest`，两种写法必须视为同一个模型，否则会误报缺失。"""
    assert is_installed("bge-m3", ["bge-m3:latest"])
    assert is_installed("bge-m3:latest", ["bge-m3"])


def test_different_tag_is_not_installed():
    """标签不同就是不同的模型（例如 0.6b 和 4b），不能误判为已安装。"""
    assert not is_installed("qwen3-embedding:0.6b", ["qwen3-embedding:4b"])
