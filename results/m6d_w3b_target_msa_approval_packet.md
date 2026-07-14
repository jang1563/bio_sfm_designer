# M6d W3b Target-MSA Approval Packet

Status: `awaiting_explicit_w3b_target_msa_approval`.
Approval packet ready: `True`.

Approval covers exactly eight target-MSA input-prep jobs, capped at 8 A40 GPU-hours. It does not authorize candidate generation, candidate-level Boltz/AF2 prediction, or a W3b claim.

- targets: `8`
- maximum A40 GPU-hours: `8.0`
- candidate generation or candidate-level prediction allowed: `False`

Command only after explicit approval:

```bash
BIO_SFM_APPROVE_W3B_TARGET_MSA=approve-w3b-target-msa-precompute bash hpc/run_w3b_target_msa_guarded.sh
```
