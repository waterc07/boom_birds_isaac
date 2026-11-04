# dev train/val 标注：近重复去重、代表抽样与 v2.1 标注（2026-11-04）

> **状态：** PROVISIONAL（dev 训练/选模用代理标注；不是模型效果、板端、导航或 Gate 验收；与 final 池标签无关）
> **来源章节：** SYSTEM_ARCHITECTURE_V2_2.md §7.4/§7.5/§7.7/§7.8；标注语义依据 configs/perception/landmark_annotation_spec_v2_1.json（FROZEN_FOR_DATA，sha256 010255d931936457ded48db9b3691b69a31d6015f1f84fbbc6a659f10f766eac）；分组依据 configs/perception/landmark_split_freeze_v2.json（sha256 5d1d3dbcc1d950e73dfd74d4d7c64c2d307aab9786367a0b674f04e163c02407）+ T9 第一批/HN 第二批辅助组描述
> **证据域：** 离线标注 QA（Isaac 合成 320×240 RGB；dev train 160 / val 134 帧；agent 代理标注 + 接触表视觉复核；无模型训练/推理，无板端/SITL/实飞/导航）
> **最后核对：** 2026-11-04（仓库 E:\isaac\proj_boom_birds，分支 feat/v2.2-simulation-perception，HEAD 800c53b，工作树含并行 teammate 未提交修改；本任务未 commit/push）

## 0. 结论先行

1. **train 标签**：160 帧（present 105 / absent 52 / undecidable 3；keypoint 56；截断 9；未验证 confuser 6）。labels_train.json sha256 01977b9fea97c58bcdda2c6c301763ac52113bcc411a23094924b917ec08d2df；格式 QA **PASS 160/160，0 error / 0 warning**。
2. **val 标签**：134 帧 = 原有系统抽样 110 帧 + HN 第二批最小子集 24 帧（HN1 13 / HN2 11）；present 106（含 11 个 GT_UNOBSERVABLE 全遮挡帧）/ absent 25 / undecidable 3；keypoint 41；截断 17；负例类型 TARGET_ABSENT 12、SIMILAR_STRUCTURE 13（HN1）。labels_val.json sha256 c3944e081d09d8a1d8398a0fb01a854580b116d004d8dcf14dacfa7f9493520d；格式 QA **PASS 134/134，0 error / 0 warning**。
3. **帧清单**：configs/perception/landmark_dev_label_lists_v1.json（sha256 befbbea1b587261ed861a081706fe44a8a761aa90b04743fb137ddbd85c27701，status DRAFT_FOR_DATAFREEZE_VAL_HN_MINIMAL_MERGED）含 train/val 逐组明确帧清单、组归属、负例类型、标签 sha、spec sha、抽样规则摘要。
4. **去重/抽样**：固定规则在查看任何图像前写定，不使用模型/检测器分数；组内 sha 相同 + dHash64 Hamming≤6 且 64×48 灰度 MAD≤3.0 近重复聚类 → medoid 代表 → 端点+midpoint systematic 固定步长 → capture 元数据覆盖 override。全量帧清单与逐帧排除理由在 dedup_sampling_report.json；跨组/跨 split sha 重复 **0**。
5. **新增 T9 第一批 dev 族已纳入**（inner_north→val、inner_south/static_high/static_negative→train、static_low→val，按 Lead 2026-11-04 指示）；HN 第二批最小子集已并入 val（HN1 = TARGET_ABSENT + verified 合成 confuser；HN2 = present+OCCLUDED+无 bbox = GT_UNOBSERVABLE，**不是负样本**）。
6. **边界**：单代理 AGENT_PROXY + SELF_CHECKED，非人类/专家独立审查；bbox 为投影 aid 校准 + 目视复核（bbox_source=PROJECTION_AID_CALIBRATED），不是逐像素人工框；参考点来自严格绿色 cue（COLOR_CUE_ASSISTED，independent_of_detector_cue=false）。标签只在 ignored outputs/，仓库只留清单/hash/统计。

## 1. 数据来源与分组

### 1.1 上游冻结与采集

