// Offline registry classification audit. No Server, listener, or workers.
#include "src/cmd/command.h"
#include "src/cmd/client_pause.h"
#include "src/exec/op.h"
#include <cstdio>
#include <iostream>
#include <sstream>
#include <string>
#include <vector>
using namespace tomo;
int main() {
    if (!command_registry_init(false)) return 1;
    std::string line;
    while (std::getline(std::cin, line)) {
        std::istringstream input(line);
        std::vector<std::string> args;
        for (std::string word; input >> word;) args.push_back(std::move(word));
        if (args.empty()) continue;
        const auto* spec = command_lookup(Slice(args[0]));
        if (!spec) continue;
        Op op;
        op.reset();
        for (const auto& arg : args) op.push_arg(Slice(arg));
        op.spec = spec;
        const bool script = spec->flags & CmdFlags::ScriptRoute;
        std::printf("%s\t%d\t%d\n", line.c_str(), script,
                    script ? -1 : int(command_pause_write(op)));
    }
}
