# V2.2 模拟传感器采集、时间戳与观测消息链（shadow）— 2026-11-03

> **状态：** PASS（单环境、shadow 观测链；ORACLE 控制未变，不提升 Gate）
> **证据域：** Isaac Sim 5.1 前台可视 GUI（DirectX/D3D12，无 headless）、单环境、预冻结 6 episode；不是真实相机/ToF、不是视觉定位或避障验收。
> **最后核对：** 2026-11-03T21:00+08:00

## 1. 结论

- 在 RMUC2027 地图、当前动力学仿真中跑通了 **机载前视 RGB 相机 + 前向渲染深度** 两条模拟观测通道；数据经 **v2 MessageHeader/ContractContext** 包装为可追踪观测记录，进入独立 shadow 记录器，**没有参与 ORACLE 路线控制**。
- 完成 **6 个预冻结 GUI episode**：静止悬停 2、含位置/yaw 变化的合法路线 2、reset 后重新初始化与隔离 2；每集 generation 1–6 递增，旧 generation 样本不进入新集。
- 数据集：**1,728 条观测记录，1,336 条被 gate 接受**；864 条 RGB 样本、490 条有效 depth 样本；其余 392 条为显式 `WARMUP`/`NON_FINITE`，未零填充。
- **相机**：320×240 原始 PNG 全部可解码、非空；画面包含地图/障碍，已人工检查安装方向（平面朝上、前向与 body +X 一致）；路线集图像随位姿变化出现不同 hash，静止集不依赖 hash 相同判陈旧。
- **距离**：使用 `SIM_RENDER_DEPTH`（不是 ToF、不是双目、不是部署算法）；两个静止对照的已知深度为 **1.680 m / 2.680 m**，独立核验与期望值一致。辅助 PhysX raycast 参考另列，不冒充主通道，深度与 raycast 的差异按定义/几何/采样解释。
- 消息时间：`capture_sim_ns` 来自仿真帧时间；`ready_host_ns`/`consume_host_ns` 是实际更新/消费的主机时刻；三者分域记录；暴露时间不伪造，`exposure_uncertainty_ns = 1 physics step`，仅表示已知上限。
- 硬 reset 后重建 unique camera prim、重建 gate 并清空 sequence；**预热 3 帧在任务 step 之外**完成（不占任务 timeout），预热记录标 `WARMUP`，首个有效样本条件满足后才接受。
- 独立核验：`scripts/verify_sensor_shadow.py` **PASS，43 checks**；迁移核验 4,230 行 PASS；全套 `pytest` **793 passed**；独立 worktree 恢复 793 passed；文档审计 PASS。

## 2. 设计映射（V2.2 正文 → 仿真 → 输出 → 消费者 → 验收）

| 设计通道 | 正文状态 | 仿真设备/配置（PROPOSED） | 输出/来源 | 消费者 | 本轮验收 |
| --- | --- | --- | --- | --- | --- |
| 前视彩色相机 OV9782 | PROVISIONAL；模组/镜头/实际分辨率/FOV 未冻结 | Isaac Lab `Camera` + `PinholeCameraCfg`，320×240，水平 FOV 90°，body +X 前向，mount `(0.12,0,0.03)` m | `SIM_RENDER_RGB`，PNG uint8 | shadow 记录器；**不参与控制** | 可解码、非空、拍到地图、运动/位姿对应 |
| 前向近场距离（VL53L8CX 设计职责） | PROVISIONAL；8×8 采样/频点/反射/时序未冻结 | **最小单像素渲染深度**，中心像素 `distance_to_image_plane`，max 60 m；**不是 8×8 ToF** | `SIM_RENDER_DEPTH`，m | shadow 记录器；辅助 raycast 参考另列 | 两个已知静止距离 1.68/2.68 m；无命中/非有限显式 |

- 正文确定项：前视相机负责目标/场景感知，前向距离用于近场障碍检查；不得把仿真值当实物参数。
- 未定项：分辨率、频率、FOV、安装角度、畸变、曝光、ToF 8×8 zone/更新率/材料反射、真实时间戳；本报告全部标 **PROPOSED**，不能用于硬件采购或实机验收。
- 距离采用 `SIM_RENDER_DEPTH`，明确不是 ToF、不是双目匹配；PhysX raycast 作为辅助参考单独记录（见 §6）。

## 3. 观测合同与消息字段

