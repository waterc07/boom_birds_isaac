# v1.2 文件架构与工作区

2026-10-11。主工作区E:\isaac\proj_boom_birds，已初始化独立Git并在p0-foundation分支推进，原v1.2资料已保存基线。已新增环境核查、标准库动作/时效合同及测试；本项目速度执行器、仿真任务和训练入口尚未实现。下方仍包含未实现目录蓝图，不创建空壳冒充实现。当前证据见[核查报告](../reports/p0/P0_ENVIRONMENT_REPORT.md)。

## 目录蓝图

```text
proj_boom_birds/
  README.md / PROJECT_PLAN.md / BoomBirds.code-workspace
  pyproject.toml                  单一boom_birds包，按sim/train/deploy可选依赖
  src/boom_birds/
    contracts/
      types.py                    观测/动作/目标/状态合同
      frames.py                   FLU水平框架、ENU/NED转换
      timebase.py                 时钟映射/年龄/到期判定
    sim/
      controllers/velocity.py     速度指令到仿真执行器
      tasks/reach.py              P1到点和停止
      tasks/avoid.py              P2静态避障
      tasks/return_dock.py        P4返程与机库
      observations.py             actor/critic观测明确隔离
      randomization.py            传感/动力/场景随机化
    learning/
      ppo_adapter.py              单一成熟PPO库接口
      policies.py                MLP/CNN/GRU策略构造
      export.py                  actor导出和隐藏状态接口
    runtime/
      observation_adapter.py     实际数据转同一观测schema
      policy_runner.py           推理与GRU reset
      supervisor.py              时效/限幅/质量/权限
      px4_gateway.py             唯一MAVLink发送器
      state_adapter.py           PX4状态质量与坐标重置
    capture/camera.py             实际采集、时间戳、有界队列
    perception/
      base_armor.py              基地及小装甲关联
      dock.py                    机库相对观测
    mission/
      state_machine.py           阶段/切换/失败处理
      match_context.py           own_team及目标映射
    dock/controller.py           机库末段运动控制
    evaluation/
      episodes.py                统一逐episode判定
      metrics.py                 成功/碰撞/延迟/能量
      manifests.py               版本/配置/数据索引
    interception/                D分支被启动时再建立
  configs/
    tasks/reach.yaml / avoid.yaml / return_dock.yaml
    agents/ppo.yaml
    observations/state.yaml / rgb_state.yaml / rgb_range.yaml
    vehicles/sim_reference.yaml / target_vehicle.yaml
    runtime/default.yaml
    mission/match.yaml
    evaluation/smoke.yaml / frozen.yaml
    local.example.yaml            路径模板，不含秘密
    local.yaml                    本机路径，Git忽略
  scripts/
    planning/                     已有文档/预算工具
    preflight.py                  环境/上游记录
    train.py / evaluate.py / replay.py / export.py
    run_sim_baseline.py / run_runtime.py
  tests/
    contracts/                    坐标、时钟、epoch、模型合同
    sim/                          reset/响应/终止/观测泄漏
    evaluation/                   指标分母、数据分割
    runtime/                      过期、重置、导出、仲裁
  env/
    manifests/                    宿主、依赖、上游SHA
    locks/                        每个宿主独立依赖锁
  external/                       固定版本上游检出，Git忽略
    NavRL/ DiffPhysDrone/          按需拉取，不默认安装
  third_party/NOTICE.md            复制代码许可与变更来源
  assets/manifests/               大资产URI与hash
  data/manifests/                 数据划分、来源、标注版本
  models/manifests/               权重、schema、预处理与限制
  calibration/                   相机/安装/传感标定小文件
  runs/                          本地实验产物，Git忽略
  docs/design/ decisions/ planning/ reports/ references/
  docs/superpowers/plans/         分阶段可执行清单
```

## 包与依赖边界

contracts仅用标准库及明确的基础数值依赖；不能导入Torch/Isaac/相机驱动。sim和learning只在训练环境加载。runtime部署环境不依赖Kit、仿真资产或训练优化器。不要为了单个训练函数安装ROS2、Gazebo、VisFly和整套NavRL运行链。

日志与测试按能力组织，不建立多层微服务或消息总线。默认同进程直接调用，仅当相机阻塞/推理争用实测需要时分离进程。所有新增文件随相应W包建立。

## 物理工作区与大文件

Windows为源码主编辑区，沿用现有Isaac解释器完成最小兼容检查，路径记入local配置。external检出只作上游对照；导入本项目的代码必须有来源SHA、许可和修改说明，不依赖运行时从external寻找模块。

大产物建议放E:\isaac\boom_birds_storage\{assets,datasets,runs,models,cache}，路径可配置，当前尚未创建。原始数据与最终权重不可当cache清理；同盘副本不算备份，P3前定义独立备份位置和hash验证。

PX4 SITL到P5再按当时兼容证据选择WSL2/Linux。若用WSL，源码与构建在Linux文件系统，模型/数据通过manifest交换；不复制venv。最终ARM机载环境单独锁定，Pi5只是既有验证平台线索，不是最终硬件约束。

## 版本与运行记录

P0已建立Git并保存v1.2规划基线，后续提交记录以实际Git历史为准。主干保持可运行基线，每个工作包独立分支；上游固定SHA，避免追随main。后续提交标题描述与正文使用中文，保留docs:/feat:/fix:等类型前缀，具体规则见根目录AGENTS.md。dirty运行允许调试，但不得晋升模型；正式run记录源码SHA、上游SHA、配置hash、资产hash、seed、环境、观测schema和结果。

每次运行有唯一run_id，目录内包括resolved_config、manifest、metrics、checkpoint索引、异常与可选视频。docs/reports保存可版本化摘要和外部产物hash；禁止只依赖被Git忽略的runs目录保存唯一结论。训练/验证/测试seed和场景分别登记。

机载模型发布必须带model manifest、预处理、动作限值、有效工作范围和回滚版本；切换模型同时重置隐藏状态。阶段性交付不自动推送远端或刷写固件。
