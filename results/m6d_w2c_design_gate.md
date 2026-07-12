# M6d W2c Design Gate

Status: `w2c_design_power_qualified_no_submit`.
Audit ok: `True`.
Execution ready: `False`.
Cayuga submission allowed: `False`.

## Scientific Design

- initial fresh targets: `8`
- evaluator implemented: `True`
- target manifest present: `True`
- target manifest integrity ok: `True`
- target MSAs ready: `False`
- eligible gate mode: `selective_pae_only`
- threshold-learning rows per target: `60`
- independent fit-screen rows per target: `120`
- fit-screen minimum accepts: `75`
- fit-screen risk UCB at the minimum: `0.136196`
- fit-screen risk UCB cap: `0.15`

## Exact Certification Power

- target alpha: `0.2`
- per-target delta: `0.0125`
- generated rows per eligible target: `180`
- minimum accepted rows: `90`
- design true risk: `0.08`
- maximum certifiable false accepts: `9`
- conditional certification power: `0.817860`
- required power: `0.8`

## Claim Boundary

This is a planning and power artifact only. It does not reuse W2b rows, select W2c targets, authorize compute, certify a gate, or support W2/W2c generalization.

## Next Action

Implement the locked W2c evaluator and build an eight-target fresh manifest with complete historical/sequence/source exclusion before any execution packet or approval request.
