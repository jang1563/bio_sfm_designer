# M6c target-MSA precompute plan
# Run this before --require-files panel/scale readiness when target .a3m/report files are missing or stale.
set -euo pipefail
PYTHON_BIN="${BIO_SFM_PYTHON:-${ENV_PY:-python3}}"

# Optional: set TARGET_MSA_PRECOMPUTE_RECEIPT to append submitted/reused targets as JSONL.
if [ -n "${TARGET_MSA_PRECOMPUTE_RECEIPT:-}" ]; then
  mkdir -p "$(dirname "$TARGET_MSA_PRECOMPUTE_RECEIPT")"
fi
TARGET_MSA_PRECOMPUTE_MANIFEST=configs/m6d_w3c_b1_target_msa_manifest.json
export TARGET_MSA_PRECOMPUTE_MANIFEST
TARGET_MSA_PRECOMPUTE_MANIFEST_SHA256_EXPECTED=d03711fbf576690a9347c2aa948af683495423c0775c60d39bf33fb52d80deda
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
TARGET_MSA_PRECOMPUTE_DRY_RUN_TARGETS='["1TE1_BA", "3QB4_AB", "5E5M_AB", "5JSB_AB", "6KBR_AC", "6KMQ_AB", "6SGE_AB", "7B5G_AB"]'
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

# 1TE1_BA
mkdir -p hpc_outputs/m6d_w3c_sources hpc_outputs/m6d_w3c_b1_targets/1TE1_BA
if [ -s hpc_outputs/m6d_w3c_sources/source_1TE1.pdb ]; then
  echo 'source PDB already exists: hpc_outputs/m6d_w3c_sources/source_1TE1.pdb'
else
  curl -fsSL https://files.rcsb.org/download/1TE1.pdb -o hpc_outputs/m6d_w3c_sources/source_1TE1.pdb
fi
if [ -s hpc_outputs/m6d_w3c_b1_targets/1TE1_BA/prepared_1TE1_BA.pdb ] && [ -s hpc_outputs/m6d_w3c_b1_targets/1TE1_BA/prepared_1TE1_BA.report.json ]; then
  echo 'prepared PDB already exists: hpc_outputs/m6d_w3c_b1_targets/1TE1_BA/prepared_1TE1_BA.pdb'
else
  "$PYTHON_BIN" hpc/prep_hetdimer.py --pdb hpc_outputs/m6d_w3c_sources/source_1TE1.pdb --target-chain B --binder-chain A --out hpc_outputs/m6d_w3c_b1_targets/1TE1_BA/prepared_1TE1_BA.pdb --report hpc_outputs/m6d_w3c_b1_targets/1TE1_BA/prepared_1TE1_BA.report.json
fi
"$PYTHON_BIN" hpc/extract_chain_fasta.py --pdb hpc_outputs/m6d_w3c_b1_targets/1TE1_BA/prepared_1TE1_BA.pdb --chain B --id 1TE1_BA_B --out hpc_outputs/m6d_w3c_b1_targets/1TE1_BA/1TE1_BA_B.fasta --report hpc_outputs/m6d_w3c_b1_targets/1TE1_BA/1TE1_BA_B.fasta.report.json
if [ -s hpc_outputs/m6d_w3c_b1_targets/1TE1_BA/1TE1_BA_B.a3m ]; then
  echo 'target MSA exists; validating and refreshing report: hpc_outputs/m6d_w3c_b1_targets/1TE1_BA/1TE1_BA_B.a3m'
  "$PYTHON_BIN" hpc/precompute_boltz_target_msa.py --fasta hpc_outputs/m6d_w3c_b1_targets/1TE1_BA/1TE1_BA_B.fasta --out hpc_outputs/m6d_w3c_b1_targets/1TE1_BA/1TE1_BA_B.a3m --report hpc_outputs/m6d_w3c_b1_targets/1TE1_BA/1TE1_BA_B.a3m.report.json
  record_target_msa_precompute 1TE1_BA validated_existing '' hpc_outputs/m6d_w3c_b1_targets/1TE1_BA/1TE1_BA_B.fasta hpc_outputs/m6d_w3c_b1_targets/1TE1_BA/1TE1_BA_B.a3m hpc_outputs/m6d_w3c_b1_targets/1TE1_BA/1TE1_BA_B.a3m.report.json
else
  MSA_00_T_1TE1_BA=$(FASTA=hpc_outputs/m6d_w3c_b1_targets/1TE1_BA/1TE1_BA_B.fasta OUT=hpc_outputs/m6d_w3c_b1_targets/1TE1_BA/1TE1_BA_B.a3m REPORT=hpc_outputs/m6d_w3c_b1_targets/1TE1_BA/1TE1_BA_B.a3m.report.json sbatch --parsable hpc/run_precompute_boltz_target_msa.sbatch)
  require_target_msa_job_id 1TE1_BA "${MSA_00_T_1TE1_BA}"
  echo 'submitted target MSA job for 1TE1_BA: '"${MSA_00_T_1TE1_BA}"
  record_target_msa_precompute 1TE1_BA submitted "${MSA_00_T_1TE1_BA}" hpc_outputs/m6d_w3c_b1_targets/1TE1_BA/1TE1_BA_B.fasta hpc_outputs/m6d_w3c_b1_targets/1TE1_BA/1TE1_BA_B.a3m hpc_outputs/m6d_w3c_b1_targets/1TE1_BA/1TE1_BA_B.a3m.report.json
fi

# 3QB4_AB
mkdir -p hpc_outputs/m6d_w3c_sources hpc_outputs/m6d_w3c_b1_targets/3QB4_AB
if [ -s hpc_outputs/m6d_w3c_sources/source_3QB4.pdb ]; then
  echo 'source PDB already exists: hpc_outputs/m6d_w3c_sources/source_3QB4.pdb'
else
  curl -fsSL https://files.rcsb.org/download/3QB4.pdb -o hpc_outputs/m6d_w3c_sources/source_3QB4.pdb
