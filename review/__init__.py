"""出院说明用语审订：换版证据流水线。

模块划分：
- dataio     读取与校验 JSON Lines 资料
- reconcile  评分异议合并、按理解目标归并回述
- comparability 锚点撤回与共同案例（bridge）可比性
- evidence   达成率、不确定性、批次计数、分顺序/错发/漏访口径
- decision   公示下限核对与换版/继续/人工说明判定
- handoff    病区交接、发行组合与服务台批次视图
- report     机器可读 JSON 与人工核对 Markdown 输出
"""

__all__ = [
    "dataio",
    "reconcile",
    "comparability",
    "evidence",
    "decision",
    "handoff",
    "report",
]
