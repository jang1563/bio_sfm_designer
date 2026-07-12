# M6c target-MSA precompute plan
# Run this before --require-files panel/scale readiness when target .a3m/report files are missing or stale.
set -euo pipefail
PYTHON_BIN="${BIO_SFM_PYTHON:-${ENV_PY:-python3}}"

# Optional: set TARGET_MSA_PRECOMPUTE_RECEIPT to append submitted/reused targets as JSONL.
if [ -n "${TARGET_MSA_PRECOMPUTE_RECEIPT:-}" ]; then
  mkdir -p "$(dirname "$TARGET_MSA_PRECOMPUTE_RECEIPT")"
fi
TARGET_MSA_PRECOMPUTE_MANIFEST=configs/m6d_w2c_fresh_targets.json
export TARGET_MSA_PRECOMPUTE_MANIFEST
TARGET_MSA_PRECOMPUTE_MANIFEST_SHA256_EXPECTED=94cae2712270ca3ef7d85357ce61ccf0ac9d0d8437077d543c20e3ac61d2eda2
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
TARGET_MSA_PRECOMPUTE_DRY_RUN_TARGETS='["1FR2_BA", "1F80_BC", "1EZV_XY", "1FFG_CD", "1FFK_HR", "1FQ9_CA", "1FYR_CD", "1F99_BA"]'
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

# 1FR2_BA
mkdir -p hpc_outputs/m6d_w2b_target_adaptive_sources hpc_outputs/m6d_w2b_target_adaptive_targets/1FR2_BA
if [ -s hpc_outputs/m6d_w2b_target_adaptive_sources/source_1FR2.pdb ]; then
  echo 'source PDB already exists: hpc_outputs/m6d_w2b_target_adaptive_sources/source_1FR2.pdb'
else
  curl -fsSL https://files.rcsb.org/download/1FR2.pdb -o hpc_outputs/m6d_w2b_target_adaptive_sources/source_1FR2.pdb
fi
if [ -s hpc_outputs/m6d_w2b_target_adaptive_targets/1FR2_BA/prepared_1FR2_BA.pdb ] && [ -s hpc_outputs/m6d_w2b_target_adaptive_targets/1FR2_BA/prepared_1FR2_BA.report.json ]; then
  echo 'prepared PDB already exists: hpc_outputs/m6d_w2b_target_adaptive_targets/1FR2_BA/prepared_1FR2_BA.pdb'
else
  "$PYTHON_BIN" hpc/prep_hetdimer.py --pdb hpc_outputs/m6d_w2b_target_adaptive_sources/source_1FR2.pdb --target-chain B --binder-chain A --out hpc_outputs/m6d_w2b_target_adaptive_targets/1FR2_BA/prepared_1FR2_BA.pdb --report hpc_outputs/m6d_w2b_target_adaptive_targets/1FR2_BA/prepared_1FR2_BA.report.json
fi
"$PYTHON_BIN" hpc/extract_chain_fasta.py --pdb hpc_outputs/m6d_w2b_target_adaptive_targets/1FR2_BA/prepared_1FR2_BA.pdb --chain B --id 1FR2_BA_B --out hpc_outputs/m6d_w2b_target_adaptive_targets/1FR2_BA/1FR2_BA_B.fasta --report hpc_outputs/m6d_w2b_target_adaptive_targets/1FR2_BA/1FR2_BA_B.fasta.report.json
if [ -s hpc_outputs/m6d_w2b_target_adaptive_targets/1FR2_BA/1FR2_BA_B.a3m ]; then
  echo 'target MSA exists; validating and refreshing report: hpc_outputs/m6d_w2b_target_adaptive_targets/1FR2_BA/1FR2_BA_B.a3m'
  "$PYTHON_BIN" hpc/precompute_boltz_target_msa.py --fasta hpc_outputs/m6d_w2b_target_adaptive_targets/1FR2_BA/1FR2_BA_B.fasta --out hpc_outputs/m6d_w2b_target_adaptive_targets/1FR2_BA/1FR2_BA_B.a3m --report hpc_outputs/m6d_w2b_target_adaptive_targets/1FR2_BA/1FR2_BA_B.a3m.report.json
  record_target_msa_precompute 1FR2_BA validated_existing '' hpc_outputs/m6d_w2b_target_adaptive_targets/1FR2_BA/1FR2_BA_B.fasta hpc_outputs/m6d_w2b_target_adaptive_targets/1FR2_BA/1FR2_BA_B.a3m hpc_outputs/m6d_w2b_target_adaptive_targets/1FR2_BA/1FR2_BA_B.a3m.report.json
else
  MSA_00_T_1FR2_BA=$(FASTA=hpc_outputs/m6d_w2b_target_adaptive_targets/1FR2_BA/1FR2_BA_B.fasta OUT=hpc_outputs/m6d_w2b_target_adaptive_targets/1FR2_BA/1FR2_BA_B.a3m REPORT=hpc_outputs/m6d_w2b_target_adaptive_targets/1FR2_BA/1FR2_BA_B.a3m.report.json sbatch --parsable hpc/run_precompute_boltz_target_msa.sbatch)
  require_target_msa_job_id 1FR2_BA "${MSA_00_T_1FR2_BA}"
  echo 'submitted target MSA job for 1FR2_BA: '"${MSA_00_T_1FR2_BA}"
  record_target_msa_precompute 1FR2_BA submitted "${MSA_00_T_1FR2_BA}" hpc_outputs/m6d_w2b_target_adaptive_targets/1FR2_BA/1FR2_BA_B.fasta hpc_outputs/m6d_w2b_target_adaptive_targets/1FR2_BA/1FR2_BA_B.a3m hpc_outputs/m6d_w2b_target_adaptive_targets/1FR2_BA/1FR2_BA_B.a3m.report.json
fi

# 1F80_BC
mkdir -p hpc_outputs/m6d_w2b_target_adaptive_sources hpc_outputs/m6d_w2b_target_adaptive_targets/1F80_BC
if [ -s hpc_outputs/m6d_w2b_target_adaptive_sources/source_1F80.pdb ]; then
  echo 'source PDB already exists: hpc_outputs/m6d_w2b_target_adaptive_sources/source_1F80.pdb'
else
  curl -fsSL https://files.rcsb.org/download/1F80.pdb -o hpc_outputs/m6d_w2b_target_adaptive_sources/source_1F80.pdb
