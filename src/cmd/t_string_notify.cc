// Compile the armed string-family instantiations in a separate translation unit. This keeps their
// code and inlining budget entirely outside the clean handler build while sharing one source of
// truth for command semantics.
#define TOMO_STRING_NOTIFY_TU 1
#include "t_string.cc"
