"""Raw-counter fixtures for serverless ABBA controls; never used by the runner."""
from abba_saturation import LbSnapshot, SATURATION_FLOOR, bottleneck_saturation


def saturation_record(mode="1s", score=99.9, threads=32, window_seconds=20, inactive_roles=()):
    wall = round(window_seconds * 1e9)
    work = round(wall * score / 100)
    before, after = {}, {}
    for tid in range(threads):
        role = "fused" if mode == "1s" else "io" if tid < threads - threads // 2 else "ex"
        before[tid] = dict(role=role, clients=0 if role == "ex" else 1,
                           ops=0, busy=0, idle=0, cpu=0)
        active = role not in inactive_roles
        after[tid] = dict(before[tid], ops=1_000_000 if active else 0,
            busy=work if active else 0, idle=wall - work if active else wall, cpu=work if active else 0)
    return bottleneck_saturation(LbSnapshot(1_000_000_000, before),
        LbSnapshot(1_000_000_000 + wall, after), floor_pct=SATURATION_FLOOR)


def quiet_record(*, cpus=tuple(range(128)), samples=2, started_at=0., finished_at=20.,
                 sample_artifact="/fake/quiet-samples.jsonl", ports=(8700,),
                 server_physical_cores=32, window_seconds=20, sampled_physical_cores=None):
    """Selected-core evidence for serverless validators; no process inventory."""
    return dict(complete=True, interference=None, started_at=started_at, finished_at=finished_at,
        samples=samples, cpu_samples=samples, sample_interval_seconds=1,
        cpus=list(cpus), requested_cpus=list(cpus), policy="selected-core-port-budget-v1",
        sample_artifact=str(sample_artifact), ports=list(ports), listener_checks=1,
        generic_cpu_screening=dict(scope="preflight", preflight_seconds=20., capacity_fraction=.0015,
            server_physical_cores=server_physical_cores, window_seconds=window_seconds,
            **({"sampled_physical_cores": sampled_physical_cores} if sampled_physical_cores else {}),
            cpu_budget_seconds=.0015 * (sampled_physical_cores or server_physical_cores) * window_seconds,
            peak_rolling=dict(cpu_ticks=0, cpu_seconds=0.)))


def workload_record(cell):
    """Complete raw workload endpoints for serverless calibration replay."""
    from abba_workloads import workload_command_names, require_workload_witness, require_workload_accounting
    names = workload_command_names(cell)
    before = {f'cmdstat_{name.lower()}': 'calls=0,usec=0' for name in names}
    after = {f'cmdstat_{name.lower()}': 'calls=100,usec=100' for name in names}
    mode = {'reorder_retired': '1', 'reorder': '0'} if cell.op == 'REORDER' else {}
    counts = {name: 100 for name in names}
    totals = [dict(connections=cell.conns, outstanding_bound=cell.conns * cell.depth,
                   reported_counts=counts, completed_hdr_counts=counts)]
    return dict(data_bytes=cell.data_bytes,
        workload_raw=dict(before=before, after=after, mode_before=mode, mode_after=mode),
        workload_witness=require_workload_witness(cell, before, after, mode, mode),
        whole_run_commandstats_before=before, whole_run_commandstats_after=after, memtier=totals,
        whole_run_accounting=require_workload_accounting(cell, before, after, totals))
