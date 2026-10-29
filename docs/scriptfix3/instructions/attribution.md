# Commit attribution

Reverse the four scriptfix2 production commits while fixing every other e2b237926 object. Two overlapping later cold LIST/LOAD diagnostic hunks remain fixed in all arms; retained-cold-conflicts.json records them. All positive and negative subtotals are retained, including signature changes and address-dependent Lua table probes.

The full signed per-function ledger covers 96 no-header scripting cases per transition (both counting scopes, namespaces, modes and atomic settings). Each function subtotal sums to its cell delta, and the five transitions telescope from headline to PRE.

These representative tables use 1s, atomic=1. Lua table probes can change by a few instructions when cold edits move addresses; those observations remain in the ledger and are not evidence that the edited cold path executed.

## namespace / normal

| Transition | EVAL-single | EVAL-cross | EVALSHA-single | EVALSHA-cross | FCALL-single | FCALL-cross |
|---|---:|---:|---:|---:|---:|---:|
| integration bridge: fixed e2b237926 objects and later cold diagnostics versus the headline | -5 | -4 | +0 | -1 | +0 | -1 |
| 370210cfc: compatibility roots, including SHA normalization, flags and redis API selection | +691 | +287 | +1309 | +285 | +170 | -1 |
| 18191bcc1: preserve callback lookup keys on cold library refresh | +0 | +0 | +0 | +0 | +0 | +0 |
| 6bc147d2c: cold callable metadata and random arithmetic | +0 | +0 | +0 | +0 | +0 | +0 |
| cdd2c4673: retain formatted numeric arguments until dispatch returns | +0 | +0 | +0 | +0 | +0 | +0 |

## namespace / db0

| Transition | EVAL-single | EVAL-cross | EVALSHA-single | EVALSHA-cross | FCALL-single | FCALL-cross |
|---|---:|---:|---:|---:|---:|---:|
| integration bridge: fixed e2b237926 objects and later cold diagnostics versus the headline | +0 | -5 | +1 | -3 | -2 | -3 |
| 370210cfc: compatibility roots, including SHA normalization, flags and redis API selection | +675 | +290 | +1276 | +285 | +140 | -1 |
| 18191bcc1: preserve callback lookup keys on cold library refresh | +0 | +0 | +0 | +0 | +0 | +0 |
| 6bc147d2c: cold callable metadata and random arithmetic | +0 | +0 | +0 | +0 | +0 | +0 |
| cdd2c4673: retain formatted numeric arguments until dispatch returns | -10 | -5 | +0 | +0 | +0 | +0 |

## lua / normal

| Transition | EVAL-single | EVAL-cross | EVALSHA-single | EVALSHA-cross | FCALL-single | FCALL-cross |
|---|---:|---:|---:|---:|---:|---:|
| integration bridge: fixed e2b237926 objects and later cold diagnostics versus the headline | -5 | -10 | +0 | -8 | +0 | -8 |
| 370210cfc: compatibility roots, including SHA normalization, flags and redis API selection | +1256 | +969 | +1880 | +1600 | +1098 | +1099 |
| 18191bcc1: preserve callback lookup keys on cold library refresh | +0 | +0 | +5 | +0 | +0 | +0 |
| 6bc147d2c: cold callable metadata and random arithmetic | +0 | +5 | -5 | -5 | +0 | +0 |
| cdd2c4673: retain formatted numeric arguments until dispatch returns | +39 | +34 | +44 | +39 | +39 | +39 |

## lua / db0

| Transition | EVAL-single | EVAL-cross | EVALSHA-single | EVALSHA-cross | FCALL-single | FCALL-cross |
|---|---:|---:|---:|---:|---:|---:|
| integration bridge: fixed e2b237926 objects and later cold diagnostics versus the headline | +13 | +16 | +17 | +18 | +15 | +21 |
| 370210cfc: compatibility roots, including SHA normalization, flags and redis API selection | +1398 | +1122 | +2050 | +1765 | +1256 | +1257 |
| 18191bcc1: preserve callback lookup keys on cold library refresh | +0 | -5 | +0 | +0 | +0 | +0 |
| 6bc147d2c: cold callable metadata and random arithmetic | +5 | +0 | +0 | +0 | +0 | +0 |
| cdd2c4673: retain formatted numeric arguments until dispatch returns | +41 | +42 | +38 | +38 | +38 | +43 |

## Exact +686 example

For normal-namespace, 1s, atomic=1 EVAL-single in the wave10-compatible namespace census, headline 19,693 → PRE 20,379 is the integration bridge −5 plus commit 370210cfc +691:

| Function (compiler clones combined only where stated) | Delta |
|---|---:|
| ScriptCache::exists, SHA spelling normalization | +572 |
| eval_header | +34 |
| run_eval | +21 |
| set_global_raw | +78 |
| command_validate_script_route | +2 |
| script_execute | +2 |
| script_thread_state | −4 |
| append_lua_result, net across old/new compiler signature | −14 |
| Commit total | +691 |

The integration bridge consists of run_eval +1 across its changed compiler signature and command_validate_script_route −6. The other three scriptfix2 commits add zero in this narrow census for this case. The expanded Lua census exposes the numeric-argument lifetime cost that the namespace census omits; it is retained in POST because it fixes real corruption. POST removes enough invariant work to meet the headline budget even with that necessary behavior.

Every executed native instruction address and visit count is retained in each arm’s traces.tar.gz. The matching visited-site disassembly, probe/server/tracer hashes, production link order and rebuild commands are under ../instruction-sites/ and the arm build receipts. Shared-library bodies are excluded by both instruments.
