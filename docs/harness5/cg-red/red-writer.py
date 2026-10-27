"""Red check for the product-record control: base run_gate (no product.json) + the new tests."""
import re, subprocess, sys
from pathlib import Path
new = Path('/home/user/Projects/cx-harness5/tests/gateprod.py').read_text()
base = subprocess.run(['git', '-C', '/home/user/Projects/cx-harness5', 'show', '3700b51d7:tests/gateprod.py'],
                      capture_output=True, text=True, check=True).stdout
def block(text):
    start = text.index('def run_gate(argv):')
    end = text.index('\ndef ', start + 1)
    return start, end
bs, be = block(base); ns, ne = block(new)
red = new[:ns] + base[bs:be] + new[ne:]
assert 'product.json' not in red[red.index('def run_gate'):red.index('def self_test')]
Path(sys.argv[1]).write_text(red)
print('base run_gate spliced into', sys.argv[1])
