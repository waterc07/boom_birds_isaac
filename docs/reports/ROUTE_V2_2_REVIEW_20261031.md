# RMUC2027 V2.1 路线验收与 V2.2 修订

日期：2026-10-31（Asia/Shanghai）。范围：用户指定的 DSH 架构文档验收、直接修订及仓库入口同步。未实施飞行能力、改环境、刷固件或执行实机测试。

## 结论与版本

接受 RK3576、3S 350mAh、非 VIO 区域导航、物理触点、局部 RL 与独立碰撞恢复的路线。原稿存在控制与时效合同冲突，不能原样作为实施依据；已直接修改。按原稿第 25 章的版本规则，合同变更升为 **V2.2.0**。

[修订正文](../design/RMUC2027_UAV_V2_2.md)是仓库当前唯一设计正文；外部原文件也已同步修订，保留原文件名便于打开。原始字节保存在 [V2.1 快照](../references/route_v2_1_20261030.md)，输入/输出 SHA-256 见 [来源记录](../references/route_review_provenance.json)。后续只编辑仓库正文，外部副本不作为第二个独立维护版本。

## 审查发现与直接修改

| 发现 | 修改与位置 | 依据/验收边界 |
| --- | --- | --- |
| 到期时刻仍被接受 | 16.6、27.3 统一 `issued_at <= now < expires_at` | 与现有实现和测试一致 |
| 严格递增序号误拒绝合法重发 | 16.6、27.3 区分新接纳和缓存重发，要求身份与摘要不变 | 重发不续期，旧动作不能回滚当前缓存 |
| 从推理完成重新起 TTL 掩盖旧观测 | 16.3.2、16.6 增加输入溯源与最早安全截止 | 按采集年龄及误差界拒绝 |
| 时钟域和 PX4 单独重启隔离缺失 | 16.3、16.3.2、27.2/3 补同步代际、误差界、PX4 boot 标识 | Companion 与 PX4 生命周期不同 |
| Epoch 更新与串口发送存在竞争窗口 | 16.4 补 PENDING/ACTIVE、入队仲裁、在途延迟和非阻塞失效 | 已上线路字节不可撤回 |
| 忽略垂直速度被写成可自动放行 | 10.4.3 默认使用验证过的全轴组合，1511 保留候选 | 掩码不能提供垂直控制 |
| 偏航权限未区分消息接口 | 10.4.3 补 yaw 新鲜度，速度无效走恢复姿态/推力路径 | 不默认支持 yaw-only 速度包 |
| 禁止平移被写成物理运动保证 | 8.4.1、28.5 区分指令与惯性漂移、冻结恢复包络 | 后续视觉状态仍需持续姿态/推力/垂直健康 |
| 光流年龄、积分窗口和速度有效性混用 | 7.3 分开定义 | 旧积分不无限累加，新鲜光流不因累计时间自动失效 |
| OV9281 灰度输入误写 RGB | 第 10、11、14 章改 `down_mono`，补 mask 与占位编码 | 候选字段不等于全部永久接入策略 |
| 完整 Student 容易被理解为全图必须转 RKNN | Phase 2.5 允许显式 CPU/NPU 划分，搬运调度计入整链测量 | 随机权重不能证明最终量化精度 |
| 规则结论强于第三方证据 | 使用说明与第 2 章统一 RULE-CHECK，条数标历史记录 | 官方原文尚未逐条归档 |
| 缺重量/推进/供电联合门 | 5.2.1 增加 BB22:G0.5 | 保留硬件不等于组合已验证 |
| Gate 图绕过机库并漏掉退化/最终部署 | 20.9、28.3 补依赖与 BB22 命名、INVALID/INCOMPLETE | 所有新 Gate 尚未验收 |
| 零错误样本容易被理解为绝对保证 | 20.11.3 补分层、置信区间和失败分母 | 统计结果有适用域 |
| 新目录树和旧入口容易造成两套路线 | 第 19 章映射现有包；同步总纲、README、AGENTS 与历史提示 | 不创建空壳，不自动继续旧训练计划 |
| 数学导出残留 | 清除 `{=tex}` 和嵌套代码围栏，修复损失表达 | 不构成算法验证 |

