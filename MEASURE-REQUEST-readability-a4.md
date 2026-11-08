## readability-a4

Branch `cx-readability-a4`, lane baseline `9a09e59190`. Production reference:
`/home/user/Projects/bins/readability-pre-5c363128/tomokv` (maintainer-supplied;
never rebuilt). No push, throughput measurement or new PAD arm is requested.

The boot documentation batch describes ownership, stop-aware rendezvous,
publication and worker lifetime ordering. It adds boot-sequence landmarks and
moves historical rationale into
[the decision log](docs/decisions/readability-a4.md). Source changes are confined
to the assigned files; the formatter regenerates the protected R7 envelope from
its handwritten inputs. No protected block is edited by hand.

Validation and final counts will be recorded after the reorder/shutdown batch
and the required selected gate jobs. No gate row or expected count is changed.
