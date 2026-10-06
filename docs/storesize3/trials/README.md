These are rejected/intermediate compiler-boundary experiments, not production
arms. The final implementation and flags are in `MEASURE-REQUEST-storesize3.md`.
Patches preserve the scratch source variants against the lane's starting
sources; logs preserve the body audit outcomes and tested thresholds. They
must not be applied wholesale to the current branch.

The `.patch` files are literal unified diffs. Their blank context lines contain
the required single-space prefix. Git's outer `diff --check` reports that
prefix as trailing whitespace when a patch is added as a document. Check
production code and other receipts with:

```sh
git diff --cached --check -- . ':!docs/storesize3/trials/*.patch'
```

No body-audit rule or comparison is relaxed by that text-artifact exclusion.
