// Finite, reply-checked workload for tornread_instructions.py; emits no rate result.
#include <arpa/inet.h>
#include <netinet/tcp.h>
#include <sys/socket.h>
#include <unistd.h>
#include <array>
#include <cstdio>
#include <cstdlib>
#include <iostream>
#include <stdexcept>
#include <string>
#include <vector>

static void require(bool condition, const char* why) {
    if (!condition) throw std::runtime_error(why);
}
static std::string bulk(const std::string& value) {
    return "$" + std::to_string(value.size()) + "\r\n" + value + "\r\n";
}
static std::string frame(const std::vector<std::string>& args) {
    std::string out = "*" + std::to_string(args.size()) + "\r\n";
    for (const auto& arg : args) out += bulk(arg);
    return out;
}
int main(int argc, char** argv) {
    try {
        require(argc == 6, "expected port verb depth count worker");
        const int port = std::stoi(argv[1]), depth = std::stoi(argv[3]);
        const int count = std::stoi(argv[4]), worker = std::stoi(argv[5]);
        const std::string verb = argv[2], value(64, 'v');
        require(count > 0 && depth > 0 && count % depth == 0 && 4096 % depth == 0,
                "invalid finite command count or depth");
        std::string reply;
        if (verb == "GET") reply = bulk(value);
        else if (verb == "MGET") {
            reply = "*8\r\n";
            for (int i = 0; i < 8; ++i) reply += bulk(value);
        } else {
            require(verb == "SET" || verb == "MSET", "unknown command");
            reply = "+OK\r\n";
        }
        std::string expected;
        for (int j = 0; j < depth; ++j) expected += reply;
        std::string received(expected.size(), '\0');
        std::array<std::string, 64> batches;
        for (int offset = 0; offset < 64; ++offset) for (int j = 0; j < depth; ++j) {
            std::vector<std::string> args{verb};
            const int k = (offset * depth + j) % 512;
            const int keys = (verb == "GET" || verb == "SET") ? 1 : 8;
            for (int i = 0; i < keys; ++i) {
                args.push_back("instr:" + std::to_string(worker) + ":" +
                               std::to_string((k + i) % 512));
                if (verb == "SET" || verb == "MSET") args.push_back(value);
            }
            batches[offset] += frame(args);
        }
        const int fd = socket(AF_INET, SOCK_STREAM, 0);
        require(fd >= 0, "socket failed");
        const int one = 1;
        require(setsockopt(fd, IPPROTO_TCP, TCP_NODELAY, &one, sizeof(one)) == 0,
                "TCP_NODELAY failed");
        timeval timeout{30, 0};
        require(setsockopt(fd, SOL_SOCKET, SO_RCVTIMEO, &timeout, sizeof(timeout)) == 0 &&
                setsockopt(fd, SOL_SOCKET, SO_SNDTIMEO, &timeout, sizeof(timeout)) == 0,
                "socket timeout failed");
        sockaddr_in addr{};
        addr.sin_family = AF_INET;
        addr.sin_port = htons(port);
        addr.sin_addr.s_addr = htonl(INADDR_LOOPBACK);
        require(connect(fd, reinterpret_cast<sockaddr*>(&addr), sizeof(addr)) == 0,
                "connect failed");
        auto run = [&](int commands) {
            for (int i = 0; i < commands / depth; ++i) {
                const auto& request = batches[i % batches.size()];
                for (size_t sent = 0; sent < request.size();) {
                    const auto n = send(fd, request.data() + sent, request.size() - sent, MSG_NOSIGNAL);
                    require(n > 0, "send failed");
                    sent += n;
                }
                for (size_t got = 0; got < received.size();) {
                    const auto n = recv(fd, received.data() + got, received.size() - got, 0);
                    require(n > 0, "receive failed");
                    got += n;
                }
                require(received == expected, "reply bytes differ");
            }
        };
        run(4096);
        std::cout << "ready" << std::endl;
        std::string command;
        require(static_cast<bool>(std::getline(std::cin, command)) && command == "run",
                "missing run boundary");
        run(count);
        std::cout << count << std::endl;
        require(static_cast<bool>(std::getline(std::cin, command)) && command == "close",
                "missing close boundary");
        close(fd);
        return 0;
    } catch (const std::exception& error) {
        std::fprintf(stderr, "%s\n", error.what());
        return 1;
    }
}
