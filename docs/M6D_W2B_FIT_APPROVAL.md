# W2b Fit-Stage Approval Packet

Status: `awaiting_explicit_fit_stage_approval`.

This packet authorizes nothing by itself. Ordinary continuation phrases such as `continue`, `go ahead`,
or `resume` are not approval. The completed target-MSA approval does not extend to this stage.

## Exact Scope

- stage: `fit` only;
- targets: `1FXK_CA`, `1F93_DC`, `1F66_AB`, `1FJG_FR`, `1FDH_GA`, `1FLT_WV`, `1F51_AE`, `1FVC_DC`;
- ProteinMPNN designs: 60 per target, 480 total;
- Slurm jobs: 8 CPU ProteinMPNN jobs plus 8 dependent A40 Boltz jobs, 16 total;
- ProteinMPNN seed: `37`;
- record namespace: `w2b-fit-v1`;
- candidate ID prefix: `w2b-fit-v1-<target-id>`;
- scheduler upper bound: 48 A40 GPU-hours from eight 6-hour Boltz limits, plus eight 45-minute CPU limits.

The fit stage chooses a frozen mode and optional pAE threshold independently for each target. It cannot
produce a certificate. Certification and test stages require new manifests, disjoint namespaces and seeds,
fit-eligible target selection, fresh input locks, and separate explicit approval.

## Bound Artifacts

- scientific protocol digest: `19bad978cdbccfeb5cfe3ec0f7c7455bb8d2f7e10697091c15ec6b40c7341b0b`;
- protocol file SHA-256: `def9cfa9989e91c83923d798b9ae1db07dd7e0cd9aea73424513e33c32a60ed5`;
- fit manifest SHA-256: `1459d29181ff0d2c1b5fafbf57b4e3f11e1cd872749f17fe951ece96e550ef14`;
- fit input-lock file SHA-256: `938003752b3ab8fb62dcd5114678738b0373ec399dafb64fab9c6fe389d94ec4`;
- fit input-lock digest: `a97423644fef1ddbbb88471a759e42ea21c9097bcf6aa314e4f608e11773064b`;
- guarded entrypoint SHA-256: `980aac2a6cd20ead41fadd873858a06f7c51c3090acefb09988a3efa0a0dd7d9`;
- shared submit bridge SHA-256: `3c5a0bd4e0e34a460e2c110b12628456ba65bc2aa252017a1f2147b3b5249d04`;
- ProteinMPNN wrapper SHA-256: `6b010e2cd45a2c148161e7dffe021165af199f9e64d21be06b2c1b706e7b0aa6`;
- Boltz wrapper SHA-256: `254e7c985fdd92d388261f8af01a319344a428a16e5bb0ecfbbc1c5bc2ca53d9`;
- ProteinMPNN generator SHA-256: `0245801d7a72f927352de3a447640c531e9364d0aa398718a7cea84fd8cfe4db`;
- Boltz predictor SHA-256: `9203d5acea2b4a9b27747eb1d7be3e218c076c549d5b8228b85d535201de71c8`;
- manifest validator SHA-256: `1acd87200bf745ca670eac69b2f27959a7d51fbdf1397daeeea2b6936e4af9e0`;
- historical-overlap audit SHA-256: `82bb6f1cd179de665b5f8aa94b7818a703b8fcf8788a202c26d71c574617fc87`;
- submit journal SHA-256: `6f3c7fe5ca455e58f44375c220b96df06616cad5fe06496dddbc983b92d3d9f8`;
- audited command plan SHA-256: `bda9fec6d2a097903b8a3b34b0e78c22e5e4caef0193250d5f9fcc34cec63332`.

The input lock covers 56 artifacts across eight targets. PDB, FASTA, and MSA scientific inputs use raw-byte
SHA-256. JSON reports use `canonical_report_json_v1`, which preserves scientific fields and content hashes
while excluding machine-specific absolute paths, work directories, source-cache paths, and commands.

## Guard

- entrypoint: `hpc/run_w2b_fit_guarded.sh`;
- approval variable: `BIO_SFM_APPROVE_W2B_FIT`;
- approval token: `approve-w2b-fit-stage-480`;
- receipt: `results/m6d_w2b_target_adaptive_fit_submit_receipt.jsonl`;
- summary: `results/m6d_w2b_target_adaptive_fit_submit_receipt_summary.json`.

The guard checks every bound SHA, verifies the input-lock digest against current local files, reruns strict
manifest and historical-overlap checks, and refuses an initial run when the receipt path already exists.

## Dry-Run Evidence

Local and Cayuga dry-runs both passed. Each enumerated exactly eight ProteinMPNN-to-Boltz pairs. Neither
created a receipt or summary. The Cayuga Slurm queue remained unchanged at `0 -> 0`. No fit job has been
submitted.

## Explicitly Excluded

- certification-stage or test-stage generation and folding;
- changing targets, alpha, delta, mode order, signal orientation, seed, namespace, or record count;
- using fit labels to change this protocol or input lock;
- claiming certification, target-adaptive viability, universal W2 generalization, or publication readiness;
- automatic retry or resubmission after a partial receipt without a separate recovery audit.

## Approved Command Shape

Only after explicit approval of the exact scope above:

```bash
ssh <hpc-login-host> 'cd <repo-root> && \
  BIO_SFM_PYTHON=<boltz-python> PYTHONNOUSERSITE=1 \
  BIO_SFM_APPROVE_W2B_FIT=approve-w2b-fit-stage-480 \
  bash hpc/run_w2b_fit_guarded.sh'
```

## Required Stop After Fit

After all 16 jobs complete, sync the eight candidate and eight record files, verify 60 records per target,
run complex-record QC, and run `m6d_w2b_target_adaptive_report` with fit records only. Stop after the report
classifies targets as `trust_all`, `selective_pae`, or `refuse`. Do not generate certification or test rows
until a new scope-bound approval packet is reviewed and explicitly approved.
