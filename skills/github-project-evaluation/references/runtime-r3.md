# r3 native runtime and handoff

The runtime still imports a real `adapters.task_runner`; no bundled fallback engine is provided. The distribution's portable tests use a clearly labeled, process-local test double, not production scheduling or integration evidence.

`native-test.state.v2` binds the original manifest bytes, source tree, Git HEAD/clean state when present, runner, selected executables, direct file argv and platform. Before replay it checks that binding and each recorded log. Changed inputs, corrupt/legacy state, symlinked records or orphan logs block without overwriting prior evidence. Start a new authorized run directory; do not reset a journal to replay side effects.

`status=completed` is only this stage. Inspect `raw_output.plan_status` and `remaining_stages`; `validate_output` is true only when every planned stage passed. Even then project verdict stays `NOT_ACCEPTED`.

Evidence must be outside the source, caller-owned and not group/world writable; HOME/scratch live inside evidence. Commands write no bytecode and logs are exclusive regular files bounded to 1,000,000 bytes each; hitting the bound fails the stage. This does not supply a sandbox, immutable runtime image, process-tree quotas or independent approval. Freeze the source in a separately audited worker; do not rely on snapshot hashes against concurrent hostile changes.

For a complete r3 bundle, use root `tools/doctor.py`, `tools/run_tests.py` and `tools/handoff_check.py`; installed Skill folders alone do not include those bundle-level tools. Example project-specific designs in the distribution are still DESIGN-only with pending independent review.
