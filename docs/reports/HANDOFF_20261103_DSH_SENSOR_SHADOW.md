# 交接：V2.2 模拟传感器采集、时间戳与观测消息链（shadow，2026-11-03）

## 状态

- **PASS（单环境 shadow）**：真实渲染 RGB + 渲染深度两条模拟观测通道经 v2 MessageHeader/Context 输出，独立 shadow 记录器；ORACLE 路线控制未变。
- **6 个预冻结 GUI episode**：静止悬停 2、位置/yaw 路线 2、reset 重绑定/隔离 2；generation 1–6；`run.complete.json` 存在、无 error。
- **数据实际产出**：1,728 条记录，1,336 条 gate 接受；864 RGB（全部可解码/非空）、490 有效 depth；两个已知静止深度 1.680/2.680 m 独立核对；392 条显式 WARMUP/NON_FINITE，未零填。
- **独立核验 PASS**：43 checks；迁移 4,230 行 PASS；`pytest -q` 793 passed；独立 worktree 恢复 793 passed、sensor freeze 校验 PASS；文档审计 PASS。
- 未启动 PPO/真实传感器/PX4/板端/SITL/HIL/实机；不提升 Gate。

## 1. 代码与配置

| 类别 | 路径 |
| --- | --- |
| 代码 commit | `a623b4b`（sensor shadow、合同、cases/config、测试） |
| 观测合同 | `src/boom_birds/evaluation/sensor_observation.py` |
| 传感器适配层 | `src/boom_birds/sim/sensor_shadow.py` |
| runner 接入 | `scripts/run_dynamic_eval.py`（`--sensor-shadow`、`--sensor-shadow-config`） |
| 合同测试 | `tests/evaluation/test_sensor_observation.py` |
| sensor 配置 | `configs/sensors/sensor_shadow_v1.json` |
| 场景 | `configs/scenarios/sensor_shadow_cases_v1.json` |
| 正式 freeze | `configs/scenarios/sensor_shadow_v2.json`（sha256 `58671440…`） |
| expected | `configs/scenarios/sensor_shadow_expected_v1.json`（`dcdd3aff…`） |
| 独立核验器 | `scripts/verify_sensor_shadow.py` |
| 报告 | `docs/reports/map_eval/contact_envelope/DSH_SENSOR_SHADOW_20261103.md` |
| 证据 | `docs/reports/map_eval/contact_envelope/evidence_20261103_sensor_shadow/` |
| 运行目录 | `outputs/sensor_shadow/formal6`（runner）、`formal6_sensor`（图像/消息） |

未提交用户既有修改；不执行 `git add .`；本轮最终提交只纳入 sensor freeze/expected/核验器/报告/证据；不推送远端。

## 2. 设计通道与 PROPOSED 边界

- **front_rgb**：设计对应 OV9782 前视彩色（V2.2 PROVISIONAL）；仿真为 Isaac Lab pinhole Camera，320×240、90°FOV、mount `(0.12,0,0.03)` m、world +X 前向；来源 `SIM_RENDER_RGB`。分辨率/FOV/安装均为 PROPOSED，不是实物参数。
- **front_depth**：设计对应 VL53L8CX 前向近场距离职责（PROVISIONAL）；本轮仿真为 **SIM_RENDER_DEPTH 中心像素 distance_to_image_plane**，不是 8×8 ToF、不是双目、不是部署算法；辅助 PhysX raycast 单独记录为参考。max 60 m；无命中/非有限显式。
- 消费者只有 shadow 记录器；路线仍用 `ORACLE_STATE`，manifest `mode=SHADOW_ONLY_NOT_IN_CONTROL`；不能把路线成功当视觉控制成功。

## 3. 观测合同/时间/reset

- 复用 `boom_birds.message.v2.0` header/context；record envelope `boom_birds.sensor_observation.v1`（标准库）。
- 每样本记录 sensor_id/modality/frame_id/sequence、capture/ready/consume 的 sim 与 host 时间及 clock_id、四级上下文/sync_generation、相机内外参、shape/dtype/hash、validity/原因、来源。
- `capture_sim_ns` 为仿真帧时间，host capture/ready/consume 分开；`exposure_uncertainty_ns` 只记录一个 physics step 的已知上限，不伪装曝光精度。
- 每集 hard reset 后新建 unique camera prim、重建 sensor、重置 gate/sequence；预热 3 帧在任务 step 之外完成，标 WARMUP，不占任务 timeout；旧 generation 样本不进入新集。
- 软件边界测试：正常新样本、旧序号/重复、过期、boot/context 不匹配、generation 不匹配、无效样本。

