"""Exercise download-vs-navigation routing; cancel the actual SDK download before its dialog."""
import argparse,json,sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT/'benchmarks'))
from windows_session import session

def main(a):
 a.results=a.results.resolve();a.results.mkdir(parents=True,exist_ok=True);marker=a.results/'download-started.json';entry=a.results/'download-host.py'
 entry.write_text('import sys\nfrom pathlib import Path\nsys.path.insert(0,'+repr(str(ROOT))+')\nfrom webview.platforms.edgechromium import EdgeChrome\ndef cancel(self,sender,args):\n args.Cancel=True\n Path('+repr(str(marker))+').write_text(\'{"download_started":true}\')\nEdgeChrome.on_download_starting=cancel\nimport desktop\ndesktop.run(Path(sys.argv[sys.argv.index("--project")+1]))\n',encoding='utf8')
 with session(Path(sys.executable),a.results,offline=True,entrypoint=entry) as (page,proc,project,errors):
  browser_cdp=page.context.browser.new_browser_cdp_session();browser_cdp.send('Browser.setDownloadBehavior',{'behavior':'allow','downloadPath':str(a.results/'downloads'),'eventsEnabled':True})
  folder=project.parent/(project.name+'.data')/'reviews';folder.mkdir(exist_ok=True);(folder/'qa-probe.bin').write_bytes(b'generated download probe')
  page.evaluate("""()=>{const link=$('reviewPackLink').cloneNode(true);link.id='qa-download';link.href='/download/qa-probe.bin';link.hidden=false;link.textContent='Download probe';link.style='position:fixed;left:50px;top:50px;z-index:99999;display:block';document.body.append(link);}""")
  page.locator('#qa-download').click();page.wait_for_timeout(300);ordinary=any(p.is_file() and p.read_bytes()==b'generated download probe' for p in (a.results/'downloads').glob('*'))
  if not ordinary:
   page.locator('#qa-download').evaluate("e=>e.download='qa-probe.bin'");page.locator('#qa-download').click();page.wait_for_timeout(500)
  result={'original_markup_download_started':ordinary,'explicit_download_received':any(p.is_file() and p.read_bytes()==b'generated download probe' for p in (a.results/'downloads').glob('*')),'editor_remained_loaded':page.evaluate('!!state?.desktop'),'browser_errors':errors,
          'scope':'Actual generated download bytes verified through CDP download handling; native Save dialog itself is not exercised'}
  (a.results/'download.json').write_text(json.dumps(result,indent=2)+'\n',encoding='utf8');print(json.dumps(result),flush=True)
  assert result['explicit_download_received'] and result['editor_remained_loaded'] and not errors
if __name__=='__main__':
 p=argparse.ArgumentParser();p.add_argument('results',type=Path);main(p.parse_args())
