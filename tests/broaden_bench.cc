#include <arpa/inet.h>
#include <netinet/in.h>
#include <netinet/tcp.h>
#include <pthread.h>
#include <sys/socket.h>
#include <unistd.h>

#include <algorithm>
#include <atomic>
#include <cerrno>
#include <chrono>
#include <cstdio>
#include <cstdlib>
#include <cstring>
#include <iterator>
#include <string>
#include <string_view>
#include <thread>
#include <vector>

namespace {

constexpr int kConnections = 64;
constexpr int kPipeline = 32;
constexpr int kRings = 1024;
constexpr int kLoadCpus[] = {244, 245, 246, 247, 252, 253, 254, 255};

std::atomic<int> ready{0};
std::atomic<bool> go{false};
std::atomic<long long> deadline_ns{0};

std::string command(std::initializer_list<std::string_view> args) {
  std::string out = "*" + std::to_string(args.size()) + "\r\n";
  for (std::string_view arg : args) {
    out += "$" + std::to_string(arg.size()) + "\r\n";
    out.append(arg);
    out += "\r\n";
  }
  return out;
}

bool send_all(int fd, std::string_view bytes) {
  while (!bytes.empty()) {
    ssize_t n = send(fd, bytes.data(), bytes.size(), MSG_NOSIGNAL);
    if (n < 0 && errno == EINTR) continue;
    if (n <= 0) return false;
    bytes.remove_prefix(static_cast<size_t>(n));
  }
  return true;
}

class Reader {
 public:
  explicit Reader(int fd) : fd_(fd) {}

  bool reply(bool* error) {
    char type;
    if (!take(&type)) return false;
    switch (type) {
      case '+':
      case ':':
        return line(nullptr);
      case '-':
        *error = true;
        return line(nullptr);
      case '$': {
        long long len;
        if (!line(&len)) return false;
        return len < 0 || discard(static_cast<size_t>(len) + 2);
      }
      case '*': {
        long long count;
        if (!line(&count)) return false;
        for (long long i = 0; i < count; ++i)
          if (!reply(error)) return false;
        return true;
      }
      case '_':
        return discard(2);
      default:
        return false;
    }
  }

 private:
  bool refill() {
    ssize_t n;
    do {
      n = recv(fd_, buffer_, sizeof(buffer_), 0);
    } while (n < 0 && errno == EINTR);
    if (n <= 0) return false;
    pos_ = 0;
    end_ = static_cast<size_t>(n);
    return true;
  }

  bool take(char* out) {
    if (pos_ == end_ && !refill()) return false;
    *out = buffer_[pos_++];
    return true;
  }

  bool line(long long* number) {
    std::string value;
    char c;
    for (;;) {
      if (!take(&c)) return false;
      if (c == '\r') {
        if (!take(&c) || c != '\n') return false;
        break;
      }
      if (number) value.push_back(c);
    }
    if (number) *number = std::strtoll(value.c_str(), nullptr, 10);
    return true;
  }

  bool discard(size_t count) {
    while (count != 0) {
      if (pos_ == end_ && !refill()) return false;
      size_t n = std::min(count, end_ - pos_);
      pos_ += n;
      count -= n;
    }
    return true;
  }

