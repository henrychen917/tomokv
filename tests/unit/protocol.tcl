start_server {tags {"protocol network"}} {
    test "Handle an empty query" {
        reconnect
        r write "\r\n"
        r flush
        assert_equal "PONG" [r ping]
    }

    test "Negative multibulk length" {
        reconnect
        r write "*-10\r\n"
        r flush
        assert_equal PONG [r ping]
    }

    test "Out of range multibulk length" {
        reconnect
        r write "*3000000000\r\n"
        r flush
        assert_error "*invalid multibulk length*" {r read}
    }

    test "Wrong multibulk payload header" {
        reconnect
        r write "*3\r\n\$3\r\nSET\r\n\$1\r\nx\r\nfooz\r\n"
        r flush
        assert_error "*expected '$', got 'f'*" {r read}
    }

    test "Negative multibulk payload length" {
        reconnect
        r write "*3\r\n\$3\r\nSET\r\n\$1\r\nx\r\n\$-10\r\n"
        r flush
        assert_error "*invalid bulk length*" {r read}
    }

    test "Out of range multibulk payload length" {
        reconnect
        r write "*3\r\n\$3\r\nSET\r\n\$1\r\nx\r\n\$2000000000\r\n"
        r flush
        assert_error "*invalid bulk length*" {r read}
    }

    test "Non-number multibulk payload length" {
        reconnect
        r write "*3\r\n\$3\r\nSET\r\n\$1\r\nx\r\n\$blabla\r\n"
        r flush
        assert_error "*invalid bulk length*" {r read}
    }

    test "Multi bulk request not followed by bulk arguments" {
        reconnect
        r write "*1\r\nfoo\r\n"
        r flush
        assert_error "*expected '$', got 'f'*" {r read}
    }

    test "Generic wrong number of args" {
        reconnect
        assert_error "*wrong*arguments*ping*" {r ping x y z}
    }

    test "Unbalanced number of quotes" {
        reconnect
        r write "set \"\"\"test-key\"\"\" test-value\r\n"
        r write "ping\r\n"
        r flush
        assert_error "*unbalanced*" {r read}
    }

    set c 0
    foreach seq [list "\x00" "*\x00" "$\x00"] {
        incr c
        test "Protocol desync regression test #$c" {
            if {$::tls} {
                set s [::tls::socket [srv 0 host] [srv 0 port]]
            } else {
                set s [socket [srv 0 host] [srv 0 port]]
            }
            puts -nonewline $s $seq
            set payload [string repeat A 1024]"\n"
            set test_start [clock seconds]
            set test_time_limit 30
            while 1 {
                if {[catch {
                    puts -nonewline $s payload
                    flush $s
                    incr payload_size [string length $payload]
                }]} {
                    set retval [gets $s]
                    close $s
                    break
                } else {
                    set elapsed [expr {[clock seconds]-$test_start}]
                    if {$elapsed > $test_time_limit} {
                        close $s
                        error "assertion:Redis did not closed connection after protocol desync"
                    }
                }
            }
            set retval
        } {*Protocol error*}
    }
    unset c

    # recover the broken connection
    reconnect
    r ping

    # raw RESP response tests
    r readraw 1

    set nullres {*-1}
    if {$::force_resp3} {
        set nullres {_}
    }

    test "raw protocol response" {
        r srandmember nonexisting_key
    } "$nullres"

    r deferred 1

    test "raw protocol response - deferred" {
        r srandmember nonexisting_key
        r read
    } "$nullres"

    test "raw protocol response - multiline" {
        r sadd ss a
        assert_equal [r read] {:1}
        r srandmember ss 100
        assert_equal [r read] {*1}
        assert_equal [r read] {$1}
        assert_equal [r read] {a}
    }

    test "bulk reply protocol" {
        # value=2 (int encoding)
        r set crlf 2
        assert_equal [r rawread 5] "+OK\r\n"
        r get crlf
        assert_equal [r rawread 7] "\$1\r\n2\r\n"

        # value=2147483647 (int encoding)
        r set crlf 2147483647
        assert_equal [r rawread 5] "+OK\r\n"
        r get crlf
        assert_equal [r rawread 17] "\$10\r\n2147483647\r\n"

        # value=-2147483648 (int encoding)
        r set crlf -2147483648
        assert_equal [r rawread 5] "+OK\r\n"
        r get crlf
        assert_equal [r rawread 18] "\$11\r\n-2147483648\r\n"

        # value=-9223372036854775809 (embstr encoding)
        r set crlf -9223372036854775809
        assert_equal [r rawread 5] "+OK\r\n"
        r get crlf
        assert_equal [r rawread 27] "\$20\r\n-9223372036854775809\r\n"

        # value=9223372036854775808 (embstr encoding)
        r set crlf 9223372036854775808
        assert_equal [r rawread 5] "+OK\r\n"
        r get crlf
        assert_equal [r rawread 26] "\$19\r\n9223372036854775808\r\n"

        # normal sds (embstr encoding)
        r set crlf aaaaaaaaaaaaaaaa
        assert_equal [r rawread 5] "+OK\r\n"
        r get crlf
        assert_equal [r rawread 23] "\$16\r\naaaaaaaaaaaaaaaa\r\n"

        # normal sds (raw string encoding) with 45 'a'
        set rawstr [string repeat "a" 45]
        r set crlf $rawstr
        assert_equal [r rawread 5] "+OK\r\n"
        r get crlf
        assert_equal [r rawread 52] "\$45\r\n$rawstr\r\n"

        r del crlf
        assert_equal [r rawread 4] ":1\r\n"
    }

    # restore connection settings
    r readraw 0
    r deferred 0

    test {large worker reply-buffer transfer preserves exact RESP bytes} {
        r del reply-buffer-transfer
        set value [string repeat x 64]
        set values [lrepeat 128 $value]
        r rpush reply-buffer-transfer {*}$values

        set element "\$64\r\n${value}\r\n"
        set expected "*128\r\n[string repeat $element 128]"
        set old_transfer [lindex [r config get tomokv-reply-buffer-transfer] 1]
        set rc [redis_client]

        r config set tomokv-reply-buffer-transfer no
        $rc readraw 1
        set disabled "[$rc lrange reply-buffer-transfer 0 -1]\r\n"
        append disabled [$rc rawread [expr {[string length $expected] - [string length $disabled]}]]
        $rc readraw 0

        r config set tomokv-reply-buffer-transfer yes
        $rc readraw 1
        set enabled "[$rc lrange reply-buffer-transfer 0 -1]\r\n"
        append enabled [$rc rawread [expr {[string length $expected] - [string length $enabled]}]]
        $rc readraw 0
        $rc close
        r config set tomokv-reply-buffer-transfer $old_transfer

        assert_equal $expected $disabled
        assert_equal $disabled $enabled
    }

    test {reply iovec preserves large, aggregate, and pipelined RESP bytes} {
        # Encode requests and expected bulk replies ourselves so this test
        # compares the complete byte stream, including every length/header and
        # CRLF, rather than trusting the client library's RESP decoder.
        proc reply_iovec_command {args} {
            set out "*[llength $args]\r\n"
            foreach arg $args {
                append out "\$[string length $arg]\r\n$arg\r\n"
            }
            return $out
        }
        proc reply_iovec_bulk {value} {
            return "\$[string length $value]\r\n$value\r\n"
        }

        set v1k  [string repeat a 1024]
        set v16k [string repeat b 16384]
        set v64k [string repeat c 65536]
        set small tiny
        set k1     reply-iovec:{8}:1k
        set k16    reply-iovec:{8}:16k
        set k64    reply-iovec:{8}:64k
        set ksmall reply-iovec:{8}:small
        set kl     reply-iovec:{8}:list
        set kh     reply-iovec:{8}:hash
        set ks     reply-iovec:{8}:set
        set kspop  reply-iovec:{8}:set-pop
        set kzrand reply-iovec:{8}:zset-rand

        r set $k1 $v1k
        r set $k16 $v16k
        r set $k64 $v64k
        r set $ksmall $small
        r del $kl $kh $ks $kspop $kzrand
        r rpush $kl $small $v16k $v64k
        r hset $kh $v16k $v64k
        r sadd $ks $v16k
        r sadd $kspop $v16k
        # Count > cardinality takes ZRANDMEMBER's deterministic full-scan
        # branch. For a skiplist-encoded large member that branch hands a new,
        # owned SDS to addReplyBulkSds, directly exercising the new adoption.
        r zadd $kzrand 1 $v16k

        set old_iovec [lindex [r config get tomokv-reply-iovec] 1]
        set old_zc [lindex [r config get tomokv-zerocopy-min-value] 1]
        set old_transfer [lindex [r config get tomokv-reply-buffer-transfer] 1]
        r config set tomokv-zerocopy-min-value 1024
        r config set tomokv-reply-buffer-transfer yes
        r config set tomokv-reply-iovec yes

        set rc [redis_client]

        # Exact GET replies at the threshold and across several send sizes.
        set request ""
        set expected ""
        foreach {key value} [list $k1 $v1k $k16 $v16k $k64 $v64k] {
            append request [reply_iovec_command GET $key]
            append expected [reply_iovec_bulk $value]
        }
        $rc write $request
        $rc flush
        set actual [$rc rawread [string length $expected]]
        assert {[string equal $actual $expected]}

        # Large multi-bulk list/hash/set elements. One-element hash/set replies
        # make their otherwise-unspecified iteration order byte-deterministic.
        set list_reply "*3\r\n[reply_iovec_bulk $small][reply_iovec_bulk $v16k][reply_iovec_bulk $v64k]"
        set hash_reply "*2\r\n[reply_iovec_bulk $v16k][reply_iovec_bulk $v64k]"
        set set_reply "*1\r\n[reply_iovec_bulk $v16k]"
        set request "[reply_iovec_command LRANGE $kl 0 -1][reply_iovec_command HGETALL $kh][reply_iovec_command SMEMBERS $ks]"
        set expected "$list_reply$hash_reply$set_reply"
        $rc write $request
        $rc flush
        set actual [$rc rawread [string length $expected]]
        assert {[string equal $actual $expected]}

        # Interleave tiny and large replies, a detached SPOP object, the owned
        # ZRANDMEMBER SDS, and same-key mutations in one pipeline. APPEND must
        # COW the pinned 16 KiB value, so the earlier GET cannot tear/change.
        set appended "${v16k}tail"
        set request ""
        append request [reply_iovec_command GET $ksmall]
        append request [reply_iovec_command GET $k64]
        append request [reply_iovec_command PING]
        append request [reply_iovec_command SPOP $kspop]
        append request [reply_iovec_command ZRANDMEMBER $kzrand 2]
        append request [reply_iovec_command GET $k16]
        append request [reply_iovec_command APPEND $k16 tail]
        append request [reply_iovec_command GET $k16]
        append request [reply_iovec_command GET $k1]

        set expected "[reply_iovec_bulk $small][reply_iovec_bulk $v64k]+PONG\r\n"
        append expected [reply_iovec_bulk $v16k]
        append expected "*1\r\n[reply_iovec_bulk $v16k]"
        append expected [reply_iovec_bulk $v16k]
        append expected ":[string length $appended]\r\n"
        append expected [reply_iovec_bulk $appended]
        append expected [reply_iovec_bulk $v1k]

        $rc write $request
        $rc flush
        set actual [$rc rawread [string length $expected]]
        assert {[string equal $actual $expected]}
        $rc close

        r config set tomokv-reply-iovec $old_iovec
        r config set tomokv-reply-buffer-transfer $old_transfer
        r config set tomokv-zerocopy-min-value $old_zc
        rename reply_iovec_command {}
        rename reply_iovec_bulk {}
    }

    # check the connection still works
    assert_equal [r ping] {PONG}

    test {RESP3 attributes} {
        r hello 3
        assert_equal {Some real reply following the attribute} [r debug protocol attrib]
        assert_equal {key-popularity {key:123 90}} [r attributes]

        # make sure attributes are not kept from previous command
        r ping
        assert_error {*attributes* no such element in array} {r attributes}

        # restore state
        r hello 2
        set _ ""
    } {} {needs:debug resp3}

    test {RESP3 attributes readraw} {
        r hello 3
        r readraw 1
        r deferred 1

        r debug protocol attrib
        assert_equal [r read] {|1}
        assert_equal [r read] {$14}
        assert_equal [r read] {key-popularity}
        assert_equal [r read] {*2}
        assert_equal [r read] {$7}
        assert_equal [r read] {key:123}
        assert_equal [r read] {:90}
        assert_equal [r read] {$39}
        assert_equal [r read] {Some real reply following the attribute}

        # restore state
        r readraw 0
        r deferred 0
        r hello 2
        set _ {}
    } {} {needs:debug resp3}

    test {RESP3 attributes on RESP2} {
        r hello 2
        set res [r debug protocol attrib]
        set _ $res
    } {Some real reply following the attribute} {needs:debug}

    test "test big number parsing" {
        r hello 3
        r debug protocol bignum
    } {1234567999999999999999999999999999999} {needs:debug resp3}

    test "test bool parsing" {
        r hello 3
        assert_equal [r debug protocol true] 1
        assert_equal [r debug protocol false] 0
        r hello 2
        assert_equal [r debug protocol true] 1
        assert_equal [r debug protocol false] 0
        set _ {}
    } {} {needs:debug resp3}

    test "test verbatim str parsing" {
        r hello 3
        r debug protocol verbatim
    } "This is a verbatim\nstring" {needs:debug resp3}

    test "test large number of args" {
        r flushdb
        set args [split [string trim [string repeat "k v " 10000]]]
        lappend args "{k}2" v2
        r mset {*}$args
        assert_equal [r get "{k}2"] v2
    }
    
    test "test argument rewriting - issue 9598" {
        # INCRBYFLOAT uses argument rewriting for correct float value propagation.
        # We use it to make sure argument rewriting works properly. It's important 
        # this test is run under valgrind to verify there are no memory leaks in 
        # arg buffer handling.
        r flushdb

        # Test normal argument handling
        r set k 0
        assert_equal [r incrbyfloat k 1.0] 1
        
        # Test argument handing in multi-state buffers
        r multi
        r incrbyfloat k 1.0
        assert_equal [r exec] 2
    }

}

start_server {tags {"regression"}} {
    test "Regression for a crash with blocking ops and pipelining" {
        set rd [redis_deferring_client]
        set fd [r channel]
        set proto "*3\r\n\$5\r\nBLPOP\r\n\$6\r\nnolist\r\n\$1\r\n0\r\n"
        puts -nonewline $fd $proto$proto
        flush $fd
        set res {}

        $rd rpush nolist a
        $rd read
        $rd rpush nolist a
        $rd read
        $rd close
    }
}

start_server {tags {"regression"}} {
    test "Regression for a crash with cron release of client arguments" {
        r write "*3\r\n"
        r flush
        after 3000 ;# wait for c->argv to be released due to timeout
        r write "\$3\r\nSET\r\n\$3\r\nkey\r\n\$1\r\n0\r\n"
        r flush
        r read
    } {OK}
}
