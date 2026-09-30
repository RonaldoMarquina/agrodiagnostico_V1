from pathlib import Path
import subprocess, tempfile, shutil, hashlib, json, time, os
root=Path.cwd(); work=Path(tempfile.mkdtemp(prefix='agro-acceptance-')); snapshot=work/'snapshot'; snapshot.mkdir(); artifacts=root/'.local/ci/group7-acceptance'; meta=root/'.local/ci/group7-provenance.json'
paths=subprocess.check_output(['git','ls-files','--cached','--others','--exclude-standard','-z']).decode().split('\0')
hashes={}
for name in paths:
 if not name or name.split('/')[0] in ('.agents','.codex'): continue
 p=root/name
 if not p.is_file(): continue
 target=snapshot/name; target.parent.mkdir(parents=True,exist_ok=True); shutil.copy2(p,target); hashes[name]=hashlib.sha256(p.read_bytes()).hexdigest()
for command in (['git','init','-q'],['git','add','.'],['git','-c','user.name=Acceptance Snapshot','-c','user.email=acceptance@localhost','commit','-qm','Temporary acceptance snapshot; not published']): subprocess.run(command,cwd=snapshot,check=True)
checkout=work/'checkout'; subprocess.run(['git','clone','--quiet','--no-local',str(snapshot),str(checkout)],check=True)
assert not subprocess.check_output(['git','status','--porcelain'],cwd=checkout)
record={'started_utc':time.strftime('%Y-%m-%dT%H:%M:%SZ',time.gmtime()),'temporary_revision':subprocess.check_output(['git','rev-parse','HEAD'],cwd=checkout,text=True).strip(),'original_revision':'sin commit','clean_checkout':True,'source_sha256':hashes,'commands':[],'remote_status':'workflow remoto no ejecutado; git ls-remote origin no devuelve referencias'}
meta.parent.mkdir(parents=True,exist_ok=True)
try:
 for command in (['bash','scripts/prepare_ci.sh'],['python3','scripts/run_ci.py','--artifacts',str(artifacts)]):
  start=time.monotonic(); result=subprocess.run(command,cwd=checkout); record['commands'].append({'command':command,'exit_code':result.returncode,'duration_seconds':round(time.monotonic()-start,3)}); meta.write_text(json.dumps(record,indent=2)+'\n'); result.check_returncode()
finally:
 record['finished_utc']=time.strftime('%Y-%m-%dT%H:%M:%SZ',time.gmtime()); meta.write_text(json.dumps(record,indent=2)+'\n'); shutil.rmtree(work)
