#!/usr/bin/env python3
"""Observe failed reports in the unchanged serverless null-control test."""
import argparse,json,sys,unittest
from pathlib import Path
ROOT=Path(__file__).resolve().parents[2];sys.path.insert(0,str(ROOT/'tests'))
import abbagate
p=argparse.ArgumentParser();p.add_argument('output',type=Path);a=p.parse_args();a.output.mkdir(parents=True,exist_ok=False)
loads=json.loads;loadcase=unittest.TestLoader.loadTestsFromTestCase;reports=[]
def observe(*args,**kw):
 result=loads(*args,**kw)
 if isinstance(result,dict) and result.get('verdict')=='FAIL' and 'reason' in result:
  reports.append(result);(a.output/'failed-reports.json').write_text(json.dumps(reports,indent=2)+'\n')
 return result
def selected(self,case):
 return unittest.TestSuite(t for t in loadcase(self,case) if t._testMethodName=='test_real_null_collection_comparison_and_subset_controls')
json.loads=observe;unittest.TestLoader.loadTestsFromTestCase=selected
raise SystemExit(abbagate.self_test())
