"""对话模型工厂测试：主备模型的组装方式。只构造对象，不发起任何请求。"""

from app.config import Settings
from app.llm import get_chat_model


def test_fallback_model_disables_thinking():
    """备用的本地小模型必须关闭思考模式：开启时一次问答要好几分钟，起不到保证可用的作用。"""
    settings = Settings(
        _env_file=None, llm_model="gpt-oss:120b-cloud", fallback_llm_model="qwen3:4b"
    )
    chat = get_chat_model(settings)
    assert chat.runnable.model == "gpt-oss:120b-cloud"
    assert chat.runnable.reasoning is None
    assert chat.fallbacks[0].model == "qwen3:4b"
    assert chat.fallbacks[0].reasoning is False


def test_no_fallback_when_same_as_primary():
    """备用模型与主模型相同时不应再套一层回退，否则同一个失败的请求会白白重试一次。"""
    settings = Settings(_env_file=None, llm_model="qwen3:4b", fallback_llm_model="qwen3:4b")
    chat = get_chat_model(settings)
    assert chat.model == "qwen3:4b"
    assert not hasattr(chat, "fallbacks")
