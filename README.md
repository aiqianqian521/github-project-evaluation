# GitHub Project Evaluation Skill

一个自包含的 AI Agent Skill：跨源发现 GitHub 开源项目 → 冻结仓库静态首评 → 项目专属测试设计（授权后隔离执行）。由原 `discover-open-source-projects` 与 `design-project-tests` 两个 Skill 于 2026-11-06 合并为单一 Skill `skills/github-project-evaluation/`。

任何分数、设计文档或回归通过都**不等于**业务验收：`PARTIAL`、`identity_gate=BLOCK`、`deployment_test_gate=BLOCK` 必须原样保留，禁止把 NOT_RUN/SKIP/BLOCK 写成 PASS。

## 平台支持矩阵

| 能力 | Windows | Linux | macOS |
| --- | --- | --- | --- |
| 离线阅读/验哈希/回归 | 【已验证】203 用例真机（198 通过 / 2 失败 / 3 跳过） | 【静态验证】POSIX 原逻辑保留，未真机验证 | 【静态验证】同左 |
| 搜索/首评/上游核验 | 【已验证】真联网冒烟（30 行候选；identity_gate PASS/VERIFIED） | 同一代码路径 | 同一代码路径 |
| 文件锁/权限位语义 | 【模拟验证】ACL 模拟 chmod/flock（`_wincompat.py`） | 【原生】fcntl + POSIX mode | 【原生】同左 |
| 输出体积硬限（RLIMIT_FSIZE） | 【不可翻译】2 项回归失败为此豁免 | 【原生】 | 【原生】 |
| bubblewrap 隔离集成 | 不适用（跳过×3） | 需 BWRAP_BINARY | 不适用 |

Windows 命令用 `python`，Linux/macOS 用 `python3`；需 Python ≥ 3.11 与 Git。

## 快速开始

```sh
# 1. 完整性校验（本目录）
python -B tools/verify_release.py          # 应输出 mismatched: []
python -B tools/doctor.py --profile core   # portable_unit_ready: true

# 2. 全量回归（portable 档，无需外部依赖）
python -B tools/run_tests.py --profile portable --output ../r4-tests
#    预期：203 发现 / 198 通过 / 2 失败 / 3 跳过（2 失败为 Windows 无 RLIMIT_FSIZE 的既有豁免）

# 3. 真实功能冒烟（联网）
python -B skills/github-project-evaluation/scripts/discover.py markupsafe \
  --source github --max-pages 1 --verify-top 3 \
  --cache-dir ../private-cache --output-dir ../smoke-search
python -B skills/github-project-evaluation/scripts/evaluate_first_pass.py <frozen-checkout> \
  --expected-repo pallets/markupsafe --discovery-file ../smoke-search/candidates.json \
  --output-dir ../smoke-firstpass --verify-upstream
```

搜索只做公开元数据与静态证据盘点，**不在评估阶段运行目标项目任何脚本**。

## 仓库结构与阅读顺序

| 内容 | 入口 |
| --- | --- |
| Skill 本体（SKILL.md → Stage A 发现/首评，Stage B 测试设计/授权执行） | `skills/github-project-evaluation/SKILL.md` |
| 发现→测试的阶段交接契约 | `skills/github-project-evaluation/references/discovery-handoff.md` |
| 交付门禁与合同 | `handoff/HANDOFF.md`、`handoff/CONTRACTS.md`、`handoff/ENVIRONMENT.md` |
| 机器验收账本与来源清单 | `handoff/ACCEPTANCE.json`、`handoff/PROVENANCE.json`、`handoff/COMPONENTS.json` |
| 输出示例 | `examples/` |

> 本仓库是**精简发布版**：内部交接包中的历史证据目录（`audit/`、`process/`、`guides/`、`evidence/`）与历史入口文档（RELEASE-INDEX、START-HERE、VERIFICATION、PROCESS-GUIDE、HANDOFF-STATUS、BASELINE-START-HERE-r2）不随本包发布。`handoff/` 文档中提及这些路径的地方指内部交接包语境，不影响本包任何命令运行。

## 不可误用的边界

- 静态首评分数只是证据覆盖度；未完成目标适配人审与上游身份核验前，`deployment_test_gate` 保持 BLOCK。
- 测试设计（DESIGN）与执行（EXECUTE）必须分开授权；压力/安全测试不得自动开跑。
- Native runner 不是沙箱；执行第三方代码前必须外部提供隔离、审批与资源限制。
- 缓存目录必须为调用者私有的 `0700` 目录；权限不安全会被拒绝而不是被静默修改。

## 分发与授权

本 Skill 的权利归发布者本人，按发布者仓库声明的许可证分发；见 `LICENSE-NOTICE.md`。第三方项目源码对象（如 MarkupSafe bundle）与公司内部 SOP 材料已从本精简包剥离；引用它们的历史证据文档不再随包发布。

## 本次发布版的实测验证账本（2026-11-06，Windows 真机）

- 合并前基线 vs 合并后：203/198/2/3 全等（零新增失败，零引用残留）
- `verify_release`：mismatched=[]；`doctor core`：portable_unit_ready=true
- `offline_acceptance`：PASS（discover/clone/first-pass/design 离线重放）
- 真实冒烟：搜索 30 行带 provenance；首评缺 origin → BLOCK(62)，补 origin+`--verify-upstream` → PASS/VERIFIED(72)
- 两次打包 sha256 一致（见 `SHA256SUMS` 旁车的 `.sha256` 文件）
