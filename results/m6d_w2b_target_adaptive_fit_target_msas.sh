# M6c target-MSA precompute plan
# Run this before --require-files panel/scale readiness when target .a3m/report files are missing or stale.
set -euo pipefail
PYTHON_BIN="${BIO_SFM_PYTHON:-${ENV_PY:-python3}}"

# Optional: set TARGET_MSA_PRECOMPUTE_RECEIPT to append submitted/reused targets as JSONL.
if [ -n "${TARGET_MSA_PRECOMPUTE_RECEIPT:-}" ]; then
  mkdir -p "$(dirname "$TARGET_MSA_PRECOMPUTE_RECEIPT")"
fi
TARGET_MSA_PRECOMPUTE_MANIFEST=configs/m6d_w2b_target_adaptive_fit_targets.json
export TARGET_MSA_PRECOMPUTE_MANIFEST
TARGET_MSA_PRECOMPUTE_MANIFEST_SHA256_EXPECTED=1459d29181ff0d2c1b5fafbf57b4e3f11e1cd872749f17fe951ece96e550ef14
export TARGET_MSA_PRECOMPUTE_MANIFEST_SHA256_EXPECTED
if [ ! -f "$TARGET_MSA_PRECOMPUTE_MANIFEST" ]; then
  echo "target-MSA precompute manifest is missing: $TARGET_MSA_PRECOMPUTE_MANIFEST" >&2
  exit 2
fi
TARGET_MSA_PRECOMPUTE_MANIFEST_SHA256_ACTUAL=$("$PYTHON_BIN" - <<'PY'
import hashlib, os, pathlib
path = pathlib.Path(os.environ["TARGET_MSA_PRECOMPUTE_MANIFEST"])
print(hashlib.sha256(path.read_bytes()).hexdigest())
PY
)
if [ "$TARGET_MSA_PRECOMPUTE_MANIFEST_SHA256_ACTUAL" != "$TARGET_MSA_PRECOMPUTE_MANIFEST_SHA256_EXPECTED" ]; then
  echo "target-MSA precompute manifest is stale: $TARGET_MSA_PRECOMPUTE_MANIFEST expected_sha256=$TARGET_MSA_PRECOMPUTE_MANIFEST_SHA256_EXPECTED actual_sha256=$TARGET_MSA_PRECOMPUTE_MANIFEST_SHA256_ACTUAL" >&2
  exit 2
fi
TARGET_MSA_PRECOMPUTE_MANIFEST_SHA256="$TARGET_MSA_PRECOMPUTE_MANIFEST_SHA256_EXPECTED"
export TARGET_MSA_PRECOMPUTE_MANIFEST_SHA256
TARGET_MSA_PRECOMPUTE_DRY_RUN_TARGETS='["1FXK_CA", "1F93_DC", "1F66_AB", "1FJG_FR", "1FDH_GA", "1FLT_WV", "1F51_AE", "1FVC_DC"]'
export TARGET_MSA_PRECOMPUTE_DRY_RUN_TARGETS
if [ "${TARGET_MSA_PRECOMPUTE_DRY_RUN:-0}" = "1" ]; then
  echo "target-MSA precompute dry-run: manifest fresh; no scheduler jobs submitted; receipt untouched."
  "$PYTHON_BIN" - <<'PY'
import json, os
targets = json.loads(os.environ.get('TARGET_MSA_PRECOMPUTE_DRY_RUN_TARGETS') or '[]')
print('target-MSA precompute dry-run targets: ' + ','.join(targets))
PY
  exit 0
fi
record_target_msa_precompute() {
  local target_id="$1"
  local status="$2"
  local job_id="$3"
  local fasta="$4"
  local out="$5"
  local report="$6"
  if [ -z "${TARGET_MSA_PRECOMPUTE_RECEIPT:-}" ]; then
    return 0
  fi
  TARGET_ID="$target_id" STATUS="$status" JOB_ID="$job_id" FASTA="$fasta" OUT="$out" REPORT="$report" WORKSTREAM="${TARGET_MSA_PRECOMPUTE_WORKSTREAM:-}" MANIFEST="${TARGET_MSA_PRECOMPUTE_MANIFEST:-}" MANIFEST_SHA256="${TARGET_MSA_PRECOMPUTE_MANIFEST_SHA256:-}" "$PYTHON_BIN" - <<'PY'
import json, os, time
record = {
    "target_id": os.environ["TARGET_ID"],
    "status": os.environ["STATUS"],
    "job_id": os.environ.get("JOB_ID") or None,
    "target_fasta": os.environ["FASTA"],
    "target_msa": os.environ["OUT"],
    "target_msa_report": os.environ["REPORT"],
    "manifest": os.environ.get("MANIFEST") or None,
    "manifest_sha256": os.environ.get("MANIFEST_SHA256") or None,
    "workstream": os.environ.get("WORKSTREAM") or None,
    "timestamp_unix": int(time.time()),
}
with open(os.environ["TARGET_MSA_PRECOMPUTE_RECEIPT"], "a") as fh:
    fh.write(json.dumps(record, sort_keys=True) + "\n")
PY
}
require_target_msa_job_id() {
  local target_id="$1"
  local job_id="$2"
  if [ -z "${job_id//[[:space:]]/}" ]; then
    echo "target-MSA precompute sbatch returned an empty or whitespace-only job id for ${target_id}; not recording submitted receipt" >&2
    exit 2
  fi
  if [[ "$job_id" =~ [[:space:]] ]]; then
    echo "target-MSA precompute sbatch returned a non-parsable job id with whitespace for ${target_id}: ${job_id}" >&2
    exit 2
  fi
}
validate_target_msa_precompute_receipt() {
  if [ -z "${TARGET_MSA_PRECOMPUTE_RECEIPT:-}" ]; then
    return 0
  fi
  local expected_json="{}"
  if [ "${1:-}" = "--expect-json" ]; then
    if [ "$#" -lt 2 ]; then
      echo "validate_target_msa_precompute_receipt missing JSON after --expect-json" >&2
      exit 2
    fi
    expected_json="$2"
    shift 2
  fi
  TARGET_MSA_PRECOMPUTE_EXPECTED_JSON="$expected_json" "$PYTHON_BIN" - "$TARGET_MSA_PRECOMPUTE_RECEIPT" "$@" <<'PY'
import json, os, pathlib, sys
receipt = pathlib.Path(sys.argv[1])
expected = [str(target_id) for target_id in sys.argv[2:]]
if not expected:
    raise SystemExit(0)
bad = []
try:
    expected_specs = json.loads(os.environ.get('TARGET_MSA_PRECOMPUTE_EXPECTED_JSON') or '{}')
except json.JSONDecodeError as exc:
    expected_specs = {}
    bad.append(f'invalid expected receipt JSON: {exc}')
if not isinstance(expected_specs, dict):
    expected_specs = {}
    bad.append('expected receipt JSON must be an object')
if not receipt.exists() or receipt.stat().st_size <= 0:
    bad.append(f'receipt is missing or empty: {receipt}')
records = []
if receipt.exists():
    with receipt.open() as fh:
        for lineno, line in enumerate(fh, 1):
            text = line.strip()
            if not text:
                continue
            try:
                record = json.loads(text)
            except json.JSONDecodeError as exc:
                bad.append(f'line {lineno}: invalid JSON: {exc}')
                continue
            if not isinstance(record, dict):
                bad.append(f'line {lineno}: receipt record is not an object')
                continue
            records.append((lineno, record))
expected_set = set(expected)
by_expected = {target_id: [] for target_id in expected}
seen_unexpected = set()
accepted_statuses = {'submitted', 'validated_existing'}
for lineno, record in records:
    target_id = str(record.get('target_id') or '')
    if target_id in expected_set:
        by_expected[target_id].append((lineno, record))
    elif target_id:
        seen_unexpected.add(target_id)
for target_id in expected:
    rows = by_expected[target_id]
    if not rows:
        bad.append(f'missing expected target_id={target_id}')
        continue
    if len(rows) > 1:
        lines = ','.join(str(lineno) for lineno, _record in rows)
        bad.append(f'duplicate expected target_id={target_id} lines={lines}')
    for lineno, record in rows:
        status = record.get('status')
        if status not in accepted_statuses:
            bad.append(f'line {lineno}: target_id={target_id} unexpected status={status!r}')
        if status == 'submitted':
            job_id = str(record.get('job_id') or '')
            if not job_id.strip() or any(ch.isspace() for ch in job_id):
                bad.append(f'line {lineno}: target_id={target_id} has non-parsable submitted job_id={job_id!r}')
        for field in ('target_fasta', 'target_msa', 'target_msa_report'):
            value = record.get(field)
            if not isinstance(value, str) or not value.strip():
                bad.append(f'line {lineno}: target_id={target_id} missing non-empty {field}')
        spec = expected_specs.get(target_id)
        if spec is not None and not isinstance(spec, dict):
            bad.append(f'target_id={target_id} expected receipt spec is not an object')
            continue
        for field in ('target_fasta', 'target_msa', 'target_msa_report', 'manifest', 'manifest_sha256', 'workstream'):
            if not spec or field not in spec:
                continue
            expected_value = str(spec[field])
            actual_value = record.get(field)
            if actual_value is None or str(actual_value) != expected_value:
                bad.append(
                    f'line {lineno}: target_id={target_id} {field} mismatch '
                    f'expected={expected_value!r} actual={actual_value!r}'
                )
if os.environ.get('TARGET_MSA_PRECOMPUTE_RECEIPT_STRICT_TARGET_SET') == '1' and seen_unexpected:
    bad.append('unexpected target ids in receipt: ' + ','.join(sorted(seen_unexpected)))
if bad:
    print('target-MSA precompute receipt validation failed:', file=sys.stderr)
    for item in bad:
        print(f'  - {item}', file=sys.stderr)
    raise SystemExit(2)
print(f'target-MSA precompute receipt validated for {len(expected)} expected target(s): {receipt}')
PY
}