| 项目 | 值 |
| --- | --- |
| 主划分 | configs/perception/landmark_split_freeze_v2.json（freeze_id landmark_split_freeze_v2，freeze_sha256 269d9a659db387beee345daff33cf1a3508261d099f548aeb93353b94c33afed，文件 sha256 5d1d3dbcc1d950e73dfd74d4d7c64c2d307aab9786367a0b674f04e163c02407） |
| T9 第一批辅助组 | dev_extra_groups_20261104.json（sha256 8cbcdf8937b2c8635a20839fbcbd80fd48bbcf501047290a9076431f40232acc，status T9_FIRST_BATCH_PLACEHOLDER_NOT_A_FROZEN_SPLIT） |
| T9/HN 采集 case 与注入记录 | configs/scenarios/landmark_dev_cases_v2.json（sha256 10b55544e4d6565dd1520e699f7c51aaded8bc6fc305f452d3000c566f2db1bc） |
| 采集 run | T9 第一批 outputs/sensor_shadow/lm_dev_capture_20261104_sensor（337 RGB 记录，gate.accepted 322，15 帧 WARMUP 被拒）；HN 第二批 outputs/sensor_shadow/lm_dev_hn_capture_20261104_sensor（59 RGB 记录，gate.accepted 53，6 帧 WARMUP） |
| GUI | 采集由 capture（T1/T9）完成，可见前台 GUI；本轮只离线读帧，未启动 Isaac、未 headless |

Lead 口径的“337 accepted / 59 accepted”是 published RGB 记录数；本任务抽样 roster 使用与 v2 冻结一致的 gate.accepted 语义（322 / 53），差额全部为 WARMUP 拒绝，不是丢帧。额外 dev 帧只作训练/验证数据，不进入 final 池；final 池图像/标签未被本任务用于选帧、标注决策或调参。

### 1.2 组与 split（新增 T9/HN 批次）

| 批次 | group_id | family | split | accepted（gate） |
| --- | --- | --- | --- | ---: |
| T9 batch1 | g_lmf_dev_inner_north_0 | fam_dev_inner_north | val（新走廊） | 155 |
| T9 batch1 | g_lmf_dev_inner_south_0 | fam_dev_inner_south | train | 102 |
| T9 batch1 | g_lmf_dev_static_high_0 | fam_dev_static_high | train | 23 |
| T9 batch1 | g_lmf_dev_static_low_0 | fam_dev_static_low | val（尺度） | 21 |
| T9 batch1 | g_lmf_dev_static_negative_0 | fam_dev_static_negative | train（负例） | 21 |
| HN batch2 | g_lmf_dev_hn1_confuser_0 | fam_dev_hn1_confuser | val（困难负例） | 27 |
| HN batch2 | g_lmf_dev_hn2_occluder_0 | fam_dev_hn2_occluder | val（GT_UNOBSERVABLE） | 26 |

HN 两个 group 只进 val；本轮只标注最小子集（13+11=24 帧），剩余 29 个 gate.accepted HN 帧未标注（见 §8）。

## 2. 去重与代表抽样（固定规则，看图前写定）

### 2.1 规则摘要（全文在脚本 docstring 与 dedup_sampling_report.json.rules）

- **R1 roster**：冻结划分中 split∈{train,val} 的 accepted 帧；组内按（episode 顺序, sequence）排序。
- **R2 完全相同**：组内 sha256 相同 → 只保留首个（SHA_DUPLICATE）；跨组/跨 split sha 重复单独报告（本轮 0）。
- **R3 近重复**：同时满足 dHash64（9×8 灰度水平梯度）Hamming ≤ 6（≤9.4% 位翻转）且 64×48 灰度缩略图平均绝对差 ≤ 3.0/255（≤1.2% 满量程）才合并；并查集传递闭包成簇。理由：采集间隔 0.25 s、静态 reset 帧仅渲染噪声差异；双阈值联合避免把真实视角变化并掉。
- **R4 代表**：簇内 medoid（到同簇其他成员 dHash 距离和最小；并列取 roster 更小）。
- **R5 固定步长**：静态组（accepted<32）取全部簇代表；动态组按簇数比例分配预算（每动态组最少 8），取首尾 + midpoint systematic idx_i=floor((i+0.5)*n/k)；无随机数。
- **R6 覆盖 override**（只用采集元数据：相机位姿 + 三角化塔估计，无模型分数）：最小/最大距离帧、最大 |相对方位| 帧、预测左右缘截断帧、green 3–6 px 小参考帧；按“最近替换”保持组预算不变。
- **R7 预算**：train 160 / val 110（任务预算 150–200 / 100–120）。HN 第二批另用固定规则 hn_midpoint_systematic_v1（HN1 k=13、HN2 k=11）追加到 val，不占 110 预算，故 val 最终 134。
- **R8 排除留痕**：每个 roster 帧恰有一个状态（SELECTED / SELECTED_BY_OVERRIDE / NOT_ACCEPTED / SHA_DUPLICATE / NEAR_DUPLICATE_OF_CLUSTER_REP / CLUSTER_NOT_SELECTED_BY_STRIDE）。
- **R9 新族接入**：T9 第一批按 episode 成组、split 按 Lead 指示；HN 第二批按 episode 成组、只进 val。