fi
if [ -s hpc_outputs/m6d_w2b_target_adaptive_targets/1F80_BC/prepared_1F80_BC.pdb ] && [ -s hpc_outputs/m6d_w2b_target_adaptive_targets/1F80_BC/prepared_1F80_BC.report.json ]; then
  echo 'prepared PDB already exists: hpc_outputs/m6d_w2b_target_adaptive_targets/1F80_BC/prepared_1F80_BC.pdb'
else
  "$PYTHON_BIN" hpc/prep_hetdimer.py --pdb hpc_outputs/m6d_w2b_target_adaptive_sources/source_1F80.pdb --target-chain B --binder-chain C --out hpc_outputs/m6d_w2b_target_adaptive_targets/1F80_BC/prepared_1F80_BC.pdb --report hpc_outputs/m6d_w2b_target_adaptive_targets/1F80_BC/prepared_1F80_BC.report.json
fi
"$PYTHON_BIN" hpc/extract_chain_fasta.py --pdb hpc_outputs/m6d_w2b_target_adaptive_targets/1F80_BC/prepared_1F80_BC.pdb --chain B --id 1F80_BC_B --out hpc_outputs/m6d_w2b_target_adaptive_targets/1F80_BC/1F80_BC_B.fasta --report hpc_outputs/m6d_w2b_target_adaptive_targets/1F80_BC/1F80_BC_B.fasta.report.json
if [ -s hpc_outputs/m6d_w2b_target_adaptive_targets/1F80_BC/1F80_BC_B.a3m ]; then
  echo 'target MSA exists; validating and refreshing report: hpc_outputs/m6d_w2b_target_adaptive_targets/1F80_BC/1F80_BC_B.a3m'
  "$PYTHON_BIN" hpc/precompute_boltz_target_msa.py --fasta hpc_outputs/m6d_w2b_target_adaptive_targets/1F80_BC/1F80_BC_B.fasta --out hpc_outputs/m6d_w2b_target_adaptive_targets/1F80_BC/1F80_BC_B.a3m --report hpc_outputs/m6d_w2b_target_adaptive_targets/1F80_BC/1F80_BC_B.a3m.report.json
  record_target_msa_precompute 1F80_BC validated_existing '' hpc_outputs/m6d_w2b_target_adaptive_targets/1F80_BC/1F80_BC_B.fasta hpc_outputs/m6d_w2b_target_adaptive_targets/1F80_BC/1F80_BC_B.a3m hpc_outputs/m6d_w2b_target_adaptive_targets/1F80_BC/1F80_BC_B.a3m.report.json
else
  MSA_01_T_1F80_BC=$(FASTA=hpc_outputs/m6d_w2b_target_adaptive_targets/1F80_BC/1F80_BC_B.fasta OUT=hpc_outputs/m6d_w2b_target_adaptive_targets/1F80_BC/1F80_BC_B.a3m REPORT=hpc_outputs/m6d_w2b_target_adaptive_targets/1F80_BC/1F80_BC_B.a3m.report.json sbatch --parsable hpc/run_precompute_boltz_target_msa.sbatch)
  require_target_msa_job_id 1F80_BC "${MSA_01_T_1F80_BC}"
  echo 'submitted target MSA job for 1F80_BC: '"${MSA_01_T_1F80_BC}"
  record_target_msa_precompute 1F80_BC submitted "${MSA_01_T_1F80_BC}" hpc_outputs/m6d_w2b_target_adaptive_targets/1F80_BC/1F80_BC_B.fasta hpc_outputs/m6d_w2b_target_adaptive_targets/1F80_BC/1F80_BC_B.a3m hpc_outputs/m6d_w2b_target_adaptive_targets/1F80_BC/1F80_BC_B.a3m.report.json
fi

# 1EZV_XY
mkdir -p hpc_outputs/m6d_w2b_target_adaptive_sources hpc_outputs/m6d_w2b_target_adaptive_targets/1EZV_XY
if [ -s hpc_outputs/m6d_w2b_target_adaptive_sources/source_1EZV.pdb ]; then
  echo 'source PDB already exists: hpc_outputs/m6d_w2b_target_adaptive_sources/source_1EZV.pdb'
else
  curl -fsSL https://files.rcsb.org/download/1EZV.pdb -o hpc_outputs/m6d_w2b_target_adaptive_sources/source_1EZV.pdb
fi
if [ -s hpc_outputs/m6d_w2b_target_adaptive_targets/1EZV_XY/prepared_1EZV_XY.pdb ] && [ -s hpc_outputs/m6d_w2b_target_adaptive_targets/1EZV_XY/prepared_1EZV_XY.report.json ]; then
  echo 'prepared PDB already exists: hpc_outputs/m6d_w2b_target_adaptive_targets/1EZV_XY/prepared_1EZV_XY.pdb'
else
  "$PYTHON_BIN" hpc/prep_hetdimer.py --pdb hpc_outputs/m6d_w2b_target_adaptive_sources/source_1EZV.pdb --target-chain X --binder-chain Y --out hpc_outputs/m6d_w2b_target_adaptive_targets/1EZV_XY/prepared_1EZV_XY.pdb --report hpc_outputs/m6d_w2b_target_adaptive_targets/1EZV_XY/prepared_1EZV_XY.report.json
fi
"$PYTHON_BIN" hpc/extract_chain_fasta.py --pdb hpc_outputs/m6d_w2b_target_adaptive_targets/1EZV_XY/prepared_1EZV_XY.pdb --chain X --id 1EZV_XY_X --out hpc_outputs/m6d_w2b_target_adaptive_targets/1EZV_XY/1EZV_XY_X.fasta --report hpc_outputs/m6d_w2b_target_adaptive_targets/1EZV_XY/1EZV_XY_X.fasta.report.json
if [ -s hpc_outputs/m6d_w2b_target_adaptive_targets/1EZV_XY/1EZV_XY_X.a3m ]; then
  echo 'target MSA exists; validating and refreshing report: hpc_outputs/m6d_w2b_target_adaptive_targets/1EZV_XY/1EZV_XY_X.a3m'
  "$PYTHON_BIN" hpc/precompute_boltz_target_msa.py --fasta hpc_outputs/m6d_w2b_target_adaptive_targets/1EZV_XY/1EZV_XY_X.fasta --out hpc_outputs/m6d_w2b_target_adaptive_targets/1EZV_XY/1EZV_XY_X.a3m --report hpc_outputs/m6d_w2b_target_adaptive_targets/1EZV_XY/1EZV_XY_X.a3m.report.json
  record_target_msa_precompute 1EZV_XY validated_existing '' hpc_outputs/m6d_w2b_target_adaptive_targets/1EZV_XY/1EZV_XY_X.fasta hpc_outputs/m6d_w2b_target_adaptive_targets/1EZV_XY/1EZV_XY_X.a3m hpc_outputs/m6d_w2b_target_adaptive_targets/1EZV_XY/1EZV_XY_X.a3m.report.json