# 1FXK_CA
mkdir -p hpc_outputs/m6d_w2b_target_adaptive_sources hpc_outputs/m6d_w2b_target_adaptive_targets/1FXK_CA
if [ -s hpc_outputs/m6d_w2b_target_adaptive_sources/source_1FXK.pdb ]; then
  echo 'source PDB already exists: hpc_outputs/m6d_w2b_target_adaptive_sources/source_1FXK.pdb'
else
  curl -fsSL https://files.rcsb.org/download/1FXK.pdb -o hpc_outputs/m6d_w2b_target_adaptive_sources/source_1FXK.pdb
fi
if [ -s hpc_outputs/m6d_w2b_target_adaptive_targets/1FXK_CA/prepared_1FXK_CA.pdb ] && [ -s hpc_outputs/m6d_w2b_target_adaptive_targets/1FXK_CA/prepared_1FXK_CA.report.json ]; then
  echo 'prepared PDB already exists: hpc_outputs/m6d_w2b_target_adaptive_targets/1FXK_CA/prepared_1FXK_CA.pdb'
else
  "$PYTHON_BIN" hpc/prep_hetdimer.py --pdb hpc_outputs/m6d_w2b_target_adaptive_sources/source_1FXK.pdb --target-chain C --binder-chain A --out hpc_outputs/m6d_w2b_target_adaptive_targets/1FXK_CA/prepared_1FXK_CA.pdb --report hpc_outputs/m6d_w2b_target_adaptive_targets/1FXK_CA/prepared_1FXK_CA.report.json
fi
"$PYTHON_BIN" hpc/extract_chain_fasta.py --pdb hpc_outputs/m6d_w2b_target_adaptive_targets/1FXK_CA/prepared_1FXK_CA.pdb --chain C --id 1FXK_CA_C --out hpc_outputs/m6d_w2b_target_adaptive_targets/1FXK_CA/1FXK_CA_C.fasta --report hpc_outputs/m6d_w2b_target_adaptive_targets/1FXK_CA/1FXK_CA_C.fasta.report.json
if [ -s hpc_outputs/m6d_w2b_target_adaptive_targets/1FXK_CA/1FXK_CA_C.a3m ]; then
  echo 'target MSA exists; validating and refreshing report: hpc_outputs/m6d_w2b_target_adaptive_targets/1FXK_CA/1FXK_CA_C.a3m'
  "$PYTHON_BIN" hpc/precompute_boltz_target_msa.py --fasta hpc_outputs/m6d_w2b_target_adaptive_targets/1FXK_CA/1FXK_CA_C.fasta --out hpc_outputs/m6d_w2b_target_adaptive_targets/1FXK_CA/1FXK_CA_C.a3m --report hpc_outputs/m6d_w2b_target_adaptive_targets/1FXK_CA/1FXK_CA_C.a3m.report.json
  record_target_msa_precompute 1FXK_CA validated_existing '' hpc_outputs/m6d_w2b_target_adaptive_targets/1FXK_CA/1FXK_CA_C.fasta hpc_outputs/m6d_w2b_target_adaptive_targets/1FXK_CA/1FXK_CA_C.a3m hpc_outputs/m6d_w2b_target_adaptive_targets/1FXK_CA/1FXK_CA_C.a3m.report.json
else
  MSA_00_T_1FXK_CA=$(FASTA=hpc_outputs/m6d_w2b_target_adaptive_targets/1FXK_CA/1FXK_CA_C.fasta OUT=hpc_outputs/m6d_w2b_target_adaptive_targets/1FXK_CA/1FXK_CA_C.a3m REPORT=hpc_outputs/m6d_w2b_target_adaptive_targets/1FXK_CA/1FXK_CA_C.a3m.report.json sbatch --parsable hpc/run_precompute_boltz_target_msa.sbatch)
  require_target_msa_job_id 1FXK_CA "${MSA_00_T_1FXK_CA}"
  echo 'submitted target MSA job for 1FXK_CA: '"${MSA_00_T_1FXK_CA}"
  record_target_msa_precompute 1FXK_CA submitted "${MSA_00_T_1FXK_CA}" hpc_outputs/m6d_w2b_target_adaptive_targets/1FXK_CA/1FXK_CA_C.fasta hpc_outputs/m6d_w2b_target_adaptive_targets/1FXK_CA/1FXK_CA_C.a3m hpc_outputs/m6d_w2b_target_adaptive_targets/1FXK_CA/1FXK_CA_C.a3m.report.json
fi

# 1F93_DC
mkdir -p hpc_outputs/m6d_w2b_target_adaptive_sources hpc_outputs/m6d_w2b_target_adaptive_targets/1F93_DC
if [ -s hpc_outputs/m6d_w2b_target_adaptive_sources/source_1F93.pdb ]; then
  echo 'source PDB already exists: hpc_outputs/m6d_w2b_target_adaptive_sources/source_1F93.pdb'