### 2.2 抽样结果

| split | group | accepted | clusters | selected | overrides | status counts |
| --- | --- | ---: | ---: | ---: | ---: | --- |
| train | g_formal6_southA | 840 | 96 | 41 | 3 | CLUSTER_NOT_SELECTED_BY_STRIDE=55, NEAR_DUPLICATE_OF_CLUSTER_REP=744, NOT_ACCEPTED=12, SELECTED=40, SELECTED_BY_OVERRIDE=1 |
| train | g_formal6_staticW | 6 | 2 | 2 | 0 | NEAR_DUPLICATE_OF_CLUSTER_REP=4, NOT_ACCEPTED=6, SELECTED=2 |
| train | g_lm_pilot_staticE | 9 | 3 | 3 | 0 | NEAR_DUPLICATE_OF_CLUSTER_REP=6, NOT_ACCEPTED=9, SELECTED=3 |
| train | g_lm_ind_devSouth | 192 | 92 | 39 | 2 | CLUSTER_NOT_SELECTED_BY_STRIDE=53, NEAR_DUPLICATE_OF_CLUSTER_REP=100, NOT_ACCEPTED=3, SELECTED=37, SELECTED_BY_OVERRIDE=2 |
| train | g_lm_ind_reverseSouth | 210 | 66 | 30 | 5 | CLUSTER_NOT_SELECTED_BY_STRIDE=36, NEAR_DUPLICATE_OF_CLUSTER_REP=144, NOT_ACCEPTED=3, SELECTED=27, SELECTED_BY_OVERRIDE=3 |
| train | g_lm_ind_staticEtest | 6 | 2 | 2 | 0 | NEAR_DUPLICATE_OF_CLUSTER_REP=4, NOT_ACCEPTED=6, SELECTED=2 |
| train | g_geo_staticE | 9 | 3 | 3 | 0 | NEAR_DUPLICATE_OF_CLUSTER_REP=6, NOT_ACCEPTED=9, SELECTED=3 |
| train | g_lmf_dev_inner_south_0 | 102 | 41 | 20 | 2 | CLUSTER_NOT_SELECTED_BY_STRIDE=21, NEAR_DUPLICATE_OF_CLUSTER_REP=61, SELECTED=19, SELECTED_BY_OVERRIDE=1 |
| train | g_lmf_dev_static_high_0 | 23 | 12 | 12 | 0 | NEAR_DUPLICATE_OF_CLUSTER_REP=11, SELECTED=12 |
| train | g_lmf_dev_static_negative_0 | 21 | 8 | 8 | 0 | NEAR_DUPLICATE_OF_CLUSTER_REP=13, SELECTED=8 |
| val | g_lm_ind_north | 190 | 46 | 19 | 2 | CLUSTER_NOT_SELECTED_BY_STRIDE=27, NEAR_DUPLICATE_OF_CLUSTER_REP=144, NOT_ACCEPTED=3, SELECTED=19 |
| val | g_geo_north | 186 | 72 | 26 | 2 | CLUSTER_NOT_SELECTED_BY_STRIDE=46, NEAR_DUPLICATE_OF_CLUSTER_REP=114, NOT_ACCEPTED=3, SELECTED=25, SELECTED_BY_OVERRIDE=1 |
| val | g_lm_pilot_north | 190 | 49 | 20 | 2 | CLUSTER_NOT_SELECTED_BY_STRIDE=29, NEAR_DUPLICATE_OF_CLUSTER_REP=141, NOT_ACCEPTED=3, SELECTED=18, SELECTED_BY_OVERRIDE=2 |
| val | g_lmf_dev_inner_north_0 | 155 | 84 | 30 | 1 | CLUSTER_NOT_SELECTED_BY_STRIDE=54, NEAR_DUPLICATE_OF_CLUSTER_REP=71, SELECTED=30 |
| val | g_lmf_dev_static_low_0 | 21 | 15 | 15 | 0 | NEAR_DUPLICATE_OF_CLUSTER_REP=6, SELECTED=15 |

