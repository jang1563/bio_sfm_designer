# M6c target-MSA precompute plan
# Run this before --require-files panel/scale readiness when target .a3m/report files are missing or stale.
set -euo pipefail
PYTHON_BIN="${BIO_SFM_PYTHON:-${ENV_PY:-python3}}"

# Optional: set TARGET_MSA_PRECOMPUTE_RECEIPT to append submitted/reused targets as JSONL.
if [ -n "${TARGET_MSA_PRECOMPUTE_RECEIPT:-}" ]; then
  mkdir -p "$(dirname "$TARGET_MSA_PRECOMPUTE_RECEIPT")"
fi
TARGET_MSA_PRECOMPUTE_MANIFEST=configs/m6d_w3b_fresh_targets.json
export TARGET_MSA_PRECOMPUTE_MANIFEST
TARGET_MSA_PRECOMPUTE_MANIFEST_SHA256_EXPECTED=0e547c450f53e276fede5f1efef1405aa234ffc54f141ade82182425fa2929fc
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
TARGET_MSA_PRECOMPUTE_DRY_RUN_TARGETS='["1FSK_LJ", "1FSX_BA", "1FL7_DC", "1F2U_CD", "1FV1_BA", "1FN3_DC", "1FHJ_BA", "1F3V_BA"]'
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

# 1FSK_LJ
mkdir -p hpc_outputs/m6d_w2b_target_adaptive_sources hpc_outputs/m6d_w2b_target_adaptive_targets/1FSK_LJ
if [ -s hpc_outputs/m6d_w2b_target_adaptive_sources/source_1FSK.pdb ]; then
  echo 'source PDB already exists: hpc_outputs/m6d_w2b_target_adaptive_sources/source_1FSK.pdb'
else
  curl -fsSL https://files.rcsb.org/download/1FSK.pdb -o hpc_outputs/m6d_w2b_target_adaptive_sources/source_1FSK.pdb
fi
if [ -s hpc_outputs/m6d_w2b_target_adaptive_targets/1FSK_LJ/prepared_1FSK_LJ.pdb ] && [ -s hpc_outputs/m6d_w2b_target_adaptive_targets/1FSK_LJ/prepared_1FSK_LJ.report.json ]; then
  echo 'prepared PDB already exists: hpc_outputs/m6d_w2b_target_adaptive_targets/1FSK_LJ/prepared_1FSK_LJ.pdb'
else
  "$PYTHON_BIN" hpc/prep_hetdimer.py --pdb hpc_outputs/m6d_w2b_target_adaptive_sources/source_1FSK.pdb --target-chain L --binder-chain J --out hpc_outputs/m6d_w2b_target_adaptive_targets/1FSK_LJ/prepared_1FSK_LJ.pdb --report hpc_outputs/m6d_w2b_target_adaptive_targets/1FSK_LJ/prepared_1FSK_LJ.report.json
fi
"$PYTHON_BIN" hpc/extract_chain_fasta.py --pdb hpc_outputs/m6d_w2b_target_adaptive_targets/1FSK_LJ/prepared_1FSK_LJ.pdb --chain L --id 1FSK_LJ_L --out hpc_outputs/m6d_w2b_target_adaptive_targets/1FSK_LJ/1FSK_LJ_L.fasta --report hpc_outputs/m6d_w2b_target_adaptive_targets/1FSK_LJ/1FSK_LJ_L.fasta.report.json
if [ -s hpc_outputs/m6d_w2b_target_adaptive_targets/1FSK_LJ/1FSK_LJ_L.a3m ]; then
  echo 'target MSA exists; validating and refreshing report: hpc_outputs/m6d_w2b_target_adaptive_targets/1FSK_LJ/1FSK_LJ_L.a3m'
  "$PYTHON_BIN" hpc/precompute_boltz_target_msa.py --fasta hpc_outputs/m6d_w2b_target_adaptive_targets/1FSK_LJ/1FSK_LJ_L.fasta --out hpc_outputs/m6d_w2b_target_adaptive_targets/1FSK_LJ/1FSK_LJ_L.a3m --report hpc_outputs/m6d_w2b_target_adaptive_targets/1FSK_LJ/1FSK_LJ_L.a3m.report.json
  record_target_msa_precompute 1FSK_LJ validated_existing '' hpc_outputs/m6d_w2b_target_adaptive_targets/1FSK_LJ/1FSK_LJ_L.fasta hpc_outputs/m6d_w2b_target_adaptive_targets/1FSK_LJ/1FSK_LJ_L.a3m hpc_outputs/m6d_w2b_target_adaptive_targets/1FSK_LJ/1FSK_LJ_L.a3m.report.json
else
  MSA_00_T_1FSK_LJ=$(FASTA=hpc_outputs/m6d_w2b_target_adaptive_targets/1FSK_LJ/1FSK_LJ_L.fasta OUT=hpc_outputs/m6d_w2b_target_adaptive_targets/1FSK_LJ/1FSK_LJ_L.a3m REPORT=hpc_outputs/m6d_w2b_target_adaptive_targets/1FSK_LJ/1FSK_LJ_L.a3m.report.json sbatch --parsable hpc/run_precompute_boltz_target_msa.sbatch)
  require_target_msa_job_id 1FSK_LJ "${MSA_00_T_1FSK_LJ}"
  echo 'submitted target MSA job for 1FSK_LJ: '"${MSA_00_T_1FSK_LJ}"
  record_target_msa_precompute 1FSK_LJ submitted "${MSA_00_T_1FSK_LJ}" hpc_outputs/m6d_w2b_target_adaptive_targets/1FSK_LJ/1FSK_LJ_L.fasta hpc_outputs/m6d_w2b_target_adaptive_targets/1FSK_LJ/1FSK_LJ_L.a3m hpc_outputs/m6d_w2b_target_adaptive_targets/1FSK_LJ/1FSK_LJ_L.a3m.report.json
fi

# 1FSX_BA
mkdir -p hpc_outputs/m6d_w2b_target_adaptive_sources hpc_outputs/m6d_w2b_target_adaptive_targets/1FSX_BA
if [ -s hpc_outputs/m6d_w2b_target_adaptive_sources/source_1FSX.pdb ]; then
  echo 'source PDB already exists: hpc_outputs/m6d_w2b_target_adaptive_sources/source_1FSX.pdb'
else
  curl -fsSL https://files.rcsb.org/download/1FSX.pdb -o hpc_outputs/m6d_w2b_target_adaptive_sources/source_1FSX.pdb