fi
if [ -s hpc_outputs/m6d_w3c_b1_targets/3QB4_AB/prepared_3QB4_AB.pdb ] && [ -s hpc_outputs/m6d_w3c_b1_targets/3QB4_AB/prepared_3QB4_AB.report.json ]; then
  echo 'prepared PDB already exists: hpc_outputs/m6d_w3c_b1_targets/3QB4_AB/prepared_3QB4_AB.pdb'
else
  "$PYTHON_BIN" hpc/prep_hetdimer.py --pdb hpc_outputs/m6d_w3c_sources/source_3QB4.pdb --target-chain A --binder-chain B --out hpc_outputs/m6d_w3c_b1_targets/3QB4_AB/prepared_3QB4_AB.pdb --report hpc_outputs/m6d_w3c_b1_targets/3QB4_AB/prepared_3QB4_AB.report.json
fi
"$PYTHON_BIN" hpc/extract_chain_fasta.py --pdb hpc_outputs/m6d_w3c_b1_targets/3QB4_AB/prepared_3QB4_AB.pdb --chain A --id 3QB4_AB_A --out hpc_outputs/m6d_w3c_b1_targets/3QB4_AB/3QB4_AB_A.fasta --report hpc_outputs/m6d_w3c_b1_targets/3QB4_AB/3QB4_AB_A.fasta.report.json
if [ -s hpc_outputs/m6d_w3c_b1_targets/3QB4_AB/3QB4_AB_A.a3m ]; then
  echo 'target MSA exists; validating and refreshing report: hpc_outputs/m6d_w3c_b1_targets/3QB4_AB/3QB4_AB_A.a3m'
  "$PYTHON_BIN" hpc/precompute_boltz_target_msa.py --fasta hpc_outputs/m6d_w3c_b1_targets/3QB4_AB/3QB4_AB_A.fasta --out hpc_outputs/m6d_w3c_b1_targets/3QB4_AB/3QB4_AB_A.a3m --report hpc_outputs/m6d_w3c_b1_targets/3QB4_AB/3QB4_AB_A.a3m.report.json
  record_target_msa_precompute 3QB4_AB validated_existing '' hpc_outputs/m6d_w3c_b1_targets/3QB4_AB/3QB4_AB_A.fasta hpc_outputs/m6d_w3c_b1_targets/3QB4_AB/3QB4_AB_A.a3m hpc_outputs/m6d_w3c_b1_targets/3QB4_AB/3QB4_AB_A.a3m.report.json
else
  MSA_01_T_3QB4_AB=$(FASTA=hpc_outputs/m6d_w3c_b1_targets/3QB4_AB/3QB4_AB_A.fasta OUT=hpc_outputs/m6d_w3c_b1_targets/3QB4_AB/3QB4_AB_A.a3m REPORT=hpc_outputs/m6d_w3c_b1_targets/3QB4_AB/3QB4_AB_A.a3m.report.json sbatch --parsable hpc/run_precompute_boltz_target_msa.sbatch)
  require_target_msa_job_id 3QB4_AB "${MSA_01_T_3QB4_AB}"
  echo 'submitted target MSA job for 3QB4_AB: '"${MSA_01_T_3QB4_AB}"
  record_target_msa_precompute 3QB4_AB submitted "${MSA_01_T_3QB4_AB}" hpc_outputs/m6d_w3c_b1_targets/3QB4_AB/3QB4_AB_A.fasta hpc_outputs/m6d_w3c_b1_targets/3QB4_AB/3QB4_AB_A.a3m hpc_outputs/m6d_w3c_b1_targets/3QB4_AB/3QB4_AB_A.a3m.report.json
fi

# 5E5M_AB
mkdir -p hpc_outputs/m6d_w3c_sources hpc_outputs/m6d_w3c_b1_targets/5E5M_AB
if [ -s hpc_outputs/m6d_w3c_sources/source_5E5M.pdb ]; then
  echo 'source PDB already exists: hpc_outputs/m6d_w3c_sources/source_5E5M.pdb'
else
  curl -fsSL https://files.rcsb.org/download/5E5M.pdb -o hpc_outputs/m6d_w3c_sources/source_5E5M.pdb
fi
if [ -s hpc_outputs/m6d_w3c_b1_targets/5E5M_AB/prepared_5E5M_AB.pdb ] && [ -s hpc_outputs/m6d_w3c_b1_targets/5E5M_AB/prepared_5E5M_AB.report.json ]; then
  echo 'prepared PDB already exists: hpc_outputs/m6d_w3c_b1_targets/5E5M_AB/prepared_5E5M_AB.pdb'
else
  "$PYTHON_BIN" hpc/prep_hetdimer.py --pdb hpc_outputs/m6d_w3c_sources/source_5E5M.pdb --target-chain A --binder-chain B --out hpc_outputs/m6d_w3c_b1_targets/5E5M_AB/prepared_5E5M_AB.pdb --report hpc_outputs/m6d_w3c_b1_targets/5E5M_AB/prepared_5E5M_AB.report.json
fi
"$PYTHON_BIN" hpc/extract_chain_fasta.py --pdb hpc_outputs/m6d_w3c_b1_targets/5E5M_AB/prepared_5E5M_AB.pdb --chain A --id 5E5M_AB_A --out hpc_outputs/m6d_w3c_b1_targets/5E5M_AB/5E5M_AB_A.fasta --report hpc_outputs/m6d_w3c_b1_targets/5E5M_AB/5E5M_AB_A.fasta.report.json
if [ -s hpc_outputs/m6d_w3c_b1_targets/5E5M_AB/5E5M_AB_A.a3m ]; then
  echo 'target MSA exists; validating and refreshing report: hpc_outputs/m6d_w3c_b1_targets/5E5M_AB/5E5M_AB_A.a3m'
  "$PYTHON_BIN" hpc/precompute_boltz_target_msa.py --fasta hpc_outputs/m6d_w3c_b1_targets/5E5M_AB/5E5M_AB_A.fasta --out hpc_outputs/m6d_w3c_b1_targets/5E5M_AB/5E5M_AB_A.a3m --report hpc_outputs/m6d_w3c_b1_targets/5E5M_AB/5E5M_AB_A.a3m.report.json
  record_target_msa_precompute 5E5M_AB validated_existing '' hpc_outputs/m6d_w3c_b1_targets/5E5M_AB/5E5M_AB_A.fasta hpc_outputs/m6d_w3c_b1_targets/5E5M_AB/5E5M_AB_A.a3m hpc_outputs/m6d_w3c_b1_targets/5E5M_AB/5E5M_AB_A.a3m.report.json
