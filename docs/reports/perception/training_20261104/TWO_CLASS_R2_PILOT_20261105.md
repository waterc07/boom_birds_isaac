# Two-class R2 pilot（v6.2 + 近距 MS1，15ep seed0）2026-11-05

> **状态：** BASELINE（dev 验证集有界实验；非认证/板端/导航）
> **来源章节：** configs/perception/landmark_two_class_protocol_v1.json（PRE-REGISTERED）、v6.2 freeze、R2 选模规则（FROZEN）
> **证据域：** 仿真 dev val_main 163 + identity 62；train 902 图（v6.1 800 + T38 近距 MS1 102）；无 Isaac 运行、无 holdout、无板端
> **最后核对：** 2026-11-05

## 0. 结论

- R2 = R1 唯一变量=数据：加入 T38 近距 MS1 训练族（A deef8284 52 + B bfb73d68 50 = 102，class1 v=0），base weights/v6.1 其余输入/warmup/超参保持不变；15ep seed0，wall 188.82 s，峰值显存 2149 MiB。
- 不可变快照 v7b：snapshot sha 93ee18fc…，config sha 5daef982…（与官方 v7b 字节一致，34 artifacts），pre_train / pre_selection / post_train 全部 VALID，独立 --verify VALID。
- 训练侧（detector 口径）相对 R1 的改善：val tower recall 0.821→**0.853**（81/95）、identity MS1 recall 0.286→**0.571**（20/35，达到 ≥0.50）、MS1-only 错误塔 claim 0/9、identity claim precision 1.000。
- 训练侧仍低于门限的：same-frame（官方 detector-side 双匹配口径）**val 15/47=0.319、identity 13/26=0.500 < 0.60**；consumer 正式指标由 evaltool 用本包预测计算（见 §7）。

## 1. 数据（v6.2）

| 项 | 值 |
| --- | --- |
| freeze | configs/perception/landmark_split_freeze_v6_2.json file sha 71a4eef0…，canonical d8ad5ca0…；train 26 组/2396 帧、val 14/1006、excluded 9/1107 |
| v4.1 | 436 实际输入排除 9 帧未覆盖投影风险（427），addendum class1 60 帧（annot 38 + annot2 22，同框 38） |
| T30 | pool 373（A 181 + B 192；class0 232 / class1 123 / 同框 39） |
| T38 近距 MS1 | final pool 102 = A 52（deef8284…）+ B 50（bfb73d68…）；class1 102、class0 0、same-frame 0；class1 h 184.1/209.35/220.15/226.7 px（min/median/p90/max） |
| dataset | dev_v7：train **902 图/902 标签**（class0 575、class1 285、同框 77；空负例保留、GT_UNOBS 3 排除）；val **134/134**（95 pos + 39 负例，GT_UNOBS 29 排除）；data.yaml ab95cac7…；dataset_build 7a45202e… |
| merged labels | outputs/landmark_train/dataset/labels_train_v6_2_merged.json sha ff3f439a… |
| 选模规则 | r2_joint（tower recall + MS1 recall 等权 → same-frame tie → name），rule json sha 4d486b3e…，freeze record d26aacae… |

## 2. 训练与选模

- 初始化：stage_verify_v5/seed2 last（6b86ef1f，单类）→ nc=2 head 重建（Transferred 391/397）；batch16、imgsz640、AMP、warmup 15（与 R1 相同，15ep 全程 warmup 保持为已记录限制）、patience 20、seed 0、workers 0、cache ram。
- 候选：last / best；按冻结 r2_joint 排序 → 选中 **last**（权重 sha 64ac3822…；best sha f55ec138…）。

## 3. 训练侧指标（tau_det 0.25、tau_iou 0.3；分母显式）

| 集合 | 指标 | R2 选中 last | R1 对照（last） |
| --- | --- | --- | --- |
| val_main 163 | tower recall | 81/95 = 0.853 | 78/95 = 0.821 |
| val_main 163 | tower claim precision | 88/99 = 0.889 | 79/90 = 0.878 |
| val_main 163 | reference coverage（3px） | 15/41 = 0.366 | 8/41 = 0.195 |
| val_main 163 | bearing median / P90 | 0.865° / 1.969°（n=39） | 0.822° / 1.963° |
| identity 62 | MS1 recall | **20/35 = 0.571** | 10/35 = 0.286 |
| identity 62 | MS1-only 错误 tower 声明 | 0/9 | 0/9 |
| identity 62 | 同框（训练侧双匹配） | 13/26 = 0.500 | 10/26 = 0.385 |
| identity 62 | identity claim precision | 1.000（57 claims） | 1.000（48 claims） |
| identity 62 | reference coverage（3px） | 7/18 = 0.389 | 6/18 = 0.333 |
| identity 62 | bearing median / P90 | 0.844° / 3.803°（n=18） | 1.194° / 3.411° |

注：训练侧与 evaltool 的 tower/MS1/同框计数差异来自匹配口径与 keypoint 有效性过滤；**pilot 门以 evaltool 正式数字为准**。

## 4. pilot 门条件（训练侧筛选；正式由 lead 汇总）

