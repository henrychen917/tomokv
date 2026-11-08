# Tree formatter

Run `make format` after C/C++ edits and `make format-check` before committing.
Both use pip's **clang-format 18.1.8**, installed in `build/clang-format-18.1.8/`.
`make format-setup` installs it independently. The system formatter is never used.
The installation uses the system pip's `--python` option, so Python's optional
`ensurepip`/venv packaging is not required.

`tools/format-files.txt` is the sorted, explicit scope: maintained C/C++ files in
`src/`, `tests/` and `tools/`. Add new maintained files to this list. Vendored code,
the three generated command metadata files, archived tools, historical `docs/`
snapshots, and `scratch/`, `scratchpad/` and calibration experiments are excluded.
No recursive file discovery runs during formatting or checks. Offending paths
are printed in manifest order, and a failed check exits nonzero.

The configuration preserves include and definition order, literal spelling,
qualifiers, braces and comment text. The driver verifies raw preprocessing tokens,
raw literal spelling and tool-comment token boundaries before writing any file.
Lua/raw strings and help texts therefore remain eligible without editing their
contents. The file list also rejects generated-file headers and archive/vendor
directories.

The R7 generated regions have `clang-format off/on` guards immediately outside
their BEGIN/END markers. `make format` formats their handwritten inputs, then runs
`tests/r7shadow_sync.py --write`. Only that generator writes those regions.
`make format-check` checks formatting and R7 token parity without writing source.

`measure_style.py` measures the frozen baseline. `compare_formats.py` compares the
three configurations in disposable directories under `build/readability-a2/`.
The lane report records the measurements and the binary/token/tool proof.
