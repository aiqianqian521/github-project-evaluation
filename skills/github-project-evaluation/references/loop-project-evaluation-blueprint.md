# Loop 驱动的“发现 → 评估 → 测试 → 交付”设计（v0.1）

状态：**设计稿，不是已实现的端到端能力**。本阶段只收尾 GitHub 项目发现、二次评估与测试；短剧、量化、漏洞防御仅用来检验骨架可替换性，不在这里建成业务系统。适用 Loop-dev `loop-dev-0927_release_20261019.zip`；冻结版本、运行环境与已通过的局部测试见工作区 `work_ooda/20261022-fixed-mode-v2/CLOSEOUT.md`。仓库中的历史 Runner 路径不是服务器已安装能力。上线前须按下述门禁重新验收。核心原则：Loop 编排与追踪、Skill 限定步骤、LLM 提案与解释、工具产生可核验事实、人类批准高风险动作；缺任何一层不许靠语言结论补齐。

三类场景的**优化版设计**及大循环训练/回归/晋级契约见 [Loop 大循环训练架构 v2](loop-training-architecture-v2.md)；它补充本页的 G0–G8 骨架，不表示视频、漏洞防御或量价系统已经实现。

## 1. 目标、非目标与完成定义

输入用户目标与约束，输出可审计的“角色/能力需求 → 跨来源候选 → 冻结仓库 → 许可/源码/构建/业务真值/韧性/本地压力 → 对比决策”，允许任何阶段按证据 FAIL/BLOCK，给出下一步及负责人。用户可以更换领域和验收 oracle，而不用重写发现、身份冻结、证据账本及 Loop 控制流程。“终极流程”指**可复用门禁模式**，不是一个适用于所有项目的固定测试题；例如短剧画面可用率、交易回测的未来数据与补丁回归并不存在同一个真值。

完成条件（每个需求场景独立判定）：需求/授权明确、每个关键能力对应独立可重复 oracle、选中候选已锁 commit 和许可、受控运行所有必需门禁、每条结论绑定日志/哈希/版本、独立审核人签字。找不到合格项目允许结论“无推荐 + BLOCK/FAIL”，不能通过减弱标准强制输出赢家。发现 COMPLETE 仅代表**所请求来源的有界页面**完成，不代表全网无遗漏，更不代表项目可用。

非目标：绕过站点 403/429 或 robots；把缓存、榜单星数、作者测试、Loop Verify 当作独立真值；在默认无沙箱的 Loop 进程直接执行未知仓库；无授权上传服务器、下真实订单或访问未授权安全目标；为凑三轮 PASS 擦除前一轮 FAIL。

## 2. 现有能力和必须补齐的断点

| 能力 | 当前证据及实际边界 | 设计动作 |
| --- | --- | --- |
| 发现/去重 | `scripts/discover.py` 支持多源检索、有界翻页、缓存、来源缺口与候选；受限目录/同运营方镜像不能视为独立全网佐证 | 复用其 `project-discovery.v1`，扩展多查询按角色覆盖；不改变既有状态含义 |
| 仓库首轮评估 | `scripts/evaluate_first_pass.py` 已能对本地冻结工作树**只读**统计 README/Start、许可、依赖、代码、测试与 CI 的证据完整度；`scripts/loop_first_pass_runner.py` 已能在 Loop 原生 Act **离线 site/有限 multi 缓存 → 首评**，人工目标适配度另见 `references/first-pass-evaluation.md`。它不能做在线多源搜索、认证上游 SHA 或证明功能 | G3 产出静态评分+证据索引+人工复核卡；离线 multi 的缺源仍 PARTIAL，不能充当全网覆盖 |
| Loop 原生 Act | `scripts/loop_discovery_runner.py` 用 `TaskRunner` 跑 `online → snapshot → negative`，落 `discovery-state.json` 和候选哈希；**只查询 site 来源**，不是多源深评 | 增加任务级 `EvaluationRunner` 或分阶段 runners，接收结构化需求/审批票据，调用多源发现及后续只读/受控工具 |
| 本地三轮 | R7–R9 中每轮 5 次直跑/5 次 Loop 原生 Act 和结构/跨域测试通过 | 只认 Skill 本地边界证据；仓库自带测试/真实业务 oracle/容量仍 BLOCK |
| 历史仓库评估器 | `work_ooda/20261020-loop-eval/skills/evaluate-repositories-with-loop/scripts/project_eval_runner.py` 已有**限定四个固定仓库**的 `screen/self/project` Runner；它把“记录已写”映射为 Loop business passed，即使自身结果为 INCOMPLETE，也不是通用仓库验收器。`work_ooda/20261021-skill-cycle-v4/design-project-tests/scripts/loop_native_test_runner.py` 能驱动预审命令，但本身不是业务 oracle/OS 沙箱 | 复用两者的边界与证据格式，不直接升级为生产深评；在新 TaskRunner 中分别接入身份、许可、独立真值及受限 worker，明确版本和测试域 |
| 模型与修复 | Loop 能装载固定 `agent_prompt` Runner、返回分层 `TaskResult`；已有发现 Runner 是确定性 Python，而非任意领域 LLM 评估器 | 可配置 LLM 用于拆解和提案；每次建议必须经过代码/工具/独立 oracle 验证；缺 LLM 时只允许确定性步骤，不假装会理解开放式任务 |
| 权限与恢复 | Loop 可保存事件/检查点，发现 Runner 在阶段开始写 `INTERRUPTED` 且拒绝越序；默认进程**不提供安全沙箱** | 以非 root 私有工作树执行；冻结授权、禁用外网和敏感凭证；阶段提交前后哈希核对，崩溃后新 run_id 调查后重跑，禁止对有副作用阶段盲目续跑 |