## 当前实现差距

基线提交 `d01e156`，接手分支 `codex/rmuc2027-map-preview`；原有未跟踪 `docs/reports/RMUC2027_ASSET_PREVIEW_20261028.md` 保留。本次分支 `codex/review-rmuc2027-v2-route`。源码未修改；`boom_birds.velocity.v1` 仍使用 ENU 速度、mission/origin epoch 和 clock_id，尚无新消息字段、监督器或 Sender。

已有动作单测不表示新 Schema、控制器、板端或新 Gate 通过。下一项先补 Phase 0 的来源/实物/Schema 差异，再按 BB22:G2.6 实施纯软件合同；旧 Task 3 的动力学响应方法可复用，旧 Task 4–6 不自动继续。

## 官方资料核验及限制

- [PX4 v1.16 Offboard](https://docs.px4.io/v1.16/en/flight_modes/offboard)：核对接口与控制层要求，未锁定为实机固件。
- [PX4 v1.16.0 接收代码](https://raw.githubusercontent.com/PX4/PX4-Autopilot/v1.16.0/src/modules/mavlink/mavlink_receiver.cpp)：检查 LOCAL_NED 掩码与控制量选择，实际飞控仍待复现。
- [MAVLink common](https://mavlink.io/en/messages/common.html)：核对 1479/1511 与姿态动作字段，未测试链路。
- [Rockchip 官方工具链](https://github.com/airockchip/rknn-toolkit2)：列有 RK3576，具体图转换和板端延迟仍待验。
- [OV9782 官方页面](https://www.ovt.com/products/ov9782/)：核对彩色器件属性，不外推模组并发性能。
- [赛事规则中心](https://bbs.robomaster.com/wiki/20204847/1969149?source=7)、[场地公告](https://bbs.robomaster.com/article/1970956)：可访问，但本次工具只提取到页面框架/标题，未获得规则附件或完整公告正文。4Wh、300Wh、通信与交互等继续为 RULE-CHECK。

## 验证记录

使用现有解释器 `E:\isaac\env_isaaclab\Scripts\python.exe`，未安装新依赖：

| 实际执行 | 结果 | 证明范围 |
| --- | --- | --- |
| `-m pytest -q` | exit 0，33 passed in 0.30s | 既有 v1 合同回归，不证明新 Schema |
| `scripts/planning/audit_documents.py` | exit 0，28 文件、117 本地链接、11 算术锚点、9 来源 hash 全部通过 | 链接存在、固定算术和文件完整性，不证明规则语义或飞行 |
| 临时将 accepted-design hash 改为全零并运行审计，finally 恢复 | 预期 exit 1，包含 `route provenance hash changed`；恢复后审计 exit 0 | 新 hash 校验会拒绝不一致的正文；未保留篡改 |
| 单次 Python 文档一致性检查 | 正文保留第 0–28 章；围栏成对；无 `{=tex}` 残留；严格到期边界和重发分支存在；外部文件与正文逐字节一致；原稿快照 hash 匹配 | 静态结构与修改落盘检查，不执行文档伪代码 |
| `git diff --check` | exit 0 | 已跟踪改动无空白错误；原稿快照按字节保留，单独设置 Git 属性避免换行转换 |

新增系统能力、RK3576 板测、SITL/HIL、训练及实机均为 NOT RUN。规则原始条款、实物 BOM/电池铭牌、重量推进供电、PX4 固件与状态映射、传感器驱动/并发、完整 Student 部署与恢复包络仍未具备放行证据。

本次工作在独立分支保留为未提交修改，未推送远端。用户原有地图预览报告未修改。
