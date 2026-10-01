// Price real reply encodings without a server or clocks; reuse the same boundary.
#define main unused_wbhybrid2_main
#include "wbhybrid2_unit.cc"
#undef main
int main(int argc, char** argv) {
    if (argc != 2) return 2;
    selected = argv[1]; unsigned done, waits, shape;
    require(std::sscanf(selected, "codes-%u-%u-%u", &done, &waits, &shape) == 3 &&
            done <= 2 && waits <= wait_limit && shape >= 1 && shape <= 3, "coded fixture grammar");
    Client c(-1); fill(c, 8, done); count(c, waits);
    for (unsigned i = 0; i < done; ++i) {
        auto& op = c.rob().at(c.rob().flush_id() + i);
        if (shape == 1) op.reply_code_ = static_cast<uint8_t>(ReplyCode::Ok);
        else if (shape == 2) op.reply.append(std::string(71, 'g').data(), 71);
        else { op.reply_code_ = static_cast<uint8_t>(ReplyCode::Int); op.reply_ival_ = 12345; }
    }
    require(wbhybrid2_defer(&c, 1), "below half and byte threshold");
    std::printf("PASS wbhybrid2 %s\n", selected);
}
