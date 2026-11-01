set pagination off
set confirm off
set breakpoint pending off
break tomo::ExLoopT<false>::service_txn_boundary<false>
commands
silent
printf "CONTROL FIRED\n"
return true
continue
end
run
python
print("INFERIOR_EXIT", gdb.parse_and_eval("$_exitcode"))
end
