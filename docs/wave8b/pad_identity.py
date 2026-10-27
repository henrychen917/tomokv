#!/usr/bin/env python3
"""Strict PRE/PAD inventory followed by the four fence relocation proofs."""
import subprocess,sys
import identity
identity.REFS={'headline':'build/tomokv-wave8b-PRE','execindex':'build/tomokv-wave8b-PRE'}
sys.argv=['identity.py','build/tomokv-wave8b-PAD-A','docs/wave8b/pad-identity']
identity.main()
subprocess.run(['python3','docs/wave8b/pad_provenance.py'],check=True)
