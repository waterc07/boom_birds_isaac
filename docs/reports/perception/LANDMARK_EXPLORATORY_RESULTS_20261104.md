# 地标学习探索实验结果：有界训练、阈值冻结与一次性 exploratory 评价（2026-11-04 二阶段）

> **状态：** EXPLORATORY_EVIDENCE / BASELINE（内部有界研究；**不是**能力认证、不是 sealed final、不是板端/导航验收）
> **来源章节：** V2.2 §7.4/§7.5/§7.6/§9.1/§11.1/§20.2/§20.11；任务定义 `LANDMARK_TASK_AND_EXPERIMENT_DEFINITION_20261104.md`（E1–E5 / C1–C8 分离）
> **证据域：** 隔离训练环境 + 仿真域 dev 验证集 + 仿真域 exploratory 一次性评价；RKNN/板端/实机/SITL/HIL 均 NOT RUN
> **最后核对：** 2026-11-04

本文只报告**实际执行**的链路、实测数字与停止原因。目标是把“方案已写”推进到“实验已跑并如实报告”；不宣称模型效果达标、不称认证通过。

---

## 0. 结论先行

| 项 | 结论 |
| --- | --- |
| 探索实验（E1–E5） | **全部执行完成**：数据标注、工具链、隔离环境、有界训练（3 seed）、阈值冻结、一次性 exploratory 评价 |
| 有界训练 | 3 seed × 60 epoch（协议上限 100；时间盒内固定 60），仅用 val 选模；选中 **seed1/last**，val joint **0.579（55/95）** |
| 阈值冻结 | **仅在 val** 冻结：tau_det=tau_conf=**0.605476**（val precision 0.9508=58/61）、tau_px=3.0、tau_iou=0.3；tau_margin=0.1 PROPOSED（val 无多候选帧） |
| 一次性 exploratory final | **已执行且只执行一次**（279 帧）：presence P1.000/R0.916、reference coverage 0.284、joint 窄口径 **71/238=0.298**、identity P1.000（但池内无已验证 HN1 → 不可作身份认证） |
| 计划效果门（joint≥0.80、coverage≥0.90 等） | **未达到**；按“不回调”规则停止，不再用该池调参 |
| 能力认证（C1–C8） | **INCOMPLETE**：许可分发未决、无独立人工标注、无未触碰 sealed final、无板卡/真实相机/重复性 |
| 工程链路 | 环境/GPU smoke/过拟合/ONNX/训练/阈值/一次 final 全部跑通；发现并修复标签坐标域 bug（旧 30 epoch 判 INVALID） |

**一句话：** 链路已经真实跑通并产出可复现的 exploratory 数字；模型效果**明显未达计划门限**，认证条件仍 INCOMPLETE，本结果只能用于内部探索与下一步决策。

---

## 1. 许可决定与 E/C 判定

- 用户 2026-11-04 授权：主候选 YOLOv8n-pose（AGPL-3.0）**仅用于内部有界研究/评测**，对外分发另行决策；不写成许可已解决或法律结论（记录于 `configs/perception/landmark_model_freeze_v1.json#license` 与本节）。
- E 判定：E1 PASS（内部研究授权）；E2 PASS（dev train/val + exploratory test 标注完成）；E3 PASS（标签转换/推理解码/分层评价/分母审计通过）；E4 PASS（隔离 venv + GPU smoke）；E5 PASS（协议与阈值在训练前/val 后冻结，final 一次）。
- C 判定：C1 INCOMPLETE（分发未决）、C2 INCOMPLETE（单代理标注）、C3 INCOMPLETE（无未触碰 sealed final）、C4 INCOMPLETE（false-match 分母 41 负例，远不足以认证 0.5%）、C5 UNKNOWN（无 RK3576）、C6 INCOMPLETE（合成域）、C7 INCOMPLETE（单次）、C8 INCOMPLETE。

---

## 2. 数据与封存（本轮完成）

| 项 | 结果 |
| --- | --- |
| dev 划分 v3 | canonical `bc037e30…`；train 10 组/1475 帧（1418 accepted）、val 7 组/816 帧（795 accepted，5 family + HN1/HN2）、test 0、excluded 9 组/1107 |
| 标注 | spec v2.1（`010255d9…` FROZEN_FOR_DATA）；train 160 帧/val 134 帧/HN 24 帧；代理标注（AGENT_PROXY+SELF_CHECKED），bbox 为投影 aid+全帧目视复核，参考点与绿色 cue 同源（循环性已披露） |
| final 探索池 | 279 帧完整标签（`7115ee04…`）：present 238 / absent 41；参考可用 218 / 不可用 20；四边截断 48（right 24 / bottom 42）；HN1/HN2 均 0（池内无已验证相似结构、无完全遮挡） |
| 暴露登记 | `configs/perception/landmark_exposure_registry_v1.json`：26 组 exposed_development、6 组 exploratory、**0 untouched**；34 帧试点→annotation calibration，6/6 族同组污染；**final 池整体降级 exploratory，不称 sealed** |
| 泄漏审计 | PASS：train-val / exploratory-dev sha 0、像素近重复 0、同轨迹跨 split 0；family/group/连续帧 0 泄漏 |
| 外部产物 | 16 数据集/3695 帧 PNG 可读、逐帧 sha 与清单一致；仓库外备份仅为建议，未上传 |
| 新采集 | 375 accepted RGB（batch1 322：inner_north/inner_south/static_high/static_low/static_negative；HN1 27/HN2 26）；GUI 可见前台、D3D12，未回退 headless |
| 重要更正 | 采集发现 map-native 带绿灯相似结构 MS1（≈(3.0,4.0)）→ **U1/U2 唯一性假设被证伪**；identity 必须依赖多候选拒绝/场景先验，本轮结局按此记录 |

