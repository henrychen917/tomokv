#!/usr/bin/env python3
"""Build throwaway, selectable cold-path regressions using POST production objects.

Set TOMO_SCRIPTFIX2_BREAK to a root or 'all' only when testing this binary.
No production source or production object is changed, and this tool runs no server.
"""
import hashlib
import json
from pathlib import Path
import shlex
import subprocess

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / 'build/scriptfix2/mutant'
HELPER = '''
bool scriptfix2_broken(const char* root) {
    const char* selected = std::getenv("TOMO_SCRIPTFIX2_BREAK");
    return selected && (!std::strcmp(selected, root) || !std::strcmp(selected, "all"));
}
'''


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    recipes = subprocess.check_output(['make', '-Bn', 'all'], cwd=ROOT, text=True)
    commands = [shlex.split(line) for line in recipes.splitlines() if line.startswith('g++ ')]
    replacements = {}
    changes = []
    for feature in ('scripting', 'functions'):
        source = (ROOT / f'src/cmd/{feature}.cc').read_text()
        source = '#include <cstdlib>\n' + source.replace('namespace {\n', 'namespace {\n' + HELPER, 1)

        def change(root, before, after):
            nonlocal source
            assert source.count(before) == 1, (root, source.count(before))
            source = source.replace(before, after)
            changes.append(dict(root=root, file=f'src/cmd/{feature}.cc', before=before, after=after))

        if feature == 'scripting':
            change('EVAL-SHEBANG', '    body = source;\n    flags = EvalLegacy;',
                   '    body = source;\n    flags = EvalLegacy;\n'
                   '    if (scriptfix2_broken("EVAL-SHEBANG")) return true;')
            change('EVALSHA-SHA-CASE', '    std::string key(sha.p, sha.n);',
                   '    std::string key(sha.p, sha.n);\n'
                   '    if (scriptfix2_broken("EVALSHA-SHA-CASE")) return key;')
            change('LUA-REDIS-API',
                   '    lua_pushcfunction(state, redis_error_reply); lua_setfield(state, -2, "error_reply");',
                   '    if (!scriptfix2_broken("LUA-REDIS-API")) {\n'
                   '        lua_pushcfunction(state, redis_error_reply); lua_setfield(state, -2, "error_reply");\n    }')
            change('LUA-SANDBOX-GLOBALS', '    remove_global(state, "dofile");',
                   '    remove_global(state, "dofile");\n'
                   '    if (scriptfix2_broken("LUA-SANDBOX-GLOBALS")) remove_global(state, "loadstring");')
            change('SCRIPT-ERROR-WORDING',
                   '"ERR Please specify at least one argument for this redis lib call");',
                   'scriptfix2_broken("SCRIPT-ERROR-WORDING") ? "ERR invalid script command" : '
                   '"ERR Please specify at least one argument for this redis lib call");')
            change('SCRIPT-NUMBER-ARG', '                    lua_pushlstring(state, number, length);',
                   '                    if (scriptfix2_broken("SCRIPT-NUMBER-ARG"))\n'
                   '                        length = std::snprintf(number, sizeof(number), "%.14g", n);\n'
                   '                    lua_pushlstring(state, number, length);')
            change('SCRIPT-REPLY-DEPTH', '    if (!lua_checkstack(state, 4)) {',
                   '    if (scriptfix2_broken("SCRIPT-REPLY-DEPTH") && depth > 32) {\n'
                   '        error = "script reply nesting limit exceeded"; return false;\n    }\n'
                   '    if (!lua_checkstack(state, 4)) {')
        else:
            change('FCALL-NAME-CASE', '    std::string result(name);',
                   '    std::string result(name);\n'
                   '    if (scriptfix2_broken("FCALL-NAME-CASE")) return result;')
            change('FUNCTION-LOAD-ENV',
                   '    lua_pushcfunction(state, fn_missing_index);\n    lua_setfield(state, environment_meta, "__index");',
                   '    if (scriptfix2_broken("FUNCTION-LOAD-ENV")) lua_pushvalue(state, LUA_GLOBALSINDEX);\n'
                   '    else lua_pushcfunction(state, fn_missing_index);\n    lua_setfield(state, environment_meta, "__index");')
            change('FUNCTION-REGISTER-ARGS',
                   '    if (!valid_function_name(name)) return register_error(state, kNameError);',
                   '    if (!scriptfix2_broken("FUNCTION-REGISTER-ARGS") && !valid_function_name(name))\n'
                   '        return register_error(state, kNameError);')
            change('FUNCTION-SHEBANG-META',
                   '    if (!cfg_split_args(header.c_str(), fields) || fields.empty()) {',
                   '    if ((scriptfix2_broken("FUNCTION-SHEBANG-META") && '
                   'header.find_first_of("\\\"\'") != std::string::npos) ||\n'
                   '        !cfg_split_args(header.c_str(), fields) || fields.empty()) {')
            change('FUNCTION-SUBCMD-ARGS', '        if (op.argc() > 4) { reply_err_string(op,',
                   '        if (!scriptfix2_broken("FUNCTION-SUBCMD-ARGS") && op.argc() > 4) { reply_err_string(op,')
        copy = OUT / f'{feature}.cc'
        if not copy.exists() or copy.read_text() != source:
            copy.write_text(source)
        for command in commands:
            if '-c' not in command or command[command.index('-c') + 1] != f'src/cmd/{feature}.cc':
                continue
            old = command[command.index('-o') + 1]
            obj = OUT / old.removeprefix('build/')
            obj.parent.mkdir(parents=True, exist_ok=True)
            command[command.index('-c') + 1] = str(copy)
            command[command.index('-o') + 1] = str(obj)
            command.insert(1, '-I' + str(ROOT / 'src/cmd'))
            if not obj.exists() or obj.stat().st_mtime < copy.stat().st_mtime:
                subprocess.run(command, cwd=ROOT, check=True)
            replacements[old] = str(obj)
    assert len(replacements) == 4
    link, = [cmd for cmd in commands if '-c' not in cmd and '-o' in cmd and
             cmd[cmd.index('-o') + 1] == 'build/tomokv']
    link = [replacements.get(arg, arg) for arg in link]
    binary = OUT / 'tomokv-mutant'
    link[link.index('-o') + 1] = str(binary)
    subprocess.run(link, cwd=ROOT, check=True)
    report = dict(binary=str(binary.relative_to(ROOT)),
                  sha256=hashlib.sha256(binary.read_bytes()).hexdigest(), changes=changes)
    (ROOT / 'docs/scriptfix2/mutations.json').write_text(json.dumps(report, indent=2) + '\n')


if __name__ == '__main__':
    main()
