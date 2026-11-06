# 模型首评结论的机器复核门禁

真实仓库试跑曾出现：静态首评 `goal_fit=NOT_REVIEWED`、`deployment_test_gate=BLOCK` 且作者完整测试 exit=1，但 Claude 草稿仍写“合格部署”。LLM 是证据解释助手，不是有权签发部署/压力测试的裁判；保留原始草稿，不修改作者测试或门禁来迎合措辞。

对每个仓库保留原样的 `FIRST-PASS.json`、模型草稿 `review.txt`、原生测试机器记录（如有），在**仓库外的新目录**执行：

```sh
python3 scripts/audit_reviewer_claim.py --first-pass <FIRST-PASS.json> --review-text <review.txt> --execution <TEST-EXECUTION.json> --output-dir <fresh-audit-dir>
```

没做原生测试时省略 `--execution`，审核仍记录缺口。脚本只读、限制每份输入 256 KB，拒绝软链和已存在的输出目录，生成 `REVIEW-AUDIT.json` 并以 **exit 2（BLOCK）** 结束；非法输入以非零错误退出，不可被当作 PASS。它记录文件 SHA、仓库身份、关键门禁以及可能宣称放行的措辞；中文关键词检查是**保守风险提示**，遇否定句也可能误报，不能把“未命中”解释为批准。汇总系统必须**仅以机器决策和独立复核为准**；有关键词矛盾时必须向用户说明并标 P0 评估缺陷，禁止复制草稿中的部署结论为建议。

`FIRST-PASS.json` 是静态文件完整度而非业务真值；`--execution` 的单份记录必须对应同一 `repository@commit`、完整原生退出码和独立人审签署。现有跨仓聚合记录没有该绑定，必保持 BLOCK。即便将来单仓所有字段均为 PASS，此审计器也**不能批准部署**：目标适配、上游身份、许可与后续隔离执行的独立人类签收属于其他阶段，需额外单独授权和设计相应机器放行门禁。