- 全量帧清单、逐帧 dHash/aHash/green/条件元数据与排除理由：outputs/perception/dev_annotations_20261104/dedup_sampling_report.json（sha256 b3c317a98712942b02fa138a04fb500285f7667d324f26f894f1cfd2572e168a）。
- T9 第一批 322 个 gate.accepted 帧中：inner_north 84 簇、inner_south 41 簇、static_high 12 簇、static_low 15 簇、static_negative 8 簇（静态三组因 accepted<32 取全部簇代表）。
- HN 最小 val：HN1 27 accepted → 13 帧、HN2 26 accepted → 11 帧（midpoint systematic；HN2 覆盖巡逻盒内“完全不可见”的代表视角）。

## 3. 标注规范、模式与视觉 QA

### 3.1 规范与模式

- 规范：configs/perception/landmark_annotation_spec_v2_1.json，status FROZEN_FOR_DATA，sha256 010255d931936457ded48db9b3691b69a31d6015f1f84fbbc6a659f10f766eac；校验器 scripts/validate_landmark_annotations.py（v1/v2/v2.1 分派）。v2.1 示例 pilot/v2_1_example_annotations.json 先跑 → PASS 5/5（示例 QA report sha256 d6348a402eeaad33fce88cae01a862d01d93068d8c5d95b3f3a7e93a0cdda6e5）。
- annotator.annotation_mode = BULK_CALIBRATED_WITH_FULL_VISUAL_QA；annotator_type = AGENT_PROXY；review_status = SELF_CHECKED；independent_of_model_dev = true；independent_of_detector_cue = false（参考点与绿色 cue 同源）。
- bbox 口径：可见目标结构本身（头/灯架 + 收分塔体 + 相连阶梯底座），不含场地平台/地面/画线/阴影；四边分别裁剪并记 truncated_edges + truncation_source；采集左右截断元数据与标注冲突时按 ANNOTATOR_OVER_CAPTURE 记录。
- 参考点口径：严格绿色 cue（g≥90, g−r≥25, g−b≥25，最大 4 连通域）且几何一致（隐含灯高 1.02–1.52 m、|u 差|≤6 px）才给 keypoint；否则 UNAVAILABLE + REFERENCE_TOO_SMALL，不猜坐标。远景绿 cue 不属于塔时记 confusers[] verified=false。
- bbox 生成方式：投影 aid 校准 draft（相机四元数全姿态投影灯点 u/v + 2·fx·tan(asin(half_width/d)) 宽度模型 + pilot 高度比 0.9），逐帧在 zoom 接触表上目视复核；geometry.bbox_source=PROJECTION_AID_CALIBRATED。这是披露的投影 aid，不是独立人工逐像素框。

### 3.2 视觉 QA 过程与发现

- train：6 张 4×3 zoom 接触表覆盖全部 108→105 个 present 帧 + 5 张 absent 校核接触表；另有 6 帧“边缘 sliver”单查表。
- val：同规则接触表 + HN1 原生 4×3（13 帧全部）+ HN2 2× 接触表（11 帧全部）。
- QA 发现并修正的系统性偏差：初版投影用仅 yaw 的方位公式，在 |相对方位| 大（>30°）的近/中距帧上 bbox 中心整体右移、宽度系统性偏大；改为全四元数投影灯点 u 与 2·fx·tan(asin(half_width/d)) 宽度模型后重新生成并复查（不合理的截断标记从 61 降到 29，避免过度截断）。修正前后均为看图前规则内的实现修正，不按模型分数选择。
- 复核结论：present 帧 draft 框普遍覆盖塔体且中心对准；近距框略松（±10–20%），远景小目标受像素尺度限制（见 §5）。未发现需要逐帧改框的严重错位；发现的 6 帧“目标中心恰在画面外、仅边缘 sliver 可见”改为 undecidable（见 §6）。
- 接触表与修正记录：outputs/perception/dev_annotations_20261104/tools/qa_sheets/、tools/corrections_dev.json（sha256 aa1d4aa7ea195d10bce5d89a09fd02f01310d3c70693096afe619fb30c0b6084）。