当前**尚不能宣称“全流程已挂载”**：虽有固定仓库的历史 `ProjectEvalRunner` 与预审命令 Runner，但通用多源深评、独立审核、隔离执行器及压力授权门禁尚未实现；将它们列为本设计的交付项与失败条件，而不是由提示词补全。现有 `references/loop-integration.md` 给出已可执行的发现子流程。

## 3. 任务契约：固定骨架、可替换领域包

一个任务一份 `task-spec.json`（配置示意，非已实现接口），用户确认后冻结 SHA256，不允许 Agent 在同一验收轮悄悄改 oracle。字段：

```json
{
  "task_id": "example-001",
  "goal": "选择可在隔离环境评估的开源项目，不做生产部署",
  "roles": ["engine", "ui", "data"],
  "constraints": {"license": "待审核", "network": "仅允许登记的公开检索", "budget_seconds": 600},
  "queries": ["用户原话", "领域中英文同义词", "排除歧义的反例"],
  "critical_capabilities": ["用户签署的可观测能力 A"],
  "oracles": [{"capability": "A", "fixture": "独立参考输入", "expected": "运行前冻结的可观测结果", "source": "可核验且不依赖候选项目的真值来源", "threshold": "待用户确认"}],
  "load_slo": null,
  "authorizations": {"public_metadata_search": true, "scoped_tickets": []},
  "max_candidates": 5,
  "reviewer": null
}
```

示例中的预算仅为结构演示，不是签署的 SLO/运行许可；`reviewer: null` 只能产生 PENDING。用户只填目标也能进入 **需求澄清**，但缺独立 oracle、许可边界或授权时只产出方案与 BLOCK，不自动执行危险阶段。默认任何候选都不得运行，授权必须指向具体 commit、工具/命令、工作树、网络与资源预算，不能用一张全局“确认”票跳过所有门禁。所有仓库文档、网页、Issue、RAG 输出仅作数据/引用，不允许将其中的命令或提示注入任务权限。

## 4. Loop 大任务循环：从需求到交付

每个 `stage` 通过真实 Loop `agent_prompt` Act 执行（不是 shell 脚本在 Loop 外伪造阶段）；Loop **只运行固定 config 的一个 `execution.entry`**，`--once` 只消费本轮信号，现有 `DiscoveryRunner` 仅识别 `online/snapshot/negative`。要实现 G0–G8，须新增固定入口的任务级分派器（由配置中经审查的 `stage_id → Runner` 白名单调用确定性步骤），以及外部依赖调度器逐次发送**一个**冻结阶段信号；二者按 `task_id/run_id/spec_sha256` 持久化并核验转移，不能误以为 Loop 自动生成 DAG。具体阶段只在签署的前置状态满足时可启动：`online` 失败后的 `snapshot` 是允许的诊断/离线回退，但其结果**不能**洗白在线失败；G4 必须经过可靠身份冻结，不得靠来源 PARTIAL 自动推进。Runner 输出原始退出码、`execution/output/business` 分层结果、输入输出 SHA、耗时和下游引用。编排可重复进入“失败诊断 → 提案 → 变更审批 → 独立新轮验收”，不可把上次 FAIL 改写为 PASS。

