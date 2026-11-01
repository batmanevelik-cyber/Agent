"""Native Windows checks from the public payload, using a synthetic seed only."""
import argparse
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import platform
import subprocess
import sys
import traceback
import unittest

def load(path):
    spec=importlib.util.spec_from_file_location('public_update',path);module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module);return module

def extract(root,work):
    if work.exists() and any(p.name!='native-windows.log' for p in work.iterdir()):raise RuntimeError('Use an empty isolated CI workspace; existing data is preserved')
    update=load(root/'downloads/Alpha50X_5_4_code_update.py');files=update.unpack_payload()
    if any(name.endswith(('.sqlite','.db','.env','.bin')) for name in files):raise RuntimeError('Non-code payload')
    work.mkdir(parents=True,exist_ok=True)
    for name,value in files.items():(work/name).write_bytes(value)
    sys.path.insert(0,str(work))
    from alpha50x_core import Journal
    seed=work/'alpha50x_migrated_v4.sqlite';journal=Journal(seed)
    journal.deposit_virtual('EUR',100)
    journal.db.execute("INSERT INTO positions VALUES('stocks','AAPL',1)")
    journal.db.execute('CREATE TABLE legacy_position_costs(market TEXT,symbol TEXT,cost_eur REAL,metadata_json TEXT)')
    journal.db.execute("INSERT INTO legacy_position_costs VALUES('stocks','AAPL',10,?)",(json.dumps({'qty':1,'entry_usd':11}),))
    journal.db.execute('CREATE TABLE legacy_import(imported_at_utc TEXT,snapshot_json TEXT)')
    journal.db.execute('INSERT INTO legacy_import VALUES(?,?)',('2026-01-01',json.dumps({'trades':[{'symbol':'AAPL','side':'BUY','price_usd':11}]})))
    journal.close();return update,files

def run(root,work,report_path):
    report={'platform':platform.system(),'python':platform.python_version(),'tested_commit':os.environ.get('GITHUB_SHA'),
        'production_exe_sha256':hashlib.sha256((root/'downloads/Alpha50X_Setup_5_4.exe').read_bytes()).hexdigest(),
        'input_seed':'synthetic only','financial_connections_tested':False,'passed':False}
    work.mkdir(parents=True,exist_ok=True);log=(work/'native-windows.log').open('w',encoding='utf-8')
    try:
        update,files=extract(root,work);os.chdir(work)
        report['stage']='production_exe'
        subprocess.run([str(root/'downloads/Alpha50X_Setup_5_4.exe'),'--verify-only'],stdout=log,stderr=subprocess.STDOUT,timeout=30,check=True)
        report['production_exe_runs_on_windows']=True
        report['stage']='unittest'
        with (work/'unittest.log').open('w',encoding='utf-8') as out:
            result=unittest.TextTestRunner(stream=out,verbosity=2).run(unittest.defaultTestLoader.discover(str(work),'test_*.py'))
        report['unittest']={'total':result.testsRun,'passed':result.testsRun-len(result.errors)-len(result.failures)-len(result.skipped),
            'skipped':len(result.skipped),'failures':[case.id() for case,_ in result.failures],'errors':[case.id() for case,_ in result.errors],
            'synthetic_failure_details':[{'case':case.id(),'tail':'\n'.join(line[:350] for line in detail.splitlines()[-8:])} for case,detail in result.failures+result.errors]}
        if not result.wasSuccessful():raise RuntimeError('Native unit tests failed')
        report['stage']='mcp_dependencies_and_protocol'
        sdk=work/'protocol-sdk';subprocess.run([sys.executable,'-m','venv',str(sdk)],check=True,stdout=log,stderr=subprocess.STDOUT,timeout=60)
        sdk_python=sdk/'Scripts/python.exe'
        subprocess.run([str(sdk_python),'-m','pip','install','--disable-pip-version-check','-r',str(work/'requirements-mcp.txt')],check=True,stdout=log,stderr=subprocess.STDOUT,timeout=300)
        subprocess.run([str(sdk_python),str(work/'alpha50x_mcp_smoke.py')],check=True,stdout=log,stderr=subprocess.STDOUT,timeout=90)
        report['native_mcp_offline_protocol']=True
        report['stage']='chromium_705_assets'
        subprocess.run([sys.executable,str(root/'tools/browser_smoke.py'),str(work/'browser')],env={**os.environ,'PYTHONPATH':str(work),'ALPHA50X_BROWSER_STRESS':'1'},check=True,stdout=log,stderr=subprocess.STDOUT,timeout=120)
        report['native_chromium_705_assets']=True
        report['stage']='installer_with_synthetic_seed'
        # Installer integration replaces the in-memory test fixture's seed and
        # manifest only. The published EXE/updater bytes remain untouched.
        fixture={**files,'alpha50x_migrated_v4.sqlite':(work/'alpha50x_migrated_v4.sqlite').read_bytes()}
        fixture['release-manifest.json']=json.dumps({name:hashlib.sha256(value).hexdigest() for name,value in fixture.items() if name!='release-manifest.json'},sort_keys=True).encode()
        installed=update.install(work/'Installed Synthetic',use_current=True,files=fixture)
        report['installer_with_synthetic_seed']=installed['installed'];report['passed']=True;report['stage']='complete'
    except Exception as error:
        report['failure_type']=type(error).__name__;traceback.print_exc(file=log)
    finally:
        log.close();report_path.parent.mkdir(parents=True,exist_ok=True);report_path.write_text(json.dumps(report,indent=2),encoding='utf-8')
    return 0 if report['passed'] else 1

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--work',type=Path,required=True);p.add_argument('--report',type=Path);p.add_argument('--extract',action='store_true');args=p.parse_args()
    repo=Path(__file__).resolve().parents[1]
    if args.extract:extract(repo,args.work)
    else:raise SystemExit(run(repo,args.work,args.report))