else
  MSA_02_T_1EZV_XY=$(FASTA=hpc_outputs/m6d_w2b_target_adaptive_targets/1EZV_XY/1EZV_XY_X.fasta OUT=hpc_outputs/m6d_w2b_target_adaptive_targets/1EZV_XY/1EZV_XY_X.a3m REPORT=hpc_outputs/m6d_w2b_target_adaptive_targets/1EZV_XY/1EZV_XY_X.a3m.report.json sbatch --parsable hpc/run_precompute_boltz_target_msa.sbatch)
  require_target_msa_job_id 1EZV_XY "${MSA_02_T_1EZV_XY}"
  echo 'submitted target MSA job for 1EZV_XY: '"${MSA_02_T_1EZV_XY}"
  record_target_msa_precompute 1EZV_XY submitted "${MSA_02_T_1EZV_XY}" hpc_outputs/m6d_w2b_target_adaptive_targets/1EZV_XY/1EZV_XY_X.fasta hpc_outputs/m6d_w2b_target_adaptive_targets/1EZV_XY/1EZV_XY_X.a3m hpc_outputs/m6d_w2b_target_adaptive_targets/1EZV_XY/1EZV_XY_X.a3m.report.json
fi

# 1FFG_CD
mkdir -p hpc_outputs/m6d_w2b_target_adaptive_sources hpc_outputs/m6d_w2b_target_adaptive_targets/1FFG_CD
if [ -s hpc_outputs/m6d_w2b_target_adaptive_sources/source_1FFG.pdb ]; then
  echo 'source PDB already exists: hpc_outputs/m6d_w2b_target_adaptive_sources/source_1FFG.pdb'
else
  curl -fsSL https://files.rcsb.org/download/1FFG.pdb -o hpc_outputs/m6d_w2b_target_adaptive_sources/source_1FFG.pdb
fi
if [ -s hpc_outputs/m6d_w2b_target_adaptive_targets/1FFG_CD/prepared_1FFG_CD.pdb ] && [ -s hpc_outputs/m6d_w2b_target_adaptive_targets/1FFG_CD/prepared_1FFG_CD.report.json ]; then
  echo 'prepared PDB already exists: hpc_outputs/m6d_w2b_target_adaptive_targets/1FFG_CD/prepared_1FFG_CD.pdb'
else
  "$PYTHON_BIN" hpc/prep_hetdimer.py --pdb hpc_outputs/m6d_w2b_target_adaptive_sources/source_1FFG.pdb --target-chain C --binder-chain D --out hpc_outputs/m6d_w2b_target_adaptive_targets/1FFG_CD/prepared_1FFG_CD.pdb --report hpc_outputs/m6d_w2b_target_adaptive_targets/1FFG_CD/prepared_1FFG_CD.report.json
fi
"$PYTHON_BIN" hpc/extract_chain_fasta.py --pdb hpc_outputs/m6d_w2b_target_adaptive_targets/1FFG_CD/prepared_1FFG_CD.pdb --chain C --id 1FFG_CD_C --out hpc_outputs/m6d_w2b_target_adaptive_targets/1FFG_CD/1FFG_CD_C.fasta --report hpc_outputs/m6d_w2b_target_adaptive_targets/1FFG_CD/1FFG_CD_C.fasta.report.json
if [ -s hpc_outputs/m6d_w2b_target_adaptive_targets/1FFG_CD/1FFG_CD_C.a3m ]; then
  echo 'target MSA exists; validating and refreshing report: hpc_outputs/m6d_w2b_target_adaptive_targets/1FFG_CD/1FFG_CD_C.a3m'
  "$PYTHON_BIN" hpc/precompute_boltz_target_msa.py --fasta hpc_outputs/m6d_w2b_target_adaptive_targets/1FFG_CD/1FFG_CD_C.fasta --out hpc_outputs/m6d_w2b_target_adaptive_targets/1FFG_CD/1FFG_CD_C.a3m --report hpc_outputs/m6d_w2b_target_adaptive_targets/1FFG_CD/1FFG_CD_C.a3m.report.json
  record_target_msa_precompute 1FFG_CD validated_existing '' hpc_outputs/m6d_w2b_target_adaptive_targets/1FFG_CD/1FFG_CD_C.fasta hpc_outputs/m6d_w2b_target_adaptive_targets/1FFG_CD/1FFG_CD_C.a3m hpc_outputs/m6d_w2b_target_adaptive_targets/1FFG_CD/1FFG_CD_C.a3m.report.json
else
  MSA_03_T_1FFG_CD=$(FASTA=hpc_outputs/m6d_w2b_target_adaptive_targets/1FFG_CD/1FFG_CD_C.fasta OUT=hpc_outputs/m6d_w2b_target_adaptive_targets/1FFG_CD/1FFG_CD_C.a3m REPORT=hpc_outputs/m6d_w2b_target_adaptive_targets/1FFG_CD/1FFG_CD_C.a3m.report.json sbatch --parsable hpc/run_precompute_boltz_target_msa.sbatch)
  require_target_msa_job_id 1FFG_CD "${MSA_03_T_1FFG_CD}"
  echo 'submitted target MSA job for 1FFG_CD: '"${MSA_03_T_1FFG_CD}"
  record_target_msa_precompute 1FFG_CD submitted "${MSA_03_T_1FFG_CD}" hpc_outputs/m6d_w2b_target_adaptive_targets/1FFG_CD/1FFG_CD_C.fasta hpc_outputs/m6d_w2b_target_adaptive_targets/1FFG_CD/1FFG_CD_C.a3m hpc_outputs/m6d_w2b_target_adaptive_targets/1FFG_CD/1FFG_CD_C.a3m.report.json
fi

# 1FFK_HR
mkdir -p hpc_outputs/m6d_w2b_target_adaptive_sources hpc_outputs/m6d_w2b_target_adaptive_targets/1FFK_HR
if [ -s hpc_outputs/m6d_w2b_target_adaptive_sources/source_1FFK.pdb ]; then
  echo 'source PDB already exists: hpc_outputs/m6d_w2b_target_adaptive_sources/source_1FFK.pdb'