## 4. 组覆盖矩阵

### 4.1 train（160 帧）

| group_id | family | frames | present | absent | undecidable | keypoints | truncated | confusers(v/u) |
| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| g_formal6_southA | fam_south_A | 41 | 29 | 11 | 1 | 7 | 1 | 0/1 |
| g_formal6_staticW | fam_static_W_start | 2 | 2 | 0 | 0 | 0 | 0 | 0/0 |
| g_geo_staticE | fam_static_E_test | 3 | 2 | 1 | 0 | 2 | 0 | 0/0 |
| g_lm_ind_devSouth | fam_south_A | 39 | 37 | 0 | 2 | 16 | 5 | 0/2 |
| g_lm_ind_reverseSouth | fam_south_A | 30 | 0 | 30 | 0 | 0 | 0 | 0/0 |
| g_lm_ind_staticEtest | fam_static_E_test | 2 | 1 | 1 | 0 | 1 | 0 | 0/0 |
| g_lm_pilot_staticE | fam_static_E_dev | 3 | 2 | 1 | 0 | 2 | 0 | 0/0 |
| g_lmf_dev_inner_south_0 | fam_dev_inner_south | 20 | 20 | 0 | 0 | 16 | 3 | 0/3 |
| g_lmf_dev_static_high_0 | fam_dev_static_high | 12 | 12 | 0 | 0 | 12 | 0 | 0/0 |
| g_lmf_dev_static_negative_0 | fam_dev_static_negative | 8 | 0 | 8 | 0 | 0 | 0 | 0/0 |

### 4.2 val（134 帧；含 HN 最小子集）

| group_id | family | frames | present | absent | undecidable | keypoints | truncated | confusers(v/u) |
| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| g_geo_north | fam_north | 26 | 21 | 3 | 2 | 6 | 4 | 0/6 |
| g_lm_ind_north | fam_north | 19 | 14 | 4 | 1 | 6 | 2 | 0/4 |
| g_lm_pilot_north | fam_north | 20 | 15 | 5 | 0 | 7 | 2 | 0/4 |
| g_lmf_dev_hn1_confuser_0 | fam_dev_hn1_confuser | 13 | 0 | 13 | 0 | 0 | 0 | 13/0 |
| g_lmf_dev_hn2_occluder_0 | fam_dev_hn2_occluder | 11 | 11 | 0 | 0 | 0 | 0 | 0/0 |
| g_lmf_dev_inner_north_0 | fam_dev_inner_north | 30 | 30 | 0 | 0 | 7 | 2 | 0/16 |
| g_lmf_dev_static_low_0 | fam_dev_static_low | 15 | 15 | 0 | 0 | 15 | 7 | 0/0 |

### 4.3 条件覆盖

- train/val 的距离、|方位|、green 像素分箱与截断、keypoint 计数见 configs/perception/landmark_dev_label_lists_v1.json 的 condition_coverage；HN 批次在 condition_coverage.val_hn_second_batch 单列（construction-record 驱动，不适用距离/方位分箱）。
- 覆盖缺口（如实）：val 的“新走廊”只有 T9 inner_north 一条；HN1/HN2 为合成注入，不代表真实 arena 分布；场景遮挡/多候选歧义/真实相似结构仍未覆盖。

## 5. 正负、不可用、截断统计

