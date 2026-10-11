### PRE/POST acknowledgement latency

Milliseconds, **p50 / p99 / max**. Sequential rows use one connection proven off
the writer. Twelve-connection and default rows report the maximum of each
statistic across all 12 connections, not a pooled percentile. Each connection
has 20 measured SETs after four warmups; sequential rows have 200. Payload is
100 bytes. Both arms use eight target cores; split uses 6:2 and 16 shards.
Defaults preserve the shipped placement, shard count and balancers. The
[per-connection CSV](docs/aoffix2/latency-connections.csv) retains every statistic.

Host one-minute load ranges are included in each row. Raw logs also retain
per-target-CPU activity and concurrent process samples. These runs share the
reserved cores with sibling lanes; use them to assess the 50 ms wait, not
as a paper-quality microsecond performance comparison.

| Shape | Policy | PRE p50/p99/max ms | POST p50/p99/max ms | PRE load | POST load |
|---|---|---:|---:|---:|---:|
| 1s-seq | off | 0.459/5.746/7.011 | 0.341/2.960/3.957 | 73.2–73.2 | 41.2–41.2 |
| 1s-seq | no | 0.742/7.010/8.615 | 0.465/4.951/5.885 | 73.2–73.2 | 41.2–41.2 |
| 1s-seq | everysec | 50.073/56.706/57.931 | 1.070/5.535/5.917 | 73.2–75.0 | 41.3–41.3 |
| 1s-seq | always | 52.804/63.252/78.664 | 2.781/6.629/6.900 | 77.1–80.0 | 41.3–41.3 |
| 2s-seq | off | 1.976/13.013/13.993 | 0.129/6.049/8.013 | 84.1–84.1 | 40.6–40.6 |
| 2s-seq | no | 0.356/13.084/13.963 | 0.478/6.988/8.028 | 84.1–84.7 | 40.6–40.6 |
| 2s-seq | everysec | 50.160/56.419/57.707 | 2.023/6.097/7.796 | 84.3–84.7 | 39.9–40.6 |
| 2s-seq | always | 51.076/63.800/64.567 | 3.964/8.899/10.590 | 83.0–84.3 | 39.9–39.9 |
| 1s-conns | off | 3.451/10.487/10.487 | 2.857/5.010/5.010 | 80.0–80.0 | 41.3–41.3 |
| 1s-conns | no | 3.011/11.623/11.623 | 2.501/6.249/6.249 | 81.2–81.2 | 41.3–41.3 |
| 1s-conns | everysec | 50.172/59.320/59.320 | 2.998/4.997/4.997 | 81.2–82.8 | 40.6–40.6 |
| 1s-conns | always | 55.041/65.818/65.818 | 3.996/6.017/6.017 | 82.8–84.1 | 40.6–40.6 |
| 2s-conns | off | 4.000/12.000/12.000 | 2.632/8.410/8.410 | 82.2–83.0 | 39.9–39.9 |
| 2s-conns | no | 3.324/12.255/12.255 | 3.021/8.046/8.046 | 82.2–82.2 | 39.9–39.9 |
| 2s-conns | everysec | 50.369/56.068/56.068 | 2.473/8.074/8.074 | 78.3–82.2 | 39.3–39.9 |
| 2s-conns | always | 55.320/66.701/66.701 | 6.306/11.064/11.064 | 77.2–78.3 | 39.3–39.3 |
| defaults | off | 3.958/11.833/11.833 | 2.495/7.006/7.006 | 76.4–77.2 | 39.3–39.3 |
| defaults | no | 4.113/12.903/12.903 | 2.973/10.003/10.003 | 76.4–76.4 | 39.1–39.3 |
| defaults | everysec | 50.227/61.144/61.144 | 2.739/7.995/7.995 | 75.4–76.4 | 39.1–39.1 |
| defaults | always | 53.773/60.684/60.684 | 5.537/11.998/11.998 | 73.3–75.4 | 39.1–39.1 |
| 2s-conns-everysec-ratio1to1 | everysec | 2.620/18.908/18.908 | 0.944/6.002/6.002 | 105.1–105.1 | 39.1–39.1 |

### Snapshot wake and reply head of line

BGSAVE seconds for 400,000 keys with 200-byte values, observed by snapshot-file
publication. Unpoked does not poll the server; poked sends PINGs every 1 ms.

| Mode | PRE unpoked/poked s | POST unpoked/poked s | PRE load | POST load |
|---|---:|---:|---:|---:|
| 1s | 0.683/0.652 | 0.407/0.449 | 73.3–73.3 | 39.4–39.4 |
| 2s | 0.717/0.615 | 0.309/0.312 | 66.9–68.4 | 34.2–34.2 |

For two connections proven on the same nonwriter IO thread, the median PING
latency alone / behind SET (five pairs) was:

- PRE: **0.192/41.458 ms**, host load 105.9–105.9.
- POST: **0.161/0.085 ms**, host load 39.4–39.4.

### TLS report-only check

TLS 1.3 GET pipelines, depth 32, eight batches per cell, three fresh boots.
The table shows the median of the three per-boot p50s in milliseconds.
Idle/poked cells use no extra traffic / PING every 1 ms. The complete
[TLS CSV](docs/aoffix2/tls-connections.csv) retains p50/p99/max for every repeat.

| Mode | Value | PRE idle/poked p50 ms | POST idle/poked p50 ms | PRE load | POST load |
|---|---:|---:|---:|---:|---:|
| 1s | 1 KiB | 0.206/0.500 | 0.172/0.117 | 71.2–73.3 | 36.2–38.5 |
| 1s | 4 KiB | 154.181/3.049 | 152.957/3.250 | 71.2–73.1 | 36.2–38.5 |
| 1s | 16 KiB | 618.083/15.791 | 614.559/11.759 | 68.4–73.1 | 35.2–38.5 |
| 2s | 1 KiB | 0.303/0.192 | 0.284/0.698 | 103.7–106.6 | 31.5–34.2 |
| 2s | 4 KiB | 158.195/6.777 | 152.576/4.151 | 103.3–105.4 | 31.5–34.2 |
| 2s | 16 KiB | 624.070/26.303 | 610.582/12.747 | 103.0–105.1 | 31.1–34.2 |
