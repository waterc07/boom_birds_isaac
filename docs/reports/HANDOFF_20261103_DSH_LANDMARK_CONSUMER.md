# 交接：V2.2 最小感知消费者（shadow，2026-11-03）

## 状态

- **PASS（软件/预冻结评价/独立核验）**，但**算法效果仅部分达标**：测试 frame TP9/FP0/FN9/TN18，precision 1.0、recall 0.5；无假阳性，遮挡/边缘/尺度变化漏检如实保留。
- 消费者为 **shadow-only**：从既有 6 个 GUI sensor episode 的 RGB/intrinsics/静态模板读取；不读 ORACLE 位置/标签/未来信息；不接控制、不提升 Gate。
- 独立核验：24 checks PASS；帧级/集级分母、hash、时间语义、generation/reset、shadow 边界；`pytest -q` 799 passed；文档审计 PASS。

## 1. 实现

| 文件 | 作用 |
| --- | --- |
| `src/boom_birds/evaluation/landmark_detector.py` | 多尺度灰度 NCC 塔模板检测；score 非概率 |
| `src/boom_birds/evaluation/landmark_consumer.py` | 输入归一化、v2 gate、generation/cache reset、结果/拒绝/溯源；无 truth 输入 |
| `scripts/run_landmark_consumer.py` | 离线消费冻结 sensor 数据，输出 results/summary；未读取 labels |
| `scripts/verify_landmark_consumer.py` | 独立重算指标、分母、hash、reset、shadow 边界 |
| `scripts/make_landmark_freeze.py` | 预冻结 consumer 源码、输入 run、template/labels、阈值/尺度/split/expected |
| `src/boom_birds/evaluation/sensor_observation.py` | v2 时间语义：`capture_time_source`、`exposure_time_status=UNKNOWN`、`capture_interval_ns`；先失败测试后修复 |
| `src/boom_birds/sim/sensor_shadow.py` | future v2 记录产生；旧 v1 数据保留 |
| `tests/evaluation/test_landmark_consumer.py` | 检测/消费者/拒绝/truth 隔离回归 |
| `tests/evaluation/test_sensor_observation.py` | v2 时间语义/拒绝回归 |

- 源码 commit：`24596a1`（consumer/detector/时间语义）；`1f8e242`（核验 episode 分母修正）；正式 consumer freeze source commit `1f8e242`。
- 不新增 AprilTag/合成色块/比赛设施；目标为现有地图 RoboMaster 中央塔自然结构；经典模板匹配，无训练模型/大框架。

## 2. 数据与评价

- 输入：上一轮 `outputs/sensor_shadow/formal6`（6 个预冻结 GUI episode）与 `formal6_sensor/observations.jsonl`。
- 标签：`configs/perception/landmark_labels_v1.json`，train route_0（11 帧），test route_1/reset_0/reset_1/static_0/static_1（36 帧）；按 episode 划分，不随机拆相邻帧；正/负 18/18；190/195 标部分遮挡。
- 模板：`configs/perception/tower_template_v1.png`（来自训练 route_0 sequence 212）。
- 阈值：0.55（只用训练帧选择；未按测试结果调参）；scale `0.5,0.65,0.8,1.0,1.15`。
- 结果：TP9/FP0/FN9/TN18；precision1.0/recall0.5；test rejection0；全 864 RGB 中 42 detected、804 not detected、18 WARMUP rejected。
- FN 为 near/edge/occluded/scale frames（route_1/reset0/reset1 seq190/195/200）；无 FP；未检测/拒绝不删除。
- 像素/方位误差 NOT_AVAILABLE：标签为 presence-only，无独立 bbox/bearing 标注；不伪造误差。

## 3. 上一轮统计/时间审查结论

