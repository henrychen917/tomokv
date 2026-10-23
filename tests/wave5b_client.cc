// Fixed-request-count mechanism driver. No clocks, rate output, or duration loop.
// READY/GO and DONE/STOP keep setup, teardown, and metric snapshots outside requests.
#include <arpa/inet.h>
#include <netinet/tcp.h>
#include <sys/socket.h>
#include <unistd.h>
#include <barrier>
#include <cerrno>
#include <cstdlib>
#include <iostream>
#include <stdexcept>
#include <string>
#include <thread>
#include <vector>

static void require(bool good, const char* why) {
    if (!good) throw std::runtime_error(why);
}
static std::string encode(const std::vector<std::string>& args) {
    std::string out = "*" + std::to_string(args.size()) + "\r\n";
    for (const auto& a : args) out += "$" + std::to_string(a.size()) + "\r\n" + a + "\r\n";
    return out;
}
static void send_all(int fd, const std::string& data) {
    size_t offset = 0;
    while (offset < data.size()) {
        ssize_t n = send(fd, data.data() + offset, data.size() - offset, MSG_NOSIGNAL);
        if (n < 0 && errno == EINTR) continue;
        require(n > 0, "send failed");
        offset += n;
    }
}
static void read_exact(int fd, const std::string& expected) {
    std::string got(expected.size(), '\0');
    size_t offset = 0;
    while (offset < got.size()) {
        ssize_t n = recv(fd, got.data() + offset, got.size() - offset, 0);
        if (n < 0 && errno == EINTR) continue;
        require(n > 0, "reply missing or timeout");
        offset += n;
    }
    require(got == expected, "reply differs from exact expected RESP");
}
int main(int argc, char** argv) try {
    require(argc == 4, "usage: client PORT MGET|MSET REQUESTS_PER_CONNECTION");
    int port = std::stoi(argv[1]), count = std::stoi(argv[3]);
    std::string command = argv[2];
    require(port >= 26800 && port <= 26899, "port outside lane");
    require(command == "MGET" || command == "MSET", "unknown command");
    require(count > 0 && count % 8 == 0, "request count must be a positive multiple of depth 8");
    constexpr int connections = 64, depth = 8;
    std::barrier ready(connections + 1), go(connections + 1), done(connections + 1), stop(connections + 1);
    std::vector<std::thread> workers;
    for (int c = 0; c < connections; ++c) workers.emplace_back([&, c] {
        try {
            int fd = socket(AF_INET, SOCK_STREAM | SOCK_CLOEXEC, 0);
            require(fd >= 0, "socket failed");
            int one = 1;
            timeval timeout{30, 0};
            setsockopt(fd, IPPROTO_TCP, TCP_NODELAY, &one, sizeof one);
            setsockopt(fd, SOL_SOCKET, SO_RCVTIMEO, &timeout, sizeof timeout);
            setsockopt(fd, SOL_SOCKET, SO_SNDTIMEO, &timeout, sizeof timeout);
            sockaddr_in address{};
            address.sin_family = AF_INET;
            address.sin_port = htons(port);
            address.sin_addr.s_addr = htonl(INADDR_LOOPBACK);
            require(connect(fd, reinterpret_cast<sockaddr*>(&address), sizeof address) == 0, "connect failed");
            // Independent connection keysets avoid write conflicts; each request has eight keys.
            std::vector<std::string> write{"MSET"}, args{command};
            const std::string value(64, 'v');
            std::string reply = command == "MGET" ? "*8\r\n" : "+OK\r\n";
            for (int k = 0; k < 8; ++k) {
                std::string key = "wave5b:" + std::to_string(c) + ":" + std::to_string(k);
                write.insert(write.end(), {key, value});
                args.push_back(key);
                if (command == "MSET") args.push_back(value);
                else reply += "$64\r\n" + value + "\r\n";
            }
            send_all(fd, encode(write));
            read_exact(fd, "+OK\r\n");
            std::string batch, replies;
            for (int i = 0; i < depth; ++i) { batch += encode(args); replies += reply; }
            ready.arrive_and_wait();
            go.arrive_and_wait();
            for (int i = 0; i < count; i += depth) {
                send_all(fd, batch);
                read_exact(fd, replies);
            }
            done.arrive_and_wait();
            stop.arrive_and_wait();
            close(fd);
        } catch (const std::exception& e) {
            std::cerr << "connection " << c << ": " << e.what() << std::endl;
            std::_Exit(2); // fail the entire bounded run; never hang at a barrier
        }
    });
    ready.arrive_and_wait();
    std::cout << "READY" << std::endl;
    std::string line;
    require(bool(std::getline(std::cin, line)) && line == "GO", "missing GO");
    go.arrive_and_wait();
    done.arrive_and_wait();
    std::cout << "DONE " << connections * count << std::endl;
    require(bool(std::getline(std::cin, line)) && line == "STOP", "missing STOP");
    stop.arrive_and_wait();
    for (auto& worker : workers) worker.join();
    return 0;
} catch (const std::exception& e) { std::cerr << e.what() << '\n'; return 2; }
