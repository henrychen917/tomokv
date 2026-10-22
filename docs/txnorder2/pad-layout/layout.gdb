set pagination off
python
import gdb,json
rows={}
for ns in ("tomo","tomo_db0"):
 t=gdb.lookup_type(ns+"::Server")
 rows[ns]=dict(size=int(t.sizeof),fields={f.name:dict(bitpos=int(f.bitpos),size=int(f.type.sizeof)) for f in t.fields() if hasattr(f,"bitpos")})
json.dump(rows,open('/home/user/Projects/cx-txnfix/docs/txnorder2/pad-layout/layout.json',"w"),indent=2)
end