else
  curl -fsSL https://files.rcsb.org/download/1F93.pdb -o hpc_outputs/m6d_w2b_target_adaptive_sources/source_1F93.pdb
fi
if [ -s hpc_outputs/m6d_w2b_target_adaptive_targets/1F93_DC/prepared_1F93_DC.pdb ] && [ -s hpc_outputs/m6d_w2b_target_adaptive_targets/1F93_DC/prepared_1F93_DC.report.json ]; then
  echo 'prepared PDB already exists: hpc_outputs/m6d_w2b_target_adaptive_targets/1F93_DC/prepared_1F93_DC.pdb'
else
  "$PYTHON_BIN" hpc/prep_hetdimer.py --pdb hpc_outputs/m6d_w2b_target_adaptive_sources/source_1F93.pdb --target-chain D --binder-chain C --out hpc_outputs/m6d_w2b_target_adaptive_targets/1F93_DC/prepared_1F93_DC.pdb --report hpc_outputs/m6d_w2b_target_adaptive_targets/1F93_DC/prepared_1F93_DC.report.json
fi
"$PYTHON_BIN" hpc/extract_chain_fasta.py --pdb hpc_outputs/m6d_w2b_target_adaptive_targets/1F93_DC/prepared_1F93_DC.pdb --chain D --id 1F93_DC_D --out hpc_outputs/m6d_w2b_target_adaptive_targets/1F93_DC/1F93_DC_D.fasta --report hpc_outputs/m6d_w2b_target_adaptive_targets/1F93_DC/1F93_DC_D.fasta.report.json
if [ -s hpc_outputs/m6d_w2b_target_adaptive_targets/1F93_DC/1F93_DC_D.a3m ]; then
  echo 'target MSA exists; validating and refreshing report: hpc_outputs/m6d_w2b_target_adaptive_targets/1F93_DC/1F93_DC_D.a3m'
  "$PYTHON_BIN" hpc/precompute_boltz_target_msa.py --fasta hpc_outputs/m6d_w2b_target_adaptive_targets/1F93_DC/1F93_DC_D.fasta --out hpc_outputs/m6d_w2b_target_adaptive_targets/1F93_DC/1F93_DC_D.a3m --report hpc_outputs/m6d_w2b_target_adaptive_targets/1F93_DC/1F93_DC_D.a3m.report.json
  record_target_msa_precompute 1F93_DC validated_existing '' hpc_outputs/m6d_w2b_target_adaptive_targets/1F93_DC/1F93_DC_D.fasta hpc_outputs/m6d_w2b_target_adaptive_targets/1F93_DC/1F93_DC_D.a3m hpc_outputs/m6d_w2b_target_adaptive_targets/1F93_DC/1F93_DC_D.a3m.report.json
else
  MSA_01_T_1F93_DC=$(FASTA=hpc_outputs/m6d_w2b_target_adaptive_targets/1F93_DC/1F93_DC_D.fasta OUT=hpc_outputs/m6d_w2b_target_adaptive_targets/1F93_DC/1F93_DC_D.a3m REPORT=hpc_outputs/m6d_w2b_target_adaptive_targets/1F93_DC/1F93_DC_D.a3m.report.json sbatch --parsable hpc/run_precompute_boltz_target_msa.sbatch)
  require_target_msa_job_id 1F93_DC "${MSA_01_T_1F93_DC}"
  echo 'submitted target MSA job for 1F93_DC: '"${MSA_01_T_1F93_DC}"
  record_target_msa_precompute 1F93_DC submitted "${MSA_01_T_1F93_DC}" hpc_outputs/m6d_w2b_target_adaptive_targets/1F93_DC/1F93_DC_D.fasta hpc_outputs/m6d_w2b_target_adaptive_targets/1F93_DC/1F93_DC_D.a3m hpc_outputs/m6d_w2b_target_adaptive_targets/1F93_DC/1F93_DC_D.a3m.report.json
fi

# 1F66_AB
mkdir -p hpc_outputs/m6d_w2b_target_adaptive_sources hpc_outputs/m6d_w2b_target_adaptive_targets/1F66_AB
if [ -s hpc_outputs/m6d_w2b_target_adaptive_sources/source_1F66.pdb ]; then
  echo 'source PDB already exists: hpc_outputs/m6d_w2b_target_adaptive_sources/source_1F66.pdb'
else
  curl -fsSL https://files.rcsb.org/download/1F66.pdb -o hpc_outputs/m6d_w2b_target_adaptive_sources/source_1F66.pdb
fi
if [ -s hpc_outputs/m6d_w2b_target_adaptive_targets/1F66_AB/prepared_1F66_AB.pdb ] && [ -s hpc_outputs/m6d_w2b_target_adaptive_targets/1F66_AB/prepared_1F66_AB.report.json ]; then
  echo 'prepared PDB already exists: hpc_outputs/m6d_w2b_target_adaptive_targets/1F66_AB/prepared_1F66_AB.pdb'
else
  "$PYTHON_BIN" hpc/prep_hetdimer.py --pdb hpc_outputs/m6d_w2b_target_adaptive_sources/source_1F66.pdb --target-chain A --binder-chain B --out hpc_outputs/m6d_w2b_target_adaptive_targets/1F66_AB/prepared_1F66_AB.pdb --report hpc_outputs/m6d_w2b_target_adaptive_targets/1F66_AB/prepared_1F66_AB.report.json
fi
"$PYTHON_BIN" hpc/extract_chain_fasta.py --pdb hpc_outputs/m6d_w2b_target_adaptive_targets/1F66_AB/prepared_1F66_AB.pdb --chain A --id 1F66_AB_A --out hpc_outputs/m6d_w2b_target_adaptive_targets/1F66_AB/1F66_AB_A.fasta --report hpc_outputs/m6d_w2b_target_adaptive_targets/1F66_AB/1F66_AB_A.fasta.report.json
if [ -s hpc_outputs/m6d_w2b_target_adaptive_targets/1F66_AB/1F66_AB_A.a3m ]; then
  echo 'target MSA exists; validating and refreshing report: hpc_outputs/m6d_w2b_target_adaptive_targets/1F66_AB/1F66_AB_A.a3m'
  "$PYTHON_BIN" hpc/precompute_boltz_target_msa.py --fasta hpc_outputs/m6d_w2b_target_adaptive_targets/1F66_AB/1F66_AB_A.fasta --out hpc_outputs/m6d_w2b_target_adaptive_targets/1F66_AB/1F66_AB_A.a3m --report hpc_outputs/m6d_w2b_target_adaptive_targets/1F66_AB/1F66_AB_A.a3m.report.json
  record_target_msa_precompute 1F66_AB validated_existing '' hpc_outputs/m6d_w2b_target_adaptive_targets/1F66_AB/1F66_AB_A.fasta hpc_outputs/m6d_w2b_target_adaptive_targets/1F66_AB/1F66_AB_A.a3m hpc_outputs/m6d_w2b_target_adaptive_targets/1F66_AB/1F66_AB_A.a3m.report.json