else
  MSA_02_T_5E5M_AB=$(FASTA=hpc_outputs/m6d_w3c_b1_targets/5E5M_AB/5E5M_AB_A.fasta OUT=hpc_outputs/m6d_w3c_b1_targets/5E5M_AB/5E5M_AB_A.a3m REPORT=hpc_outputs/m6d_w3c_b1_targets/5E5M_AB/5E5M_AB_A.a3m.report.json sbatch --parsable hpc/run_precompute_boltz_target_msa.sbatch)
  require_target_msa_job_id 5E5M_AB "${MSA_02_T_5E5M_AB}"
  echo 'submitted target MSA job for 5E5M_AB: '"${MSA_02_T_5E5M_AB}"
  record_target_msa_precompute 5E5M_AB submitted "${MSA_02_T_5E5M_AB}" hpc_outputs/m6d_w3c_b1_targets/5E5M_AB/5E5M_AB_A.fasta hpc_outputs/m6d_w3c_b1_targets/5E5M_AB/5E5M_AB_A.a3m hpc_outputs/m6d_w3c_b1_targets/5E5M_AB/5E5M_AB_A.a3m.report.json
fi

# 5JSB_AB
mkdir -p hpc_outputs/m6d_w3c_sources hpc_outputs/m6d_w3c_b1_targets/5JSB_AB
if [ -s hpc_outputs/m6d_w3c_sources/source_5JSB.pdb ]; then
  echo 'source PDB already exists: hpc_outputs/m6d_w3c_sources/source_5JSB.pdb'
else
  curl -fsSL https://files.rcsb.org/download/5JSB.pdb -o hpc_outputs/m6d_w3c_sources/source_5JSB.pdb
fi
if [ -s hpc_outputs/m6d_w3c_b1_targets/5JSB_AB/prepared_5JSB_AB.pdb ] && [ -s hpc_outputs/m6d_w3c_b1_targets/5JSB_AB/prepared_5JSB_AB.report.json ]; then
  echo 'prepared PDB already exists: hpc_outputs/m6d_w3c_b1_targets/5JSB_AB/prepared_5JSB_AB.pdb'
else
  "$PYTHON_BIN" hpc/prep_hetdimer.py --pdb hpc_outputs/m6d_w3c_sources/source_5JSB.pdb --target-chain A --binder-chain B --out hpc_outputs/m6d_w3c_b1_targets/5JSB_AB/prepared_5JSB_AB.pdb --report hpc_outputs/m6d_w3c_b1_targets/5JSB_AB/prepared_5JSB_AB.report.json
fi
"$PYTHON_BIN" hpc/extract_chain_fasta.py --pdb hpc_outputs/m6d_w3c_b1_targets/5JSB_AB/prepared_5JSB_AB.pdb --chain A --id 5JSB_AB_A --out hpc_outputs/m6d_w3c_b1_targets/5JSB_AB/5JSB_AB_A.fasta --report hpc_outputs/m6d_w3c_b1_targets/5JSB_AB/5JSB_AB_A.fasta.report.json
if [ -s hpc_outputs/m6d_w3c_b1_targets/5JSB_AB/5JSB_AB_A.a3m ]; then
  echo 'target MSA exists; validating and refreshing report: hpc_outputs/m6d_w3c_b1_targets/5JSB_AB/5JSB_AB_A.a3m'
  "$PYTHON_BIN" hpc/precompute_boltz_target_msa.py --fasta hpc_outputs/m6d_w3c_b1_targets/5JSB_AB/5JSB_AB_A.fasta --out hpc_outputs/m6d_w3c_b1_targets/5JSB_AB/5JSB_AB_A.a3m --report hpc_outputs/m6d_w3c_b1_targets/5JSB_AB/5JSB_AB_A.a3m.report.json
  record_target_msa_precompute 5JSB_AB validated_existing '' hpc_outputs/m6d_w3c_b1_targets/5JSB_AB/5JSB_AB_A.fasta hpc_outputs/m6d_w3c_b1_targets/5JSB_AB/5JSB_AB_A.a3m hpc_outputs/m6d_w3c_b1_targets/5JSB_AB/5JSB_AB_A.a3m.report.json
else
  MSA_03_T_5JSB_AB=$(FASTA=hpc_outputs/m6d_w3c_b1_targets/5JSB_AB/5JSB_AB_A.fasta OUT=hpc_outputs/m6d_w3c_b1_targets/5JSB_AB/5JSB_AB_A.a3m REPORT=hpc_outputs/m6d_w3c_b1_targets/5JSB_AB/5JSB_AB_A.a3m.report.json sbatch --parsable hpc/run_precompute_boltz_target_msa.sbatch)
  require_target_msa_job_id 5JSB_AB "${MSA_03_T_5JSB_AB}"
  echo 'submitted target MSA job for 5JSB_AB: '"${MSA_03_T_5JSB_AB}"
  record_target_msa_precompute 5JSB_AB submitted "${MSA_03_T_5JSB_AB}" hpc_outputs/m6d_w3c_b1_targets/5JSB_AB/5JSB_AB_A.fasta hpc_outputs/m6d_w3c_b1_targets/5JSB_AB/5JSB_AB_A.a3m hpc_outputs/m6d_w3c_b1_targets/5JSB_AB/5JSB_AB_A.a3m.report.json
fi

# 6KBR_AC
mkdir -p hpc_outputs/m6d_w3c_sources hpc_outputs/m6d_w3c_b1_targets/6KBR_AC
if [ -s hpc_outputs/m6d_w3c_sources/source_6KBR.pdb ]; then
  echo 'source PDB already exists: hpc_outputs/m6d_w3c_sources/source_6KBR.pdb'