else
  curl -fsSL https://files.rcsb.org/download/1FFK.pdb -o hpc_outputs/m6d_w2b_target_adaptive_sources/source_1FFK.pdb
fi
if [ -s hpc_outputs/m6d_w2b_target_adaptive_targets/1FFK_HR/prepared_1FFK_HR.pdb ] && [ -s hpc_outputs/m6d_w2b_target_adaptive_targets/1FFK_HR/prepared_1FFK_HR.report.json ]; then
  echo 'prepared PDB already exists: hpc_outputs/m6d_w2b_target_adaptive_targets/1FFK_HR/prepared_1FFK_HR.pdb'
else
  "$PYTHON_BIN" hpc/prep_hetdimer.py --pdb hpc_outputs/m6d_w2b_target_adaptive_sources/source_1FFK.pdb --target-chain H --binder-chain R --out hpc_outputs/m6d_w2b_target_adaptive_targets/1FFK_HR/prepared_1FFK_HR.pdb --report hpc_outputs/m6d_w2b_target_adaptive_targets/1FFK_HR/prepared_1FFK_HR.report.json
fi
"$PYTHON_BIN" hpc/extract_chain_fasta.py --pdb hpc_outputs/m6d_w2b_target_adaptive_targets/1FFK_HR/prepared_1FFK_HR.pdb --chain H --id 1FFK_HR_H --out hpc_outputs/m6d_w2b_target_adaptive_targets/1FFK_HR/1FFK_HR_H.fasta --report hpc_outputs/m6d_w2b_target_adaptive_targets/1FFK_HR/1FFK_HR_H.fasta.report.json
if [ -s hpc_outputs/m6d_w2b_target_adaptive_targets/1FFK_HR/1FFK_HR_H.a3m ]; then
  echo 'target MSA exists; validating and refreshing report: hpc_outputs/m6d_w2b_target_adaptive_targets/1FFK_HR/1FFK_HR_H.a3m'
  "$PYTHON_BIN" hpc/precompute_boltz_target_msa.py --fasta hpc_outputs/m6d_w2b_target_adaptive_targets/1FFK_HR/1FFK_HR_H.fasta --out hpc_outputs/m6d_w2b_target_adaptive_targets/1FFK_HR/1FFK_HR_H.a3m --report hpc_outputs/m6d_w2b_target_adaptive_targets/1FFK_HR/1FFK_HR_H.a3m.report.json
  record_target_msa_precompute 1FFK_HR validated_existing '' hpc_outputs/m6d_w2b_target_adaptive_targets/1FFK_HR/1FFK_HR_H.fasta hpc_outputs/m6d_w2b_target_adaptive_targets/1FFK_HR/1FFK_HR_H.a3m hpc_outputs/m6d_w2b_target_adaptive_targets/1FFK_HR/1FFK_HR_H.a3m.report.json
else
  MSA_04_T_1FFK_HR=$(FASTA=hpc_outputs/m6d_w2b_target_adaptive_targets/1FFK_HR/1FFK_HR_H.fasta OUT=hpc_outputs/m6d_w2b_target_adaptive_targets/1FFK_HR/1FFK_HR_H.a3m REPORT=hpc_outputs/m6d_w2b_target_adaptive_targets/1FFK_HR/1FFK_HR_H.a3m.report.json sbatch --parsable hpc/run_precompute_boltz_target_msa.sbatch)
  require_target_msa_job_id 1FFK_HR "${MSA_04_T_1FFK_HR}"
  echo 'submitted target MSA job for 1FFK_HR: '"${MSA_04_T_1FFK_HR}"
  record_target_msa_precompute 1FFK_HR submitted "${MSA_04_T_1FFK_HR}" hpc_outputs/m6d_w2b_target_adaptive_targets/1FFK_HR/1FFK_HR_H.fasta hpc_outputs/m6d_w2b_target_adaptive_targets/1FFK_HR/1FFK_HR_H.a3m hpc_outputs/m6d_w2b_target_adaptive_targets/1FFK_HR/1FFK_HR_H.a3m.report.json
fi

# 1FQ9_CA
mkdir -p hpc_outputs/m6d_w2b_target_adaptive_sources hpc_outputs/m6d_w2b_target_adaptive_targets/1FQ9_CA
if [ -s hpc_outputs/m6d_w2b_target_adaptive_sources/source_1FQ9.pdb ]; then
  echo 'source PDB already exists: hpc_outputs/m6d_w2b_target_adaptive_sources/source_1FQ9.pdb'
else
  curl -fsSL https://files.rcsb.org/download/1FQ9.pdb -o hpc_outputs/m6d_w2b_target_adaptive_sources/source_1FQ9.pdb
fi
if [ -s hpc_outputs/m6d_w2b_target_adaptive_targets/1FQ9_CA/prepared_1FQ9_CA.pdb ] && [ -s hpc_outputs/m6d_w2b_target_adaptive_targets/1FQ9_CA/prepared_1FQ9_CA.report.json ]; then
  echo 'prepared PDB already exists: hpc_outputs/m6d_w2b_target_adaptive_targets/1FQ9_CA/prepared_1FQ9_CA.pdb'
else
  "$PYTHON_BIN" hpc/prep_hetdimer.py --pdb hpc_outputs/m6d_w2b_target_adaptive_sources/source_1FQ9.pdb --target-chain C --binder-chain A --out hpc_outputs/m6d_w2b_target_adaptive_targets/1FQ9_CA/prepared_1FQ9_CA.pdb --report hpc_outputs/m6d_w2b_target_adaptive_targets/1FQ9_CA/prepared_1FQ9_CA.report.json
