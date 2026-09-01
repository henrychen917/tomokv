#include <cstdio>
#include <cstdlib>
#include <cstring>
#include <initializer_list>
#include <string>
#include <unistd.h>
#include <vector>

#include "src/core/config.h"

namespace {

[[noreturn]] void fail(const char* message) {
    std::fprintf(stderr, "config parser test: %s\n", message);
    std::exit(1);
}

}  // namespace

int main() {
    char path[] = "/tmp/tomokv-config-parser.XXXXXX";
    const int fd = ::mkstemp(path);
    if (fd < 0) fail("mkstemp failed");
    std::FILE* file = ::fdopen(fd, "w");
    if (!file) fail("fdopen failed");

    std::fputs("  # leading comments are skipped after trimming\n", file);
    std::fputs("user alice on #0123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef >\"pass phrase\" ~*\n",
               file);
    std::fputs("requirepass 'single quoted value'\n", file);
    if (std::fclose(file) != 0) fail("fclose failed");

    std::vector<std::string> tokens;
    const bool loaded = tomo::load_conf_file(path, tokens);
    ::unlink(path);
    if (!loaded) fail("load_conf_file rejected valid Redis quoting");

    const std::vector<std::string> expected = {
        "--user",
        "alice",
        "on",
        "#0123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef",
        ">pass phrase",
        "~*",
        "--requirepass",
        "single quoted value",
    };
    if (tokens != expected) fail("mid-value '#' or quoted token did not survive exactly");

    std::vector<std::string> inline_hash;
    if (!tomo::cfg_split_args("port 7953 #not-an-inline-comment", inline_hash) ||
        inline_hash.size() != 3 || inline_hash[2] != "#not-an-inline-comment")
        fail("inline '#' was treated as a comment");

    std::vector<std::string> escaped;
    if (!tomo::cfg_split_args("requirepass \"a\\n\\x23b\"", escaped) ||
        escaped.size() != 2 || escaped[1] != "a\n#b")
        fail("double-quoted Redis escapes were not decoded");

    std::vector<std::string> malformed;
    if (tomo::cfg_split_args("requirepass \"unterminated", malformed) ||
        tomo::cfg_split_args("requirepass \"closed\"suffix", malformed))
        fail("malformed Redis quoting was accepted");

    tomo::Config tls;
    tomo::ConfigParseState tls_state;
    const std::vector<const char*> tls_args = {
        "--port", "0", "--tls-port", "7953",
        "--tls-cert-file", "/cert.pem", "--tls-key-file", "/key.pem",
        "--tls-ca-cert-file", "/ca.pem", "--tls-ca-cert-dir", "/ca-dir",
        "--tls-auth-clients", "OpTiOnAl",
        "--tls-protocols", "TLSv1.2 TLSv1.3",
        "--tls-ciphers", "DEFAULT", "--tls-ciphersuites", "TLS_AES_256_GCM_SHA384",
        "--tls-prefer-server-ciphers", "YeS",
    };
    if (tomo::parse_config_args(tls_args, tls, tls_state, 2, "test") != tomo::kConfigParsed ||
        tomo::validate_config(tls) != tomo::kConfigParsed)
        fail("valid TLS Redis grammar was rejected");
    if (tls.port != 0 || tls.tls_port != 7953 ||
        tls.tls_auth_clients != tomo::TlsAuthClients::Optional ||
        !tls.tls_prefer_server_ciphers ||
        std::strcmp(tls.tls_protocols, "TLSv1.2 TLSv1.3") ||
        std::strcmp(tls.tls_ciphers, "DEFAULT") ||
        std::strcmp(tls.tls_ciphersuites, "TLS_AES_256_GCM_SHA384"))
        fail("TLS knob values were not preserved byte-exactly");

    auto rejects = [](std::initializer_list<const char*> values) {
        tomo::Config cfg;
        tomo::ConfigParseState state;
        const std::vector<const char*> args(values);
        return tomo::parse_config_args(args, cfg, state, 2, "test") == tomo::kConfigError;
    };
    if (!rejects({"--tls-port", "65536"}) ||
        !rejects({"--tls-port", "-1"}) ||
        !rejects({"--tls-auth-clients", "true"}) ||
        !rejects({"--tls-prefer-server-ciphers", "1"}))
        fail("invalid TLS grammar was accepted");

    tomo::Config persistence;
    tomo::ConfigParseState persistence_state;
    const std::vector<const char*> persistence_args = {"--persist-io", "NoRmAl"};
    if (tomo::parse_config_args(persistence_args, persistence, persistence_state, 2, "test") !=
            tomo::kConfigParsed ||
        persistence.persist_io != tomo::PersistIoEngine::Normal ||
        !rejects({"--persist-io", "hybrid"}))
        fail("persist-io boot grammar differs");

    // --net-io mirrors --persist-io exactly: named enum, case insensitive, boot-only, and a
    // NEGATIVE CONTROL so "it parsed" cannot pass for a parser that accepts anything.
    tomo::Config network;
    tomo::ConfigParseState network_state;
    const std::vector<const char*> network_args = {"--net-io", "EpOlL"};
    if (tomo::parse_config_args(network_args, network, network_state, 2, "test") !=
            tomo::kConfigParsed ||
        network.net_io != tomo::NetIoEngine::Epoll ||
        !rejects({"--net-io", "kqueue"}) ||
        !rejects({"--net-io", ""}))
        fail("net-io boot grammar differs");
    tomo::Config network_default;
    if (network_default.net_io != tomo::NetIoEngine::Uring)
        fail("net-io default is not uring");

    tomo::Config schedule;
    tomo::ConfigParseState schedule_state;
    const std::vector<const char*> schedule_args = {
        "--genthread-schedule", "PiPeLiNeD-FuSeD"};
    if (tomo::parse_config_args(schedule_args, schedule, schedule_state, 2, "test") !=
            tomo::kConfigParsed ||
        schedule.genthread_schedule != tomo::GenthreadSchedule::PipelinedFused ||
        !rejects({"--genthread-schedule", "pipeline"}) ||
        !rejects({"--genthread-schedule", ""}))
        fail("genthread-schedule boot grammar differs");
    tomo::Config schedule_default;
    if (schedule_default.genthread_schedule != tomo::GenthreadSchedule::Coarse)
        fail("genthread-schedule default is not coarse");
    tomo::Config iofused_schedule;
    tomo::ConfigParseState iofused_schedule_state;
    const std::vector<const char*> iofused_schedule_args = {
        "--genthread-schedule", "IoFuSeD"};
    if (tomo::parse_config_args(iofused_schedule_args, iofused_schedule,
                                iofused_schedule_state, 2, "test") != tomo::kConfigParsed ||
        iofused_schedule.genthread_schedule != tomo::GenthreadSchedule::IoFused)
        fail("iofused genthread schedule grammar differs");
    tomo::Config streams0_schedule;
    tomo::ConfigParseState streams0_schedule_state;
    const std::vector<const char*> streams0_schedule_args = {
        "--genthread-schedule", "StReAmS0"};
    if (tomo::parse_config_args(streams0_schedule_args, streams0_schedule,
                                streams0_schedule_state, 2, "test") != tomo::kConfigParsed ||
        streams0_schedule.genthread_schedule != tomo::GenthreadSchedule::Streams0)
        fail("streams0 genthread schedule grammar differs");
    schedule.net_io = tomo::NetIoEngine::Epoll;
    if (tomo::validate_config(schedule) != tomo::kConfigError)
        fail("pipelined-fused accepted an engine without a single N2 boundary");
    streams0_schedule.net_io = tomo::NetIoEngine::Epoll;
    if (tomo::validate_config(streams0_schedule) != tomo::kConfigError)
        fail("streams0 accepted an engine without a single N2 boundary");

    tomo::Config smt;
    tomo::ConfigParseState smt_state;
    const std::vector<const char*> smt_args = {"--smt-mode", "1"};
    if (tomo::parse_config_args(smt_args, smt, smt_state, 2, "test") !=
            tomo::kConfigParsed ||
        smt.smt_mode != 1 ||
        !rejects({"--smt-mode", "2"}) ||
        !rejects({"--smt-mode", "yes"}) ||
        !rejects({"--smt-mode", "-1"}))
        fail("smt-mode boot grammar differs");
    tomo::Config smt_default;
    if (smt_default.smt_mode != 0)
        fail("smt-mode default is not logical-CPU independent");

    tomo::Config lb;
    tomo::ConfigParseState lb_state;
    const std::vector<const char*> lb_args = {
        "--key-lb", "0", "--client-lb", "0",
        "--lb-sample-rate", "0", "--lb-age-sample-rate", "0", "--lb-tick-ms", "250",
        "--lb-imbalance-pct", "17", "--lb-move-cap", "3",
        "--lb-cooldown-ms", "9000",
    };
    if (tomo::parse_config_args(lb_args, lb, lb_state, 2, "test") != tomo::kConfigParsed ||
        lb.key_lb != 0 || lb.client_lb != 0 || lb.lb_sample_rate != 0 ||
        lb.lb_age_sample_rate != 0 ||
        lb.lb_tick_ms != 250 || lb.lb_imbalance_pct != 17 || lb.lb_move_cap != 3 ||
        lb.lb_cooldown_ms != 9000)
        fail("weighted-LB knob grammar or zero off posture differs");
    tomo::Config lb_default;
    if (lb_default.key_lb != 1 || lb_default.client_lb != 1 ||
        lb_default.lb_sample_rate != 64 || lb_default.lb_age_sample_rate != 0 ||
        lb_default.lb_tick_ms != 1000 ||
        lb_default.lb_imbalance_pct != 25 || lb_default.lb_move_cap != 1 ||
        lb_default.lb_cooldown_ms != 5000)
        fail("weighted-LB defaults differ");
    if (!rejects({"--key-lb", "2"}) ||
        !rejects({"--key-lb", "-1"}) ||
        !rejects({"--client-lb", "yes"}) ||
        !rejects({"--client-lb", "2"}) ||
        !rejects({"--lb-sample-rate", "-1"}) ||
        !rejects({"--lb-age-sample-rate", "-1"}) ||
        !rejects({"--lb-tick-ms", "later"}) ||
        !rejects({"--lb-imbalance-pct", "-1"}) ||
        !rejects({"--lb-move-cap", "-1"}) ||
        !rejects({"--lb-cooldown-ms", "-1"}))
        fail("invalid weighted-LB knob grammar was accepted");

    if (!rejects({"--ratio", "4:4"}) || !rejects({"--ratio"}))
        fail("generalized-thread mode accepted the removed --ratio knob");

    tomo::Config xscript;
    tomo::ConfigParseState xscript_state;
    const std::vector<const char*> xscript_args = {
        "--script-crossshard-max-bytes", "0",
        "--script-crossshard-workbench-bytes", "1048576",
        "--script-crossshard-conflict-retries", "-1",
        "--script-crossshard-cut-slots", "7",
    };
    if (tomo::parse_config_args(xscript_args, xscript, xscript_state, 2, "test") !=
            tomo::kConfigParsed ||
        xscript.script_crossshard_max_bytes != 0 ||
        xscript.script_crossshard_workbench_bytes != 1048576 ||
        xscript.script_crossshard_conflict_retries != -1 ||
        xscript.script_crossshard_cut_slots != 7)
        fail("cross-script knob grammar or values differ");
    if (!rejects({"--script-crossshard-max-bytes", "-2"}) ||
        !rejects({"--script-crossshard-max-bytes", "-9223372036854775808"}) ||
        !rejects({"--script-crossshard-workbench-bytes", "wat"}) ||
        !rejects({"--script-crossshard-conflict-retries", "9223372036854775808"}) ||
        !rejects({"--script-crossshard-cut-slots", "-9"}))
        fail("invalid cross-script knob grammar was accepted");

    tomo::Config missing_ca;
    tomo::ConfigParseState missing_ca_state;
    const std::vector<const char*> missing_ca_args = {
        "--tls-port", "7953", "--tls-cert-file", "/cert.pem",
        "--tls-key-file", "/key.pem", "--tls-auth-clients", "yes",
    };
    if (tomo::parse_config_args(missing_ca_args, missing_ca, missing_ca_state, 2, "test") !=
            tomo::kConfigParsed ||
        tomo::validate_config(missing_ca) != tomo::kConfigError)
        fail("client-auth TLS boot without a CA was accepted");

    return 0;
}
