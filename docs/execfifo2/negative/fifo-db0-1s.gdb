set pagination off
set confirm off
set breakpoint pending off
break tomo_db0::multi_plain_write_probe
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
