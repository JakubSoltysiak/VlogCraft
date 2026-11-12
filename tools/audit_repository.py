"""Scan all reachable history without printing suspected credential contents."""
import json
import re
import subprocess
import sys

PATTERNS={
    'provider credential': rb'(?:sk-(?:proj-|svcacct-)?[A-Za-z0-9_-]{20,}|gh[pousr]_[A-Za-z0-9]{20,}|github_pat_[A-Za-z0-9_]{25,}|AKIA[A-Z0-9]{16})',
    'private key': rb'-----BEGIN (?:RSA |EC |OPENSSH |DSA )?PRIVATE KEY-----',
    'credential URL': rb'https?://[^\s<>"]{1,80}:[^\s<>"]{5,80}@',
    'literal secret': rb'(?im)^\s*(?:password|passwd|secret|api[_-]?key|access[_-]?token)\s*=\s*["\x27][^"\x27\r\n]{8,}["\x27]',
}
FORBIDDEN=re.compile(r'(?i)(?:^|/)(?:\.env(?:\..*)?|credentials[^/]*|id_rsa|[^/]*\.(?:vlogcraft|mp4|mov|mkv|msi|exe|dll|zip|pfx|pem))$')


def audit():
    rows=subprocess.check_output(['git','rev-list','--objects','--all']).decode('utf8').splitlines()
    objects={row.split(' ',1)[0]:row.split(' ',1)[1] if ' ' in row else '' for row in rows}
    findings=[];count=0
    process=subprocess.Popen(['git','cat-file','--batch'],stdin=subprocess.PIPE,stdout=subprocess.PIPE)
    try:
        for sha,path in objects.items():
            process.stdin.write((sha+'\n').encode());process.stdin.flush()
            header=process.stdout.readline().split();size=int(header[2])
            data=process.stdout.read(size);process.stdout.read(1)
            if header[1] not in (b'blob',b'commit',b'tag'):continue
            if header[1]==b'blob':
                count+=1
                if size>5*1024**2:findings.append({'path':path,'object':sha,'rule':'large tracked object'})
                if FORBIDDEN.search(path):findings.append({'path':path,'object':sha,'rule':'private/generated file type'})
            if b'\0' in data:continue
            for rule,pattern in PATTERNS.items():
                if re.search(pattern,data):findings.append({'path':path,'object':sha,'rule':rule})
    finally:
        process.stdin.close();process.wait()
    return {'objects':len(objects),'blobs':count,'findings':findings}


if __name__=='__main__':
    result=audit();print(json.dumps(result,indent=2))
    sys.exit(bool(result['findings']))
