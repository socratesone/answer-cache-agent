"""Protocol-level acceptance against an INSTALLED executable; no provider calls.
Run with a new --data directory. It redirects LOCALAPPDATA only for the child host.
This does not claim an actual Chrome browser connection.
"""
import argparse
import json
import os
from pathlib import Path
import struct
import subprocess
import uuid

p = argparse.ArgumentParser()
p.add_argument('--install', type=Path, required=True)
p.add_argument('--data', type=Path, required=True)
p.add_argument('--reopen', action='store_true')
a = p.parse_args()
a.install = a.install.resolve()
a.data = a.data.resolve()
if not a.reopen:
    a.data.mkdir(parents=True, exist_ok=False)
manifest = json.loads((a.install / 'native-host.json').read_text())
origin = manifest['allowed_origins'][0]
exe = a.install / 'questionnaire-host.exe'
assert Path(manifest['path']) == exe
contract = json.loads((a.install / '_internal/questionnaire_host/contract.json').read_text())
env = {k: v for k, v in os.environ.items() if not k.startswith(('PYTHON', 'CONDA', 'VIRTUAL_ENV', 'OPENAI', 'ANTHROPIC', 'LANGCHAIN', 'LANGSMITH', 'HF_TOKEN', 'HUGGING_FACE_HUB_TOKEN'))}
env.update(LOCALAPPDATA=str(a.data), PATH=os.path.join(os.environ['SystemRoot'], 'System32'),
           HF_HUB_OFFLINE='1', HF_HOME=str(a.data / 'empty-model-cache'))

def run(commands):
    frames = b''
    for op, data in commands:
        body = json.dumps(dict(id=str(uuid.uuid4()), protocol=1, fingerprint=contract['fingerprint'], operation=op, data=data)).encode()
        frames += struct.pack('<I', len(body)) + body
    proc = subprocess.run([str(exe), origin], input=frames, capture_output=True, cwd=a.data, env=env, timeout=180)
    assert proc.returncode == 0, (proc.returncode, proc.stderr.decode(errors='replace'))
    results = []
    raw = proc.stdout
    while raw:
        assert len(raw) >= 4, raw
        size = struct.unpack('<I', raw[:4])[0]
        result = json.loads(raw[4:4 + size])
        assert result['ok'], result
        results.append(result['data'])
        raw = raw[4 + size:]
    assert len(results) == len(commands), results
    return results

if not a.reopen:
    results = run([
        ('hello', {}),
        ('configure', {'budget': 0.25, 'provider': 'openai', 'key': 'PACKAGING_FAKE_KEY_NOT_A_PROVIDER_CREDENTIAL'}),
        ('ingest', {'record': {'kind': 'variable', 'id': 'packaging_name', 'safe_description': 'Synthetic test label'}}),
        ('binding', {'id': 'packaging_name', 'value': 'PACKAGING_SYNTHETIC_PRIVATE'}),
        ('ingest', {'record': {'kind': 'template', 'id': 'T_packaging', 'intent': 'testing', 'aliases': ['What do you test?'],
                             'body': 'I test installers.', 'disclosure': 'local_only', 'approved_by': 'packaging-test', 'approved_at': '2026-09-22'}}),
        ('event', {'event': {'event_id': str(uuid.uuid4()), 'session_id': 'packaging-session', 'scope_id': 'user-default',
                            'type': 'prepare_form', 'expected_revision': None, 'payload': {'questions': [{'id': 'q', 'text': 'What do you test?'}]}}}),
        ('diagnostics', {}),
    ])
    assert results[0]['version'] == '0.1.1' and results[0]['configured'] is False
    assert results[-2]['status'] == 'ready'
    assert results[-1]['engineLoaded'] is True

results = run([('settings', {}), ('search', {'query': 'What do you test?'}),
               ('render', {'body': '{{packaging_name}}', 'constraints': {}})])
assert results[0]['budget']['max_session_cost_usd'] == 0.25
assert results[0]['configured'] is True
assert any(x['id'] == 'T_packaging' for x in results[1]['matches'])
assert results[2]['text'] == 'PACKAGING_SYNTHETIC_PRIVATE'
if not a.reopen:
    edited = run([('template_update', {'id': 'T_packaging', 'intent': 'Installation testing',
                                      'body': 'I verify installed applications.',
                                      'alias': 'What do you test?', 'expected_version': 1})])[0]
    assert edited['id'] == 'T_packaging' and edited['version'] == 2
    saved = run([('template_get', {'id': 'T_packaging'}), ('search', {'query': 'Installation testing'})])
    assert saved[0]['body'] == 'I verify installed applications.'
    assert any(x['id'] == 'T_packaging' for x in saved[1]['matches'])
store = a.data / 'SocratesOne/QuestionnaireAssistant'
assert b'PACKAGING_SYNTHETIC_PRIVATE' not in (store / 'private.dpapi').read_bytes()
assert b'PACKAGING_FAKE_KEY' not in (store / 'private.dpapi').read_bytes()
assert (store / 'answer_cache.db').is_file()
wrong = subprocess.run([str(exe), 'https://invalid.example/'], input=b'', capture_output=True, cwd=a.data, env=env, timeout=30)
assert wrong.returncode == 2 and not wrong.stdout
print('INSTALLED_PROTOCOL_OK: bundled real ONNX model, SQLite/vector search, config, DPAPI, reconnect, origin rejection; zero provider calls')
