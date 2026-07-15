# M6d W3b Target-MSA Lifecycle

Status: `target_msa_precompute_complete_8_of_8`.
Audit ok: `True`.
Completion ok: `True`.
No submit: `True`.
Explicit approval still required: `False`.

Target-MSA lifecycle provenance only. This tool never submits work and cannot authorize candidate generation, candidate-level prediction, a gate certificate, or a W3b claim. The reconciliation changes no raw accounting, scientific input, threshold, role, or compute scope.

- targets: `8`
- submitted jobs: `8`
- jobs terminal success: `True`
- A40 GPU-hours: `0.216389` / `8.0`
- failures: `0`

Next action: rerun the design audit into post-MSA outputs, then stop for a separate candidate-generation approval packet.

## Allocation Telemetry Reconciliation

- status: `allocation_telemetry_reconciled`
- audit ok: `True`
- raw sacct SHA-256: `f5bf4643dd172b64edb12c502e18a5445ead87b72cab65ae0ae9efcd27b62bda`
- submit-time scontrol SHA-256: `5813c291e35d4bf615e57a461268c977d752d67e0b122add9d741a3121988231`
- node inventory SHA-256: `6ac91e1ff757417767a670404d5f7d7006881db75199f424017f5ce6f0529fdb`
- normalized primary jobs: `8`

Raw Slurm accounting remains unchanged; only the omitted A40 subtype is restored in memory after independent proof.