fi
"$PYTHON_BIN" hpc/extract_chain_fasta.py --pdb hpc_outputs/m6d_w2b_target_adaptive_targets/1FQ9_CA/prepared_1FQ9_CA.pdb --chain C --id 1FQ9_CA_C --out hpc_outputs/m6d_w2b_target_adaptive_targets/1FQ9_CA/1FQ9_CA_C.fasta --report hpc_outputs/m6d_w2b_target_adaptive_targets/1FQ9_CA/1FQ9_CA_C.fasta.report.json
if [ -s hpc_outputs/m6d_w2b_target_adaptive_targets/1FQ9_CA/1FQ9_CA_C.a3m ]; then
  echo 'target MSA exists; validating and refreshing report: hpc_outputs/m6d_w2b_target_adaptive_targets/1FQ9_CA/1FQ9_CA_C.a3m'
  "$PYTHON_BIN" hpc/precompute_boltz_target_msa.py --fasta hpc_outputs/m6d_w2b_target_adaptive_targets/1FQ9_CA/1FQ9_CA_C.fasta --out hpc_outputs/m6d_w2b_target_adaptive_targets/1FQ9_CA/1FQ9_CA_C.a3m --report hpc_outputs/m6d_w2b_target_adaptive_targets/1FQ9_CA/1FQ9_CA_C.a3m.report.json
  record_target_msa_precompute 1FQ9_CA validated_existing '' hpc_outputs/m6d_w2b_target_adaptive_targets/1FQ9_CA/1FQ9_CA_C.fasta hpc_outputs/m6d_w2b_target_adaptive_targets/1FQ9_CA/1FQ9_CA_C.a3m hpc_outputs/m6d_w2b_target_adaptive_targets/1FQ9_CA/1FQ9_CA_C.a3m.report.json
else
  MSA_05_T_1FQ9_CA=$(FASTA=hpc_outputs/m6d_w2b_target_adaptive_targets/1FQ9_CA/1FQ9_CA_C.fasta OUT=hpc_outputs/m6d_w2b_target_adaptive_targets/1FQ9_CA/1FQ9_CA_C.a3m REPORT=hpc_outputs/m6d_w2b_target_adaptive_targets/1FQ9_CA/1FQ9_CA_C.a3m.report.json sbatch --parsable hpc/run_precompute_boltz_target_msa.sbatch)
  require_target_msa_job_id 1FQ9_CA "${MSA_05_T_1FQ9_CA}"
  echo 'submitted target MSA job for 1FQ9_CA: '"${MSA_05_T_1FQ9_CA}"
  record_target_msa_precompute 1FQ9_CA submitted "${MSA_05_T_1FQ9_CA}" hpc_outputs/m6d_w2b_target_adaptive_targets/1FQ9_CA/1FQ9_CA_C.fasta hpc_outputs/m6d_w2b_target_adaptive_targets/1FQ9_CA/1FQ9_CA_C.a3m hpc_outputs/m6d_w2b_target_adaptive_targets/1FQ9_CA/1FQ9_CA_C.a3m.report.json
fi

# 1FYR_CD
mkdir -p hpc_outputs/m6d_w2b_target_adaptive_sources hpc_outputs/m6d_w2b_target_adaptive_targets/1FYR_CD
if [ -s hpc_outputs/m6d_w2b_target_adaptive_sources/source_1FYR.pdb ]; then
  echo 'source PDB already exists: hpc_outputs/m6d_w2b_target_adaptive_sources/source_1FYR.pdb'
else
  curl -fsSL https://files.rcsb.org/download/1FYR.pdb -o hpc_outputs/m6d_w2b_target_adaptive_sources/source_1FYR.pdb
fi
if [ -s hpc_outputs/m6d_w2b_target_adaptive_targets/1FYR_CD/prepared_1FYR_CD.pdb ] && [ -s hpc_outputs/m6d_w2b_target_adaptive_targets/1FYR_CD/prepared_1FYR_CD.report.json ]; then
  echo 'prepared PDB already exists: hpc_outputs/m6d_w2b_target_adaptive_targets/1FYR_CD/prepared_1FYR_CD.pdb'
else
  "$PYTHON_BIN" hpc/prep_hetdimer.py --pdb hpc_outputs/m6d_w2b_target_adaptive_sources/source_1FYR.pdb --target-chain C --binder-chain D --out hpc_outputs/m6d_w2b_target_adaptive_targets/1FYR_CD/prepared_1FYR_CD.pdb --report hpc_outputs/m6d_w2b_target_adaptive_targets/1FYR_CD/prepared_1FYR_CD.report.json
fi
"$PYTHON_BIN" hpc/extract_chain_fasta.py --pdb hpc_outputs/m6d_w2b_target_adaptive_targets/1FYR_CD/prepared_1FYR_CD.pdb --chain C --id 1FYR_CD_C --out hpc_outputs/m6d_w2b_target_adaptive_targets/1FYR_CD/1FYR_CD_C.fasta --report hpc_outputs/m6d_w2b_target_adaptive_targets/1FYR_CD/1FYR_CD_C.fasta.report.json
if [ -s hpc_outputs/m6d_w2b_target_adaptive_targets/1FYR_CD/1FYR_CD_C.a3m ]; then
  echo 'target MSA exists; validating and refreshing report: hpc_outputs/m6d_w2b_target_adaptive_targets/1FYR_CD/1FYR_CD_C.a3m'
  "$PYTHON_BIN" hpc/precompute_boltz_target_msa.py --fasta hpc_outputs/m6d_w2b_target_adaptive_targets/1FYR_CD/1FYR_CD_C.fasta --out hpc_outputs/m6d_w2b_target_adaptive_targets/1FYR_CD/1FYR_CD_C.a3m --report hpc_outputs/m6d_w2b_target_adaptive_targets/1FYR_CD/1FYR_CD_C.a3m.report.json
  record_target_msa_precompute 1FYR_CD validated_existing '' hpc_outputs/m6d_w2b_target_adaptive_targets/1FYR_CD/1FYR_CD_C.fasta hpc_outputs/m6d_w2b_target_adaptive_targets/1FYR_CD/1FYR_CD_C.a3m hpc_outputs/m6d_w2b_target_adaptive_targets/1FYR_CD/1FYR_CD_C.a3m.report.json
else
  MSA_06_T_1FYR_CD=$(FASTA=hpc_outputs/m6d_w2b_target_adaptive_targets/1FYR_CD/1FYR_CD_C.fasta OUT=hpc_outputs/m6d_w2b_target_adaptive_targets/1FYR_CD/1FYR_CD_C.a3m REPORT=hpc_outputs/m6d_w2b_target_adaptive_targets/1FYR_CD/1FYR_CD_C.a3m.report.json sbatch --parsable hpc/run_precompute_boltz_target_msa.sbatch)
  require_target_msa_job_id 1FYR_CD "${MSA_06_T_1FYR_CD}"
  echo 'submitted target MSA job for 1FYR_CD: '"${MSA_06_T_1FYR_CD}"
  record_target_msa_precompute 1FYR_CD submitted "${MSA_06_T_1FYR_CD}" hpc_outputs/m6d_w2b_target_adaptive_targets/1FYR_CD/1FYR_CD_C.fasta hpc_outputs/m6d_w2b_target_adaptive_targets/1FYR_CD/1FYR_CD_C.a3m hpc_outputs/m6d_w2b_target_adaptive_targets/1FYR_CD/1FYR_CD_C.a3m.report.json