else
  MSA_02_T_1F66_AB=$(FASTA=hpc_outputs/m6d_w2b_target_adaptive_targets/1F66_AB/1F66_AB_A.fasta OUT=hpc_outputs/m6d_w2b_target_adaptive_targets/1F66_AB/1F66_AB_A.a3m REPORT=hpc_outputs/m6d_w2b_target_adaptive_targets/1F66_AB/1F66_AB_A.a3m.report.json sbatch --parsable hpc/run_precompute_boltz_target_msa.sbatch)
  require_target_msa_job_id 1F66_AB "${MSA_02_T_1F66_AB}"
  echo 'submitted target MSA job for 1F66_AB: '"${MSA_02_T_1F66_AB}"
  record_target_msa_precompute 1F66_AB submitted "${MSA_02_T_1F66_AB}" hpc_outputs/m6d_w2b_target_adaptive_targets/1F66_AB/1F66_AB_A.fasta hpc_outputs/m6d_w2b_target_adaptive_targets/1F66_AB/1F66_AB_A.a3m hpc_outputs/m6d_w2b_target_adaptive_targets/1F66_AB/1F66_AB_A.a3m.report.json
fi

# 1FJG_FR
mkdir -p hpc_outputs/m6d_w2b_target_adaptive_sources hpc_outputs/m6d_w2b_target_adaptive_targets/1FJG_FR
if [ -s hpc_outputs/m6d_w2b_target_adaptive_sources/source_1FJG.pdb ]; then
  echo 'source PDB already exists: hpc_outputs/m6d_w2b_target_adaptive_sources/source_1FJG.pdb'
else
  curl -fsSL https://files.rcsb.org/download/1FJG.pdb -o hpc_outputs/m6d_w2b_target_adaptive_sources/source_1FJG.pdb
fi
if [ -s hpc_outputs/m6d_w2b_target_adaptive_targets/1FJG_FR/prepared_1FJG_FR.pdb ] && [ -s hpc_outputs/m6d_w2b_target_adaptive_targets/1FJG_FR/prepared_1FJG_FR.report.json ]; then
  echo 'prepared PDB already exists: hpc_outputs/m6d_w2b_target_adaptive_targets/1FJG_FR/prepared_1FJG_FR.pdb'
else
  "$PYTHON_BIN" hpc/prep_hetdimer.py --pdb hpc_outputs/m6d_w2b_target_adaptive_sources/source_1FJG.pdb --target-chain F --binder-chain R --out hpc_outputs/m6d_w2b_target_adaptive_targets/1FJG_FR/prepared_1FJG_FR.pdb --report hpc_outputs/m6d_w2b_target_adaptive_targets/1FJG_FR/prepared_1FJG_FR.report.json
fi
"$PYTHON_BIN" hpc/extract_chain_fasta.py --pdb hpc_outputs/m6d_w2b_target_adaptive_targets/1FJG_FR/prepared_1FJG_FR.pdb --chain F --id 1FJG_FR_F --out hpc_outputs/m6d_w2b_target_adaptive_targets/1FJG_FR/1FJG_FR_F.fasta --report hpc_outputs/m6d_w2b_target_adaptive_targets/1FJG_FR/1FJG_FR_F.fasta.report.json
if [ -s hpc_outputs/m6d_w2b_target_adaptive_targets/1FJG_FR/1FJG_FR_F.a3m ]; then
  echo 'target MSA exists; validating and refreshing report: hpc_outputs/m6d_w2b_target_adaptive_targets/1FJG_FR/1FJG_FR_F.a3m'
  "$PYTHON_BIN" hpc/precompute_boltz_target_msa.py --fasta hpc_outputs/m6d_w2b_target_adaptive_targets/1FJG_FR/1FJG_FR_F.fasta --out hpc_outputs/m6d_w2b_target_adaptive_targets/1FJG_FR/1FJG_FR_F.a3m --report hpc_outputs/m6d_w2b_target_adaptive_targets/1FJG_FR/1FJG_FR_F.a3m.report.json
  record_target_msa_precompute 1FJG_FR validated_existing '' hpc_outputs/m6d_w2b_target_adaptive_targets/1FJG_FR/1FJG_FR_F.fasta hpc_outputs/m6d_w2b_target_adaptive_targets/1FJG_FR/1FJG_FR_F.a3m hpc_outputs/m6d_w2b_target_adaptive_targets/1FJG_FR/1FJG_FR_F.a3m.report.json
else
  MSA_03_T_1FJG_FR=$(FASTA=hpc_outputs/m6d_w2b_target_adaptive_targets/1FJG_FR/1FJG_FR_F.fasta OUT=hpc_outputs/m6d_w2b_target_adaptive_targets/1FJG_FR/1FJG_FR_F.a3m REPORT=hpc_outputs/m6d_w2b_target_adaptive_targets/1FJG_FR/1FJG_FR_F.a3m.report.json sbatch --parsable hpc/run_precompute_boltz_target_msa.sbatch)
  require_target_msa_job_id 1FJG_FR "${MSA_03_T_1FJG_FR}"
  echo 'submitted target MSA job for 1FJG_FR: '"${MSA_03_T_1FJG_FR}"
  record_target_msa_precompute 1FJG_FR submitted "${MSA_03_T_1FJG_FR}" hpc_outputs/m6d_w2b_target_adaptive_targets/1FJG_FR/1FJG_FR_F.fasta hpc_outputs/m6d_w2b_target_adaptive_targets/1FJG_FR/1FJG_FR_F.a3m hpc_outputs/m6d_w2b_target_adaptive_targets/1FJG_FR/1FJG_FR_F.a3m.report.json
fi

# 1FDH_GA
mkdir -p hpc_outputs/m6d_w2b_target_adaptive_sources hpc_outputs/m6d_w2b_target_adaptive_targets/1FDH_GA
if [ -s hpc_outputs/m6d_w2b_target_adaptive_sources/source_1FDH.pdb ]; then
  echo 'source PDB already exists: hpc_outputs/m6d_w2b_target_adaptive_sources/source_1FDH.pdb'
else
  curl -fsSL https://files.rcsb.org/download/1FDH.pdb -o hpc_outputs/m6d_w2b_target_adaptive_sources/source_1FDH.pdb
fi
if [ -s hpc_outputs/m6d_w2b_target_adaptive_targets/1FDH_GA/prepared_1FDH_GA.pdb ] && [ -s hpc_outputs/m6d_w2b_target_adaptive_targets/1FDH_GA/prepared_1FDH_GA.report.json ]; then
  echo 'prepared PDB already exists: hpc_outputs/m6d_w2b_target_adaptive_targets/1FDH_GA/prepared_1FDH_GA.pdb'
else
  "$PYTHON_BIN" hpc/prep_hetdimer.py --pdb hpc_outputs/m6d_w2b_target_adaptive_sources/source_1FDH.pdb --target-chain G --binder-chain A --out hpc_outputs/m6d_w2b_target_adaptive_targets/1FDH_GA/prepared_1FDH_GA.pdb --report hpc_outputs/m6d_w2b_target_adaptive_targets/1FDH_GA/prepared_1FDH_GA.report.json
