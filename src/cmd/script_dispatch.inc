// Shared Lua dispatch body: the ordinary instantiation has no MONITOR hook.
    auto* slot = static_cast<ScriptContext**>(lua_touserdata(state, lua_upvalueindex(1)));
    ScriptContext* context = slot ? *slot : nullptr;
    char deferred_error[2100] = {};
    bool failed = false;
    {
        const int argc = lua_gettop(state);
        Op nested;
        if (!context || argc < 1) {
            std::snprintf(deferred_error, sizeof(deferred_error), "ERR redis.call requires a command name");
            failed = true;
        } else {
            for (int i = 1; i <= argc && !failed; i++) {
                const int type = lua_type(state, i);
                if (type != LUA_TSTRING && type != LUA_TNUMBER) {
                    std::snprintf(deferred_error, sizeof(deferred_error),
                                  "ERR Lua redis() command arguments must be strings or integers");
                    failed = true;
                    break;
                }
                size_t length = 0;
                const char* value = lua_tolstring(state, i, &length);
                if (length > UINT32_MAX || !nested.push_arg(
                        Slice(value, static_cast<uint32_t>(length)))) {
                    std::snprintf(deferred_error, sizeof(deferred_error), "ERR out of memory");
                    failed = true;
                }
            }
        }

        const CommandSpec* spec = failed ? nullptr : command_lookup(nested.cmd_name());
        if (!failed && (!spec || !command_arity_ok(*spec, nested.argc()))) {
            std::snprintf(deferred_error, sizeof(deferred_error),
                          spec ? "ERR wrong number of arguments for command from script"
                               : "ERR Unknown Redis command called from script");
            failed = true;
        }
        if (!failed && !script_command_allowed(*spec, nested.argc())) {
            std::snprintf(deferred_error, sizeof(deferred_error),
                          "ERR command '%s' is not allowed from scripts", spec->name);
            failed = true;
        }
        // The read-only gate. CommandSpec::flags carries Write on every keyspace mutation
        // (verified against the registry rows, e.g. PERSIST/DEL/SETBIT are Write, TOUCH/EXISTS
        // are Readonly), so this needs no second whitelist.
        if (!failed && context->readonly && (spec->flags & CmdFlags::Write)) {
            std::snprintf(deferred_error, sizeof(deferred_error),
                          "ERR Write commands are not allowed from read-only scripts.");
            g_ro_rejections.fetch_add(1, std::memory_order_relaxed);
            failed = true;
        }
        if (!failed) {
            const uint32_t key_arg = static_cast<uint32_t>(spec->first_key);
            nested.db = context->parent->db;
            nested.physical_db = context->parent->physical_db;
            nested.set_arg_namespace(key_arg, nested.physical_db);
            const Slice key = nested.arg(key_arg);
            if (!mark_declared(*context, key, 1)) {
                std::snprintf(deferred_error, sizeof(deferred_error),
                              "ERR Script attempted to access an undeclared key");
                failed = true;
            } else {
                if (context->notify) spec = command_notify_variant(spec);
                nested.spec = spec;
                nested.hash = FlatStore::hash_key(key);
                nested.shard = context->shard->id();
                if (context->script_resp == 3) nested.mark_resp3();
                if (context->notify)
                    notify_execute_source(*context->shard, nested,
                                          context->call_index++ * 0x10000u);
                if ((spec->flags & CmdFlags::DenyOom) &&
                    !context->shard->store().budget_admit(key)) {
                    reply_maxmemory_oom(nested);
                } else {
                    spec->handler(*context->shard, nested);
#ifdef TOMO_MONITOR_SCRIPT_DISPATCH
                    climon_monitor_feed(*context->shard, nested, *context->parent);
#endif
                }
                if (context->notify)
                    notify_execute_source(*context->shard, *context->parent, 0);
                // A Write row that answered without an error has already changed the keyspace.
                // Nothing later in this activation may reverse it, so record it here: this is the
                // quantity a regression asserts on, not "no exception was thrown".
                if (spec->flags & CmdFlags::Write) {
                    const bool errored = !nested.zc_ptr && nested.reply.size() &&
                                         nested.reply.data()[0] == '-';
                    if (!errored) {
                        mark_declared(*context, key, 2);
                        context->effect_writes++;
                        g_effect_writes.fetch_add(1, std::memory_order_relaxed);
                    }
                }
                if (nested.zc_ptr) {
                    try {
                        std::string borrowed(nested.zc_ptr, nested.zc_len);
                        context->shard->store().unborrow(nested.zc_ptr);
                        nested.zc_ptr = nullptr;
                        lua_pushlstring(state, borrowed.data(), borrowed.size());
                    } catch (const std::bad_alloc&) {
                        context->shard->store().unborrow(nested.zc_ptr);
                        nested.zc_ptr = nullptr;
                        std::snprintf(deferred_error, sizeof(deferred_error), "ERR out of memory");
                        failed = true;
                    }
                } else {
                    size_t pos = 0;
                    bool server_error = false;
                    std::string parse_error;
                    if (!push_resp_value(state, nested.reply.data(), nested.reply.size(), pos, 0,
                                         true, server_error, parse_error) ||
                        (!server_error && pos != nested.reply.size())) {
                        std::snprintf(deferred_error, sizeof(deferred_error), "ERR %s",
                                      parse_error.empty() ? "invalid nested command reply"
                                                          : parse_error.c_str());
                        failed = true;
                    } else if (server_error) {
                        const std::string safe = clean_error(parse_error.data(), parse_error.size());
                        std::snprintf(deferred_error, sizeof(deferred_error), "%s", safe.c_str());
                        failed = true;
                    }
                }
            }
        }
    }

    if (!failed) return 1;
    lua_createtable(state, 0, 1);
    lua_pushstring(state, deferred_error);
    lua_setfield(state, -2, "err");
    if (protected_call) return 1;
    // RAISE A TABLE, not a string. Lua prepends `user_script:N: ` to a raised string; Redis's
    // wire error for a failed redis.call has no position prefix (the position appears only in the
    // trailing " ... on @user_script:N." clause), and a table carries none.
    return lua_error(state);
