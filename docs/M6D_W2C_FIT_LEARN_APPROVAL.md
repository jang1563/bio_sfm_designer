# W2c Threshold-Learning Approval Packet

Status: `approval_consumed_run_complete_threshold_learning_terminal_not_supported`.

The exact approval was consumed on 2026-07-14. All 16 receipt-bound jobs completed without
retry, 480/480 Boltz records passed strict QC, and the frozen learning rule retained zero
of eight target candidates. W2c is terminal before independent screening. See
`docs/M6D_W2C_THRESHOLD_LEARNING_COMPLETION.md`. This historical packet must not be reused
for resubmission or any later stage.

This packet authorizes nothing by itself. The user's approval in the packet-preparation turn covered
construction and dry-run validation only. It did not approve ProteinMPNN or Boltz record generation.
Ordinary continuation, `go ahead`, `resume`, or goal-mode language is not generation approval.

## Exact Scope

- stage: `threshold_learning` only;
- targets: `1FR2_BA`, `1F80_BC`, `1EZV_XY`, `1FFG_CD`, `1FFK_HR`, `1FQ9_CA`, `1FYR_CD`, and `1F99_BA`;
- ProteinMPNN designs: exactly 60 per target, 480 total;
- Slurm jobs: 8 CPU ProteinMPNN jobs plus 8 dependent H100 Boltz jobs, 16 total;
- namespace: `w2c-fit-learn-v1`;
- candidate IDs: `w2c-fit-learn-v1-<target-id>-<index>`;
- outputs: `hpc_outputs/m6d_w2c_fit_learn_records/<target-id>`;
- Boltz resources: `preempt_gpu/low/gpu:h100:1`;
- scheduler ceiling: 48 H100 GPU-hours from eight 6-hour job limits.

The target-specific ProteinMPNN seeds are deterministically derived from
`sha256("w2c-fit-learn-v1:<target-id>")`. They are frozen in
`configs/m6d_w2c_fit_learn_targets.json`. This stage learns a candidate selective-pAE threshold for
each target. It cannot produce an independent-screen result or certificate.

## Isolation

The source W2c target manifest retains historical W2b output fields and therefore must never be passed
directly to a record-generation bridge. The stage manifest replaces those fields with a dedicated W2c
output root. Its input lock rejects any candidate or record path that collides with the historical W2b
paths. Before initial execution, the guard also requires all 16 W2c candidate/record paths to be absent.

Generated candidates and predictor records are checked for exactly 60 unique IDs, the locked target ID,
and the `threshold_learning` / `w2c-fit-learn-v1` metadata. Historical `w2b_stage` metadata is forbidden.

## Bound Artifacts

- local machine-readable operational packet (intentionally ignored by public checkouts):
  `results/m6d_w2c_fit_learn_approval_packet.json`
  (`d880e85405be102c9706e62ece5a06cb044131364c8f46244503ec5c6412c9a7`);
- stage manifest: `configs/m6d_w2c_fit_learn_targets.json`
  (`c60e1d001f187724bb00a49484158efad0997ca418a0589e5446819fca59daa8`);
- input lock: `configs/m6d_w2c_fit_learn_input_lock.json`
  (`904262663513ad243f3dc5ab8160af0b1fb5965939dd5a815066f285cedf9674`);
- input-lock digest: `8d36af1b46e61d42bdd41532d37845beb06a58a45f87be93e8be97a8fe3bf877`;
- guarded entrypoint: `hpc/run_w2c_fit_learn_guarded.sh`
  (`4c3cd28364564a8387c3c9c6ac101af704e6756ee2d63694ce48fb521834bc1b`).

The local machine-readable packet binds 19 protocol, manifest, completion, validation, generation, prediction,
journal, and guard artifacts. The input lock covers 56 artifacts across eight targets. Raw PDB, FASTA,
and MSA bytes are SHA-256 locked. JSON reports use portable canonical bindings; machine paths and
tool-version-only FASTA report fields are excluded while sequence and content hashes remain fixed.
The submit bridge independently rechecks the fixed stage-manifest and input-lock file hashes and reruns
the input-lock verifier before either dry-run enumeration or any approved scheduler call.

## Dry-Run Evidence

Local and Cayuga dry-runs both passed and enumerated exactly eight ProteinMPNN-to-H100-Boltz pairs.
Neither created a receipt or summary. Cayuga Slurm state remained `0 -> 0`. Strict manifest validation
was 8/8 ready, the historical-overlap audit admitted all eight as fresh, all 16 output paths were absent,
and the current input-lock digest matched on both machines. A non-dry run without the exact approval token
was also refused with exit code 2 locally and on Cayuga.

## Explicitly Excluded

- independent-screen or certification generation;
- reusing any W2b or target-MSA-stage record as a W2c learning row;
- changing target IDs, record counts, seeds, namespace, temperature, signal orientation, or output root;
- automatic retry or resubmission after a partial receipt without a separate recovery audit;
- claiming W2c viability, certification, W2 generalization, or publication readiness.

## Consumed Approval

The explicit approval naming **W2c threshold-learning 480-record generation on H100** authorized only the
following guarded command shape and has now been consumed:

```bash
ssh <hpc-login-host> 'cd <repo-root> && \
  BIO_SFM_PYTHON=/opt/ohpc/pub/software/python/3.13.7/bin/python3 \
  PYTHONNOUSERSITE=1 \
  BIO_SFM_APPROVE_W2C_FIT_LEARN=approve-w2c-fit-learn-480-h100 \
  bash hpc/run_w2c_fit_learn_guarded.sh'
```

The approved generation, sync, strict QC, and learning-only evaluation are complete. Because all eight
targets froze to `refuse`, no independent-screen packet is scientifically reachable under the locked
protocol. Independent-screen and certification generation remain unapproved and unsubmitted.
