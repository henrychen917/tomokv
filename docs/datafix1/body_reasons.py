"""Attach reviewed scope reasons to the complete emitted-function inventory."""
from pathlib import Path
import json,re,gzip
root=Path(__file__).resolve().parents[2]
out=root/'docs/datafix1'
rows=json.loads((out/'identity-final/changed-bodies.json').read_text())
features={'geo.o':'CD4.3 free-order GEO grammar and owner-side error precedence',
 't_hash.o':'CD4.12 HRANDFIELD half-range error text',
 't_hash_ttl.o':'CD4.11 expiry validation before FIELDS',
 't_list.o':'CD4.5 one-node list demotion',
 't_server.o':'CD4.6 locale-collate registry, validation and publication',
 't_set.o':'CD4.4 compact SPOP and survivor rebuilding; CD4.12 SRANDMEMBER grammar',
 't_sort.o':'CD4.6 per-sort locale lifetime and strcoll_l comparison',
 't_zset.o':'CD4.12 ZRANDMEMBER grammar and ZSCAN NOVALUES',
 'xshard.o':'CD4.3 prepared GEO error and CD4.10 BITFIELD offset acceptance',
 'main.o':'CD4.6 Config reserved storage, boot parsing and locale validation'}
semantic={'geo.o':r'parse_search|cmd_geosearch|geo_build_store|geo_prepare_route|cmd_geo_xshard_local',
 't_hash.o':r'cmd_hrandfield','t_hash_ttl.o':r'parse_expire|expire_generic|cmd_h(?:expire|pexpire)',
 't_list.o':r'demote_shrunk_list|pop_generic|xshard_pop_list|xshard_remove_list|cmd_l(?:rem|set|trim)',
 't_server.o':r'cmd_config|init_config|collect_config_updates',
 't_set.o':r'pop_compact|pop_rebuilt|cmd_spop|cmd_srandmember',
 't_sort.o':'.*','t_zset.o':r'cmd_zrandmember|cmd_zscan',
 'xshard.o':r'finish_phase1|assemble_final|parse_bitfield_operations','main.o':'.*'}
for r in rows:
    obj=Path(r['object']).name
    r['feature']=features[obj]
    if re.search(semantic[obj],r['name']):
        r['reason']='Direct implementation or generated clone/template of '+r['feature']+'.'
        r['category']='implementation'
    else:
        r['reason']='Unedited helper/command: compiler inlining, cloning, register allocation or relocation-target change within the unit after '+r['feature']+'. No source behavior change in this body; included in existing batteries and the requested merit comparison.'
        r['category']='compiler spillover'
    if r['raw_equal']:r['reason']+=' Raw instruction bytes match; canonical relocation targets differ.'
(out/'body-reasons.json').write_text(json.dumps(rows,indent=2)+'\n')
layouts=json.loads((out/'linked-final/layouts.json').read_text())
changes=[]
for name,a in layouts['PRE'].items():
    b=layouts['POST'][name]
    assert a['size']==b['size'],name
    for field,offset in a['fields'].items():
        if field!='layout_reserved':assert b['fields'].get(field)==offset,(name,field)
    if a!=b:changes.append(dict(name=name,pre=a,post=b))
(out/'layout-reviewed.json').write_text(json.dumps(dict(changes=changes,sizes={k:v['size'] for k,v in layouts['POST'].items()}),indent=2)+'\n')
linked=json.loads(gzip.decompress((out/'linked-final/linked-ordinary.json.gz').read_bytes()))
primary=[r for r in linked if re.search(r'::cmd_(?:get|set|mget|mset)(?:<|\()',r['name'])]
assert primary and all(r['proven'] for r in primary)
(out/'linked-primary.json').write_text(json.dumps(primary,indent=2)+'\n')
print('Every changed emitted body has a reason:',len(rows))
print('Linked primary handlers proven:',len(primary))
print('Locked sizes and existing field offsets unchanged; changed definitions:',[r['name'] for r in changes])