else
  curl -fsSL https://files.rcsb.org/download/6KBR.pdb -o hpc_outputs/m6d_w3c_sources/source_6KBR.pdb
fi
if [ -s hpc_outputs/m6d_w3c_b1_targets/6KBR_AC/prepared_6KBR_AC.pdb ] && [ -s hpc_outputs/m6d_w3c_b1_targets/6KBR_AC/prepared_6KBR_AC.report.json ]; then
  echo 'prepared PDB already exists: hpc_outputs/m6d_w3c_b1_targets/6KBR_AC/prepared_6KBR_AC.pdb'
else
  "$PYTHON_BIN" hpc/prep_hetdimer.py --pdb hpc_outputs/m6d_w3c_sources/source_6KBR.pdb --target-chain A --binder-chain C --out hpc_outputs/m6d_w3c_b1_targets/6KBR_AC/prepared_6KBR_AC.pdb --report hpc_outputs/m6d_w3c_b1_targets/6KBR_AC/prepared_6KBR_AC.report.json
fi
"$PYTHON_BIN" hpc/extract_chain_fasta.py --pdb hpc_outputs/m6d_w3c_b1_targets/6KBR_AC/prepared_6KBR_AC.pdb --chain A --id 6KBR_AC_A --out hpc_outputs/m6d_w3c_b1_targets/6KBR_AC/6KBR_AC_A.fasta --report hpc_outputs/m6d_w3c_b1_targets/6KBR_AC/6KBR_AC_A.fasta.report.json
if [ -s hpc_outputs/m6d_w3c_b1_targets/6KBR_AC/6KBR_AC_A.a3m ]; then
  echo 'target MSA exists; validating and refreshing report: hpc_outputs/m6d_w3c_b1_targets/6KBR_AC/6KBR_AC_A.a3m'
  "$PYTHON_BIN" hpc/precompute_boltz_target_msa.py --fasta hpc_outputs/m6d_w3c_b1_targets/6KBR_AC/6KBR_AC_A.fasta --out hpc_outputs/m6d_w3c_b1_targets/6KBR_AC/6KBR_AC_A.a3m --report hpc_outputs/m6d_w3c_b1_targets/6KBR_AC/6KBR_AC_A.a3m.report.json
  record_target_msa_precompute 6KBR_AC validated_existing '' hpc_outputs/m6d_w3c_b1_targets/6KBR_AC/6KBR_AC_A.fasta hpc_outputs/m6d_w3c_b1_targets/6KBR_AC/6KBR_AC_A.a3m hpc_outputs/m6d_w3c_b1_targets/6KBR_AC/6KBR_AC_A.a3m.report.json
else
  MSA_04_T_6KBR_AC=$(FASTA=hpc_outputs/m6d_w3c_b1_targets/6KBR_AC/6KBR_AC_A.fasta OUT=hpc_outputs/m6d_w3c_b1_targets/6KBR_AC/6KBR_AC_A.a3m REPORT=hpc_outputs/m6d_w3c_b1_targets/6KBR_AC/6KBR_AC_A.a3m.report.json sbatch --parsable hpc/run_precompute_boltz_target_msa.sbatch)
  require_target_msa_job_id 6KBR_AC "${MSA_04_T_6KBR_AC}"
  echo 'submitted target MSA job for 6KBR_AC: '"${MSA_04_T_6KBR_AC}"
  record_target_msa_precompute 6KBR_AC submitted "${MSA_04_T_6KBR_AC}" hpc_outputs/m6d_w3c_b1_targets/6KBR_AC/6KBR_AC_A.fasta hpc_outputs/m6d_w3c_b1_targets/6KBR_AC/6KBR_AC_A.a3m hpc_outputs/m6d_w3c_b1_targets/6KBR_AC/6KBR_AC_A.a3m.report.json
fi

# 6KMQ_AB
mkdir -p hpc_outputs/m6d_w3c_sources hpc_outputs/m6d_w3c_b1_targets/6KMQ_AB
if [ -s hpc_outputs/m6d_w3c_sources/source_6KMQ.pdb ]; then
  echo 'source PDB already exists: hpc_outputs/m6d_w3c_sources/source_6KMQ.pdb'
else
  curl -fsSL https://files.rcsb.org/download/6KMQ.pdb -o hpc_outputs/m6d_w3c_sources/source_6KMQ.pdb
fi
if [ -s hpc_outputs/m6d_w3c_b1_targets/6KMQ_AB/prepared_6KMQ_AB.pdb ] && [ -s hpc_outputs/m6d_w3c_b1_targets/6KMQ_AB/prepared_6KMQ_AB.report.json ]; then
  echo 'prepared PDB already exists: hpc_outputs/m6d_w3c_b1_targets/6KMQ_AB/prepared_6KMQ_AB.pdb'
else
  "$PYTHON_BIN" hpc/prep_hetdimer.py --pdb hpc_outputs/m6d_w3c_sources/source_6KMQ.pdb --target-chain A --binder-chain B --out hpc_outputs/m6d_w3c_b1_targets/6KMQ_AB/prepared_6KMQ_AB.pdb --report hpc_outputs/m6d_w3c_b1_targets/6KMQ_AB/prepared_6KMQ_AB.report.json
