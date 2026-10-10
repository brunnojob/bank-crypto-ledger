import json
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

def run(argv, expected=0):
    result = subprocess.run(argv, cwd=ROOT, capture_output=True, text=True, timeout=30)
    if result.returncode != expected:
        raise RuntimeError(result.stderr + result.stdout)
    return result.stdout

with tempfile.TemporaryDirectory() as temp:
    path=Path(temp)/'ledger.log'
    argv=['java','-cp','target/classes','io.brunnodev.ledger.Journal',str(path)]
    first=json.loads(run(argv+['post','receipt-001','cash','revenue','BRL','1250']))
    replay=json.loads(run(argv+['post','receipt-001','cash','revenue','BRL','1250']))
    recovered=json.loads(run(argv+['report']))
    assert first==replay==recovered and recovered['balanced']
    assert sum(recovered['balancesMinor'].values())==0
    print(json.dumps({'recovered':recovered,'idempotent_replay':True},sort_keys=True))
