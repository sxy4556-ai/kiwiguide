"""检索指标：hit@k 和 MRR，纯代码计算。

排名以检索返回的父块为单位；同一页面的多个父块各占一个名次，与回答时放进提示词的顺序一致。
"""


def _norm(url: str) -> str:
    """忽略末尾斜杠的差异，抓取时有的 URL 带斜杠、有的不带。"""
    return url.rstrip("/")


def hit_at_k(retrieved_urls: list[str], gold_urls: list[str], k: int) -> float:
    """前 k 个结果中只要有一个属于标准页面就记 1，否则记 0。"""
    gold = {_norm(u) for u in gold_urls}
    return 1.0 if any(_norm(u) in gold for u in retrieved_urls[:k]) else 0.0


def reciprocal_rank(retrieved_urls: list[str], gold_urls: list[str]) -> float:
    """第一个标准页面所在名次的倒数；没有命中记 0。"""
    gold = {_norm(u) for u in gold_urls}
    for rank, url in enumerate(retrieved_urls, 1):
        if _norm(url) in gold:
            return 1.0 / rank
    return 0.0


def summarize(rows: list[dict], ks: tuple[int, ...] = (1, 3, 5)) -> dict:
    """rows 中每项含 retrieved_urls 和 gold_urls，返回各指标在全部题目上的平均值。"""
    n = len(rows)
    if n == 0:
        return {"n": 0}
    out: dict = {"n": n}
    for k in ks:
        out[f"hit@{k}"] = sum(hit_at_k(r["retrieved_urls"], r["gold_urls"], k) for r in rows) / n
    out["mrr"] = sum(reciprocal_rank(r["retrieved_urls"], r["gold_urls"]) for r in rows) / n
    return out