fi
"$PYTHON_BIN" hpc/extract_chain_fasta.py --pdb hpc_outputs/m6d_w3c_b1_targets/6KMQ_AB/prepared_6KMQ_AB.pdb --chain A --id 6KMQ_AB_A --out hpc_outputs/m6d_w3c_b1_targets/6KMQ_AB/6KMQ_AB_A.fasta --report hpc_outputs/m6d_w3c_b1_targets/6KMQ_AB/6KMQ_AB_A.fasta.report.json
if [ -s hpc_outputs/m6d_w3c_b1_targets/6KMQ_AB/6KMQ_AB_A.a3m ]; then
  echo 'target MSA exists; validating and refreshing report: hpc_outputs/m6d_w3c_b1_targets/6KMQ_AB/6KMQ_AB_A.a3m'
  "$PYTHON_BIN" hpc/precompute_boltz_target_msa.py --fasta hpc_outputs/m6d_w3c_b1_targets/6KMQ_AB/6KMQ_AB_A.fasta --out hpc_outputs/m6d_w3c_b1_targets/6KMQ_AB/6KMQ_AB_A.a3m --report hpc_outputs/m6d_w3c_b1_targets/6KMQ_AB/6KMQ_AB_A.a3m.report.json
  record_target_msa_precompute 6KMQ_AB validated_existing '' hpc_outputs/m6d_w3c_b1_targets/6KMQ_AB/6KMQ_AB_A.fasta hpc_outputs/m6d_w3c_b1_targets/6KMQ_AB/6KMQ_AB_A.a3m hpc_outputs/m6d_w3c_b1_targets/6KMQ_AB/6KMQ_AB_A.a3m.report.json
else
  MSA_05_T_6KMQ_AB=$(FASTA=hpc_outputs/m6d_w3c_b1_targets/6KMQ_AB/6KMQ_AB_A.fasta OUT=hpc_outputs/m6d_w3c_b1_targets/6KMQ_AB/6KMQ_AB_A.a3m REPORT=hpc_outputs/m6d_w3c_b1_targets/6KMQ_AB/6KMQ_AB_A.a3m.report.json sbatch --parsable hpc/run_precompute_boltz_target_msa.sbatch)
  require_target_msa_job_id 6KMQ_AB "${MSA_05_T_6KMQ_AB}"
  echo 'submitted target MSA job for 6KMQ_AB: '"${MSA_05_T_6KMQ_AB}"
  record_target_msa_precompute 6KMQ_AB submitted "${MSA_05_T_6KMQ_AB}" hpc_outputs/m6d_w3c_b1_targets/6KMQ_AB/6KMQ_AB_A.fasta hpc_outputs/m6d_w3c_b1_targets/6KMQ_AB/6KMQ_AB_A.a3m hpc_outputs/m6d_w3c_b1_targets/6KMQ_AB/6KMQ_AB_A.a3m.report.json
fi

# 6SGE_AB
mkdir -p hpc_outputs/m6d_w3c_sources hpc_outputs/m6d_w3c_b1_targets/6SGE_AB
if [ -s hpc_outputs/m6d_w3c_sources/source_6SGE.pdb ]; then
  echo 'source PDB already exists: hpc_outputs/m6d_w3c_sources/source_6SGE.pdb'
else
  curl -fsSL https://files.rcsb.org/download/6SGE.pdb -o hpc_outputs/m6d_w3c_sources/source_6SGE.pdb
fi
if [ -s hpc_outputs/m6d_w3c_b1_targets/6SGE_AB/prepared_6SGE_AB.pdb ] && [ -s hpc_outputs/m6d_w3c_b1_targets/6SGE_AB/prepared_6SGE_AB.report.json ]; then
  echo 'prepared PDB already exists: hpc_outputs/m6d_w3c_b1_targets/6SGE_AB/prepared_6SGE_AB.pdb'
else
  "$PYTHON_BIN" hpc/prep_hetdimer.py --pdb hpc_outputs/m6d_w3c_sources/source_6SGE.pdb --target-chain A --binder-chain B --out hpc_outputs/m6d_w3c_b1_targets/6SGE_AB/prepared_6SGE_AB.pdb --report hpc_outputs/m6d_w3c_b1_targets/6SGE_AB/prepared_6SGE_AB.report.json
fi
"$PYTHON_BIN" hpc/extract_chain_fasta.py --pdb hpc_outputs/m6d_w3c_b1_targets/6SGE_AB/prepared_6SGE_AB.pdb --chain A --id 6SGE_AB_A --out hpc_outputs/m6d_w3c_b1_targets/6SGE_AB/6SGE_AB_A.fasta --report hpc_outputs/m6d_w3c_b1_targets/6SGE_AB/6SGE_AB_A.fasta.report.json
if [ -s hpc_outputs/m6d_w3c_b1_targets/6SGE_AB/6SGE_AB_A.a3m ]; then
  echo 'target MSA exists; validating and refreshing report: hpc_outputs/m6d_w3c_b1_targets/6SGE_AB/6SGE_AB_A.a3m'
  "$PYTHON_BIN" hpc/precompute_boltz_target_msa.py --fasta hpc_outputs/m6d_w3c_b1_targets/6SGE_AB/6SGE_AB_A.fasta --out hpc_outputs/m6d_w3c_b1_targets/6SGE_AB/6SGE_AB_A.a3m --report hpc_outputs/m6d_w3c_b1_targets/6SGE_AB/6SGE_AB_A.a3m.report.json
  record_target_msa_precompute 6SGE_AB validated_existing '' hpc_outputs/m6d_w3c_b1_targets/6SGE_AB/6SGE_AB_A.fasta hpc_outputs/m6d_w3c_b1_targets/6SGE_AB/6SGE_AB_A.a3m hpc_outputs/m6d_w3c_b1_targets/6SGE_AB/6SGE_AB_A.a3m.report.json
else
  MSA_06_T_6SGE_AB=$(FASTA=hpc_outputs/m6d_w3c_b1_targets/6SGE_AB/6SGE_AB_A.fasta OUT=hpc_outputs/m6d_w3c_b1_targets/6SGE_AB/6SGE_AB_A.a3m REPORT=hpc_outputs/m6d_w3c_b1_targets/6SGE_AB/6SGE_AB_A.a3m.report.json sbatch --parsable hpc/run_precompute_boltz_target_msa.sbatch)
  require_target_msa_job_id 6SGE_AB "${MSA_06_T_6SGE_AB}"
  echo 'submitted target MSA job for 6SGE_AB: '"${MSA_06_T_6SGE_AB}"
  record_target_msa_precompute 6SGE_AB submitted "${MSA_06_T_6SGE_AB}" hpc_outputs/m6d_w3c_b1_targets/6SGE_AB/6SGE_AB_A.fasta hpc_outputs/m6d_w3c_b1_targets/6SGE_AB/6SGE_AB_A.a3m hpc_outputs/m6d_w3c_b1_targets/6SGE_AB/6SGE_AB_A.a3m.report.json
