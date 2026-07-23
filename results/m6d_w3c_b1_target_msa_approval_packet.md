# M6d W3c-B1 target-MSA approval packet

Status: `w3c_b1_packet_prepared_cayuga_no_submit_validation_required`.
Approval packet ready: `True`.
No submit: `True`.

## Scope

- targets: `8`
- target-MSA queries authorized now: `0`
- target-MSA queries after exact approval: `8`
- maximum A40 GPU-hours: `8.0`
- ProteinMPNN allowed: `False`
- structure predictors allowed: `False`
- Cayuga no-submit validation: `not_run`
- ready to request exact approval: `False`

## Exact approval

Required user phrase: `approve W3c-B1 target-MSA precompute`

Command only after that exact approval:

```bash
BIO_SFM_APPROVE_W3C_B1_TARGET_MSA=approve-w3c-b1-target-msa-precompute bash hpc/run_w3c_b1_target_msa_guarded.sh
```

## Claim boundary

This no-submit packet can authorize exactly eight target-MSA input-prep queries only after the exact approval phrase. It never authorizes ProteinMPNN, either structure predictor, W3c-B2 preparation, or any scientific claim.
