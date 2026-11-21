# 出院说明用语审订资料约定

所有回述只记目标是否达成，测试资料没有个人信息、医疗指示或实际出院内容。

## dispatch

assigned 为分派版次，paper、audio 为实际接触版次。cluster 是同病区同批次的人群键。

字段 `encounter`, `language`, `ward`, `assigned`, `paper`, `audio`, `order`, `cluster`, `followup`。

## scores

自家评分员各自记录，同人同任务出现异判时保留未定直到复核。

字段 `score`, `encounter`, `task`, `assessor`, `understood`, `received_on`。

## targets

归并语言与任务的理解目标。place 和 return 任一有效项正确视为达成。call 若拆题须各部分都正确。anchor_label 仅用于标记跨版含义可比较的题，null 无共同锚点。

字段 `language`, `task`, `goal`, `anchor_label`。

## anchor_changes

审核确认某语言某题的共同意义不再成立，适用于指定的审订轮次。复审日期前发出的依据可回查。

字段 `notice`, `language`, `task`, `applied_on`, `kind`。

## review_floors

关键理解目标按语言、拟投放组合判断。minimum_acceptance 为新版达成率公布下限，max_decrease 为较旧版可接受下降上限。minimum_cluster 为每侧可用于判断的最少完整批次数。

字段 `rule`, `goal`, `minimum_acceptance`, `max_decrease`, `minimum_cluster`。

## release_options

纸张和口译的兼容组合，禁止发行日期起该组合不能用于新批次。requires_pair 表明切换时需成套换发。

字段 `edition`, `language`, `paper`, `audio`, `requires_pair`, `banned_for_new_on`。

## active_wards

病区现有语言与手头版次，既已发纸但未完成口译的批次依其已有纸件保持匹配。

字段 `handoff`, `ward`, `language`, `encounter`, `paper`, `audio_complete`。

## bridge_cases

审订组核对跨版含义使用的合成共同案例，列出可比语言、理解目标、情形与两版任务的独立判定。confirmed 指复审认可；同一共同案例不属于回访试验样本。

字段 `bridge`, `language`, `goal`, `case`, `old_task`, `new_task`, `old_understood`, `new_understood`, `state`。

## scorer_reviews

评分员异议可以在审订前复核，决议只适用列出的该次回述任务。

字段 `review`, `encounter`, `task`, `decided`, `received_on`。
