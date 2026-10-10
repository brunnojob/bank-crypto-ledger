import hashlib
import html
import json
import os
import signal
import subprocess
import sys
import tempfile
import textwrap
import time
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
LIMIT = 2 * 1024 * 1024


def reject(message):
    raise ValueError(message)


def relative(value):
    path = (ROOT / value).resolve()
    if not path.is_relative_to(ROOT):
        reject('path outside repository')
    return path


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def execute(case):
    argv = case['argv']
    if not isinstance(argv, list) or not argv or not all(isinstance(v, str) and v and '\x00' not in v for v in argv):
        reject('argv must contain nonempty strings')
    timeout = case.get('timeout', 120)
    if not isinstance(timeout, int) or not 1 <= timeout <= 900:
        reject('timeout outside supported range')
    data = case.get('stdin', '')
    if 'input' in case:
        data = relative(case['input']).read_text()
    if not isinstance(data, str) or len(data.encode()) > LIMIT:
        reject('input exceeds supported size')
    started = time.monotonic()
    with tempfile.TemporaryFile() as output, tempfile.TemporaryFile() as source:
        source.write(data.encode())
        source.seek(0)
        process = subprocess.Popen(argv, cwd=ROOT, stdin=source, stdout=output, stderr=subprocess.STDOUT, start_new_session=True)
        reason = None
        while process.poll() is None:
            if time.monotonic() - started > timeout:
                reason = 'timeout'
            elif os.fstat(output.fileno()).st_size > LIMIT:
                reason = 'output capacity exceeded'
            if reason:
                os.killpg(process.pid, signal.SIGKILL)
                break
            time.sleep(0.05)
        code = process.wait()
        output.seek(0)
        raw = output.read(LIMIT + 1)
        if len(raw) > LIMIT:
            reason = 'output capacity exceeded'
        transcript = raw[:LIMIT].decode('utf-8', errors='replace')
    passed = reason is None and code == case.get('exit', 0)
    missing = [value for value in case.get('contains', []) if value not in transcript]
    forbidden = [value for value in case.get('absent', []) if value in transcript]
    if missing or forbidden:
        passed = False
    record = {'display': case.get('display', True), 'name': case['name'], 'argv': argv, 'exit': code, 'expected_exit': case.get('exit', 0), 'passed': passed, 'seconds': round(time.monotonic() - started, 3), 'output': transcript, 'output_sha256': hashlib.sha256(raw[:LIMIT]).hexdigest()}
    if reason:
        record['failure'] = reason
    if missing:
        record['missing'] = missing
    if forbidden:
        record['forbidden'] = forbidden
    return record


def preview(report):
    lines = [report['repository'], 'Executed: ' + report['generated_at'], 'Source: ' + report['source_commit'][:12]]
    for case in report['cases']:
        if case.get('display') is False:
            continue
        lines.extend(['', ('PASS ' if case['passed'] else 'FAIL ') + case['name'], '$ ' + ' '.join(case['argv'])])
        interesting = [v.strip() for v in case['output'].splitlines() if v.strip()]
        lines.extend(interesting[:8])
        if len(interesting) > 8:
            lines.append('Full output: evidence.json')
    wrapped = []
    for line in lines:
        wrapped.extend(textwrap.wrap(line, width=106, replace_whitespace=False, drop_whitespace=False) or [''])
    height = 68 + 22 * len(wrapped)
    elements = ['<svg xmlns="http://www.w3.org/2000/svg" width="1100" height="' + str(height) + '" viewBox="0 0 1100 ' + str(height) + '">', '<rect width="1100" height="' + str(height) + '" rx="12" fill="#0d1117"/>', '<title>Recorded program execution</title>', '<g font-family="monospace" font-size="16">']
    for index, line in enumerate(wrapped):
        color = '#3fb950' if line.startswith('PASS ') else '#f85149' if line.startswith('FAIL ') else '#79c0ff' if line.startswith('$ ') else '#c9d1d9'
        elements.append('<text x="24" y="' + str(36 + 22 * index) + '" fill="' + color + '">' + html.escape(line) + '</text>')
    elements.extend(['</g>', '</svg>'])
    return '\n'.join(elements) + '\n'


def main():
    config = json.loads(relative('.proof/scenarios.json').read_text())
    if not isinstance(config.get('cases'), list) or not 1 <= len(config['cases']) <= 30:
        reject('scenario count outside supported range')
    source = subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=ROOT, text=True).strip()
    files = {value: digest(relative(value)) for value in config.get('inputs', [])}
    report = {'schema': 1, 'repository': config['repository'], 'source_commit': source, 'generated_at': datetime.now(timezone.utc).isoformat(), 'run_url': os.environ.get('GITHUB_SERVER_URL', 'https://github.com') + '/' + os.environ.get('GITHUB_REPOSITORY', config['repository']) + '/actions/runs/' + os.environ.get('GITHUB_RUN_ID', 'local'), 'inputs_sha256': files, 'cases': []}
    for case in config['cases']:
        result = execute(case)
        report['cases'].append(result)
        print(('PASS ' if result['passed'] else 'FAIL ') + result['name'])
        print(result['output'])
        if not result['passed']:
            break
    report['passed'] = len(report['cases']) == len(config['cases']) and all(case['passed'] for case in report['cases'])
    target = relative('docs/proof')
    target.mkdir(parents=True, exist_ok=True)
    payload = json.dumps(report, indent=2, ensure_ascii=False, allow_nan=False) + '\n'
    (target / 'evidence.json').write_text(payload)
    (target / 'execution.svg').write_text(preview(report))
    transcript = '\n'.join('$ ' + ' '.join(case['argv']) + '\n' + case['output'] for case in report['cases'])
    (target / 'transcript.txt').write_text(transcript)
    compact = json.loads(payload)
    for case in compact['cases']:
        if len(case['output']) > 3500:
            case['output'] = case['output'][:3500] + '\nFull transcript in the execution-proof artifact.'
    print('PROOF_EVIDENCE_JSON=' + json.dumps(compact, ensure_ascii=True, allow_nan=False))
    return 0 if report['passed'] else 1


if __name__ == '__main__':
    try:
        sys.exit(main())
    except (ValueError, KeyError, OSError, subprocess.SubprocessError) as error:
        print(str(error), file=sys.stderr)
        sys.exit(2)
