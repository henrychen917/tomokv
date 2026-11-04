# NT5.2 promotion, using the pinned Redis Tcl RESP client on a descriptor-limited
# server. The ordinary upstream passing subset remains unchanged.
source [file join [lindex $argv 0] tests support redis.tcl]
set c [redis 127.0.0.1 [lindex $argv 1]]
set old [lindex [$c config get maxclients] 1]
if {![catch {$c config set maxclients 1000} message]} {error "impossible maxclients accepted"}
if {![string match "ERR CONFIG SET failed (possibly related to argument 'maxclients') - The operating system is not able to handle the specified number of clients, try with *" $message]} {
    error "wrong maxclients refusal: $message"
}
if {[lindex [$c config get maxclients] 1] != $old} {error "failed CONFIG changed maxclients"}
if {[$c config set maxclients 2] != "OK"} {error "valid maxclients rejected"}
set peer [redis 127.0.0.1 [lindex $argv 1]]
if {[$peer ping] != "PONG"} {error "second client rejected"}
set excess [redis 127.0.0.1 [lindex $argv 1]]
if {![catch {$excess ping} message] || $message ne "ERR max number of clients reached"} {
    error "wrong excess-client reply: $message"
}
catch {$excess close}
$peer close
if {[$c config set maxclients $old] != "OK"} {error "restore failed"}
$c close
puts "PASS netfix2 Tcl maxclients: 6 assertions"
