The four PRE negative controls originally inherited the driver's global POST
hash in their metadata. Their server commands correctly name the immutable
PRE binary. The manifest now records its verified digest and preserves the
original incorrect digest alongside the correction. No command, test result,
or assertion changed. The release driver hashes the actual server binary.
