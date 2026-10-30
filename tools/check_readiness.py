"""Run reproducible code checks before planning a new map or NPC batch."""
import argparse,json,subprocess,sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
def main():
 p=argparse.ArgumentParser(description=__doc__);p.add_argument('--out',type=Path,default=ROOT/'output/readiness');a=p.parse_args();a.out.mkdir(parents=True,exist_ok=True);rows=[]
 jobs=[('python-tests',[sys.executable,'-m','unittest','discover','-s','tests']),('npc-builder',[sys.executable,'foundry_builder/project_audit.py']),('documentation',[sys.executable,'tools/check_docs.py'])]
 for name,command in jobs:
  with (a.out/(name+'.log')).open('w',encoding='utf-8') as log:r=subprocess.run(command,cwd=ROOT,stdout=log,stderr=subprocess.STDOUT)
  rows.append({'check':name,'returncode':r.returncode,'log':name+'.log'})
 report={'format':'wowmap.readiness/1','checks':rows,'passed':all(x['returncode']==0 for x in rows),'scope':'Code/fixtures and mocked Foundry API; asset-specific proofs and real Foundry playtest are separate.'}
 (a.out/'report.json').write_text(json.dumps(report,indent=2)+'\n');print(json.dumps(report));return 0 if report['passed'] else 1
if __name__=='__main__':raise SystemExit(main())