- 复用 `boom_birds.message.v2.0` 的 `MessageHeader`/`ContractContext`，不新建飞行控制 schema；record envelope 为 `boom_birds.sensor_observation.v1`（标准库模块 `src/boom_birds/evaluation/sensor_observation.py`）。
- 每样本记录：
  - `sensor_id/modality/frame_id/sequence_id/source`；`RGB_IMAGE` 或 `SIM_RENDER_DEPTH`；
  - header 四级上下文、`system_boot_id=2201`、`sync_generation=physics_generation`、`px4_boot_id=None`（非 PX4 数据）、`clock_id=sim_physics`；
  - `capture_sim_ns`、`ready_sim_ns`、`consume_sim_ns`；`capture_host_ns`、`ready_host_ns`、`consume_host_ns`；三个 clock_id；
  - 相机内参矩阵、camera world pose/quat、mount/frame 约定；像素单位/米单位；
  - payload 外部 ref、shape、dtype、size、sha256；大 PNG 只放忽略输出目录，仓库保留小样例/索引；
  - validity/reason、gate decision、age_ns、phase；
  - `exposure_uncertainty_ns=physics_dt_ns`（明确是已知上限，不声称曝光精度）。
- `ObservationGate` 使用 v2 消息校验与显式序列/过期/上下文/generation 规则；`WARMUP`/`NO_RETURN`/`NON_FINITE` 不伪装为有效。
- 软件边界测试覆盖：正常新样本、旧序号/重复、过期、上下文/boot 不匹配、generation 不匹配、无效样本；见 `tests/evaluation/test_sensor_observation.py`。

## 4. reset / 预热 / 隔离

- 默认评价 measured 模式每集 `env.sim.reset(soft=False)`；adapter 在每次 `begin_episode` 关闭旧 camera、创建 unique `.../shadow_camera_<generation>`、重建 `Camera` sensor，并 `ObservationGate.reset(context, generation)`。
- 预热：`start_measurement()` 在正式 RUN 前执行 3 次 camera update；这些样本写为 `WARMUP` 且 gate 拒绝，不占任务 step、不改变任务 timeout；记录预热帧数。
- 序列在每个 generation 内从 0 开始；旧 generation 记录不进入新集；RUN 内没有未声明 reset。
- 正式运行 generation 1–6；每集 warmup 3 帧；static/route samples 数见证据。
- 传感器失败会抛错并写 runner `summary.error.txt`，不创建 completion marker；本轮正式运行 completion marker 均存在且无 error 文件。

## 5. 正式预冻结与运行

- 代码 commit：`a623b4b`（sensor chain、config/cases、合同测试）。
- 正式 freeze：`configs/scenarios/sensor_shadow_v2.json`，sha256 `58671440f71425d4355f8bbc0723dd92859239e317f212c6ff3d8e23b0e1bc8c`，Git HEAD `a623b4b`，包含 source/config/cases/sensor config hash、六案例、PROPOSED 参数、或预期引用。
- expected：`configs/scenarios/sensor_shadow_expected_v1.json`，sha256 `dcdd3affbad0dff4ccc2c508673cf6dbb7f3542d98be60f745c4ccc44ece09ec`。
- 案例：`sensor_static_0/1`（悬停，障碍物距相机约 1.68/2.68 m）、`sensor_route_0/1`（A/B 合法路线，位置与 yaw 变化）、`sensor_reset_0/1`（A 路线连续两集，验证 reset 重建/隔离）。
- 正式运行：`outputs/sensor_shadow/formal6`（runner）与 `formal6_sensor`（传感器外部目录）；开始 `2026-11-03T20:43:22+08:00`；前台 GUI/DirectX/D3D12；6 集 `follow_only` ORACLE 路线，均 `SUCCESS/ROUTE_COMPLETE`；completion marker 存在，无 error。

## 6. 数据实际验证

- **相机**：864 个 PNG（含 warmup）全部存在、hash 一致、Pillow 可解码；非空图像（std/edge>0）；静态样例可见地图地面/标线/障碍，方向正确；路线集图像 hash 随运动变化（例如 route_0/route_1 各多个不同 hash）。静止集不依赖“hash 相同”单独判陈旧；freshness 由 generation/sequence/capture time/pose 共同核验。
- **距离**（`SIM_RENDER_DEPTH`）：
  - 静止 `sensor_static_0` 稳定 **1.680000 m**；`sensor_static_1` 稳定 **2.680000 m**，与已知场景几何/障碍距离一致（两个已知距离）。
  - 路线集 depth 1.14–23.47 m；部分天空/无表面样本为 `NON_FINITE`，显式拒绝，不填零。
  - 辅助 PhysX raycast 参考记录：静止射线命中 `/World/RMUC2027/Collisions/collision_015`（约 9.79 m），而渲染深度命中近处障碍 1.68 m；说明 raycast 参考与渲染深度不是同一几何/采样定义，**不把差异判为深度缺陷**，主通道明确为 `SIM_RENDER_DEPTH`。
