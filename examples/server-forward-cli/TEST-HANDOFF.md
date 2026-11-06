# Markdown CLI 设计交接

设计完成 ≠ 测试通过；独立人员未签字，当前 **DESIGN-REVIEW-BLOCKED**。此三文档是本轮测试者按 Skill 手工编制的正控，不是模型或 Loop 自主生成的设计。

| source claim | source ref | design decision | verification still needed |
| --- | --- | --- | --- |
| 结构入口、状态、来源 | `work_ooda/20261021-skill-cycle-v3/design-project-tests/scripts/validate_design.py:29` | F-VALID/STATUS/ISOLATE | 独立审查者复核代码与入口 |
| 坏编码捕获、五项评审 | `work_ooda/20261021-skill-cycle-v3/design-project-tests/scripts/validate_design.py:36` | F-ENCODING/REVIEW | 验证没有修改已冻结负控 oracle |
| 执行门禁独立 | `work_ooda/20261021-skill-cycle-v3/design-project-tests/references/output-contract.md:1` | 不宣称结构校验等于语义 | 明确人审负责人 |

功能六项，压力七项，全体 NOT-RUN；高风险优先：缺评审、结构误放、坏编码；负载目标与资源安全上限缺签，全部 BLOCK。决策负责人：源码项目 owner TBD、测试隔离 owner TBD、性能/SLO owner TBD、独立审查者 TBD。下一步先批准隔离小规模功能测试，再单独批准负载；严禁对共享系统测拐点。

| check | reviewer | independent evidence | decision | owner/retest condition |
| --- | --- | --- | --- | --- |
| source existence and revision | TBD | 尚未有独立源码哈希复核 | BLOCK | owner 提供固定代码身份 |
| risk-to-case mapping | TBD | 作者映射不足以替代独立审计 | BLOCK | 测试负责人逐条对照风险 |
| independent oracle | TBD | 预设的退出码与拒绝条件待签 | BLOCK | 第三方认可负控 |
| load scope, SLO and stop | TBD | 无批准数值预算或杀停演练 | BLOCK | 容量负责人先批准 |
| secrets/redaction | TBD | 只有作者声明用合成数据 | BLOCK | 独立审查日志内容 |