  int fd_;
  char buffer_[65536];
  size_t pos_ = 0;
  size_t end_ = 0;
};

int connect_to(int port) {
  int fd = socket(AF_INET, SOCK_STREAM, 0);
  if (fd < 0) return -1;
  int one = 1;
  setsockopt(fd, IPPROTO_TCP, TCP_NODELAY, &one, sizeof(one));
  sockaddr_in addr{};
  addr.sin_family = AF_INET;
  addr.sin_port = htons(port);
  inet_pton(AF_INET, "127.0.0.1", &addr.sin_addr);
  if (connect(fd, reinterpret_cast<sockaddr*>(&addr), sizeof(addr)) != 0) {
    close(fd);
    return -1;
  }
  return fd;
}

bool roundtrip(int fd, Reader& reader, const std::string& request, int replies,
               unsigned long long* errors) {
  if (!send_all(fd, request)) return false;
  for (int i = 0; i < replies; ++i) {
    bool error = false;
    if (!reader.reply(&error)) return false;
    *errors += error;
  }
  return true;
}

enum class Workload { Bitop, Rename, Sinterstore, Lmpop };

struct Result {
  unsigned long long targets = 0;
  unsigned long long errors = 0;
  bool io_ok = true;
};

std::string key(const char* stem, int connection, int ring) {
  return std::string(stem) + ':' + std::to_string(connection) + ':' +
         std::to_string(ring);
}

void worker(int port, int id, Workload workload, Result* result) {
  cpu_set_t set;
  CPU_ZERO(&set);
  CPU_SET(kLoadCpus[id % std::size(kLoadCpus)], &set);
  pthread_setaffinity_np(pthread_self(), sizeof(set), &set);

  int fd = connect_to(port);
  if (fd < 0) {
    result->io_ok = false;
    ++ready;
    return;
  }
  Reader reader(fd);
  std::string setup;
  int setup_replies = 0;
  std::vector<std::string> forward(kRings);
  std::vector<std::string> reverse(kRings);
  std::vector<std::string> replenish(kRings);

  const std::string value(32, static_cast<char>('a' + id % 26));
  for (int ring = 0; ring < kRings; ++ring) {
    std::string a = key("bb:a", id, ring);
    std::string b = key("bb:b", id, ring);
    std::string d = key("bb:d", id, ring);
    if (workload == Workload::Bitop) {
      setup += command({"SET", a, value});
      setup += command({"SET", b, value});
      setup_replies += 2;
      forward[ring] = command({"BITOP", "AND", d, a, b});
    } else if (workload == Workload::Sinterstore) {
      setup += command({"SADD", a, "base", "left"});
      setup += command({"SADD", b, "base", "right"});
      setup_replies += 2;
      forward[ring] = command({"SINTERSTORE", d, a, b});
    } else if (workload == Workload::Rename) {
      setup += command({"SET", a, value});
      ++setup_replies;
      forward[ring] = command({"RENAME", a, b});
      reverse[ring] = command({"RENAME", b, a});
    } else {
      std::string empty = key("lp:e", id, ring);
      std::string list = key("lp:l", id, ring);
      replenish[ring] = command({"RPUSH", list, value});
      forward[ring] = command({"LMPOP", "2", empty, list, "LEFT"});
    }
    if (setup_replies >= 256) {
      if (!roundtrip(fd, reader, setup, setup_replies, &result->errors)) {
        result->io_ok = false;
        close(fd);
        ++ready;
        return;
      }
      setup.clear();
      setup_replies = 0;
    }
  }
  if (setup_replies &&
      !roundtrip(fd, reader, setup, setup_replies, &result->errors)) {
    result->io_ok = false;
    close(fd);
    ++ready;
    return;
  }

  ++ready;
  while (!go.load(std::memory_order_acquire)) std::this_thread::yield();

  int cursor = 0;
  std::vector<unsigned char> direction(kRings, 0);
  while (std::chrono::steady_clock::now().time_since_epoch().count() <
         deadline_ns.load(std::memory_order_relaxed)) {
    std::string request;
    int replies = 0;
    int targets = 0;
    request.reserve(8192);
    for (int i = 0; i < kPipeline; ++i) {
      int ring = cursor++ % kRings;
      if (workload == Workload::Rename) {
        request += direction[ring] ? reverse[ring] : forward[ring];
        direction[ring] ^= 1;
      } else if (workload == Workload::Lmpop) {
        request += replenish[ring];
        request += forward[ring];
        ++replies;
      } else {
        request += forward[ring];
      }
      ++replies;
      ++targets;
    }
    if (!roundtrip(fd, reader, request, replies, &result->errors)) {
      result->io_ok = false;
      break;
    }
    result->targets += targets;
  }
  close(fd);
}

bool flushall(int port) {
  int fd = connect_to(port);
  if (fd < 0) return false;
  Reader reader(fd);
  unsigned long long errors = 0;
  bool ok = roundtrip(fd, reader, command({"FLUSHALL"}), 1, &errors);
  close(fd);
  return ok && errors == 0;
}

}  // namespace

int main(int argc, char** argv) {
  if (argc != 4) {
    std::fprintf(stderr, "usage: %s PORT {bitop|rename|sinterstore|lmpop} SECONDS\n", argv[0]);
    return 2;
  }
  int port = std::atoi(argv[1]);
  int seconds = std::atoi(argv[3]);
  Workload workload;
  std::string_view name = argv[2];
  if (name == "bitop") workload = Workload::Bitop;
  else if (name == "rename") workload = Workload::Rename;
  else if (name == "sinterstore") workload = Workload::Sinterstore;
  else if (name == "lmpop") workload = Workload::Lmpop;
  else return 2;

  if (!flushall(port)) {
    std::fprintf(stderr, "FLUSHALL failed\n");
    return 1;
  }
  std::vector<Result> results(kConnections);
  std::vector<std::thread> threads;
  for (int i = 0; i < kConnections; ++i)
    threads.emplace_back(worker, port, i, workload, &results[i]);
  while (ready.load() != kConnections) std::this_thread::yield();
  deadline_ns.store((std::chrono::steady_clock::now() + std::chrono::seconds(seconds))
                        .time_since_epoch().count());
  go.store(true, std::memory_order_release);
  for (auto& thread : threads) thread.join();

  unsigned long long targets = 0;
  unsigned long long errors = 0;
  bool io_ok = true;
  for (const Result& result : results) {
    targets += result.targets;
    errors += result.errors;
    io_ok &= result.io_ok;
  }
  std::printf("%.*s targets=%llu rate=%.0f errors=%llu io=%s\n",
              static_cast<int>(name.size()), name.data(), targets,
              static_cast<double>(targets) / seconds, errors, io_ok ? "ok" : "FAIL");
  return errors == 0 && io_ok ? 0 : 1;
}
