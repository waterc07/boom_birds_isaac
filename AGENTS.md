# Boom_Birds 仓库协作规则

本文件是后续代理接手项目的操作入口。详细需求、接口与验收以对应设计和实施计划为准；代码、运行证据与文档不一致时，先核查并同步记录，不把规划当成实现。

## 接手顺序与依据

1. 先读 `PROJECT_PLAN.md`、`docs/design/02_ARCHITECTURE.md`、`docs/design/05_WORKSPACE.md`。
2. 再读 `docs/superpowers/plans/2026-10-11-p0-p1-foundation.md`、`docs/reports/p0/P0_ENVIRONMENT_REPORT.md`，确认已完成项、限制和下一工作包。
3. 检查 `git status --short`、当前分支和近期提交；保留用户已有修改，不覆盖、不回退无关文件。
4. 实施前阅读对应任务的设计、配置和测试；验收依据见 `docs/design/08_EVALUATION.md`，上游复用依据见 `third_party/NOTICE.md`。

当前采用 v1.2 总纲及 `docs/design/01–09`，优先于归档计划。P0/P1按现有实施计划推进；后续阶段在前置决策门证据具备后编写具体计划。

## 当前状态与延续入口

截至 2026-10-11，以下为接手基线，后续须以现场检查和最新报告刷新：

- Task 1/W00：已有环境、上游许可、版本与官方最小例证据；选定现有 RSL-RL 5.0.1。环境依赖一致性仍有冲突，详情见 P0 报告；不能宣称 G0 全面通过。
- Task 2/W01：已实现标准库动作、坐标、时效合同及回归测试。
- Task 3–6：仿真速度执行器、到点任务、统一评价、项目 PPO 训练和重放尚未实现。
- 下一工作包是 Task 3：在官方四旋翼资产上验证速度指令→控制器→力/力矩→实际运动，覆盖前/左/上/偏航阶跃、停止、过期和 reset。
- 官方任务步进和官方 PPO 短迭代仅证明相应入口可运行，不代表本项目训练、稳定飞行或迁移验收；G1及后续阶段尚未验收。

## 目录与实现边界

- `src/boom_birds/contracts/`：已实现的标准库动作、坐标与时效合同。
- `tests/contracts/`：对应合同的 pytest 回归测试。
- `scripts/`：环境诊断；`scripts/planning/`：文档审计。
- `configs/runtime/`：拟定运行参数，不代表运行系统已实现。
- `env/manifests/`、`env/locks/`：观测版本、上游 SHA 和既有依赖快照；快照不保证环境可干净重建。
- `docs/reports/p0/`：执行证据；`third_party/NOTICE.md`：复用边界。
- `external/`：被忽略的上游参考源码，不能成为项目运行时的隐式依赖。

设计中的其他目录是蓝图，随工作包实际建立，不创建空壳冒充实现。权重、大型资产和实验输出不入 Git；官方 USD 资产按远程引用及 manifest 追踪，不直接打包入库。

## 开发与验证命令

在仓库根目录使用 PowerShell 和现有解释器，无需为单元测试安装项目包；pytest 已配置 `src` 导入：

```powershell
$bbPython = 'E:\isaac\env_isaaclab\Scripts\python.exe'
& $bbPython -m pytest -q
& $bbPython scripts/planning/audit_documents.py
```

需要刷新环境证据或验证官方任务时再运行：

```powershell
& $bbPython scripts/preflight.py --isaaclab-root E:\isaac\IsaacLab --output env/manifests/host.json
& $bbPython scripts/check_official_quadcopter.py --headless --device cuda:0 --clone-in-usd --steps 100 --output env/manifests/official-quadcopter-usd-smoke.json
```

诊断会覆盖指定记录；刷新时同步报告，保留重要历史失败证据。当前官方例使用 USD 克隆路径；Fabric 克隆问题及证据边界见 P0 报告。尚无项目训练或构建 CLI，实施计划中的未来命令须待入口实现后使用。

## 编码与测试

使用 Python 3.11+、四空格缩进、`snake_case` 函数/文件和 `PascalCase` 类型。公共接口加类型注解，变量名标明单位，如 `now_ns`、`velocity_enu_mps`。当前没有配置 formatter 或 linter，不声称已通过不存在的检查。

contracts 仅依赖标准库，不导入 Torch、Isaac 或相机库；sim/learning 与 runtime 保持既定依赖边界。

pytest 文件使用 `test_*.py` 和描述明确的 `test_*` 函数。修改合同行为前先添加失败回归测试，再实现并运行全套测试。覆盖坐标符号、水平向量限幅、非法值、到期边界、时钟域和 mission/origin reset。新增仿真与评价能力按对应计划验证；未配置覆盖率百分比门限。

完成声明须附实际验证命令、结果与限制。单元测试、官方 smoke、本项目仿真、训练及实机证据分别描述，不能互相替代。

## Git 提交与 PR

- **后续所有 Git 提交消息使用中文：标题的描述部分及正文均使用中文。** 保留 `docs:`、`feat:`、`fix:` 等类型前缀，代码标识符、路径和必要技术名词可保留原文。例如：`docs: 完善项目接手规则`、`feat: 实现仿真速度执行器`、`fix: 拒绝过期速度指令`。
- 中文规则适用于普通提交、合并提交、回退提交及 squash 最终消息；不为语言规则改写既有历史。
- 按工作包使用独立分支；新建分支默认使用 `codex/` 前缀，已有工作包分支可继续沿用。
- 提交前检查 diff 与验证结果，只纳入当前任务文件；不纳入秘密、本机私有配置、大产物和无关修改。
- PR 说明行为变化、计划任务、验证命令/结果及剩余限制，有相关 issue 时关联。阶段交付不自动推送远端或刷写固件。

## 环境、架构与复用约束

保留现有 Isaac 环境；依赖冲突先复现受影响入口并调查，再决定局部调整，不全局升级或复制 venv。不安装 NavRL/DiffPhysDrone 整套旧运行链；采用已选 RSL-RL 后端，不自行实现 PPO 优化器。

统一四维归一化动作：水平 FLU 前/左速度、向上速度、逆时针偏航率；运行指令使用 ENU 物理单位，PX4 网关再转 NED。水平速度约束向量模长，不能只逐轴限幅；重发不续期，`now_ns >= valid_until_ns` 即过期。任务/原点 epoch 与时钟域不匹配时拒绝旧动作。

PX4 保留飞控权限；策略不能直接解锁、改模式或改参数。官方推力/力矩动作不能直接当作本项目速度动作；理想赋速度对照须标明 KINEMATIC，不用于迁移验收。无效状态不得用零值伪装有效，零速度也不是所有失效情形下的实机安全保证。

私有路径与秘密放被忽略的本地配置，不新写入可提交配置或报告。复制上游代码前核对许可，记录来源 SHA、文件及修改说明；DiffPhysDrone 代码复制仍被许可澄清阻塞。

## 工作包收尾与交接

完成工作包时同步实施计划勾选项、相关设计/命令与 `docs/reports/` 证据；只有实际执行并满足条件的项目才能取消 NOT RUN 或标记通过。UNKNOWN、PROPOSED 和未通过项须保留明确状态。

交接至少记录：完成范围、验证命令和结果、源码/配置/资产等可追踪标识、未解决问题及下一工作包。报告保存可版本化摘要和外部产物 hash，不把被忽略的日志或 runs 目录作为唯一结论来源。能力或入口变化时同步更新本文件，避免接手指引漂移。
