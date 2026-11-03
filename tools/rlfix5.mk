# Linked production schedules: the candidate must be current before these build.
build/rlfix5-scopes: $(BIN) tests/rlfix5_scope.cc tools/rlfix5_proof.py tools/wave13_counts.py tools/rlfix5.mk
	python3 tools/rlfix5_proof.py build --arm post
	touch $@
