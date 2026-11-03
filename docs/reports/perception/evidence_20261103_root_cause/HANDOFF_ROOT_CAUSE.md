# 交接：自然塔感知失败根因诊断与方法去留（2026-11-03）

## 状态

- **诊断/去留评审完成**；**无确认实现缺陷、无生产代码修复**；旧 freeze/正式结果保留。
- 49 帧已降级为**已暴露诊断数据**，不再是封存测试；本包没有为了增加运行次数采集新 Isaac 数据。
- **方法决策：停止继续堆模板**，转向“几何 + 绿灯 anchor”下一方法；本包不实现下一方法。

## 1. 关键证据

- 坐标/对象：
  - label bbox center vs green: 0.28–5.06°；
  - baseline 接受检测 center vs label bbox center: 5.65–11.74°；
  - baseline center vs green: 9.13–11.46°；
  - baseline 无物理 anchor，旧 green-bearing 不直接可比；但预测框中心偏移真实存在。
  - 图像全 320×240、内参一致；无 crop/letterbox；合成 anchor 尺度 .5/.8/1.0 通过。
- 消融：
  - B：当前代码 + 旧模板 + 旧参数 .55 对 613 帧与旧 baseline **0 状态不一致** → 排除“新代码改坏旧路径”。
  - C：center 单模板 .65 TP0/FP2；left 单模板 .65 TP0/FP0；route near 单模板 .65 TP0/FP0；.55 时 center TP15/FP22，route TP0/FP4。
  - D：多模板 max 在 .65 TP0/FP2；.55 TP15/FP22；center 模板主导 43/49，left 0/49。
  - E：真实测试无正确候选，anchor 精度不可评估；仅坐标合成测试通过。
- 阈值：
  - improved .55 TP15/FP22；.60 TP4/FP20；.65 TP0/FP2；.70 TP0/FP0；无好工作点。
  - 9 个 bbox 可评估正例：4 个 target-overlap 候选 .528–.592 低于 .65，5 个 .342–.499；0 个正确候选达到 .65。
  - 18 个正例只有 presence 标签，不具备目标重叠真值。
- 尺度：target 宽最高 1.82× 模板最大；额外诊断尺度到 2.0 只把 north s192 提到 .627，reverse 仍 .34–.43。
- gate：49 测试帧 0 UNKNOWN/0 REJECTED；拒绝仅 warmup；不构成根因。
- 根因树/方法决策详见 `DSH_LANDMARK_ROOT_CAUSE_20261103.md`。

## 2. 文件/提交

- 诊断脚本：`scripts/diagnose_landmark_failure.py`
- 独立核验：`scripts/verify_landmark_root_cause.py`
- 根因 JSON：`docs/reports/perception/dsh_landmark_root_cause_20261103.json`
- 核验 JSON：`docs/reports/perception/dsh_landmark_root_cause_verify_20261103.json`
- 候选表：`docs/reports/perception/evidence_20261103_root_cause/candidates.jsonl`
- 证据：`evidence_20261103_root_cause/`（模板、wrong candidate、target candidate below threshold、baseline center offset、root cause/verify/labels）
- 旧报告勘误：`docs/reports/perception/DSH_LANDMARK_INDEPENDENT_ERRATA_20261103.md`
- 计划：`docs/superpowers/plans/2026-11-03-landmark-root-cause.md`
- 新增合成坐标回归：`tests/evaluation/test_landmark_improved.py`（scale .5/.8/1.0 anchor/bbox）
- 未修改旧 freeze/正式结果；未推送。

## 3. 独立核验/测试

- `scripts/verify_landmark_root_cause.py`：**PASS 43 checks**；重算候选 best、threshold sweep、坐标差、B 复现、模板/输入 hash；B mismatch 0。
- `pytest -q` 与文档审计见最终结果；新增坐标测试通过。
- 没有新 Isaac 运行/completion；旧 GUI 数据只作离线证据。

## 4. 方法决策

- **停止模板方法作为主候选**：继续加同场景模板会追逐视角覆盖并放大误报；没有证据支持“再堆几个模板”可解决 reverse/困难负例。
- 下一方法：“几何 + 绿灯 anchor”传统 CV（边缘/梯形/对称性 + HSV 绿灯 blob + 相对位置校验）；无训练/大模型。
- 验证成本：3–4 个新独立 GUI episode + 40–60 帧独立标注 + 离线 CPU 评价；先冻结参数/规则再测，不用测试回调。
- 停止条件：若几何+anchor 在新独立数据仍达不到预先声明的 IoU/bearing 和可接受误报，则停止本阶段感知推进，转向真实相机/区域拓扑，而不是继续模板。

## 5. 边界

- 49 帧是已暴露诊断数据，不能再次称独立测试；没有新正式测试结论。
- 不接控制/SLAM/VIO/PPO/真实硬件/板端/SITL/HIL/实机，不提升 Gate；规则/BOM/PX4 保持 UNKNOWN/RULE-CHECK。
- 硬件参数待测，不作为本轮离线诊断阻塞。