fi
if [ -s hpc_outputs/m6d_w2b_target_adaptive_targets/1FSX_BA/prepared_1FSX_BA.pdb ] && [ -s hpc_outputs/m6d_w2b_target_adaptive_targets/1FSX_BA/prepared_1FSX_BA.report.json ]; then
  echo 'prepared PDB already exists: hpc_outputs/m6d_w2b_target_adaptive_targets/1FSX_BA/prepared_1FSX_BA.pdb'
else
  "$PYTHON_BIN" hpc/prep_hetdimer.py --pdb hpc_outputs/m6d_w2b_target_adaptive_sources/source_1FSX.pdb --target-chain B --binder-chain A --out hpc_outputs/m6d_w2b_target_adaptive_targets/1FSX_BA/prepared_1FSX_BA.pdb --report hpc_outputs/m6d_w2b_target_adaptive_targets/1FSX_BA/prepared_1FSX_BA.report.json
fi
"$PYTHON_BIN" hpc/extract_chain_fasta.py --pdb hpc_outputs/m6d_w2b_target_adaptive_targets/1FSX_BA/prepared_1FSX_BA.pdb --chain B --id 1FSX_BA_B --out hpc_outputs/m6d_w2b_target_adaptive_targets/1FSX_BA/1FSX_BA_B.fasta --report hpc_outputs/m6d_w2b_target_adaptive_targets/1FSX_BA/1FSX_BA_B.fasta.report.json
if [ -s hpc_outputs/m6d_w2b_target_adaptive_targets/1FSX_BA/1FSX_BA_B.a3m ]; then
  echo 'target MSA exists; validating and refreshing report: hpc_outputs/m6d_w2b_target_adaptive_targets/1FSX_BA/1FSX_BA_B.a3m'
  "$PYTHON_BIN" hpc/precompute_boltz_target_msa.py --fasta hpc_outputs/m6d_w2b_target_adaptive_targets/1FSX_BA/1FSX_BA_B.fasta --out hpc_outputs/m6d_w2b_target_adaptive_targets/1FSX_BA/1FSX_BA_B.a3m --report hpc_outputs/m6d_w2b_target_adaptive_targets/1FSX_BA/1FSX_BA_B.a3m.report.json
  record_target_msa_precompute 1FSX_BA validated_existing '' hpc_outputs/m6d_w2b_target_adaptive_targets/1FSX_BA/1FSX_BA_B.fasta hpc_outputs/m6d_w2b_target_adaptive_targets/1FSX_BA/1FSX_BA_B.a3m hpc_outputs/m6d_w2b_target_adaptive_targets/1FSX_BA/1FSX_BA_B.a3m.report.json
else
  MSA_01_T_1FSX_BA=$(FASTA=hpc_outputs/m6d_w2b_target_adaptive_targets/1FSX_BA/1FSX_BA_B.fasta OUT=hpc_outputs/m6d_w2b_target_adaptive_targets/1FSX_BA/1FSX_BA_B.a3m REPORT=hpc_outputs/m6d_w2b_target_adaptive_targets/1FSX_BA/1FSX_BA_B.a3m.report.json sbatch --parsable hpc/run_precompute_boltz_target_msa.sbatch)
  require_target_msa_job_id 1FSX_BA "${MSA_01_T_1FSX_BA}"
  echo 'submitted target MSA job for 1FSX_BA: '"${MSA_01_T_1FSX_BA}"
  record_target_msa_precompute 1FSX_BA submitted "${MSA_01_T_1FSX_BA}" hpc_outputs/m6d_w2b_target_adaptive_targets/1FSX_BA/1FSX_BA_B.fasta hpc_outputs/m6d_w2b_target_adaptive_targets/1FSX_BA/1FSX_BA_B.a3m hpc_outputs/m6d_w2b_target_adaptive_targets/1FSX_BA/1FSX_BA_B.a3m.report.json
fi

# 1FL7_DC
mkdir -p hpc_outputs/m6d_w2b_target_adaptive_sources hpc_outputs/m6d_w2b_target_adaptive_targets/1FL7_DC
if [ -s hpc_outputs/m6d_w2b_target_adaptive_sources/source_1FL7.pdb ]; then
  echo 'source PDB already exists: hpc_outputs/m6d_w2b_target_adaptive_sources/source_1FL7.pdb'
else
  curl -fsSL https://files.rcsb.org/download/1FL7.pdb -o hpc_outputs/m6d_w2b_target_adaptive_sources/source_1FL7.pdb
fi
if [ -s hpc_outputs/m6d_w2b_target_adaptive_targets/1FL7_DC/prepared_1FL7_DC.pdb ] && [ -s hpc_outputs/m6d_w2b_target_adaptive_targets/1FL7_DC/prepared_1FL7_DC.report.json ]; then
  echo 'prepared PDB already exists: hpc_outputs/m6d_w2b_target_adaptive_targets/1FL7_DC/prepared_1FL7_DC.pdb'
else
  "$PYTHON_BIN" hpc/prep_hetdimer.py --pdb hpc_outputs/m6d_w2b_target_adaptive_sources/source_1FL7.pdb --target-chain D --binder-chain C --out hpc_outputs/m6d_w2b_target_adaptive_targets/1FL7_DC/prepared_1FL7_DC.pdb --report hpc_outputs/m6d_w2b_target_adaptive_targets/1FL7_DC/prepared_1FL7_DC.report.json
fi
"$PYTHON_BIN" hpc/extract_chain_fasta.py --pdb hpc_outputs/m6d_w2b_target_adaptive_targets/1FL7_DC/prepared_1FL7_DC.pdb --chain D --id 1FL7_DC_D --out hpc_outputs/m6d_w2b_target_adaptive_targets/1FL7_DC/1FL7_DC_D.fasta --report hpc_outputs/m6d_w2b_target_adaptive_targets/1FL7_DC/1FL7_DC_D.fasta.report.json
if [ -s hpc_outputs/m6d_w2b_target_adaptive_targets/1FL7_DC/1FL7_DC_D.a3m ]; then
  echo 'target MSA exists; validating and refreshing report: hpc_outputs/m6d_w2b_target_adaptive_targets/1FL7_DC/1FL7_DC_D.a3m'
  "$PYTHON_BIN" hpc/precompute_boltz_target_msa.py --fasta hpc_outputs/m6d_w2b_target_adaptive_targets/1FL7_DC/1FL7_DC_D.fasta --out hpc_outputs/m6d_w2b_target_adaptive_targets/1FL7_DC/1FL7_DC_D.a3m --report hpc_outputs/m6d_w2b_target_adaptive_targets/1FL7_DC/1FL7_DC_D.a3m.report.json
  record_target_msa_precompute 1FL7_DC validated_existing '' hpc_outputs/m6d_w2b_target_adaptive_targets/1FL7_DC/1FL7_DC_D.fasta hpc_outputs/m6d_w2b_target_adaptive_targets/1FL7_DC/1FL7_DC_D.a3m hpc_outputs/m6d_w2b_target_adaptive_targets/1FL7_DC/1FL7_DC_D.a3m.report.json
