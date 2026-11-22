# 换版审订流水线说明

本目录把每批回访资料转成审订组可核对的换版依据，并给发行同事与服务台提供可回查的视图。
全部代码仅使用 Python 3.11 标准库。

## 运行

```sh
# 整轮审订：读取 data/，写出 outputs/ 三个文件
python3 run_review.py run --data data --output outputs --review-date 2026-11-22

# 服务台按出院批次查询
python3 run_review.py lookup B013 --output outputs

# 测试
python3 -m unittest discover -s tests -v
```

## 模块与口径

| 模块 | 职责 |
|---|---|
| `review/dataio.py` | 按 manifest 读取 JSON Lines，校验字段、主键、外键与取值集合 |
| `review/reconcile.py` | 合并评分员异判、套用复核决议、按理解目标归并（call 拆题须两部分都正确） |
| `review/comparability.py` | 处理锚点撤回，用共同案例重判可比性；共同案例不并入试验样本 |
| `review/evidence.py` | 双视角达成率、Wilson 95% 区间、保守口径、批次计数、顺序效应、错发/漏访登记 |
| `review/decision.py` | 公示下限/下降上限/完整批次门槛与渠道裁决、下轮补问清单 |
| `review/handoff.py` | 病区交接、三类处置范围、服务台逐批次视图 |
| `review/report.py` | `review_packet.json`、`review_report.md`、`service_desk.jsonl` |

### 关键口径（与资料约定一致）

1. **归并**：一次回述可覆盖多个理解目标，每人每目标只计一次。
   - `place`、`return`：任一有效项正确即达成。
   - `call`：旧版 `call-old` 单题；新版拆成 `call-new-a`/`call-new-b`，两部分都正确才算达成。
2. **异议**：同人同任务异判且无 `scorer_reviews` 决议的记为未定，不进入达成率分子分母；
   另给“未定按未达成”的保守率作为敏感性核对。已复核单元按决议入口径。
3. **可比性分级**：
   - `anchor`：共同锚点未撤回，可在回访试验内做旧/新定量比较；
   - `bridge-only`：锚点撤回但共同案例两版判定一致，只能定性核对，不能定量换版；
   - `incomparable`：锚点撤回且共同案例出现分歧，该语言×目标不可跨版比较；
   - `no-anchor`：无锚点且无可用共同案例（兜底）。
   共同案例不属于回访样本，永不并入达成率。
4. **双视角**：
   - assigned（试行分派）：按 `assigned` 版次，回答“分派上的效果”；
   - exposure（实际接触）：按真实 `paper`/`audio` 组合，回答“人群实际接触到什么”。
   错发记录在 exposure 视角按实际组合单列，不回补到分派组。
5. **漏访**：`followup != observed`（pending/refused）一律不进速率，只登记证据缺口；
   “只用既领新版又成功回访的人”不能发布。
6. **判定门槛**（每个关键目标独立，不抵消）：
   新版达成率 ≥ `minimum_acceptance`；较旧版下降 ≤ `max_decrease`；
   每侧完整批次（无漏访且无错发）≥ `minimum_cluster`；且必须是 `anchor` 可比。
7. **不确定性**：所有速率配 Wilson 95% 区间；分母为 0 标 `estimable=false`，不当作 0%。
8. **顺序效应**：在分派视角内按 `paper-first`/`audio-first` 分层，报告差值与区间重叠情况；
   错发或漏访集中在某顺序时，结合数据问题清单解释，不做过度因果解读。

## 输出文件

- `outputs/review_packet.json`：全量结构化依据（可比性、速率、顺序效应、批次、数据问题、裁决、补问清单、交接）。
- `outputs/review_report.md`：审订组人工核对报告，含阻断项、证据缺口与下轮补问对象。
- `outputs/service_desk.jsonl`：每行一个出院批次，含实际发放、尚能提供的组合、目标证据与裁决引用。

## 处置状态

| 状态 | 含义 |
|---|---|
| `continue-old` | 继续旧组合（在院批次与对照侧） |
| `allow-new` | 允许新组合（全部目标通过门槛，本轮资料下无组合达到） |
| `hold-evidence` | 证据不足暂缓：下限/下降/批次/可比性未过或新旧组合互不兼容 |
| `manual-harmonize` | 需人工统一说明：旧稿禁发新批次但在院批次仍需匹配口译稿 |

数据问题区分两类：可通过复核调整口径的（已复核异判）与需要补充证据的
（43 条未定异判、10 条错发、12 条漏访/拒访），全部保留原始 `score`/`encounter`/`cluster` 编号可回查。
