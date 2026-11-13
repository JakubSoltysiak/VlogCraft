"""Local-only privacy/integrity gate. Never print original filenames, hashes or metadata."""
import argparse,hashlib,json,subprocess
from pathlib import Path
def audit(manifest,verify):
 rows=json.loads(manifest.read_text());forbidden=set();content_ids=set();changed=0;missing=0
 for row in rows:
  path=Path(row['path'])
  forbidden.update(x.encode('utf8').lower() for x in (path.name,str(path),str(path).replace('\\','/'),row['sha256_before']))
  if not path.is_file():missing+=1;continue
  if verify:
   h=hashlib.sha256();g=hashlib.sha1(b'blob '+str(path.stat().st_size).encode()+b'\0')
   with path.open('rb') as handle:
    while data:=handle.read(8*1024*1024):h.update(data);g.update(data)
   content_ids.add(g.hexdigest());changed+=h.hexdigest()!=row['sha256_before'] or path.stat().st_mtime_ns!=row['mtime_ns']
  probe=manifest.parent/(row['alias']+'-probe.json')
  if probe.is_file():
   doc=json.loads(probe.read_text())
   for node in [doc.get('format',{}),*doc.get('streams',[])]:
    for key,value in node.get('tags',{}).items():
     if any(k in key.lower() for k in ('location','gps','creation','serial','device_id')) and len(str(value))>=8:
      forbidden.add(str(value).encode('utf8').lower())
 objects=subprocess.check_output(['git','rev-list','--objects','--all']).decode().splitlines()
 names={Path(row['path']).name.lower() for row in rows}
 history_paths=sum(1 for row in objects if row.split(' ',1)[-1].replace('\\','/').lower().split('/')[-1] in names)
 ids={row.split(' ',1)[0] for row in objects};content_hits=len(ids&content_ids)
 found=0;process=subprocess.Popen(['git','cat-file','--batch'],stdin=subprocess.PIPE,stdout=subprocess.PIPE)
 try:
  for ident in ids:
   process.stdin.write((ident+'\n').encode());process.stdin.flush();header=process.stdout.readline().split();size=int(header[2]);data=process.stdout.read(size);process.stdout.read(1)
   if b'\0' not in data and any(secret in data.lower() for secret in forbidden):found+=1
 finally:process.stdin.close();process.wait()
 working=subprocess.check_output(['git','ls-files','--cached','--others','--exclude-standard','-z']).decode().split('\0')
 local_hits=0;private_tracked=0
 for name in working:
  if not name:continue
  if name.replace('\\','/').lower().startswith('sample videos/'):private_tracked+=1
  path=Path(name)
  if path.is_file() and path.stat().st_size<8*1024*1024:
   data=path.read_bytes()
   if b'\0' not in data and any(secret in data.lower() for secret in forbidden):local_hits+=1
 result={'source_count':len(rows),'private_folder_tracked_files':private_tracked,'private_history_path_matches':history_paths,
         'private_content_objects':content_hits,'private_text_objects':found,'private_working_text_files':local_hits,
         'missing_originals':missing,'original_hashes_verified':verify,'changed_originals':changed}
 return result
if __name__=='__main__':
 p=argparse.ArgumentParser();p.add_argument('manifest',type=Path);p.add_argument('--verify-hashes',action='store_true');p.add_argument('--result',type=Path)
 a=p.parse_args();result=audit(a.manifest,a.verify_hashes)
 if a.result:a.result.parent.mkdir(parents=True,exist_ok=True);a.result.write_text(json.dumps(result,indent=2))
 print(json.dumps(result));raise SystemExit(any(result[k] for k in ('private_folder_tracked_files','private_history_path_matches','private_content_objects','private_text_objects','private_working_text_files','missing_originals','changed_originals')))