else
  MSA_02_T_1FL7_DC=$(FASTA=hpc_outputs/m6d_w2b_target_adaptive_targets/1FL7_DC/1FL7_DC_D.fasta OUT=hpc_outputs/m6d_w2b_target_adaptive_targets/1FL7_DC/1FL7_DC_D.a3m REPORT=hpc_outputs/m6d_w2b_target_adaptive_targets/1FL7_DC/1FL7_DC_D.a3m.report.json sbatch --parsable hpc/run_precompute_boltz_target_msa.sbatch)
  require_target_msa_job_id 1FL7_DC "${MSA_02_T_1FL7_DC}"
  echo 'submitted target MSA job for 1FL7_DC: '"${MSA_02_T_1FL7_DC}"
  record_target_msa_precompute 1FL7_DC submitted "${MSA_02_T_1FL7_DC}" hpc_outputs/m6d_w2b_target_adaptive_targets/1FL7_DC/1FL7_DC_D.fasta hpc_outputs/m6d_w2b_target_adaptive_targets/1FL7_DC/1FL7_DC_D.a3m hpc_outputs/m6d_w2b_target_adaptive_targets/1FL7_DC/1FL7_DC_D.a3m.report.json
fi

# 1F2U_CD
mkdir -p hpc_outputs/m6d_w2b_target_adaptive_sources hpc_outputs/m6d_w2b_target_adaptive_targets/1F2U_CD
if [ -s hpc_outputs/m6d_w2b_target_adaptive_sources/source_1F2U.pdb ]; then
  echo 'source PDB already exists: hpc_outputs/m6d_w2b_target_adaptive_sources/source_1F2U.pdb'
else
  curl -fsSL https://files.rcsb.org/download/1F2U.pdb -o hpc_outputs/m6d_w2b_target_adaptive_sources/source_1F2U.pdb
fi
if [ -s hpc_outputs/m6d_w2b_target_adaptive_targets/1F2U_CD/prepared_1F2U_CD.pdb ] && [ -s hpc_outputs/m6d_w2b_target_adaptive_targets/1F2U_CD/prepared_1F2U_CD.report.json ]; then
  echo 'prepared PDB already exists: hpc_outputs/m6d_w2b_target_adaptive_targets/1F2U_CD/prepared_1F2U_CD.pdb'
else
  "$PYTHON_BIN" hpc/prep_hetdimer.py --pdb hpc_outputs/m6d_w2b_target_adaptive_sources/source_1F2U.pdb --target-chain C --binder-chain D --out hpc_outputs/m6d_w2b_target_adaptive_targets/1F2U_CD/prepared_1F2U_CD.pdb --report hpc_outputs/m6d_w2b_target_adaptive_targets/1F2U_CD/prepared_1F2U_CD.report.json
fi
"$PYTHON_BIN" hpc/extract_chain_fasta.py --pdb hpc_outputs/m6d_w2b_target_adaptive_targets/1F2U_CD/prepared_1F2U_CD.pdb --chain C --id 1F2U_CD_C --out hpc_outputs/m6d_w2b_target_adaptive_targets/1F2U_CD/1F2U_CD_C.fasta --report hpc_outputs/m6d_w2b_target_adaptive_targets/1F2U_CD/1F2U_CD_C.fasta.report.json
if [ -s hpc_outputs/m6d_w2b_target_adaptive_targets/1F2U_CD/1F2U_CD_C.a3m ]; then
  echo 'target MSA exists; validating and refreshing report: hpc_outputs/m6d_w2b_target_adaptive_targets/1F2U_CD/1F2U_CD_C.a3m'
  "$PYTHON_BIN" hpc/precompute_boltz_target_msa.py --fasta hpc_outputs/m6d_w2b_target_adaptive_targets/1F2U_CD/1F2U_CD_C.fasta --out hpc_outputs/m6d_w2b_target_adaptive_targets/1F2U_CD/1F2U_CD_C.a3m --report hpc_outputs/m6d_w2b_target_adaptive_targets/1F2U_CD/1F2U_CD_C.a3m.report.json
  record_target_msa_precompute 1F2U_CD validated_existing '' hpc_outputs/m6d_w2b_target_adaptive_targets/1F2U_CD/1F2U_CD_C.fasta hpc_outputs/m6d_w2b_target_adaptive_targets/1F2U_CD/1F2U_CD_C.a3m hpc_outputs/m6d_w2b_target_adaptive_targets/1F2U_CD/1F2U_CD_C.a3m.report.json
else
  MSA_03_T_1F2U_CD=$(FASTA=hpc_outputs/m6d_w2b_target_adaptive_targets/1F2U_CD/1F2U_CD_C.fasta OUT=hpc_outputs/m6d_w2b_target_adaptive_targets/1F2U_CD/1F2U_CD_C.a3m REPORT=hpc_outputs/m6d_w2b_target_adaptive_targets/1F2U_CD/1F2U_CD_C.a3m.report.json sbatch --parsable hpc/run_precompute_boltz_target_msa.sbatch)
  require_target_msa_job_id 1F2U_CD "${MSA_03_T_1F2U_CD}"
  echo 'submitted target MSA job for 1F2U_CD: '"${MSA_03_T_1F2U_CD}"
  record_target_msa_precompute 1F2U_CD submitted "${MSA_03_T_1F2U_CD}" hpc_outputs/m6d_w2b_target_adaptive_targets/1F2U_CD/1F2U_CD_C.fasta hpc_outputs/m6d_w2b_target_adaptive_targets/1F2U_CD/1F2U_CD_C.a3m hpc_outputs/m6d_w2b_target_adaptive_targets/1F2U_CD/1F2U_CD_C.a3m.report.json
fi

# 1FV1_BA
mkdir -p hpc_outputs/m6d_w2b_target_adaptive_sources hpc_outputs/m6d_w2b_target_adaptive_targets/1FV1_BA
if [ -s hpc_outputs/m6d_w2b_target_adaptive_sources/source_1FV1.pdb ]; then
  echo 'source PDB already exists: hpc_outputs/m6d_w2b_target_adaptive_sources/source_1FV1.pdb'
