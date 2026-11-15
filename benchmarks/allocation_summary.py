"""Whitelisted numeric allocation groups; no raw script URLs or private paths."""
import re

def allocation_summary(profile):
    totals={}
    def visit(node):
        call=node['callFrame'];url=call.get('url','');name=url.split('?',1)[0].replace('\\','/').rsplit('/',1)[-1]
        if name not in ('app.js','audio.js','timebase.js','native_preview.js','recovery.js',''):name='other'
        function=call.get('functionName','')[:120]
        if not re.fullmatch(r'[\w .$<>()[\]-]*',function):function='anonymous'
        key=(name,function);totals[key]=totals.get(key,0)+node.get('selfSize',0)
        for child in node.get('children',[]):visit(child)
    visit(profile['head'])
    return [{'script':k[0],'function':k[1],'sampled_bytes':v} for k,v in sorted(totals.items(),key=lambda p:p[1],reverse=True)[:30]]