fi
"$PYTHON_BIN" hpc/extract_chain_fasta.py --pdb hpc_outputs/m6d_w2b_target_adaptive_targets/1FDH_GA/prepared_1FDH_GA.pdb --chain G --id 1FDH_GA_G --out hpc_outputs/m6d_w2b_target_adaptive_targets/1FDH_GA/1FDH_GA_G.fasta --report hpc_outputs/m6d_w2b_target_adaptive_targets/1FDH_GA/1FDH_GA_G.fasta.report.json
if [ -s hpc_outputs/m6d_w2b_target_adaptive_targets/1FDH_GA/1FDH_GA_G.a3m ]; then
  echo 'target MSA exists; validating and refreshing report: hpc_outputs/m6d_w2b_target_adaptive_targets/1FDH_GA/1FDH_GA_G.a3m'
  "$PYTHON_BIN" hpc/precompute_boltz_target_msa.py --fasta hpc_outputs/m6d_w2b_target_adaptive_targets/1FDH_GA/1FDH_GA_G.fasta --out hpc_outputs/m6d_w2b_target_adaptive_targets/1FDH_GA/1FDH_GA_G.a3m --report hpc_outputs/m6d_w2b_target_adaptive_targets/1FDH_GA/1FDH_GA_G.a3m.report.json
  record_target_msa_precompute 1FDH_GA validated_existing '' hpc_outputs/m6d_w2b_target_adaptive_targets/1FDH_GA/1FDH_GA_G.fasta hpc_outputs/m6d_w2b_target_adaptive_targets/1FDH_GA/1FDH_GA_G.a3m hpc_outputs/m6d_w2b_target_adaptive_targets/1FDH_GA/1FDH_GA_G.a3m.report.json
else
  MSA_04_T_1FDH_GA=$(FASTA=hpc_outputs/m6d_w2b_target_adaptive_targets/1FDH_GA/1FDH_GA_G.fasta OUT=hpc_outputs/m6d_w2b_target_adaptive_targets/1FDH_GA/1FDH_GA_G.a3m REPORT=hpc_outputs/m6d_w2b_target_adaptive_targets/1FDH_GA/1FDH_GA_G.a3m.report.json sbatch --parsable hpc/run_precompute_boltz_target_msa.sbatch)
  require_target_msa_job_id 1FDH_GA "${MSA_04_T_1FDH_GA}"
  echo 'submitted target MSA job for 1FDH_GA: '"${MSA_04_T_1FDH_GA}"
  record_target_msa_precompute 1FDH_GA submitted "${MSA_04_T_1FDH_GA}" hpc_outputs/m6d_w2b_target_adaptive_targets/1FDH_GA/1FDH_GA_G.fasta hpc_outputs/m6d_w2b_target_adaptive_targets/1FDH_GA/1FDH_GA_G.a3m hpc_outputs/m6d_w2b_target_adaptive_targets/1FDH_GA/1FDH_GA_G.a3m.report.json
fi

# 1FLT_WV
mkdir -p hpc_outputs/m6d_w2b_target_adaptive_sources hpc_outputs/m6d_w2b_target_adaptive_targets/1FLT_WV
if [ -s hpc_outputs/m6d_w2b_target_adaptive_sources/source_1FLT.pdb ]; then
  echo 'source PDB already exists: hpc_outputs/m6d_w2b_target_adaptive_sources/source_1FLT.pdb'
else
  curl -fsSL https://files.rcsb.org/download/1FLT.pdb -o hpc_outputs/m6d_w2b_target_adaptive_sources/source_1FLT.pdb
fi
if [ -s hpc_outputs/m6d_w2b_target_adaptive_targets/1FLT_WV/prepared_1FLT_WV.pdb ] && [ -s hpc_outputs/m6d_w2b_target_adaptive_targets/1FLT_WV/prepared_1FLT_WV.report.json ]; then
  echo 'prepared PDB already exists: hpc_outputs/m6d_w2b_target_adaptive_targets/1FLT_WV/prepared_1FLT_WV.pdb'
else
  "$PYTHON_BIN" hpc/prep_hetdimer.py --pdb hpc_outputs/m6d_w2b_target_adaptive_sources/source_1FLT.pdb --target-chain W --binder-chain V --out hpc_outputs/m6d_w2b_target_adaptive_targets/1FLT_WV/prepared_1FLT_WV.pdb --report hpc_outputs/m6d_w2b_target_adaptive_targets/1FLT_WV/prepared_1FLT_WV.report.json
fi
"$PYTHON_BIN" hpc/extract_chain_fasta.py --pdb hpc_outputs/m6d_w2b_target_adaptive_targets/1FLT_WV/prepared_1FLT_WV.pdb --chain W --id 1FLT_WV_W --out hpc_outputs/m6d_w2b_target_adaptive_targets/1FLT_WV/1FLT_WV_W.fasta --report hpc_outputs/m6d_w2b_target_adaptive_targets/1FLT_WV/1FLT_WV_W.fasta.report.json
if [ -s hpc_outputs/m6d_w2b_target_adaptive_targets/1FLT_WV/1FLT_WV_W.a3m ]; then
  echo 'target MSA exists; validating and refreshing report: hpc_outputs/m6d_w2b_target_adaptive_targets/1FLT_WV/1FLT_WV_W.a3m'
  "$PYTHON_BIN" hpc/precompute_boltz_target_msa.py --fasta hpc_outputs/m6d_w2b_target_adaptive_targets/1FLT_WV/1FLT_WV_W.fasta --out hpc_outputs/m6d_w2b_target_adaptive_targets/1FLT_WV/1FLT_WV_W.a3m --report hpc_outputs/m6d_w2b_target_adaptive_targets/1FLT_WV/1FLT_WV_W.a3m.report.json
  record_target_msa_precompute 1FLT_WV validated_existing '' hpc_outputs/m6d_w2b_target_adaptive_targets/1FLT_WV/1FLT_WV_W.fasta hpc_outputs/m6d_w2b_target_adaptive_targets/1FLT_WV/1FLT_WV_W.a3m hpc_outputs/m6d_w2b_target_adaptive_targets/1FLT_WV/1FLT_WV_W.a3m.report.json
else
  MSA_05_T_1FLT_WV=$(FASTA=hpc_outputs/m6d_w2b_target_adaptive_targets/1FLT_WV/1FLT_WV_W.fasta OUT=hpc_outputs/m6d_w2b_target_adaptive_targets/1FLT_WV/1FLT_WV_W.a3m REPORT=hpc_outputs/m6d_w2b_target_adaptive_targets/1FLT_WV/1FLT_WV_W.a3m.report.json sbatch --parsable hpc/run_precompute_boltz_target_msa.sbatch)
  require_target_msa_job_id 1FLT_WV "${MSA_05_T_1FLT_WV}"
  echo 'submitted target MSA job for 1FLT_WV: '"${MSA_05_T_1FLT_WV}"
  record_target_msa_precompute 1FLT_WV submitted "${MSA_05_T_1FLT_WV}" hpc_outputs/m6d_w2b_target_adaptive_targets/1FLT_WV/1FLT_WV_W.fasta hpc_outputs/m6d_w2b_target_adaptive_targets/1FLT_WV/1FLT_WV_W.a3m hpc_outputs/m6d_w2b_target_adaptive_targets/1FLT_WV/1FLT_WV_W.a3m.report.json
fi

# 1F51_AE
mkdir -p hpc_outputs/m6d_w2b_target_adaptive_sources hpc_outputs/m6d_w2b_target_adaptive_targets/1F51_AE
if [ -s hpc_outputs/m6d_w2b_target_adaptive_sources/source_1F51.pdb ]; then
  echo 'source PDB already exists: hpc_outputs/m6d_w2b_target_adaptive_sources/source_1F51.pdb'
else
  curl -fsSL https://files.rcsb.org/download/1F51.pdb -o hpc_outputs/m6d_w2b_target_adaptive_sources/source_1F51.pdb
fi
if [ -s hpc_outputs/m6d_w2b_target_adaptive_targets/1F51_AE/prepared_1F51_AE.pdb ] && [ -s hpc_outputs/m6d_w2b_target_adaptive_targets/1F51_AE/prepared_1F51_AE.report.json ]; then
  echo 'prepared PDB already exists: hpc_outputs/m6d_w2b_target_adaptive_targets/1F51_AE/prepared_1F51_AE.pdb'