---

## 3. 执行链与工程证据（实测）

| 阶段 | 结果（证据域） | 关键数字/证据 |
| --- | --- | --- |
| 0 隔离环境 | PASS | `.venv/landmark-train`：torch 2.7.0+cu128（sm_120）、ultralytics 8.2.0、onnx 1.22.0、onnxruntime 1.31.1；Isaac venv 未改；修复 numpy 2.x→1.26.4 兼容 |
| 1 GPU/kpt smoke | PASS | 前向 (1,8,8400) finite、峰值 39.2 MiB；1 epoch loss finite、峰值 215.9 MiB |
| 2 小样本过拟合 | PASS（工程） | 修正标签+pretrained：total 10.00→2.51（0.25×）、pose 0.189→0.041、kobj 0.767→0.181 |
| 3 ONNX | PASS（主机数值） | opset18、导出 sha `ca28a5c9…`；torch vs ORT raw max_abs_diff 1.22e-4；loader 坐标闭环 0.0003 px；训练后 .pt vs .onnx 原生 predict 一致（box≤2 px、kpt≤4.67 px 源图） |
| 4 pilot | PASS（预算探测） | 3.677 s/epoch、峰值 1967.6 MiB；val joint 0.432（20 epoch 早段快照） |
| 5 有界训练 | 完成（v2 协议） | 3 seed × 60 epoch（协议上限 100；固定 60 属时间盒预注册 delta），3.0–3.2 s/epoch、峰值 ~2.0 GiB；joint：seed0 0.484、**seed1 0.579**、seed2 0.442（最差已报）；选模仅用 val |
| 6 阈值冻结 | 完成（仅 val） | 见 §0；tau_conf 取 val identity precision≥0.95 的最小分数（0.605476 → 58/61=0.9508, recall 0.611）；tau_px=3.0、tau_iou=0.3；tau_margin PROPOSED |
| final | 一次性 exploratory | 见 §4；脚本拒绝覆盖、未回调、未重跑 |

**关键工程发现（保留为证据）**：YOLO txt 标签坐标域 bug——旧转换把 640 模型画布归一化直接写 txt，导致二次 letterbox（keypoint y ±58 px、bbox h 0.75×）。用 ultralytics 8.2.0 loader 复现（delta_y=+3.25 px）→ evaltool 修复为源图归一化 + 幂等 marker + fail-loud → 重建数据集与 canonical 导出**逐字节一致**（157/157、120/120）、loader delta 0.0003 px。**bug 存在时的 30 epoch 过拟合运行判 INVALID**，不作方法/数据结论。

**RKNN**：UNKNOWN / NOT RUN——无 RK3576 板卡；RKNN-Toolkit2 为专有许可且未安装；ONNX 主机导出不证明板端 INT8/延迟/热稳定。

---

## 4. 一次性 exploratory final 评价（只读一次，279 帧）

- 输入：模型 `last.pt`（sha `d4ffe49a…`，val 选定 seed1）、阈值来自 val（`configs/perception/landmark_model_freeze_v1.json`，sha `16618b7c…`）、标签 `7115ee04…`、spec v2.1；命令与完整输出 hash 记录于 `configs/perception/landmark_final_eval_protocol_v1.json#execution`。
- 首次执行因 torch 2.7 `weights_only` 默认在**推理前**失败、未产生指标；加 `TORCH_FORCE_NO_WEIGHTS_ONLY_LOAD=1` 后成功——这是**唯一一次**成功读取，未回调。

