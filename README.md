# 超级大乐透历史数据分析工具（dlt_tool）

**开源仓库**：<https://github.com/0HeiMao/dlt-analysis> · **许可证**：MIT · 语言：Python / JavaScript

> ⚠️ **先说清楚，免得白点**：本工具**完全在你自己的电脑上运行，没有线上版本**。
> `http://127.0.0.1:8765/` 是**本机回环地址**（127.0.0.1 永远指"这台电脑自己"）。只有先在本机把服务跑起来，浏览器才能打开它。
> **在 GitHub 页面上直接点这个链接一定打不开**——它访问的是你此刻电脑上并未运行的 8765 端口。想用网页版，按下面「本地网页」那行先启动服务即可。

提供两种用法：

| 用法 | 入口 | 适合 |
|---|---|---|
| 命令行（CLI） | `python dlt_tool.py <子命令>` | 批处理、脚本集成、只要数值结果 |
| 本地网页（Web） | 先跑 `python webapp/server.py`（或 `python launch_tool.py`，会自动打开浏览器），再访问 `http://127.0.0.1:8765/` | 交互式看图、点选参数、不想敲命令 |

Web 版为 FastAPI + 原生 HTML/JS/CSS，无构建步骤、无 CDN、可完全离线；详见 [`webapp/README.md`](webapp/README.md)。

> **版本**：1.0.0 · 单文件 Python CLI · 纯数值分析（无画图依赖）
>
> **总声明（先读这个）**：超级大乐透每期开奖为**相互独立的随机事件**。任意一注 5+2 组合的中奖概率恒为 **1/21,425,712**，与历史数据、号码选择、投注金额、投注方式完全无关。本工具**不能预测未来开奖结果**，所有分析仅描述历史样本、计算结构性概率与期望、检验样本与随机模型的一致性。
>
> **理性购彩提示**：彩票是娱乐消费而非投资；每期开奖为独立随机事件，任何统计分析都无法预测未来结果；中奖概率与投注金额、方式、号码选择无关；未成年人不得购买彩票；请量力而行，切勿沉迷。

---

## 交付物结构（按阅读顺序）

| 顺序 | 文件 | 内容 |
|---|---|---|
| 1 | `expert_role.md` | 专家角色设定：概率与统计建模专家（回答协议、置信度标注、拒答红线） |
| 2 | `math_model.md` | 数学模型与公式说明（超几何推导、奖级概率表、期望值、卡方、蒙特卡洛、全部口径） |
| 3 | `dlt_tool.py` | 完整可执行代码（单文件 CLI） |
| 4 | `example_output.md` | 示例运行结果（真实输出）与结论解读 |
| — | `webapp/` | 本地 Web 界面（FastAPI 后端 + 原生前端），见 `webapp/README.md` |
| — | `sample_data_simulated.csv` | **模拟数据集（非真实开奖记录）**，固定种子生成，600 期 |
| — | `dirty_demo.csv` | 脏数据演示文件（用于展示清洗校验规则） |
| — | `README.md` | 本文件 |

### Windows 桌面集成（可选）

`launch_tool.py` / `stop_tool.py` 负责后台拉起与停止 Web 服务，`portutil.py` 用 ctypes 直调 Windows API 做端口与进程管理（不依赖 `netstat`/`taskkill`）。
`_build/make_*.py` 可生成桌面快捷方式与开机自启项（需 `pip install pylnk3`）：

```bash
python _build/make_ico.py             # 生成 assets/lucky-star-five.ico
python _build/make_shortcut.py        # 桌面「启动」快捷方式
python _build/make_stop_shortcut.py   # 桌面「停止」快捷方式
python _build/make_autostart.py       # 登录后自动启动（删除对应 .lnk 即取消）
```

路径均为运行时推导（不写死用户名），换机器直接可用。

---

## 环境要求

- Python ≥ 3.8（开发验证环境：3.13）
- 依赖：`numpy`、`scipy`、`pandas`（无其他第三方依赖，不用 matplotlib）

安装依赖（任意 pip 均可）：

```bash
pip install numpy scipy pandas
```

## 快速开始

```bash
cd dlt_analysis
python dlt_tool.py probability        # 不需要数据文件，直接算奖级概率
python dlt_tool.py selftest            # 概率自洽性断言 + 蒙特卡洛交叉校验
```

---

## 子命令与真实可跑示例

以下命令均在 `dlt_analysis` 目录下执行（`$` 为提示符，不带 `$`）。

### 0. 查看帮助 / 版本

```bash
python dlt_tool.py --help
python dlt_tool.py --version
```

### 1. clean — 导入历史数据并清洗校验

```bash
# 清洗模拟数据集（600 期，应无问题）
python dlt_tool.py clean --input sample_data_simulated.csv

# 脏数据演示：12 条记录覆盖 9 类规则问题（8 条 error 丢弃、3 条 warning，4 条有效）
python dlt_tool.py clean --input dirty_demo.csv

# 导出清洗后的规范 CSV
python dlt_tool.py clean --input dirty_demo.csv --output cleaned.csv

# JSON 格式输出（便于程序对接）
python dlt_tool.py clean --input sample_data_simulated.csv --format json
```