else
  curl -fsSL https://files.rcsb.org/download/1FV1.pdb -o hpc_outputs/m6d_w2b_target_adaptive_sources/source_1FV1.pdb
fi
if [ -s hpc_outputs/m6d_w2b_target_adaptive_targets/1FV1_BA/prepared_1FV1_BA.pdb ] && [ -s hpc_outputs/m6d_w2b_target_adaptive_targets/1FV1_BA/prepared_1FV1_BA.report.json ]; then
  echo 'prepared PDB already exists: hpc_outputs/m6d_w2b_target_adaptive_targets/1FV1_BA/prepared_1FV1_BA.pdb'
else
  "$PYTHON_BIN" hpc/prep_hetdimer.py --pdb hpc_outputs/m6d_w2b_target_adaptive_sources/source_1FV1.pdb --target-chain B --binder-chain A --out hpc_outputs/m6d_w2b_target_adaptive_targets/1FV1_BA/prepared_1FV1_BA.pdb --report hpc_outputs/m6d_w2b_target_adaptive_targets/1FV1_BA/prepared_1FV1_BA.report.json
fi
"$PYTHON_BIN" hpc/extract_chain_fasta.py --pdb hpc_outputs/m6d_w2b_target_adaptive_targets/1FV1_BA/prepared_1FV1_BA.pdb --chain B --id 1FV1_BA_B --out hpc_outputs/m6d_w2b_target_adaptive_targets/1FV1_BA/1FV1_BA_B.fasta --report hpc_outputs/m6d_w2b_target_adaptive_targets/1FV1_BA/1FV1_BA_B.fasta.report.json
if [ -s hpc_outputs/m6d_w2b_target_adaptive_targets/1FV1_BA/1FV1_BA_B.a3m ]; then
  echo 'target MSA exists; validating and refreshing report: hpc_outputs/m6d_w2b_target_adaptive_targets/1FV1_BA/1FV1_BA_B.a3m'
  "$PYTHON_BIN" hpc/precompute_boltz_target_msa.py --fasta hpc_outputs/m6d_w2b_target_adaptive_targets/1FV1_BA/1FV1_BA_B.fasta --out hpc_outputs/m6d_w2b_target_adaptive_targets/1FV1_BA/1FV1_BA_B.a3m --report hpc_outputs/m6d_w2b_target_adaptive_targets/1FV1_BA/1FV1_BA_B.a3m.report.json
  record_target_msa_precompute 1FV1_BA validated_existing '' hpc_outputs/m6d_w2b_target_adaptive_targets/1FV1_BA/1FV1_BA_B.fasta hpc_outputs/m6d_w2b_target_adaptive_targets/1FV1_BA/1FV1_BA_B.a3m hpc_outputs/m6d_w2b_target_adaptive_targets/1FV1_BA/1FV1_BA_B.a3m.report.json
else
  MSA_04_T_1FV1_BA=$(FASTA=hpc_outputs/m6d_w2b_target_adaptive_targets/1FV1_BA/1FV1_BA_B.fasta OUT=hpc_outputs/m6d_w2b_target_adaptive_targets/1FV1_BA/1FV1_BA_B.a3m REPORT=hpc_outputs/m6d_w2b_target_adaptive_targets/1FV1_BA/1FV1_BA_B.a3m.report.json sbatch --parsable hpc/run_precompute_boltz_target_msa.sbatch)
  require_target_msa_job_id 1FV1_BA "${MSA_04_T_1FV1_BA}"
  echo 'submitted target MSA job for 1FV1_BA: '"${MSA_04_T_1FV1_BA}"
  record_target_msa_precompute 1FV1_BA submitted "${MSA_04_T_1FV1_BA}" hpc_outputs/m6d_w2b_target_adaptive_targets/1FV1_BA/1FV1_BA_B.fasta hpc_outputs/m6d_w2b_target_adaptive_targets/1FV1_BA/1FV1_BA_B.a3m hpc_outputs/m6d_w2b_target_adaptive_targets/1FV1_BA/1FV1_BA_B.a3m.report.json
fi

# 1FN3_DC
mkdir -p hpc_outputs/m6d_w2b_target_adaptive_sources hpc_outputs/m6d_w2b_target_adaptive_targets/1FN3_DC
if [ -s hpc_outputs/m6d_w2b_target_adaptive_sources/source_1FN3.pdb ]; then
  echo 'source PDB already exists: hpc_outputs/m6d_w2b_target_adaptive_sources/source_1FN3.pdb'
else
  curl -fsSL https://files.rcsb.org/download/1FN3.pdb -o hpc_outputs/m6d_w2b_target_adaptive_sources/source_1FN3.pdb
fi
if [ -s hpc_outputs/m6d_w2b_target_adaptive_targets/1FN3_DC/prepared_1FN3_DC.pdb ] && [ -s hpc_outputs/m6d_w2b_target_adaptive_targets/1FN3_DC/prepared_1FN3_DC.report.json ]; then
  echo 'prepared PDB already exists: hpc_outputs/m6d_w2b_target_adaptive_targets/1FN3_DC/prepared_1FN3_DC.pdb'
else
  "$PYTHON_BIN" hpc/prep_hetdimer.py --pdb hpc_outputs/m6d_w2b_target_adaptive_sources/source_1FN3.pdb --target-chain D --binder-chain C --out hpc_outputs/m6d_w2b_target_adaptive_targets/1FN3_DC/prepared_1FN3_DC.pdb --report hpc_outputs/m6d_w2b_target_adaptive_targets/1FN3_DC/prepared_1FN3_DC.report.json
