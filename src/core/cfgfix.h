// Cold process-service and listener-control interfaces, shared by main.cc, server.h and
// CONFIG handlers. Boot hooks precede workers; live controls use the Server transition
// fence. Executor hooks borrow loop pointers and require the registered physical owner.
#pragma once
#include <cstdint>
#include <string>

namespace tomo {
struct Config;
class Server;
// Cold process lifetime and configuration hooks; no operation-path call sites.
bool cfgfix_process_boot(const Config&);
void cfgfix_process_ready();
void cfgfix_loglevel(const char*);
void cfgfix_key_load_delay(int32_t);
void cfgfix_delay_loaded_key();
bool cfgfix_control_busy(const Server&);
bool cfgfix_control_begin(Server&);
void cfgfix_control_end(Server&);
bool cfgfix_rebind(Server&, uint32_t caller, uint16_t port, const std::string& bind,
                   std::string& error, int appendonly = -1);
void cfgfix_register_executor(Server*, uint32_t, void*, bool (*)(void*, int));
bool cfgfix_executor_control(Server&, uint32_t, int);
}
