#include <sys/prctl.h>
#include <unistd.h>
__attribute__((constructor)) static void owned_debugger(void) { if (prctl(PR_SET_PTRACER, PR_SET_PTRACER_ANY, 0, 0, 0)) _exit(125); }