fi
"$PYTHON_BIN" hpc/extract_chain_fasta.py --pdb hpc_outputs/m6d_w2b_target_adaptive_targets/1FN3_DC/prepared_1FN3_DC.pdb --chain D --id 1FN3_DC_D --out hpc_outputs/m6d_w2b_target_adaptive_targets/1FN3_DC/1FN3_DC_D.fasta --report hpc_outputs/m6d_w2b_target_adaptive_targets/1FN3_DC/1FN3_DC_D.fasta.report.json
if [ -s hpc_outputs/m6d_w2b_target_adaptive_targets/1FN3_DC/1FN3_DC_D.a3m ]; then
  echo 'target MSA exists; validating and refreshing report: hpc_outputs/m6d_w2b_target_adaptive_targets/1FN3_DC/1FN3_DC_D.a3m'
  "$PYTHON_BIN" hpc/precompute_boltz_target_msa.py --fasta hpc_outputs/m6d_w2b_target_adaptive_targets/1FN3_DC/1FN3_DC_D.fasta --out hpc_outputs/m6d_w2b_target_adaptive_targets/1FN3_DC/1FN3_DC_D.a3m --report hpc_outputs/m6d_w2b_target_adaptive_targets/1FN3_DC/1FN3_DC_D.a3m.report.json
  record_target_msa_precompute 1FN3_DC validated_existing '' hpc_outputs/m6d_w2b_target_adaptive_targets/1FN3_DC/1FN3_DC_D.fasta hpc_outputs/m6d_w2b_target_adaptive_targets/1FN3_DC/1FN3_DC_D.a3m hpc_outputs/m6d_w2b_target_adaptive_targets/1FN3_DC/1FN3_DC_D.a3m.report.json
else
  MSA_05_T_1FN3_DC=$(FASTA=hpc_outputs/m6d_w2b_target_adaptive_targets/1FN3_DC/1FN3_DC_D.fasta OUT=hpc_outputs/m6d_w2b_target_adaptive_targets/1FN3_DC/1FN3_DC_D.a3m REPORT=hpc_outputs/m6d_w2b_target_adaptive_targets/1FN3_DC/1FN3_DC_D.a3m.report.json sbatch --parsable hpc/run_precompute_boltz_target_msa.sbatch)
  require_target_msa_job_id 1FN3_DC "${MSA_05_T_1FN3_DC}"
  echo 'submitted target MSA job for 1FN3_DC: '"${MSA_05_T_1FN3_DC}"
  record_target_msa_precompute 1FN3_DC submitted "${MSA_05_T_1FN3_DC}" hpc_outputs/m6d_w2b_target_adaptive_targets/1FN3_DC/1FN3_DC_D.fasta hpc_outputs/m6d_w2b_target_adaptive_targets/1FN3_DC/1FN3_DC_D.a3m hpc_outputs/m6d_w2b_target_adaptive_targets/1FN3_DC/1FN3_DC_D.a3m.report.json
fi

# 1FHJ_BA
mkdir -p hpc_outputs/m6d_w2b_target_adaptive_sources hpc_outputs/m6d_w2b_target_adaptive_targets/1FHJ_BA
if [ -s hpc_outputs/m6d_w2b_target_adaptive_sources/source_1FHJ.pdb ]; then
  echo 'source PDB already exists: hpc_outputs/m6d_w2b_target_adaptive_sources/source_1FHJ.pdb'
else
  curl -fsSL https://files.rcsb.org/download/1FHJ.pdb -o hpc_outputs/m6d_w2b_target_adaptive_sources/source_1FHJ.pdb
fi
if [ -s hpc_outputs/m6d_w2b_target_adaptive_targets/1FHJ_BA/prepared_1FHJ_BA.pdb ] && [ -s hpc_outputs/m6d_w2b_target_adaptive_targets/1FHJ_BA/prepared_1FHJ_BA.report.json ]; then
  echo 'prepared PDB already exists: hpc_outputs/m6d_w2b_target_adaptive_targets/1FHJ_BA/prepared_1FHJ_BA.pdb'
else
  "$PYTHON_BIN" hpc/prep_hetdimer.py --pdb hpc_outputs/m6d_w2b_target_adaptive_sources/source_1FHJ.pdb --target-chain B --binder-chain A --out hpc_outputs/m6d_w2b_target_adaptive_targets/1FHJ_BA/prepared_1FHJ_BA.pdb --report hpc_outputs/m6d_w2b_target_adaptive_targets/1FHJ_BA/prepared_1FHJ_BA.report.json
fi
"$PYTHON_BIN" hpc/extract_chain_fasta.py --pdb hpc_outputs/m6d_w2b_target_adaptive_targets/1FHJ_BA/prepared_1FHJ_BA.pdb --chain B --id 1FHJ_BA_B --out hpc_outputs/m6d_w2b_target_adaptive_targets/1FHJ_BA/1FHJ_BA_B.fasta --report hpc_outputs/m6d_w2b_target_adaptive_targets/1FHJ_BA/1FHJ_BA_B.fasta.report.json
if [ -s hpc_outputs/m6d_w2b_target_adaptive_targets/1FHJ_BA/1FHJ_BA_B.a3m ]; then
  echo 'target MSA exists; validating and refreshing report: hpc_outputs/m6d_w2b_target_adaptive_targets/1FHJ_BA/1FHJ_BA_B.a3m'
  "$PYTHON_BIN" hpc/precompute_boltz_target_msa.py --fasta hpc_outputs/m6d_w2b_target_adaptive_targets/1FHJ_BA/1FHJ_BA_B.fasta --out hpc_outputs/m6d_w2b_target_adaptive_targets/1FHJ_BA/1FHJ_BA_B.a3m --report hpc_outputs/m6d_w2b_target_adaptive_targets/1FHJ_BA/1FHJ_BA_B.a3m.report.json
  record_target_msa_precompute 1FHJ_BA validated_existing '' hpc_outputs/m6d_w2b_target_adaptive_targets/1FHJ_BA/1FHJ_BA_B.fasta hpc_outputs/m6d_w2b_target_adaptive_targets/1FHJ_BA/1FHJ_BA_B.a3m hpc_outputs/m6d_w2b_target_adaptive_targets/1FHJ_BA/1FHJ_BA_B.a3m.report.json
else
  MSA_06_T_1FHJ_BA=$(FASTA=hpc_outputs/m6d_w2b_target_adaptive_targets/1FHJ_BA/1FHJ_BA_B.fasta OUT=hpc_outputs/m6d_w2b_target_adaptive_targets/1FHJ_BA/1FHJ_BA_B.a3m REPORT=hpc_outputs/m6d_w2b_target_adaptive_targets/1FHJ_BA/1FHJ_BA_B.a3m.report.json sbatch --parsable hpc/run_precompute_boltz_target_msa.sbatch)
  require_target_msa_job_id 1FHJ_BA "${MSA_06_T_1FHJ_BA}"
  echo 'submitted target MSA job for 1FHJ_BA: '"${MSA_06_T_1FHJ_BA}"
  record_target_msa_precompute 1FHJ_BA submitted "${MSA_06_T_1FHJ_BA}" hpc_outputs/m6d_w2b_target_adaptive_targets/1FHJ_BA/1FHJ_BA_B.fasta hpc_outputs/m6d_w2b_target_adaptive_targets/1FHJ_BA/1FHJ_BA_B.a3m hpc_outputs/m6d_w2b_target_adaptive_targets/1FHJ_BA/1FHJ_BA_B.a3m.report.json