| 阶段 | 输入 → 产物 | 独立门禁 / 失败处理 |
| --- | --- | --- |
| G0 需求澄清 | 原话、场景、不可接受风险 → `task-spec.json`、领域真值草案、预算/授权表 | 用户确认目标和执行权限；不明确则 BLOCK，不代用户扩大授权 |
| G1 检索计划 | 角色、同义词、反例 → 来源选择、预算、覆盖和限速计划 | 多站同运营方不重复算独立佐证，403/429 不绕过；无来源则 PARTIAL |
| G2 多源发现 | 冻结查询 → `candidates.json`、`SHORTLIST.md`、来源/缺页账本 | Schema/哈希/跨页去重；`acceptance=NOT_REVIEWED`；**P1 实施后**原生阶段调 `discover --source multi`，不可用时保留单源缺口与 `local-unverified` 标记 |
| G3 首轮仓库静态评估与用户选范围 | 候选及经批准的冻结本地仓库 → README/Start、许可/manifest/源码/测试/CI 证据完整度和人工目标适配度评分、排除原因、上限 3–5 个目标 | 可通过 Loop 原生**离线 site 或有限 multi 缓存子流程**只读执行自动证据分；缺源仍 PARTIAL，人工目标适配分、在线多源验证仍另行完成；站点分数不能替代仓库能力/上游许可核验；仅可标 TEST_DESIGN_ELIGIBLE，绝不直接准许安装/部署/压力 |
| G4 身份冻结及静态深评 | 上游身份、固定 commit、锁文件、许可/CI/关键代码 → 每仓证据表 | 本地快照哈希不是来源认证；每条站点/缓存引线独立核上游身份并保留 `local-unverified`，GitHub 不可达则身份 BLOCK；代码只读，不执行 README 内命令；建立独立业务 oracle 与限额 |
| G5 隔离功能测试 | 审批命令和依赖、离线 fixture → stdout/stderr/exit/日志/结果哈希 | 仓库代码仅在**单独的受限 worker**（容器/VM 的实际 OS 隔离、只读挂载、无凭据、默认断网、进程/内存/时限）执行；Loop 进程只编排，未知依赖脚本先审；不能落实隔离即 BLOCK，不得用非 root 冒充沙箱；独立 oracle 缺失亦 BLOCK |
| G6 故障/容量测试 | 签署单位/SLO/预算 → 内存、耗时、错误/恢复、重试与压力数据 | 未签阈值不做压力；在 worker 的网络出口限定本地地址且执行时核验最终目的地、限制并发/请求总量，监视止损开关；禁止借配置生产 URL 打向外网；不向 GitHub/榜单注入负载 |
| G7 对比与审核 | 所有原始证据 → 逐能力 PASS/FAIL/BLOCK、风险排序、建议 | 推荐仅对冻结版本/用途成立；独立审核员签署，冲突先归因，不得让 Loop Verify 单独签批 |
| G8 归档/后续集成 | 评估报告/哈希清单 → 可下载包、复现脚本、责任人与下一轮提案 | 交付件包含证据/未知与再测入口；部署、二次开发是**另一张任务票** |

循环规则：对可恢复网络错误最多按配置预算重试且遵守 Retry-After；权限拒绝/robots/许可证/关键 oracle 缺失立即 BLOCK；独立反例 FAIL → 保留失败证据、新版本/新 `run_id` 提案后重测；同一版本连续失败不得自动降级 oracle。结束条件 `all(critical_gates == PASS) && reviewer_approved`，或明确 `FAIL/BLOCK + 风险、缺口、负责人、下一步`；`max_rounds`/预算耗尽也以 BLOCK 退出。成功定义是**可信交付**，不是必须全部变绿；不可从 Runner 的 `business=passed`（可能仅表示“评估记录写出”）推导候选仓库获准。

## 5. 运行和证据契约（拟实现）

建议非 root 工作树：`legacy internal test-server assets/loop-evaluations/<task-id>/<run-id>/`（本地开发用工作区同构目录），不用服务器 `/tmp`。每次运行独立 HOME/TMPDIR/SQLite、缓存与只读源码快照；禁止缓存目录符号链接，日志脱敏，不打包凭据。目录模板：

