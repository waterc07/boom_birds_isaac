# Codex 独立复核：陈旧接触与完整物理 reset（2026-11-02）

状态：独立 GUI 诊断完成，找到本次配置下可用的边界处理方案；未接入正式评价或新冻结，不提升 Gate、不宣称底层 PhysX 缺陷已修复。DSH 源文件及用户修改保留，未提交。

## 1. 复核范围与方法

阅读 DSH 的 lifecycle 报告、重放计划与探针源码后，独立增加三层并行读取：Isaac Lab ContactSensor、底层 contact force matrix、`get_contact_data(dt=physics_dt)` 的原始 contact count/force。第二个实验另加 PhysX 原生 callback，第三个实验只改变 episode 边界的完整物理 reset。

所有运行均 GUI、DirectX/D3D12、cuda:0，日志有 `Creating window for environment.`；每次 3 集 ×110 策略步，策略步长 0.05 s。所有进程正常结束，日志有探针完成标记、落盘 JSON 和应用关闭记录，进程 exit=0。沿用 DSH 的静态运动学障碍及受控高度修正，不作为无干预飞行或正式配对验收。

## 2. 关键结果

以机器人 x<-0.5 m 定义本探针的远离障碍采样段，每集 78 个样本；障碍在 (0,0,1)，size 0.6 m。

| 处理 | ep0 远处分离非零力/非零 raw count | ep1 | ep2 | 首次非零力策略步 |
| --- | --- | --- | --- | --- |
| 普通连续运行 fixed | 0/0 | 78/78 | 78/78 | 86 / 1 / 1 |
| 完整物理 reset + env reset | 0/0 | 0/0 | 0/0 | 86 / 86 / 86 |

普通运行 ep1 首步机器人 x=-1.999916 m，contact matrix 仍为上一集最后值 0.01600086 N，raw count=4，raw force buffer 也完全保留旧值。ep2 相同现象，保留约 0.01621804 N。

完整物理 reset 后各集首步 force=0、raw count=0；三集首次接触分别在 x=-0.350107/-0.350173/-0.350173 m；最大力约 0.016507/0.021705/0.021701 N。

重要：ep0 真实接触的最大力低于 0.02 N，因此“未超过判定阈值”不能解释为“没有物理接触”。后续事件与测力合同应保留真实低幅信号、几何和覆盖信息，不通过改阈值重写旧结果。

## 3. 结论与限制

已证实：

- DSH 的跨 episode 陈旧读数现象可独立复现。
- 陈旧不只发生在 Python sensor buffer，底层 tensor force matrix、raw contact count 和 force buffer 同样保留。因此仅增加 raw count 校验无法解决。
- 本次单环境配置中，episode 边界完整物理 reset 可清除旧状态并恢复连续三集的零基线/接触读数，无需每集新建进程。

未证实：底层内部具体缺陷、所有场景/版本的相同行为、地图墙体及多环境/并行训练可用性、分离后不 reset 的接触结束事件可靠性。

原生 `subscribe_contact_report_events` 在本配置 3 集共返回 0 个事件，尽管 tensor 读到力；不能拿该通道无事件证明无接触。callback 方案未建立独立可靠证据，不应先写入生产合同。

本机 Isaac Lab `schemas.activate_contact_sensors` 的源码说明 ContactReportAPI 对刚体配置，遍历检查 RigidBodyAPI，并设报告阈值。不能将“collider shape 必须挂 reporter”当作已确认的一般规则。DSH 本轮也已发现 root-only 能测力，应修订旧报告中过强归因。

## 4. 可复现实验

版本化的 [探针源码](codex_lifecycle_review/contact_lifecycle_physics_reset_probe.py) 与执行过的 hard-reset 探针字节一致。该探针的 `env_reset` 变体特指完整物理 reset 后再 env.reset，与原 DSH 同名变体不同。

```powershell
$bbPython = 'E:\isaac\env_isaaclab\Scripts\python.exe'
& $bbPython -u docs/reports/map_eval/contact_envelope/codex_lifecycle_review/contact_lifecycle_physics_reset_probe.py --scene static_obstacle --variant fixed --episodes 3 --steps 110 --device cuda:0 --kit_args=--/app/vulkan=false --output outputs/codex_contact_raw_probe/new_fixed
& $bbPython -u docs/reports/map_eval/contact_envelope/codex_lifecycle_review/contact_lifecycle_physics_reset_probe.py --scene static_obstacle --variant env_reset --episodes 3 --steps 110 --device cuda:0 --kit_args=--/app/vulkan=false --output outputs/codex_contact_raw_probe/new_physics_reset
```

正式已执行目录：`outputs/codex_contact_raw_probe/fixed3`、`native3`、`hard_reset3`；日志 `logs/codex_contact_raw_fixed3.log`、`codex_contact_native3.log`、`codex_contact_hard_reset3.log` 及各自 exit 文件。版本化 [独立摘要](codex_lifecycle_review/independent_probe_summary.json) 保存选定原始样本、原产物 hash、探针 hash 和各集统计。

## 5. 交给 DSH 的最小接入方案

1. 沿用 Codex 已修复的读取层，不重写张量解析或用 L1。
2. 在单环境正式评价的 episode 边界，显式选择完整物理 reset 模式：`env.sim.reset(soft=False)`，然后执行项目 episode 初始化。应在正式测量开始前完成，绝不在一次 episode 中途悄悄 reset。
3. 完整 reset 会停止/重启物理并使 views/资产/sensor 生命周期失效，必须核对重新初始化后的 sensor/body/filter、清空队列、重设 gate/executor epoch、记录物理 generation；不能沿用旧 generation 的缓存。
4. 在已知分离位姿推进物理并记录原始 force/count，设有限握手步数。失败标 UNKNOWN 或初始化失败，不无限等待、不手动把原始缓冲填零、不通过几何规则制造“健康”。
5. 先做静态障碍三集与墙体三集 GUI 验证，再决定生产接入和闭环复核。若墙体因开口/高度问题无法形成持续接触，使用经验证的实墙或独立诊断墙，写明对象来源。
6. 低幅接触不等于没有接触；正/负证据均需考虑覆盖和新鲜度。已有 contact_readout 的正值目前也没有独立新鲜度保证，应增加 episode 健康握手/generation 记录，不把“读取成功”升级为“当前接触真实”。
7. 完整物理 reset 是单环境评价的可用处理路径，代价及时间语义必须记录。不能直接推广到多环境训练中的单 env reset；不为此修改训练链。
8. 新预运行冻结须包含 reset 模式、读取器源码 hash、接触证据/包络 policy 版本。旧冻结保持原样，禁止事后扩张预期。

## 6. 原案例复核与包络迁移

DSH 的 replay plan 可作为输入清单，但“旧 runner commit 可用”不代表所有依赖恢复到旧版本。重放须固定 supervisor/控制器/合同等依赖的来源，不能仅提取旧 runner 后导入当前工作树模块并称严格同配置。

先恢复测量新鲜度，再做两个旧案例的闭环新测量；缺少运行版本、origin 等信息如实列出，不承诺位级复现，也不把局部几何探针作为旧标签真伪判断。

包络迁移方案方向可行，但需区分视觉/碰撞覆盖和任意关节状态；使用 root-frame center offset，版本化 policy，不只替换常量。接触闭环之前不扩大样本，之后最小重跑受影响专项。

当前结论：读取层确定缺陷已修复并有单元测试；接触跨 episode 问题已有独立实测支持的完整物理 reset 路径；正式入口集成、墙体矩阵、旧案例闭环和生产包络迁移仍未完成，不能标整体问题 complete。