fi

# 1F3V_BA
mkdir -p hpc_outputs/m6d_w2b_target_adaptive_sources hpc_outputs/m6d_w2b_target_adaptive_targets/1F3V_BA
if [ -s hpc_outputs/m6d_w2b_target_adaptive_sources/source_1F3V.pdb ]; then
  echo 'source PDB already exists: hpc_outputs/m6d_w2b_target_adaptive_sources/source_1F3V.pdb'
else
  curl -fsSL https://files.rcsb.org/download/1F3V.pdb -o hpc_outputs/m6d_w2b_target_adaptive_sources/source_1F3V.pdb
fi
if [ -s hpc_outputs/m6d_w2b_target_adaptive_targets/1F3V_BA/prepared_1F3V_BA.pdb ] && [ -s hpc_outputs/m6d_w2b_target_adaptive_targets/1F3V_BA/prepared_1F3V_BA.report.json ]; then
  echo 'prepared PDB already exists: hpc_outputs/m6d_w2b_target_adaptive_targets/1F3V_BA/prepared_1F3V_BA.pdb'
else
  "$PYTHON_BIN" hpc/prep_hetdimer.py --pdb hpc_outputs/m6d_w2b_target_adaptive_sources/source_1F3V.pdb --target-chain B --binder-chain A --out hpc_outputs/m6d_w2b_target_adaptive_targets/1F3V_BA/prepared_1F3V_BA.pdb --report hpc_outputs/m6d_w2b_target_adaptive_targets/1F3V_BA/prepared_1F3V_BA.report.json
fi
"$PYTHON_BIN" hpc/extract_chain_fasta.py --pdb hpc_outputs/m6d_w2b_target_adaptive_targets/1F3V_BA/prepared_1F3V_BA.pdb --chain B --id 1F3V_BA_B --out hpc_outputs/m6d_w2b_target_adaptive_targets/1F3V_BA/1F3V_BA_B.fasta --report hpc_outputs/m6d_w2b_target_adaptive_targets/1F3V_BA/1F3V_BA_B.fasta.report.json
if [ -s hpc_outputs/m6d_w2b_target_adaptive_targets/1F3V_BA/1F3V_BA_B.a3m ]; then
  echo 'target MSA exists; validating and refreshing report: hpc_outputs/m6d_w2b_target_adaptive_targets/1F3V_BA/1F3V_BA_B.a3m'
  "$PYTHON_BIN" hpc/precompute_boltz_target_msa.py --fasta hpc_outputs/m6d_w2b_target_adaptive_targets/1F3V_BA/1F3V_BA_B.fasta --out hpc_outputs/m6d_w2b_target_adaptive_targets/1F3V_BA/1F3V_BA_B.a3m --report hpc_outputs/m6d_w2b_target_adaptive_targets/1F3V_BA/1F3V_BA_B.a3m.report.json
  record_target_msa_precompute 1F3V_BA validated_existing '' hpc_outputs/m6d_w2b_target_adaptive_targets/1F3V_BA/1F3V_BA_B.fasta hpc_outputs/m6d_w2b_target_adaptive_targets/1F3V_BA/1F3V_BA_B.a3m hpc_outputs/m6d_w2b_target_adaptive_targets/1F3V_BA/1F3V_BA_B.a3m.report.json
else
  MSA_07_T_1F3V_BA=$(FASTA=hpc_outputs/m6d_w2b_target_adaptive_targets/1F3V_BA/1F3V_BA_B.fasta OUT=hpc_outputs/m6d_w2b_target_adaptive_targets/1F3V_BA/1F3V_BA_B.a3m REPORT=hpc_outputs/m6d_w2b_target_adaptive_targets/1F3V_BA/1F3V_BA_B.a3m.report.json sbatch --parsable hpc/run_precompute_boltz_target_msa.sbatch)
  require_target_msa_job_id 1F3V_BA "${MSA_07_T_1F3V_BA}"
  echo 'submitted target MSA job for 1F3V_BA: '"${MSA_07_T_1F3V_BA}"
  record_target_msa_precompute 1F3V_BA submitted "${MSA_07_T_1F3V_BA}" hpc_outputs/m6d_w2b_target_adaptive_targets/1F3V_BA/1F3V_BA_B.fasta hpc_outputs/m6d_w2b_target_adaptive_targets/1F3V_BA/1F3V_BA_B.a3m hpc_outputs/m6d_w2b_target_adaptive_targets/1F3V_BA/1F3V_BA_B.a3m.report.json
fi

