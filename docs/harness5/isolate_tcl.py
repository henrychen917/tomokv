"""Fresh-server, exact-name reruns of observed Tcl failures, with command traces."""
import argparse
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'tests'))
import redis_tcl as suite

TRACE = r'''
rename ::redis::__dispatch__raw__ ::redis::harness5_original_dispatch
proc ::redis::__dispatch__raw__ {id method argv} {
    set record 0
    if {$::cur_test ne "" && [info command ::redis::__method__$method] eq {}} {
        set name [lindex [split $::cur_test "\n"] 0]
        foreach selected $::only_tests {
            if {$::cur_test eq "$selected in $::curfile"} { set record 1 }
        }
    }
    if {$record} {
        set path "$::env(HARNESS5_TCL_EVENTS).commands"
        set f [open $path a]
        set values [list request $id $::cur_test $method {*}$argv]
        set fields {}
        foreach value $values { lappend fields [binary encode base64 -maxlen 0 [encoding convertto utf-8 $value]] }
        puts $f [join $fields "\t"]; close $f
    }
    set status [catch {::redis::harness5_original_dispatch $id $method $argv} result options]
    if {$record} {
        set f [open $path a]; set fields {}
        foreach value [list response $id $status $result] {
            lappend fields [binary encode base64 -maxlen 0 [encoding convertto utf-8 $value]]
        }
        puts $f [join $fields "\t"]; close $f
    }
    return -options $options $result
}
'''

def main():
    p = argparse.ArgumentParser()
    p.add_argument('--cases', type=Path, required=True)
    p.add_argument('--output', type=Path, required=True)
    p.add_argument('--cores', default='32-39')
    p.add_argument('--port', type=int, default=45820)
    p.add_argument('--baseport', type=int, default=45853)
    options = p.parse_args()
    base = options.output.resolve(); base.mkdir(parents=True, exist_ok=True)
    tree = base / 'checkout'
    suite.prepare(Path('/home/user/Projects/redis'), tree)
    helper = tree / 'tests/test_helper.tcl'
    marker = 'if {$::client} {\n    if {[catch { test_client_main'
    helper.write_text(helper.read_text().replace(marker, TRACE + '\n' + marker, 1))
    cases = json.loads(options.cases.read_text())
    for i, case in enumerate(cases):
        unit, name = case[:2]
        selected_names = case[2] if len(case) > 2 else [name]
        results = {}
        for mode, binary in [('2s', ROOT / 'build/tomokv'),
                             ('redis', Path('/home/user/Projects/redis/src/redis-server'))]:
            output = base / f'{i:03}' / mode
            args = argparse.Namespace(output=output, binary=binary, mode=mode, cores=options.cores,
                port=options.port, baseport=options.baseport, idle_timeout=15, file_timeout=35)
            saved = output / unit / 'result.json'
            row = json.loads(saved.read_text()) if saved.exists() else suite.run_file(args, tree, unit, only=selected_names)
            selected = [e for e in row['events'] if e['status'] in ('ok', 'err') and
                        e['test'] == name + ' in tests/' + unit + '.tcl']
            results[mode] = dict(selected=selected, error=row['error'], exit_code=row['exit_code'])
        (base / f'{i:03}' / 'comparison.json').write_text(json.dumps(dict(file=unit, test=name,
            selected_names=selected_names, results=results), indent=2)+'\n')
        print(i, unit, name, {m:[e['status'] for e in r['selected']] for m,r in results.items()}, flush=True)

if __name__ == '__main__': main()
