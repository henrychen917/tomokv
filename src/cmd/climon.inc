// climon.inc -- declarations for the IO-owned CLIENT scatter transport.
//
// Included inside IoLoop. Implementations live in climon.cc so adding cold CLIENT catalog work
// cannot move or perturb the hot parse/dispatch code emitted from main.cc.

    enum class ClimonStartResult : uint8_t { NotHandled, Sync, Async };
    enum class ClimonPendingKind : uint8_t { ClientList, ClientKill };

    struct ClimonPending {
        ClimonPendingKind kind = ClimonPendingKind::ClientList;
        Client* client = nullptr;
        uint64_t op_id = 0;
        uint32_t remaining = 0;
        uint64_t count = 0;
        bool old_form = false;
        std::string body;
    };

    static bool climon_parse_i64(Slice value, int64_t& out);
    static std::string climon_string(Slice value);
    static bool climon_parse_client_type(Slice value, ClientTypeFilter& type);
    static void climon_copy_client_filter(PubSubEvent& target, const PubSubEvent& source);

    ClimonStartResult climon_begin_client_scatter(
        Client* client, const PubSubEvent& filter, ClimonPendingKind kind);
    ClimonStartResult climon_start_client_list(Client* client, Op& op);
    ClimonStartResult climon_start_client_kill(Client* client, Op& op);
    ClimonStartResult climon_start_client_command(Client* client, Op& op);
    void climon_handle_client_request(PubSubEvent& event);
    void climon_finish_client_pending(uint64_t conn_id);
    void climon_handle_client_result(PubSubEvent& event);
    bool climon_handle_event(PubSubEvent& event);