fi

# 7B5G_AB
mkdir -p hpc_outputs/m6d_w3c_sources hpc_outputs/m6d_w3c_b1_targets/7B5G_AB
if [ -s hpc_outputs/m6d_w3c_sources/source_7B5G.pdb ]; then
  echo 'source PDB already exists: hpc_outputs/m6d_w3c_sources/source_7B5G.pdb'
else
  curl -fsSL https://files.rcsb.org/download/7B5G.pdb -o hpc_outputs/m6d_w3c_sources/source_7B5G.pdb
fi
if [ -s hpc_outputs/m6d_w3c_b1_targets/7B5G_AB/prepared_7B5G_AB.pdb ] && [ -s hpc_outputs/m6d_w3c_b1_targets/7B5G_AB/prepared_7B5G_AB.report.json ]; then
  echo 'prepared PDB already exists: hpc_outputs/m6d_w3c_b1_targets/7B5G_AB/prepared_7B5G_AB.pdb'
else
  "$PYTHON_BIN" hpc/prep_hetdimer.py --pdb hpc_outputs/m6d_w3c_sources/source_7B5G.pdb --target-chain A --binder-chain B --out hpc_outputs/m6d_w3c_b1_targets/7B5G_AB/prepared_7B5G_AB.pdb --report hpc_outputs/m6d_w3c_b1_targets/7B5G_AB/prepared_7B5G_AB.report.json
fi
"$PYTHON_BIN" hpc/extract_chain_fasta.py --pdb hpc_outputs/m6d_w3c_b1_targets/7B5G_AB/prepared_7B5G_AB.pdb --chain A --id 7B5G_AB_A --out hpc_outputs/m6d_w3c_b1_targets/7B5G_AB/7B5G_AB_A.fasta --report hpc_outputs/m6d_w3c_b1_targets/7B5G_AB/7B5G_AB_A.fasta.report.json
if [ -s hpc_outputs/m6d_w3c_b1_targets/7B5G_AB/7B5G_AB_A.a3m ]; then
  echo 'target MSA exists; validating and refreshing report: hpc_outputs/m6d_w3c_b1_targets/7B5G_AB/7B5G_AB_A.a3m'
  "$PYTHON_BIN" hpc/precompute_boltz_target_msa.py --fasta hpc_outputs/m6d_w3c_b1_targets/7B5G_AB/7B5G_AB_A.fasta --out hpc_outputs/m6d_w3c_b1_targets/7B5G_AB/7B5G_AB_A.a3m --report hpc_outputs/m6d_w3c_b1_targets/7B5G_AB/7B5G_AB_A.a3m.report.json
  record_target_msa_precompute 7B5G_AB validated_existing '' hpc_outputs/m6d_w3c_b1_targets/7B5G_AB/7B5G_AB_A.fasta hpc_outputs/m6d_w3c_b1_targets/7B5G_AB/7B5G_AB_A.a3m hpc_outputs/m6d_w3c_b1_targets/7B5G_AB/7B5G_AB_A.a3m.report.json
else
  MSA_07_T_7B5G_AB=$(FASTA=hpc_outputs/m6d_w3c_b1_targets/7B5G_AB/7B5G_AB_A.fasta OUT=hpc_outputs/m6d_w3c_b1_targets/7B5G_AB/7B5G_AB_A.a3m REPORT=hpc_outputs/m6d_w3c_b1_targets/7B5G_AB/7B5G_AB_A.a3m.report.json sbatch --parsable hpc/run_precompute_boltz_target_msa.sbatch)
  require_target_msa_job_id 7B5G_AB "${MSA_07_T_7B5G_AB}"
  echo 'submitted target MSA job for 7B5G_AB: '"${MSA_07_T_7B5G_AB}"
  record_target_msa_precompute 7B5G_AB submitted "${MSA_07_T_7B5G_AB}" hpc_outputs/m6d_w3c_b1_targets/7B5G_AB/7B5G_AB_A.fasta hpc_outputs/m6d_w3c_b1_targets/7B5G_AB/7B5G_AB_A.a3m hpc_outputs/m6d_w3c_b1_targets/7B5G_AB/7B5G_AB_A.a3m.report.json
fi