| 条件 | 训练侧值 | 训练侧判定 |
| --- | --- | --- |
| tower recall ≥0.70 | 0.853 | PASS |
| MS1 recall identity ≥0.50 | 0.571 | **PASS（R1 为 FAIL）** |
| MS1-only 错误塔 claim ≤1 | 0/9 | PASS |
| same-frame ≥0.60 | 0.500 | FAIL（训练侧口径；evaltool 正式同框口径待定） |
| identity precision ≥0.95 | 1.000 | PASS |
| bearing median ≤3° | 0.865° / 0.844° | PASS |
| tower recall 不比基线差 >0.08 | 0.853 ≥ 0.741 | PASS |
| consumer confirmed success ≥0.30 | PENDING（evaltool） | — |

## 5. 证据

| 内容 | 路径 / sha |
| --- | --- |
| 训练证据 | two_class_pilot_seed0.json sha a6ef7fdb…（status TWO_CLASS_R2_PILOT_DEV_VALIDATION_ONLY） |
| 快照 | run_snapshot.json（snapshot sha 93ee18fc…，config 5daef982…，34 artifacts，三阶段 VALID） |
| 预测 val_main last / best | 52fa71f5… / b6f29eb1…（含 keypoint_confidence，131/110 detections 全覆盖） |
| 预测 identity last / best | 595cc5a5… / 6d87ae55…（77/60 detections，含 keypoint_confidence） |
| 权重 last / best | 64ac3822… / f55ec138… |
| 数据 | dev_v7/dataset_build.json 7a45202e…、data.yaml ab95cac7…、labels_train_v6_2_merged.json ff3f439a… |
| 冻结 | split freeze v6.2 file 71a4eef0…；snapshot v7b 5daef982…；selection rule 4d486b3e… |

## 6. 限制与非声明

- agent-proxy 标签（非独立人工 GT）；近距 MS1 102 帧为 class1-only（塔不在 FOV），不覆盖同框近距；v4.1 addendum 60 帧非全覆盖；无 holdout。
- warmup_epochs=15 == 总 15ep（全程 warmup）为 R1/R2 共同已记录限制；R2 未改超参/epoch/模型，唯一变量=数据。
- 不进入 3 seed；pilot 门/是否继续由 lead 汇总正式指标判定。
## 7. 最终判定（lead 2026-11-05 收口）

**pilot gate FAIL，R2 recipe 被拒，版本停止，不进入 3 seed / holdout。**

| 条件 | R2 选中 last（official） | 判定 |
| --- | --- | --- |
| tower recall val_main ≥0.70 | 81/95 = 0.853 | PASS |
| MS1 recall identity ≥0.50 | 20/35 = 0.571（R1 0.286） | PASS（已修复） |
| MS1-only 错误塔 claim ≤1 | 0/9 | PASS |
| same-frame disambiguation ≥0.60（detector-side 双匹配） | **val 15/47=0.319、identity 13/26=0.500** | **FAIL** |
| identity precision ≥0.95 | 1.000 | PASS |
| consumer confirmed success ≥0.30（val all-positive 121） | 0.645 | PASS |
| bearing median ≤3° | 0.865°（val）/0.844°（identity） | PASS |
| tower recall 不比基线差 >0.08 | 0.853 ≥ 0.741 | PASS |

**失败判定要点（写入失败分析）**：R2 虽把 MS1 recall 0.286→0.571，但 **official same-frame 0.319/0.500 < 0.60**、**identity false-ref 0.077→0.500**、**consumer all 0.698→0.434** → 版本停止；不进入 3 seed。

### same-frame 定义（本版固定，不再两套混用）

- pilot gate 第 4 条使用 **detector-side 双匹配定义**：both-visible 帧中，class0 claim 必须匹配 GT tower **且** 全部 class1 GT 实例被正确匹配（不允许把 MS1 当塔）；本版 official = val 15/47=0.319、identity 13/26=0.500。
- evaltool consumer evaluator 的“塔 claim 与 GT 塔匹配”口径（val 38/47=0.809、identity 25/26=0.962）仅作**诊断对照**，不作为 pilot gate 输入；后续版本不得改回该口径规避门限。

### 最终 artifact sha（定稿，不再改写）

| 内容 | sha |
| --- | --- |
| 本报告 TWO_CLASS_R2_PILOT_20261105.md | （见文件自身 sha，下方消息报告） |
| 训练证据 two_class_pilot_seed0.json | a6ef7fdbbdd1d7d26d91137da71b6bc303b578dc22ddcd90e66a42d746f35e1e |
| 快照 run_snapshot.json | 93ee18fc973e5f8446e485723bed596b42a5a74095df9f0bb2d3d4b752cb6284 |
| snapshot config（= 官方 v7b） | 5daef9824dd0a2538f2fd422fc5bf4a2fcefacb1d86df5407bf813030c7b200e |
| 预测 val_main last / best | 52fa71f5275dbb9f… / b6f29eb1c7d16711… |
| 预测 identity last / best | 595cc5a5e0c0ff2d… / 6d87ae555f312041… |
| 权重 last / best | 64ac38229adc658b… / f55ec1386e1d8332… |
| 数据 freeze / merged / dataset_build | 71a4eef0… / ff3f439a… / 7a45202e… |
| 选模规则 / freeze record | 4d486b3e… / d26aacae… |
| evaltool official 证据 | summary a0e2cf06…、evidence shas 5c0bcb1f…、report 637d6c8d…（pilot_v7b_canonical） |

- 预测仅重导一次（补 keypoint_confidence，无训练/权重变化）：早期 sha c46035ea/0c41bd9f 已被上表替换，之后未再改写。
- 本报告写入后即为定稿；不再改写预测/证据/快照；版本停止。