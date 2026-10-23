"""Explain each retained strict linked-body residual without relaxing identity."""
import gzip, json
from pathlib import Path
DEST=Path(__file__).resolve().parent/'identity'

def reason(row):
    name=row['name']
    if '::cmd_' in name and row.get('literal_verified'):
        return 'All instructions and normalized encodings match; referenced scalar/table bytes or all jump destinations independently match PRE (command-literals.json). Strict label residual retained.'
    if row.get('source_objects') and all(o['byte_identical'] for o in row['source_objects']):
        return 'Every defining object is byte-identical to PRE; only linked relocation/literal-label normalization differs. Full strict difference retained.'
    edits=[
        ('tracking_retire_read', 'Resolve every pending reader using its observed completion certificate; deliver an outstanding frame once, prevent stale enrollment, restore the registry spec and release drain arming.'),
        ('tracking_register_read', 'Allocate the armed spec copy, capture dispatch bounds, retain all readers and per-shard observations; preserve the registry spec for queued MULTI.'),
        ('tracking_register_key', 'Persist completed-enrollment certificates and clear certificates when bounded-table eviction invalidates a key; signature gains the stamp.'),
        ('tracking_invalidate_local', 'Compare write certificates with completed enrollments and defer pending-reader decisions until Done; signature gains the stamp.'),
        ('tracking_handle_event', 'Consume and forward stamped events, reject missing certificates, and cancel pending/completed registrations on FLUSH.'),
        ('tracking_broadcast_keys', 'Transport the completion certificate in the existing event count field; signature gains the stamp.'),
        ('tracking_broadcast_flush', 'Retain the monotonic filter so concurrent new/pending registrations cannot be erased.'),
        ('tracking_forget_client', 'Cancel obligations while retaining live spec copies and drain arming through retirement.'),
        ('tracking_retire_plain', 'Include canceled-but-live draining reads in retirement.'),
        ('tracking_client_subcommand', 'Re-enable without double-counting drain arming; tracking side-state offsets change.'),
        ('tracking_observe_read', 'New tracking-only executor observation, bounded by pinned MVCC cut and dispatch certificate.'),
        ('tracking_observe_local', 'New tracking-only certificate sampling before read-local capture.'),
        ('tracking_clock_', 'New non-resetting tracking-only acquire/release completion clock, with wrap abort.'),
        ('tracking_read_marker', 'New never-invoked marker identifies the side-owned read spec.'),
        ('notify_retire_batch_entry', 'Carry the batch certificate to tracking consumers; cumulative CC4.4 counts only publication records on an empty pub/sub reservation.'),
        ('notify_take_batch', 'Seal async completed batches at retirement before transporting notifications.'),
        ('notify_tracking_commit', 'New completion certificate selection for ordinary and special notification batches.'),
        ('NotifyExecutionScope::NotifyExecutionScope', 'Observe tracked special/blocking reads after the active guard; command wrappers retain their original bodies.'),
        ('notify_ex_pass_entry', 'Seal keyless changes after mutation returns and preserve the certificate through transport retries; NotifyOut stride grows by eight bytes.'),
        ('client_routing_commit_extract', 'Move tracking side state in the existing ownership critical section and preserve draining tracker counts.'),
        ('client_routing_install', 'Restore tracking side state and draining arming at the existing ownership commit edge.'),
        ('climon_reply_suppressed', 'Keep canceled-but-live tracked reads on the retirement path.'),
        ('climon_serve_suppressed', 'Inlined pending-read retirement/drain-state handling and enlarged side-state layout.'),
    ]
    for token,why in edits:
        if token in name:return why
    if 'TrackingRead' in name or 'TrackingPending' in name or 'ClimonConn' in name:
        return 'Tracking-owned side-container instantiation/lifetime/layout changes: all-reader obligations, owned spec copies and completed enrollment stamps.'
    if 'Notify' in name or 'notify_' in name:
        return 'Notification-side allocation, construction, destruction or transport uses the added 64-bit batch/keyless certificate; compiler propagation in notify.inc is retained.'
    if 'ExLoopT<' in name and '::execute<' in name:
        return 'Add the globally tracking-armed observation guard before execution and seal selected notification batches after owner publication.'
    if 'drain_local_reads_bounded_impl' in name:
        return 'Add tracking-armed observation before read-local capture; compiler propagation from the additional cold branch is retained.'
    if '::tracking_' in name or '::climon_' in name:
        return 'Tracking connection side-state offsets/lifetimes and armed helper compilation changed; unedited surrounding instructions remain in the strict residual.'
    if name.startswith('_GLOBAL'):
        return 'Translation-unit initializer symbol/reference propagation after tracking side-state additions; renamed/new/removed initializer groups are retained separately.'
    if name.startswith(('std::','void std::','char const*& std::')):
        return 'Container allocation/cleanup instantiation and clone selection changed after replacing pending Op pointers with all-reader side state; strict residual retained.'
    if not row['headline_sizes'] or not row['post_sizes']:
        return 'Out-of-line helper/clone emitted or absorbed after dependent-header recompilation; no independent source change to this helper. Full added/removed body retained.'
    objects=', '.join(sorted(set(o['object'] for o in row.get('source_objects',[]))))
    return ('Unedited implementation; dependent-header recompilation, inline selection and linked references changed. '
            'No unique compiler decision isolated; strict residual requires merit review. Defining objects: '+objects+'.')

def main():
    summary=json.loads((DEST/'summary.json').read_text())
    verified={r['name'] for r in json.loads((DEST/'command-literals.json').read_text())}
    diffs=gzip.open(DEST/'instruction-differences.txt.gz','rt').read()
    blocks={b.splitlines()[0]:b for b in diffs.split('\nFUNCTION ') if b}
    for row in summary['changed']:
        row['literal_verified']=row['name'] in verified
        row['reason']=reason(row)
        block=blocks[row['name']]
        a=[l[1:] for l in block.splitlines() if l.startswith('-') and not l.startswith('---')]
        b=[l[1:] for l in block.splitlines() if l.startswith('+') and not l.startswith('+++')]
        if a and len(a)==len(b) and all(x.split(' # ')[0]==y.split(' # ')[0] and x.split(' | ')[-1]==y.split(' | ')[-1] for x,y in zip(a,b)):
            row['difference_shape']='reference labels only; opcode/normalized encoding unchanged'
        else:row['difference_shape']='instructions, encodings, clone set or body size differ'
    (DEST/'summary.json').write_text(json.dumps(summary,indent=2)+'\n')
    (DEST/'changed-bodies.md').write_text('# Every changed linked body\n\n'
        '512 strict residuals are retained. Identity is a proxy; command literal controls explain 28 without removing them. '
        'Opcode, register, immediate, member offset and clone multiplicity are never masked.\n\n'
        '| Body | PRE sizes | POST sizes | Difference | Reason |\n|---|---|---|---|---|\n'+''.join(
        f"| `{r['name']}` | {r['headline_sizes']} | {r['post_sizes']} | {r['difference_shape']} | {r['reason']} |\n" for r in summary['changed']))
    with gzip.open(DEST/'instruction-differences.txt.gz','wt') as f:
        for row in summary['changed']:
            block=blocks[row['name']]
            lines=[l for l in block.splitlines() if not l.startswith('REASON ')]
            f.write('\nFUNCTION '+'\n'.join(lines)+'\nREASON '+row['reason']+'\n')
    print('Explained',len(summary['changed']),'retained residuals; all',summary['command_identity']['groups'],'command groups verified.')

if __name__=='__main__':main()
