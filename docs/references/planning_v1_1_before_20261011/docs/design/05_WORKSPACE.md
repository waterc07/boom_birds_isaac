# 目录与工作区

v1.1。用户已选择 E:\isaac\proj_boom_birds；当前仅文档/来源/规划工具，业务目录按工作包建立。[总纲](../../PROJECT_PLAN.md)为入口。

## 当前与未来目录的区别

v1.1补充拟建configs/mission/match.json及src/boom_birds/mission/match_context.py、identity、projectile_tracker/interception_skill；只在对应工作包建立。一项own_team配置派生敌我，不复制红队/蓝队两套源码。

已存在README、PROJECT_PLAN、BoomBirds.code-workspace、.gitignore、docs/design/decisions/planning/research/references、env/phase0-preflight、scripts/planning/calculate_budgets.py。docs/reports包含规划验收、自动核查和来源证据；env/planning-preflight保存只读WSL复核。tmp为下载/提取依赖和PDF预览，不是运行依赖。

以下为实施蓝图，尚未建立的文件不提供现成执行命令：

```text
proj_boom_birds/
  pyproject.toml                    实施时一个轻量主包，可选依赖组
  src/boom_birds/
    contracts/                     schema、坐标、时间，标准库
    runtime/                       state_adapter、supervisor、唯一px4_gateway
    capture/ perception/ geometry/  实时视觉
    navigation/ mission/ energy/    传统技能和任务
    dock/ storage/                 库内事件和数据
    evaluation/                    分层指标、失败原因
  configs/
    runtime/ vehicle/ sensors/     端点/限值、动力、安装与时延
    scenes/ mission/ rules/        3D布局、任务和赛季来源
    evaluation/                    冻结场景、回归与验收门限
    local.example.json             本机路径模板
    local.json                     本机实际路径，忽略Git
  env/                             宿主/提交/依赖/参数哈希和检查记录
  calibration/                     小型内外参与标定manifest
  scenes/                          小型布局和大资产索引
  data/                            数据manifest与划分，大原始数据外置
  models/                          模型卡/哈希/预处理，大权重外置
  runs/                            本地临时产物，Git忽略；归档到外置存储
  tests/contracts/ integration/    合同与真实链路验收
  scripts/planning/ experiments/   现有预算工具/后续试验入口
  docs/                            design/decisions/planning/research/references/reports
  learning/                        有证据触发后才建立独立训练适配
```

一个主包降低早期三包editable/版本同步成本；contracts不导入Kit/Torch/相机库；训练适配与主运行器依赖隔离。后续Isaac扩展单独环境，只依赖稳定合同，不要求Pi安装Kit/CUDA/ROS2。不用复制venv。

## 宿主与物理路径

Windows：现有IsaacLab与env_isaaclab保留；项目编辑/证据/离线预算在E盘短英文路径。WSL2：计划Ubuntu24.04，虚拟磁盘优先E盘，PX4源码在 ~/boom_birds/toolchains/PX4-Autopilot，运行代码在 ~/boom_birds/project，venv独立位于 ~/boom_birds/envs/runtime；均未创建。Linux构建不放 /mnt/e 或中文目录。Pi：部署时按验证过的同一主包提交创建独立ARM64环境，平台参数和端点独立配置。

大产物计划 E:\isaac\boom_birds_storage\{assets,datasets,runs,models,cache}，当前不创建空目录。运行先写WSL本地，再停止/刷新后按哈希归档到Windows；不对正在写的ULog直接当完整归档。cache可重建，原始录制/标定/模型/最终ULog不可当cache删除。项目与大存储同盘不是备份；正式数据需要额外备份位置及校验记录，未配置则备份NOT RUN。

小型、可版本化的运行索引放docs/reports/（包含外置位置/哈希/结果）；runs/按现有.gitignore排除，不能期待其中索引自动进入Git。

## 单一源码与版本交接

Windows项目为主编辑来源，WSL为固定提交运行检出；PX4独立工具链，不嵌入本项目源码。后续实施时初始化项目Git，当前未初始化/未提交，不伪造HEAD。

无远端也可用Git bundle：先把已审查变更提交，制作bundle并校验哈希，WSL导入对应提交；记录Windows提交=Linux实际运行提交，dirty状态必须显式拒绝晋升。这些是未来步骤，尚无bundle可调用。WSL修复必须形成commit/patch带回主项目，再以统一提交运行，禁止手工改两份。暂不授权远端push。

跨宿主传递代码用Git版本；数据用manifest/hash；环境分别锁，不复制venv和绝对路径配置。路径映射在local配置记录，业务代码不硬编码E盘。标定、坐标、配置schema变化绑定版本并重验影响阶段。

## VS Code和日常入口

BoomBirds.code-workspace保持当前单项目文件夹，不自动激活旧Isaac、启动仿真或解锁。S0实施后才添加对应解释器/测试/启动任务，任务必须注明宿主、环境和配置。日常流程：读首阶段→确认门→冻结配置→运行→归档日志→记录PASS/FAIL/NOT RUN→更新对应门。不得用最新一次PASS覆盖失败历史。
