// Open N connections, PING each so the server has fully accepted and armed them, then hold until
// stdin closes. Per-connection state is what this lane grows, so the instrument is RSS with the
// connections up minus RSS with none -- not a rate.
#include <arpa/inet.h>
#include <netinet/in.h>
#include <netinet/tcp.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/socket.h>
#include <unistd.h>

int main(int argc, char** argv) {
    if (argc < 3) { fprintf(stderr, "holdconns <port> <n>\n"); return 2; }
    int port = atoi(argv[1]), n = atoi(argv[2]);
    int* fds = calloc(n, sizeof(int));
    struct sockaddr_in a = {0};
    a.sin_family = AF_INET; a.sin_port = htons(port);
    a.sin_addr.s_addr = inet_addr("127.0.0.1");
    int up = 0;
    for (int i = 0; i < n; i++) {
        int fd = socket(AF_INET, SOCK_STREAM, 0);
        if (fd < 0) break;
        if (connect(fd, (struct sockaddr*)&a, sizeof a) != 0) { close(fd); break; }
        int one = 1; setsockopt(fd, IPPROTO_TCP, TCP_NODELAY, &one, sizeof one);
        if (write(fd, "PING\r\n", 6) != 6) { close(fd); break; }
        char buf[64];
        if (read(fd, buf, sizeof buf) <= 0) { close(fd); break; }
        fds[i] = fd; up++;
    }
    printf("%d\n", up); fflush(stdout);
    char c; while (read(0, &c, 1) > 0) {}
    return 0;
}
