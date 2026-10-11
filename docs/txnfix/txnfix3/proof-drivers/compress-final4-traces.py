import gzip,hashlib,json,pathlib
root=pathlib.Path('docs/txnfix/txnfix3');rows=[]
for name in ['scatter-final4','prepare-final4','prepare-stream-final4','read-final4','scan-final4']:
 folder=root/name
 assert (folder/'runs.json').exists()
 for p in sorted(folder.iterdir()):
  if p.name.endswith(('-trace.json','-ranges.json','.log')):
   data=p.read_bytes();out=pathlib.Path(str(p)+'.gz')
   assert not out.exists()
   with gzip.GzipFile(filename=str(out),mode='wb',mtime=0) as f:f.write(data)
   assert gzip.decompress(out.read_bytes())==data
   rows.append(dict(path=str(p),gzip=str(out),bytes=len(data),compressed_bytes=out.stat().st_size,sha256=hashlib.sha256(data).hexdigest()))
   p.unlink()
(root/'final4-compressed-traces.json').write_text(json.dumps(rows,indent=2)+'\n')
print(len(rows),sum(r['bytes'] for r in rows),sum(r['compressed_bytes'] for r in rows))
