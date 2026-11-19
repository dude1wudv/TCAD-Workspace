# F6 synthetic archive fixture contract

These fixtures test archive parsing and frozen numerical gates only. They are not
TCAD calculations, original measurements, native receipts, execution authority,
released research inputs, or physical evidence. No tool is launched.

Decisions recorded before implementation:

- `build_fixture(root, bit=0, case="Aalpha")` requires a new directory whose own
  name contains `UNIT_FIXTURE_NOT_NATIVE`, and refuses any `runs` ancestor. The
  solver, extraction, and package directories share this root. Its
  `fixture-manifest.json` is the isolation marker required by `audit_fixture`.
- Solver and operation manifests, synthetic execution release, authorization,
  geometry report, and fixture inventory all have `origin="synthetic_fixture"`
  and `synthetic=true`. Their numeric zero exits and RELEASED status exist only
  to exercise the parser. They cannot authorize a real operation.
- Frozen mathematical source/reference/profile/windows materials are copied
  unchanged from the offline alpha generator, as agreed with the main agent,
  so strict independent-reference reproduction remains meaningful. The enclosing
  package and root identify them as unit-test inputs. New text logs and binary
  substitutes visibly say `SYNTHETIC_NOT_NATIVE`; strict-format CSV/exit files are
  identified by the enclosing synthetic manifests rather than extra invalid rows.
- The deterministic time array has 83 points: initial time zero, the source-window
  left boundary, 80 source-window endpoints, and 25 ns. There are 82 BE intervals,
  81 saved source-window files including its diagnostic initial boundary, and no
  inferred filenames-to-time mapping. This is deliberately a parser fixture,
  not a valid full-operation timestep-convergence run.
- Native TDR and mesh payloads are explicit `SYNTHETIC_NOT_NATIVE` byte strings.
  SHA256, lengths, archive membership, four reference-check phases, and cleanup
  records are internally consistent. Fake inode/mode values are test tokens,
  never filesystem observations.
- G and its moments are computed from the frozen analytical reference. A0 omits
  G to exercise structural-zero semantics; Z retains measured-format zero values.
  Both stored bits are supported, but no electrical or KCL behavior is generated.
- Every requested output file is new. No old S2 code, frozen package, original
  archive, budget, native receipt, or real run directory is modified. Public
  `audit_native` must reject this fixture; only `audit_fixture` may exercise its
  complete parse path, always with `native_qualified=false`.

The release binds the current `evidence.py` and `audit.py` SHA256 at fixture build
time (E009), and binds the producer hashes recorded in the synthetic solver and
operation manifests. Those hashes identify parser inputs; they do not assert
that the named producer code was executed.

E010 fixture decisions, recorded before updating the builder:

- Both synthetic tool records include exactly one `Name`, `Pid`, `PPid`,
  `Threads`, and `Cpus_allowed_list` in their raw status bytes. Each observation
  binds those exact bytes by SHA256 and the exact status filename.
- The synthetic parent chain has a wrapper PID 123, one launch child, and one
  distinct native-tool PID. Solver uses child/native PIDs 124/125; extractor uses
  224/225. Start ticks are positive test constants, and all parent links, terminal
  name/PID/start ticks, and raw status PID/PPid are consistent. These tokens are
  never read from a real process.
- The installation root is the absolute POSIX test path
  `/UNIT_FIXTURE_NOT_NATIVE/installation/W-2024.09`; the synthetic executable is
  its `bin/sdevice` or `bin/svisual` child with an exact tool basename. No file at
  that path is opened or executed.
- Observation JSON uses `native-process-observation-r1`, `status=OBSERVED`, and
  explicit synthetic provenance. The solver additionally includes a separate
  `native-process-admission-r1` JSON with `status=PASSED`, empty errors, requested
  CPU `"0"`, and a separate numeric-zero admission exit file. SVisual has no
  admission record. A tool exit never substitutes for the admission exit.
- This E010 update is limited to fixture construction and these notes. No audit
  or archive build is run while the main agent updates the core interface;
  integration verification is deferred to the main agent's validation worker.

Pre-E010 offline implementation checks on 2026-10-16 used `python -B -` with direct calls
to `build_fixture`, `audit_fixture`, and `audit_native`. Both commands exited 0.
The complete parse path passed for Aalpha bit0/bit1, A0 bit1, Z bit0, split bit1,
and H bit0. Every public native call refused synthetic provenance and every
result retained `native_qualified=false`. Four isolation guards rejected an
unmarked root, a `runs` ancestor, an existing root, and bool-as-bit input. No
native receipt filenames were created. Reports are under
`local_runtime/dram-see-v4/s2-evidence-r1/20261016T123650Z/fixtures/`:
`fixture-build-check-r1.json` and `fixture-branch-check-r1.json`.

After the main agent stopped core-interface writes and explicitly allowed one
focused E010 check, a new Aalpha bit0 fixture was built. `python -B -` exited 0:
the complete private parser path passed, the public native path refused its
synthetic origin, and both kept `native_qualified=false`. The report is
`fixtures/fixture-e010-check-r1.json` under the same runtime directory. The six
earlier branches were not repeated; independent worker verification remains
the next integration step.

These tests only demonstrate the synthetic archive parser path. The real native
capture patch, native archive path, solver, SVisual, physical geometry, and
electrical response remain unexecuted and unverified.
