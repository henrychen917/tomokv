#!/usr/bin/env python3
"""Reuse wave14's serverless instruction instrument with eoffix source arms."""
from pathlib import Path
import wave14_counts as counts

ROOT = Path(__file__).resolve().parents[1]
counts.BUILD = ROOT/'build/eoffix'
counts.DOC = ROOT/'docs/eoffix'
counts.PRE = ROOT/'build/eoffix/pre-source'
counts.census.BUILD = counts.BUILD/'counts'
counts.census.DOC = counts.DOC/'instructions'

if __name__ == '__main__':
    counts.main()
