#!/usr/bin/env python3
"""Version-string lane's offline body/link/layout proof; never runs a server.

Uses the INFOFIELDS byte comparator, with only this lane's edited cold bodies
exempted from ordinary dispatch. All other emitted-body changes fail the audit.
Usage: versionstr_artifacts.py PRE_BUILD POST_BUILD OUTPUT_DIRECTORY
"""
import re

import infofields_artifacts as proof


def reason(relative, name):
    if "::parse_config_args(" in name:
        return "cold CLI parser handles --version/-v before server initialization"
    if "::print_version(" in name:
        return "shared cold product/compatibility version formatter"
    if "::print_boot_presentation<" in name:
        return "cold boot banner prints both versions before the existing geometry line"
    if relative.endswith("/cmd/t_server.o"):
        if "::(anonymous namespace)::cmd_info(" in name:
            return "INFO reports separate Redis compatibility and TomoKV identity constants"
        if "::(anonymous namespace)::cmd_hello(" in name:
            return "HELLO reports the numeric Redis compatibility constant"
    if relative.endswith("/cmd/server_tail.o") and "::(anonymous namespace)::cmd_lolwut(" in name:
        return "LOLWUT footer reports the TomoKV identity constant"
    if relative.endswith("/main.o"):
        if re.match(r"(?:main|tomokv_multidb_main)(?:\(|$|\.cold| \[)", name):
            return "cold CLI --version/-v exit before boot"
    return None


if __name__ == "__main__":
    proof.COLD = re.compile(r"::\(anonymous namespace\)::cmd_(?:info|hello|lolwut)\(")
    proof.cold_reason = reason
    proof.main()
