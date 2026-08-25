# Vendored Lua

This directory contains the Lua 5.1.5 interpreter sources copied from the complete offline Lua
tree shipped in the local Valkey checkout. The upstream version is identified by `LUA_RELEASE` in
`lua.h`; its MIT license is reproduced in `LICENSE`.

TomoKV textually includes `lua_amalgamation.c` once, under C linkage in the scripting translation
unit. Only the core, auxiliary API, and the base/table/string/math libraries are included. Package
loading, filesystem, OS, IO, and debug libraries are intentionally absent from the sandbox.
