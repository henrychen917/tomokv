import sys,pathlib,json
sys.path.insert(0,'tests')
source=pathlib.Path('tests/atomic_torn.py').read_text()
source=source[:source.index('geometry = gate_geometry()')]
# Keep the detector unchanged, but retain the actual replies/images on failure.
old='''                anomalies += 1
                continue
            if command == "RENAMENX":'''
new='''                print("NX failure", iteration, replies, values, flush=True)
                anomalies += 1
                continue
            if command == "RENAMENX":'''
assert source.count(old)==1
source=source.replace(old,new)
old='''                anomalies += values[:2] != expected_sources'''
new='''                if values[:2] != expected_sources:
                    print("NX source failure", iteration, replies, values, expected_sources, flush=True)
                anomalies += values[:2] != expected_sources'''
assert source.count(old)==1
source=source.replace(old,new)
context={'__name__':'txnfix_conditional_probe'}
exec(compile(source,'tests/atomic_torn.py','exec'),context)
g=context['gate_geometry']()
results=[]
for attempt in range(16):
 result=context['conditional_races']('at:txnfix-probe',1,'RENAMENX',g['conditional_sources'],g['conditional_destination'],rounds=256)
 results.append(result);print(attempt,repr(result),flush=True)
 if result[0] or result[1] or result[2]:break
pathlib.Path(sys.argv[3] if len(sys.argv)>3 else 'build/txnfix/conditional.json').write_text(json.dumps(results,indent=2)+'\n')
sys.exit(any(result[0] or result[1] or result[2] for result in results))
