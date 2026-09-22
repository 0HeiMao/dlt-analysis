# dlt_tool 本地 Web 前端

超级大乐透历史数据分析工具的本地 Web 界面：**FastAPI 后端 + 无构建步骤的原生 HTML/JS/CSS 前端**，前后端都在本机运行，无任何云依赖、无 CDN 依赖（图表为手写 SVG），可完全离线使用。

## 重要声明

- 超级大乐透每期开奖均为**相互独立的随机事件**，本工具不预测未来结果。
- 任何统计依据（热号、形态、遗漏等）都**不改变任何单个组合的中奖概率**（恒为 1/21,425,712）。
- 理性购彩：彩票是娱乐消费而非投资；量力而行；未成年人不得购彩。

## 环境要求

- Python：任意 Python 3.10+
- 依赖：`numpy`、`pandas`、`scipy`（dlt_tool 本体）+ `fastapi`、`uvicorn`（Web 服务）
- 安装（唯一新增依赖）：

```bash
pip install fastapi uvicorn
```

## 启动

```bash
cd webapp
python server.py
# 默认地址 http://127.0.0.1:8765/ ；自定义端口: python server.py --port 9000
```

启动后浏览器打开 `http://127.0.0.1:8765/` 即可使用。

> 注意：`127.0.0.1` 是本机回环地址，服务必须在本机运行才可访问；**在 GitHub 页面上直接点击该地址是打不开的**（那里没有服务在监听）。

## 页面功能（五个标签页）

| 标签页 | 功能 |
|---|---|
| 数据管理 | 上传 CSV 清洗校验 / 载入内置模拟数据集（600 期，**模拟数据，非真实开奖记录**）；展示清洗报告与问题明细 |
| 描述统计 | 前/后区频次 SVG 柱状图（叠加理论期望虚线）、冷热号、遗漏值表、和值直方图、奇偶/大小/区间/连号/重号 观测 vs 理论表 |
| 概率推理 | 九奖级概率表（超几何精确计算）、期望值计算器（9 个奖金可编辑，实时重算返奖率）、概率自洽断言徽章 |
| 随机性检验 | 卡方检验、单号二项检验 + Bonferroni/FDR 多重比较校正、蒙特卡洛经验 p 值、最大遗漏对照 |
| 参考号码 | hot_weighted / balanced_profile / both 三种策略，每组附统计依据说明 |

## API 端点

全部挂在 `/api` 前缀，返回 UTF-8 JSON：

| 方法 | 路径 | 说明 |
|---|---|---|
| GET | `/api/health` | 服务与数据集状态 |
| POST | `/api/dataset/sample` | 载入内置模拟数据集（600 期） |
| POST | `/api/dataset/upload` | 上传 CSV（multipart 字段 `file`），清洗并设为当前数据集 |
| GET | `/api/describe?top_n=5` | 描述性统计（需先载入数据） |
| GET | `/api/probability` | 奖级概率 + 期望值（示例奖金）+ 自洽性断言 |
| POST | `/api/probability` | 自定义 9 奖级奖金重算期望值（body: JSON 对象） |
| GET | `/api/randomness?mc_trials=20000&seed=20240920` | 随机性检验（需先载入数据） |
| GET | `/api/generate?count=5&strategy=both&seed=20240920` | 参考号码生成（需先载入数据） |

错误统一返回 JSON `{"detail": "中文错误信息"}`；未载入数据集时数据类端点返回 409。

## 已知设计局限

- **单用户本地工具**：当前数据集保存在服务进程的模块级变量中，不支持多用户并发访问；服务重启后需重新载入数据集。
- 服务默认只监听 `127.0.0.1`（仅本机访问），不要暴露到公网。
- 后端直接 `import dlt_tool` 复用其计算函数；修改 `dlt_tool.py` 后重启服务生效。

## 快速自测（curl）

```bash
curl http://127.0.0.1:8765/api/health
curl -X POST http://127.0.0.1:8765/api/dataset/sample
curl "http://127.0.0.1:8765/api/describe?top_n=5"
curl http://127.0.0.1:8765/api/probability
curl "http://127.0.0.1:8765/api/randomness?mc_trials=20000"
curl "http://127.0.0.1:8765/api/generate?count=3&strategy=both"
curl -F "file=@../dirty_demo.csv" http://127.0.0.1:8765/api/dataset/upload
```