validate_target_msa_precompute_receipt --expect-json '{"1F2U_CD":{"manifest":"configs/m6d_w3b_fresh_targets.json","manifest_sha256":"0e547c450f53e276fede5f1efef1405aa234ffc54f141ade82182425fa2929fc","target_fasta":"hpc_outputs/m6d_w2b_target_adaptive_targets/1F2U_CD/1F2U_CD_C.fasta","target_msa":"hpc_outputs/m6d_w2b_target_adaptive_targets/1F2U_CD/1F2U_CD_C.a3m","target_msa_report":"hpc_outputs/m6d_w2b_target_adaptive_targets/1F2U_CD/1F2U_CD_C.a3m.report.json"},"1F3V_BA":{"manifest":"configs/m6d_w3b_fresh_targets.json","manifest_sha256":"0e547c450f53e276fede5f1efef1405aa234ffc54f141ade82182425fa2929fc","target_fasta":"hpc_outputs/m6d_w2b_target_adaptive_targets/1F3V_BA/1F3V_BA_B.fasta","target_msa":"hpc_outputs/m6d_w2b_target_adaptive_targets/1F3V_BA/1F3V_BA_B.a3m","target_msa_report":"hpc_outputs/m6d_w2b_target_adaptive_targets/1F3V_BA/1F3V_BA_B.a3m.report.json"},"1FHJ_BA":{"manifest":"configs/m6d_w3b_fresh_targets.json","manifest_sha256":"0e547c450f53e276fede5f1efef1405aa234ffc54f141ade82182425fa2929fc","target_fasta":"hpc_outputs/m6d_w2b_target_adaptive_targets/1FHJ_BA/1FHJ_BA_B.fasta","target_msa":"hpc_outputs/m6d_w2b_target_adaptive_targets/1FHJ_BA/1FHJ_BA_B.a3m","target_msa_report":"hpc_outputs/m6d_w2b_target_adaptive_targets/1FHJ_BA/1FHJ_BA_B.a3m.report.json"},"1FL7_DC":{"manifest":"configs/m6d_w3b_fresh_targets.json","manifest_sha256":"0e547c450f53e276fede5f1efef1405aa234ffc54f141ade82182425fa2929fc","target_fasta":"hpc_outputs/m6d_w2b_target_adaptive_targets/1FL7_DC/1FL7_DC_D.fasta","target_msa":"hpc_outputs/m6d_w2b_target_adaptive_targets/1FL7_DC/1FL7_DC_D.a3m","target_msa_report":"hpc_outputs/m6d_w2b_target_adaptive_targets/1FL7_DC/1FL7_DC_D.a3m.report.json"},"1FN3_DC":{"manifest":"configs/m6d_w3b_fresh_targets.json","manifest_sha256":"0e547c450f53e276fede5f1efef1405aa234ffc54f141ade82182425fa2929fc","target_fasta":"hpc_outputs/m6d_w2b_target_adaptive_targets/1FN3_DC/1FN3_DC_D.fasta","target_msa":"hpc_outputs/m6d_w2b_target_adaptive_targets/1FN3_DC/1FN3_DC_D.a3m","target_msa_report":"hpc_outputs/m6d_w2b_target_adaptive_targets/1FN3_DC/1FN3_DC_D.a3m.report.json"},"1FSK_LJ":{"manifest":"configs/m6d_w3b_fresh_targets.json","manifest_sha256":"0e547c450f53e276fede5f1efef1405aa234ffc54f141ade82182425fa2929fc","target_fasta":"hpc_outputs/m6d_w2b_target_adaptive_targets/1FSK_LJ/1FSK_LJ_L.fasta","target_msa":"hpc_outputs/m6d_w2b_target_adaptive_targets/1FSK_LJ/1FSK_LJ_L.a3m","target_msa_report":"hpc_outputs/m6d_w2b_target_adaptive_targets/1FSK_LJ/1FSK_LJ_L.a3m.report.json"},"1FSX_BA":{"manifest":"configs/m6d_w3b_fresh_targets.json","manifest_sha256":"0e547c450f53e276fede5f1efef1405aa234ffc54f141ade82182425fa2929fc","target_fasta":"hpc_outputs/m6d_w2b_target_adaptive_targets/1FSX_BA/1FSX_BA_B.fasta","target_msa":"hpc_outputs/m6d_w2b_target_adaptive_targets/1FSX_BA/1FSX_BA_B.a3m","target_msa_report":"hpc_outputs/m6d_w2b_target_adaptive_targets/1FSX_BA/1FSX_BA_B.a3m.report.json"},"1FV1_BA":{"manifest":"configs/m6d_w3b_fresh_targets.json","manifest_sha256":"0e547c450f53e276fede5f1efef1405aa234ffc54f141ade82182425fa2929fc","target_fasta":"hpc_outputs/m6d_w2b_target_adaptive_targets/1FV1_BA/1FV1_BA_B.fasta","target_msa":"hpc_outputs/m6d_w2b_target_adaptive_targets/1FV1_BA/1FV1_BA_B.a3m","target_msa_report":"hpc_outputs/m6d_w2b_target_adaptive_targets/1FV1_BA/1FV1_BA_B.a3m.report.json"}}' 1FSK_LJ 1FSX_BA 1FL7_DC 1F2U_CD 1FV1_BA 1FN3_DC 1FHJ_BA 1F3V_BA