## 4. 正式运行

- freeze/expected 见上；`a623b4b` 预冻结；6 ep、`follow_only`、默认 measured/reference_origin；前台 GUI/DirectX/D3D12；开始 `20:43:22`（+08:00）。
- 案例：`sensor_static_0/1`（悬停、障碍约 1.68/2.68m）、`sensor_route_0/1`（A/B 合法路线，位置/yaw 变化）、`sensor_reset_0/1`（A 路线连续两集）。
- 正式运行全 `SUCCESS/ROUTE_COMPLETE`；completion marker 存在、无 error；记录 generation 1–6、warmup 每集 3 帧、每集 camera/depth 均有 accepted。

## 5. 数据/独立核验

- 1,728 records：864 RGB、864 depth 记录（其中 490 valid；392 条排除含 WARMUP/NON_FINITE）；1,336 accepted。
- 静止 depth：1.680000 m / 2.680000 m（两处已知几何）；路线 depth 1.14–23.47 m，非有限显式 invalid。
- 图像：全部 PNG 可解码/非空；地图/障碍可见；静态方向已人工核对；路线图像 hash 随运动变化。
- 独立核验 `verify_sensor_shadow.py`：PASS 43 checks（freeze/源码/config、completion/error、6 集分母、generation/握手、sequence reset、时间/age、图像解码/hash/非空/运动、两 depth 参考、reset 隔离、ORACLE 界限）。
- 迁移核验：PASS 4,230 行/6 集。
- `pytest -q`：793 passed；文档审计 PASS。
- 独立 worktree（`a623b4b`，`core.autocrlf=false`，本地 map config/既有 brake evidence）：sensor freeze 校验 PASS、导入 PASS、793 passed。

## 6. 失败/重试保留

- 初版相机 mount 旋转导致图像横滚 → 改为 world +X/+Z，图像正立。
- 初版 raycast 距离主通道在静态场景未命中（射线低于障碍）→ 改用 `SIM_RENDER_DEPTH` 主通道，raycast 辅助；明确不是 ToF。
- 静态 case goal region 错误被 loader 拒绝 → 修正为 W；调试运行保留在 `outputs/sensor_shadow/debug_*`，不作为正式数据。
- 正式 6 集无失败。

## 7. 未验证项 / 适用边界

- PROPOSED 相机分辨率/FOV/安装/曝光/畸变未实测；距离不是 8×8 ToF/双目；无真实硬件时间戳、CSI/驱动、反射率/环境光/zone 覆盖。
- 仅单环境、当前地图、6 episode；不是全场景统计，不做图像识别/定位/SLAM/VIO/在线避障/学习策略。
- 传感器未进入控制；不能宣称视觉控制/感知成功；不提升 G2/G3/实机。
- PPO/板端/PX4 Sender/SITL/HIL/实机均未运行；规则/BOM/PX4 保持 UNKNOWN/RULE-CHECK。

## 8. 恢复命令（摘要）

```powershell
$py='E:\isaac\env_isaaclab\Scripts\python.exe'
& $py -u scripts/run_dynamic_eval.py --cases configs/scenarios/sensor_shadow_cases_v1.json --methods follow_only --execution-path v2 --geometry-policy reference_origin_v2 --contact-mode measured_hard_reset --sensor-shadow outputs/sensor_shadow/formal6_sensor --sensor-shadow-config configs/sensors/sensor_shadow_v1.json --screenshots --device cuda:0 --kit_args=--/app/vulkan=false --code-commit a623b4baaab54ea1a88066483b4b528210d65bde --freeze configs/scenarios/sensor_shadow_v2.json --output outputs/sensor_shadow/formal6
& $py scripts/verify_sensor_shadow.py --run outputs/sensor_shadow/formal6 --shadow outputs/sensor_shadow/formal6_sensor --freeze configs/scenarios/sensor_shadow_v2.json --expected configs/scenarios/sensor_shadow_expected_v1.json --repo-root . --output docs/reports/map_eval/contact_envelope/dsh_sensor_shadow_verify_20261103.json
& $py -m pytest -q
```

## 9. 下一项 V2.2 主路线工作

不要继续增跑相同静态 scene；下一步应补 **OV9782/VL53L8CX 实物参数、镜头/CSI/驱动、真实时间戳与 RK3576 采集标定**，建立真实采集链；然后再接入最小区域/地标感知消费者，仍先 shadow，不直接进入控制。实机/多环境/原生 event 不作为本 shadow 观测链的无限期前置，但也是后续升级边界。