- **时间**：`capture_sim_ns` 与仿真帧对应；host capture/ready/consume 分别记录；accepted age（sim 域）10 ms ≤ 250 ms；不把 ready/save 当 capture。
- **reset**：generation 1–6 全部有样本；sequence 每代从 0 重启；旧代不进入新代；warmup 3 帧显式标记。

## 7. 独立核验与测试

- `scripts/verify_sensor_shadow.py` → `docs/reports/map_eval/contact_envelope/dsh_sensor_shadow_verify_20261103.json`：**PASS，43 checks**，0 failures。覆盖 freeze/source/config、completion/error、6 集分母、generation/握手、record schema/来源/单位、sequence reset、timestamp/age、图像解码/hash/非空/运动、depth 两参考、raycast 辅助、reset 隔离、ORACLE 控制界线。
- `scripts/verify_dynamic_migration.py` → `dsh_sensor_shadow_migration_verify_20261103.json`：PASS，4,230 行/6 集。
- `pytest -q`：**793 passed**（含 sensor contract/gate 7 项、既有回归）。
- 独立 worktree（commit `a623b4b`、`core.autocrlf=false`、本地 map config/既有 brake evidence）：
  - sensor freeze 校验 **PASS**（argument sources explicit）；
  - 模块导入 PASS；
  - `pytest -q` **793 passed**。
- 文档审计：PASS。

## 8. 失败/重试记录

1. 首版相机 mount 用 ROS 旋转导致图像横滚；改为 world +X/+Z 约定后图像正立。
2. 最初用 PhysX raycast 作距离主通道，静态场景因射线高度在障碍物下而未命中；改用 `SIM_RENDER_DEPTH` 作为明确 PROPOSED 距离通道，raycast 仅辅助参考；图像/深度均实际产出。
3. 静态案例初版 goal 区域填错（W 起点/E 目标）被 loader 拒绝；修正为 W 后运行成功。
4. 调试期失败输出保留在 `outputs/sensor_shadow/debug_*`，不作为正式证据；正式 6 集无失败。

## 9. 适用边界 / 未验证项

- 单环境、当前地图/单障碍；6 episode 是观测链专项，不是全场景统计，也不是视觉定位/避障验收。
- 相机 320×240/90°FOV/mount 是 **PROPOSED**，不是 OV9782 实物参数；未验证真实镜头畸变、曝光、运动模糊、CSI 时序、硬件时间戳。
- 距离是 **SIM_RENDER_DEPTH** 单中心像素，不是 VL53L8CX 8×8 ToF，不是双目，不是部署算法；未验证反射率、环境光、zone 覆盖、真实量程。
- 相机/传感器数据 **未进入控制**；路线成功仍是 ORACLE 控制结果，不能算视觉控制/感知成功。
- 未做图像识别、目标检测、SLAM/VIO、在线避障、学习策略；未启动 PPO、板端、PX4 Sender、SITL/HIL/实机；不提升 Gate。
- 规则/BOM/PX4 缺口保持 UNKNOWN/RULE-CHECK。

## 10. 下一步推进 V2.2 主路线

不是再跑相同静态场景，而是：
1. 依据 V2.2 实物模块/镜头/接口清单补齐 **OV9782/VL53L8CX 实际参数、标定和 CSI/驱动**，把 PROPOSED 替换为实测；
2. 在板端/RK3576 建立真实采集与时间戳链，验证相机-飞控/主机时钟映射；
3. 再将 shadow RGB/depth 接入最小感知消费者（区域/地标接口），仍不直接进入控制，直到感知合同与安全链验收。

## 11. 版本化证据

- sensor config：`configs/sensors/sensor_shadow_v1.json`（sha256 `06a47962…`）；cases `configs/scenarios/sensor_shadow_cases_v1.json`（`d6b51c1f…`）。
- 证据目录：`docs/reports/map_eval/contact_envelope/evidence_20261103_sensor_shadow/`：小图像样例、depth_timeseries、observations_sample、runner/sensor summary/manifest、GUI 截图、hashes.json。
- 完整 raw 观测/图像位于忽略的 `outputs/sensor_shadow/formal6_sensor/`；hash 归档。