else
  "$PYTHON_BIN" hpc/prep_hetdimer.py --pdb hpc_outputs/m6d_w2b_target_adaptive_sources/source_1F51.pdb --target-chain A --binder-chain E --out hpc_outputs/m6d_w2b_target_adaptive_targets/1F51_AE/prepared_1F51_AE.pdb --report hpc_outputs/m6d_w2b_target_adaptive_targets/1F51_AE/prepared_1F51_AE.report.json
fi
"$PYTHON_BIN" hpc/extract_chain_fasta.py --pdb hpc_outputs/m6d_w2b_target_adaptive_targets/1F51_AE/prepared_1F51_AE.pdb --chain A --id 1F51_AE_A --out hpc_outputs/m6d_w2b_target_adaptive_targets/1F51_AE/1F51_AE_A.fasta --report hpc_outputs/m6d_w2b_target_adaptive_targets/1F51_AE/1F51_AE_A.fasta.report.json
if [ -s hpc_outputs/m6d_w2b_target_adaptive_targets/1F51_AE/1F51_AE_A.a3m ]; then
  echo 'target MSA exists; validating and refreshing report: hpc_outputs/m6d_w2b_target_adaptive_targets/1F51_AE/1F51_AE_A.a3m'
  "$PYTHON_BIN" hpc/precompute_boltz_target_msa.py --fasta hpc_outputs/m6d_w2b_target_adaptive_targets/1F51_AE/1F51_AE_A.fasta --out hpc_outputs/m6d_w2b_target_adaptive_targets/1F51_AE/1F51_AE_A.a3m --report hpc_outputs/m6d_w2b_target_adaptive_targets/1F51_AE/1F51_AE_A.a3m.report.json
  record_target_msa_precompute 1F51_AE validated_existing '' hpc_outputs/m6d_w2b_target_adaptive_targets/1F51_AE/1F51_AE_A.fasta hpc_outputs/m6d_w2b_target_adaptive_targets/1F51_AE/1F51_AE_A.a3m hpc_outputs/m6d_w2b_target_adaptive_targets/1F51_AE/1F51_AE_A.a3m.report.json
else
  MSA_06_T_1F51_AE=$(FASTA=hpc_outputs/m6d_w2b_target_adaptive_targets/1F51_AE/1F51_AE_A.fasta OUT=hpc_outputs/m6d_w2b_target_adaptive_targets/1F51_AE/1F51_AE_A.a3m REPORT=hpc_outputs/m6d_w2b_target_adaptive_targets/1F51_AE/1F51_AE_A.a3m.report.json sbatch --parsable hpc/run_precompute_boltz_target_msa.sbatch)
  require_target_msa_job_id 1F51_AE "${MSA_06_T_1F51_AE}"
  echo 'submitted target MSA job for 1F51_AE: '"${MSA_06_T_1F51_AE}"
  record_target_msa_precompute 1F51_AE submitted "${MSA_06_T_1F51_AE}" hpc_outputs/m6d_w2b_target_adaptive_targets/1F51_AE/1F51_AE_A.fasta hpc_outputs/m6d_w2b_target_adaptive_targets/1F51_AE/1F51_AE_A.a3m hpc_outputs/m6d_w2b_target_adaptive_targets/1F51_AE/1F51_AE_A.a3m.report.json
fi

# 1FVC_DC
mkdir -p hpc_outputs/m6d_w2b_target_adaptive_sources hpc_outputs/m6d_w2b_target_adaptive_targets/1FVC_DC
if [ -s hpc_outputs/m6d_w2b_target_adaptive_sources/source_1FVC.pdb ]; then
  echo 'source PDB already exists: hpc_outputs/m6d_w2b_target_adaptive_sources/source_1FVC.pdb'
else
  curl -fsSL https://files.rcsb.org/download/1FVC.pdb -o hpc_outputs/m6d_w2b_target_adaptive_sources/source_1FVC.pdb
fi
if [ -s hpc_outputs/m6d_w2b_target_adaptive_targets/1FVC_DC/prepared_1FVC_DC.pdb ] && [ -s hpc_outputs/m6d_w2b_target_adaptive_targets/1FVC_DC/prepared_1FVC_DC.report.json ]; then
  echo 'prepared PDB already exists: hpc_outputs/m6d_w2b_target_adaptive_targets/1FVC_DC/prepared_1FVC_DC.pdb'
else
  "$PYTHON_BIN" hpc/prep_hetdimer.py --pdb hpc_outputs/m6d_w2b_target_adaptive_sources/source_1FVC.pdb --target-chain D --binder-chain C --out hpc_outputs/m6d_w2b_target_adaptive_targets/1FVC_DC/prepared_1FVC_DC.pdb --report hpc_outputs/m6d_w2b_target_adaptive_targets/1FVC_DC/prepared_1FVC_DC.report.json
fi
"$PYTHON_BIN" hpc/extract_chain_fasta.py --pdb hpc_outputs/m6d_w2b_target_adaptive_targets/1FVC_DC/prepared_1FVC_DC.pdb --chain D --id 1FVC_DC_D --out hpc_outputs/m6d_w2b_target_adaptive_targets/1FVC_DC/1FVC_DC_D.fasta --report hpc_outputs/m6d_w2b_target_adaptive_targets/1FVC_DC/1FVC_DC_D.fasta.report.json
if [ -s hpc_outputs/m6d_w2b_target_adaptive_targets/1FVC_DC/1FVC_DC_D.a3m ]; then
  echo 'target MSA exists; validating and refreshing report: hpc_outputs/m6d_w2b_target_adaptive_targets/1FVC_DC/1FVC_DC_D.a3m'
  "$PYTHON_BIN" hpc/precompute_boltz_target_msa.py --fasta hpc_outputs/m6d_w2b_target_adaptive_targets/1FVC_DC/1FVC_DC_D.fasta --out hpc_outputs/m6d_w2b_target_adaptive_targets/1FVC_DC/1FVC_DC_D.a3m --report hpc_outputs/m6d_w2b_target_adaptive_targets/1FVC_DC/1FVC_DC_D.a3m.report.json
  record_target_msa_precompute 1FVC_DC validated_existing '' hpc_outputs/m6d_w2b_target_adaptive_targets/1FVC_DC/1FVC_DC_D.fasta hpc_outputs/m6d_w2b_target_adaptive_targets/1FVC_DC/1FVC_DC_D.a3m hpc_outputs/m6d_w2b_target_adaptive_targets/1FVC_DC/1FVC_DC_D.a3m.report.json
else
  MSA_07_T_1FVC_DC=$(FASTA=hpc_outputs/m6d_w2b_target_adaptive_targets/1FVC_DC/1FVC_DC_D.fasta OUT=hpc_outputs/m6d_w2b_target_adaptive_targets/1FVC_DC/1FVC_DC_D.a3m REPORT=hpc_outputs/m6d_w2b_target_adaptive_targets/1FVC_DC/1FVC_DC_D.a3m.report.json sbatch --parsable hpc/run_precompute_boltz_target_msa.sbatch)
  require_target_msa_job_id 1FVC_DC "${MSA_07_T_1FVC_DC}"
  echo 'submitted target MSA job for 1FVC_DC: '"${MSA_07_T_1FVC_DC}"
  record_target_msa_precompute 1FVC_DC submitted "${MSA_07_T_1FVC_DC}" hpc_outputs/m6d_w2b_target_adaptive_targets/1FVC_DC/1FVC_DC_D.fasta hpc_outputs/m6d_w2b_target_adaptive_targets/1FVC_DC/1FVC_DC_D.a3m hpc_outputs/m6d_w2b_target_adaptive_targets/1FVC_DC/1FVC_DC_D.a3m.report.json
