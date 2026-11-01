"""Repack verified 5.5.1 code with explicitly reviewed crypto activity changes."""
import argparse
import ast
import base64
import hashlib
import importlib.util
import io
import json
from pathlib import Path
import zipfile

BASE_SHA256 = '986aae6b519b8f76fbe78806693280379113a4e6be28c6e7a4a5df6ddafa3e08'
SEED_SHA256 = 'd41aa1a8f95c886df82964cb3029e959c49c07ef0239057b1517ff7878c7a26e'
ALLOWED = {'alpha50x_runtime.py', 'alpha50x_auto.py', 'alpha50x_crypto_activity.py',
           'alpha50x_terminal_v55.html', 'alpha50x_ui_v55.py', 'alpha50x_workspace_ui.py',
           'alpha50x_web.py', 'alpha50x_diagnostics.py', 'test_alpha50x_crypto_activity.py', 'UPDATE_5_6.md'}


def build(source, root):
    base = root/'downloads/Alpha50X_5_5_1_code_update.py'
    assert hashlib.sha256(base.read_bytes()).hexdigest() == BASE_SHA256
    spec = importlib.util.spec_from_file_location('base_updater', base)
    module = importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
    original = module.unpack_payload();files = dict(original)
    for name, value in original.items():
        if name not in ALLOWED and name != 'release-manifest.json':
            assert (source/name).read_bytes() == value, 'Unreviewed change: '+name
    for name in ALLOWED:
        files[name] = (source/name).read_bytes()
    changed = {name for name, value in files.items() if original.get(name) != value}
    assert changed and changed <= ALLOWED
    assert not any(name.endswith(('.sqlite', '.db', '.env', '.bin')) for name in files)
    manifest = json.loads(original['release-manifest.json'])
    assert manifest['alpha50x_migrated_v4.sqlite'] == SEED_SHA256
    for name, value in files.items():
        if name != 'release-manifest.json':
            manifest[name] = hashlib.sha256(value).hexdigest()
    files['release-manifest.json'] = (json.dumps(manifest, sort_keys=True, indent=2)+'\n').encode()
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, 'w', zipfile.ZIP_DEFLATED, compresslevel=9) as archive:
        for name, value in sorted(files.items()):
            info = zipfile.ZipInfo(name, date_time=(2026, 1, 1, 0, 0, 0))
            info.compress_type = zipfile.ZIP_DEFLATED;info.external_attr = 0o600 << 16
            archive.writestr(info, value)
    raw = buffer.getvalue();code = base.read_text(encoding='utf-8')
    tree = ast.parse(code)
    replacements = {'PAYLOAD': base64.b85encode(raw).decode(), 'PAYLOAD_SHA256': hashlib.sha256(raw).hexdigest()}
    for node in tree.body:
        if isinstance(node, ast.Assign) and len(node.targets) == 1 and isinstance(node.targets[0], ast.Name) and node.targets[0].id in replacements:
            old = ast.get_source_segment(code, node)
            assert code.count(old) == 1
            code = code.replace(old, node.targets[0].id+'='+repr(replacements[node.targets[0].id]))
    ast.parse(code)
    output = root/'downloads/Alpha50X_5_6_code_update.py'
    output.write_text(code, encoding='utf-8')
    return {'output': str(output), 'changed_application_files': sorted(changed),
            'seed_sha256_retained': SEED_SHA256, 'embedded_customer_database': False,
            'sha256': hashlib.sha256(output.read_bytes()).hexdigest()}


if __name__ == '__main__':
    parser = argparse.ArgumentParser();parser.add_argument('--source', type=Path, required=True);args = parser.parse_args()
    print(json.dumps(build(args.source, Path(__file__).resolve().parents[1]), indent=2))
