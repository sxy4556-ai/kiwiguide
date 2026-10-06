"""在 eval/questions.yaml 上评测朴素 RAG 和 Agent，结果保存到 eval/results/。

用法：
    只评测检索：uv run python scripts/run_eval.py --mode naive --retrieval-only [--top-k 10]
    评测回答：  uv run python scripts/run_eval.py --mode agent [--top-k 6] [--workers 4] [--tag xxx]
评测回答时检索指标按放进提示词的父块计算，忠实度和正确率由 LLM 评判（1–5 分）。
"""

import argparse
import json
import logging
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime
from pathlib import Path

import yaml

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from langgraph.checkpoint.memory import InMemorySaver  # noqa: E402

from app.agent.graph import build_graph  # noqa: E402
from app.config import get_settings  # noqa: E402
from app.eval.metrics import reciprocal_rank, summarize  # noqa: E402
from app.eval.runner import evaluate, run_agent, run_naive, summarize_answers  # noqa: E402
from app.llm import get_chat_model  # noqa: E402
from app.logging_config import setup_logging  # noqa: E402
from app.retrieval.embeddings import (  # noqa: E402
    make_dense_embedder,
    make_sparse_embedder,
    probe_dimension,
)
from app.retrieval.search import HybridSearcher  # noqa: E402
from app.retrieval.store import ParentStore, VectorStore  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent


def fmt(s: dict) -> str:
    return (f"hit@1 {s['hit@1']:.3f}  hit@3 {s['hit@3']:.3f}  hit@5 {s['hit@5']:.3f}  "
            f"MRR {s['mrr']:.3f}（{s['n']} 题）")


def fmt_scores(s: dict) -> str:
    def score(key: str) -> str:
        return "—" if s[key] is None else f"{s[key]:.2f}"
    return (f"忠实度 {score('faithfulness')}（{s['faithfulness_n']} 题）  "
            f"正确率 {score('correctness')}（{s['correctness_n']} 题）  "
            f"反问 {s['clarified']} 题  平均耗时 {s['avg_seconds']} 秒")


def eval_retrieval(args, questions: list[dict], searcher: HybridSearcher) -> tuple[dict, list]:
    rows = []
    for q in questions:
        # 朴素基线：原问题直接检索，不改写、不按主题过滤
        results = searcher.search(q["question"], top_k=args.top_k)
        urls = [r.parent.url for r in results]
        rows.append({
            "id": q["id"], "lang": q["lang"], "topic": q["topic"], "type": q["type"],
            "question": q["question"], "gold_urls": q["gold_urls"], "retrieved_urls": urls,
            "rr": reciprocal_rank(urls, q["gold_urls"]),
        })
    return summarize(rows), rows


def eval_answers(args, questions: list[dict], searcher: HybridSearcher, settings) -> tuple:
    llm = get_chat_model(settings)
    graph = build_graph(llm, searcher.search, InMemorySaver(), top_k=args.top_k)

    def task(q: dict) -> dict:
        if args.mode == "naive":
            def run():
                return run_naive(q, searcher.search, llm, args.top_k)
        else:
            def run():
                return run_agent(q, graph, f"eval-{q['id']}")
        row = evaluate(q, run, llm)
        print(f"  {row['id']}：忠实度 {row['faithfulness']}，正确率 {row['correctness']}，"
              f"{row['seconds']} 秒", flush=True)
        return row

    # 各题互不依赖，并行调用模型以缩短总耗时；结果按题目顺序保存
    with ThreadPoolExecutor(max_workers=args.workers) as pool:
        rows = list(pool.map(task, questions))
    return summarize_answers(rows), rows


def main() -> int:
    parser = argparse.ArgumentParser(description="评测朴素 RAG 和 Agent")
    parser.add_argument("--mode", choices=["naive", "agent"], default="naive", help="评测对象")
    parser.add_argument("--retrieval-only", action="store_true", help="只评测检索，不生成回答")
    parser.add_argument("--top-k", type=int, default=None,
                        help="每题取回的父块数；只评测检索时默认 10，评测回答时默认 6")
    parser.add_argument("--workers", type=int, default=4, help="评测回答时并行的题数")
    parser.add_argument("--tag", default="", help="结果文件名后缀，用于区分调参前后")
    parser.add_argument("--questions", default=str(ROOT / "eval" / "questions.yaml"))
    args = parser.parse_args()
    if args.retrieval_only and args.mode != "naive":
        print("--retrieval-only 只支持 naive：Agent 的检索依赖模型改写，请直接评测回答")
        return 2
    if args.top_k is None:
        args.top_k = 10 if args.retrieval_only else 6

    settings = get_settings()
    setup_logging(settings.log_level)
    logging.getLogger("httpx").setLevel(logging.WARNING)

    questions = yaml.safe_load(Path(args.questions).read_text(encoding="utf-8"))["questions"]
    dense, sparse = make_dense_embedder(settings), make_sparse_embedder(settings)
    vector_store = VectorStore.open(settings.data_dir / "qdrant", probe_dimension(dense))
    parent_store = ParentStore(settings.data_dir / "parents.sqlite")
    searcher = HybridSearcher(vector_store, parent_store, dense, sparse)

    start = time.perf_counter()
    try:
        if args.retrieval_only:
            overall, rows = eval_retrieval(args, questions, searcher)
        else:
            overall, rows = eval_answers(args, questions, searcher, settings)
    finally:
        vector_store.close()
        parent_store.close()
    elapsed = time.perf_counter() - start

    def by(key: str, values: tuple) -> dict:
        pick = summarize if args.retrieval_only else summarize_answers
        return {v: pick([r for r in rows if r[key] == v]) for v in values}

    report = {
        "mode": args.mode,
        "retrieval_only": args.retrieval_only,
        "run_at": datetime.now(UTC).isoformat(timespec="seconds"),
        "settings": {
            "embed_model": settings.embed_model,
            "sparse_model": settings.sparse_model,
            "top_k": args.top_k,
            **({} if args.retrieval_only else {"llm_model": settings.llm_model}),
        },
        "summary": overall,
        "by_lang": by("lang", ("zh", "en")),
        **({} if args.retrieval_only
           else {"by_type": by("type", ("simple", "compound", "underspecified"))}),
        "questions": rows,
    }
    kind = "retrieval" if args.retrieval_only else "answers"
    suffix = f"-{args.tag}" if args.tag else ""
    out = ROOT / "eval" / "results" / f"{args.mode}-{kind}{suffix}.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    print(f"全部：{fmt(overall)}")
    if not args.retrieval_only:
        print(f"      {fmt_scores(overall)}")
    for lang, s in report["by_lang"].items():
        print(f"{'中文' if lang == 'zh' else '英文'}：{fmt(s)}")
    misses = [r["id"] for r in rows if r["rr"] == 0]
    print(f"前 {args.top_k} 个结果都没命中的题：{', '.join(misses) or '无'}")
    print(f"总耗时 {elapsed:.1f} 秒；结果已保存到 {out.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