fi

validate_target_msa_precompute_receipt --expect-json '{"1F51_AE":{"manifest":"configs/m6d_w2b_target_adaptive_fit_targets.json","manifest_sha256":"1459d29181ff0d2c1b5fafbf57b4e3f11e1cd872749f17fe951ece96e550ef14","target_fasta":"hpc_outputs/m6d_w2b_target_adaptive_targets/1F51_AE/1F51_AE_A.fasta","target_msa":"hpc_outputs/m6d_w2b_target_adaptive_targets/1F51_AE/1F51_AE_A.a3m","target_msa_report":"hpc_outputs/m6d_w2b_target_adaptive_targets/1F51_AE/1F51_AE_A.a3m.report.json"},"1F66_AB":{"manifest":"configs/m6d_w2b_target_adaptive_fit_targets.json","manifest_sha256":"1459d29181ff0d2c1b5fafbf57b4e3f11e1cd872749f17fe951ece96e550ef14","target_fasta":"hpc_outputs/m6d_w2b_target_adaptive_targets/1F66_AB/1F66_AB_A.fasta","target_msa":"hpc_outputs/m6d_w2b_target_adaptive_targets/1F66_AB/1F66_AB_A.a3m","target_msa_report":"hpc_outputs/m6d_w2b_target_adaptive_targets/1F66_AB/1F66_AB_A.a3m.report.json"},"1F93_DC":{"manifest":"configs/m6d_w2b_target_adaptive_fit_targets.json","manifest_sha256":"1459d29181ff0d2c1b5fafbf57b4e3f11e1cd872749f17fe951ece96e550ef14","target_fasta":"hpc_outputs/m6d_w2b_target_adaptive_targets/1F93_DC/1F93_DC_D.fasta","target_msa":"hpc_outputs/m6d_w2b_target_adaptive_targets/1F93_DC/1F93_DC_D.a3m","target_msa_report":"hpc_outputs/m6d_w2b_target_adaptive_targets/1F93_DC/1F93_DC_D.a3m.report.json"},"1FDH_GA":{"manifest":"configs/m6d_w2b_target_adaptive_fit_targets.json","manifest_sha256":"1459d29181ff0d2c1b5fafbf57b4e3f11e1cd872749f17fe951ece96e550ef14","target_fasta":"hpc_outputs/m6d_w2b_target_adaptive_targets/1FDH_GA/1FDH_GA_G.fasta","target_msa":"hpc_outputs/m6d_w2b_target_adaptive_targets/1FDH_GA/1FDH_GA_G.a3m","target_msa_report":"hpc_outputs/m6d_w2b_target_adaptive_targets/1FDH_GA/1FDH_GA_G.a3m.report.json"},"1FJG_FR":{"manifest":"configs/m6d_w2b_target_adaptive_fit_targets.json","manifest_sha256":"1459d29181ff0d2c1b5fafbf57b4e3f11e1cd872749f17fe951ece96e550ef14","target_fasta":"hpc_outputs/m6d_w2b_target_adaptive_targets/1FJG_FR/1FJG_FR_F.fasta","target_msa":"hpc_outputs/m6d_w2b_target_adaptive_targets/1FJG_FR/1FJG_FR_F.a3m","target_msa_report":"hpc_outputs/m6d_w2b_target_adaptive_targets/1FJG_FR/1FJG_FR_F.a3m.report.json"},"1FLT_WV":{"manifest":"configs/m6d_w2b_target_adaptive_fit_targets.json","manifest_sha256":"1459d29181ff0d2c1b5fafbf57b4e3f11e1cd872749f17fe951ece96e550ef14","target_fasta":"hpc_outputs/m6d_w2b_target_adaptive_targets/1FLT_WV/1FLT_WV_W.fasta","target_msa":"hpc_outputs/m6d_w2b_target_adaptive_targets/1FLT_WV/1FLT_WV_W.a3m","target_msa_report":"hpc_outputs/m6d_w2b_target_adaptive_targets/1FLT_WV/1FLT_WV_W.a3m.report.json"},"1FVC_DC":{"manifest":"configs/m6d_w2b_target_adaptive_fit_targets.json","manifest_sha256":"1459d29181ff0d2c1b5fafbf57b4e3f11e1cd872749f17fe951ece96e550ef14","target_fasta":"hpc_outputs/m6d_w2b_target_adaptive_targets/1FVC_DC/1FVC_DC_D.fasta","target_msa":"hpc_outputs/m6d_w2b_target_adaptive_targets/1FVC_DC/1FVC_DC_D.a3m","target_msa_report":"hpc_outputs/m6d_w2b_target_adaptive_targets/1FVC_DC/1FVC_DC_D.a3m.report.json"},"1FXK_CA":{"manifest":"configs/m6d_w2b_target_adaptive_fit_targets.json","manifest_sha256":"1459d29181ff0d2c1b5fafbf57b4e3f11e1cd872749f17fe951ece96e550ef14","target_fasta":"hpc_outputs/m6d_w2b_target_adaptive_targets/1FXK_CA/1FXK_CA_C.fasta","target_msa":"hpc_outputs/m6d_w2b_target_adaptive_targets/1FXK_CA/1FXK_CA_C.a3m","target_msa_report":"hpc_outputs/m6d_w2b_target_adaptive_targets/1FXK_CA/1FXK_CA_C.a3m.report.json"}}' 1FXK_CA 1F93_DC 1F66_AB 1FJG_FR 1FDH_GA 1FLT_WV 1F51_AE 1FVC_DC

