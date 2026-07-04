# M6d Candidate Target Panel

This is the current W2 candidate panel for testing whether the complex/binder
`pAE_interaction` trust signal survives beyond barnase-barstar. The initial
panel has now completed as a negative generalization check, not as a missing
MSA or sync problem.

Current status:

- `results/m6c_panel_report.json`: `multi_target_evaluable_not_certified`
- `results/m6c_w2_redesign_diagnostic.json`: recommends
  `redesign_or_replace_low_success_targets`
- `results/m6d_candidate_targets_manifest.json`: current manifest validates
  with 3/3 prepared targets and 0 manifest failures
- `results/m6d_redesign_panel_report.json`: replacement panel completed with
  4/4 targets and 400 records, but remains
  `multi_target_evaluable_not_certified` at alpha=0.2
- `results/m6d_redesign_panel_diagnostic.json`: replacement-panel diagnostic
  says drop/replace `1SYX_AB`, retain/retest `1BRS_AD`, `3PC8_AB`, and
  `1S1Q_CD`, and do not make a multi-target claim yet
- `results/m6d_followup_panel_report.json`: follow-up panel reusing
  `1BRS_AD`/`3PC8_AB` and adding `1MEL_MB`, `1GCQ_CB`, and `2IDO_CD`
  completed with 5/5 targets and 500 records, but remains
  `multi_target_evaluable_not_certified` at alpha=0.2
- `results/m6d_followup_next_science_actions.{json,md}`: current resume
  anchor; `3PC8_AB` is now alpha=0.2 certified after target-specific mini-scale,
  but this is target-specific rather than W2 generalization

Do not submit another identical W2 panel before replacing the low-success targets
or redesigning the generation/evaluation protocol for them.

## Candidate Manifest

Use:

```sh
python -m bio_sfm_designer.experiments.complex_target_manifest \
  --manifest configs/m6d_candidate_complex_targets.json \
  --require-files --min-targets 3 \
  --out results/m6d_candidate_targets_manifest.json \
  --emit-plan results/m6d_candidate_targets_submit.sh \
  --emit-msa-plan results/m6d_candidate_target_msas.sh
```

Current `--require-files` status passes for the existing three targets. The
emitted submit plan is useful as provenance for how the completed panel was made,
but it is not the next scientific action after the negative panel result.

## Prep Evidence

| target | source | chains | target CA | binder CA | CA contacts | numbering gaps | status |
|---|---|---:|---:|---:|---:|---|---|
| `1BRS_AD` | `1BRS` | A/D | 108 | 87 | 36 | binder D64-D65 reviewed exception | 60/100 successes; `underpowered_or_split_sensitive` |
| `2SIC_EI` | `2SIC` | E/I | 275 | 107 | 65 | none | 4/100 successes; `target_protocol_mismatch_low_success` |
| `1CGI_EI` | `1CGI` | E/I | 245 | 56 | 64 | none | 7/100 successes; `target_protocol_mismatch_low_success` |

The local prep artifacts are under `hpc_outputs/targets/`:

- `source_*.pdb`
- `prepared_*.pdb`
- `prepared_*.report.json`
- target-chain FASTA and FASTA report files

## Replacement Panel Result

The M6d replacement panel used `configs/m6d_redesign_complex_targets.json` with
`1BRS_AD`, `3PC8_AB`, `1S1Q_CD`, and `1SYX_AB`. All four targets completed
ProteinMPNN candidate generation and Boltz complex evaluation with 100 records
per target. Completion and report artifacts are:

- `results/m6d_redesign_panel_completion.json`
- `results/m6d_redesign_panel_report.json`
- `results/m6d_redesign_panel_diagnostic.json`
- `results/m6d_redesign_next_science_actions.{json,md}`

At alpha=0.2, every target is evaluable but not certified:

| target | success | alpha=0.2 status | diagnostic class | recommended action |
|---|---:|---|---|---|
| `1BRS_AD` | 54/100 | not certified | `underpowered_or_split_sensitive` | keep as anchor, but do not treat as solved generalization |
| `3PC8_AB` | 53/100 | not certified | `underpowered_low_pae_acceptance` | retain as the best scale candidate after explicit low-pAE strategy |
| `1S1Q_CD` | 43/100 | not certified | `underpowered_low_pae_acceptance` | do not scale until acceptance strategy improves |
| `1SYX_AB` | 12/100 | not certified | `target_protocol_mismatch_low_success` | replace or redesign protocol before more GPU |

Relaxed-alpha diagnostics are useful only for planning: at alpha=0.3,
`3PC8_AB` certifies; at alpha=0.4, `1BRS_AD` and `3PC8_AB` certify. These are
not alpha=0.2 W2 claims.

## Follow-up Panel Result

The follow-up panel used `configs/m6d_followup_complex_targets.json`, reused the
completed `1BRS_AD` and `3PC8_AB` records, and added `1MEL_MB`, `1GCQ_CB`, and
`2IDO_CD`. All five targets have 100 records each.

At alpha=0.2, the panel remains evaluable but not certified:

| target | success | alpha=0.2 status | seed-sensitivity readout | decision |
|---|---:|---|---|---|
| `1BRS_AD` | 54/100 | not certified | alpha=0.3 in 26/100 split seeds; alpha=0.2 in 0/100 | keep as anchor/reference |
| `3PC8_AB` | 53/100 | not certified | alpha=0.3 in 100/100 split seeds; alpha=0.2 in 4/100; median extra records 22 | target-specific mini-scale |
| `1MEL_MB` | 52/100 | not certified | alpha=0.3 and alpha=0.2 in 0/100; median extra records 2464 | do not scale under current protocol |
| `1GCQ_CB` | 14/100 | not certified | alpha=0.3 and alpha=0.2 in 0/100; no useful extra-record estimate | replace or redesign protocol |
| `2IDO_CD` | 33/100 | not certified | alpha=0.3 and alpha=0.2 in 0/100; median extra records 4944 | do not scale under current protocol |

The `3PC8_AB` t0.3 mini-scale from
`results/m6d_followup_3PC8_AB_next_batch.{json,sh}` wrote only to
`hpc_outputs/m6d_followup_3PC8_AB_scale_t030` and completed successfully:
50 candidates, 50 Boltz records, then
`results/m6d_followup_3PC8_AB_posthoc_scale_t030/complex_alpha_decision.json`
returned `decision=stop_certified` for alpha=0.2 with 150 total 3PC8 records.
This is a target-specific alpha-tightening certificate and must not be promoted
to a multi-target W2 claim.

## Next Action

Use the redesign diagnostic before any new W2 GPU spend:

```sh
python -m bio_sfm_designer.experiments.complex_panel_redesign_diagnostic \
  --panel-report results/m6c_panel_report.json \
  --protocol-summary results/m6c_protocol_branch_summary.json \
  --out results/m6c_w2_redesign_diagnostic.json \
  --out-md results/m6c_w2_redesign_diagnostic.md
```

The next W2 manifest should either replace `1CGI_EI` and `2SIC_EI` with targets
that have a less pathological baseline success rate, or explicitly redesign the
generation/evaluation protocol for those target classes. After a revised manifest
exists, rerun the readiness artifact so the roadmap status, ordered steps, and
shell review plan all carry the same evidence:

```sh
python -m bio_sfm_designer.experiments.complex_readiness \
  --target-manifest configs/m6d_candidate_complex_targets.json \
  --input-prep-completion results/m6d_candidate_input_prep_completion.json \
  --require-files \
  --panel-min-targets 3 \
  --target-alpha 0.2 \
  --out results/m6d_candidate_readiness.json \
  --emit-plan results/m6d_candidate_readiness.sh
```

After the completed follow-up panel and 3PC8 mini-scale, the next W2 action is
narrower: freeze `3PC8_AB` as a target-specific alpha=0.2 result, then continue
searching for better 3PC8-like targets. Do not spend more GPU on `1MEL_MB`,
`1GCQ_CB`, or `2IDO_CD` under the current protocol.