| 指标 | train | val（含 HN） |
| --- | ---: | ---: |
| 帧数 | 160 | 134 |
| present | 105 | 106（含 11 GT_UNOBSERVABLE/全遮挡） |
| absent（TARGET_ABSENT） | 52 | 25（另有 13 SIMILAR_STRUCTURE=HN1） |
| undecidable | 3 | 3 |
| GT_UNOBSERVABLE（OCCLUDED） | 0 | 11 |
| keypoint 可用（MANUAL_APPROX） | 56 | 41 |
| reference UNAVAILABLE | 49 | 65 |
| 截断（四边并集） | 9 | 17 |
| 截断边计 | left 9/right 0/top 0/bottom 0 | left 0/right 10/top 0/bottom 7 |
| confusers（verified/unverified） | 6（0/6） | 43（13/30） |

- train 负例 52 帧全部 TARGET_ABSENT：其中 g_lm_ind_reverseSouth 30 帧整族“塔在相机身后”（航向反向），g_lmf_dev_static_negative_0 8 帧（相机朝后、画面仅柱/墙结构），其余为线路上目标出视野段。train 不含 SIMILAR_STRUCTURE/GT_UNOBSERVABLE（HN 只进 val）。
- val 负例构成：TARGET_ABSENT 12、SIMILAR_STRUCTURE 13（HN1 合成注入 confuser，verified=true，verification_source=EXTERNAL_EVIDENCE）、undecidable 3；另有 GT_UNOBSERVABLE 11（HN2），不是负例、不得计入 TN。
- 像素尺度限制：320×240、fx=160 px、cx=160 → 1 px≈0.358°；远景（>10 m）塔仅约 10–20 px，bbox/keypoint 的像素级不确定性显著大于中近距；不得把本标注的 bbox/keypoint 差异写成“亚像素/实物级精度”。

## 6. 争议、歧义与处理记录

| # | 记录 | 处理 |
| --- | --- | --- |
| C1 | 6 帧（train 3：devSouth×2 + g_formal6_southA×1；val 3：北走廊×3）目标中心恰在画面外、画面只余边缘 sliver，无法判定 sliver 是否目标 | 标 present=false + undecidable=true + ANNOTATOR_UNDECIDABLE，不进正/负分母；不写成 TARGET_ABSENT |
| C2 | 绿色 cue 在多帧来自非塔结构（绿顶/绿窗/灯柱等），推断隐含灯高 2.5–5.5 m 或 u 偏差大 | 不标 keypoint（UNAVAILABLE/REFERENCE_TOO_SMALL），记 confusers[] verified=false（不臆造 bbox，只有 green_cue 点）；不为这些绿 blob 声称身份 |
| C3 | 远景北走廊可见“高的绿色顶部结构”与中央塔投影 u 仅差数 px | 按几何一致性判为非塔绿 cue，keypoint 置 UNAVAILABLE；作为 HN1 类干扰的未验证候选记录，不作为相似结构结论 |
| C4 | 初版投影模型在大偏航角近距帧 bbox 中心偏移/过宽 | 改为全四元数投影 + asin 宽度模型，重新生成并复查；记录在 §3.2 |
| C5 | HN1/HN2 为合成注入（非 arena 资产） | HN1 confuser verified=true 但 verification_note 明示 synthetic/not arena-native/不代表真实分布；HN2 标 GT_UNOBSERVABLE 并附构造记录 sha |
| C6 | 参考点与绿色 cue 同源（循环性） | independent_of_detector_cue=false；不得用本标签验证绿色 seed 检测器的 anchor 精度 |

## 7. 代理标注边界（必须与结果一起读）

1. 单代理（AGENT_PROXY）标注 + 自检（SELF_CHECKED），没有人类/专家独立标注、仲裁或 HUMAN_REVIEWED/ADJUDICATED；同一执行者既做数据/标注又可能参与后续模型/评测开发 → 只能声称流程隔离 + hash 承诺，没有统计独立性。
2. bbox 是“投影 aid 校准 + 全量目视复核”，不是逐帧人工像素框；bbox_source=PROJECTION_AID_CALIBRATED。参考点由颜色 cue 辅助（COLOR_CUE_ASSISTED），anchor 残差不是独立精度证据。
3. 本标签仅用于 dev 训练/选模；不得作为 final/sealed 评测标签，不得把 dev 标签结果写成模型效果、板端或导航验收；也不能把 dev 指标当作感知能力达标。
4. 未查看 final 池标签用于本任务决策：早期仅为确认 v2.1 schema 读取过 landmark_final_annotations_20261104/labels_v1.json 的文件头 2 条记录（格式了解），dev 选帧/标注/修正均未使用其内容；final 池标签/结果未参与任何阈值或规则选择。
5. 未 git commit/push；未改 outputs/sensor_shadow/ 原始帧；未安装训练依赖、未跑训练。