fi

# 1F99_BA
mkdir -p hpc_outputs/m6d_w2b_target_adaptive_sources hpc_outputs/m6d_w2b_target_adaptive_targets/1F99_BA
if [ -s hpc_outputs/m6d_w2b_target_adaptive_sources/source_1F99.pdb ]; then
  echo 'source PDB already exists: hpc_outputs/m6d_w2b_target_adaptive_sources/source_1F99.pdb'
else
  curl -fsSL https://files.rcsb.org/download/1F99.pdb -o hpc_outputs/m6d_w2b_target_adaptive_sources/source_1F99.pdb
fi
if [ -s hpc_outputs/m6d_w2b_target_adaptive_targets/1F99_BA/prepared_1F99_BA.pdb ] && [ -s hpc_outputs/m6d_w2b_target_adaptive_targets/1F99_BA/prepared_1F99_BA.report.json ]; then
  echo 'prepared PDB already exists: hpc_outputs/m6d_w2b_target_adaptive_targets/1F99_BA/prepared_1F99_BA.pdb'
else
  "$PYTHON_BIN" hpc/prep_hetdimer.py --pdb hpc_outputs/m6d_w2b_target_adaptive_sources/source_1F99.pdb --target-chain B --binder-chain A --out hpc_outputs/m6d_w2b_target_adaptive_targets/1F99_BA/prepared_1F99_BA.pdb --report hpc_outputs/m6d_w2b_target_adaptive_targets/1F99_BA/prepared_1F99_BA.report.json
fi
"$PYTHON_BIN" hpc/extract_chain_fasta.py --pdb hpc_outputs/m6d_w2b_target_adaptive_targets/1F99_BA/prepared_1F99_BA.pdb --chain B --id 1F99_BA_B --out hpc_outputs/m6d_w2b_target_adaptive_targets/1F99_BA/1F99_BA_B.fasta --report hpc_outputs/m6d_w2b_target_adaptive_targets/1F99_BA/1F99_BA_B.fasta.report.json
if [ -s hpc_outputs/m6d_w2b_target_adaptive_targets/1F99_BA/1F99_BA_B.a3m ]; then
  echo 'target MSA exists; validating and refreshing report: hpc_outputs/m6d_w2b_target_adaptive_targets/1F99_BA/1F99_BA_B.a3m'
  "$PYTHON_BIN" hpc/precompute_boltz_target_msa.py --fasta hpc_outputs/m6d_w2b_target_adaptive_targets/1F99_BA/1F99_BA_B.fasta --out hpc_outputs/m6d_w2b_target_adaptive_targets/1F99_BA/1F99_BA_B.a3m --report hpc_outputs/m6d_w2b_target_adaptive_targets/1F99_BA/1F99_BA_B.a3m.report.json
  record_target_msa_precompute 1F99_BA validated_existing '' hpc_outputs/m6d_w2b_target_adaptive_targets/1F99_BA/1F99_BA_B.fasta hpc_outputs/m6d_w2b_target_adaptive_targets/1F99_BA/1F99_BA_B.a3m hpc_outputs/m6d_w2b_target_adaptive_targets/1F99_BA/1F99_BA_B.a3m.report.json
else
  MSA_07_T_1F99_BA=$(FASTA=hpc_outputs/m6d_w2b_target_adaptive_targets/1F99_BA/1F99_BA_B.fasta OUT=hpc_outputs/m6d_w2b_target_adaptive_targets/1F99_BA/1F99_BA_B.a3m REPORT=hpc_outputs/m6d_w2b_target_adaptive_targets/1F99_BA/1F99_BA_B.a3m.report.json sbatch --parsable hpc/run_precompute_boltz_target_msa.sbatch)
  require_target_msa_job_id 1F99_BA "${MSA_07_T_1F99_BA}"
  echo 'submitted target MSA job for 1F99_BA: '"${MSA_07_T_1F99_BA}"
  record_target_msa_precompute 1F99_BA submitted "${MSA_07_T_1F99_BA}" hpc_outputs/m6d_w2b_target_adaptive_targets/1F99_BA/1F99_BA_B.fasta hpc_outputs/m6d_w2b_target_adaptive_targets/1F99_BA/1F99_BA_B.a3m hpc_outputs/m6d_w2b_target_adaptive_targets/1F99_BA/1F99_BA_B.a3m.report.json
fi

