import json
import os
from pathlib import Path

path = Path('docs/proof/evidence.json')
if path.exists():
    report = json.loads(path.read_text())
    lines = ['## Executable proof', '', 'Source commit: `' + report['source_commit'] + '`', '', '| Scenario | Result | Exit |', '|---|---|---|']
    for case in report['cases']:
        lines.append('| ' + case['name'].replace('|', '/') + ' | ' + ('PASS' if case['passed'] else 'FAIL') + ' | ' + str(case['exit']) + ' |')
    lines.extend(['', 'Download execution-proof for the complete transcript, SHA-256 input fingerprints, structured results and rendered execution.'])
    if os.environ.get('GITHUB_STEP_SUMMARY'):
        with open(os.environ['GITHUB_STEP_SUMMARY'], 'a') as stream:
            stream.write('\n'.join(lines) + '\n')
