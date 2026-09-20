// Included by multidb_unit.cc so this checks the real private execution parser,
// without exporting a test hook or starting a server. Run from the worktree root.
#include <fstream>
#include <sstream>

namespace {
struct SortstoreCase {
    std::string name;
    std::vector<unsigned> keys;
    std::vector<std::string> args;
};

void sortstore_require(bool ok, const SortstoreCase& row, const char* assertion) {
    if (!ok) {
        std::fprintf(stderr, "FAIL sortstore: %s: %s\n", row.name.c_str(), assertion);
        std::exit(1);
    }
}

std::vector<SortstoreCase> sortstore_cases() {
    std::ifstream input("tests/sortstore_cases.tsv");
    require(input.good(), "open SORT namespace corpus");
    std::vector<SortstoreCase> rows;
    std::string line;
    while (std::getline(input, line)) {
        if (line.empty() || line[0] == '#') continue;
        std::istringstream fields(line);
        SortstoreCase row;
        std::string indexes, field;
        std::getline(fields, row.name, '\t');
        std::getline(fields, indexes, '\t');
        std::istringstream keys(indexes);
        while (std::getline(keys, field, ',')) row.keys.push_back(std::stoul(field));
        while (std::getline(fields, field, '\t')) row.args.push_back(field);
        sortstore_require(!row.keys.empty() && row.args.size() >= 2, row, "valid corpus row");
        rows.push_back(std::move(row));
    }
    require(!rows.empty(), "nonempty SORT namespace corpus");
    return rows;
}

void sortstore_setup(Op& op, const std::vector<std::string>& args) {
    for (const auto& arg : args) require(op.push_arg(Slice(arg)), "SORT argv");
    op.spec = command_lookup(op.cmd_name());
    require(op.spec, "registered SORT test command");
}

uint16_t sortstore_flag(const char* name) {
    for (uint32_t index = 0; index < command_metadata_key_flag_count(); ++index)
        if (std::strcmp(command_metadata_key_flag_name(index), name) == 0) return 1u << index;
    require(false, "SORT key flag exists");
    return 0;
}

void sortstore_keys(const SortstoreCase& row) {
    Op execution;
    sortstore_setup(execution, row.args);
    SortOptions options;
    const bool invalid = row.name.starts_with("invalid-");
    sortstore_require(parse_sort_options(execution, options) != invalid, row,
                      "execution accepts valid / rejects malformed argv");
    std::vector<unsigned> parsed{1};
    if (options.store) parsed.push_back(options.store_arg);
    if (invalid) parsed = row.keys;  // Redis GETKEYS is deliberately not a syntax validator.
    else sortstore_require(parsed == row.keys, row, "execution key indexes");

    for (const char* wrapper : {"", "GETKEYS", "GETKEYSANDFLAGS"}) {
        const unsigned offset = *wrapper ? 2 : 0;
        std::vector<std::string> args;
        if (offset) args = {"COMMAND", wrapper};
        args.insert(args.end(), row.args.begin(), row.args.end());
        Op metadata;
        sortstore_setup(metadata, args);
        const auto* spec = command_metadata_resolve(metadata, offset);
        sortstore_require(spec != nullptr, row, "metadata resolves");
        std::vector<CommandKeyMetadata> keys;
        sortstore_require(command_metadata_collect_keys(metadata, offset, *spec, keys) ==
                          CommandMetadataKeysResult::Success, row, "metadata extracts keys");
        std::vector<unsigned> extracted;
        for (const auto& key : keys) extracted.push_back(key.argument - offset);
        if (extracted != parsed) {
            std::fprintf(stderr, "command offset %u; metadata indexes:", offset);
            for (unsigned index : extracted) std::fprintf(stderr, " %u", index);
            std::fprintf(stderr, "; execution indexes:");
            for (unsigned index : parsed) std::fprintf(stderr, " %u", index);
            std::fprintf(stderr, "\n");
        }
        sortstore_require(extracted == parsed, row, "metadata/execution key indexes");
        for (size_t i = 0; i < keys.size(); ++i) {
            const uint16_t expected = i == 0
                ? sortstore_flag("RO") | sortstore_flag("access")
                : sortstore_flag("OW") | sortstore_flag("update");
            sortstore_require(keys[i].flags == expected, row, "key intent flags");
        }
    }
}

void sortstore_stamp(Server& server, const DatabaseMap::Map& map, const SortstoreCase& row) {
    for (bool supplied : {false, true}) {
        Op op;
        sortstore_setup(op, row.args);
        if (supplied) multidb_stamp(server, op, 1, map);
        else multidb_stamp(server, op, 1);
        sortstore_require(op.db == 1 && op.physical_db == 9 && !op.replied(), row,
                          "selected logical 1 maps to physical 9");
        bool namespaces = true;
        for (unsigned i = 0; i < row.args.size(); ++i) {
            const uint8_t expected = std::find(row.keys.begin(), row.keys.end(), i) != row.keys.end()
                ? 9 : 0;
            if (op.arg(i).ns != expected) {
                std::fprintf(stderr, "%s argv[%u]: ns=%u expected=%u (%s map)\n",
                             row.name.c_str(), i, op.arg(i).ns, expected,
                             supplied ? "supplied" : "published");
                namespaces = false;
            }
            sortstore_require(op.arg(i).p == row.args[i].data() &&
                              op.arg(i).sv() == row.args[i], row, "argv bytes/pointers unchanged");
        }
        sortstore_require(namespaces, row, "only actual keys stamped; LIMIT untouched");
    }
}

void sortstore_checks(const char* selection) {
    const bool all = std::strcmp(selection, "all") == 0;
    const bool battery = std::strcmp(selection, "battery") == 0;
    const bool keys = std::strcmp(selection, "oracle-keys") == 0;
    const bool stamp = std::strcmp(selection, "oracle-stamp") == 0;
    require(all || battery || keys || stamp, "known SORT namespace selection");
    Server server;
    require(server.databases().swap(1, 9), "publish nonidentity SORT database map");
    const auto map = server.databases().capture();
    unsigned checked = 0;
    for (const auto& row : sortstore_cases()) {
        if (!(all || battery) && row.name != "oracle") continue;
        if (!stamp) sortstore_keys(row);
        if (!keys) sortstore_stamp(server, map, row);
        ++checked;
    }
    require(checked > 0, "SORT namespace selection exercised");
    std::printf("PASS sortstore %s: %u cases\n", selection, checked);
}
}  // namespace
