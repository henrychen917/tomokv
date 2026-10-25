/* Throwaway stale-registration control: lie about DEL only for this test port. */
#define _GNU_SOURCE
#include <dlfcn.h>
#include <stdlib.h>
#include <sys/epoll.h>
#include <sys/socket.h>
#include <netinet/in.h>
int epoll_ctl(int epfd, int operation, int fd, struct epoll_event *event) {
    static int (*real_ctl)(int,int,int,struct epoll_event *);
    if (!real_ctl) real_ctl = dlsym(RTLD_NEXT, "epoll_ctl");
    const char *port = getenv("WAVE7B_BROKEN_EPOLL_PORT");
    if (port && operation == EPOLL_CTL_DEL) {
        struct sockaddr_in address;
        socklen_t length = sizeof(address);
        int listener = 0;
        socklen_t size = sizeof(listener);
        if (getsockname(fd, (struct sockaddr *)&address, &length) == 0 &&
            address.sin_family == AF_INET && ntohs(address.sin_port) == atoi(port) &&
            getsockopt(fd, SOL_SOCKET, SO_ACCEPTCONN, &listener, &size) == 0 && !listener)
            return 0;
    }
    return real_ctl(epfd, operation, fd, event);
}
