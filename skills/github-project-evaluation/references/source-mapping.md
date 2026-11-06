# Provenance and safe reuse from `legacy internal test-server assets`

Inspected on 2026-10-21 on Loop host: `legacy internal test-server assets/README.md` and `00`–`05` Markdown guides; earlier Loop-only `skill-v3/skills/evaluate-repositories-with-loop/SKILL.md`. This mapping is a synthesis of those files, not independent validation of all their past run claims. Keep the originals unchanged.

| Original source | Reuse in this Skill | Do not transpose |
| --- | --- | --- |
| `00-总纲-项目完整测试标准与设计.md` | Project routing, T1–T8 and gated evidence before release | Its per-type “pressure N/A” for sandbox agents is not universal: a bounded load on a simulated queue or scanner may be useful with authorization. |
| `01-沙箱测试设计规范.md` | Sandbox is environment/permissions boundary; mark inaccessible cases BLOCK | `hostPID`, `nsenter`, host file mounts or privileged commands are not default setup. |
| `02-AGENT_TASK_TEMPLATE_终极版.md` | Predeclare criterion ledger, ID counts, independent expected truth and handoff | Its mandatory execution loops do not mean a design-only task ran any tests. |
| `03-测试判定与日志契约.md` | Match logs to actual emitted code; distinguish skip vs safe; source/build/runtime check | security-agent-specific flags, hard-coded paths, debug prefixes, historical sample secrets and `isvul` semantics do not apply to other projects. |
| `04-踩坑归档-容器版安全agent实测问题与解法.md` | Environment/tool limitations and hidden failures motivate negative cases | security-agent-dependent diagnoses are not proof about the user's new project. |
| `05-测试流程SOP-从下发到归档.md` | Environment→version live→execute→observe→judge→archive; every stage has a gate | Do not preemptively change hosts, replace daemons or mutate user accounts. |
| `skill-v3/skills/evaluate-repositories-with-loop/SKILL.md` | Independent result vs Loop Verify, concurrency artifacts, untested holdout | This existing Skill **runs/audits** Loop evaluation; the new Skill only **designs** cross-project functional and load tests. |

All source docs stay on the remote host; this portable Skill contains only a sanitized mapping, no credentials, internal IPs or raw logs. Follow user-specific `the legacy internal test server` (not `/tmp`) rule on this host; elsewhere respect that project's approved workspace and filesystem boundaries.
