| Body | PRE bytes | storesize2 bytes | storesize3 bytes | Raw equal to PRE | Resolved-target equal |
| --- | ---: | ---: | ---: | --- | --- |
| 1. rl2s `parse<true, 32u, false, true>` callback #1 | 772 | 852 | 772 | yes | yes |
| 2. rl2s `parse<true, 32u, false, true>` callback #4 | 772 | 852 | 772 | yes | yes |
| 3. rl2s `parse<false, 0u, true, true>` callback #1 | 772 | 852 | 772 | yes | yes |
| 4. rl2s `parse<false, 0u, true, true>` callback #4 | 772 | 852 | 772 | yes | yes |
| 5. rl2s `parse<true, 32u, false, false>` callback #1 | 852 | 772 | 772 | NO | NO |
| 6. rl2s `parse<true, 32u, false, false>` callback #4 | 852 | 772 | 772 | NO | NO |
| 7. rl2s `parse<false, 32u, false, false>` callback #1 | 852 | 772 | 852 | yes | yes |
| 8. rl2s `parse<false, 32u, false, false>` callback #4 | 852 | 772 | 852 | yes | yes |
| 9. main `serve_impl<false,true,true,false,false,false>` lambda #1 | 824 | 537 | 824 | yes | yes |
| 10. reorder `FlatStore::erase_in_read_local` | 1257 | 1208 | 1257 | yes | yes |
| 11. reorder ordinary `parse<false,32,false,false>` | 18363 | 18411 | 18363 | yes | yes |
| 12. t_server `scan_home<cmd_scan::lambda>` | 1567 | 1535 | 1567 | NO | yes |
| 13. t_server `cmd_randomkey` | 653 | 663 | 653 | yes | yes |
