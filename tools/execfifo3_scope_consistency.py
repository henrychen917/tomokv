#!/usr/bin/env python3
"""Compare saved scopes, including calls outside the counted production bodies."""
from collections import Counter
import json
from pathlib import Path
import re

ROOT=Path(__file__).resolve().parents[1]
DOCS=ROOT/'docs/execfifo3'
PROBE_SUFFIX=re.compile(r' in section \.text of '+re.escape(str(ROOT))+r'/build/execfifo3/'
                        r'(commands|memory)-scopes/(PRE|POST-final)-(normal|db0)/probe$')

def callees(record):
    result=Counter()
    for name,count in record['excluded'].items():
        # GDB appends the containing image to fixture callback names. Remove
        # only our known probe filename; preserve the full symbol and count.
        result[PROBE_SUFFIX.sub('',name)]+=count
    return result

def main():
    rows=[]
    for family in ('commands','memory'):
        for path in sorted((DOCS/family).glob('POST-final-*.json')):
            if path.name.endswith('-build.json'):continue
            pre=path.with_name(path.name.replace('POST-final-','PRE-',1))
            if not pre.exists():continue
            a=json.loads(pre.read_text());b=json.loads(path.read_text())
            if not isinstance(a,dict) or 'functions' not in a:continue
            row=dict(family=family,pre=str(pre.relative_to(ROOT)),post=str(path.relative_to(ROOT)),
                     total_equal=a['total']==b['total'],per_function_equal=a['functions']==b['functions'],
                     raw_excluded_labels_equal=a['excluded']==b['excluded'],
                     excluded_call_counts_equal=callees(a)==callees(b),clock_calls_equal=a['clock_calls']==b['clock_calls'])
            checks=['total_equal','per_function_equal','excluded_call_counts_equal','clock_calls_equal']
            if family=='memory':
                row.update(classified_accesses_equal=a['memory']==b['memory'],
                           unclassified_accesses_equal=a['unknown_memory']==b['unknown_memory'],
                           stack_line_delta=b['stack_cache_lines']-a['stack_cache_lines'])
                checks+=['classified_accesses_equal','unclassified_accesses_equal']
            row['passed']=all(row[key] for key in checks) and row.get('stack_line_delta',0)<=0
            rows.append(row)
    counts={family:sum(row['family']==family for row in rows) for family in ('commands','memory')}
    summary=dict(counts=counts,rows=rows,passed=counts==dict(commands=48,memory=36) and all(row['passed'] for row in rows),
                 label_note='Eight MSET callback labels differ only in the PRE/POST probe pathname. '
                 'Raw equality is recorded separately; full callee symbols and call counts must agree.')
    (DOCS/'scope-consistency.json').write_text(json.dumps(summary,indent=2)+'\n')
    print(counts,'passed',summary['passed']);assert summary['passed']

if __name__=='__main__':main()
