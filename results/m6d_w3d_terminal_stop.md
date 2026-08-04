# M6d W3d Terminal Stop

Status: `w3d_terminal_partial_result_native_validity_impossibility_stop`.
Audit ok: `True`.
Stage pass: `False`.
Strict-QC prospective records: `16/24`.
Observed H100 GPU-hours: `1.723889`.

## Decision

The frozen native-validity pass is mathematically impossible: target-MSA has 2/8 Boltz and 2/8 AF2 successes, while query-only has 1/8 Boltz successes. Each representation therefore has a fully observed predictor below the required 6/8, regardless of the missing query-only AF2 outcomes.

The full representation-by-predictor localization is not evaluable. All eight query-only AF2 jobs failed before model inference because the A3M encoding omitted runtime-required unpaired monomer query rows. This is an implementation failure, not a scientific negative.

The frozen native-validity pass is impossible because at least one fully observed predictor is below 6/8 under each representation. The missing query-only AF2 cell prevents complete-matrix bottleneck localization and is an input-encoding failure, not a scientific negative.

Next action: Close W3d without retry. Any corrected query-only AF2 encoding must be a separately preregistered successor; generator and gate work remain blocked.