```text
run-id/
  input/task-spec.json             # 用户确认后冻结
  input/source-manifest.json        # Loop/Skill/fixtures/候选 commit 的 SHA
  stages/G0..G8/<stage-id>/        # 原始命令、退出码、stdout/stderr、输入输出哈希
  state/ledger.jsonl               # 只追加；stage_id/attempt/idempotency_key/依赖
  state/checkpoints/               # 检查点只是恢复线索，不是验收
  reviews/<candidate>/             # 静态清单、oracle、功能/故障/容量证据
  deliverables/                    # 结构化 verdict + 人读报告 + 清单
```

以**正交字段**记录 `coverage=COMPLETE/PARTIAL`（指定有界来源及范围）、`execution=NOT_STARTED/RUNNING/INTERRUPTED/PASS/FAIL/BLOCK/SKIP`、`candidate_acceptance=NOT_REVIEWED/PASS/FAIL/BLOCK`、`review=PENDING/APPROVED/REJECTED`；任何候选的 PASS 不得从 coverage、Loop Verify 或“记录已写”提升。账本每条携 `candidate_id`、`commit`、`task_spec_sha256`、`oracle_sha256`、`runner_version`、`permission_ticket`、`started_at`、`ended_at`、`exit_code`、`artifact_sha256`、错误类别与人工审查签名；目标候选整体 FAIL 优先于 BLOCK，任何关键门禁 BLOCK/审核 PENDING 均不得 PASS。

授权票由独立审批者签署并在**每次 Act 前**机器核对签发者、有效期、撤销状态及 `task_id/run_id/spec_sha256/commit/lockfile_sha256/命令+参数摘要/worker 身份/出口策略/资源和费用上限/阶段`；任一变化使票失效，不得由 Runner 自己为自己审批。只追加的账本不是防篡改来源：PASS 前将完整输入/输出/退出/授权/日志哈希形成清单，先写本次独立 attempt 的临时目录、校验后原子发布，并将摘要登记到独立只读位置；不存在可信外部锚点时证据来源维持未验证。崩溃后的 `RUNNING/INTERRUPTED` 不自动推进：校验所有产物和副作用、隔离本次 attempt，获取新授权后以新 `run_id` 重跑；**发现 Skill 的 `--once` 阶段复用已改为核验本地配置/脚本/快照/缓存/先前报告摘要**，但本地可写账本和缓存并非独立来源，Loop 核心 `--resume`、跨进程副作用及授权票仍未审计。`orchestrator.py --once` 与 `--resume` 不是同一恢复路径，不得把 Loop checkpoint resume 当作副作用安全重试。进程、输出 Schema、业务 oracle 三层分离。以 `project-tests.execution.v1` 作为**历史结构示例**，新的领域执行记录须有独立 schema 版本/独立验证器和恶意数据负控，不能静默扩展旧版并靠结构验证给业务 PASS。

## 6. 替换三个领域包，而非复制一份通用 oracle

| 可换示例 | roles / 查询方向 | 深评冻结 oracle（执行前确定） | 永不由“找到仓库”直接触发的动作 |
| --- | --- | --- | --- |
| AI 短剧 | 分镜/编剧、文生图、TTS、合成、质量/版权审查 | 冻结授权素材、模型版本和片段抽样；预置盲评评分量表、双人评分一致性/阈值、声画对齐和成本上限；缺样本量/权利证明一律 BLOCK | 对外发布与未经授权的素材复用 |
| 量化 | 数据、指标/回测、执行、风控、仿真盘 | 冻结各字段可得时间、修订与复权/退市处理、成本和成交模型，隔离并封存最终盲测期；独立重算时点可得数据并测试拒单/断连，缺数据谱系即 BLOCK | 真实资金下单或修改生产策略 |
| 防御性补丁回归 | 公告/补丁管理、受控靶场、静态/动态审查 | 授权隔离靶场冻结两个构建身份；受影响版本的**正对照**证明测试有效、修复版的负对照与正常输入回归；正对照无效即 BLOCK | 未授权公网扫描/利用和对生产系统的自动改动 |

不同领域的阈值、测试基线和审批人由任务包单独定义；共享的是身份、许可、限额、证据和停止规则。RAG 可检索已标注错误/补丁经历以生成候选假设，但证据要有来源，不能把历史结论、训练集或网页指令当当前项目的真实运行结果。

