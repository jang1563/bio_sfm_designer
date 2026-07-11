# W2b Target-MSA Approval Packet

Status: `awaiting_explicit_target_msa_approval`.

This packet authorizes nothing by itself. Ordinary continuation phrases such as `continue`, `go ahead`,
or `resume` are not approval.

## Scope

- input preparation only: eight target-MSA jobs;
- targets: `1FXK_CA`, `1F93_DC`, `1F66_AB`, `1FJG_FR`, `1FDH_GA`, `1FLT_WV`, `1F51_AE`, `1FVC_DC`;
- manifest SHA-256: `1459d29181ff0d2c1b5fafbf57b4e3f11e1cd872749f17fe951ece96e550ef14`;
- protocol file SHA-256: `2e2b0d8de2d3abe9e120b878893a9dae529a5aa5de6158d989fafa2170b4b7d5`;
- MSA plan SHA-256: `34f44d18ab784a321a948bcf1d0c3c0b4cb0c7e5d5bd3f77d3fa247a20a9ff5d`;
- guarded entrypoint: `hpc/run_w2b_target_msa_guarded.sh`;
- approval variable: `BIO_SFM_APPROVE_W2B_TARGET_MSA`;
- approval token: `approve-w2b-target-msa-precompute`.

Local and Cayuga dry-runs passed. Both runs created no receipt, and the Cayuga Slurm queue remained
unchanged at zero jobs.

## Explicitly Excluded

- ProteinMPNN generation;
- Boltz folding;
- certification or W2b scientific claims;
- changing the target set, hashes, alpha, delta, fit rule, or exact-bound method.

## Approved Command Shape

Only after explicit approval of the exact scope above:

```bash
ssh <hpc-login-host> 'cd <repo-root> && \
  BIO_SFM_PYTHON=<boltz-python> PYTHONNOUSERSITE=1 \
  BIO_SFM_APPROVE_W2B_TARGET_MSA=approve-w2b-target-msa-precompute \
  bash hpc/run_w2b_target_msa_guarded.sh'
```

After completion, sync only the eight `.a3m` files, eight MSA reports, receipt, and receipt summary back
locally. Then rerun strict manifest validation. Fit-stage ProteinMPNN/Boltz remains separately blocked.
