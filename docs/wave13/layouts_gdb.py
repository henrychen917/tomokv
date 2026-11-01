# Source this file from gdb without running an inferior.
import gdb
import json

result = {}
locked = {'Op': 336, 'Client': 1984, 'ThreadCtx': 1408, 'Shard': 1440,
          'FlatStore': 944, 'Rob<64>': 192, 'AtomicEntry': 144, 'Config': 624}
for namespace in ('tomo', 'tomo_db0'):
    rows = {}
    for name in (*locked, 'Server', 'SnapshotManager', 'SnapshotLoadPlan'):
        typ = gdb.lookup_type(namespace + '::' + name)
        rows[name] = {'bytes': typ.sizeof}
        if name in locked:
            assert typ.sizeof == locked[name], (namespace, name, typ.sizeof)
        else:
            rows[name]['fields'] = {field.name: field.bitpos // 8 for field in typ.fields()
                                   if field.name and hasattr(field, 'bitpos')}
            rows[name]['field_bytes'] = {field.name: field.type.sizeof for field in typ.fields()
                                       if field.name and hasattr(field, 'bitpos')}
    result[namespace] = rows
print('WAVE13_LAYOUTS=' + json.dumps(result, sort_keys=True))
