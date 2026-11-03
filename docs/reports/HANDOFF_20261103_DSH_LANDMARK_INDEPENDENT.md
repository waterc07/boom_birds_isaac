# 交接：地标消费者独立评价与有限改进（shadow，2026-11-03）

## 状态

- **PASS（软件/冻结/独立核验/交接）**；**算法未达标、未改善**。
- 新 sealed test：49 帧 / 4 families（27 正、22 负）；frame-level。
- baseline（旧单模板）：presence TP12/FP0/FN15/TN22，precision 1.0、recall **0.444**；localization TP 0/8，bearing error mean **10.44°**（阈值 5°）。
- improved（多视角+anchor）：presence TP0/FP2/FN27/TN20，precision/recall **0**；localization TP 0；比基线**更差**。
- 独立核验 PASS 30 checks；`pytest -q` **801 passed**；文档审计 PASS。
- 不接控制、不提升 Gate、无真实硬件/PPO/SITL/HIL/实机。

## 1. 旧数据独立性 / TP 修订

- 旧 route_0/route_1/reset_0/reset_1 的 waypoints、start/goal **完全相同**；g4/5/6 与 g3 同 seq 相机位置差≤0.006 m、图像 MAE 0.5–8.6；属同轨迹重复采集。
- 旧 846 RGB exact SHA 重复 0，但 hash 不同不代表轨迹独立；旧 36 帧测试降级为开发/历史回归。
- 旧标签只有 presence；旧 TP = 任意检测，无 bbox 验证；旧 bearing = bbox 中心角度，不是固定塔特征。旧 recall 0.5 **不是**独立定位结果。
- 审计：`docs/reports/perception/DSH_LANDMARK_INDEPENDENCE_AUDIT_20261103.md`、
  `docs/reports/perception/dsh_independence_audit_20261103.json`。

## 2. 新数据 / 标签 / 冻结

- 新采集 5 个前台 GUI episode：`dev_south_new`（development）、`test_reverse_south`、`test_north_0`、`test_static_oblique`、`test_static_away`（sealed test）；全部 SUCCESS，completion 存在、无 error。
- pilot 静止视角（center/left/away）作为 development。
- 采集计划 v1/v2（`independence_plan_v1/v2.json`）：v2 在只看目标可见性、未看检测结果时修正了采样尾部窗口；v1 保留。
- labels：`configs/perception/landmark_independent_labels_v1.json`（49 test / 30 dev；bbox/绿灯参考点仅 9 个 localization 子集；代理人标注，不是用户专家复核）。
- 模板：baseline 旧塔模板；improved 3 个 **development-only** 模板（pilot center/left + dev route near）；test 图像未用于模板/阈值。
- 正式 freeze：`configs/perception/independent_freeze_v3.json` sha256 `6493f653…`；code commit `1ecbb9c`；包含源码/输入/模板/labels/划分/阈值/IoU/bearing/expected。

## 3. 算法与结果

- 改进 1：development-only 多视角模板库；改进 2：模板绿灯 anchor 映射为图像参考点 bearing；阈值 0.65 只用 dev 选择，测试后未调。
- baseline：北向/静态斜视有 presence 检测；reverse 方向 0/12；presence precision 1.0/recall .444。
- improved：所有测试正例未达阈值；north/reverse 各 1 FP（非目标结构 score≈0.65）；presence precision/recall 0。
- localization：baseline IoU 多数可接受但 bearing error 9.1–11.5°（>5°），TP0/8；improved 无 accepted detection，bearing 无独立证据。
- 失败样例：`docs/reports/perception/evidence_20261103_independent_landmark/`
  - `correct_presence_bearing_error.png`
  - `localization_bearing_error.png`
  - `miss_reverse.png`
  - `false_positive_improved.png`
  - `occluded_unavailable_ref.png`
  - `unknown_rejected.png`

## 4. 时间 / reset

- 复用 `SIM_UPDATE_SAMPLE_TIME` / exposure `UNKNOWN`；旧 v1 输入归一化 legacy；age 非完整采集延迟。
- generation 变化重置 gate/sequence/cache；结果带来源 frame/payload hash、generation/context/有效期/算法/模板/阈值/拒绝原因；shadow/ORACLE 分离。
- 未重跑接触/动作故障矩阵；单测覆盖旧帧/重复/过期/generation/context/truth 隔离。

## 5. 独立核验

- `scripts/verify_independent_landmark.py` → `docs/reports/perception/dsh_independent_landmark_verify_20261103.json`：PASS 30 checks；重算 presence/localization/bearing/family 分母、hash、时间、shadow 边界。
- `pytest -q` 801 passed；文档审计 PASS；freeze/source/label/template/input hash 均检查。
- PASS 仅表示软件/评价/核验闭合，不表示算法/导航能力达标。

## 6. 失败与适用边界

- 新 test 只有 49 帧、4 families；positive 27、localization 8 可评估；**样本不足**，不能下统计充分结论。
- improved 过拟合开发视角：模板库不覆盖 reverse/north 视角，阈值 0.65 拒绝正例；困难负例导致 2 FP。
- 只有单自然塔、无区域图/地标数据库/SLAM/VIO/定位/控制；无目标距离；相机参数仍 PROPOSED。
- 未接控制、未启动 PPO/真实相机/板端/PX4/SITL/HIL/实机；不提升 Gate；规则/BOM/PX4 保持 UNKNOWN/RULE-CHECK。

## 7. 是否可进入“区域/地标关联 shadow”

**不可以。** presence 尤其 reverse 方向不足；localization TP 0、bearing 误差超门限；没有区域拓扑/多假设/关联合同。应先扩大独立视角与标签覆盖、补齐地标数据库/区域拓扑，再谈关联。

## 8. 下一步最少实物参数/测量

- OV9782 实际镜头/模组、FOV/分辨率/像素格式、CSI lane、帧率、曝光范围/畸变；
- 相机安装基准、光轴/机体外参、相机-IMU/飞控时间戳同步；
- 若使用距离：VL53L8CX 接口/8×8 zone/更新率/量程/反射率/相机视场映射；
- RK3576 CSI/驱动采集、真实端到端时间戳/延迟；
- 多视角/遮挡/尺度/困难负例的独立标注与区域拓扑草案。

## 9. 证据/提交

- 报告：`docs/reports/perception/DSH_LANDMARK_INDEPENDENT_20261103.md`
- 交接：本文件
- 审计：`DSH_LANDMARK_INDEPENDENCE_AUDIT_20261103.md`、`dsh_independence_audit_20261103.json`
- 核验：`dsh_independent_landmark_verify_20261103.json`
- freeze/labels/templates：`configs/perception/independent_freeze_v3.json`、`landmark_independent_labels_v1.json`、`independent_templates/`
- 证据：`docs/reports/perception/evidence_20261103_independent_landmark/`
- 原始数据：`outputs/sensor_shadow/lm_independence_sensor/`、`outputs/perception/independent_v3_baseline/`、`independent_v3_improved/`（gitignored，hash 归档）
- 分支 `codex/bb22-contact-envelope`；未推送；用户修改保留。


## 10. 版本化失败/修正

- v1 freeze（source `18ae544`）后 improved 首次运行因注入检测器初始化残留 `Path(None)` 失败；修复提交 `f3f8b23`，v1 不作为正式评价。
- v2 freeze 后独立核验发现 localization 统计误用 NOT_DETECTED 候选 bbox/bearing；修复提交 `1ecbb9c`，生成正式 v3；修正不涉及模板/阈值/门限，测试未用于调参。
- v1/v2 freeze 与失败保留；正式结果/核验仅引用 v3。
