# Gate harness self-tests

Final command (passed 72/72):

```sh
taskset -c 48-63 env GATE_TEST_PORT=20299 TMPDIR="$PWD/build/at412c/tmp" \
  python3 tests/gates_test.py
```

The first run during compiles/traces failed the scheduler fixture's 45-second
deadline (71/72). A quiet rerun passed 72/72. Both left GATE_TEST_PORT unset,
so brief harness guard sockets used kernel-selected ephemeral ports. That was
outside this lane's assigned listening-port range. Actual correctness servers
used 20200–20299. The final quiet rerun explicitly bounded the guard to 20299
and passed 72/72; the native proof runner now always sets this variable.
