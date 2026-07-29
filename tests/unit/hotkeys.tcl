# Helper function to convert flat array response to dict
proc hotkeys_array_to_dict {arr} {
    set result {}
    for {set i 0} {$i < [llength $arr]} {incr i 2} {
        set key [lindex $arr $i]
        set val [lindex $arr [expr {$i + 1}]]
        dict set result $key $val
    }
    return $result
}

start_server {tags {external:skip "hotkeys"}} {
    test {HOTKEYS START - METRICS required} {
        catch {r hotkeys start} err
        assert_match "*METRICS parameter is required*" $err
    }

    test {HOTKEYS START - METRICS with CPU only} {
        assert_equal {OK} [r hotkeys start METRICS 1 CPU]
        r set key1 value1
        assert_equal {OK} [r hotkeys stop]

        set result [lindex [r hotkeys get] 0]
        if {[llength $result] > 0 && [lindex $result 0] ne "tracking-active"} {
            set result [hotkeys_array_to_dict $result]
        }

        assert [dict exists $result "total-cpu-time-user-ms"]
        assert [dict exists $result "total-cpu-time-sys-ms"]
        assert [dict exists $result "by-cpu-time-us"]
        assert {![dict exists $result "total-net-bytes"]}
        assert {![dict exists $result "by-net-bytes"]}

        assert_equal {OK} [r hotkeys reset]
    }

    test {HOTKEYS START - METRICS with NET only} {
        assert_equal {OK} [r hotkeys start METRICS 1 NET]
        r set key1 value1
        assert_equal {OK} [r hotkeys stop]

        set result [lindex [r hotkeys get] 0]
        if {[llength $result] > 0 && [lindex $result 0] ne "tracking-active"} {
            set result [hotkeys_array_to_dict $result]
        }

        assert [dict exists $result "total-net-bytes"]
        assert [dict exists $result "by-net-bytes"]
        assert {![dict exists $result "total-cpu-time-user-ms"]}
        assert {![dict exists $result "total-cpu-time-sys-ms"]}
        assert {![dict exists $result "by-cpu-time-us"]}

        assert_equal {OK} [r hotkeys reset]
    }

    test {HOTKEYS START - METRICS with both CPU and NET} {
        assert_equal {OK} [r hotkeys start METRICS 2 CPU NET]
        r set key1 value1
        assert_equal {OK} [r hotkeys stop]

        set result [lindex [r hotkeys get] 0]
        if {[llength $result] > 0 && [lindex $result 0] ne "tracking-active"} {
            set result [hotkeys_array_to_dict $result]
        }

        assert [dict exists $result "total-cpu-time-user-ms"]
        assert [dict exists $result "total-cpu-time-sys-ms"]
        assert [dict exists $result "by-cpu-time-us"]
        assert [dict exists $result "total-net-bytes"]
        assert [dict exists $result "by-net-bytes"]

        assert_equal {OK} [r hotkeys reset]
    }

    test {HOTKEYS START - Error: session already started} {
        assert_equal {OK} [r hotkeys start METRICS 1 CPU]
        catch {r hotkeys start METRICS 1 NET} err
        assert_match "*hotkey tracking session already in progress*" $err
        assert_equal {OK} [r hotkeys stop]
        assert_equal {OK} [r hotkeys reset]
    }

    test {HOTKEYS START - Error: invalid METRICS count} {
        catch {r hotkeys start METRICS 0} err
        assert_match "*METRICS count*" $err
        catch {r hotkeys start METRICS -1} err
        assert_match "*METRICS count*" $err
    }

    test {HOTKEYS START - Error: METRICS count mismatch} {
        catch {r hotkeys start METRICS 2 CPU} err
        assert_match "*METRICS count does not match number of metric types provided*" $err
        catch {r hotkeys start METRICS 1 CPU NET} err
        assert_match "*syntax error*" $err
        catch {r hotkeys start METRICS 3 CPU NET} err
        assert_match "*METRICS count*" $err
    }

    test {HOTKEYS START - Error: METRICS invalid metrics} {
        catch {r hotkeys start METRICS 1 GPU} err
        assert_match "*METRICS no valid metrics*" $err
        catch {r hotkeys start METRICS 2 GPU NYET} err
        assert_match "*METRICS no valid metrics*" $err

        # Allowing invalid metrics gives us forward-compatibility
        assert_equal {OK} [r hotkeys start METRICS 2 GPU CPU]

        assert_equal {OK} [r hotkeys stop]
        assert_equal {OK} [r hotkeys reset]
    }

    test {HOTKEYS START - Error: METRICS same parameter} {
        catch {r hotkeys start METRICS 2 CPU CPU} err
        assert_match "*METRICS CPU*" $err
        catch {r hotkeys start METRICS 2 NET NET} err
        assert_match "*METRICS NET*" $err
    }


    test {HOTKEYS START - with COUNT parameter} {
        assert_equal {OK} [r hotkeys start METRICS 2 CPU NET COUNT 20]

        for {set i 0} {$i < 30} {incr i} {
            r set "key_$i" "value_$i"
        }

        assert_equal {OK} [r hotkeys stop]

        set result [lindex [r hotkeys get] 0]
        if {[llength $result] > 0 && [lindex $result 0] ne "tracking-active"} {
            set result [hotkeys_array_to_dict $result]
        }

        set cpu_array [dict get $result "by-cpu-time-us"]
        set net_array [dict get $result "by-net-bytes"]

        set cpu_count [expr {[llength $cpu_array] / 2}]
        set net_count [expr {[llength $net_array] / 2}]
 
        assert_lessthan_equal $cpu_count 20
        assert_lessthan_equal $net_count 20

        assert_equal {OK} [r hotkeys reset]
    }

    test {HOTKEYS START - Error: COUNT out of range} {
        catch {r hotkeys start METRICS 1 CPU COUNT 0} err
        assert_match "*COUNT must be between 1 and 64*" $err
        catch {r hotkeys start METRICS 1 CPU COUNT 100} err
        assert_match "*COUNT must be between 1 and 64*" $err
    }

    test {HOTKEYS START - with DURATION parameter} {
        assert_equal {OK} [r hotkeys start METRICS 1 CPU DURATION 1]
        after 1500

        set result [lindex [r hotkeys get] 0]
        if {[llength $result] > 0 && [lindex $result 0] eq "tracking-active"} {
            set result [hotkeys_array_to_dict $result]
        }
        assert_equal 0 [dict get $result "tracking-active"]

        assert_equal {OK} [r hotkeys reset]
    }

    test {HOTKEYS START - with SAMPLE parameter} {
        assert_equal {OK} [r hotkeys start METRICS 2 CPU NET SAMPLE 10]
        assert_equal {OK} [r hotkeys stop]
        assert_equal {OK} [r hotkeys reset]
    }

    test {HOTKEYS START - Error: SAMPLE ratio invalid} {
        catch {r hotkeys start METRICS 1 CPU SAMPLE 0} err
        assert_match "*SAMPLE ratio must be positive*" $err
    }

    test {HOTKEYS START - Error: SLOTS not allowed in non-cluster mode} {
        catch {r hotkeys start METRICS 1 CPU SLOTS 2 0 5} err
        assert_match "*SLOTS parameter cannot be used in non-cluster mode*" $err
    } {} {cluster:skip}

    test {HOTKEYS STOP - basic functionality} {
        assert_equal {OK} [r hotkeys start METRICS 2 CPU NET]
        assert_equal {OK} [r hotkeys stop]

        set result [lindex [r hotkeys get] 0]
        if {[llength $result] > 0 && [lindex $result 0] ne "tracking-active"} {
            set result [hotkeys_array_to_dict $result]
        }
        assert_equal 0 [dict get $result "tracking-active"]

        assert_equal {OK} [r hotkeys reset]
    }

    test {HOTKEYS RESET - basic functionality} {
        assert_equal {OK} [r hotkeys start METRICS 1 CPU]
        assert_equal {OK} [r hotkeys stop]
        assert_equal {OK} [r hotkeys reset]
        # After reset, GET should return nil
        set result [lindex [r hotkeys get] 0]
        assert_equal {} $result
    }

    test {HOTKEYS RESET - Error: session in progress} {
        assert_equal {OK} [r hotkeys start METRICS 1 CPU]
        catch {r hotkeys reset} err
        assert_match "*hotkey tracking session in progress, stop tracking first*" $err
        assert_equal {OK} [r hotkeys stop]
        assert_equal {OK} [r hotkeys reset]
    }

    test {HOTKEYS GET - returns nil when not started} {
        set result [lindex [r hotkeys get] 0]
        assert_equal {} $result
    }

    test {HOTKEYS GET - sample-ratio field} {
        assert_equal {OK} [r hotkeys start METRICS 2 CPU NET SAMPLE 5]
        assert_equal {OK} [r hotkeys stop]

        set result [lindex [r hotkeys get] 0]
        if {[llength $result] > 0 && [lindex $result 0] ne "tracking-active"} {
            set result [hotkeys_array_to_dict $result]
        }
        assert_equal 5 [dict get $result "sample-ratio"]

        assert_equal {OK} [r hotkeys reset]
    }

    test {HOTKEYS - nested commands} {
        assert_equal {OK} [r hotkeys start METRICS 1 NET]
        r eval "redis.call('set', 'x', 1)" 1 x
        r eval "redis.call('set', 'y', 1)" 1 y
        r eval "redis.call('set', 'x', 2)" 1 x
        r eval "redis.call('set', 'x', 3)" 1 x

        set result [lindex [r hotkeys get] 0]
        set result [dict get $result "by-net-bytes"]
        assert [dict exists $result "x"]
        assert [dict exists $result "y"]

        assert_equal {OK} [r hotkeys stop]
        assert_equal {OK} [r hotkeys reset]
    }

    test {HOTKEYS - commands inside MULTI/EXEC} {
        set key1 "key1\{t\}"
        set key2 "key2\{t\}"

        assert_equal {OK} [r hotkeys start METRICS 2 CPU NET]
        r multi
        # Send multiple commands to avoid <1us cpu for $key2 which we assert
        # at end of test
        for {set i 0} {$i < 7} {incr i} {
            r set $key1 value1
            r set $key2 value1
            r set $key1 value2
            r set $key1 value3
        }
        r exec

        assert_equal {OK} [r hotkeys stop]
        set result [lindex [r hotkeys get] 0]
        assert_equal {OK} [r hotkeys reset]

        # Check NET metrics
        set net_result [dict get $result "by-net-bytes"]
        # Both keys should be tracked from within the MULTI/EXEC block
        assert [dict exists $net_result $key1]
        assert [dict exists $net_result $key2]
        # key1 should have more bytes than key2 since it's accessed more times
        assert {[dict get $net_result $key1] > [dict get $net_result $key2]}

        # Check CPU metrics
        set cpu_result [dict get $result "by-cpu-time-us"]
        # Both keys should be tracked from within the MULTI/EXEC block
        assert [dict exists $cpu_result $key1]
        assert [dict exists $cpu_result $key2]
    }

    test {HOTKEYS - EVAL inside MULTI/EXEC with nested calls} {
        set key1 "evalkey1\{t\}"
        set key2 "evalkey2\{t\}"

        assert_equal {OK} [r hotkeys start METRICS 1 NET]
        r multi
        r eval {redis.call('set', KEYS[1], 'value1')} 1 $key1
        r eval {redis.call('set', KEYS[1], 'value2'); redis.call('set', KEYS[1], 'value3')} 1 $key1
        r eval {redis.call('set', KEYS[1], 'value4')} 1 $key2
        r exec

        assert_equal {OK} [r hotkeys stop]
        set result [lindex [r hotkeys get] 0]
        assert_equal {OK} [r hotkeys reset]

        # Check NET metrics - both keys should be tracked through EVAL commands
        set net_result [dict get $result "by-net-bytes"]
        assert [dict exists $net_result $key1]
        assert [dict exists $net_result $key2]
        # key1 should have more bytes than key2 since it's accessed by more EVAL commands
        assert {[dict get $net_result $key1] > [dict get $net_result $key2]}
    }

    test {HOTKEYS GET - no conditional fields without selected slots} {
        assert_equal {OK} [r hotkeys start METRICS 2 CPU NET SAMPLE 10]
        r set key1 value1
        assert_equal {OK} [r hotkeys stop]

        set result [lindex [r hotkeys get] 0]
        if {[llength $result] > 0 && [lindex $result 0] ne "tracking-active"} {
            set result [hotkeys_array_to_dict $result]
        }

        # Should NOT have selected-slots conditional fields
        assert {![dict exists $result "sampled-commands-selected-slots-us"]}
        assert {![dict exists $result "all-commands-selected-slots-us"]}
        assert {![dict exists $result "net-bytes-sampled-commands-selected-slots"]}
        assert {![dict exists $result "net-bytes-all-commands-selected-slots"]}

        # Should have all-slots fields
        assert [dict exists $result "all-commands-all-slots-us"]
        assert [dict exists $result "net-bytes-all-commands-all-slots"]

        assert_equal {OK} [r hotkeys reset]
    }

    foreach sample_ratio {1 100 500 1000} {
        test "HOTKEYS detection with biased key access, sample ratio = $sample_ratio" {
            # Generate 100 random keys
            set all_keys {}
            for {set i 0} {$i < 100} {incr i} {
                lappend all_keys "key_[format %03d $i]"
            }

            # Choose 20 keys to bias towards. These will be out hot keys
            set hot_keys {}
            for {set i 0} {$i < 20} {incr i} {
                lappend hot_keys [lindex $all_keys $i]
            }

            assert_equal {OK} [r hotkeys start METRICS 2 CPU NET SAMPLE $sample_ratio]

            # Biasing towards the 20 chosen keys when sending commands
            set total_commands 50000
            for {set i 0} {$i < $total_commands} {incr i} {
                set rand [expr {rand()}]
                if {$rand < 0.8} {
                    set key [lindex $hot_keys [expr {int(rand() * 20)}]]
                } else {
                    set key [lindex $all_keys [expr {20 + int(rand() * 80)}]]
                }
                r set $key "value_$i"
            }

            assert_equal {OK} [r hotkeys stop]

            set result [lindex [r hotkeys get] 0]
            assert_not_equal $result {}

            # Convert to dict if it's a flat array
            if {[llength $result] > 0 && [lindex $result 0] ne "tracking-active"} {
                set result [hotkeys_array_to_dict $result]
            }

            set cpu_time_array [dict get $result "by-cpu-time-us"]
            set net_bytes_array [dict get $result "by-net-bytes"]

            set returned_cpu_keys {}
            for {set i 0} {$i < [llength $cpu_time_array]} {incr i 2} {
                lappend returned_cpu_keys [lindex $cpu_time_array $i]
            }

            # Check that most of returned keys (based on cpu time) are from our
            # hot_keys list
            set num_returned_cpu [llength $returned_cpu_keys]
            assert_lessthan_equal $num_returned_cpu 10
            assert_morethan $num_returned_cpu 0

            set res 0
            foreach key $returned_cpu_keys {
                if {[lsearch -exact $hot_keys $key] >= 0} {
                    incr res
                }
            }
            assert_morethan $res 5

            set returned_net_keys {}
            for {set i 0} {$i < [llength $net_bytes_array]} {incr i 2} {
                lappend returned_net_keys [lindex $net_bytes_array $i]
            }

            # Same as cpu-time but for net-bytes
            set num_returned_net [llength $returned_net_keys]
            assert_lessthan_equal $num_returned_net 10
            assert_morethan $num_returned_net 0

            set res_net 0
            foreach key $returned_net_keys {
                if {[lsearch -exact $hot_keys $key] >= 0} {
                    incr res_net
                }
            }
            assert_morethan $res_net 5

            assert_equal {OK} [r hotkeys reset]
        }
    }
}