validate_target_msa_precompute_receipt --expect-json '{"1TE1_BA":{"manifest":"configs/m6d_w3c_b1_target_msa_manifest.json","manifest_sha256":"d03711fbf576690a9347c2aa948af683495423c0775c60d39bf33fb52d80deda","target_fasta":"hpc_outputs/m6d_w3c_b1_targets/1TE1_BA/1TE1_BA_B.fasta","target_msa":"hpc_outputs/m6d_w3c_b1_targets/1TE1_BA/1TE1_BA_B.a3m","target_msa_report":"hpc_outputs/m6d_w3c_b1_targets/1TE1_BA/1TE1_BA_B.a3m.report.json"},"3QB4_AB":{"manifest":"configs/m6d_w3c_b1_target_msa_manifest.json","manifest_sha256":"d03711fbf576690a9347c2aa948af683495423c0775c60d39bf33fb52d80deda","target_fasta":"hpc_outputs/m6d_w3c_b1_targets/3QB4_AB/3QB4_AB_A.fasta","target_msa":"hpc_outputs/m6d_w3c_b1_targets/3QB4_AB/3QB4_AB_A.a3m","target_msa_report":"hpc_outputs/m6d_w3c_b1_targets/3QB4_AB/3QB4_AB_A.a3m.report.json"},"5E5M_AB":{"manifest":"configs/m6d_w3c_b1_target_msa_manifest.json","manifest_sha256":"d03711fbf576690a9347c2aa948af683495423c0775c60d39bf33fb52d80deda","target_fasta":"hpc_outputs/m6d_w3c_b1_targets/5E5M_AB/5E5M_AB_A.fasta","target_msa":"hpc_outputs/m6d_w3c_b1_targets/5E5M_AB/5E5M_AB_A.a3m","target_msa_report":"hpc_outputs/m6d_w3c_b1_targets/5E5M_AB/5E5M_AB_A.a3m.report.json"},"5JSB_AB":{"manifest":"configs/m6d_w3c_b1_target_msa_manifest.json","manifest_sha256":"d03711fbf576690a9347c2aa948af683495423c0775c60d39bf33fb52d80deda","target_fasta":"hpc_outputs/m6d_w3c_b1_targets/5JSB_AB/5JSB_AB_A.fasta","target_msa":"hpc_outputs/m6d_w3c_b1_targets/5JSB_AB/5JSB_AB_A.a3m","target_msa_report":"hpc_outputs/m6d_w3c_b1_targets/5JSB_AB/5JSB_AB_A.a3m.report.json"},"6KBR_AC":{"manifest":"configs/m6d_w3c_b1_target_msa_manifest.json","manifest_sha256":"d03711fbf576690a9347c2aa948af683495423c0775c60d39bf33fb52d80deda","target_fasta":"hpc_outputs/m6d_w3c_b1_targets/6KBR_AC/6KBR_AC_A.fasta","target_msa":"hpc_outputs/m6d_w3c_b1_targets/6KBR_AC/6KBR_AC_A.a3m","target_msa_report":"hpc_outputs/m6d_w3c_b1_targets/6KBR_AC/6KBR_AC_A.a3m.report.json"},"6KMQ_AB":{"manifest":"configs/m6d_w3c_b1_target_msa_manifest.json","manifest_sha256":"d03711fbf576690a9347c2aa948af683495423c0775c60d39bf33fb52d80deda","target_fasta":"hpc_outputs/m6d_w3c_b1_targets/6KMQ_AB/6KMQ_AB_A.fasta","target_msa":"hpc_outputs/m6d_w3c_b1_targets/6KMQ_AB/6KMQ_AB_A.a3m","target_msa_report":"hpc_outputs/m6d_w3c_b1_targets/6KMQ_AB/6KMQ_AB_A.a3m.report.json"},"6SGE_AB":{"manifest":"configs/m6d_w3c_b1_target_msa_manifest.json","manifest_sha256":"d03711fbf576690a9347c2aa948af683495423c0775c60d39bf33fb52d80deda","target_fasta":"hpc_outputs/m6d_w3c_b1_targets/6SGE_AB/6SGE_AB_A.fasta","target_msa":"hpc_outputs/m6d_w3c_b1_targets/6SGE_AB/6SGE_AB_A.a3m","target_msa_report":"hpc_outputs/m6d_w3c_b1_targets/6SGE_AB/6SGE_AB_A.a3m.report.json"},"7B5G_AB":{"manifest":"configs/m6d_w3c_b1_target_msa_manifest.json","manifest_sha256":"d03711fbf576690a9347c2aa948af683495423c0775c60d39bf33fb52d80deda","target_fasta":"hpc_outputs/m6d_w3c_b1_targets/7B5G_AB/7B5G_AB_A.fasta","target_msa":"hpc_outputs/m6d_w3c_b1_targets/7B5G_AB/7B5G_AB_A.a3m","target_msa_report":"hpc_outputs/m6d_w3c_b1_targets/7B5G_AB/7B5G_AB_A.a3m.report.json"}}' 1TE1_BA 3QB4_AB 5E5M_AB 5JSB_AB 6KBR_AC 6KMQ_AB 6SGE_AB 7B5G_AB