validate_target_msa_precompute_receipt --expect-json '{"1EZV_XY":{"manifest":"configs/m6d_w2c_fresh_targets.json","manifest_sha256":"94cae2712270ca3ef7d85357ce61ccf0ac9d0d8437077d543c20e3ac61d2eda2","target_fasta":"hpc_outputs/m6d_w2b_target_adaptive_targets/1EZV_XY/1EZV_XY_X.fasta","target_msa":"hpc_outputs/m6d_w2b_target_adaptive_targets/1EZV_XY/1EZV_XY_X.a3m","target_msa_report":"hpc_outputs/m6d_w2b_target_adaptive_targets/1EZV_XY/1EZV_XY_X.a3m.report.json"},"1F80_BC":{"manifest":"configs/m6d_w2c_fresh_targets.json","manifest_sha256":"94cae2712270ca3ef7d85357ce61ccf0ac9d0d8437077d543c20e3ac61d2eda2","target_fasta":"hpc_outputs/m6d_w2b_target_adaptive_targets/1F80_BC/1F80_BC_B.fasta","target_msa":"hpc_outputs/m6d_w2b_target_adaptive_targets/1F80_BC/1F80_BC_B.a3m","target_msa_report":"hpc_outputs/m6d_w2b_target_adaptive_targets/1F80_BC/1F80_BC_B.a3m.report.json"},"1F99_BA":{"manifest":"configs/m6d_w2c_fresh_targets.json","manifest_sha256":"94cae2712270ca3ef7d85357ce61ccf0ac9d0d8437077d543c20e3ac61d2eda2","target_fasta":"hpc_outputs/m6d_w2b_target_adaptive_targets/1F99_BA/1F99_BA_B.fasta","target_msa":"hpc_outputs/m6d_w2b_target_adaptive_targets/1F99_BA/1F99_BA_B.a3m","target_msa_report":"hpc_outputs/m6d_w2b_target_adaptive_targets/1F99_BA/1F99_BA_B.a3m.report.json"},"1FFG_CD":{"manifest":"configs/m6d_w2c_fresh_targets.json","manifest_sha256":"94cae2712270ca3ef7d85357ce61ccf0ac9d0d8437077d543c20e3ac61d2eda2","target_fasta":"hpc_outputs/m6d_w2b_target_adaptive_targets/1FFG_CD/1FFG_CD_C.fasta","target_msa":"hpc_outputs/m6d_w2b_target_adaptive_targets/1FFG_CD/1FFG_CD_C.a3m","target_msa_report":"hpc_outputs/m6d_w2b_target_adaptive_targets/1FFG_CD/1FFG_CD_C.a3m.report.json"},"1FFK_HR":{"manifest":"configs/m6d_w2c_fresh_targets.json","manifest_sha256":"94cae2712270ca3ef7d85357ce61ccf0ac9d0d8437077d543c20e3ac61d2eda2","target_fasta":"hpc_outputs/m6d_w2b_target_adaptive_targets/1FFK_HR/1FFK_HR_H.fasta","target_msa":"hpc_outputs/m6d_w2b_target_adaptive_targets/1FFK_HR/1FFK_HR_H.a3m","target_msa_report":"hpc_outputs/m6d_w2b_target_adaptive_targets/1FFK_HR/1FFK_HR_H.a3m.report.json"},"1FQ9_CA":{"manifest":"configs/m6d_w2c_fresh_targets.json","manifest_sha256":"94cae2712270ca3ef7d85357ce61ccf0ac9d0d8437077d543c20e3ac61d2eda2","target_fasta":"hpc_outputs/m6d_w2b_target_adaptive_targets/1FQ9_CA/1FQ9_CA_C.fasta","target_msa":"hpc_outputs/m6d_w2b_target_adaptive_targets/1FQ9_CA/1FQ9_CA_C.a3m","target_msa_report":"hpc_outputs/m6d_w2b_target_adaptive_targets/1FQ9_CA/1FQ9_CA_C.a3m.report.json"},"1FR2_BA":{"manifest":"configs/m6d_w2c_fresh_targets.json","manifest_sha256":"94cae2712270ca3ef7d85357ce61ccf0ac9d0d8437077d543c20e3ac61d2eda2","target_fasta":"hpc_outputs/m6d_w2b_target_adaptive_targets/1FR2_BA/1FR2_BA_B.fasta","target_msa":"hpc_outputs/m6d_w2b_target_adaptive_targets/1FR2_BA/1FR2_BA_B.a3m","target_msa_report":"hpc_outputs/m6d_w2b_target_adaptive_targets/1FR2_BA/1FR2_BA_B.a3m.report.json"},"1FYR_CD":{"manifest":"configs/m6d_w2c_fresh_targets.json","manifest_sha256":"94cae2712270ca3ef7d85357ce61ccf0ac9d0d8437077d543c20e3ac61d2eda2","target_fasta":"hpc_outputs/m6d_w2b_target_adaptive_targets/1FYR_CD/1FYR_CD_C.fasta","target_msa":"hpc_outputs/m6d_w2b_target_adaptive_targets/1FYR_CD/1FYR_CD_C.a3m","target_msa_report":"hpc_outputs/m6d_w2b_target_adaptive_targets/1FYR_CD/1FYR_CD_C.a3m.report.json"}}' 1FR2_BA 1F80_BC 1EZV_XY 1FFG_CD 1FFK_HR 1FQ9_CA 1FYR_CD 1F99_BA