## 8. 未完成 / 留给后续（HN 剩余、T9、datafreeze）

- HN 第二批剩余帧：59 个 published RGB（53 gate.accepted）中本轮只标 24 帧（HN1 13 / HN2 11）；剩余 29 个 gate.accepted HN 帧未标注（capture 报告尚未到，构造记录已在 cases JSON）。若 datafreeze 要求 val HN 全覆盖，需再补 29 帧（同规则追加，仅 val）。
- HN 覆盖边界：HN1/HN2 均合成注入（现场施工记录），不代表真实 arena 的相似结构/遮挡分布；HN1 verified=true 只表示“确实是注入的 confuser”，不是“真实相似塔已确认”。
- T9 报告：本轮已纳入 T9 第一批 5 族；capture 报告 docs/reports/perception/capture_dev_20261104/ 尚未发布，故本报告只按 cases/observations/构造记录引用。
- datafreeze 待办：把本清单（landmark_dev_label_lists_v1.json）与标签 sha 纳入 dev 冻结 v3；确认 val 134 帧（110 系统 + 24 HN）与 train 160 帧的 split 归属；外部产物索引登记 labels/hn/qa sha。
- 帧级事件：6 帧 undecidable 已在 labels 与清单里显式列出，训练必须排除（不得当 background）；11 帧 GT_UNOBSERVABLE 同样必须排除损失。
- 可复现性：标注工具（draft 构建/QA 接触表/HN 构建/label 构建/清单生成）在 ignored outputs/perception/dev_annotations_20261104/tools/ 下，脚本 sha 未入 Git；仓库内仅 scripts/landmark_dedup_sampling.py 与清单/hash/统计。若 datafreeze 要求工具入 Git，需 Lead 扩大写域后另行提交。

## 9. 验证命令与结果（本轮实际运行）

~~~
# 去重/代表抽样（main freeze + T9 batch1）
& E:\isaac\env_isaaclab\Scripts\python.exe -u scripts/landmark_dedup_sampling.py --repo . --train-budget 160 --val-budget 110 --extra-freeze outputs/perception/dev_annotations_20261104/dev_extra_groups_20261104.json
# 标签构建 + v2.1 校验
& E:\isaac\env_isaaclab\Scripts\python.exe -u outputs/perception/dev_annotations_20261104/tools/build_dev_labels.py
& E:\isaac\env_isaaclab\Scripts\python.exe scripts/validate_landmark_annotations.py --annotations outputs/perception/dev_annotations_20261104/labels_train.json --root . --overlay-dir outputs/perception/dev_annotations_20261104/overlays_train --output outputs/perception/dev_annotations_20261104/qa_train.json
& E:\isaac\env_isaaclab\Scripts\python.exe scripts/validate_landmark_annotations.py --annotations outputs/perception/dev_annotations_20261104/labels_val.json --root . --overlay-dir outputs/perception/dev_annotations_20261104/overlays_val --output outputs/perception/dev_annotations_20261104/qa_val.json
# 全量单测
& E:\isaac\env_isaaclab\Scripts\python.exe -m pytest -q   # 969 passed in 51.47s（2026-11-04 本轮收尾运行）
~~~

| 检查 | 结果 |
| --- | --- |
| train 标签 v2.1 格式 QA | PASS 160/160，0 error / 0 warning（qa_train.json sha256 113cff347252eb14b3a5787590e8e6431155169de6f8b9b8a5822b702bdbc1fc） |
| val 标签 v2.1 格式 QA（含 HN） | PASS 134/134，0 error / 0 warning（qa_val.json sha256 ceed8b1bdd4ef1d5bb93dceac15f3fe23f9aac85b918ac5b38014768c06e765f） |
| v2.1 校验器示例 | PASS 5/5 |
| 全量 pytest | 969 passed in 51.47s |
| 跨组/跨 split sha 重复 | 0 |
| 本任务范围 | 无训练/推理/板端/SITL/实飞/导航；未提升任何 Gate |