- 1728 = 864 RGB + 864 depth。
- accepted 1336 = RGB valid 846 + depth valid 490。
- invalid 392 = RGB WARMUP 18 + depth WARMUP 18 + depth NON_FINITE 356。
- 18 差异 = 864 全 RGB 中未扣除的 RGB WARMUP；不是丢失数据。详见 `DSH_SENSOR_SHADOW_ERRATA_20261103.md`。
- 旧 v1 `capture_host` 在 camera update 后、不是曝光；`exposure_uncertainty_ns=physics_dt` 不是曝光界；旧 age 10ms 是 timestamp uncertainty，不是完整采集延迟。
- v2 记录改为 `SIM_UPDATE_SAMPLE_TIME`/`exposure UNKNOWN`/`capture_interval=250ms`；消费者对旧 v1 显式标 legacy/UNKNOWN；完整曝光/延迟仍未验证。

## 4. 预冻结与证据

- consumer freeze：`configs/perception/landmark_freeze_v4.json`，sha256 `e812a64e07d57f5e6a77319f7a028c66e2cdd6cf4f6defb25be108540042b641`；包含源码 hash、sensor input run/freeze/hash、template/labels hash、threshold/scales/split/expected；不按测试结果放宽。
- 核验 JSON：`docs/reports/map_eval/contact_envelope/dsh_landmark_consumer_verify_20261103.json`（PASS 24 checks）。
- 证据：`docs/reports/map_eval/contact_envelope/evidence_20261103_landmark_consumer/`（correct_tp、miss_fn_occluded、miss_fn_scale、negative_tn、unknown_reject、template、labels、metrics、results sample、consumer summary、hashes.json）。
- 原始结果：`outputs/perception/landmark_final/results.jsonl`（864 条，gitignored，hash 归档）。

## 5. 未完成/失败/适用边界

- 仅单塔模板、单视角族；recall 0.5；部分遮挡/边缘/尺度变化漏检；无区域识别、区域图、地标数据库、定位/SLAM/VIO、在线避障。
- 无独立 bbox/bearing 标签；无像素/方位误差数据；无真实相机/镜头/CSI/曝光/硬件时间戳；相机参数仍 PROPOSED。
- 单中心深度不能给任意检测框距离，故本轮 distance UNAVAILABLE；未把渲染深度当 ToF/双目。
- 不接控制；路线仍 ORACLE shadow；不提升 G2/G3/Gate；规则/BOM/PX4 保持 UNKNOWN/RULE-CHECK。
- 未启动 PPO/真实感知/PX4 Sender/板端/SITL/HIL/实机；未购买/复制硬件资产。

## 6. 距区域/地标导航还缺什么

1. 地标数据库/区域拓扑（地标 ID、坐标/区域、可见性、方向先验）；当前仅一个自然塔模板。
2. 真实 OV9782 镜头/CSI/内参与畸变、相机-机体外参、安装基准。
3. 相机/主机时间戳与曝光可用性、真实端到端延迟；替换 PROPOSED 参数。
4. 多视角/尺度/遮挡的检测鲁棒性，独立 bbox/bearing 标注，多假设管理。
5. 若需距离，合法 VL53L8CX/深度采样与标定，而非单中心像素。
6. 真实 RK3576/板端采集链与 shadow 消费者资源验证。

## 7. 下一项最少实物参数/测量（不要求先补齐全部硬件）

- OV9782 实际模组/镜头型号、FOV/分辨率/像素格式、CSI lane、帧率、曝光范围/畸变；
- 相机安装基准/光轴/机体外参、相机-IMU/飞控时间戳与同步误差；
- 若使用距离：VL53L8CX 接口/8×8 zone/更新率/量程/反射率/相机视场映射；
- RK3576 CSI/驱动采集与时间戳、端到端延迟；
- 至少一套多视角/遮挡的地标标注与区域拓扑草案。

## 8. 下一步 V2.2 主路线

停止继续拆分接触诊断；本软件消费者已形成可评价 baseline。下一步应补 **真实相机/镜头/CSI/时间戳 + 地标数据库/区域拓扑**，再接入最小区域/地标 shadow 消费者；不接控制，不提升 Gate。真正阻断后续架构的是真实感知/定位、PX4 Sender/固件、板端 Student、多环境训练与实机安全链；购买硬件不是本包软件完成前置，但上述实测是下一步所需。
