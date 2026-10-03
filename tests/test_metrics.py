"""检索指标测试：用手算的样例核对 hit@k 和 MRR。"""

import pytest

from app.eval.metrics import hit_at_k, reciprocal_rank, summarize

GOLD = ["https://www.tenancy.govt.nz/bond/"]
RANKED = [
    "https://www.tenancy.govt.nz/rent/",
    "https://www.tenancy.govt.nz/rent/",
    "https://www.tenancy.govt.nz/bond",  # 第 3 名命中，末尾斜杠不同也算
    "https://www.ird.govt.nz/tax/",
]


def test_hit_at_k_boundary():
    """hit@k 必须只看前 k 个：第 3 名命中时 hit@2 为 0、hit@3 为 1，差一位都会让基线对比失真。"""
    assert hit_at_k(RANKED, GOLD, 2) == 0.0
    assert hit_at_k(RANKED, GOLD, 3) == 1.0


def test_reciprocal_rank_uses_first_gold_position():
    """MRR 取第一个命中的名次的倒数：第 3 名命中记 1/3，完全没命中记 0。"""
    assert reciprocal_rank(RANKED, GOLD) == pytest.approx(1 / 3)
    assert reciprocal_rank(RANKED, ["https://other.govt.nz/"]) == 0.0
    assert reciprocal_rank(RANKED, GOLD + ["https://www.tenancy.govt.nz/rent"]) == 1.0


def test_summarize_averages_over_questions():
    """汇总值是逐题平均。手算 3 题（第 1 名、第 3 名、未命中）：
    hit@1=1/3，hit@3=2/3，MRR=(1+1/3+0)/3。"""
    rows = [
        {"retrieved_urls": ["a", "b"], "gold_urls": ["a"]},
        {"retrieved_urls": ["x", "y", "a"], "gold_urls": ["a"]},
        {"retrieved_urls": ["x", "y"], "gold_urls": ["a"]},
    ]
    result = summarize(rows, ks=(1, 3))
    assert result["n"] == 3
    assert result["hit@1"] == pytest.approx(1 / 3)
    assert result["hit@3"] == pytest.approx(2 / 3)
    assert result["mrr"] == pytest.approx((1 + 1 / 3) / 3)
