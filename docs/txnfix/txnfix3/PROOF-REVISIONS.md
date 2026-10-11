Receipts are immutable checkpoints; directory names record the pass, not a claim of acceptance.

- `final-*`: first full txnfix3 proof, binary `876db2f6b7421cbc0f79966bc65fac39348da561ed68e58b8f0071707bd64ada`.
- `release-*`, `identity-release`, `scatter-release`, `scatter-matrix`, `prepare-release`: second full proof, binary `a5b043c71974f4bda4472af265b036cd9f9345be071237df4bfc0777551dfe3f`. Four DB0 preparation shapes still added two instructions and prompted another placement change.
- `certified-*`, `identity-certified`, `scatter-certified`, `prepare-certified`: final branch-placement candidate. Results and acceptance limits are in the txnfix3 handoff, not implied by the directory name.
- `prepare-unlikely`: isolated object trial of the final branch hint. Both namespaces, 44 command shapes each, with no extra captured instruction in any named preparation/lifetime function. Full production rebuild follows the trial.
- Other `prepare-*` and `scatter-trace` variants preserve rejected compiler-placement trials and fixture corrections.

Large raw instruction traces, symbol ranges and GDB transcripts are stored with an added `.gz` suffix. The commands and result manifests retain their original output paths. `compressed-traces.json` maps the initial compression. Use `gzip.open(path + ".gz")` when the uncompressed path is absent. Compression changes no assertions or trace data.

The serverless fixtures link production objects directly. They start no worker/listener, use no offered load or timer, and count only the named scatter functions. They are disassembly-path evidence, not cycles/op or whole-operation instruction measurements. Literal universal sequence identity requires more than these sampled traces.
