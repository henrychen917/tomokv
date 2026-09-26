#include "signalacct_checks.h"
int main(int argc, char** argv) {
    return signalacct_test::run(argc > 1 ? argv[1] : "all");
}