# expected_input_prep_files
# If this plan runs on Cayuga, sync these paths back before rerunning --require-files.
# 1FR2_BA source_pdb: hpc_outputs/m6d_w2b_target_adaptive_sources/source_1FR2.pdb
# 1FR2_BA prepared_pdb: hpc_outputs/m6d_w2b_target_adaptive_targets/1FR2_BA/prepared_1FR2_BA.pdb
# 1FR2_BA prep_report: hpc_outputs/m6d_w2b_target_adaptive_targets/1FR2_BA/prepared_1FR2_BA.report.json
# 1FR2_BA target_fasta: hpc_outputs/m6d_w2b_target_adaptive_targets/1FR2_BA/1FR2_BA_B.fasta
# 1FR2_BA target_fasta_report: hpc_outputs/m6d_w2b_target_adaptive_targets/1FR2_BA/1FR2_BA_B.fasta.report.json
# 1FR2_BA target_msa: hpc_outputs/m6d_w2b_target_adaptive_targets/1FR2_BA/1FR2_BA_B.a3m
# 1FR2_BA target_msa_report: hpc_outputs/m6d_w2b_target_adaptive_targets/1FR2_BA/1FR2_BA_B.a3m.report.json
# 1F80_BC source_pdb: hpc_outputs/m6d_w2b_target_adaptive_sources/source_1F80.pdb
# 1F80_BC prepared_pdb: hpc_outputs/m6d_w2b_target_adaptive_targets/1F80_BC/prepared_1F80_BC.pdb
# 1F80_BC prep_report: hpc_outputs/m6d_w2b_target_adaptive_targets/1F80_BC/prepared_1F80_BC.report.json
# 1F80_BC target_fasta: hpc_outputs/m6d_w2b_target_adaptive_targets/1F80_BC/1F80_BC_B.fasta
# 1F80_BC target_fasta_report: hpc_outputs/m6d_w2b_target_adaptive_targets/1F80_BC/1F80_BC_B.fasta.report.json
# 1F80_BC target_msa: hpc_outputs/m6d_w2b_target_adaptive_targets/1F80_BC/1F80_BC_B.a3m
# 1F80_BC target_msa_report: hpc_outputs/m6d_w2b_target_adaptive_targets/1F80_BC/1F80_BC_B.a3m.report.json
# 1EZV_XY source_pdb: hpc_outputs/m6d_w2b_target_adaptive_sources/source_1EZV.pdb
# 1EZV_XY prepared_pdb: hpc_outputs/m6d_w2b_target_adaptive_targets/1EZV_XY/prepared_1EZV_XY.pdb
# 1EZV_XY prep_report: hpc_outputs/m6d_w2b_target_adaptive_targets/1EZV_XY/prepared_1EZV_XY.report.json
# 1EZV_XY target_fasta: hpc_outputs/m6d_w2b_target_adaptive_targets/1EZV_XY/1EZV_XY_X.fasta
# 1EZV_XY target_fasta_report: hpc_outputs/m6d_w2b_target_adaptive_targets/1EZV_XY/1EZV_XY_X.fasta.report.json
# 1EZV_XY target_msa: hpc_outputs/m6d_w2b_target_adaptive_targets/1EZV_XY/1EZV_XY_X.a3m
# 1EZV_XY target_msa_report: hpc_outputs/m6d_w2b_target_adaptive_targets/1EZV_XY/1EZV_XY_X.a3m.report.json
# 1FFG_CD source_pdb: hpc_outputs/m6d_w2b_target_adaptive_sources/source_1FFG.pdb
# 1FFG_CD prepared_pdb: hpc_outputs/m6d_w2b_target_adaptive_targets/1FFG_CD/prepared_1FFG_CD.pdb
# 1FFG_CD prep_report: hpc_outputs/m6d_w2b_target_adaptive_targets/1FFG_CD/prepared_1FFG_CD.report.json
# 1FFG_CD target_fasta: hpc_outputs/m6d_w2b_target_adaptive_targets/1FFG_CD/1FFG_CD_C.fasta
# 1FFG_CD target_fasta_report: hpc_outputs/m6d_w2b_target_adaptive_targets/1FFG_CD/1FFG_CD_C.fasta.report.json
# 1FFG_CD target_msa: hpc_outputs/m6d_w2b_target_adaptive_targets/1FFG_CD/1FFG_CD_C.a3m
# 1FFG_CD target_msa_report: hpc_outputs/m6d_w2b_target_adaptive_targets/1FFG_CD/1FFG_CD_C.a3m.report.json
# 1FFK_HR source_pdb: hpc_outputs/m6d_w2b_target_adaptive_sources/source_1FFK.pdb
# 1FFK_HR prepared_pdb: hpc_outputs/m6d_w2b_target_adaptive_targets/1FFK_HR/prepared_1FFK_HR.pdb
# 1FFK_HR prep_report: hpc_outputs/m6d_w2b_target_adaptive_targets/1FFK_HR/prepared_1FFK_HR.report.json
# 1FFK_HR target_fasta: hpc_outputs/m6d_w2b_target_adaptive_targets/1FFK_HR/1FFK_HR_H.fasta
# 1FFK_HR target_fasta_report: hpc_outputs/m6d_w2b_target_adaptive_targets/1FFK_HR/1FFK_HR_H.fasta.report.json
# 1FFK_HR target_msa: hpc_outputs/m6d_w2b_target_adaptive_targets/1FFK_HR/1FFK_HR_H.a3m
# 1FFK_HR target_msa_report: hpc_outputs/m6d_w2b_target_adaptive_targets/1FFK_HR/1FFK_HR_H.a3m.report.json
# 1FQ9_CA source_pdb: hpc_outputs/m6d_w2b_target_adaptive_sources/source_1FQ9.pdb
# 1FQ9_CA prepared_pdb: hpc_outputs/m6d_w2b_target_adaptive_targets/1FQ9_CA/prepared_1FQ9_CA.pdb
# 1FQ9_CA prep_report: hpc_outputs/m6d_w2b_target_adaptive_targets/1FQ9_CA/prepared_1FQ9_CA.report.json
# 1FQ9_CA target_fasta: hpc_outputs/m6d_w2b_target_adaptive_targets/1FQ9_CA/1FQ9_CA_C.fasta
# 1FQ9_CA target_fasta_report: hpc_outputs/m6d_w2b_target_adaptive_targets/1FQ9_CA/1FQ9_CA_C.fasta.report.json
# 1FQ9_CA target_msa: hpc_outputs/m6d_w2b_target_adaptive_targets/1FQ9_CA/1FQ9_CA_C.a3m
# 1FQ9_CA target_msa_report: hpc_outputs/m6d_w2b_target_adaptive_targets/1FQ9_CA/1FQ9_CA_C.a3m.report.json
# 1FYR_CD source_pdb: hpc_outputs/m6d_w2b_target_adaptive_sources/source_1FYR.pdb
# 1FYR_CD prepared_pdb: hpc_outputs/m6d_w2b_target_adaptive_targets/1FYR_CD/prepared_1FYR_CD.pdb
# 1FYR_CD prep_report: hpc_outputs/m6d_w2b_target_adaptive_targets/1FYR_CD/prepared_1FYR_CD.report.json
# 1FYR_CD target_fasta: hpc_outputs/m6d_w2b_target_adaptive_targets/1FYR_CD/1FYR_CD_C.fasta
# 1FYR_CD target_fasta_report: hpc_outputs/m6d_w2b_target_adaptive_targets/1FYR_CD/1FYR_CD_C.fasta.report.json
# 1FYR_CD target_msa: hpc_outputs/m6d_w2b_target_adaptive_targets/1FYR_CD/1FYR_CD_C.a3m
# 1FYR_CD target_msa_report: hpc_outputs/m6d_w2b_target_adaptive_targets/1FYR_CD/1FYR_CD_C.a3m.report.json
# 1F99_BA source_pdb: hpc_outputs/m6d_w2b_target_adaptive_sources/source_1F99.pdb
# 1F99_BA prepared_pdb: hpc_outputs/m6d_w2b_target_adaptive_targets/1F99_BA/prepared_1F99_BA.pdb
# 1F99_BA prep_report: hpc_outputs/m6d_w2b_target_adaptive_targets/1F99_BA/prepared_1F99_BA.report.json
# 1F99_BA target_fasta: hpc_outputs/m6d_w2b_target_adaptive_targets/1F99_BA/1F99_BA_B.fasta
# 1F99_BA target_fasta_report: hpc_outputs/m6d_w2b_target_adaptive_targets/1F99_BA/1F99_BA_B.fasta.report.json
# 1F99_BA target_msa: hpc_outputs/m6d_w2b_target_adaptive_targets/1F99_BA/1F99_BA_B.a3m
# 1F99_BA target_msa_report: hpc_outputs/m6d_w2b_target_adaptive_targets/1F99_BA/1F99_BA_B.a3m.report.json

# rerun_manifest_after_msa
# python -m bio_sfm_designer.experiments.complex_target_manifest --manifest configs/m6d_w2c_fresh_targets.json --require-files --min-targets 8 --min-contacts 1 --out results/m6d_w2c_manifest_pre_msa.json
