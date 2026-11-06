# Markdown 测试设计校验 CLI：测试设计（非执行结果）

## 项目画像与证据边界

目标是本地 `work_ooda/20261021-skill-cycle-v3/design-project-tests/scripts/validate_design.py:29`。CLI 读同目录的三个 Markdown，返回结构问题；它既不运行被测项目，也不判断文字真伪。身份以测试前上述脚本文件 SHA-256 冻结；此设计文档本身由测试者写成，不能当模型生成能力的证据。仅允许独立工作目录，无外网、无线上服务或金融交易。

## 功能风险地图

高风险：没有评审的设计误报合格、坏编码抛栈、误把 `BLOCK` 当执行状态、缺少独立判据的四列空壳放行。CLI 零退出码不是人工业务认证；oracle 来自冻结契约 `references/output-contract.md` 与外部预设负例，而非校验器对自身输出的赞美。

## 功能用例账本

| ID | 来源与风险 | 前置/输入/动作 | 外部期望及反例 | 原始证据及层级 | 执行状态 |
| --- | --- | --- | --- | --- | --- |
| F-VALID | 三份设计完整且评审未签 | 独立目录预置全部标题、六/五列案例、五项评审 BLOCK；执行一次 CLI | 仅结构上退出 0，交接须写 DESIGN-REVIEW-BLOCKED；任何业务 PASS 为失败 | stdout、stderr、退出码、文件哈希；CLI 契约 | NOT-RUN |
| F-REVIEW | 缺五项评审容易误放 | 删除 TEST-HANDOFF 的 review 表；执行 CLI | 退出 1，报告评审表缺失；退出 0 判失败 | stdout、stderr、原始 SHA-256；负控 | NOT-RUN |
| F-ENCODING | 坏编码应干净失败 | 第三文档写入非 UTF-8 字节并保持其余合法；执行 CLI | 退出 1、明确 unreadable，不能抛未捕获 traceback | 字节哈希、退出码、stderr；异常边界 | NOT-RUN |
| F-STATUS | 设计禁止已经执行的结论 | 一例状态单元改为 BLOCK 或 PASS；执行 CLI | 退出 1，报告缺 NOT-RUN 或误报执行判定 | 原始行、stderr、退出码；契约 | NOT-RUN |
| F-ISOLATE | 别覆盖其他输出目录 | 两个临时工作目录，同一脚本并发读取不同文档 | 返回码相互独立，三个原文件字节哈希前后不变 | 进程/文件哈希对账；并发 | NOT-RUN |
| F-PERM | 权限边界 | 用非特权账号只读输入目录，输出日志到独立目录 | 输入不可读或消失返回明确非零，不写源目录 | uid、权限、返回码与文件 hash；权限 | NOT-RUN（BLOCK：运行账号待确认） |

## 环境与准入

只读目标脚本，合成三份短文档写到独立的工作目录；先固定脚本与夹具 sha256，审查 `TMPDIR`、权限、进程限额。异常测试仅本地副本，不写 `/tmp` 或真实项目目录。未获得远端独立人审，不能关闭业务验收。

## 执行顺序与判据

获本地测试授权后先运行合法样本，继而五类变异、并发，再对输入哈希；示例 CLI 为 `python3 work_ooda/20261021-skill-cycle-v3/design-project-tests/scripts/validate_design.py <isolated-design-dir>`。退出 0 仅证明结构，负例必须退出 1；未运行就保持 NOT-RUN，缺目标或权限标 BLOCK（列明负责人/重试条件）。

## 准出与交付

六例设计、零例执行/通过。每次执行另建 run ID，保留脚本/夹具 hash、原始 stdout/stderr、返回码、用例到业务判据的独立复核；若 F-REVIEW 或 F-ENCODING 不符则禁止宣布门禁通过。交付脱敏原始记录，负责人待指定。