清洗规则（每条违规都记录"期号 + 规则码 + 明细"，不静默丢弃）：
`FRONT_OUT_OF_RANGE` / `BACK_OUT_OF_RANGE`（超范围）、`FRONT_DUPLICATE` / `BACK_DUPLICATE`（同区重复）、`NOT_SORTED`（未升序，warning 并自动排序）、`DUPLICATE_ISSUE`（期号重复，error 丢弃后出现者）、`BAD_DATE`（日期不可解析）、`BAD_NUMBER_FORMAT`（非整数）、`BAD_ISSUE`（期号空）、`COLUMN_MISMATCH`（列数不符）。

**数据格式**：CSV 列 `期号,开奖日期,前区1..前区5,后区1,后区2`，日期支持 `YYYY-MM-DD` / `YYYY/MM/DD` / `YYYYMMDD`，也支持 JSON 来源（`--source json`）。不传 `--input` 时使用内置模拟数据集。

### 2. describe — 描述性统计

```bash
python dlt_tool.py describe --input sample_data_simulated.csv
python dlt_tool.py describe --input sample_data_simulated.csv --top-n 10   # 冷热号取前 10
```

输出九大指标（口径详见 `math_model.md` §4）：号码频次与频率（对照理论期望）、冷热号、遗漏值（当前/历史最大/平均）、和值分布（对照理论均值 90 与方差 450）、奇偶比、大小比（18 为界）、区间分布（5 区间）、连号统计、重号统计。

### 3. probability — 概率推理（无需数据文件）

```bash
python dlt_tool.py probability

# 自定义奖级奖金（JSON 文件: {"一等奖": 10000000, "二等奖": 200000, ...}）
python dlt_tool.py probability --prize-amounts my_prizes.json
```

输出：组合总数推导、9 奖级理论概率（超几何精确计算）、至少中奖概率、期望值/返奖率（**默认奖金为示例值，非官方承诺**）、自洽性校验结果。

### 4. randomness — 随机性检验

```bash
python dlt_tool.py randomness --input sample_data_simulated.csv

# 降低蒙特卡洛期数以加快速度 / 指定种子
python dlt_tool.py randomness --input sample_data_simulated.csv --mc-trials 20000 --seed 42
```

输出：卡方拟合优度检验（前区 df=34 / 后区 df=11）、单号码二项检验 + Bonferroni / BH-FDR 多重比较校正、蒙特卡洛经验 p 值（默认模拟 100,000 期，按样本期数分块）、最大遗漏对照、结论与局限声明。

### 5. generate — 参考号码生成

```bash
python dlt_tool.py generate --input sample_data_simulated.csv --count 5
python dlt_tool.py generate --input sample_data_simulated.csv --strategy both --count 4
```

策略：`hot_weighted`（热号加权）/ `balanced_profile`（形态匹配）/ `both`。每组号码逐条标注统计依据，并强制声明：**统计依据不改变任何单个组合的中奖概率（恒为 1/21,425,712）**。

### 6. report — 综合报告（一次跑全）

```bash
python dlt_tool.py report --input sample_data_simulated.csv
python dlt_tool.py report --input sample_data_simulated.csv --format json --output report.json
```

### 7. selftest — 自洽性断言

```bash
python dlt_tool.py selftest
```

运行四项精确断言（全组合数穷举求和、中奖+未中奖=总数、计数法 vs 公式法零差异、九等奖子情形一致）+ 200,000 次蒙特卡洛交叉校验。**必须 PASSED 才可信。**

### 8. make-sample — 重新生成模拟数据集

```bash
python dlt_tool.py make-sample --output my_sim.csv --issues 500 --seed 20240920
```

**生成的数据为模拟数据（均匀随机抽取），非真实开奖记录，仅用于演示工具能力。**

---

## 输出解读指南

1. **频率表**：先看"理论期望频次"列（前区 n/7、后区 n/6）。观测值围绕理论值波动是正常的——波动幅度是否超标由 randomness 的检验判定，不是肉眼判定。
2. **冷热号**：热/冷只是频率排序的中性描述。每期独立，热号下期命中概率仍是 5/35。
3. **遗漏**：前区单号期望遗漏约 6 期；出现 40+ 期遗漏在 600 期样本中属正常波动（见 randomness 的遗漏对照）。
4. **检验结论**：p ≥ 0.05 读作"未检出显著偏离"，**不等于证明均匀**；p < 0.05 也只说明"该样本与均匀模型不一致"，不提供任何预测信息。
5. **期望值**：返奖率约 51–53% 意味着长期每投入 1 元期望收回约 0.5 元。这是结构性负期望，不存在通过策略扭转的方法。

## 已知限制

- 一等/二等奖实际为**浮动奖金**（按奖池分配），本工具的期望值按示例固定奖金计算，仅演示方法。
- 示例数据集为模拟数据；接入真实历史数据时请使用 `clean --input <你的文件>` 并先看清洗报告。
- 卡方检验对"同期号码不重复导致的计数负相关"做了说明并用蒙特卡洛经验分布做精确参照，但一切检验结论仍受样本量与检验功效限制。

## 免责声明

本工具仅用于统计学习与数据检验演示，不构成任何投注建议，不预测任何未来开奖结果。彩票有风险，购彩需理性；未成年人不得购买彩票；如感到购彩行为失控，请及时寻求帮助。