# expected_input_prep_files
# If this plan runs on Cayuga, sync these paths back before rerunning --require-files.
# 1FXK_CA source_pdb: hpc_outputs/m6d_w2b_target_adaptive_sources/source_1FXK.pdb
# 1FXK_CA prepared_pdb: hpc_outputs/m6d_w2b_target_adaptive_targets/1FXK_CA/prepared_1FXK_CA.pdb
# 1FXK_CA prep_report: hpc_outputs/m6d_w2b_target_adaptive_targets/1FXK_CA/prepared_1FXK_CA.report.json
# 1FXK_CA target_fasta: hpc_outputs/m6d_w2b_target_adaptive_targets/1FXK_CA/1FXK_CA_C.fasta
# 1FXK_CA target_fasta_report: hpc_outputs/m6d_w2b_target_adaptive_targets/1FXK_CA/1FXK_CA_C.fasta.report.json
# 1FXK_CA target_msa: hpc_outputs/m6d_w2b_target_adaptive_targets/1FXK_CA/1FXK_CA_C.a3m
# 1FXK_CA target_msa_report: hpc_outputs/m6d_w2b_target_adaptive_targets/1FXK_CA/1FXK_CA_C.a3m.report.json
# 1F93_DC source_pdb: hpc_outputs/m6d_w2b_target_adaptive_sources/source_1F93.pdb
# 1F93_DC prepared_pdb: hpc_outputs/m6d_w2b_target_adaptive_targets/1F93_DC/prepared_1F93_DC.pdb
# 1F93_DC prep_report: hpc_outputs/m6d_w2b_target_adaptive_targets/1F93_DC/prepared_1F93_DC.report.json
# 1F93_DC target_fasta: hpc_outputs/m6d_w2b_target_adaptive_targets/1F93_DC/1F93_DC_D.fasta
# 1F93_DC target_fasta_report: hpc_outputs/m6d_w2b_target_adaptive_targets/1F93_DC/1F93_DC_D.fasta.report.json
# 1F93_DC target_msa: hpc_outputs/m6d_w2b_target_adaptive_targets/1F93_DC/1F93_DC_D.a3m
# 1F93_DC target_msa_report: hpc_outputs/m6d_w2b_target_adaptive_targets/1F93_DC/1F93_DC_D.a3m.report.json
# 1F66_AB source_pdb: hpc_outputs/m6d_w2b_target_adaptive_sources/source_1F66.pdb
# 1F66_AB prepared_pdb: hpc_outputs/m6d_w2b_target_adaptive_targets/1F66_AB/prepared_1F66_AB.pdb
# 1F66_AB prep_report: hpc_outputs/m6d_w2b_target_adaptive_targets/1F66_AB/prepared_1F66_AB.report.json
# 1F66_AB target_fasta: hpc_outputs/m6d_w2b_target_adaptive_targets/1F66_AB/1F66_AB_A.fasta
# 1F66_AB target_fasta_report: hpc_outputs/m6d_w2b_target_adaptive_targets/1F66_AB/1F66_AB_A.fasta.report.json
# 1F66_AB target_msa: hpc_outputs/m6d_w2b_target_adaptive_targets/1F66_AB/1F66_AB_A.a3m
# 1F66_AB target_msa_report: hpc_outputs/m6d_w2b_target_adaptive_targets/1F66_AB/1F66_AB_A.a3m.report.json
# 1FJG_FR source_pdb: hpc_outputs/m6d_w2b_target_adaptive_sources/source_1FJG.pdb
# 1FJG_FR prepared_pdb: hpc_outputs/m6d_w2b_target_adaptive_targets/1FJG_FR/prepared_1FJG_FR.pdb
# 1FJG_FR prep_report: hpc_outputs/m6d_w2b_target_adaptive_targets/1FJG_FR/prepared_1FJG_FR.report.json
# 1FJG_FR target_fasta: hpc_outputs/m6d_w2b_target_adaptive_targets/1FJG_FR/1FJG_FR_F.fasta
# 1FJG_FR target_fasta_report: hpc_outputs/m6d_w2b_target_adaptive_targets/1FJG_FR/1FJG_FR_F.fasta.report.json
# 1FJG_FR target_msa: hpc_outputs/m6d_w2b_target_adaptive_targets/1FJG_FR/1FJG_FR_F.a3m
# 1FJG_FR target_msa_report: hpc_outputs/m6d_w2b_target_adaptive_targets/1FJG_FR/1FJG_FR_F.a3m.report.json
# 1FDH_GA source_pdb: hpc_outputs/m6d_w2b_target_adaptive_sources/source_1FDH.pdb
# 1FDH_GA prepared_pdb: hpc_outputs/m6d_w2b_target_adaptive_targets/1FDH_GA/prepared_1FDH_GA.pdb
# 1FDH_GA prep_report: hpc_outputs/m6d_w2b_target_adaptive_targets/1FDH_GA/prepared_1FDH_GA.report.json
# 1FDH_GA target_fasta: hpc_outputs/m6d_w2b_target_adaptive_targets/1FDH_GA/1FDH_GA_G.fasta
# 1FDH_GA target_fasta_report: hpc_outputs/m6d_w2b_target_adaptive_targets/1FDH_GA/1FDH_GA_G.fasta.report.json
# 1FDH_GA target_msa: hpc_outputs/m6d_w2b_target_adaptive_targets/1FDH_GA/1FDH_GA_G.a3m
# 1FDH_GA target_msa_report: hpc_outputs/m6d_w2b_target_adaptive_targets/1FDH_GA/1FDH_GA_G.a3m.report.json
# 1FLT_WV source_pdb: hpc_outputs/m6d_w2b_target_adaptive_sources/source_1FLT.pdb
# 1FLT_WV prepared_pdb: hpc_outputs/m6d_w2b_target_adaptive_targets/1FLT_WV/prepared_1FLT_WV.pdb
# 1FLT_WV prep_report: hpc_outputs/m6d_w2b_target_adaptive_targets/1FLT_WV/prepared_1FLT_WV.report.json
# 1FLT_WV target_fasta: hpc_outputs/m6d_w2b_target_adaptive_targets/1FLT_WV/1FLT_WV_W.fasta
# 1FLT_WV target_fasta_report: hpc_outputs/m6d_w2b_target_adaptive_targets/1FLT_WV/1FLT_WV_W.fasta.report.json
# 1FLT_WV target_msa: hpc_outputs/m6d_w2b_target_adaptive_targets/1FLT_WV/1FLT_WV_W.a3m
# 1FLT_WV target_msa_report: hpc_outputs/m6d_w2b_target_adaptive_targets/1FLT_WV/1FLT_WV_W.a3m.report.json
# 1F51_AE source_pdb: hpc_outputs/m6d_w2b_target_adaptive_sources/source_1F51.pdb
# 1F51_AE prepared_pdb: hpc_outputs/m6d_w2b_target_adaptive_targets/1F51_AE/prepared_1F51_AE.pdb
# 1F51_AE prep_report: hpc_outputs/m6d_w2b_target_adaptive_targets/1F51_AE/prepared_1F51_AE.report.json
# 1F51_AE target_fasta: hpc_outputs/m6d_w2b_target_adaptive_targets/1F51_AE/1F51_AE_A.fasta
# 1F51_AE target_fasta_report: hpc_outputs/m6d_w2b_target_adaptive_targets/1F51_AE/1F51_AE_A.fasta.report.json
# 1F51_AE target_msa: hpc_outputs/m6d_w2b_target_adaptive_targets/1F51_AE/1F51_AE_A.a3m
# 1F51_AE target_msa_report: hpc_outputs/m6d_w2b_target_adaptive_targets/1F51_AE/1F51_AE_A.a3m.report.json
# 1FVC_DC source_pdb: hpc_outputs/m6d_w2b_target_adaptive_sources/source_1FVC.pdb
# 1FVC_DC prepared_pdb: hpc_outputs/m6d_w2b_target_adaptive_targets/1FVC_DC/prepared_1FVC_DC.pdb
# 1FVC_DC prep_report: hpc_outputs/m6d_w2b_target_adaptive_targets/1FVC_DC/prepared_1FVC_DC.report.json
# 1FVC_DC target_fasta: hpc_outputs/m6d_w2b_target_adaptive_targets/1FVC_DC/1FVC_DC_D.fasta
# 1FVC_DC target_fasta_report: hpc_outputs/m6d_w2b_target_adaptive_targets/1FVC_DC/1FVC_DC_D.fasta.report.json
# 1FVC_DC target_msa: hpc_outputs/m6d_w2b_target_adaptive_targets/1FVC_DC/1FVC_DC_D.a3m
# 1FVC_DC target_msa_report: hpc_outputs/m6d_w2b_target_adaptive_targets/1FVC_DC/1FVC_DC_D.a3m.report.json

# rerun_manifest_after_msa
# python -m bio_sfm_designer.experiments.complex_target_manifest --manifest configs/m6d_w2b_target_adaptive_fit_targets.json --require-files --min-targets 8 --min-contacts 1 --out results/m6d_w2b_target_adaptive_fit_manifest_schema.json
