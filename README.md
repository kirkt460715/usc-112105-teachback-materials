# 出院说明用语审订

所有回述只记目标是否达成，测试资料没有个人信息、医疗指示或实际出院内容。

项目使用 Python 3.11.2 标准库。资料按来源表以 UTF-8 JSON Lines 保存，每行是一条记录。缺失值写作 `null`，其业务含义见资料约定。列名见 `data/manifest.json`，编号由各资料表原样保留。

[资料约定](docs/materials.md)说明各表的来源、时间及关联语义。[流水线说明](docs/pipeline.md)描述换版审订的口径、模块与输出。从项目根目录可检查资料能否读取  

```sh
python3 inspect_inputs.py
python3 -m unittest discover -s tests -v
```

一轮回访资料到齐后生成审订依据与服务台视图：

```sh
python3 run_review.py run --data data --output outputs --review-date 2026-11-22
python3 run_review.py lookup B013 --output outputs
```