start_server {tags {external:skip "hotkeys"}} {
    test {HOTKEYS GET - RESP3 returns map with flat array values for hotkeys} {
        r hello 3

        assert_equal {OK} [r hotkeys start METRICS 2 CPU NET]
        r set testkey testvalue
        assert_equal {OK} [r hotkeys stop]

        set result [lindex [r hotkeys get] 0]

        # In RESP3, the outer result is a native map (dict)
        assert [dict exists $result "tracking-active"]
        assert [dict exists $result "sample-ratio"]
        assert [dict exists $result "selected-slots"]
        assert [dict exists $result "by-cpu-time-us"]
        assert [dict exists $result "by-net-bytes"]

        # Verify by-cpu-time-us is a flat array [key1, val1, key2, val2, ...]
        set cpu_array [dict get $result "by-cpu-time-us"]
        # Flat array length should be even (key-value pairs)
        assert {[llength $cpu_array] % 2 == 0}
        # First element is the key name (string), second is the value (integer)
        set first_key [lindex $cpu_array 0]
        set first_val [lindex $cpu_array 1]
        assert_equal "testkey" $first_key
        assert {[string is integer $first_val]}

        # Verify by-net-bytes is a flat array [key1, val1, key2, val2, ...]
        set net_array [dict get $result "by-net-bytes"]
        # Flat array length should be even (key-value pairs)
        assert {[llength $net_array] % 2 == 0}
        # First element is the key name (string), second is the value (integer)
        set first_key [lindex $net_array 0]
        set first_val [lindex $net_array 1]
        assert_equal "testkey" $first_key
        assert {[string is integer $first_val]}

        assert_equal {OK} [r hotkeys reset]
    }

    test {HOTKEYS GET - selected-slots returns full range in non-cluster mode} {
        assert_equal {OK} [r hotkeys start METRICS 1 CPU]
        assert_equal {OK} [r hotkeys stop]

        set result [lindex [r hotkeys get] 0]
        if {[llength $result] > 0 && [lindex $result 0] ne "tracking-active"} {
            set result [hotkeys_array_to_dict $result]
        }
        set slots [dict get $result "selected-slots"]
        # Should return single range [[0, 16383]]
        assert_equal 1 [llength $slots]
        set range [lindex $slots 0]
        assert_equal 2 [llength $range]
        assert_equal 0 [lindex $range 0]
        assert_equal 16383 [lindex $range 1]

        assert_equal {OK} [r hotkeys reset]
    }
}
