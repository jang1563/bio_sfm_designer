# W2b Target-MSA Completion

Status: `target_msa_input_prep_complete`.

This is input-preparation provenance only. It is not W2b scientific evidence and does not authorize
ProteinMPNN generation, Boltz panel folding, fitting, certification, or a scientific claim.

## Final Validation

- manifest: `configs/m6d_w2b_target_adaptive_fit_targets.json`;
- manifest SHA-256: `1459d29181ff0d2c1b5fafbf57b4e3f11e1cd872749f17fe951ece96e550ef14`;
- targets ready: 8/8;
- strict local and Cayuga result: `ok=true`, zero failures;
- final validation artifact: `results/m6d_w2b_target_adaptive_fit_manifest_require_files.json` (ignored raw result);
- regression suite after the integrity repair: 848 passed.

## Execution History

The guarded submission created exactly the eight approved initial jobs, `3079693` through `3079700`.
Six completed on the first attempt. `1F51_AE` and `1FVC_DC` failed with transient ColabFold API connect
timeouts. Slurm requeue was disabled, so the same two targets were retried serially as `3079701` and
`3079702`; both completed.

The first sync-back then failed strict local validation for `1F93_DC`. Its source PDB contains two target-chain
MSE residues as `HETATM` records. `prep_hetdimer.py` counted supported modified residues during validation
but emitted only `ATOM` records, so the prepared target silently lost those residues. The Cayuga MSA query
was therefore 98 aa while the locked local target FASTA was 100 aa. The 98-aa MSA was invalidated and
quarantined, not accepted as evidence.

The repair normalizes supported modified amino acids to standard ProteinMPNN-compatible `ATOM` records and
standard residue names in both heterodimer preparation and the defensive ProteinMPNN chain-strip path.
Regression tests cover preservation of MSE. The corrected `1F93_DC` prepared PDB and FASTA are 100 aa, and
correction job `3079703` generated the matching MSA. Final strict validation passes 8/8 locally and on Cayuga.

Raw submission and recovery provenance is retained in ignored artifacts:

- `results/m6d_w2b_target_adaptive_fit_target_msa_receipt.jsonl`;
- `results/m6d_w2b_target_adaptive_fit_target_msa_receipt_summary.json`;
- `results/m6d_w2b_target_adaptive_fit_target_msa_recovery_receipt.jsonl`;
- `results/m6d_w2b_target_adaptive_fit_target_msa_recovery_summary.json`.

## Boundary

The next scientific stage requires a new, explicit approval boundary. Do not interpret completed target-MSA
input preparation as permission to run ProteinMPNN or Boltz, and do not report a fitted threshold or W2b
certificate until the predeclared fit/certification/test workflow has actually completed.
