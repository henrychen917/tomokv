set pagination off
set confirm off
set breakpoint pending off
break tomo_db0::ExLoopT<true>::service_multi_chain<false>
commands
silent
printf "CONTROL FIRED\n"
return 0
continue
end
run
python
print("INFERIOR_EXIT", gdb.parse_and_eval("$_exitcode"))
end