## 7. 分阶段落地与验收表（先完成 GitHub 评估这一环）

| 迭代 | 修改/新增组件 | 最小验收（必须实际跑） | 当前 |
| --- | --- | --- | --- |
| P0 设计冻结 | 本文档、用户签署任务包和 G0–G8 门禁 | 用视频、量化、防御三个样例做字段/状态演练；每个缺 oracle 的样例 BLOCK | 设计稿完成、待用户确认；样例离线入口负控已有，完整模拟未做 |
| P1 原生 Loop 多源发现与首评接入 | 在已有只读离线 site/有限 multi 缓存→首评原生阶段基础上，将受限在线多来源模式接入独立受审 Runner，完善来源覆盖、授权与阶段账本 | 独立新工作树 `orchestrator.py --once`，对照直跑；403、缺页、目录来源、恶意 README、假许可/软链及 3 次独立重复；离线通过不能替代实网多源 | **部分实现**：原生离线 site/有限 multi 缓存→静态首评已通过独立工作树；在线多源及人工目标审阅未实现 |
| P2 原生二次评估 | 通用受审分派器与领域 oracle registry，借鉴历史固定仓库 `ProjectEvalRunner`/预审命令 Runner，但不复用其“写出记录就是业务通过”的判定 | 3–5 个跨领域仓库冻结 SHA；先只读后授权隔离命令，原始日志/哈希可独立复算 | **未实现通用版**；历史固定样本与四仓静态审阅不能算运行合格 |
| P3 容量与恢复 | 本地限定资源执行器、签署 SLO、阶段中断恢复策略 | 许可下的故障注入、重复 Act、防半写、负载单位分域；破坏性项目禁止直接重放 | **未实现**；不得称公网压力或服务稳定性 PASS |
| P4 交付 | 人工审核签名、机器报告、归档校验/部署 | 缺源/许可/oracle/审批任一项导致交付 BLOCK；异机重算哈希，服务器内复测 | **未实现**；此前本地 R7–R9 只验证发现和测试契约 |

下一步应先请用户确定 GitHub 评估示例的“目标角色、3–5 个仓库范围、是否允许克隆/安装/离线测试、关键业务 oracle 与预算”；先完成 P1 的 Loop 原生多源接入并跑负控，再逐个推进 P2，**不要现在用三条业务示例宣称已完成全自动化**。

## 8. 实施前冻结的致命反例与停止条件

下面是**未来 Runner 必须通过的负控设计**，本稿完成不等于它们已执行；每条用独立新运行目录保留原始退出码和证据。

| ID | 输入/破坏条件 | 必须观察到的结果 |
| --- | --- | --- |
| D-01 | 给当前 site-only Runner 一个 `G5` 信号；或跳过身份冻结直接调 G5 | 目前应 `stage_invalid`；P2 分派器上线后须阻断越级执行，而不是调用外部仓库代码 |
| D-02 | G2 网站缺页、离线缓存页面和本地摘要被同时替换、GitStar 目录正常返回 | 缺页或目录范围仍 PARTIAL；缓存 `local-unverified` 一直传递到候选，G4 无上游身份则 BLOCK，不能伪造完整性或全网认证 |
| D-03 | G4 同名仓库更换 commit、锁文件/命令摘要改变、旧审批票重放/过期/撤销 | 在任何安装/执行前拒绝票据；生成新 attempt 和签署请求，不复用旧 PASS |
| D-04 | 恶意依赖安装脚本读宿主凭据/写外部路径/向公网通信；本地负载配置含外网生产 URL | 无凭据的隔离 worker 拒绝访问/出口；资源或目的地突破即停止、记录 FAIL；没有 worker 或观测证据则 BLOCK |
| D-05 | 写了部分 stdout/报告后强制终止，再原路径复跑；或篡改已发布报告 | `INTERRUPTED` 不提升 PASS；先逐项核哈希及副作用，旧 attempt 隔离，新的 `run_id`/授权后再执行 |
| D-06 | Loop Act 返回 `completed/business=passed`，但仓库独立 oracle FAIL；或审核仍 PENDING | 发现/记录可成功，仓库准入必须 FAIL 或 BLOCK；Loop Verify 不得为候选签名 |
| D-07 | 视频只给一段样片、量化数据含未来修订、防御靶场正对照未触发 | 缺盲评统计/时间可得性/有效正对照即该能力 BLOCK，不得借另一个领域的绿灯填补 |
