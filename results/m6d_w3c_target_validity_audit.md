# M6d W3c target-validity audit

Status: `w3c_target_validity_reset_complete_fresh_target_discovery_required`.
Audit ok: `True`.

## Result

- representative targets: `24`
- complete author-determined two-chain assemblies: `5`
- strict target-binder eligible: `3`
- strict eligible IDs: `1FFG_CD, 1FR2_BA, 1F3V_BA`

## Historical Branches

| branch | targets | complete two-chain | strict target-binder |
|---|---:|---:|---:|
| W2b | 8 | 1 | 0 |
| W2c | 8 | 2 | 2 |
| W3b | 8 | 2 | 1 |

## Targets

| target | branch | selected molecules | author assembly | omitted protein chains | structural | semantic | strict |
|---|---|---|---|---|---|---|---|
| `1F66_AB` | W2b | HISTONE H3 / HISTONE H4 | DECAMERIC:A,B,C,D,E,F,G,H | C,D,E,F,G,H | `False` | `out_of_scope` | `False` |
| `1F93_DC` | W2b | DIMERIZATION COFACTOR OF HEPATOCYTE NUCLEAR FACTOR 1-ALPHA / DIMERIZATION COFACTOR OF HEPATOCYTE NUCLEAR FACTOR 1-ALPHA | TETRAMERIC:C,D,G,H | G,H | `False` | `out_of_scope` | `False` |
| `1FJG_FR` | W2b | 30S RIBOSOMAL PROTEIN S6 / 30S RIBOSOMAL PROTEIN S18 | 22-MERIC:B,C,D,E,F,G,H,I,J,K,L,M,N,O,P,Q,R,S,T,V | B,C,D,E,G,H,I,J,K,L,M,N,O,P,Q,S,T,V | `False` | `out_of_scope` | `False` |
| `1FYR_CD` | W2c | GROWTH FACTOR RECEPTOR-BOUND PROTEIN 2 / GROWTH FACTOR RECEPTOR-BOUND PROTEIN 2 | TETRAMERIC:C,D,K,L | K,L | `False` | `out_of_scope` | `False` |
| `1FLT_WV` | W2b | VASCULAR ENDOTHELIAL GROWTH FACTOR / VASCULAR ENDOTHELIAL GROWTH FACTOR | TETRAMERIC:V,W,X,Y | X,Y | `False` | `out_of_scope` | `False` |
| `1FL7_DC` | W3b | FOLLICLE STIMULATING PROTEIN BETA CHAIN / FOLLICLE STIMULATING PROTEIN ALPHA CHAIN | DIMERIC:C,D | none | `True` | `out_of_scope` | `False` |
| `1F80_BC` | W2c | HOLO-(ACYL CARRIER PROTEIN) SYNTHASE / HOLO-(ACYL CARRIER PROTEIN) SYNTHASE | HEXAMERIC:A,B,C,D,E,F | A,D,E,F | `False` | `out_of_scope` | `False` |
| `1FVC_DC` | W2b | IGG1-KAPPA 4D5 FV (HEAVY CHAIN) / IGG1-KAPPA 4D5 FV (LIGHT CHAIN) | DIMERIC:C,D | none | `True` | `out_of_scope` | `False` |
| `1EZV_XY` | W2c | HEAVY CHAIN (VH) OF FV-FRAGMENT / LIGHT CHAIN (VL) OF FV-FRAGMENT | EICOSAMERIC:A,B,C,D,E,F,G,H,I,X,Y | A,B,C,D,E,F,G,H,I | `False` | `out_of_scope` | `False` |
| `1FFG_CD` | W2c | CHEMOTAXIS PROTEIN CHEY / CHEMOTAXIS PROTEIN CHEA | DIMERIC:C,D | none | `True` | `pass` | `True` |
| `1FR2_BA` | W2c | COLICIN E9 / COLICIN E9 IMMUNITY PROTEIN | DIMERIC:A,B | none | `True` | `pass` | `True` |
| `1FFK_HR` | W2c | RIBOSOMAL PROTEIN L14 / RIBOSOMAL PROTEIN L24E | 29-MERIC:1,A,B,C,D,E,F,G,H,I,J,K,L,M,N,O,P,Q,R,S,T,U,V,W,X,Y,Z | 1,A,B,C,D,E,F,G,I,J,K,L,M,N,O,P,Q,S,T,U,V,W,X,Y,Z | `False` | `out_of_scope` | `False` |
| `1FXK_CA` | W2b | PROTEIN (PREFOLDIN) / PREFOLDIN | HEXAMERIC:A,B,C | B | `False` | `out_of_scope` | `False` |
| `1FSX_BA` | W3b | HEMOGLOBIN BETA CHAIN / HEMOGLOBIN ALPHA CHAIN | TETRAMERIC:A,B,C,D | C,D | `False` | `out_of_scope` | `False` |
| `1FDH_GA` | W2b | HEMOGLOBIN F (DEOXY) (GAMMA CHAIN) / HEMOGLOBIN F (DEOXY) (ALPHA CHAIN) | TETRAMERIC:A,B,G,H | B,H | `False` | `out_of_scope` | `False` |
| `1FN3_DC` | W3b | HEMOGLOBIN BETA CHAIN / HEMOGLOBIN ALPHA CHAIN | TETRAMERIC:A,B,C,D | A,B | `False` | `out_of_scope` | `False` |
| `1FHJ_BA` | W3b | HEMOGLOBIN (BETA CHAIN) / HEMOGLOBIN (ALPHA CHAIN) | TETRAMERIC:A,B,C,D | C,D | `False` | `out_of_scope` | `False` |
| `1F2U_CD` | W3b | RAD50 ABC-ATPASE / RAD50 ABC-ATPASE | TETRAMERIC:A,B,C,D | A,B | `False` | `out_of_scope` | `False` |
| `1F3V_BA` | W3b | TUMOR NECROSIS FACTOR RECEPTOR-ASSOCIATED PROTEIN / TUMOR NECROSIS FACTOR RECEPTOR TYPE 1 ASSOCIATED DEATH DOMAIN PROTEIN | DIMERIC:A,B | none | `True` | `pass` | `True` |
| `1F99_BA` | W2c | R-PHYCOCYANIN / R-PHYCOCYANIN | DODECAMERIC:A,B,K,L,M,N | K,L,M,N | `False` | `out_of_scope` | `False` |
| `1F51_AE` | W2b | SPORULATION INITIATION PHOSPHOTRANSFERASE B / SPORULATION INITIATION PHOSPHOTRANSFERASE F | TETRAMERIC:A,B,E,F | B,F | `False` | `needs_reformulation` | `False` |
| `1FV1_BA` | W3b | MAJOR HISTOCOMPATIBILITY COMPLEX BETA CHAIN / MAJOR HISTOCOMPATIBILITY COMPLEX ALPHA CHAIN | TRIMERIC:A,B,C | C | `False` | `out_of_scope` | `False` |
| `1FQ9_CA` | W2c | FIBROBLAST GROWTH FACTOR RECEPTOR 1 / FIBROBLAST GROWTH FACTOR 2 | TETRAMERIC:A,B,C,D | B,D | `False` | `needs_reformulation` | `False` |
| `1FSK_LJ` | W3b | ANTIBODY HEAVY CHAIN FAB / MAJOR POLLEN ALLERGEN BET V 1-A | TRIMERIC:J,K,L | K | `False` | `needs_reformulation` | `False` |

## Reproducibility

- public structure fixture: `tests/fixtures/m6d_w3c_historical_structure_fixture.json`
- fixture SHA-256: `ba67e4c6922d580e200266b3a0531564f8fe9e76387ee46de70ec2e664f917e5`
- local source PDBs verified against fixture: `True`

## Claim Boundary

W2b, W2c, and W3b remain valid for their exact prepared two-chain structural-proxy inputs. Because the representative pool did not prospectively require a complete author-determined dimer plus target-binder semantics, those branches do not estimate generalization to strict biological target-binder systems.

## Next Action

Discover and preregister eight fresh, source-disjoint targets that pass the frozen structural and semantic validity gate. Prepare no ProteinMPNN designs. A separately approved native-sequence screen must show that both frozen predictors can recover each target before any generator or trust-gate experiment.

No compute or Cayuga submission is authorized by this audit.
