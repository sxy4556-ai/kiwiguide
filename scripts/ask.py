"""命令行提问：用真实模型和本地索引运行 Agent，同一个 --thread 下的多次提问共享会话记忆。

用法：uv run python scripts/ask.py "房东最多可以收多少押金？" [--thread demo] [--verbose]
助手反问时会打印反问并退出，用 --resume 在同一个会话里回答：
    uv run python scripts/ask.py "学生签证，学期中" --thread demo --resume
"""

import argparse
import logging
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.agent.graph import (  # noqa: E402
    ask,
    build_graph,
    open_checkpointer,
    pending_clarification,
    resume,
)
from app.config import get_settings  # noqa: E402
from app.llm import get_chat_model  # noqa: E402
from app.logging_config import setup_logging  # noqa: E402
from app.retrieval.embeddings import (  # noqa: E402
    make_dense_embedder,
    make_sparse_embedder,
    probe_dimension,
)
from app.retrieval.search import HybridSearcher  # noqa: E402
from app.retrieval.store import ParentStore, VectorStore  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description="向 KiwiGuide 提问")
    parser.add_argument("question", help="问题；加 --resume 时是对反问的回答")
    parser.add_argument("--thread", default="cli", help="会话 ID，相同 ID 共享上下文")
    parser.add_argument("--resume", action="store_true", help="回答上一次的反问，从断点继续")
    parser.add_argument("--verbose", action="store_true", help="打印子问题、检索词和重试次数")
    args = parser.parse_args()

    settings = get_settings()
    setup_logging(settings.log_level)
    logging.getLogger("httpx").setLevel(logging.WARNING)

    dense, sparse = make_dense_embedder(settings), make_sparse_embedder(settings)
    vector_store = VectorStore.open(settings.data_dir / "qdrant", probe_dimension(dense))
    parent_store = ParentStore(settings.data_dir / "parents.sqlite")
    saver = open_checkpointer(settings.data_dir / "checkpoints.sqlite")
    searcher = HybridSearcher(vector_store, parent_store, dense, sparse)
    graph = build_graph(get_chat_model(settings), searcher.search, saver)
    try:
        start = time.perf_counter()
        run = resume if args.resume else ask
        state = run(graph, args.question, args.thread)
        elapsed = time.perf_counter() - start
    finally:
        saver.conn.close()
        vector_store.close()
        parent_store.close()

    clarification = pending_clarification(state)
    if args.verbose:
        for s in state.get("sub_questions", []):
            print(f"子问题：{s['question']} → {s['query']}（主题 {s['topic']}）")
        print(f"范围：{state.get('scope')}；转介：{state.get('needs_referral')}；"
              f"重试次数：{state.get('retries')}；评估：{state.get('grade')}")
        print("-" * 40)
    if clarification:
        print(f"反问：{clarification}")
        print(f"（请用 --resume --thread {args.thread} 回答）")
    else:
        print(state["answer"])
    print(f"\n（耗时 {elapsed:.1f} 秒）")
    return 0


if __name__ == "__main__":
    sys.exit(main())
