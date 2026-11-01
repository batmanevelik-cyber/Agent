"""Reproducible code-only Windows bootstrap; requires an official Go toolchain."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile

def main():
    parser=argparse.ArgumentParser();parser.add_argument('--go',default='go');parser.add_argument('--test-only',action='store_true');args=parser.parse_args()
    root=Path(__file__).resolve().parents[1];updater=root/'downloads/Alpha50X_5_5_1_code_update.py'
    digest=hashlib.sha256(updater.read_bytes()).hexdigest()
    build_env={**os.environ,'GOTOOLCHAIN':'local','GOTELEMETRY':'off','ALPHA50X_TEST_PYTHON':sys.executable}
    with tempfile.TemporaryDirectory(prefix='alpha50x-setup-build-') as tmp:
        work=Path(tmp)
        for name in ('windows_setup.go','windows_setup_test.go'):shutil.copy2(root/'tools'/name,work/name)
        shutil.copy2(updater,work/updater.name)
        subprocess.run([args.go,'test','-v','windows_setup.go','windows_setup_test.go'],cwd=work,env=build_env,check=True)
        if args.test_only:return
        flags=['-trimpath','-buildvcs=false','-ldflags=-s -w -X main.payloadDigest='+digest]
        native=work/('verify.exe' if os.name=='nt' else 'verify')
        subprocess.run([args.go,'build',*flags,'-o',str(native),'windows_setup.go'],cwd=work,env=build_env,check=True)
        subprocess.run([str(native),'--verify-only'],check=True)
        output=root/'downloads/Alpha50X_Setup_5_5_1.exe'
        subprocess.run([args.go,'build',*flags,'-o',str(output),'windows_setup.go'],cwd=work,env={**build_env,'GOOS':'windows','GOARCH':'amd64','CGO_ENABLED':'0'},check=True)
        print(json.dumps({'artifact':str(output),'sha256':hashlib.sha256(output.read_bytes()).hexdigest(),'bytes':output.stat().st_size,'code_updater_sha256':digest}))

if __name__=='__main__':main()
