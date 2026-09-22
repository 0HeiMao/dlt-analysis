#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""中国体育彩票超级大乐透 历史数据分析工具 (dlt_tool).

本工具对超级大乐透历史开奖数据进行**描述性统计**、**概率推理**、
**随机性检验**与**参考号码生成**。

!! 重要声明 !!
------------------------------------------------------------------
超级大乐透每期开奖均为**相互独立的随机事件**。任何基于历史数据的
统计分析, 都**无法**预测未来任何一期的开奖结果, 也无法提高任何单个
组合的中奖概率。本工具的全部输出仅用于统计学习、数据分析与娱乐参考,
**不构成任何投注建议**。

彩票属于娱乐消费而非投资: 量力而行, 未成年人不得购彩, 中奖概率与投注
金额无关, 每 1 元投注的长期期望回报显著小于 1 元。理性购彩, 请勿沉迷。
------------------------------------------------------------------

运行环境: Python 3.10+ , 依赖 numpy / pandas / scipy (本机已装).
用法: python dlt_tool.py --help
"""

from __future__ import annotations

import argparse
import json
import math
import random
import sys
import traceback
from dataclasses import dataclass, field, asdict
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple

import numpy as np
import pandas as pd
from scipy import stats

# --------------------------------------------------------------------------- #
# 0. 控制台编码处理 (Windows 控制台默认 cp936 会导致中文乱码)
# --------------------------------------------------------------------------- #
def _configure_stdio_encoding() -> None:
    """尽最大努力将标准输出/错误流切换为 UTF-8, 失败则静默忽略."""
    for stream_name in ("stdout", "stderr"):
        stream = getattr(sys, stream_name, None)
        reconfigure = getattr(stream, "reconfigure", None)
        if callable(reconfigure):
            try:
                reconfigure(encoding="utf-8", errors="replace")
            except (ValueError, OSError):
                pass


_configure_stdio_encoding()


# --------------------------------------------------------------------------- #
# 1. 全局常量 (集中定义, 便于单测与校验)
# --------------------------------------------------------------------------- #
# 业务规则: 前区 01-35 选 5, 后区 01-12 选 2, 前区与后区相互独立.
FRONT_MIN: int = 1
FRONT_MAX: int = 35
FRONT_PICK: int = 5
BACK_MIN: int = 1
BACK_MAX: int = 12
BACK_PICK: int = 2

# 大小分界: 01-17 为小, 18-35 为大.
BIG_SMALL_BOUNDARY: int = 18

# 和值理论均值依据的分区中点 (用于数学推导校验).
FRONT_RANGE_SIZE: int = FRONT_MAX - FRONT_MIN + 1          # 35
BACK_RANGE_SIZE: int = BACK_MAX - BACK_MIN + 1             # 12

# 五个号码区间 (前区).
FRONT_ZONES: Tuple[Tuple[int, int], ...] = (
    (1, 7), (8, 14), (15, 21), (22, 28), (29, 35),
)

# 投注成本 (元).
BASE_BET_COST: float = 2.0       # 基本投注 2 元
ADDITIONAL_BET_COST: float = 1.0  # 追加 1 元 (追加总价 3 元)
OFFICIAL_RETURN_RATE: float = 0.51  # 财政规定返奖率约 51%

# 显著性水平.
DEFAULT_ALPHA: float = 0.05

# 随机种子 (保证可复现).
DEFAULT_SEED: int = 20240920

# 默认蒙特卡洛模拟期数.
DEFAULT_MC_TRIALS: int = 100_000

# 默认参考号码生成组数.
DEFAULT_GENERATE_COUNT: int = 5


# --------------------------------------------------------------------------- #
# 2. 奖级定义 (9 个奖级)
# --------------------------------------------------------------------------- #
# 每个奖级由若干互斥的 (前区命中数, 后区命中数) 子情形组成.
PRIZE_RULES: Dict[str, Tuple[Tuple[int, int], ...]] = {
    "一等奖": ((5, 2),),
    "二等奖": ((5, 1),),
    "三等奖": ((5, 0),),
    "四等奖": ((4, 2),),
    "五等奖": ((4, 1),),
    "六等奖": ((3, 2),),
    "七等奖": ((4, 0),),
    "八等奖": ((3, 1), (2, 2)),
    "九等奖": ((3, 0), (1, 2), (2, 1), (0, 2)),
}

# 奖级顺序 (从高到低), 用于稳定输出.
PRIZE_ORDER: Tuple[str, ...] = tuple(PRIZE_RULES.keys())

# 默认单注奖金示例字典 (仅用于演示, 非官方承诺, 用户可自定义).
DEFAULT_PRIZE_AMOUNTS: Dict[str, float] = {
    "一等奖": 8_000_000.0,
    "二等奖": 150_000.0,
    "三等奖": 10_000.0,
    "四等奖": 3_000.0,
    "五等奖": 300.0,
    "六等奖": 200.0,
    "七等奖": 100.0,
    "八等奖": 15.0,
    "九等奖": 5.0,
}

# 中奖号码判定中, 每个奖级只需唯一归属一次 (互斥); 八/九等奖含多个子情形.
PRIZE_LABEL_BY_HITS: Dict[Tuple[int, int], str] = {}
for _prize_name, _hit_cases in PRIZE_RULES.items():
    for _case in _hit_cases:
        # 子情形在 9 奖级体系内互不重叠, 直接建立映射即可.
        PRIZE_LABEL_BY_HITS.setdefault(_case, _prize_name)


# --------------------------------------------------------------------------- #
# 3. 数据模型
# --------------------------------------------------------------------------- #
@dataclass
class IssueRecord:
    """单期开奖记录.

    Attributes:
        issue: 期号 (字符串, 保持原始格式).
        date: 开奖日期, 规范化为 YYYY-MM-DD 字符串 (解析失败时为原始文本).
        front: 前区 5 个号码 (升序).
        back: 后区 2 个号码 (升序).
    """

    issue: str
    date: str
    front: Tuple[int, int, int, int, int]
    back: Tuple[int, int]

    def to_row(self) -> Dict[str, Any]:
        """转换为扁平字典 (便于写 CSV)."""
        return {
            "期号": self.issue,
            "开奖日期": self.date,
            "前区1": self.front[0],
            "前区2": self.front[1],
            "前区3": self.front[2],
            "前区4": self.front[3],
            "前区5": self.front[4],
            "后区1": self.back[0],
            "后区2": self.back[1],
        }


@dataclass
class CleanIssue:
    """单条清洗问题记录.

    Attributes:
        issue: 涉及期号 (无法识别时为空字符串).
        code: 规则码, 见 CLEAN_RULE_DESCRIPTIONS.
        level: 'error' 表示该条被丢弃; 'warning' 表示已自动修复后保留.
        detail: 明细说明.
    """

    issue: str
    code: str
    level: str
    detail: str


# 清洗规则码字典 (规则码 -> 说明).
CLEAN_RULE_DESCRIPTIONS: Dict[str, str] = {
    "MISSING_FIELD": "必填字段缺失或为空",
    "BAD_ISSUE": "期号为空或无法识别",
    "BAD_DATE": "开奖日期无法解析",
    "TOO_FEW_NUMBERS": "号码个数不足",
    "TOO_MANY_NUMBERS": "号码个数过多",
    "BAD_NUMBER_FORMAT": "号码非整数或格式非法",
    "FRONT_OUT_OF_RANGE": "前区号码超出 01-35 范围",
    "BACK_OUT_OF_RANGE": "后区号码超出 01-12 范围",
    "FRONT_DUPLICATE": "前区号码重复",
    "BACK_DUPLICATE": "后区号码重复",
    "NOT_SORTED": "号码未升序 (已自动排序)",
    "DUPLICATE_ISSUE": "期号重复 (保留首条)",
    "EMPTY_ROW": "空行",
    "COLUMN_MISMATCH": "列数与表头不符",
}


# --------------------------------------------------------------------------- #
# 4. 基础组合数学 (纯函数, 全部基于 math.comb)
# --------------------------------------------------------------------------- #
def count_front_combinations() -> int:
    """前区组合总数 C(35, 5) = 324,632."""
    return math.comb(FRONT_RANGE_SIZE, FRONT_PICK)


def count_back_combinations() -> int:
    """后区组合总数 C(12, 2) = 66."""
    return math.comb(BACK_RANGE_SIZE, BACK_PICK)


def count_total_combinations() -> int:
    """全组合总数 C(35,5) * C(12,2) = 21,425,712."""
    return count_front_combinations() * count_back_combinations()


def hypergeometric_probability(
    population: int,
    successes: int,
    draws: int,
    hits: int,
) -> float:
    """超几何分布质量函数 P(X = hits).

    对应"从 population 个对象中(含 successes 个成功对象)不放回抽取
    draws 个, 恰好抽中 hits 个成功对象"的概率.

    Args:
        population: 总体规模 (前区 35, 后区 12).
        successes: 总体中"成功"对象数 (前区 5, 后区 2).
        draws: 抽取个数 (前区 5, 后区 2).
        hits: 命中个数.

    Returns:
        概率 (0.0 表示不可能事件).
    """
    if draws < 0 or hits < 0 or hits > successes or hits > draws:
        return 0.0
    if draws - hits > population - successes:
        return 0.0
    numerator = math.comb(successes, hits) * math.comb(population - successes, draws - hits)
    denominator = math.comb(population, draws)
    if denominator == 0:
        return 0.0
    return numerator / denominator


def case_probability(front_hits: int, back_hits: int) -> float:
    """计算"前区命中 front_hits 且后区命中 back_hits"这一子情形的精确概率.

    公式: P = [C(5,a) * C(30,5-a) / C(35,5)] * [C(2,b) * C(10,2-b) / C(12,2)]
    其中 a = front_hits, b = back_hits. 前区与后区独立 -> 概率相乘.

    Args:
        front_hits: 前区命中个数 (0..5).
        back_hits: 后区命中个数 (0..2).

    Returns:
        该子情形的精确概率.
    """
    p_front = hypergeometric_probability(FRONT_RANGE_SIZE, FRONT_PICK, FRONT_PICK, front_hits)
    p_back = hypergeometric_probability(BACK_RANGE_SIZE, BACK_PICK, BACK_PICK, back_hits)
    return p_front * p_back


def case_count(front_hits: int, back_hits: int) -> int:
    """计算某子情形对应的组合数 (整数, 用于精确计数校验).

    组合数 = C(5,a)*C(30,5-a) * C(2,b)*C(10,2-b).

    Args:
        front_hits: 前区命中个数.
        back_hits: 后区命中个数.

    Returns:
        对应的组合数 (整数).
    """
    front_part = math.comb(FRONT_PICK, front_hits) * math.comb(
        FRONT_RANGE_SIZE - FRONT_PICK, FRONT_PICK - front_hits
    )
    back_part = math.comb(BACK_PICK, back_hits) * math.comb(
        BACK_RANGE_SIZE - BACK_PICK, BACK_PICK - back_hits
    )
    return front_part * back_part


def prize_probabilities() -> Dict[str, Dict[str, Any]]:
    """计算 9 个奖级的理论中奖概率.

    每个奖级由若干互斥子情形组成, 概率为该奖级所有子情形概率之和;
    组合数为子情形组合数之和.

    Returns:
        字典: 奖级 -> {"probability": float, "one_in": float,
                       "count": int, "cases": [(a,b), ...]}.
    """
    result: Dict[str, Dict[str, Any]] = {}
    for prize_name in PRIZE_ORDER:
        cases = PRIZE_RULES[prize_name]
        probability = sum(case_probability(a, b) for a, b in cases)
        count = sum(case_count(a, b) for a, b in cases)
        one_in = (1.0 / probability) if probability > 0.0 else float("inf")
        result[prize_name] = {
            "probability": probability,
            "one_in": one_in,
            "count": count,
            "cases": list(cases),
        }
    return result


def any_prize_probability() -> float:
    """至少中任意一个奖级的概率 (9 奖级概率之和, 因互斥)."""
    probs = prize_probabilities()
    return float(sum(item["probability"] for item in probs.values()))


def self_consistency_check() -> Dict[str, Any]:
    """概率自洽性断言 (精确计数法).

    校验三件事:
      1. 9 奖级组合数之和 == 全部未中奖组合数 + 各奖级组合数 == 总组合数.
         (即: 所有 (a,b) 子情形组合数之和 == C(35,5)*C(12,2))
      2. 至少中奖概率 + 未中奖概率 == 1 (误差 < 1e-12).
      3. 九等奖内部 4 个子情形互斥且计数与概率一致.

    Returns:
        含各项校验明细与总判定 'passed' 的结果字典. 断言失败会抛 AssertionError.
    """
    total = count_total_combinations()

    # --- 校验 1: 枚举全部 (a, b) 子情形组合数求和 ---
    enumerated_total = 0
    for a in range(0, FRONT_PICK + 1):
        for b in range(0, BACK_PICK + 1):
            enumerated_total += case_count(a, b)

    # --- 校验 2: 至少中奖 + 未中奖 == 1 ---
    win_cases = sum(case_count(a, b) for a in range(0, FRONT_PICK + 1)
                    for b in range(0, BACK_PICK + 1)
                    if (a, b) in PRIZE_LABEL_BY_HITS)
    lose_cases = total - win_cases
    p_win_count = win_cases / total
    p_win_formula = any_prize_probability()
    p_lose_formula = case_probability(0, 0) + case_probability(0, 1) + case_probability(1, 0) \
        + case_probability(1, 1) + case_probability(2, 0)
    # 未中奖子情形: (0,0)(0,1)(1,0)(1,1)(2,0)
    lose_cases_expected = case_count(0, 0) + case_count(0, 1) + case_count(1, 0) \
        + case_count(1, 1) + case_count(2, 0)
    assert lose_cases == lose_cases_expected, (
        f"未中奖组合数不符: {lose_cases} != {lose_cases_expected}"
    )

    # --- 校验 3: 九等奖子情形互斥合并 ---
    ninth = PRIZE_RULES["九等奖"]
    ninth_count_sum = sum(case_count(a, b) for a, b in ninth)
    ninth_prob_sum = sum(case_probability(a, b) for a, b in ninth)
    ninth_from_table = prize_probabilities()["九等奖"]["count"]
    assert ninth_count_sum == ninth_from_table, "九等奖计数不一致"
    assert abs(ninth_prob_sum - prize_probabilities()["九等奖"]["probability"]) < 1e-15, (
        "九等奖概率不一致"
    )

    checks = {
        "total_combinations": total,
        "enumerated_case_sum": enumerated_total,
        "enumerated_equals_total": enumerated_total == total,
        "win_cases": win_cases,
        "lose_cases": lose_cases,
        "win_plus_lose_equals_total": win_cases + lose_cases == total,
        "p_win_by_count": p_win_count,
        "p_win_by_formula": p_win_formula,
        "p_win_abs_diff": abs(p_win_count - p_win_formula),
        "p_win_plus_p_lose": p_win_formula + p_lose_formula,
        "ninth_count_by_cases": ninth_count_sum,
        "ninth_count_by_table": ninth_from_table,
        "ninth_prob_abs_diff": abs(
            ninth_prob_sum - prize_probabilities()["九等奖"]["probability"]
        ),
    }
    passed = (
        checks["enumerated_equals_total"]
        and checks["win_plus_lose_equals_total"]
        and checks["p_win_abs_diff"] < 1e-12
        and abs(checks["p_win_plus_p_lose"] - 1.0) < 1e-12
        and checks["ninth_count_by_cases"] == checks["ninth_count_by_table"]
        and checks["ninth_prob_abs_diff"] < 1e-15
    )
    checks["passed"] = bool(passed)
    assert passed, f"概率自洽性校验失败: {checks}"
    return checks


def monte_carlo_probability_check(trials: int = 200_000, seed: int = DEFAULT_SEED) -> Dict[str, Any]:
    """蒙特卡洛验证: 随机抽取模拟号码, 统计各奖级频率与理论概率比对.

    这是一个**小样本蒙特卡洛自洽性验证**, 用于交叉确认公式实现无误
    (理论概率极小的奖级在有限试验下可能一次都不命中, 属正常现象).

    Args:
        trials: 模拟注数.
        seed: 随机种子.

    Returns:
        各奖级 (命中数, 模拟频率, 理论概率, 绝对误差) 与结论.
    """
    rng = np.random.default_rng(seed)
    prize_probs = prize_probabilities()

    # 向量化模拟: 固定"投注号码"为 前区 01-05 / 后区 01-02 (与开奖独立)。
    # 每行用 argpartition 取 k 个最小随机键, 等价于不放回均匀抽取 k 个号码。
    front_idx = np.argpartition(
        rng.random((trials, FRONT_RANGE_SIZE)), FRONT_PICK - 1, axis=1
    )[:, :FRONT_PICK]
    back_idx = np.argpartition(
        rng.random((trials, BACK_RANGE_SIZE)), BACK_PICK - 1, axis=1
    )[:, :BACK_PICK]
    a = np.isin(front_idx, np.arange(0, FRONT_PICK)).sum(axis=1)
    b = np.isin(back_idx, np.arange(0, BACK_PICK)).sum(axis=1)

    # (前命中, 后命中) -> 奖级索引; -1 表示未中奖 (子情形互斥, 查表唯一)。
    lookup = np.full((FRONT_PICK + 1) * (BACK_PICK + 1), -1, dtype=int)
    for prize_index, prize_name in enumerate(PRIZE_ORDER):
        for fa, ba in PRIZE_RULES[prize_name]:
            lookup[fa * (BACK_PICK + 1) + ba] = prize_index
    labels = lookup[a * (BACK_PICK + 1) + b]
    hit_counts_arr = np.bincount(labels[labels >= 0], minlength=len(PRIZE_ORDER))
    no_prize = int((labels == -1).sum())

    details: Dict[str, Dict[str, float]] = {}
    for prize_index, name in enumerate(PRIZE_ORDER):
        hits = int(hit_counts_arr[prize_index])
        empirical = hits / trials
        theoretical = prize_probs[name]["probability"]
        details[name] = {
            "hits": hits,
            "empirical": empirical,
            "theoretical": theoretical,
            "abs_diff": abs(empirical - theoretical),
        }
    no_prize_empirical = no_prize / trials
    no_prize_theoretical = 1.0 - any_prize_probability()

    return {
        "trials": trials,
        "seed": seed,
        "prizes": details,
        "no_prize": {
            "hits": no_prize,
            "empirical": no_prize_empirical,
            "theoretical": no_prize_theoretical,
            "abs_diff": abs(no_prize_empirical - no_prize_theoretical),
        },
    }


def expected_value(prize_amounts: Optional[Dict[str, float]] = None,
                   bet_cost: float = BASE_BET_COST) -> Dict[str, Any]:
    """计算单注数学期望值与返奖率.

    数学期望值 E = Σ(P_i * Amount_i) - bet_cost, 其中 i 遍历 9 个奖级.
    每 1 元期望回报 = (E + bet_cost) / bet_cost = Σ(P_i * Amount_i) / bet_cost.
    返奖率 = Σ(P_i * Amount_i) / bet_cost (与每元期望回报同值).

    Args:
        prize_amounts: 奖级 -> 单注奖金字典; 默认使用 DEFAULT_PRIZE_AMOUNTS.
        bet_cost: 单注投注成本 (元), 默认 2 元.

    Returns:
        含各奖级期望贡献、总期望回报、期望值、每元期望回报、返奖率、
        期望亏损、以及相对官方 51% 返奖率对照的结果字典.
    """
    amounts = dict(DEFAULT_PRIZE_AMOUNTS if prize_amounts is None else prize_amounts)
    # 补齐缺失奖级为 0.
    for name in PRIZE_ORDER:
        amounts.setdefault(name, 0.0)

    prize_probs = prize_probabilities()
    per_prize: Dict[str, Dict[str, float]] = {}
    gross_return = 0.0
    for name in PRIZE_ORDER:
        p = prize_probs[name]["probability"]
        amount = float(amounts[name])
        contribution = p * amount
        gross_return += contribution
        per_prize[name] = {
            "probability": p,
            "amount": amount,
            "expectation_contribution": contribution,
        }

    ev = gross_return - bet_cost
    per_yuan = gross_return / bet_cost if bet_cost > 0 else 0.0
    return_rate = per_yuan

    return {
        "bet_cost": bet_cost,
        "prize_amounts": amounts,
        "per_prize": per_prize,
        "gross_return_per_bet": gross_return,
        "expected_value_per_bet": ev,
        "expected_return_per_yuan": per_yuan,
        "return_rate": return_rate,
        "expected_loss_per_bet": -ev,
        # 官方规定返奖率约 51%，示例奖金字典仅用于演示.
        "official_return_rate_reference": OFFICIAL_RETURN_RATE,
        "return_rate_vs_official": return_rate - OFFICIAL_RETURN_RATE,
    }


# --------------------------------------------------------------------------- #
# 5. 理论分布 (和值 / 奇偶 / 大小 / 连号) 的解析计算
# --------------------------------------------------------------------------- #
def all_front_combinations() -> List[Tuple[int, int, int, int, int]]:
    """枚举全部前区组合 C(35,5) = 324,632 种 (用于精确分布计算)."""
    from itertools import combinations
    return list(combinations(range(FRONT_MIN, FRONT_MAX + 1), FRONT_PICK))


def theoretical_sum_distribution() -> Dict[str, float]:
    """前区 5 个号码和值的理论分布 (精确枚举 C(35,5) 种组合).

    Returns:
        {"mean": 理论均值, "variance": 理论方差, "std": 理论标准差,
         "distribution": {和值: 概率}}.
    """
    combos = all_front_combinations()
    total = len(combos)
    counter: Dict[int, int] = {}
    for combo in combos:
        counter[sum(combo)] = counter.get(sum(combo), 0) + 1
    distribution = {s: c / total for s, c in sorted(counter.items())}
    mean = sum(s * p for s, p in distribution.items())
    var = sum((s - mean) ** 2 * p for s, p in distribution.items())
    return {
        "mean": mean,
        "variance": var,
        "std": math.sqrt(var),
        "distribution": distribution,
    }


def theoretical_sum_mean_variance_formula() -> Dict[str, float]:
    """用不放回抽样公式推导前区和值理论均值/方差 (解析解, 供交叉校验).

    设 35 个号码为 1..35, 不放回抽取 5 个.
    单次抽取的总体均值 mu = (1+35)/2 = 18, 总体方差 sigma^2 = (n^2-1)/12
    其中 n = 35 -> sigma^2 = (35^2-1)/12 = 102.
    和值 = 5 个号码之和, 期望 = 5*mu; 方差 = 5*sigma^2*(N-5)/(N-1) (有限总体校正).

    Returns:
        {"mean": 解析均值, "variance": 解析方差, "std": 解析标准差}.
    """
    n = FRONT_RANGE_SIZE
    k = FRONT_PICK
    mu = (FRONT_MIN + FRONT_MAX) / 2.0
    sigma2 = (n * n - 1) / 12.0
    mean = k * mu
    variance = k * sigma2 * (n - k) / (n - 1)
    return {"mean": mean, "variance": variance, "std": math.sqrt(variance)}


def theoretical_odd_count_distribution() -> Dict[int, float]:
    """前区奇数个数分布 (奇数共 18 个: 1,3,...,35).

    Returns:
        {奇数个数: 理论概率}, 键范围 0..5.
    """
    odd_total = len([x for x in range(FRONT_MIN, FRONT_MAX + 1) if x % 2 == 1])  # 18
    dist: Dict[int, float] = {}
    for k in range(0, FRONT_PICK + 1):
        dist[k] = hypergeometric_probability(FRONT_RANGE_SIZE, odd_total, FRONT_PICK, k)
    return dist


def theoretical_big_count_distribution() -> Dict[int, float]:
    """前区大号 (>=18) 个数分布 (大号共 18 个: 18..35).

    Returns:
        {大号个数: 理论概率}, 键范围 0..5.
    """
    big_total = len([x for x in range(FRONT_MIN, FRONT_MAX + 1) if x >= BIG_SMALL_BOUNDARY])  # 18
    dist: Dict[int, float] = {}
    for k in range(0, FRONT_PICK + 1):
        dist[k] = hypergeometric_probability(FRONT_RANGE_SIZE, big_total, FRONT_PICK, k)
    return dist


def theoretical_zone_distribution() -> Dict[int, float]:
    """单号落入某区间 (每区 7 个号) 的期望个数.

    Returns:
        {区间索引 1..5: 该区每期期望命中号码个数}.
    """
    dist: Dict[int, float] = {}
    for idx, (lo, hi) in enumerate(FRONT_ZONES, start=1):
        size = hi - lo + 1
        # 每期 5 个号, 该区被命中的期望个数 = 5 * size / 35.
        dist[idx] = FRONT_PICK * size / FRONT_RANGE_SIZE
    return dist


def count_consecutive_groups(numbers: Sequence[int]) -> int:
    """统计一组升序号码中"连号组"的数量.

    连号组定义: 连续整数构成的极大连通块 (长度 >= 2) 记为一个连号组.
    例如 [1,2,3,7,8] 有 2 个连号组 (1-2-3 与 7-8).

    Args:
        numbers: 升序号码序列.

    Returns:
        连号组数量.
    """
    if len(numbers) == 0:
        return 0
    groups = 0
    run = 1
    for i in range(1, len(numbers)):
        if numbers[i] == numbers[i - 1] + 1:
            run += 1
        else:
            if run >= 2:
                groups += 1
            run = 1
    if run >= 2:
        groups += 1
    return groups


def theoretical_consecutive_group_distribution() -> Dict[int, float]:
    """前区连号组数量的理论分布 (精确枚举 C(35,5)).

    Returns:
        {连号组数量: 理论概率}.
    """
    combos = all_front_combinations()
    total = len(combos)
    counter: Dict[int, int] = {}
    for combo in combos:
        g = count_consecutive_groups(combo)
        counter[g] = counter.get(g, 0) + 1
    return {g: counter.get(g, 0) / total for g in range(0, FRONT_PICK)}


def theoretical_repeat_expectation() -> float:
    """相邻两期前区重复号码个数 (重号) 的期望值.

    上一期前区 5 个号码, 本期从 35 个号中抽 5 个, 每个上期号码是否
    被本期命中服从超几何; 重号数 X 的期望 = 5 * 5 / 35 = 25/35.

    Returns:
        期望重号个数.
    """
    return FRONT_PICK * FRONT_PICK / FRONT_RANGE_SIZE


def theoretical_repeat_distribution() -> Dict[int, float]:
    """相邻两期前区重号个数的理论分布.

    本期从 35 号中抽 5 个, 命中上期 5 个号码中的 k 个 -> 超几何.

    Returns:
        {重号个数: 理论概率}, 键范围 0..5.
    """
    dist: Dict[int, float] = {}
    for k in range(0, FRONT_PICK + 1):
        dist[k] = hypergeometric_probability(FRONT_RANGE_SIZE, FRONT_PICK, FRONT_PICK, k)
    return dist


# --------------------------------------------------------------------------- #
# 6. 数据加载与清洗
# --------------------------------------------------------------------------- #
def _parse_date(raw: str) -> Optional[str]:
    """解析多种日期格式, 返回规范化 YYYY-MM-DD; 失败返回 None.

    支持: YYYY-MM-DD / YYYY/MM/DD / YYYYMMDD / YYYY.MM.DD.
    """
    text = str(raw).strip()
    if not text:
        return None
    formats = ("%Y-%m-%d", "%Y/%m/%d", "%Y%m%d", "%Y.%m.%d")
    for fmt in formats:
        try:
            return datetime.strptime(text, fmt).strftime("%Y-%m-%d")
        except ValueError:
            continue
    return None


def _extract_numbers_from_cell(cell: str) -> List[int]:
    """从单个单元格中容错提取整数号码 (支持空格/逗号/顿号/连字符分隔)."""
    import re
    tokens = re.split(r"[\s,，、;；|\-]+", str(cell).strip())
    numbers: List[int] = []
    for tok in tokens:
        if tok == "":
            continue
        try:
            numbers.append(int(tok))
        except ValueError:
            # 非整数 token 视为格式错误, 由上层记录.
            raise ValueError(f"非整数 token: {tok!r}")
    return numbers


def _row_to_record(row: pd.Series, row_index: int,
                   issues: List[CleanIssue]) -> Optional[IssueRecord]:
    """将一行原始数据转换为 IssueRecord, 失败返回 None 并追加问题记录.

    容错策略: 若"前区1..5 / 后区1..2"7 列齐全则直接使用; 否则尝试把
    "号码"类列或剩余列拆分为 7 个整数 (前 5 个前区, 后 2 个后区).
    """
    raw_issue = str(row.get("期号", "")).strip()
    if raw_issue == "" or raw_issue.lower() in ("nan", "none"):
        issues.append(CleanIssue("", "BAD_ISSUE", "error", f"第 {row_index} 行期号为空"))
        return None

    raw_date = str(row.get("开奖日期", "")).strip()
    date_norm = _parse_date(raw_date)
    if date_norm is None:
        issues.append(CleanIssue(raw_issue, "BAD_DATE", "warning",
                                 f"日期 {raw_date!r} 无法解析, 保留原文本"))
        date_norm = raw_date

    front_cols = ["前区1", "前区2", "前区3", "前区4", "前区5"]
    back_cols = ["后区1", "后区2"]

    numbers: List[int] = []
    has_std_columns = all(col in row.index for col in front_cols + back_cols) and all(
        str(row.get(col, "")).strip() not in ("", "nan", "NaN", "None")
        for col in front_cols + back_cols
    )

    if has_std_columns:
        for col in front_cols + back_cols:
            cell = row.get(col)
            try:
                numbers.append(int(str(cell).strip()))
            except ValueError:
                try:
                    numbers.append(int(float(str(cell).strip())))
                except ValueError:
                    issues.append(CleanIssue(
                        raw_issue, "BAD_NUMBER_FORMAT", "error",
                        f"字段 {col} 值 {cell!r} 非整数"))
                    return None
    else:
        # 容错: 将非 期号/开奖日期 的单元格内容合并解析.
        collected: List[int] = []
        parse_error = False
        for col in row.index:
            if col in ("期号", "开奖日期"):
                continue
            cell = row.get(col)
            if str(cell).strip() in ("", "nan", "NaN", "None"):
                continue
            try:
                collected.extend(_extract_numbers_from_cell(str(cell)))
            except ValueError:
                parse_error = True
        if parse_error:
            issues.append(CleanIssue(raw_issue, "BAD_NUMBER_FORMAT", "error",
                                     "号码单元格含非整数内容"))
            return None
        numbers = collected
        if len(numbers) != FRONT_PICK + BACK_PICK:
            code = "TOO_FEW_NUMBERS" if len(numbers) < FRONT_PICK + BACK_PICK else "TOO_MANY_NUMBERS"
            issues.append(CleanIssue(raw_issue, code, "error",
                                     f"解析得到 {len(numbers)} 个号码, 期望 7 个"))
            return None

    if len(numbers) != FRONT_PICK + BACK_PICK:
        code = "TOO_FEW_NUMBERS" if len(numbers) < FRONT_PICK + BACK_PICK else "TOO_MANY_NUMBERS"
        issues.append(CleanIssue(raw_issue, code, "error",
                                 f"号码个数为 {len(numbers)}, 期望 7"))
        return None

    front_raw = numbers[:FRONT_PICK]
    back_raw = numbers[FRONT_PICK:]

    # 范围校验.
    for n in front_raw:
        if not (FRONT_MIN <= n <= FRONT_MAX):
            issues.append(CleanIssue(raw_issue, "FRONT_OUT_OF_RANGE", "error",
                                     f"前区号码 {n} 超出 {FRONT_MIN}-{FRONT_MAX}"))
            return None
    for n in back_raw:
        if not (BACK_MIN <= n <= BACK_MAX):
            issues.append(CleanIssue(raw_issue, "BACK_OUT_OF_RANGE", "error",
                                     f"后区号码 {n} 超出 {BACK_MIN}-{BACK_MAX}"))
            return None

    # 重复校验.
    if len(set(front_raw)) != FRONT_PICK:
        issues.append(CleanIssue(raw_issue, "FRONT_DUPLICATE", "error",
                                 f"前区号码重复: {front_raw}"))
        return None
    if len(set(back_raw)) != BACK_PICK:
        issues.append(CleanIssue(raw_issue, "BACK_DUPLICATE", "error",
                                 f"后区号码重复: {back_raw}"))
        return None

    # 升序校验 (未升序则自动排序并 warning).
    front_sorted = sorted(front_raw)
    back_sorted = sorted(back_raw)
    if front_raw != front_sorted:
        issues.append(CleanIssue(raw_issue, "NOT_SORTED", "warning",
                                 f"前区未升序, 已排序: {front_raw} -> {front_sorted}"))
    if back_raw != back_sorted:
        issues.append(CleanIssue(raw_issue, "NOT_SORTED", "warning",
                                 f"后区未升序, 已排序: {back_raw} -> {back_sorted}"))

    return IssueRecord(
        issue=raw_issue,
        date=date_norm,
        front=(front_sorted[0], front_sorted[1], front_sorted[2],
               front_sorted[3], front_sorted[4]),
        back=(back_sorted[0], back_sorted[1]),
    )


def clean_records(raw_df: pd.DataFrame) -> Tuple[pd.DataFrame, Dict[str, Any]]:
    """清洗并校验原始开奖数据.

    校验规则 (违规必记录, 不静默丢弃):
      - 期号为空 -> error, 丢弃
      - 日期无法解析 -> warning, 保留原文本
      - 号码个数不足/过多 -> error, 丢弃
      - 号码非整数 -> error, 丢弃
      - 前区超出 01-35 / 后区超出 01-12 -> error, 丢弃
      - 前区/后区号码重复 -> error, 丢弃
      - 前区/后区未升序 -> warning, 自动排序
      - 期号重复 -> error, 保留首条并去重
      - 空行 -> warning

    Args:
        raw_df: 原始 DataFrame (列名应为 期号/开奖日期/前区1..5/后区1..2).

    Returns:
        (清洗后 DataFrame, 清洗报告 dict).
    """
    issues: List[CleanIssue] = []
    original_rows = int(len(raw_df))
    records: List[IssueRecord] = []
    seen_issues: set[str] = set()
    dropped_rows = 0

    for idx, row in raw_df.iterrows():
        # 空行检测: 全字段空白.
        if all(str(v).strip() in ("", "nan", "NaN", "None") for v in row.values):
            issues.append(CleanIssue("", "EMPTY_ROW", "warning", f"第 {idx} 行为空行"))
            dropped_rows += 1
            continue

        record = _row_to_record(row, int(idx) if isinstance(idx, (int, np.integer)) else 0, issues)
        if record is None:
            dropped_rows += 1
            continue

        # 期号去重 (保留首条).
        if record.issue in seen_issues:
            issues.append(CleanIssue(record.issue, "DUPLICATE_ISSUE", "error",
                                     "期号重复, 已丢弃后出现的重复记录"))
            dropped_rows += 1
            continue
        seen_issues.add(record.issue)
        records.append(record)

    clean_df = pd.DataFrame([r.to_row() for r in records]) if records else pd.DataFrame(
        columns=["期号", "开奖日期", "前区1", "前区2", "前区3", "前区4", "前区5", "后区1", "后区2"]
    )

    # 汇总各类问题计数.
    code_counts: Dict[str, int] = {}
    level_counts: Dict[str, int] = {"error": 0, "warning": 0}
    for issue in issues:
        code_counts[issue.code] = code_counts.get(issue.code, 0) + 1
        level_counts[issue.level] = level_counts.get(issue.level, 0) + 1

    issue_rows = [
        {
            "期号": i.issue,
            "规则码": i.code,
            "级别": i.level,
            "明细": i.detail,
            "规则说明": CLEAN_RULE_DESCRIPTIONS.get(i.code, ""),
        }
        for i in issues
    ]

    report: Dict[str, Any] = {
        "original_rows": original_rows,
        "valid_rows": int(len(clean_df)),
        "dropped_rows": dropped_rows,
        "warning_count": level_counts["warning"],
        "error_count": level_counts["error"],
        "code_counts": code_counts,
        "issues": issue_rows,
    }
    return clean_df, report


def load_data(source: str, input_path: Optional[str] = None) -> Tuple[pd.DataFrame, Dict[str, Any]]:
    """加载数据并按来源执行清洗.

    Args:
        source: 'csv' | 'json' | 'sample' | 'builtin' 之一.
        input_path: csv/json 文件路径 (source 为 sample 时忽略).

    Returns:
        (清洗后 DataFrame, 清洗报告 dict). 报告含 'source' 字段.
    """
    src = source.lower()
    parse_issues: List[Dict[str, str]] = []
    if src in ("sample", "builtin", "simulated"):
        raw_df = build_sample_dataframe()
        report_source = "builtin_sample(simulated)"
    elif src == "csv":
        if not input_path:
            raise ValueError("--source csv 时必须提供 --input")
        raw_df, parse_issues = read_csv_tolerant(input_path)
        report_source = f"csv:{input_path}"
    elif src == "json":
        if not input_path:
            raise ValueError("--source json 时必须提供 --input")
        with open(input_path, "r", encoding="utf-8-sig") as fh:
            payload = json.load(fh)
        if isinstance(payload, dict):
            payload = payload.get("data", payload.get("records", []))
        raw_df = pd.DataFrame(payload)
        # 统一为字符串列, 便于复用清洗逻辑.
        raw_df = raw_df.astype(str)
        report_source = f"json:{input_path}"
    else:
        raise ValueError(f"未知数据来源: {source}")

    clean_df, report = clean_records(raw_df)
    if parse_issues:
        merge_parse_issues(report, parse_issues)
    report["source"] = report_source
    report["raw_columns"] = list(raw_df.columns)
    return clean_df, report


def build_sample_dataframe(num_issues: int = 600, seed: int = DEFAULT_SEED) -> pd.DataFrame:
    """生成内置模拟数据集 (固定随机种子, 显式标注为模拟数据).

    !! 本函数生成的数据为**模拟数据**, 仅用于演示工具能力, 非真实开奖记录 !!

    Args:
        num_issues: 期数 (默认 600 期, >= 500).
        seed: 随机种子.

    Returns:
        含 期号/开奖日期/前区1..5/后区1..2 的 DataFrame.
    """
    num_issues = max(num_issues, 500)
    rng = np.random.default_rng(seed)
    front_pool = np.arange(FRONT_MIN, FRONT_MAX + 1)
    back_pool = np.arange(BACK_MIN, BACK_MAX + 1)

    start_date = datetime(2015, 1, 3)
    rows: List[Dict[str, Any]] = []
    for i in range(num_issues):
        front = sorted(int(x) for x in rng.choice(front_pool, size=FRONT_PICK, replace=False))
        back = sorted(int(x) for x in rng.choice(back_pool, size=BACK_PICK, replace=False))
        # 每期大致 3 天一期 (周一/周三/周六), 简化处理.
        date = start_date + pd.Timedelta(days=3 * i)
        rows.append({
            "期号": f"SIM{i + 1:05d}",
            "开奖日期": date.strftime("%Y-%m-%d"),
            "前区1": front[0], "前区2": front[1], "前区3": front[2],
            "前区4": front[3], "前区5": front[4],
            "后区1": back[0], "后区2": back[1],
        })
    return pd.DataFrame(rows)


def write_sample_csv(path: str, num_issues: int = 600, seed: int = DEFAULT_SEED) -> int:
    """生成并落盘模拟数据集为 CSV, 首部写入中文注释行标注为模拟数据.

    Args:
        path: 输出路径.
        num_issues: 期数.
        seed: 随机种子.

    Returns:
        写入的数据行数 (不含注释行).
    """
    df = build_sample_dataframe(num_issues=num_issues, seed=seed)
    out_path = Path(path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with open(out_path, "w", encoding="utf-8", newline="") as fh:
        fh.write("# 本文件为【模拟数据】, 仅用于演示 dlt_tool 的分析能力, 非真实开奖记录。\n")
        fh.write("# 生成方式: 固定随机种子 seed=%d, 均匀随机抽取, 仅供统计分析教学演示。\n" % seed)
        fh.write("# 字段: 期号,开奖日期,前区1..前区5,后区1,后区2\n")
        df.to_csv(fh, index=False)
    return len(df)


def read_csv_tolerant(path: str) -> Tuple[pd.DataFrame, List[Dict[str, str]]]:
    """容错读取 CSV (纯函数).

    规则:
      - 以 '#' 开头的注释行自动跳过 (不记录问题);
      - 完全空白的行记为 EMPTY_ROW (warning), 不进入 DataFrame;
      - 列数与表头不符的行记为 COLUMN_MISMATCH (error), 不进入 DataFrame;
      - 其余行为原生解析, 交由 clean_records 做后续校验.

    Args:
        path: CSV 文件路径.

    Returns:
        (DataFrame, 解析层问题列表); 每个问题为
        {'issue': 期号或空, 'code': 规则码, 'level': 级别, 'detail': 明细}.
    """
    import csv as _csv
    from io import StringIO

    lines: List[str] = []
    # utf-8-sig: 同时兼容带 BOM 与不带 BOM 的 UTF-8 文件 (BOM 会被自动剥离).
    with open(path, "r", encoding="utf-8-sig") as fh:
        for line in fh:
            if line.lstrip().startswith("#"):
                continue
            lines.append(line)

    parse_issues: List[Dict[str, str]] = []
    parsed_rows: List[List[str]] = []
    for row in _csv.reader(StringIO("".join(lines))):
        if not row:
            parse_issues.append({
                "issue": "", "code": "EMPTY_ROW", "level": "warning",
                "detail": "CSV 中存在完全空白的行, 解析时跳过",
            })
            continue
        parsed_rows.append(row)

    if not parsed_rows:
        return pd.DataFrame(), parse_issues

    header = [h.strip() for h in parsed_rows[0]]
    n_cols = len(header)
    good_rows: List[List[str]] = []
    for row_index, row in enumerate(parsed_rows[1:], start=2):
        if len(row) != n_cols:
            parse_issues.append({
                "issue": (row[0].strip() if row else ""),
                "code": "COLUMN_MISMATCH", "level": "error",
                "detail": (f"数据第 {row_index - 1} 行列数为 {len(row)}, "
                           f"与表头列数 {n_cols} 不符 (内容: {','.join(row)[:60]})"),
            })
            continue
        good_rows.append(row)

    if good_rows:
        df = pd.DataFrame(good_rows, columns=header)
    else:
        df = pd.DataFrame(columns=header)
    return df, parse_issues


def merge_parse_issues(report: Dict[str, Any],
                       parse_issues: List[Dict[str, str]]) -> Dict[str, Any]:
    """将 CSV 解析层问题合并进清洗报告 (保持 原始=有效+丢弃 的算术自洽).

    Args:
        report: clean_records 产出的清洗报告.
        parse_issues: read_csv_tolerant 产出的解析层问题列表.

    Returns:
        合并后的报告 (原字典就地修改并返回).
    """
    for pi in parse_issues:
        report["issues"].append({
            "期号": pi["issue"],
            "规则码": pi["code"],
            "级别": pi["level"],
            "明细": pi["detail"],
            "规则说明": CLEAN_RULE_DESCRIPTIONS.get(pi["code"], ""),
        })
        report["code_counts"][pi["code"]] = report["code_counts"].get(pi["code"], 0) + 1
        report[f"{pi['level']}_count"] += 1
        report["original_rows"] += 1
        report["dropped_rows"] += 1
    return report


# --------------------------------------------------------------------------- #
# 7. 描述性统计
# --------------------------------------------------------------------------- #
def compute_frequency(df: pd.DataFrame, zone: str) -> pd.DataFrame:
    """计算号码出现频次与频率.

    统计口径: 遍历全部有效期, 逐期对前区 5 个号 / 后区 2 个号计数.
    频率 = 出现次数 / 总期数 (前区每期贡献 5 次计数, 故频率之和 = 5).

    Args:
        df: 清洗后 DataFrame.
        zone: 'front' 或 'back'.

    Returns:
        含 号码/出现次数/频率/理论期望频次 的 DataFrame (按号码升序).
    """
    if zone == "front":
        cols = ["前区1", "前区2", "前区3", "前区4", "前区5"]
        number_range = range(FRONT_MIN, FRONT_MAX + 1)
        per_issue_pick = FRONT_PICK
    else:
        cols = ["后区1", "后区2"]
        number_range = range(BACK_MIN, BACK_MAX + 1)
        per_issue_pick = BACK_PICK

    total_issues = int(len(df))
    counts: Dict[int, int] = {n: 0 for n in number_range}
    for col in cols:
        if col not in df.columns:
            continue
        for value in df[col].tolist():
            try:
                n = int(value)
            except (ValueError, TypeError):
                continue
            if n in counts:
                counts[n] += 1

    theoretical_per_number = (total_issues * per_issue_pick / len(list(number_range))) \
        if total_issues > 0 else 0.0
    rows = []
    for n in number_range:
        c = counts[n]
        freq = (c / total_issues) if total_issues > 0 else 0.0
        rows.append({
            "号码": n,
            "出现次数": c,
            "频率": freq,
            "理论期望频次": theoretical_per_number,
        })
    return pd.DataFrame(rows)


def compute_hot_cold(df: pd.DataFrame, zone: str, top_n: int = 5) -> Dict[str, Any]:
    """冷热号统计.

    Args:
        df: 清洗后 DataFrame.
        zone: 'front' 或 'back'.
        top_n: Top-N / Bottom-N 的 N.

    Returns:
        {"hot": [ {号码, 出现次数, 频率, 理论期望频次}, ... ],
         "cold": [...], "theoretical": 理论单号频次}.
    """
    freq_df = compute_frequency(df, zone).sort_values(
        by=["出现次数", "号码"], ascending=[False, True]).reset_index(drop=True)
    cold_df = compute_frequency(df, zone).sort_values(
        by=["出现次数", "号码"], ascending=[True, True]).reset_index(drop=True)
    theoretical = float(freq_df["理论期望频次"].iloc[0]) if len(freq_df) else 0.0
    return {
        "hot": freq_df.head(top_n).to_dict(orient="records"),
        "cold": cold_df.head(top_n).to_dict(orient="records"),
        "theoretical": theoretical,
    }


def compute_missing_values(df: pd.DataFrame, zone: str) -> pd.DataFrame:
    """计算遗漏值.

    定义:
      - 当前遗漏 = 总期数 - 1 - (该号最近一次出现的期序号); 若从未出现则为总期数.
      - 历史最大遗漏 = 该号在序列中两次出现之间的最大间隔期数;
        首现之前与末现之后也计入 (以出现位置计算间隔).

    Args:
        df: 清洗后 DataFrame.
        zone: 'front' 或 'back'.

    Returns:
        含 号码/当前遗漏/历史最大遗漏/平均遗漏 的 DataFrame.
    """
    if zone == "front":
        cols = ["前区1", "前区2", "前区3", "前区4", "前区5"]
        number_range = list(range(FRONT_MIN, FRONT_MAX + 1))
    else:
        cols = ["后区1", "后区2"]
        number_range = list(range(BACK_MIN, BACK_MAX + 1))

    total_issues = int(len(df))
    # 构建每号出现期序列表.
    appearances: Dict[int, List[int]] = {n: [] for n in number_range}
    for pos in range(total_issues):
        for col in cols:
            try:
                n = int(df.iloc[pos][col])
            except (ValueError, TypeError, KeyError):
                continue
            if n in appearances:
                appearances[n].append(pos)

    rows = []
    for n in number_range:
        pos_list = appearances[n]
        if not pos_list:
            current_missing = total_issues
            max_missing = total_issues
            avg_missing = float(total_issues)
        else:
            current_missing = total_issues - 1 - pos_list[-1]
            # 间隔: 首现前、相邻两次之间、末现后.
            gaps = [pos_list[0]]
            for i in range(1, len(pos_list)):
                gaps.append(pos_list[i] - pos_list[i - 1] - 1)
            gaps.append(total_issues - 1 - pos_list[-1])
            max_missing = max(gaps) if gaps else 0
            avg_missing = (sum(gaps) / len(gaps)) if gaps else 0.0
        rows.append({
            "号码": n,
            "当前遗漏": current_missing,
            "历史最大遗漏": max_missing,
            "平均遗漏": avg_missing,
        })
    return pd.DataFrame(rows)


def compute_sum_distribution(df: pd.DataFrame) -> Dict[str, Any]:
    """前区 5 号和值的经验分布与统计量.

    Returns:
        {"observed_mean", "observed_std", "theoretical_mean",
         "theoretical_variance", "theoretical_std", "histogram": {和值: 期数}}.
    """
    sums: List[int] = []
    for _, row in df.iterrows():
        try:
            vals = [int(row[c]) for c in ["前区1", "前区2", "前区3", "前区4", "前区5"]]
        except (ValueError, TypeError, KeyError):
            continue
        sums.append(sum(vals))
    arr = np.array(sums, dtype=float)
    observed_mean = float(arr.mean()) if arr.size else 0.0
    observed_std = float(arr.std(ddof=0)) if arr.size else 0.0
    histogram: Dict[int, int] = {}
    for s in sums:
        histogram[s] = histogram.get(s, 0) + 1
    theo = theoretical_sum_mean_variance_formula()
    return {
        "count": len(sums),
        "observed_mean": observed_mean,
        "observed_std": observed_std,
        "theoretical_mean": theo["mean"],
        "theoretical_variance": theo["variance"],
        "theoretical_std": theo["std"],
        "histogram": {int(k): int(v) for k, v in sorted(histogram.items())},
    }


def compute_odd_even_distribution(df: pd.DataFrame) -> Dict[str, Any]:
    """前区奇偶比分布 (奇数个数 0..5).

    Returns:
        {"observed": {奇数个数: 期数}, "observed_freq": {...},
         "theoretical": {奇数个数: 理论概率}}.
    """
    observed: Dict[int, int] = {k: 0 for k in range(0, FRONT_PICK + 1)}
    total = 0
    for _, row in df.iterrows():
        try:
            vals = [int(row[c]) for c in ["前区1", "前区2", "前区3", "前区4", "前区5"]]
        except (ValueError, TypeError, KeyError):
            continue
        odd_count = sum(1 for v in vals if v % 2 == 1)
        observed[odd_count] += 1
        total += 1
    observed_freq = {k: (v / total if total else 0.0) for k, v in observed.items()}
    return {
        "total": total,
        "observed": observed,
        "observed_freq": observed_freq,
        "theoretical": theoretical_odd_count_distribution(),
    }


def compute_big_small_distribution(df: pd.DataFrame) -> Dict[str, Any]:
    """前区大小比分布 (大号 >=18 的个数 0..5).

    Returns:
        {"observed": {大号个数: 期数}, "observed_freq": {...},
         "theoretical": {大号个数: 理论概率}}.
    """
    observed: Dict[int, int] = {k: 0 for k in range(0, FRONT_PICK + 1)}
    total = 0
    for _, row in df.iterrows():
        try:
            vals = [int(row[c]) for c in ["前区1", "前区2", "前区3", "前区4", "前区5"]]
        except (ValueError, TypeError, KeyError):
            continue
        big_count = sum(1 for v in vals if v >= BIG_SMALL_BOUNDARY)
        observed[big_count] += 1
        total += 1
    observed_freq = {k: (v / total if total else 0.0) for k, v in observed.items()}
    return {
        "total": total,
        "observed": observed,
        "observed_freq": observed_freq,
        "theoretical": theoretical_big_count_distribution(),
    }


def compute_zone_distribution(df: pd.DataFrame) -> Dict[str, Any]:
    """前区五区间 (01-07 / 08-14 / 15-21 / 22-28 / 29-35) 分布.

    统计口径: 统计每区在全部期数中的总命中号码个数与平均每期命中数.

    Returns:
        {"observed_total": {区间: 命中总数}, "observed_avg_per_issue": {...},
         "theoretical_avg_per_issue": {...}}.
    """
    zones = FRONT_ZONES
    observed_total: Dict[int, int] = {i: 0 for i in range(1, len(zones) + 1)}
    total = 0
    for _, row in df.iterrows():
        try:
            vals = [int(row[c]) for c in ["前区1", "前区2", "前区3", "前区4", "前区5"]]
        except (ValueError, TypeError, KeyError):
            continue
        total += 1
        for v in vals:
            for idx, (lo, hi) in enumerate(zones, start=1):
                if lo <= v <= hi:
                    observed_total[idx] += 1
                    break
    observed_avg = {i: (c / total if total else 0.0) for i, c in observed_total.items()}
    return {
        "total": total,
        "zones": {i: zones[i - 1] for i in range(1, len(zones) + 1)},
        "observed_total": observed_total,
        "observed_avg_per_issue": observed_avg,
        "theoretical_avg_per_issue": theoretical_zone_distribution(),
    }


def compute_consecutive_distribution(df: pd.DataFrame) -> Dict[str, Any]:
    """连号组数量分布.

    Returns:
        {"observed": {连号组数: 期数}, "observed_freq": {...},
         "theoretical": {连号组数: 理论概率}}.
    """
    observed: Dict[int, int] = {k: 0 for k in range(0, FRONT_PICK)}
    total = 0
    for _, row in df.iterrows():
        try:
            vals = sorted(int(row[c]) for c in ["前区1", "前区2", "前区3", "前区4", "前区5"])
        except (ValueError, TypeError, KeyError):
            continue
        g = count_consecutive_groups(vals)
        observed[g] = observed.get(g, 0) + 1
        total += 1
    observed_freq = {k: (v / total if total else 0.0) for k, v in observed.items()}
    return {
        "total": total,
        "observed": observed,
        "observed_freq": observed_freq,
        "theoretical": theoretical_consecutive_group_distribution(),
    }


def compute_repeat_distribution(df: pd.DataFrame) -> Dict[str, Any]:
    """相邻两期前区重号个数分布.

    Returns:
        {"observed": {重号数: 相邻期对数}, "observed_freq": {...},
         "theoretical": {重号数: 理论概率}, "expected_repeat": 期望重号数}.
    """
    observed: Dict[int, int] = {k: 0 for k in range(0, FRONT_PICK + 1)}
    prev: Optional[set] = None
    total = 0
    for _, row in df.iterrows():
        try:
            cur = {int(row[c]) for c in ["前区1", "前区2", "前区3", "前区4", "前区5"]}
        except (ValueError, TypeError, KeyError):
            prev = None
            continue
        if prev is not None:
            overlap = len(cur & prev)
            observed[overlap] = observed.get(overlap, 0) + 1
            total += 1
        prev = cur
    observed_freq = {k: (v / total if total else 0.0) for k, v in observed.items()}
    return {
        "total_pairs": total,
        "observed": observed,
        "observed_freq": observed_freq,
        "theoretical": theoretical_repeat_distribution(),
        "expected_repeat": theoretical_repeat_expectation(),
    }


def descriptive_statistics(df: pd.DataFrame, top_n: int = 5) -> Dict[str, Any]:
    """汇总全部描述性统计指标.

    Args:
        df: 清洗后 DataFrame.
        top_n: 冷热号 Top-N.

    Returns:
        含全部指标的嵌套字典.
    """
    freq_front = compute_frequency(df, "front")
    freq_back = compute_frequency(df, "back")
    return {
        "total_issues": int(len(df)),
        "frequency_front": freq_front.to_dict(orient="records"),
        "frequency_back": freq_back.to_dict(orient="records"),
        "hot_cold_front": compute_hot_cold(df, "front", top_n),
        "hot_cold_back": compute_hot_cold(df, "back", top_n),
        "missing_front": compute_missing_values(df, "front").to_dict(orient="records"),
        "missing_back": compute_missing_values(df, "back").to_dict(orient="records"),
        "sum_distribution": compute_sum_distribution(df),
        "odd_even": compute_odd_even_distribution(df),
        "big_small": compute_big_small_distribution(df),
        "zone": compute_zone_distribution(df),
        "consecutive": compute_consecutive_distribution(df),
        "repeat": compute_repeat_distribution(df),
    }


# --------------------------------------------------------------------------- #
# 8. 随机性检验
# --------------------------------------------------------------------------- #
def chi_square_uniform_test(observed_counts: np.ndarray,
                            expected_counts: np.ndarray) -> Dict[str, Any]:
    """卡方拟合优度检验 (纯函数).

    统计量 chi2 = sum((O_i - E_i)^2 / E_i), 自由度 df = k - 1.

    Args:
        observed_counts: 各号码观测频次.
        expected_counts: 各号码理论期望频次 (同上形状).

    Returns:
        {"chi2", "df", "p_value", "alpha", "reject_null", "conclusion_code"}.
    """
    obs = np.asarray(observed_counts, dtype=float)
    exp = np.asarray(expected_counts, dtype=float)
    if obs.shape != exp.shape:
        raise ValueError("观测频次与期望频次形状不一致")
    if np.any(exp <= 0):
        raise ValueError("理论期望频次必须为正")
    chi2 = float(np.sum((obs - exp) ** 2 / exp))
    df = int(obs.size - 1)
    p_value = float(1.0 - stats.chi2.cdf(chi2, df)) if df > 0 else 1.0
    reject_null = bool(p_value < DEFAULT_ALPHA)
    return {
        "chi2": chi2,
        "df": df,
        "p_value": p_value,
        "alpha": DEFAULT_ALPHA,
        "reject_null": reject_null,
        "conclusion_code": "REJECT_UNIFORM" if reject_null else "FAIL_TO_REJECT_UNIFORM",
    }


def per_number_binomial_test(observed_counts: np.ndarray,
                             trials: int,
                             p_hit: float,
                             method: str = "fdr") -> Dict[str, Any]:
    """单号码二项检验 + 多重比较校正.

    对每个号码做双边二项检验 H0: 命中概率 = p_hit (每期该号被抽中的概率).
    同时用 Bonferroni 与 Benjamini-Hochberg FDR 两种方式校正.

    Args:
        observed_counts: 各号码观测命中次数.
        trials: 总期数.
        p_hit: 单号码每期被抽中的概率 (前区 5/35, 后区 2/12).
        method: 返回主校正方法标签, 'fdr' 或 'bonferroni'.

    Returns:
        含逐号 p 值、校正阈值/校正 p 值, 与显著号码列表的结果字典.
    """
    obs = np.asarray(observed_counts, dtype=float)
    k = int(obs.size)
    p_values: List[float] = []
    for o in obs:
        # 双边二项检验.
        p = stats.binomtest(int(o), trials, p_hit, alternative="two-sided").pvalue
        p_values.append(float(p))
    p_arr = np.array(p_values, dtype=float)

    # Bonferroni.
    bonf_alpha = DEFAULT_ALPHA / k if k > 0 else DEFAULT_ALPHA
    bonf_reject = p_arr < bonf_alpha

    # Benjamini-Hochberg FDR.
    order = np.argsort(p_arr)
    ranked = p_arr[order]
    m = k
    bh_critical = (np.arange(1, m + 1) / m) * DEFAULT_ALPHA
    below = ranked <= bh_critical
    if below.any():
        max_rank = np.max(np.where(below)[0])
        bh_reject_sorted = np.zeros(m, dtype=bool)
        bh_reject_sorted[: max_rank + 1] = True
    else:
        bh_reject_sorted = np.zeros(m, dtype=bool)
    bh_reject = np.zeros(m, dtype=bool)
    bh_reject[order] = bh_reject_sorted
    # 校正后 p 值 (BH adjusted) = min over tail of (m/rank * p).
    adjusted = np.empty(m, dtype=float)
    adjusted_sorted = np.minimum.accumulate((ranked * m / np.arange(1, m + 1))[::-1])[::-1]
    adjusted_sorted = np.clip(adjusted_sorted, 0.0, 1.0)
    adjusted[order] = adjusted_sorted

    primary = bh_reject if method == "fdr" else bonf_reject
    return {
        "k": k,
        "trials": trials,
        "p_hit": p_hit,
        "alpha": DEFAULT_ALPHA,
        "raw_p_values": p_values,
        "bonferroni_alpha": bonf_alpha,
        "bonferroni_reject": bonf_reject.tolist(),
        "bh_adjusted_p_values": adjusted.tolist(),
        "fdr_reject": bh_reject.tolist(),
        "significant_indices": [int(i) for i in np.where(primary)[0]],
        "method": method,
    }


def _extract_counts(df: pd.DataFrame) -> Tuple[np.ndarray, np.ndarray]:
    """提取前区/后区各号码出现次数 (纯函数).

    统计口径: 遍历全部有效期, 前区 35 个号 / 后区 12 个号逐号计数.

    Args:
        df: 清洗后 DataFrame.

    Returns:
        (前区计数数组长度 35, 后区计数数组长度 12), 下标 = 号码 - 最小值.
    """
    front_counts = np.zeros(FRONT_RANGE_SIZE, dtype=float)
    back_counts = np.zeros(BACK_RANGE_SIZE, dtype=float)
    for _, row in df.iterrows():
        try:
            for c in ["前区1", "前区2", "前区3", "前区4", "前区5"]:
                front_counts[int(row[c]) - FRONT_MIN] += 1
            for c in ["后区1", "后区2"]:
                back_counts[int(row[c]) - BACK_MIN] += 1
        except (ValueError, TypeError, KeyError):
            continue
    return front_counts, back_counts


def monte_carlo_randomness(df: pd.DataFrame,
                           trials: int = DEFAULT_MC_TRIALS,
                           seed: int = DEFAULT_SEED) -> Dict[str, Any]:
    """蒙特卡洛模拟随机性检验 (向量化实现).

    统计口径:
      - 模拟 `trials` 期独立均匀随机开奖 (前区 35 选 5, 后区 12 选 2);
      - 以历史期数 T 为块长, 将模拟序列切分为 m = trials // T 块
        (若 trials < T 则退化为单块, 并在结果 block_size_note 中注明);
      - 对每块分别计算: 前区卡方统计量 (df=34)、后区卡方统计量 (df=11)、
        前区最大遗漏值 (35 个号码"历史最大遗漏"的最大值, 口径与
        compute_missing_values 一致: 含首现前/末现后间隔);
      - 经验 p 值定义 (Phipson & Smyth, 2010):
            p_emp = (1 + #{块统计量 >= 历史统计量}) / (m + 1)
        该定义保证 p_emp > 0, 且在原假设成立时 p_emp 近似服从均匀分布.

    Args:
        df: 清洗后 DataFrame.
        trials: 模拟总期数 (默认 100000).
        seed: 随机种子.

    Returns:
        含经验分布、经验 p 值、最大遗漏对比的结果字典.
    """
    total_issues = int(len(df))
    if total_issues <= 0:
        raise ValueError("数据为空, 无法进行蒙特卡洛检验")
    rng = np.random.default_rng(seed)

    # --- 历史卡方统计量与历史最大遗漏 ---
    front_counts, back_counts = _extract_counts(df)
    exp_front = total_issues * FRONT_PICK / FRONT_RANGE_SIZE
    exp_back = total_issues * BACK_PICK / BACK_RANGE_SIZE
    hist_front_chi2 = float(np.sum((front_counts - exp_front) ** 2 / exp_front))
    hist_back_chi2 = float(np.sum((back_counts - exp_back) ** 2 / exp_back))
    missing_df = compute_missing_values(df, "front")
    hist_max_missing = int(missing_df["历史最大遗漏"].max()) if len(missing_df) else 0

    # --- 向量化模拟 trials 期独立开奖 ---
    # argpartition 取每行 k 个最小随机键 => 不放回均匀抽取 k 个不同号码 (0 基)。
    n_use = int(max(trials, 1))
    front_idx = np.argpartition(
        rng.random((n_use, FRONT_RANGE_SIZE)), FRONT_PICK - 1, axis=1
    )[:, :FRONT_PICK]
    back_idx = np.argpartition(
        rng.random((n_use, BACK_RANGE_SIZE)), BACK_PICK - 1, axis=1
    )[:, :BACK_PICK]

    # --- 分块计算每块的卡方统计量与最大遗漏 ---
    if n_use >= total_issues:
        block_size = total_issues
        n_blocks = n_use // block_size
    else:
        block_size = n_use
        n_blocks = 1

    front_chi2_samples = np.empty(n_blocks, dtype=float)
    back_chi2_samples = np.empty(n_blocks, dtype=float)
    front_max_missing_samples = np.empty(n_blocks, dtype=float)
    row_index = np.arange(block_size, dtype=np.int64)[:, None]

    for b in range(n_blocks):
        s = b * block_size
        e = s + block_size
        blk_front = front_idx[s:e]
        blk_back = back_idx[s:e]

        fc = np.bincount(blk_front.ravel(), minlength=FRONT_RANGE_SIZE).astype(float)
        bc = np.bincount(blk_back.ravel(), minlength=BACK_RANGE_SIZE).astype(float)
        front_chi2_samples[b] = float(np.sum((fc - exp_front) ** 2 / exp_front))
        back_chi2_samples[b] = float(np.sum((bc - exp_back) ** 2 / exp_back))

        # 块内最大遗漏: 前向填充"最近出现期号", gap = i - last_seen, 取最大.
        occ = np.zeros((block_size, FRONT_RANGE_SIZE), dtype=bool)
        occ[row_index, blk_front] = True
        seen = np.full((block_size, FRONT_RANGE_SIZE), -1, dtype=np.int64)
        occ_rows, occ_cols = np.nonzero(occ)
        seen[occ_rows, occ_cols] = occ_rows
        last_seen = np.maximum.accumulate(seen, axis=0)
        gaps = np.arange(block_size, dtype=np.int64)[:, None] - last_seen
        front_max_missing_samples[b] = int(gaps.max())

    # --- 经验 p 值 (Phipson & Smyth 校正形式) ---
    emp_p_front = float((1 + int(np.sum(front_chi2_samples >= hist_front_chi2)))
                        / (n_blocks + 1))
    emp_p_back = float((1 + int(np.sum(back_chi2_samples >= hist_back_chi2)))
                       / (n_blocks + 1))
    missing_quantile = float(np.mean(front_max_missing_samples <= hist_max_missing))
    missing_exceed_ratio = float(np.mean(front_max_missing_samples >= hist_max_missing))

    def describe(samples: np.ndarray) -> Dict[str, float]:
        return {
            "mean": float(np.mean(samples)),
            "std": float(np.std(samples)),
            "p50": float(np.percentile(samples, 50)),
            "p90": float(np.percentile(samples, 90)),
            "p95": float(np.percentile(samples, 95)),
            "p99": float(np.percentile(samples, 99)),
            "max": float(np.max(samples)),
        }

    return {
        "trials": n_use,
        "seed": seed,
        "issues_simulated": n_use,
        "block_size": block_size,
        "blocks": n_blocks,
        "block_size_note": (
            "块长与历史期数一致" if block_size == total_issues
            else f"模拟期数少于历史期数, 块长降为 {n_use} 期"
        ),
        "empirical_p_definition": "p_emp = (1 + #{块统计量 >= 历史统计量}) / (块数 + 1)",
        "historical": {
            "front_chi2": hist_front_chi2,
            "back_chi2": hist_back_chi2,
            "front_max_missing": hist_max_missing,
        },
        "front_chi2_distribution": describe(front_chi2_samples),
        "back_chi2_distribution": describe(back_chi2_samples),
        "front_max_missing_distribution": describe(front_max_missing_samples),
        "empirical_p_value_front": emp_p_front,
        "empirical_p_value_back": emp_p_back,
        "max_missing_quantile": missing_quantile,
        "max_missing_exceed_ratio": missing_exceed_ratio,
    }


def randomness_tests(df: pd.DataFrame,
                     mc_trials: int = DEFAULT_MC_TRIALS,
                     seed: int = DEFAULT_SEED) -> Dict[str, Any]:
    """汇总随机性检验 (卡方 + 多重比较校正 + 蒙特卡洛).

    Args:
        df: 清洗后 DataFrame.
        mc_trials: 蒙特卡洛期数.
        seed: 随机种子.

    Returns:
        结果字典, 含结论与局限说明所需的一切中间量.
    """
    total_issues = int(len(df))

    front_counts, back_counts = _extract_counts(df)

    exp_front = np.full(FRONT_RANGE_SIZE, total_issues * FRONT_PICK / FRONT_RANGE_SIZE)
    exp_back = np.full(BACK_RANGE_SIZE, total_issues * BACK_PICK / BACK_RANGE_SIZE)

    chi2_front = chi_square_uniform_test(front_counts, exp_front)
    chi2_back = chi_square_uniform_test(back_counts, exp_back)

    binom_front = per_number_binomial_test(
        front_counts, total_issues, FRONT_PICK / FRONT_RANGE_SIZE, method="fdr")
    binom_back = per_number_binomial_test(
        back_counts, total_issues, BACK_PICK / BACK_RANGE_SIZE, method="fdr")

    mc = monte_carlo_randomness(df, trials=mc_trials, seed=seed)

    return {
        "total_issues": total_issues,
        "chi2_front": chi2_front,
        "chi2_back": chi2_back,
        "binomial_front": binom_front,
        "binomial_back": binom_back,
        "monte_carlo": mc,
        "alpha": DEFAULT_ALPHA,
        "limitation_note": (
            "不拒绝原假设 (未检出显著偏离) 并不等于证明开奖是均匀随机的; "
            "只能说明在当前样本量下没有检出显著偏离, 结论受样本量限制, "
            "且不能预测未来任何一期结果。"
        ),
    }


# --------------------------------------------------------------------------- #
# 9. 参考号码生成
# --------------------------------------------------------------------------- #
def compute_sum_high_freq_interval(df: pd.DataFrame) -> Tuple[int, int]:
    """给出历史高频和值区间 (以均值为中心, 覆盖约 68% 样本作为主区间).

    Returns:
        (low, high) 和值主区间 (闭区间).
    """
    stat = compute_sum_distribution(df)
    total = stat["count"]
    if total == 0:
        return (int(stat["theoretical_mean"] - stat["theoretical_std"]),
                int(stat["theoretical_mean"] + stat["theoretical_std"]))
    mean = stat["observed_mean"]
    std = stat["observed_std"]
    return (int(round(mean - std)), int(round(mean + std)))


def generate_hot_weighted(df: pd.DataFrame, count: int,
                          seed: int = DEFAULT_SEED) -> List[Dict[str, Any]]:
    """策略一: 热号加权生成.

    以前区/后区号码的历史出现频率 (相对理论期望的比值) 作为抽样权重,
    结合和值区间约束, 生成若干组参考号码.

    Args:
        df: 清洗后 DataFrame.
        count: 生成组数.
        seed: 随机种子.

    Returns:
        每组的 {"front", "back", "basis"} 列表.
    """
    rng = random.Random(seed)
    freq_front = compute_frequency(df, "front")
    freq_back = compute_frequency(df, "back")
    weights_front = freq_front["出现次数"].astype(float).tolist()
    numbers_front = freq_front["号码"].astype(int).tolist()
    weights_back = freq_back["出现次数"].astype(float).tolist()
    numbers_back = freq_back["号码"].astype(int).tolist()
    low, high = compute_sum_high_freq_interval(df)

    results: List[Dict[str, Any]] = []
    attempts = 0
    while len(results) < count and attempts < count * 500:
        attempts += 1
        front = sorted(rng.choices(numbers_front, weights=weights_front, k=FRONT_PICK))
        if len(set(front)) != FRONT_PICK:
            continue
        s = sum(front)
        if not (low <= s <= high):
            continue
        back = sorted(rng.choices(numbers_back, weights=weights_back, k=BACK_PICK))
        if len(set(back)) != BACK_PICK:
            continue
        odd = sum(1 for x in front if x % 2 == 1)
        big = sum(1 for x in front if x >= BIG_SMALL_BOUNDARY)
        results.append({
            "front": front,
            "back": back,
            "sum": s,
            "odd_even": f"{odd}:{FRONT_PICK - odd}",
            "big_small": f"{big}:{FRONT_PICK - big}",
            "basis": [
                "策略=hot_weighted: 以历史出现频率作为抽样权重 (热号权重更高)",
                f"和值约束: 命中历史高频和值区间 [{low}, {high}] (均值±1标准差)",
                f"奇偶比 {odd}:{FRONT_PICK - odd}, 大小比 {big}:{FRONT_PICK - big}",
                "重要: 统计权重仅改变生成的号码形态分布, 不改变任何单个组合的中奖概率",
            ],
        })
    return results


def generate_balanced_profile(df: pd.DataFrame, count: int,
                              seed: int = DEFAULT_SEED) -> List[Dict[str, Any]]:
    """策略二: 形态匹配生成.

    对齐历史高频形态: 和值落入主区间、奇偶比接近 3:2、大小比接近 3:2,
    并尽量覆盖多个区间; 号码在满足形态前提下均匀随机选取.

    Args:
        df: 清洗后 DataFrame.
        count: 生成组数.
        seed: 随机种子.

    Returns:
        每组的 {"front", "back", "basis"} 列表.
    """
    rng = random.Random(seed + 999)
    low, high = compute_sum_high_freq_interval(df)
    odd_even_stat = compute_odd_even_distribution(df)
    # 高频奇偶形态 (按理论概率排序, 取概率最高的奇数个数).
    best_odd = max(odd_even_stat["theoretical"].items(), key=lambda kv: kv[1])[0]
    best_big = max(theoretical_big_count_distribution().items(), key=lambda kv: kv[1])[0]

    odd_pool = [x for x in range(FRONT_MIN, FRONT_MAX + 1) if x % 2 == 1]
    even_pool = [x for x in range(FRONT_MIN, FRONT_MAX + 1) if x % 2 == 0]
    big_pool = [x for x in range(FRONT_MIN, FRONT_MAX + 1) if x >= BIG_SMALL_BOUNDARY]
    small_pool = [x for x in range(FRONT_MIN, FRONT_MAX + 1) if x < BIG_SMALL_BOUNDARY]

    results: List[Dict[str, Any]] = []
    attempts = 0
    while len(results) < count and attempts < count * 2000:
        attempts += 1
        front_set: set = set()
        # 按目标奇偶 + 大小联合约束抽样.
        target_odd = best_odd
        target_big = best_big
        # 从奇数/偶数池中按目标个数抽.
        chosen_odd = rng.sample(odd_pool, target_odd)
        chosen_even = rng.sample(even_pool, FRONT_PICK - target_odd)
        front_set = set(chosen_odd) | set(chosen_even)
        if len(front_set) != FRONT_PICK:
            continue
        front = sorted(front_set)
        s = sum(front)
        if not (low <= s <= high):
            continue
        big_cnt = sum(1 for x in front if x >= BIG_SMALL_BOUNDARY)
        # 形态匹配允许 ±1 偏差.
        if abs(big_cnt - target_big) > 1:
            continue
        zones_covered = len({idx for x in front
                             for idx, (lo, hi) in enumerate(FRONT_ZONES, start=1)
                             if lo <= x <= hi})
        back = sorted(rng.sample(range(BACK_MIN, BACK_MAX + 1), BACK_PICK))
        odd_cnt = sum(1 for x in front if x % 2 == 1)
        results.append({
            "front": front,
            "back": back,
            "sum": s,
            "odd_even": f"{odd_cnt}:{FRONT_PICK - odd_cnt}",
            "big_small": f"{big_cnt}:{FRONT_PICK - big_cnt}",
            "zones_covered": zones_covered,
            "basis": [
                "策略=balanced_profile: 对齐历史高频形态",
                f"奇偶比 {odd_cnt}:{FRONT_PICK - odd_cnt} (理论高频形态)",
                f"大小比 {big_cnt}:{FRONT_PICK - big_cnt} (理论高频形态)",
                f"和值 {s} 落在历史主区间 [{low}, {high}]",
                f"覆盖区间数 {zones_covered}/5",
                "重要: 形态匹配不改变任何单个组合的中奖概率 (恒为 1/21,425,712)",
            ],
        })
    return results


def generate_reference_numbers(df: pd.DataFrame,
                               count: int = DEFAULT_GENERATE_COUNT,
                               strategy: str = "hot_weighted",
                               seed: int = DEFAULT_SEED) -> Dict[str, Any]:
    """生成参考号码 (支持两种策略并对比).

    Args:
        df: 清洗后 DataFrame.
        count: 生成组数.
        strategy: 'hot_weighted' | 'balanced_profile' | 'both'.
        seed: 随机种子.

    Returns:
        含各策略结果、对照说明与免责声明的字典.
    """
    result: Dict[str, Any] = {
        "strategy": strategy,
        "count": count,
        "disclaimer": (
            "以下号码仅供统计形态参考, 其统计依据【不改变】任何单个组合的中奖概率; "
            "每个 5+2 组合的中奖概率恒为 1/21,425,712。生成结果不具备预测能力, "
            "不得作为投注依据。敬请理性购彩。"
        ),
    }
    if strategy in ("hot_weighted", "both"):
        result["hot_weighted"] = generate_hot_weighted(df, count, seed=seed)
    if strategy in ("balanced_profile", "both"):
        result["balanced_profile"] = generate_balanced_profile(df, count, seed=seed)
    if strategy == "both":
        result["comparison"] = (
            "hot_weighted 侧重历史高频号码; balanced_profile 侧重形态 (奇偶/大小/和值/区间) "
            "匹配。两者都是'历史形态的采样', 理论上任何组合中奖概率完全相同, 二者无优劣之分。"
        )
    return result


# --------------------------------------------------------------------------- #
# 10. 输出格式化
# --------------------------------------------------------------------------- #
def _fmt_prob(p: float) -> str:
    """概率格式化: 同时给出小数与分数近似表示 (1/N)."""
    if p <= 0:
        return "0"
    if p >= 1e-4:
        return f"{p:.10f} (约 1/{1 / p:,.2f})"
    return f"{p:.15g} (约 1/{1 / p:,.0f})"


def render_clean_report(report: Dict[str, Any], clean_df: pd.DataFrame,
                        fmt: str = "text") -> str:
    """渲染清洗报告."""
    if fmt == "json":
        return json.dumps({
            "report": report,
            "cleaned_rows": clean_df.to_dict(orient="records"),
        }, ensure_ascii=False, indent=2)
    lines: List[str] = []
    lines.append("=" * 72)
    lines.append("数据清洗与校验报告")
    lines.append("=" * 72)
    lines.append(f"数据来源        : {report.get('source', 'N/A')}")
    lines.append(f"原始记录数      : {report['original_rows']}")
    lines.append(f"有效记录数      : {report['valid_rows']}")
    lines.append(f"丢弃记录数      : {report['dropped_rows']}")
    lines.append(f"warning 条数    : {report['warning_count']}")
    lines.append(f"error   条数    : {report['error_count']}")
    lines.append("-" * 72)
    lines.append("各类问题计数 (规则码 -> 条数):")
    if report["code_counts"]:
        for code, cnt in sorted(report["code_counts"].items()):
            desc = CLEAN_RULE_DESCRIPTIONS.get(code, "")
            lines.append(f"  - {code:<22} {cnt:>5} 条   {desc}")
    else:
        lines.append("  (无)")
    lines.append("-" * 72)
    if report["issues"]:
        lines.append("问题明细 (最多展示前 30 条):")
        for item in report["issues"][:30]:
            lines.append(f"  [{item['级别']:<7}] 期号={item['期号'] or '-':<12} "
                         f"规则={item['规则码']:<20} {item['明细']}")
        if len(report["issues"]) > 30:
            lines.append(f"  ... 其余 {len(report['issues']) - 30} 条已省略 (可加 --format json 查看全部)")
    else:
        lines.append("问题明细: 无")
    lines.append("-" * 72)
    lines.append("清洗后数据预览 (前 5 行):")
    lines.append(clean_df.head(5).to_string(index=False) if len(clean_df) else "(空)")
    lines.append("=" * 72)
    return "\n".join(lines)


def render_probability(fmt: str = "text",
                       prize_amounts: Optional[Dict[str, float]] = None) -> str:
    """渲染概率推理结果."""
    probs = prize_probabilities()
    ev = expected_value(prize_amounts)
    checks = self_consistency_check()

    if fmt == "json":
        return json.dumps({
            "combination_counts": {
                "front": count_front_combinations(),
                "back": count_back_combinations(),
                "total": count_total_combinations(),
            },
            "prizes": {name: {
                "probability": probs[name]["probability"],
                "one_in": probs[name]["one_in"],
                "count": probs[name]["count"],
                "cases": probs[name]["cases"],
            } for name in PRIZE_ORDER},
            "any_prize_probability": any_prize_probability(),
            "expected_value": {
                "bet_cost": ev["bet_cost"],
                "gross_return_per_bet": ev["gross_return_per_bet"],
                "expected_value_per_bet": ev["expected_value_per_bet"],
                "expected_return_per_yuan": ev["expected_return_per_yuan"],
                "return_rate": ev["return_rate"],
                "expected_loss_per_bet": ev["expected_loss_per_bet"],
                "prize_amounts": ev["prize_amounts"],
                "official_return_rate_reference": ev["official_return_rate_reference"],
            },
            "self_consistency": checks,
        }, ensure_ascii=False, indent=2)

    lines: List[str] = []
    lines.append("=" * 72)
    lines.append("概率推理: 组合总数 / 各奖级中奖概率 / 期望值")
    lines.append("=" * 72)
    lines.append("【组合总数推导】")
    lines.append(f"  前区组合数 C(35,5) = {count_front_combinations():,}")
    lines.append(f"  后区组合数 C(12,2) = {count_back_combinations():,}")
    lines.append(f"  总组合数 = {count_front_combinations():,} x "
                 f"{count_back_combinations():,} = {count_total_combinations():,}")
    lines.append("-" * 72)
    lines.append("【各奖级理论中奖概率】(超几何分布精确计算)")
    lines.append(f"  {'奖级':<6} {'命中要求(前,后)':<20} {'组合数':>12}  概率 / 约 1/N")
    for name in PRIZE_ORDER:
        item = probs[name]
        req = "+".join(f"前{a}后{b}" for a, b in item["cases"])
        lines.append(f"  {name:<6} {req:<20} {item['count']:>12,}  {_fmt_prob(item['probability'])}")
    lines.append("-" * 72)
    lines.append(f"至少中任一奖级概率 = {_fmt_prob(any_prize_probability())}")
    lines.append("-" * 72)
    lines.append("【数学期望值与返奖率】(奖金为示例值, 非官方承诺)")
    lines.append(f"  {'奖级':<6} {'单注奖金(元)':>14}  期望贡献(元)")
    for name in PRIZE_ORDER:
        pp = ev["per_prize"][name]
        lines.append(f"  {name:<6} {pp['amount']:>14,.0f}  {pp['expectation_contribution']:.10f}")
    lines.append("-" * 72)
    lines.append(f"  单注投注成本                : {ev['bet_cost']:.2f} 元")
    lines.append(f"  每注期望毛回报              : {ev['gross_return_per_bet']:.6f} 元")
    lines.append(f"  每注数学期望值 (净)         : {ev['expected_value_per_bet']:.6f} 元")
    lines.append(f"  每 1 元期望回报             : {ev['expected_return_per_yuan']:.6f} 元")
    lines.append(f"  返奖率 (期望)               : {ev['return_rate'] * 100:.2f}%")
    lines.append(f"  每注期望亏损                : {ev['expected_loss_per_bet']:.6f} 元")
    lines.append(f"  官方规定返奖率参考          : {ev['official_return_rate_reference'] * 100:.0f}%")
    lines.append(f"  示例奖金字典 vs 官方返奖率差 : {ev['return_rate_vs_official'] * 100:+.2f} 个百分点")
    lines.append("-" * 72)
    lines.append("【自洽性校验 (精确计数法)】")
    lines.append(f"  总组合数                    : {checks['total_combinations']:,}")
    lines.append(f"  枚举全部(a,b)组合数之和     : {checks['enumerated_case_sum']:,} "
                 f"(与总组合数一致: {checks['enumerated_equals_total']})")
    lines.append(f"  中奖组合数 / 未中奖组合数   : {checks['win_cases']:,} / {checks['lose_cases']:,} "
                 f"(和=总组合: {checks['win_plus_lose_equals_total']})")
    lines.append(f"  计数法与公式法概率差        : {checks['p_win_abs_diff']:.3e}")
    lines.append(f"  中奖概率 + 未中奖概率       : {checks['p_win_plus_p_lose']:.15f}")
    lines.append(f"  九等奖子情形计数/概率一致   : {checks['ninth_count_by_cases'] == checks['ninth_count_by_table']} / "
                 f"diff={checks['ninth_prob_abs_diff']:.3e}")
    lines.append(f"  自洽性断言                  : {'PASSED' if checks['passed'] else 'FAILED'}")
    lines.append("=" * 72)
    lines.append("提示: 每个 5+2 组合的中奖概率恒为 1/21,425,712, 与投注方式、"
                 "金额、历史数据无关。理性购彩, 量力而行, 未成年人不得购彩。")
    lines.append("=" * 72)
    return "\n".join(lines)


def render_describe(stats: Dict[str, Any], fmt: str = "text") -> str:
    """渲染描述性统计结果."""
    if fmt == "json":
        return json.dumps(stats, ensure_ascii=False, indent=2)

    lines: List[str] = []
    lines.append("=" * 72)
    lines.append("描述性统计报告")
    lines.append("=" * 72)
    lines.append(f"有效期数: {stats['total_issues']}")
    lines.append("-" * 72)
    lines.append("【1. 号码频次与频率】(前区 35 号)")
    lines.append(f"  {'号码':>4} {'出现次数':>8} {'频率':>10} {'理论期望频次':>12}")
    for rec in stats["frequency_front"]:
        lines.append(f"  {rec['号码']:>4} {rec['出现次数']:>8} {rec['频率']:>10.4f} "
                     f"{rec['理论期望频次']:>12.2f}")
    lines.append("  (频率 = 出现次数 / 总期数; 前区 35 个频率之和 = 5)")
    lines.append("-" * 72)
    lines.append("【1. 号码频次与频率】(后区 12 号)")
    lines.append(f"  {'号码':>4} {'出现次数':>8} {'频率':>10} {'理论期望频次':>12}")
    for rec in stats["frequency_back"]:
        lines.append(f"  {rec['号码']:>4} {rec['出现次数']:>8} {rec['频率']:>10.4f} "
                     f"{rec['理论期望频次']:>12.2f}")
    lines.append("  (频率 = 出现次数 / 总期数; 后区 12 个频率之和 = 2)")
    lines.append("-" * 72)
    lines.append("【2. 冷热号】")
    lines.append(f"  理论期望频次基线: 前区单号 {stats['hot_cold_front']['theoretical']:.2f} 次 / "
                 f"后区单号 {stats['hot_cold_back']['theoretical']:.2f} 次")
    lines.append("  前区热号 Top: " + ", ".join(
        f"{r['号码']}({r['出现次数']})" for r in stats["hot_cold_front"]["hot"]))
    lines.append("  前区冷号 Bottom: " + ", ".join(
        f"{r['号码']}({r['出现次数']})" for r in stats["hot_cold_front"]["cold"]))
    lines.append("  后区热号 Top: " + ", ".join(
        f"{r['号码']}({r['出现次数']})" for r in stats["hot_cold_back"]["hot"]))
    lines.append("  后区冷号 Bottom: " + ", ".join(
        f"{r['号码']}({r['出现次数']})" for r in stats["hot_cold_back"]["cold"]))
    lines.append("-" * 72)
    lines.append("【3. 遗漏值】(前区)")
    lines.append(f"  {'号码':>4} {'当前遗漏':>10} {'历史最大遗漏':>14} {'平均遗漏':>10}")
    for rec in stats["missing_front"]:
        lines.append(f"  {rec['号码']:>4} {rec['当前遗漏']:>10} "
                     f"{rec['历史最大遗漏']:>14} {rec['平均遗漏']:>10.2f}")
    lines.append("  (当前遗漏 = 距最近一次出现的期数; 历史最大遗漏含首现前与末现后间隔)")
    lines.append("-" * 72)
    lines.append("【4. 和值分布】(前区 5 号和值)")
    sd = stats["sum_distribution"]
    lines.append(f"  观测均值 {sd['observed_mean']:.4f} / 标准差 {sd['observed_std']:.4f}")
    lines.append(f"  理论均值 {sd['theoretical_mean']:.4f} / 理论标准差 {sd['theoretical_std']:.4f} "
                 f"(理论方差 {sd['theoretical_variance']:.4f})")
    lines.append("  和值直方图 (和值:期数):")
    hist_items = list(sd["histogram"].items())
    for i in range(0, len(hist_items), 8):
        chunk = hist_items[i:i + 8]
        lines.append("    " + "  ".join(f"{s}:{c}" for s, c in chunk))
    lines.append("-" * 72)
    lines.append("【5. 奇偶比分布】(前区奇数个数)")
    oe = stats["odd_even"]
    lines.append(f"  {'奇数个数':>8} {'奇:偶':>8} {'观测期数':>10} {'观测频率':>10} {'理论概率':>10}")
    for k in range(FRONT_PICK + 1):
        lines.append(f"  {k:>8} {k}:{FRONT_PICK - k:<6} {oe['observed'][k]:>10} "
                     f"{oe['observed_freq'][k]:>10.4f} {oe['theoretical'][k]:>10.4f}")
    lines.append("-" * 72)
    lines.append("【6. 大小比分布】(18 为界, >=18 为大号)")
    bs = stats["big_small"]
    lines.append(f"  {'大号个数':>8} {'大:小':>8} {'观测期数':>10} {'观测频率':>10} {'理论概率':>10}")
    for k in range(FRONT_PICK + 1):
        lines.append(f"  {k:>8} {k}:{FRONT_PICK - k:<6} {bs['observed'][k]:>10} "
                     f"{bs['observed_freq'][k]:>10.4f} {bs['theoretical'][k]:>10.4f}")
    lines.append("-" * 72)
    lines.append("【7. 区间分布】(01-07/08-14/15-21/22-28/29-35)")
    zc = stats["zone"]
    lines.append(f"  {'区间':>14} {'命中总数':>10} {'平均每期':>10} {'理论每期':>10}")
    for idx in range(1, 6):
        lo, hi = zc["zones"][idx]
        lines.append(f"  {f'{lo:02d}-{hi:02d}':>14} {zc['observed_total'][idx]:>10} "
                     f"{zc['observed_avg_per_issue'][idx]:>10.4f} "
                     f"{zc['theoretical_avg_per_issue'][idx]:>10.4f}")
    lines.append("-" * 72)
    lines.append("【8. 连号统计】(相邻号码差为 1 的极大连号组数量)")
    cs = stats["consecutive"]
    lines.append(f"  {'连号组数':>8} {'观测期数':>10} {'观测频率':>10} {'理论概率':>10}")
    for k in sorted(cs["observed"].keys()):
        lines.append(f"  {k:>8} {cs['observed'][k]:>10} {cs['observed_freq'][k]:>10.4f} "
                     f"{cs['theoretical'].get(k, 0.0):>10.4f}")
    lines.append("-" * 72)
    lines.append("【9. 重号统计】(相邻两期前区重复号码个数)")
    rp = stats["repeat"]
    lines.append(f"  {'重号个数':>8} {'观测期对':>10} {'观测频率':>10} {'理论概率':>10}")
    for k in sorted(rp["observed"].keys()):
        lines.append(f"  {k:>8} {rp['observed'][k]:>10} {rp['observed_freq'][k]:>10.4f} "
                     f"{rp['theoretical'].get(k, 0.0):>10.4f}")
    lines.append(f"  理论期望重号个数: {rp['expected_repeat']:.4f} ( = 5 x 5 / 35 )")
    lines.append("=" * 72)
    lines.append("提示: 以上统计仅描述历史样本, 不代表未来走势。独立随机事件无可预测性。")
    lines.append("=" * 72)
    return "\n".join(lines)


def render_randomness(res: Dict[str, Any], fmt: str = "text") -> str:
    """渲染随机性检验结果."""
    if fmt == "json":
        return json.dumps(res, ensure_ascii=False, indent=2)

    lines: List[str] = []
    lines.append("=" * 72)
    lines.append("随机性检验报告")
    lines.append("=" * 72)
    lines.append(f"有效期数: {res['total_issues']}    显著性水平 alpha = {res['alpha']}")
    lines.append("-" * 72)
    lines.append("【1. 卡方拟合优度检验】")
    lines.append("  注: 每期前区 5 个号互不重复, 号码计数间存在负相关,")
    lines.append("      χ²(k-1) 仅是近似参照 (其均值偏大); 精确参照以第 3 节")
    lines.append("      蒙特卡洛经验分布为准。")
    for label, key in (
        ("前区(35 号)", "chi2_front"),
        ("后区(12 号)", "chi2_back"),
    ):
        t = res[key]
        conclusion = "拒绝均匀分布假设" if t["reject_null"] else "不拒绝均匀分布假设"
        lines.append(f"  {label}: chi2 = {t['chi2']:.4f}, df = {t['df']}, "
                     f"p = {t['p_value']:.6f} (渐近近似)")
        lines.append(f"       结论 (alpha={t['alpha']}): {conclusion}")
    lines.append("-" * 72)
    lines.append("【2. 单号码二项检验 + 多重比较校正】")
    lines.append("  说明: 同时检验 35 (前区) / 12 (后区) 个号码, 未校正的多次检验会使")
    lines.append("        第一类错误膨胀; 故必须做 Bonferroni 或 Benjamini-Hochberg FDR 校正。")
    for label, key, numbers in (
        ("前区", "binomial_front", list(range(FRONT_MIN, FRONT_MAX + 1))),
        ("后区", "binomial_back", list(range(BACK_MIN, BACK_MAX + 1))),
    ):
        b = res[key]
        lines.append(f"  {label}: 检验数 k={b['k']}, 单号命中概率 p_hit={b['p_hit']:.6f}")
        lines.append(f"        Bonferroni 校正阈值 alpha/k = {b['bonferroni_alpha']:.8f}, "
                     f"显著号码数 = {sum(b['bonferroni_reject'])}")
        lines.append(f"        FDR(BH) 校正显著号码数 = {len(b['significant_indices'])}")
        if b["significant_indices"]:
            sig = [numbers[i] for i in b["significant_indices"]]
            lines.append(f"        FDR 显著号码: {sig}")
        else:
            lines.append("        FDR 显著号码: 无 (校正后无单号显著偏离)")
        # 展示原始 p 值最小的 3 个号码.
        pairs = sorted(zip(numbers, b["raw_p_values"], b["bh_adjusted_p_values"]),
                       key=lambda x: x[1])[:3]
        lines.append("        原始 p 值最小的 3 个号码 (号码, 原始p, BH校正p):")
        for num, rp, ap in pairs:
            lines.append(f"          {num}: {rp:.6f} -> {ap:.6f}")
    lines.append("-" * 72)
    mc = res["monte_carlo"]
    lines.append(f"【3. 蒙特卡洛模拟】(模拟 {mc['trials']} 期独立开奖, "
                 f"分 {mc['blocks']} 块 x 每块 {mc['block_size']} 期, "
                 f"seed={mc['seed']}; {mc['block_size_note']})")
    lines.append(f"  经验 p 值定义: {mc['empirical_p_definition']}")
    lines.append(f"  历史前区 chi2 = {mc['historical']['front_chi2']:.4f} ; "
                 f"模拟经验 p 值 = {mc['empirical_p_value_front']:.6f}")
    lines.append(f"  历史后区 chi2 = {mc['historical']['back_chi2']:.4f} ; "
                 f"模拟经验 p 值 = {mc['empirical_p_value_back']:.6f}")
    lines.append("  模拟前区 chi2 经验分布: " + ", ".join(
        f"{k}={v:.2f}" for k, v in mc["front_chi2_distribution"].items()))
    lines.append("  模拟后区 chi2 经验分布: " + ", ".join(
        f"{k}={v:.2f}" for k, v in mc["back_chi2_distribution"].items()))
    lines.append(f"  历史前区最大遗漏 = {mc['historical']['front_max_missing']} ; "
                 f"模拟块最大遗漏 >= 历史值的比例 = {mc['max_missing_exceed_ratio']:.4f} "
                 f"(历史值在模拟分布中的分位 = {mc['max_missing_quantile']:.4f})")
    lines.append("  模拟最大遗漏经验分布: " + ", ".join(
        f"{k}={v:.2f}" for k, v in mc["front_max_missing_distribution"].items()))
    lines.append("-" * 72)
    lines.append("【结论与局限】")
    lines.append("  - 若 p 值 >= alpha, 结论为'不拒绝均匀随机假设', 即当前样本下")
    lines.append("    未检出显著偏离均匀分布的证据。")
    lines.append("  - 不拒绝原假设 != 证明开奖是均匀随机的; 只能说明在当前样本量下")
    lines.append("    没有检出显著偏离, 结论受样本量限制, 不代表未来走势。")
    lines.append("  - 无论如何, 每期开奖均为独立随机事件, 历史数据无法预测未来结果。")
    lines.append("=" * 72)
    return "\n".join(lines)


def render_generate(res: Dict[str, Any], fmt: str = "text") -> str:
    """渲染参考号码生成结果."""
    if fmt == "json":
        return json.dumps(res, ensure_ascii=False, indent=2)

    lines: List[str] = []
    lines.append("=" * 72)
    lines.append("参考号码生成")
    lines.append("=" * 72)
    lines.append("【重要声明】" + res["disclaimer"])
    lines.append("-" * 72)

    def render_group(strategy_name: str, groups: List[Dict[str, Any]]) -> None:
        lines.append(f"[策略] {strategy_name}")
        for i, g in enumerate(groups, start=1):
            front_str = " ".join(f"{x:02d}" for x in g["front"])
            back_str = " ".join(f"{x:02d}" for x in g["back"])
            lines.append(f"  第 {i} 组: 前区 [{front_str}]  后区 [{back_str}]")
            lines.append(f"          和值={g['sum']} 奇偶比={g['odd_even']} 大小比={g['big_small']}"
                         + (f" 覆盖区间={g['zones_covered']}/5" if "zones_covered" in g else ""))
            for b in g["basis"]:
                lines.append(f"          依据: {b}")
            lines.append("")

    if "hot_weighted" in res:
        render_group("hot_weighted (热号加权)", res["hot_weighted"])
    if "balanced_profile" in res:
        render_group("balanced_profile (形态匹配)", res["balanced_profile"])
    if "comparison" in res:
        lines.append("[策略对比] " + res["comparison"])
    lines.append("-" * 72)
    lines.append("再次强调: 上述号码不具备预测能力, 任何组合中奖概率均为 1/21,425,712。")
    lines.append("彩票是娱乐消费而非投资, 请量力而行, 未成年人不得购彩。")
    lines.append("=" * 72)
    return "\n".join(lines)


def render_report(df: pd.DataFrame, stats: Dict[str, Any],
                  rnd: Dict[str, Any], fmt: str = "text") -> str:
    """渲染综合报告 (描述性统计 + 随机性检验摘要 + 概率摘要)."""
    if fmt == "json":
        return json.dumps({
            "descriptive": stats,
            "randomness": rnd,
            "probability_summary": {
                "total_combinations": count_total_combinations(),
                "any_prize_probability": any_prize_probability(),
                "expected_value": expected_value(),
            },
        }, ensure_ascii=False, indent=2)

    lines: List[str] = []
    lines.append("#" * 72)
    lines.append("# 超级大乐透 历史数据分析 综合报告")
    lines.append("#" * 72)
    lines.append("")
    lines.append(render_describe(stats, fmt="text"))
    lines.append("")
    lines.append(render_randomness(rnd, fmt="text"))
    lines.append("")
    lines.append(render_probability(fmt="text"))
    lines.append("")
    lines.append("#" * 72)
    lines.append("# 理性购彩提示")
    lines.append("#  1. 彩票是娱乐消费, 不是投资, 请量力而行;")
    lines.append("#  2. 每期开奖为独立随机事件, 历史数据无法预测未来结果;")
    lines.append("#  3. 中奖概率与投注金额、方式、号码选择无关;")
    lines.append("#  4. 未成年人不得购买彩票;")
    lines.append("#  5. 每 1 元投注的长期期望回报显著小于 1 元, 请理性对待。")
    lines.append("#" * 72)
    return "\n".join(lines)


# --------------------------------------------------------------------------- #
# 11. CLI
# --------------------------------------------------------------------------- #
RATIONAL_PURCHASE_NOTICE = (
    "理性购彩提示: 彩票是娱乐消费而非投资; 每期开奖为独立随机事件, 任何统计分析都"
    "无法预测未来结果; 中奖概率与投注金额、方式、号码选择无关; 未成年人不得购彩; "
    "请量力而行, 切勿沉迷。"
)


def _resolve_input(args: argparse.Namespace) -> Tuple[pd.DataFrame, Dict[str, Any]]:
    """根据 CLI 参数解析数据来源并返回 (df, report)."""
    parse_issues: List[Dict[str, str]] = []
    if args.source == "csv" and getattr(args, "input", None):
        raw_df, parse_issues = read_csv_tolerant(args.input)
        report_source = f"csv:{args.input}"
    elif args.source == "json" and getattr(args, "input", None):
        with open(args.input, "r", encoding="utf-8-sig") as fh:
            payload = json.load(fh)
        if isinstance(payload, dict):
            payload = payload.get("data", payload.get("records", []))
        raw_df = pd.DataFrame(payload).astype(str)
        report_source = f"json:{args.input}"
    else:
        raw_df = build_sample_dataframe()
        report_source = "builtin_sample(simulated)"

    clean_df, report = clean_records(raw_df)
    if parse_issues:
        merge_parse_issues(report, parse_issues)
    report["source"] = report_source
    return clean_df, report


def cmd_clean(args: argparse.Namespace) -> int:
    """clean 子命令: 清洗数据并输出报告, 可选导出规范 CSV."""
    clean_df, report = _resolve_input(args)
    print(render_clean_report(report, clean_df, fmt=args.format))
    if args.output:
        clean_df.to_csv(args.output, index=False, encoding="utf-8")
        print(f"\n[已导出清洗后数据] {args.output} ({len(clean_df)} 行)")
    print("\n" + RATIONAL_PURCHASE_NOTICE)
    return 0


def cmd_describe(args: argparse.Namespace) -> int:
    """describe 子命令: 输出全部描述性统计指标."""
    clean_df, _ = _resolve_input(args)
    stats = descriptive_statistics(clean_df, top_n=args.top_n)
    print(render_describe(stats, fmt=args.format))
    if args.output and args.format == "json":
        with open(args.output, "w", encoding="utf-8") as fh:
            json.dump(stats, fh, ensure_ascii=False, indent=2)
        print(f"\n[已导出统计结果] {args.output}")
    print("\n" + RATIONAL_PURCHASE_NOTICE)
    return 0


def cmd_probability(args: argparse.Namespace) -> int:
    """probability 子命令: 输出概率推理与期望值."""
    prize_amounts = None
    if args.prize_amounts:
        with open(args.prize_amounts, "r", encoding="utf-8-sig") as fh:
            prize_amounts = json.load(fh)
    print(render_probability(fmt=args.format, prize_amounts=prize_amounts))
    print("\n" + RATIONAL_PURCHASE_NOTICE)
    return 0


def cmd_randomness(args: argparse.Namespace) -> int:
    """randomness 子命令: 卡方检验 + 多重比较校正 + 蒙特卡洛."""
    clean_df, _ = _resolve_input(args)
    res = randomness_tests(clean_df, mc_trials=args.mc_trials, seed=args.seed)
    print(render_randomness(res, fmt=args.format))
    if args.output and args.format == "json":
        with open(args.output, "w", encoding="utf-8") as fh:
            json.dump(res, fh, ensure_ascii=False, indent=2)
        print(f"\n[已导出检验结果] {args.output}")
    print("\n" + RATIONAL_PURCHASE_NOTICE)
    return 0


def cmd_generate(args: argparse.Namespace) -> int:
    """generate 子命令: 生成参考号码."""
    clean_df, _ = _resolve_input(args)
    res = generate_reference_numbers(
        clean_df, count=args.count, strategy=args.strategy, seed=args.seed)
    print(render_generate(res, fmt=args.format))
    if args.output and args.format == "json":
        with open(args.output, "w", encoding="utf-8") as fh:
            json.dump(res, fh, ensure_ascii=False, indent=2)
        print(f"\n[已导出生成结果] {args.output}")
    print("\n" + RATIONAL_PURCHASE_NOTICE)
    return 0


def cmd_report(args: argparse.Namespace) -> int:
    """report 子命令: 综合报告 (描述性 + 随机性 + 概率)."""
    clean_df, _ = _resolve_input(args)
    stats = descriptive_statistics(clean_df, top_n=args.top_n)
    rnd = randomness_tests(clean_df, mc_trials=args.mc_trials, seed=args.seed)
    print(render_report(clean_df, stats, rnd, fmt=args.format))
    if args.output and args.format == "json":
        with open(args.output, "w", encoding="utf-8") as fh:
            json.dump({
                "descriptive": stats,
                "randomness": rnd,
                "probability": {
                    "total_combinations": count_total_combinations(),
                    "any_prize_probability": any_prize_probability(),
                    "expected_value": expected_value(),
                },
            }, fh, ensure_ascii=False, indent=2)
        print(f"\n[已导出综合报告] {args.output}")
    print("\n" + RATIONAL_PURCHASE_NOTICE)
    return 0


def cmd_selftest(args: argparse.Namespace) -> int:
    """selftest 子命令: 运行概率自洽性断言与蒙特卡洛小样本交叉校验."""
    checks = self_consistency_check()
    print("=" * 72)
    print("概率自洽性断言 (精确计数法)")
    print("=" * 72)
    for key, value in checks.items():
        print(f"  {key:<32}: {value}")
    print(f"\n断言结果: {'PASSED' if checks['passed'] else 'FAILED'}")
    mc = monte_carlo_probability_check(trials=200_000, seed=DEFAULT_SEED)
    print("-" * 72)
    print(f"蒙特卡洛小样本交叉校验 (trials={mc['trials']}, seed={mc['seed']})")
    print(f"  {'奖级':<6} {'命中数':>8} {'模拟频率':>14} {'理论概率':>16} {'绝对误差':>12}")
    for name in PRIZE_ORDER:
        d = mc["prizes"][name]
        print(f"  {name:<6} {d['hits']:>8} {d['empirical']:>14.3e} "
              f"{d['theoretical']:>16.3e} {d['abs_diff']:>12.3e}")
    d = mc["no_prize"]
    print(f"  {'未中奖':<6} {d['hits']:>8} {d['empirical']:>14.6f} "
          f"{d['theoretical']:>16.6f} {d['abs_diff']:>12.6f}")
    print("=" * 72)
    return 0 if checks["passed"] else 1


def build_parser() -> argparse.ArgumentParser:
    """构建 CLI 参数解析器."""
    parser = argparse.ArgumentParser(
        prog="dlt_tool",
        description=("中国体育彩票超级大乐透历史数据分析工具。"
                     "开奖为独立随机事件, 本工具不预测未来结果。"),
        epilog=(RATIONAL_PURCHASE_NOTICE + " 用法示例: "
                "python dlt_tool.py probability"),
    )
    parser.add_argument("--version", action="version", version="dlt_tool 1.0.0")
    sub = parser.add_subparsers(dest="command", required=True)

    def add_common(p: argparse.ArgumentParser) -> None:
        p.add_argument("--input", "-i", default=None,
                       help="输入文件路径 (CSV/JSON); 缺省时使用内置模拟数据集")
        p.add_argument("--source", "-s", default=None,
                       choices=["csv", "json", "sample", "builtin"],
                       help="数据来源类型; 缺省时由 --input 后缀自动推断, 否则用内置模拟数据")
        p.add_argument("--format", "-f", default="text", choices=["text", "json"],
                       help="输出格式 (默认 text)")
        p.add_argument("--output", "-o", default=None,
                       help="可选: 导出结果文件 (clean 导出 CSV; 其余为 JSON)")

    p_clean = sub.add_parser("clean", help="导入并清洗校验数据")
    add_common(p_clean)
    p_clean.set_defaults(func=cmd_clean)

    p_desc = sub.add_parser("describe", help="描述性统计 (频次/冷热/遗漏/和值/形态)")
    add_common(p_desc)
    p_desc.add_argument("--top-n", type=int, default=5, help="冷热号 Top-N (默认 5)")
    p_desc.set_defaults(func=cmd_describe)

    p_prob = sub.add_parser("probability", help="概率推理 (奖级概率/期望值/返奖率)")
    p_prob.add_argument("--format", "-f", default="text", choices=["text", "json"],
                        help="输出格式 (默认 text)")
    p_prob.add_argument("--prize-amounts", default=None,
                        help="可选: 自定义奖级奖金 JSON 文件路径")
    p_prob.add_argument("--output", "-o", default=None, help="可选: 导出 JSON 结果")
    p_prob.set_defaults(func=cmd_probability)

    p_rnd = sub.add_parser("randomness", help="随机性检验 (卡方/多重比较/蒙特卡洛)")
    add_common(p_rnd)
    p_rnd.add_argument("--mc-trials", type=int, default=DEFAULT_MC_TRIALS,
                       help=f"蒙特卡洛模拟期数 (默认 {DEFAULT_MC_TRIALS})")
    p_rnd.add_argument("--seed", type=int, default=DEFAULT_SEED, help="随机种子")
    p_rnd.set_defaults(func=cmd_randomness)

    p_gen = sub.add_parser("generate", help="生成参考号码")
    add_common(p_gen)
    p_gen.add_argument("--count", type=int, default=DEFAULT_GENERATE_COUNT,
                       help=f"生成组数 (默认 {DEFAULT_GENERATE_COUNT})")
    p_gen.add_argument("--strategy", default="hot_weighted",
                       choices=["hot_weighted", "balanced_profile", "both"],
                       help="生成策略 (默认 hot_weighted)")
    p_gen.add_argument("--seed", type=int, default=DEFAULT_SEED, help="随机种子")
    p_gen.set_defaults(func=cmd_generate)

    p_rep = sub.add_parser("report", help="综合报告 (描述性+随机性+概率)")
    add_common(p_rep)
    p_rep.add_argument("--top-n", type=int, default=5, help="冷热号 Top-N (默认 5)")
    p_rep.add_argument("--mc-trials", type=int, default=DEFAULT_MC_TRIALS,
                       help=f"蒙特卡洛模拟期数 (默认 {DEFAULT_MC_TRIALS})")
    p_rep.add_argument("--seed", type=int, default=DEFAULT_SEED, help="随机种子")
    p_rep.set_defaults(func=cmd_report)

    p_self = sub.add_parser("selftest", help="概率自洽性断言 + 蒙特卡洛交叉校验")
    p_self.set_defaults(func=cmd_selftest)

    p_sample = sub.add_parser("make-sample", help="生成内置模拟数据集 CSV (供演示)")
    p_sample.add_argument("--output", "-o", default="sample_data_simulated.csv",
                          help="输出 CSV 路径")
    p_sample.add_argument("--issues", type=int, default=600, help="期数 (默认 600)")
    p_sample.add_argument("--seed", type=int, default=DEFAULT_SEED, help="随机种子")
    p_sample.set_defaults(func=cmd_make_sample)

    return parser


def cmd_make_sample(args: argparse.Namespace) -> int:
    """make-sample 子命令: 生成模拟数据集 CSV."""
    n = write_sample_csv(args.output, num_issues=args.issues, seed=args.seed)
    print(f"[已生成模拟数据集] {args.output} ({n} 期, seed={args.seed})")
    print("注意: 该文件为【模拟数据】, 仅用于演示, 非真实开奖记录。")
    print(RATIONAL_PURCHASE_NOTICE)
    return 0


def _normalize_source(args: argparse.Namespace) -> None:
    """当未显式指定 --source 时, 依据 --input 后缀推断来源; 无输入则用内置模拟数据."""
    if getattr(args, "source", None):
        return
    input_path = getattr(args, "input", None)
    if input_path:
        lower = str(input_path).lower()
        if lower.endswith(".json"):
            args.source = "json"
        else:
            args.source = "csv"
    else:
        args.source = "sample"


def main(argv: Optional[Sequence[str]] = None) -> int:
    """CLI 入口."""
    parser = build_parser()
    args = parser.parse_args(argv)
    if hasattr(args, "source"):
        _normalize_source(args)
    try:
        return int(args.func(args))
    except AssertionError as exc:
        print(f"[断言失败] {exc}", file=sys.stderr)
        return 2
    except Exception as exc:  # noqa: BLE001 - CLI 顶层兜底
        print(f"[运行错误] {exc}", file=sys.stderr)
        traceback.print_exc()
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