# expected_input_prep_files
# If this plan runs on Cayuga, sync these paths back before rerunning --require-files.
# 1FSK_LJ source_pdb: hpc_outputs/m6d_w2b_target_adaptive_sources/source_1FSK.pdb
# 1FSK_LJ prepared_pdb: hpc_outputs/m6d_w2b_target_adaptive_targets/1FSK_LJ/prepared_1FSK_LJ.pdb
# 1FSK_LJ prep_report: hpc_outputs/m6d_w2b_target_adaptive_targets/1FSK_LJ/prepared_1FSK_LJ.report.json
# 1FSK_LJ target_fasta: hpc_outputs/m6d_w2b_target_adaptive_targets/1FSK_LJ/1FSK_LJ_L.fasta
# 1FSK_LJ target_fasta_report: hpc_outputs/m6d_w2b_target_adaptive_targets/1FSK_LJ/1FSK_LJ_L.fasta.report.json
# 1FSK_LJ target_msa: hpc_outputs/m6d_w2b_target_adaptive_targets/1FSK_LJ/1FSK_LJ_L.a3m
# 1FSK_LJ target_msa_report: hpc_outputs/m6d_w2b_target_adaptive_targets/1FSK_LJ/1FSK_LJ_L.a3m.report.json
# 1FSX_BA source_pdb: hpc_outputs/m6d_w2b_target_adaptive_sources/source_1FSX.pdb
# 1FSX_BA prepared_pdb: hpc_outputs/m6d_w2b_target_adaptive_targets/1FSX_BA/prepared_1FSX_BA.pdb
# 1FSX_BA prep_report: hpc_outputs/m6d_w2b_target_adaptive_targets/1FSX_BA/prepared_1FSX_BA.report.json
# 1FSX_BA target_fasta: hpc_outputs/m6d_w2b_target_adaptive_targets/1FSX_BA/1FSX_BA_B.fasta
# 1FSX_BA target_fasta_report: hpc_outputs/m6d_w2b_target_adaptive_targets/1FSX_BA/1FSX_BA_B.fasta.report.json
# 1FSX_BA target_msa: hpc_outputs/m6d_w2b_target_adaptive_targets/1FSX_BA/1FSX_BA_B.a3m
# 1FSX_BA target_msa_report: hpc_outputs/m6d_w2b_target_adaptive_targets/1FSX_BA/1FSX_BA_B.a3m.report.json
# 1FL7_DC source_pdb: hpc_outputs/m6d_w2b_target_adaptive_sources/source_1FL7.pdb
# 1FL7_DC prepared_pdb: hpc_outputs/m6d_w2b_target_adaptive_targets/1FL7_DC/prepared_1FL7_DC.pdb
# 1FL7_DC prep_report: hpc_outputs/m6d_w2b_target_adaptive_targets/1FL7_DC/prepared_1FL7_DC.report.json
# 1FL7_DC target_fasta: hpc_outputs/m6d_w2b_target_adaptive_targets/1FL7_DC/1FL7_DC_D.fasta
# 1FL7_DC target_fasta_report: hpc_outputs/m6d_w2b_target_adaptive_targets/1FL7_DC/1FL7_DC_D.fasta.report.json
# 1FL7_DC target_msa: hpc_outputs/m6d_w2b_target_adaptive_targets/1FL7_DC/1FL7_DC_D.a3m
# 1FL7_DC target_msa_report: hpc_outputs/m6d_w2b_target_adaptive_targets/1FL7_DC/1FL7_DC_D.a3m.report.json
# 1F2U_CD source_pdb: hpc_outputs/m6d_w2b_target_adaptive_sources/source_1F2U.pdb
# 1F2U_CD prepared_pdb: hpc_outputs/m6d_w2b_target_adaptive_targets/1F2U_CD/prepared_1F2U_CD.pdb
# 1F2U_CD prep_report: hpc_outputs/m6d_w2b_target_adaptive_targets/1F2U_CD/prepared_1F2U_CD.report.json
# 1F2U_CD target_fasta: hpc_outputs/m6d_w2b_target_adaptive_targets/1F2U_CD/1F2U_CD_C.fasta
# 1F2U_CD target_fasta_report: hpc_outputs/m6d_w2b_target_adaptive_targets/1F2U_CD/1F2U_CD_C.fasta.report.json
# 1F2U_CD target_msa: hpc_outputs/m6d_w2b_target_adaptive_targets/1F2U_CD/1F2U_CD_C.a3m
# 1F2U_CD target_msa_report: hpc_outputs/m6d_w2b_target_adaptive_targets/1F2U_CD/1F2U_CD_C.a3m.report.json
# 1FV1_BA source_pdb: hpc_outputs/m6d_w2b_target_adaptive_sources/source_1FV1.pdb
# 1FV1_BA prepared_pdb: hpc_outputs/m6d_w2b_target_adaptive_targets/1FV1_BA/prepared_1FV1_BA.pdb
# 1FV1_BA prep_report: hpc_outputs/m6d_w2b_target_adaptive_targets/1FV1_BA/prepared_1FV1_BA.report.json
# 1FV1_BA target_fasta: hpc_outputs/m6d_w2b_target_adaptive_targets/1FV1_BA/1FV1_BA_B.fasta
# 1FV1_BA target_fasta_report: hpc_outputs/m6d_w2b_target_adaptive_targets/1FV1_BA/1FV1_BA_B.fasta.report.json
# 1FV1_BA target_msa: hpc_outputs/m6d_w2b_target_adaptive_targets/1FV1_BA/1FV1_BA_B.a3m
# 1FV1_BA target_msa_report: hpc_outputs/m6d_w2b_target_adaptive_targets/1FV1_BA/1FV1_BA_B.a3m.report.json
# 1FN3_DC source_pdb: hpc_outputs/m6d_w2b_target_adaptive_sources/source_1FN3.pdb
# 1FN3_DC prepared_pdb: hpc_outputs/m6d_w2b_target_adaptive_targets/1FN3_DC/prepared_1FN3_DC.pdb
# 1FN3_DC prep_report: hpc_outputs/m6d_w2b_target_adaptive_targets/1FN3_DC/prepared_1FN3_DC.report.json
# 1FN3_DC target_fasta: hpc_outputs/m6d_w2b_target_adaptive_targets/1FN3_DC/1FN3_DC_D.fasta
# 1FN3_DC target_fasta_report: hpc_outputs/m6d_w2b_target_adaptive_targets/1FN3_DC/1FN3_DC_D.fasta.report.json
# 1FN3_DC target_msa: hpc_outputs/m6d_w2b_target_adaptive_targets/1FN3_DC/1FN3_DC_D.a3m
# 1FN3_DC target_msa_report: hpc_outputs/m6d_w2b_target_adaptive_targets/1FN3_DC/1FN3_DC_D.a3m.report.json
# 1FHJ_BA source_pdb: hpc_outputs/m6d_w2b_target_adaptive_sources/source_1FHJ.pdb
# 1FHJ_BA prepared_pdb: hpc_outputs/m6d_w2b_target_adaptive_targets/1FHJ_BA/prepared_1FHJ_BA.pdb
# 1FHJ_BA prep_report: hpc_outputs/m6d_w2b_target_adaptive_targets/1FHJ_BA/prepared_1FHJ_BA.report.json
# 1FHJ_BA target_fasta: hpc_outputs/m6d_w2b_target_adaptive_targets/1FHJ_BA/1FHJ_BA_B.fasta
# 1FHJ_BA target_fasta_report: hpc_outputs/m6d_w2b_target_adaptive_targets/1FHJ_BA/1FHJ_BA_B.fasta.report.json
# 1FHJ_BA target_msa: hpc_outputs/m6d_w2b_target_adaptive_targets/1FHJ_BA/1FHJ_BA_B.a3m
# 1FHJ_BA target_msa_report: hpc_outputs/m6d_w2b_target_adaptive_targets/1FHJ_BA/1FHJ_BA_B.a3m.report.json
# 1F3V_BA source_pdb: hpc_outputs/m6d_w2b_target_adaptive_sources/source_1F3V.pdb
# 1F3V_BA prepared_pdb: hpc_outputs/m6d_w2b_target_adaptive_targets/1F3V_BA/prepared_1F3V_BA.pdb
# 1F3V_BA prep_report: hpc_outputs/m6d_w2b_target_adaptive_targets/1F3V_BA/prepared_1F3V_BA.report.json
# 1F3V_BA target_fasta: hpc_outputs/m6d_w2b_target_adaptive_targets/1F3V_BA/1F3V_BA_B.fasta
# 1F3V_BA target_fasta_report: hpc_outputs/m6d_w2b_target_adaptive_targets/1F3V_BA/1F3V_BA_B.fasta.report.json
# 1F3V_BA target_msa: hpc_outputs/m6d_w2b_target_adaptive_targets/1F3V_BA/1F3V_BA_B.a3m
# 1F3V_BA target_msa_report: hpc_outputs/m6d_w2b_target_adaptive_targets/1F3V_BA/1F3V_BA_B.a3m.report.json

# rerun_manifest_after_msa
# python -m bio_sfm_designer.experiments.complex_target_manifest --manifest configs/m6d_w3b_fresh_targets.json --require-files --min-targets 8 --min-contacts 1 --out results/m6d_w3b_manifest_pre_msa.json
