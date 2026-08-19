/* m1 workload signals. All hot writes are IO-owner-local; model folding lives on the 4 Hz
 * controller side and is added separately so this substrate is independently reviewable. */

#include "server.h"
#include "flip_m1.h"

#include <limits.h>

tomoM1IoSignal tomo_m1_io_signals[TOMO_IO_THREADS_MAX + 1];

void tomoM1StampCommandClass(struct redisCommand *cmd) {
    tomoM1CommandClass class_id = TOMO_M1_CLASS_OTHER;

    if (cmd->proc == getCommand) class_id = TOMO_M1_CLASS_GET;
    else if (cmd->proc == setCommand) class_id = TOMO_M1_CLASS_SET;
    else if (cmd->proc == mgetCommand) class_id = TOMO_M1_CLASS_MGET;
    else if (cmd->proc == msetCommand) class_id = TOMO_M1_CLASS_MSET;
    else if (cmd->proc == zrangeCommand) class_id = TOMO_M1_CLASS_ZRANGE;
    else if (cmd->proc == delCommand) class_id = TOMO_M1_CLASS_DEL;
    else if (cmd->proc == expireCommand || cmd->proc == expireatCommand ||
             cmd->proc == pexpireCommand || cmd->proc == pexpireatCommand ||
             cmd->proc == persistCommand)
        class_id = TOMO_M1_CLASS_EXPIRE;

    cmd->tomo_m1_class = (uint8_t)class_id;
}

void tomoM1BatchDepthNote(unsigned int commands) {
    if (commands == 0) return;
    serverAssert(iotid >= 0 && iotid <= TOMO_IO_THREADS_MAX);

    if (commands > (unsigned int)(INT_MAX >> 8)) commands = (unsigned int)(INT_MAX >> 8);
    int sample_q8 = (int)(commands << 8);
    int *ewma_q8 = &tomo_m1_io_signals[iotid].batch_depth_q8;
    if (*ewma_q8 == 0)
        *ewma_q8 = sample_q8;
    else
        *ewma_q8 += (sample_q8 - *ewma_q8) >> 3;
}
