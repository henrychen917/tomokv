| Row (`case-mode-variant-engine`) | PRE | POST | PRE / POST seconds |
|---|---|---|---:|
| `acks-1s-sigterm-uring` | lost 6/8 acknowledged values | exit 0, all assertions pass | 7.573 / 10.219 |
| `acks-1s-command-uring` | lost 5/8 acknowledged values | exit 0, all assertions pass | 8.272 / 9.786 |
| `acks-2s-sigterm-uring` | lost 7/8 acknowledged values | exit 0, all assertions pass | 6.604 / 7.088 |
| `acks-2s-command-uring` | lost 8/8 acknowledged values | exit 0, all assertions pass | 7.152 / 6.348 |
| `bgsave-1s-0-uring` | SIGABRT (-6), orphan temp | exit 0, all assertions pass | 5.643 / 4.486 |
| `bgsave-1s-1-uring` | SIGABRT (-6), orphan temp | exit 0, all assertions pass | 5.550 / 4.265 |
| `bgsave-2s-0-uring` | SIGABRT (-6), orphan temp | exit 0, all assertions pass | 5.649 / 5.316 |
| `bgsave-2s-1-uring` | SIGABRT (-6), orphan temp | exit 0, all assertions pass | 6.544 / 5.617 |
| `rewrite-1s-0-uring` | SIGABRT (-6), orphan temp | exit 0, all assertions pass | 20.800 / 18.123 |
| `rewrite-1s-1-uring` | SIGABRT (-6), orphan temp | exit 0, all assertions pass | 30.601 / 29.279 |
| `rewrite-2s-0-uring` | SIGABRT (-6), orphan temp | exit 0, all assertions pass | 26.136 / 24.769 |
| `rewrite-2s-1-uring` | SIGABRT (-6), orphan temp | exit 0, all assertions pass | 26.437 / 25.409 |
| `acks-1s-sigterm-epoll` | lost 6/8 acknowledged values | exit 0, all assertions pass | 14.479 / 12.659 |
| `acks-1s-command-epoll` | lost 7/8 acknowledged values | exit 0, all assertions pass | 13.200 / 11.293 |
| `acks-2s-sigterm-epoll` | lost 5/8 acknowledged values | exit 0, all assertions pass | 9.532 / 8.524 |
| `acks-2s-command-epoll` | lost 5/8 acknowledged values | exit 0, all assertions pass | 9.373 / 8.174 |
| `bgsave-1s-0-epoll` | SIGABRT (-6), orphan temp | exit 0, all assertions pass | 7.102 / 5.397 |
| `bgsave-1s-1-epoll` | SIGABRT (-6), orphan temp | exit 0, all assertions pass | 6.403 / 4.872 |
| `bgsave-2s-0-epoll` | SIGABRT (-6), orphan temp | exit 0, all assertions pass | 7.237 / 5.303 |
| `bgsave-2s-1-epoll` | SIGABRT (-6), orphan temp | exit 0, all assertions pass | 7.082 / 5.416 |
| `rewrite-1s-0-epoll` | SIGABRT (-6), orphan temp | exit 0, all assertions pass | 19.695 / 17.425 |
| `rewrite-1s-1-epoll` | SIGABRT (-6), orphan temp | exit 0, all assertions pass | 30.388 / 28.118 |
| `rewrite-2s-0-epoll` | SIGABRT (-6), orphan temp | exit 0, all assertions pass | 27.462 / 25.479 |
| `rewrite-2s-1-epoll` | SIGABRT (-6), orphan temp | exit 0, all assertions pass | 27.673 / 28.888 |
