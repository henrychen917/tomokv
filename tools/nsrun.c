/* nsrun — enter one of the two TomoKV bench namespaces without sudo.
 * Installed once with: setcap cap_sys_admin,cap_net_admin+ep /usr/local/bin/nsrun
 * Only "clientns" and "serverns" are allowed. After setns() we execvp(); file
 * capabilities do not survive exec, so the launched program runs with the
 * caller's normal privileges, inside the namespace. RLIMIT_NOFILE is inherited
 * untouched (unlike `ip netns exec`, which resets it to 1024). */
#define _GNU_SOURCE
#include <fcntl.h>
#include <sched.h>
#include <stdio.h>
#include <string.h>
#include <unistd.h>
int main(int argc, char** argv) {
    if (argc < 3) { fprintf(stderr, "usage: nsrun clientns|serverns cmd [args...]\n"); return 2; }
    if (strcmp(argv[1], "clientns") && strcmp(argv[1], "serverns")) {
        fprintf(stderr, "nsrun: namespace must be clientns or serverns\n"); return 2;
    }
    char path[64];
    snprintf(path, sizeof path, "/var/run/netns/%s", argv[1]);
    int fd = open(path, O_RDONLY | O_CLOEXEC);
    if (fd < 0) { perror("nsrun: open netns (is the rig up? systemctl status tomokv-nic)"); return 1; }
    if (setns(fd, CLONE_NEWNET) != 0) { perror("nsrun: setns"); return 1; }
    close(fd);
    execvp(argv[2], &argv[2]);
    perror("nsrun: exec");
    return 1;
}
