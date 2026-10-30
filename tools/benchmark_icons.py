"""Synthetic ZIP-opening benchmark; pixel output must remain byte-identical."""
import gzip,hashlib,io,json,statistics,sys,tempfile,time
from pathlib import Path
from unittest.mock import patch
from zipfile import ZipFile
from PIL import Image
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from wowmap.icons import IconAssets

def main():
 with tempfile.TemporaryDirectory() as tmp:
  root=Path(tmp);rows=[];names=[]
  with ZipFile(root/'icons.zip','w') as z:
   for n in range(5000):z.writestr(f'unused/entry_{n:05d}.bin',b'x')
   for i in range(100):
    name=f'interface/icons/audit_{i:03d}.png';buffer=io.BytesIO();Image.new('RGBA',(32,32),(i,200-i,100,180)).save(buffer,format='PNG');raw=buffer.getvalue();z.writestr(name,raw);names.append(name);rows.append({'path':name,'member':name,'package':'icons.zip','size':len(raw),'id':'raw:'+hashlib.sha256(raw).hexdigest()})
  with gzip.open(root/'catalog.jsonl.gz','wt',encoding='utf-8') as f:f.write('\n'.join(json.dumps(r) for r in rows))
  samples={'individual':[],'session':[]};opens={};baseline=None
  for repeat in range(5):
   for mode in (['individual','session'] if repeat%2==0 else ['session','individual']):
    icons=IconAssets(root);start=time.perf_counter()
    with patch('wowmap.icons.ZipFile',wraps=ZipFile) as opened:
     if mode=='session':
      with icons.session():
       for n in names:icons.select(n)
     else:
      for n in names:icons.select(n)
     opens[mode]=opened.call_count
    samples[mode].append(time.perf_counter()-start)
    if baseline is None:baseline=icons.images
    else:assert icons.images==baseline
  print(json.dumps({'scope':'100 selected synthetic PNG icons in a ZIP with 5100 entries, five alternating runs on this machine','zip_opens':opens,'median_seconds':{k:statistics.median(v) for k,v in samples.items()},'output_bytes_identical':True}))
if __name__=='__main__':main()
