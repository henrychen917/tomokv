/*
 * Lua 5.1.5 library amalgamation for TomoKV.
 *
 * The individual files are the upstream sources vendored beside this file.  Keeping this as one
 * C translation unit makes the dependency a single build input and avoids exposing Lua's private
 * headers to the C++ build.  stdio.h must precede ldebug.h: Lua's private getline macro otherwise
 * rewrites the modern libc getline declaration when the sources are textually combined.
 */
#include <stdio.h>

#include "lapi.c"
#include "lcode.c"
#include "ldebug.c"
#include "ldo.c"
#include "ldump.c"
#include "lfunc.c"
#include "lgc.c"
#include "llex.c"
#include "lmem.c"
#include "lobject.c"
#include "lopcodes.c"
#include "lparser.c"
#include "lstate.c"
#include "lstring.c"
#include "ltable.c"
#include "ltm.c"
#include "lundump.c"
#include "lvm.c"
#include "lzio.c"

#include "lauxlib.c"
#include "lbaselib.c"
#include "lmathlib.c"
#include "ltablib.c"
#include "lstrlib.c"
