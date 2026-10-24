#!/usr/bin/env python3
"""CG4.3: physical config lines, comments, quoting and no line continuation."""
from _serverfix import main, Server


def probe(run, mode, label, extra):
    cases = [
        ('comment-garbage', '#' + 'x' * 4094 + 'garbage\n', True, b''),
        ('comment-password', '#' + 'x' * 4094 + 'requirepass hidden\n', True, b''),
        ('comment-many-chunks', ' \t#' + 'x' * 131072 + '\r\n', True, b''),
        ('comment-eof', '#' + 'x' * 8192 + 'requirepass hidden', True, b''),
        ('raw-nul-comment', '#\0discard\nrequirepass hidden\n', True, b''),
        ('raw-nul-directive', 'requirepass first\0discard\ntimeout 0\n', False, b''),
        ('long-quoted', 'requirepass "' + 'x' * 32768 + '"\n', True, b'x' * 32768),
        ('long-eof', 'requirepass ' + 'x' * 8192, True, b'x' * 8192),
        ('case-and-crlf', ' ReQuIrEpAsS "a b#c\\x21" \r\n', True, b'a b#c!'),
        ('single-quote', "requirepass 'a\\'b#c'\n", True, b"a'b#c"),
        ('prefix-quote', 'requirepass pre"fix space"\n', True, b'prefix space'),
        ('unquoted-backslash', 'requirepass pass\\word\n', True, b'pass\\word'),
        ('no-continuation', 'requirepass "first\\\nsecond"\n', False, b''),
        ('no-inline-comment', 'timeout 0 #comment\n', False, b''),
        ('closing-quote', 'requirepass "hello"tail\n', False, b''),
        ('unbalanced-long', 'requirepass "' + 'x' * 8192, False, b''),
    ]
    for name, text, accepted, password in cases:
        case = label + '-' + name
        if len(password) > 4096:
            # Redis caps unauthenticated bulks. Read the long config value through a
            # short, independent ACL credential instead of tripping that protocol guard.
            text = 'user inspector on nopass ~* &* +@all\n' + text
        conf = run.conf(case, text)
        with Server(run, case, mode, conf, extra, refusal=True) as server:
            run.check(case + ' startup', server.booted, accepted)
            if server.booted:
                with server.client() as client:
                    if password:
                        auth = ('AUTH', 'inspector', '') if len(password) > 4096 else ('AUTH', password)
                        run.check(case + ' authenticated access', client.cmd(*auth), b'OK')
                    run.check(case + ' comment did not enable auth', client.cmd('PING'), b'PONG')
                    run.check(case + ' decoded bytes', client.cmd('CONFIG', 'GET', 'requirepass'),
                              [b'requirepass', password])
            else:
                run.check(case + ' startup error exit', server.process.poll(), 1)


if __name__ == '__main__':
    raise SystemExit(main(probe))
