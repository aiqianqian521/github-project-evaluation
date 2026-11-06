# Loop 原生首评（已实现的离线、有界子流程）

`loop_first_pass_runner.FirstPassWorkflowRunner` 是单一 `agent_prompt` 固定入口，**只有** `discovery → first_pass` 两阶段。当前发现阶段以 `.query` 与 `page-N.html` 离线快照为输入，默认解析 Kaiyuanbang `site`；也可指定离线 `multi` 读取**已有**跨源缓存，缺少来源应如实 `PARTIAL`。只要预期 `owner/repo` 确实出现在已有来源中，就允许对被批准放在私有根下 `checkouts/<name>/` 的干净 Git 工作树做**初步**静态首评；发现缺页/多源缺口必须保留，不会因阶段完成被改成 COMPLETE。它**不自动克隆**、不访问公网、不安装依赖、不执行候选仓库代码、不做人类的目标适配评分。此子流程不能代替在线 `--source multi` 的覆盖、上游 commit 认证或后续部署/压力测试。

## 冻结工作树与运行

按项目建不复用的私有非 root 目录 `legacy internal test-server assets/loop-evaluations/<task>/<run-id>/`（本地可用工作区同构目录），创建 `snapshots/.query`、`snapshots/page-1.html` 等有界离线素材、`checkouts/<name>` Git 仓库、空 `evidence/`。工作树须无未提交/被忽略的计分文件，原 GitHub 身份另由独立人工/上游证据核对。写 `workflow.json`：

```json
{
  "root": "legacy internal test-server assets/loop-evaluations/task/run-id",
  "checkout": "legacy internal test-server assets/loop-evaluations/task/run-id/checkouts/name",
  "expected_repo": "owner/repo",
  "query": "搜索词（与 snapshots/.query 相同）",
  "max_pages": 1,
  "source_mode": "site"
}
```

Loop 配置 `task.execution.type=agent_prompt`，`task.execution.entry=loop_first_pass_runner.FirstPassWorkflowRunner`；`runtime.root` 指向独立 `projects/first-pass-task`，每次信号文件必须且仅有一个对象：`[{"signal_pattern":"discovery"}]`，第二轮改 `[{"signal_pattern":"first_pass"}]`。在 `loop-engine/` 下依次运行 `python3 orchestrator.py --config <config> --once --signals <discovery-signal>` 和同命令的 `<first-pass-signal>`；设置 `LOOP_FIRST_PASS_CONFIG=<workflow.json>`、`PYTHONPATH=<skill>/scripts:<loop-engine>`，以及隔离的 HOME/TMPDIR/SQLite。`--once` 不等于 `--resume`，不要重放有疑问的阶段或跳过权限检查。可对照工作区 `work_ooda/20261022-fixed-mode-v2/run_first_pass_native.py` 的脚本，使用固定 Loop 20261019 ZIP 生成独立测试树与直跑比较；脚本的 `example/demo` 是**虚构离线负载**，不是实际推荐仓库。

## 状态与不可越过的门禁

`evidence/workflow-state.json` 的状态 `INTERRUPTED/COMPLETE/BLOCK` 和每阶段输入、输出 SHA 是**阶段证据账本**；`evidence/discovery/candidates.json` 和 `evidence/first_pass/FIRST-PASS.json` 是独立产物。首评可输出 `REVIEW_CANDIDATE` 或 `HOLD`；这两种情况阶段都可能 `COMPLETE`，因为只意味着审查记录写入，`business.scope=evidence-record-only`，候选审批永远是 `NOT_REVIEWED`，`deployment_test_gate=BLOCK`。Loop Verify、`TaskResult.business=passed` 或自动证据 100/100 **不得**解释为项目质量 PASS。

重复 Act 只有配置、解析器、首评脚本、快照、发现产物的 SHA 均匹配且本地仓库仍符合干净树/提交/计分结果时才返回旧阶段记录；报告篡改、变更配置、仓库变脏或旧 `INTERRUPTED` 均 fail closed。一次中断/失败留下 `BLOCK` 与原始材料，不在原目录内清理重跑；调查副作用，按新运行 ID/工作树再试。静态审阅之后按 `first-pass-evaluation.md` 的人工目标评分和上游身份许可门禁出具报告；只有用户再授权的独立测试 Skill 才能在受限 worker 执行候选代码。