# expected_input_prep_files
# If this plan runs on Cayuga, sync these paths back before rerunning --require-files.
# 1TE1_BA source_pdb: hpc_outputs/m6d_w3c_sources/source_1TE1.pdb
# 1TE1_BA prepared_pdb: hpc_outputs/m6d_w3c_b1_targets/1TE1_BA/prepared_1TE1_BA.pdb
# 1TE1_BA prep_report: hpc_outputs/m6d_w3c_b1_targets/1TE1_BA/prepared_1TE1_BA.report.json
# 1TE1_BA target_fasta: hpc_outputs/m6d_w3c_b1_targets/1TE1_BA/1TE1_BA_B.fasta
# 1TE1_BA target_fasta_report: hpc_outputs/m6d_w3c_b1_targets/1TE1_BA/1TE1_BA_B.fasta.report.json
# 1TE1_BA target_msa: hpc_outputs/m6d_w3c_b1_targets/1TE1_BA/1TE1_BA_B.a3m
# 1TE1_BA target_msa_report: hpc_outputs/m6d_w3c_b1_targets/1TE1_BA/1TE1_BA_B.a3m.report.json
# 3QB4_AB source_pdb: hpc_outputs/m6d_w3c_sources/source_3QB4.pdb
# 3QB4_AB prepared_pdb: hpc_outputs/m6d_w3c_b1_targets/3QB4_AB/prepared_3QB4_AB.pdb
# 3QB4_AB prep_report: hpc_outputs/m6d_w3c_b1_targets/3QB4_AB/prepared_3QB4_AB.report.json
# 3QB4_AB target_fasta: hpc_outputs/m6d_w3c_b1_targets/3QB4_AB/3QB4_AB_A.fasta
# 3QB4_AB target_fasta_report: hpc_outputs/m6d_w3c_b1_targets/3QB4_AB/3QB4_AB_A.fasta.report.json
# 3QB4_AB target_msa: hpc_outputs/m6d_w3c_b1_targets/3QB4_AB/3QB4_AB_A.a3m
# 3QB4_AB target_msa_report: hpc_outputs/m6d_w3c_b1_targets/3QB4_AB/3QB4_AB_A.a3m.report.json
# 5E5M_AB source_pdb: hpc_outputs/m6d_w3c_sources/source_5E5M.pdb
# 5E5M_AB prepared_pdb: hpc_outputs/m6d_w3c_b1_targets/5E5M_AB/prepared_5E5M_AB.pdb
# 5E5M_AB prep_report: hpc_outputs/m6d_w3c_b1_targets/5E5M_AB/prepared_5E5M_AB.report.json
# 5E5M_AB target_fasta: hpc_outputs/m6d_w3c_b1_targets/5E5M_AB/5E5M_AB_A.fasta
# 5E5M_AB target_fasta_report: hpc_outputs/m6d_w3c_b1_targets/5E5M_AB/5E5M_AB_A.fasta.report.json
# 5E5M_AB target_msa: hpc_outputs/m6d_w3c_b1_targets/5E5M_AB/5E5M_AB_A.a3m
# 5E5M_AB target_msa_report: hpc_outputs/m6d_w3c_b1_targets/5E5M_AB/5E5M_AB_A.a3m.report.json
# 5JSB_AB source_pdb: hpc_outputs/m6d_w3c_sources/source_5JSB.pdb
# 5JSB_AB prepared_pdb: hpc_outputs/m6d_w3c_b1_targets/5JSB_AB/prepared_5JSB_AB.pdb
# 5JSB_AB prep_report: hpc_outputs/m6d_w3c_b1_targets/5JSB_AB/prepared_5JSB_AB.report.json
# 5JSB_AB target_fasta: hpc_outputs/m6d_w3c_b1_targets/5JSB_AB/5JSB_AB_A.fasta
# 5JSB_AB target_fasta_report: hpc_outputs/m6d_w3c_b1_targets/5JSB_AB/5JSB_AB_A.fasta.report.json
# 5JSB_AB target_msa: hpc_outputs/m6d_w3c_b1_targets/5JSB_AB/5JSB_AB_A.a3m
# 5JSB_AB target_msa_report: hpc_outputs/m6d_w3c_b1_targets/5JSB_AB/5JSB_AB_A.a3m.report.json
# 6KBR_AC source_pdb: hpc_outputs/m6d_w3c_sources/source_6KBR.pdb
# 6KBR_AC prepared_pdb: hpc_outputs/m6d_w3c_b1_targets/6KBR_AC/prepared_6KBR_AC.pdb
# 6KBR_AC prep_report: hpc_outputs/m6d_w3c_b1_targets/6KBR_AC/prepared_6KBR_AC.report.json
# 6KBR_AC target_fasta: hpc_outputs/m6d_w3c_b1_targets/6KBR_AC/6KBR_AC_A.fasta
# 6KBR_AC target_fasta_report: hpc_outputs/m6d_w3c_b1_targets/6KBR_AC/6KBR_AC_A.fasta.report.json
# 6KBR_AC target_msa: hpc_outputs/m6d_w3c_b1_targets/6KBR_AC/6KBR_AC_A.a3m
# 6KBR_AC target_msa_report: hpc_outputs/m6d_w3c_b1_targets/6KBR_AC/6KBR_AC_A.a3m.report.json
# 6KMQ_AB source_pdb: hpc_outputs/m6d_w3c_sources/source_6KMQ.pdb
# 6KMQ_AB prepared_pdb: hpc_outputs/m6d_w3c_b1_targets/6KMQ_AB/prepared_6KMQ_AB.pdb
# 6KMQ_AB prep_report: hpc_outputs/m6d_w3c_b1_targets/6KMQ_AB/prepared_6KMQ_AB.report.json
# 6KMQ_AB target_fasta: hpc_outputs/m6d_w3c_b1_targets/6KMQ_AB/6KMQ_AB_A.fasta
# 6KMQ_AB target_fasta_report: hpc_outputs/m6d_w3c_b1_targets/6KMQ_AB/6KMQ_AB_A.fasta.report.json
# 6KMQ_AB target_msa: hpc_outputs/m6d_w3c_b1_targets/6KMQ_AB/6KMQ_AB_A.a3m
# 6KMQ_AB target_msa_report: hpc_outputs/m6d_w3c_b1_targets/6KMQ_AB/6KMQ_AB_A.a3m.report.json
# 6SGE_AB source_pdb: hpc_outputs/m6d_w3c_sources/source_6SGE.pdb
# 6SGE_AB prepared_pdb: hpc_outputs/m6d_w3c_b1_targets/6SGE_AB/prepared_6SGE_AB.pdb
# 6SGE_AB prep_report: hpc_outputs/m6d_w3c_b1_targets/6SGE_AB/prepared_6SGE_AB.report.json
# 6SGE_AB target_fasta: hpc_outputs/m6d_w3c_b1_targets/6SGE_AB/6SGE_AB_A.fasta
# 6SGE_AB target_fasta_report: hpc_outputs/m6d_w3c_b1_targets/6SGE_AB/6SGE_AB_A.fasta.report.json
# 6SGE_AB target_msa: hpc_outputs/m6d_w3c_b1_targets/6SGE_AB/6SGE_AB_A.a3m
# 6SGE_AB target_msa_report: hpc_outputs/m6d_w3c_b1_targets/6SGE_AB/6SGE_AB_A.a3m.report.json
# 7B5G_AB source_pdb: hpc_outputs/m6d_w3c_sources/source_7B5G.pdb
# 7B5G_AB prepared_pdb: hpc_outputs/m6d_w3c_b1_targets/7B5G_AB/prepared_7B5G_AB.pdb
# 7B5G_AB prep_report: hpc_outputs/m6d_w3c_b1_targets/7B5G_AB/prepared_7B5G_AB.report.json
# 7B5G_AB target_fasta: hpc_outputs/m6d_w3c_b1_targets/7B5G_AB/7B5G_AB_A.fasta
# 7B5G_AB target_fasta_report: hpc_outputs/m6d_w3c_b1_targets/7B5G_AB/7B5G_AB_A.fasta.report.json
# 7B5G_AB target_msa: hpc_outputs/m6d_w3c_b1_targets/7B5G_AB/7B5G_AB_A.a3m
# 7B5G_AB target_msa_report: hpc_outputs/m6d_w3c_b1_targets/7B5G_AB/7B5G_AB_A.a3m.report.json

# rerun_manifest_after_msa
# python -m bio_sfm_designer.experiments.complex_target_manifest --manifest configs/m6d_w3c_b1_target_msa_manifest.json --require-files --min-targets 8 --min-contacts 20 --out results/m6d_w3c_b1_target_manifest_pre_msa.json