| 指标 | 分子/分母 | 结果 |
| --- | --- | --- |
| presence | TP218/FP0/FN20/TN41 | precision **1.000**、recall **0.916**；UNKNOWN/REJECTED 0 |
| reference coverage | 62/218 | **0.284**（失败 156：wrong anchor 119 + no keypoint 37） |
| false-reference rate | 0/20 | **0.000** |
| anchor 误差（全部输出） | n=181 | median **3.72 px** / P90 5.96 / max 8.44 |
| anchor 误差（正确子集） | n=62 | median **1.95 px** / P90 2.82 |
| bearing 误差（全部/正确） | n=181/62 | median 0.546°/0.300°，P90 1.19°/0.64° |
| identity | claims 218，correct 218 | precision **1.000**、FMR 0/41；**但池内无已验证 HN1/相似结构负例 → 不是身份认证** |
| joint（窄口径） | 71/238 | **0.298**；覆盖率 1.0；失败 presence 20 + reference 147 |
| bbox IoU（辅助） | n=218 | median 0.682 / P90 0.747 |
| 最差条件 | — | family joint：lmf_near 3/23=0.130；presence recall：backoff 60/76=0.789；scale TINY recall 19/34=0.559、ref coverage 1/15=0.067；FULL visibility joint 56/190=0.295 |

计划效果门（joint≥0.80、reference coverage≥0.90 等）**全部未达到**；joint 失败主要由 reference（147）主导，presence 已接近门限但远景小目标仍有明显漏检。

---

## 5. 停止原因与不声明

- **停止原因**：预注册效果门未达到 → 按“final 不回调、不重跑、不调参”停止，不追加 seed/epoch 或阈值搜索来“凑结果”；认证条件 C1–C8 未闭合。
- **不声明**：不声明模型效果达标、不是 sealed final、不是认证、不是板端或导航能力、不是真实赛场分布；RKNN/板端保持 UNKNOWN。
- **限制**：单代理代理标注（非人工独立）、bbox 为投影 aid、参考点与绿色 cue 同源、final 池已被试点污染（6/6 族）、HN1/HN2 在 final 池为 0、HN 仍有 29 accepted 帧未标、合成资产/相机、无重复性统计、false-match 分母仅 41。
- **U1/U2 证伪**：MS1 存在意味着单类+绿色 cue 不能建立身份；identity 的 1.000 只是该池无相似结构负例下的单地标口径，不得外推。

---

## 6. 认证所需（不自动开始）

1. 许可分发决策（AGPL/商业/切换）；2. ≥2 名独立人工标注 + 仲裁；3. 全新未触碰 sealed final（≥3 新族、200–400 帧，含 HN1/HN2）；4. 充足负例分母以认证 false-match；5. RK3576 板端（自定义 1-kpt RKNN INT8/延迟/热稳定）；6. 真实相机/场地分布；7. 多 session 重复性；8. 与 V2.2 合同/规则/版本矩阵对齐。

---

## 7. 证据与复现

| 内容 | 路径 |
| --- | --- |
| 训练执行报告 | `docs/reports/perception/training_20261104/TRAINING_20261104.md` |
| 环境证据 | `docs/reports/perception/training_20261104/ENV_20261104.md` |
| 阈值冻结证据 | `docs/reports/perception/training_20261104/threshold_freeze_val_20261104.json` |
| 模型/阈值冻结清单 | `configs/perception/landmark_model_freeze_v1.json`（sha `16618b7c…`） |
| 训练协议预注册 | `configs/perception/landmark_train_protocol_v1.json` |
| final 评价协议（含执行记录） | `configs/perception/landmark_final_eval_protocol_v1.json` |
| final 输出（ignored） | `outputs/perception/final_exploratory_eval_20261104/{metrics.json,predictions.jsonl}`（sha `a01c08ec…`/`8cdfe558…`） |
| 数据冻结 v3/暴露/泄漏 | `configs/perception/landmark_split_freeze_v3.json`、`landmark_exposure_registry_v1.json`、`docs/reports/perception/dataset_freeze_20261104/` |
| 采集与 HN 构造 | `docs/reports/perception/capture_dev_20261104/CAPTURE_DEV_20261104.md` |
| 标注与 QA | `docs/reports/perception/annotation_verify_20261104/`（FINAL_EXPLORATORY / DEV_TRAIN_VAL / spec v2.1） |
| 工具链 | `src/boom_birds/evaluation/landmark_yolo.py`、`landmark_metrics.py`、`scripts/evaluate_landmark_yolo.py`、`TRAINING_EVAL_TOOLING_20261104.md` |

复现命令（节选）：

```powershell
# 训练（详见 training 报告）
& .venv/landmark-train/Scripts/python.exe -c "..."   # overfit / pilot / bounded_v2 脚本在 outputs/landmark_train/scripts/
# 一次性 exploratory final（唯一一次，勿重跑）
$env:TORCH_FORCE_NO_WEIGHTS_ONLY_LOAD=1
& .venv/landmark-train/Scripts/python.exe scripts/evaluate_landmark_yolo.py --model outputs/landmark_train/runs/bounded_v2/seed1/bounded_1/weights/last.pt --labels outputs/perception/final_exploratory_20261104/labels_v1.json --split test --images outputs/sensor_shadow/lm_final_candidate_20261104_sensor/images --output-dir outputs/perception/final_exploratory_eval_20261104 --tau-iou 0.3 --tau-px 3.0 --tau-conf 0.605476 --tau-det 0.605476 --tau-margin 0.1
```
