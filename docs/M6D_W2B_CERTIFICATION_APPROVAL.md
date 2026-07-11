# W2b Certification-Stage Approval Packet

Status: `awaiting_explicit_certification_execution_approval`.

The earlier message approving the next task authorized preparation and validation of this packet only. It
could not authorize execution before these exact artifacts and hashes existed. This packet grants no
authority by itself and does not authorize test-stage compute. Certification jobs require a new explicit
approval of the exact scope below.

## Exact Scope

- stage: `certification` only;
- targets: `1F51_AE`, `1F93_DC`, `1FDH_GA`, `1FLT_WV`, `1FVC_DC`;
- ProteinMPNN designs: 60 per target, 300 total;
- Slurm jobs: 5 CPU ProteinMPNN jobs plus 5 dependent H100 Boltz jobs, 10 total;
- ProteinMPNN seed: `1037`;
- record namespace: `w2b-cert-v1`;
- candidate ID prefix: `w2b-cert-v1-<target-id>`;
- Boltz resources: Cayuga `preempt_gpu`, QOS `low`, `gpu:h100:1`;
- scheduler upper bound: 30 H100 GPU-hours from five 6-hour Boltz limits, plus five 45-minute CPU limits.

The frozen target rules are:

| target | mode | tau |
|---|---|---:|
| `1F51_AE` | `selective_pae` | 5.7365 |
| `1F93_DC` | `trust_all` | - |
| `1FDH_GA` | `trust_all` | - |
| `1FLT_WV` | `trust_all` | - |
| `1FVC_DC` | `trust_all` | - |

Certification uses the predeclared one-sided exact Clopper-Pearson bound at target alpha 0.2 and
per-target delta 0.0125. The Bonferroni denominator remains all eight initial targets. Each target needs at
least 22 accepted certification rows and an exact upper bound no greater than 0.2.

## Bound Artifacts

- scientific protocol digest: `19bad978cdbccfeb5cfe3ec0f7c7455bb8d2f7e10697091c15ec6b40c7341b0b`;
- protocol file SHA-256: `dcef5d1b080791b54bafb485f815e08b536bcd68a44ee4ab458b34ebb3d5567c`;
- certification manifest SHA-256: `502b2d91e29c9f9c1199e79b075051c83b0a634277283a6c97ee4b6d83ae8d99`;
- certification input-lock file SHA-256: `41279f144bcbe09fe61aedd838e413900200a814b73f64b2616a64430fdcdd23`;
- certification input-lock digest: `2153bf715745813730e2f41b340329adb21dc7415f293980cf8519320b5deaae`;
- frozen fit report SHA-256: `6aac81be46805ad983e770af49f15e38cac140d469e4541e40788a21129ef3c1`;
- CPU-replay fit fixture SHA-256: `3187ba56a3eb39e4820d17c42e6a8ffd8ce28add05d858645a1e92427c6d4dbe`;
- guarded entrypoint SHA-256: `d03eba2e60105fd4401d5dcd65aaf001d6e30eb2e9870b2e073a8c7a9a8a7fdf`;
- stage input-lock tool SHA-256: `ea5f2e6fe3a62c32a3436e3e43e6649a88a3d201364ce9e642edac092a195631`;
- shared submit bridge SHA-256: `61fb4b92d935e5708c35f3d90380b06ed0a8c6b4f7cfc5affb137d16b4332a92`;
- ProteinMPNN wrapper SHA-256: `6b010e2cd45a2c148161e7dffe021165af199f9e64d21be06b2c1b706e7b0aa6`;
- Boltz wrapper SHA-256: `254e7c985fdd92d388261f8af01a319344a428a16e5bb0ecfbbc1c5bc2ca53d9`;
- ProteinMPNN generator SHA-256: `0245801d7a72f927352de3a447640c531e9364d0aa398718a7cea84fd8cfe4db`;
- Boltz predictor SHA-256: `9203d5acea2b4a9b27747eb1d7be3e218c076c549d5b8228b85d535201de71c8`;
- manifest validator SHA-256: `1acd87200bf745ca670eac69b2f27959a7d51fbdf1397daeeea2b6936e4af9e0`;
- historical-overlap audit SHA-256: `82bb6f1cd179de665b5f8aa94b7818a703b8fcf8788a202c26d71c574617fc87`;
- submit journal SHA-256: `6f3c7fe5ca455e58f44375c220b96df06616cad5fe06496dddbc983b92d3d9f8`.

The input lock covers 35 artifacts across five targets and binds the five frozen fit rules plus the fit
manifest, report, and replay-fixture hashes. Scientific PDB, FASTA, and MSA inputs use raw-byte SHA-256;
JSON reports use portable canonical semantic hashes.

## Guard

- entrypoint: `hpc/run_w2b_certification_guarded.sh`;
- approval variable: `BIO_SFM_APPROVE_W2B_CERTIFICATION`;
- approval token: `approve-w2b-certification-stage-300-h100`;
- receipt: `results/m6d_w2b_target_adaptive_certification_submit_receipt.jsonl`;
- summary: `results/m6d_w2b_target_adaptive_certification_submit_receipt_summary.json`.

The guard checks every bound SHA, verifies the input-lock digest from current files, cross-checks target IDs
and frozen rules against the fit report, rejects pre-existing certification outputs or receipts, and applies
the H100 resource override only to Boltz jobs.

## Dry-Run Evidence

Local and Cayuga dry-runs passed and each enumerated exactly five ProteinMPNN-to-Boltz pairs with
`preempt_gpu/low/gpu:h100:1`. Neither made an `sbatch` call or created a receipt, summary, or output file.
The Cayuga Slurm queue remained unchanged at `0 -> 0`.

## Explicitly Excluded

- test-stage generation or folding;
- changing targets, alpha, delta, frozen mode, tau, seed, namespace, or record count;
- replacing the all-eight-target multiplicity denominator with only eligible targets;
- reusing any fit sequence or candidate ID in certification;
- claiming certification from submission, job completion, or fit-stage performance;
- automatic retry or resubmission after a partial receipt without a separate recovery audit.

## Approved Command Shape

Only after explicit approval of the exact packet above:

```bash
ssh <hpc-login-host> 'cd <repo-root> && \
  BIO_SFM_PYTHON=<boltz-python> PYTHONNOUSERSITE=1 \
  BIO_SFM_APPROVE_W2B_CERTIFICATION=approve-w2b-certification-stage-300-h100 \
  bash hpc/run_w2b_certification_guarded.sh'
```

## Required Stop After Certification

After all 10 jobs complete, sync and validate exactly 60 fresh records per target. Run the locked evaluator
with the committed fit fixture plus certification records. Stop after exact certification and panel-status
reporting. Do not generate test rows until a separate test-stage packet is reviewed and explicitly approved.
