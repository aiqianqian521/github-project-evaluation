# 测试边界

`loop_contract_fixture.py` 仅提供单元测试用TaskInput/TaskResult数据容器和空TaskRunner基类。portable测试驱动显式注入当前Python测试进程，**不安装、不提供真实Loop引擎，也不改变运行时适配器的真实import要求**。

测试验证适配器本地分支、真实无害命令、离线数据处理、签验算法和故障恢复判断；不验证外部调度、checkpoint或生产隔离。full档不注入该替身，必须满足真实Loop合同pin和Linux/bwrap检查；full仍不是调度器E2E。

回归输出有完整test ID与passed/failures/errors/skipped/import_errors。portable仅预期三项Linuxnamespace集成跳过；无OpenSSL时更多跳过使整体BLOCK，不会静默通过。