格式 QA 只证明标签文件自洽合法；不证明标注语义是专家真值。

## 10. 证据清单（sha256）

| 文件 | 说明 | sha256 |
| --- | --- | --- |
| outputs\perception\dev_annotations_20261104\labels_train.json | train 标签（ignored） | 01977b9fea97c58bcdda2c6c301763ac52113bcc411a23094924b917ec08d2df |
| outputs\perception\dev_annotations_20261104\labels_val.json | val 标签（ignored，含 HN 24 帧） | c3944e081d09d8a1d8398a0fb01a854580b116d004d8dcf14dacfa7f9493520d |
| outputs\perception\dev_annotations_20261104\labels_hn_val.json | HN 最小 val 子集标签（ignored） | 3dff20b6d99249a0cf71b7703eddea08ff223c8e2ff3d0466acfefc6ce283dc2 |
| outputs\perception\dev_annotations_20261104\labels_manifest.json | 标签 manifest | 34fd3fd0f525423fee41b7ce6217b8fbfdadcb1b7909ecbb7c1c4e03401d4b0a |
| configs\perception\landmark_dev_label_lists_v1.json | train/val 明确帧清单（入 Git） | befbbea1b587261ed861a081706fe44a8a761aa90b04743fb137ddbd85c27701 |
| configs\perception\landmark_annotation_spec_v2_1.json | 标注规范 v2.1（FROZEN_FOR_DATA） | 010255d931936457ded48db9b3691b69a31d6015f1f84fbbc6a659f10f766eac |
| scripts\landmark_dedup_sampling.py | 去重/代表抽样脚本 | 8c5b2cde820b4928af11bbe452ed35edc55c01d2a465a65fe49660b11e92100c |
| outputs\perception\dev_annotations_20261104\dedup_sampling_report.json | 全量帧清单/排除理由/覆盖统计 | b3c317a98712942b02fa138a04fb500285f7667d324f26f894f1cfd2572e168a |
| outputs\perception\dev_annotations_20261104\selection_train.json | train 抽样清单 | 334870604bd4f67611f05b22b77d40a36b71c6b4543cfdeb90899afd10b486d7 |
| outputs\perception\dev_annotations_20261104\selection_val.json | val 抽样清单 | 129b95e021d24e8dffdc694d19871debfb8c6028640bb5e2bb1eb74363495dae |
| outputs\perception\dev_annotations_20261104\selection_hn.json | HN 最小 val 抽样清单 | 17627ea4a45cd18ad3b3d2656755b0b194c39d49dbeae37237a5196fbc4609d6 |
| outputs\perception\dev_annotations_20261104\dev_extra_groups_20261104.json | T9 第一批 dev 辅助组描述 | 8cbcdf8937b2c8635a20839fbcbd80fd48bbcf501047290a9076431f40232acc |
| outputs\perception\dev_annotations_20261104\tools\corrections_dev.json | 视觉 QA 修正（边缘 sliver 6 帧 → undecidable） | aa1d4aa7ea195d10bce5d89a09fd02f01310d3c70693096afe619fb30c0b6084 |
| outputs\perception\dev_annotations_20261104\qa_train.json | v2.1 格式 QA（train） | 113cff347252eb14b3a5787590e8e6431155169de6f8b9b8a5822b702bdbc1fc |
| outputs\perception\dev_annotations_20261104\qa_val.json | v2.1 格式 QA（val，含 HN） | ceed8b1bdd4ef1d5bb93dceac15f3fe23f9aac85b918ac5b38014768c06e765f |
| docs\reports\perception\annotation_verify_20261104\pilot\v2_1_example_qa_report.json | v2.1 校验器示例 | d6348a402eeaad33fce88cae01a862d01d93068d8c5d95b3f3a7e93a0cdda6e5 |
| configs\scenarios\landmark_dev_cases_v2.json | T9/HN 采集 case + 注入构造记录 | 10b55544e4d6565dd1520e699f7c51aaded8bc6fc305f452d3000c566f2db1bc |
