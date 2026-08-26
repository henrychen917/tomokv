// acl.inc -- ACL machinery, textually included once by xshard.cc.

namespace tomo {
namespace {

bool acl_equal_icase(Slice value, const char* literal) {
    const size_t length = std::strlen(literal);
    if (value.n != length) return false;
    for (size_t i = 0; i < length; i++) {
        unsigned char left = static_cast<unsigned char>(value.p[i]);
        unsigned char right = static_cast<unsigned char>(literal[i]);
        if (left >= 'A' && left <= 'Z') left = static_cast<unsigned char>(left + ('a' - 'A'));
        if (right >= 'A' && right <= 'Z') right = static_cast<unsigned char>(right + ('a' - 'A'));
        if (left != right) return false;
    }
    return true;
}

const AclCategoryDefinition* acl_category(Slice name) {
    for (const AclCategoryDefinition& category : kAclCategories)
        if (acl_equal_icase(name, category.name)) return &category;
    return nullptr;
}

std::string acl_lower_command_name(const char* name) {
    std::string result(name);
    for (char& byte : result)
        if (byte >= 'A' && byte <= 'Z') byte = static_cast<char>(byte + ('a' - 'A'));
    return result;
}

}  // namespace

void cmd_acl(Shard&, Op& op) {
    if (!acl_equal_icase(op.arg(1), "CAT") || op.argc() > 3) {
        reply_err(op.sink(),
                  "ERR Unknown subcommand or wrong number of arguments for 'acl'. Try ACL HELP.");
        return;
    }
    if (op.argc() == 2) {
        reply_array_header(op.sink(), kAclCategoryCount);
        for (const AclCategoryDefinition& category : kAclCategories)
            reply_bulk(op.sink(), Slice(category.name, std::strlen(category.name)));
        return;
    }

    const AclCategoryDefinition* category = acl_category(op.arg(2));
    if (!category) {
        const size_t length = std::min<size_t>(op.arg(2).n, 128);
        std::string message = "ERR Unknown category '";
        message.append(op.arg(2).p, length);
        message.push_back('\'');
        reply_err(op.sink(), message.c_str());
        return;
    }

    std::vector<const CommandSpec*> commands;
    for (uint32_t id = 0; id < command_registry_size(); id++) {
        const CommandSpec* spec = command_registry_at(id);
        if (spec->acl_categories & category->bit) commands.push_back(spec);
    }
    std::sort(commands.begin(), commands.end(), [](const CommandSpec* left,
                                                    const CommandSpec* right) {
        return std::strcmp(left->name, right->name) < 0;
    });
    reply_array_header(op.sink(), commands.size());
    for (const CommandSpec* spec : commands) {
        const std::string name = acl_lower_command_name(spec->name);
        reply_bulk(op.sink(), Slice(name.data(), name.size()));
    }
}

}  // namespace tomo
