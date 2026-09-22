#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""dlt_tool 本地 Web 服务 (FastAPI + uvicorn).

把 dlt_tool.py 的计算能力以 HTTP API 形式提供给本地前端页面:
  - 后端直接 import dlt_tool 的计算函数 (不复制计算逻辑, 不调用 CLI 子进程);
  - 前端为无构建步骤的原生 HTML/JS/CSS 单页应用 (见 static/ 目录);
  - 全部 API 挂在 /api 前缀, 静态文件挂在 / (默认返回 index.html)。

!! 重要声明 !!
------------------------------------------------------------------
超级大乐透每期开奖均为**相互独立的随机事件**。本服务提供的全部统计
分析**无法预测未来任何一期的开奖结果**, 也不改变任何单个组合的
中奖概率 (恒为 1/21,425,712)。输出仅供统计学习与娱乐参考,
不构成任何投注建议。理性购彩, 量力而行, 未成年人不得购彩。
------------------------------------------------------------------

运行: python server.py [--port 8765]
依赖: fastapi, uvicorn (pip install fastapi uvicorn)

已知设计局限 (单用户本地工具):
  - 数据集状态保存在**模块级变量**中, 不支持多用户并发;
  - 服务重启后需重新载入数据集。
"""

from __future__ import annotations

import argparse
import csv
import json
import os
import sys
import tempfile
from datetime import date, datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

import numpy as np
import pandas as pd
from fastapi import FastAPI, File, HTTPException, Query, UploadFile
from fastapi.responses import JSONResponse, Response
from fastapi.staticfiles import StaticFiles

# --------------------------------------------------------------------------- #
# 0. 路径处理: 直接 import 同级的 dlt_tool 模块
# --------------------------------------------------------------------------- #
BASE_DIR = Path(__file__).resolve().parent.parent          # dlt_analysis/
APP_DIR = Path(__file__).resolve().parent                  # dlt_analysis/webapp/
STATIC_DIR = APP_DIR / "static"
if str(BASE_DIR) not in sys.path:
    sys.path.insert(0, str(BASE_DIR))

import dlt_tool as dt  # noqa: E402  (依赖上面的 sys.path 注入)

APP_VERSION = "1.0.0"
DEFAULT_PORT = 8765

RATIONAL_NOTICE = (
    "理性购彩提示: 彩票是娱乐消费而非投资; 每期开奖为独立随机事件, 任何统计分析都"
    "无法预测未来结果; 中奖概率与投注金额、方式、号码选择无关; 未成年人不得购彩; "
    "请量力而行, 切勿沉迷。"
)

app = FastAPI(
    title="超级大乐透历史数据分析工具 - 本地版",
    version=APP_VERSION,
    description="开奖为独立随机事件, 本工具不预测未来结果。" + RATIONAL_NOTICE,
)


# --------------------------------------------------------------------------- #
# 1. JSON 序列化 (numpy/pandas 类型 -> 原生 Python 类型)
# --------------------------------------------------------------------------- #
def jsonable(obj: Any) -> Any:
    """递归把 numpy / pandas 类型转换为可 JSON 序列化的原生类型.

    Args:
        obj: 任意对象 (dict/list/numpy 标量或数组/DataFrame 等).

    Returns:
        仅含 dict/list/str/int/float/bool/None 的结构.
    """
    if obj is None or isinstance(obj, (str, int, float, bool)):
        return obj
    if isinstance(obj, (np.bool_,)):
        return bool(obj)
    if isinstance(obj, (np.integer,)):
        return int(obj)
    if isinstance(obj, (np.floating,)):
        v = float(obj)
        return v if np.isfinite(v) else None
    if isinstance(obj, np.ndarray):
        return [jsonable(x) for x in obj.tolist()]
    if isinstance(obj, dict):
        return {str(k): jsonable(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple, set)):
        return [jsonable(x) for x in obj]
    if isinstance(obj, (datetime, date)):
        return obj.isoformat()
    if isinstance(obj, pd.DataFrame):
        return jsonable(obj.to_dict(orient="records"))
    if isinstance(obj, pd.Series):
        return jsonable(obj.tolist())
    # 兜底: 尝试 str, 保证不因未知类型炸掉序列化.
    return str(obj)


def ok(payload: Any, status: int = 200) -> Response:
    """构造 UTF-8 JSON 成功响应."""
    return Response(
        content=json.dumps(jsonable(payload), ensure_ascii=False, allow_nan=False),
        status_code=status,
        media_type="application/json; charset=utf-8",
    )


def fail(status: int, message: str) -> HTTPException:
    """构造统一 JSON 错误 (FastAPI 会序列化为 {'detail': message})."""
    return HTTPException(status_code=status, detail=message)


# --------------------------------------------------------------------------- #
# 2. 全局单数据集状态 (单用户本地工具, 见模块 docstring 局限说明)
# --------------------------------------------------------------------------- #
class DatasetState:
    """当前载入的数据集与其清洗报告."""

    def __init__(self) -> None:
        self.name: Optional[str] = None
        self.raw_rows: int = 0
        self.clean_df: Optional[pd.DataFrame] = None
        self.report: Optional[Dict[str, Any]] = None

    @property
    def loaded(self) -> bool:
        return self.clean_df is not None and len(self.clean_df) > 0

    def summary(self) -> Dict[str, Any]:
        if not self.loaded:
            return {"loaded": False, "name": None, "rows": 0, "valid_rows": 0}
        return {
            "loaded": True,
            "name": self.name,
            "rows": int(self.report["original_rows"]) if self.report else int(len(self.clean_df)),
            "valid_rows": int(len(self.clean_df)),
        }


state = DatasetState()


def _require_dataset() -> None:
    """未载入数据集时抛出 409, 引导用户先去数据管理页."""
    if not state.loaded:
        raise fail(409, "请先在数据管理页载入数据 (上传 CSV 或载入内置模拟数据)")


# --------------------------------------------------------------------------- #
# 3. API 端点
# --------------------------------------------------------------------------- #
@app.get("/api/health")
def api_health() -> Response:
    """健康检查: 服务状态 + 当前数据集摘要."""
    return ok({
        "status": "ok",
        "version": APP_VERSION,
        "dataset": state.summary(),
        "notice": "开奖为独立随机事件, 本工具不预测未来结果。",
    })


@app.post("/api/dataset/sample")
def api_dataset_sample() -> Response:
    """载入内置模拟数据集 (build_sample_dataframe, 600 期, 非真实开奖记录)."""
    raw_df = dt.build_sample_dataframe()          # 600 期, 固定种子模拟数据
    clean_df, report = dt.clean_records(raw_df)
    if len(clean_df) < 1:
        raise fail(500, "内置模拟数据生成异常, 请重试")
    state.clean_df = clean_df
    state.report = report
    state.raw_rows = int(report["original_rows"])
    state.name = "内置模拟数据集 (600 期, 模拟数据, 非真实开奖记录)"
    return ok({
        "message": "已载入内置模拟数据集 (600 期, 模拟数据, 非真实开奖记录)",
        "dataset": state.summary(),
        "report": report,
        "preview": clean_df.head(5).to_dict(orient="records"),
    })


@app.post("/api/dataset/upload")
async def api_dataset_upload(file: UploadFile = File(...)) -> Response:
    """上传 CSV 并清洗校验, 设为当前数据集.

    支持 '#' 开头注释行; 列数不符/空行在解析层记录, 其余规则由 clean_records 校验.
    原始条数为 0 或清洗后有效记录数 < 1 时返回 400 + 中文错误;
    文件编码非 UTF-8 (如 GBK/二进制) 或结构非法 (如单字段超长) 时返回 400 + 中文提示.
    """
    if file is None or not file.filename:
        raise fail(400, "未收到文件, 请选择 CSV 文件后重试")
    if not str(file.filename).lower().endswith(".csv"):
        raise fail(400, "仅支持 .csv 文件, 请检查文件后缀")

    suffix = Path(str(file.filename)).suffix or ".csv"
    tmp_path = ""
    try:
        with tempfile.NamedTemporaryFile(
            delete=False, suffix=suffix, prefix="dlt_upload_"
        ) as tmp:
            tmp_path = tmp.name
            content = await file.read()
            if not content:
                raise fail(400, "上传的文件为空, 请检查后重试")
            tmp.write(content)

        try:
            raw_df, parse_issues = dt.read_csv_tolerant(tmp_path)
        except UnicodeDecodeError:
            # 非 UTF-8 文件 (如 Excel 默认另存的 GBK CSV) 或二进制改名 .csv:
            # dlt_tool 以 utf-8-sig 解码会抛 UnicodeDecodeError, 在此转为
            # 400 + 中文提示, 不让 500 漏出.
            raise fail(
                400,
                "文件编码不是 UTF-8：请将 CSV 另存为 UTF-8 编码后重试"
                "（Excel 请选「CSV UTF-8」格式）",
            )
        except csv.Error:
            # 单字段超过 csv 默认 field_size_limit(128KB) 等结构非法文件
            # (压缩/混淆 JS、日志、base64 串等被误传): _csv.Error 会穿透
            # read_csv_tolerant, 在此同样转为 400, 不让 500 漏出.
            raise fail(
                400,
                "CSV 解析失败：文件结构非法（如单字段超长）",
            )
        if int(report_rows(raw_df, parse_issues)) <= 0:
            raise fail(400, "上传的 CSV 中没有可解析的数据行 (原始条数为 0)")

        clean_df, report = dt.clean_records(raw_df)
        if parse_issues:
            dt.merge_parse_issues(report, parse_issues)
        if len(clean_df) < 1:
            raise fail(
                400,
                f"清洗后有效记录数为 0 (原始 {report['original_rows']} 条全部被判定无效), "
                "无法载入; 请查看清洗报告中的 error 明细修正数据后重试",
            )

        state.clean_df = clean_df
        state.report = report
        state.raw_rows = int(report["original_rows"])
        state.name = f"上传文件: {file.filename}"
        return ok({
            "message": f"已载入 {file.filename}: 有效 {len(clean_df)} 条 / "
                       f"原始 {report['original_rows']} 条",
            "dataset": state.summary(),
            "report": report,
            "preview": clean_df.head(5).to_dict(orient="records"),
        })
    except HTTPException:
        raise
    finally:
        if tmp_path and os.path.exists(tmp_path):
            try:
                os.unlink(tmp_path)
            except OSError:
                pass


def report_rows(raw_df: pd.DataFrame, parse_issues: List[Dict[str, str]]) -> int:
    """计算"原始条数"口径: DataFrame 行数 + 解析层被丢弃的行数."""
    return len(raw_df) + len(parse_issues)


@app.get("/api/describe")
def api_describe(top_n: int = Query(default=5, ge=1, le=20)) -> Response:
    """描述性统计 (频次/冷热/遗漏/和值/形态等全部指标)."""
    _require_dataset()
    stats = dt.descriptive_statistics(state.clean_df, top_n=top_n)
    return ok({
        "dataset": state.summary(),
        "notice": "统计仅描述历史样本, 不代表未来走势; 独立随机事件无可预测性。",
        "statistics": stats,
    })


@app.get("/api/probability")
def api_probability() -> Response:
    """概率推理: 组合总数 / 9 奖级概率 / 期望值(示例奖金) / 自洽性断言."""
    checks = dt.self_consistency_check()
    return ok({
        "combination_counts": {
            "front": dt.count_front_combinations(),
            "back": dt.count_back_combinations(),
            "total": dt.count_total_combinations(),
        },
        "prizes": dt.prize_probabilities(),
        "any_prize_probability": dt.any_prize_probability(),
        "expected_value": dt.expected_value(),
        "self_consistency": checks,
        "notice": "奖金为示例值, 非官方承诺; 每个组合中奖概率恒为 1/21,425,712。",
    })


@app.post("/api/probability")
def api_probability_custom(amounts: Dict[str, float]) -> Response:
    """自定义 9 奖级单注奖金, 重算期望值与返奖率."""
    if not isinstance(amounts, dict) or not amounts:
        raise fail(400, "请求体必须是非空的奖级奖金 JSON 对象, 例如 {\"一等奖\": 10000000}")
    for name, value in amounts.items():
        if name not in dt.PRIZE_RULES:
            raise fail(400, f"未知奖级: {name}; 合法奖级为 {list(dt.PRIZE_ORDER)}")
        if not isinstance(value, (int, float)) or isinstance(value, bool) or value < 0:
            raise fail(400, f"奖级 {name} 的奖金必须为非负数值")
    ev = dt.expected_value(prize_amounts=dict(amounts))
    return ok({
        "message": "已按自定义奖金重算 (奖金为用户输入的假设值, 非官方承诺)",
        "expected_value": ev,
        "self_consistency": dt.self_consistency_check(),
    })


@app.get("/api/randomness")
def api_randomness(
    mc_trials: int = Query(default=20_000, ge=100, le=500_000),
    seed: int = Query(default=dt.DEFAULT_SEED),
) -> Response:
    """随机性检验: 卡方 + 多重比较校正 + 蒙特卡洛经验 p 值."""
    _require_dataset()
    result = dt.randomness_tests(state.clean_df, mc_trials=mc_trials, seed=seed)
    return ok({
        "dataset": state.summary(),
        "result": result,
        "notice": "不拒绝原假设不等于证明开奖是均匀随机的; 结论受样本量限制, "
                  "且不能预测未来任何一期结果。",
    })


@app.get("/api/generate")
def api_generate(
    count: int = Query(default=5, ge=1, le=20),
    strategy: str = Query(default="both"),
    seed: int = Query(default=dt.DEFAULT_SEED),
) -> Response:
    """生成参考号码 (hot_weighted / balanced_profile / both)."""
    _require_dataset()
    if strategy not in ("hot_weighted", "balanced_profile", "both"):
        raise fail(400, "strategy 仅支持 hot_weighted / balanced_profile / both")
    result = dt.generate_reference_numbers(
        state.clean_df, count=count, strategy=strategy, seed=seed
    )
    return ok({
        "dataset": state.summary(),
        "result": result,
        "notice": "统计依据不改变任何单个组合的中奖概率 (恒为 1/21,425,712), "
                  "生成结果不具备预测能力。",
    })


# --------------------------------------------------------------------------- #
# 4. 静态文件 (挂 /; API 路由已先注册, 优先级更高)
# --------------------------------------------------------------------------- #
app.mount("/", StaticFiles(directory=str(STATIC_DIR), html=True), name="static")


# --------------------------------------------------------------------------- #
# 5. 入口
# --------------------------------------------------------------------------- #
def main() -> int:
    """CLI 入口: python server.py [--port 8765]."""
    parser = argparse.ArgumentParser(
        prog="server.py",
        description="dlt_tool 本地 Web 服务 (开奖为独立随机事件, 不预测未来结果)。",
    )
    parser.add_argument("--port", type=int, default=DEFAULT_PORT,
                        help=f"监听端口 (默认 {DEFAULT_PORT})")
    parser.add_argument("--host", type=str, default="127.0.0.1",
                        help="监听地址 (默认 127.0.0.1, 仅本机访问)")
    args = parser.parse_args()

    import uvicorn
    print("=" * 72)
    print("超级大乐透历史数据分析工具 - 本地 Web 服务")
    print(f"  地址   : http://{args.host}:{args.port}/")
    print("  声明   : 开奖为独立随机事件, 本工具不预测未来结果。")
    print("  提示   : " + RATIONAL_NOTICE)
    print("=" * 72, flush=True)
    uvicorn.run(app, host=args.host, port=args.port, log_level="info")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
