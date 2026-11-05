# R2 pilot 选模规则（预注册草案，训练前冻结）2026-11-05

> **状态：** FROZEN_2026_11_05（lead 已批准；R2 训练/评测中不得再改）
> **来源章节：** configs/perception/landmark_two_class_protocol_v1.json、2026-11-05 R2 批准（唯一变量=数据）
> **证据域：** dev val_main 163 + identity 62（val-only）；不用于 holdout，不认证
> **最后核对：** 2026-11-05

## 规则（r2_joint）

1. 候选集合：训练产出的 last 与 best 两个 checkpoint（同 R1，不增加候选/不换模型）。
2. 每个候选在 **val-only** 上计算：
   - tower recall = val_main 163 上 tower 检测 recall（tau_det 0.25，IoU≥0.3，与训练侧 detector 口径一致；不用 final/holdout）；
   - MS1 recall = identity 62 上 class1 recall（35 个 MS1 GT 实例，同一 detector 口径）；
   - same-frame rate = identity 62 上同时含 tower+MS1 的帧中，tower 与全部 MS1 均正确匹配的比例（训练侧 detector 双匹配定义；正式 gate 仍用 evaltool 口径，二者不混用）。
3. 联合分数：**score = tower_recall + MS1_recall（等权）**，逐候选比较；
4. tie-break：同分 → same-frame rate 更高者；仍同分 → 候选名字母序（best < last，确定性）。
5. 只选一个；选中的 checkpoint 用于 pilot 门报告与 consumer 正式评测输入。
6. 选模规则、输入定义与代码路径在训练前写入本文件并记录 sha；训练后不得按结果回改。

## 实现与可复现

- 代码：src/boom_birds/evaluation/landmark_two_class.py 的 candidate_rank_key(candidate, "r2_joint")；CLI：scripts/landmark_train_two_class.py --selection-rule r2_joint。
- 单测：tests/evaluation/test_landmark_two_class.py（4 条选模规则测试，20 passed）。
- 与 R1 的 r1_detector 规则并存（R1 证据保持原样，不回改）。

## 冻结记录

- rule json: outputs/landmark_train/runs/r2_selection_rule.json **sha256 4d486b3e95c35d357814197cd4b365d7f973b69a3e7c019048df3fcbe590e1c6**
- freeze record: outputs/landmark_train/runs/r2_selection_rule_freeze.json **sha256 d26aacaefd1d375c3cfd69734ef094acd8b2bb77d0371480fd7d34af6b98edf**（status FROZEN_BEFORE_R2_TRAINING，approved_by lead，2026-11-05）
- 训练/评测中不得再改；consumer/holdout 不参与选模。