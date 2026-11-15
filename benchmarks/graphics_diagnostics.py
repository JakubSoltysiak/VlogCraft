"""Read preflight CDP data through an existing session; no browser dependency."""
import re
def graphics_diagnostics(browser):
    cdp=browser.new_browser_cdp_session();result={}
    try:
        try:
            version=cdp.send('Browser.getVersion')
            result['runtime']={k:version[k] for k in ('product','protocolVersion','jsVersion') if k in version}
        except Exception as error:result['runtime_unavailable']=type(error).__name__
        try:
            gpu=cdp.send('SystemInfo.getInfo').get('gpu',{})
            result['devices']=[{k:d[k] for k in ('vendorString','deviceString','driverVersion') if k in d} for d in gpu.get('devices',[])]
            aux=gpu.get('auxAttributes',{})
            result['graphics']={k:aux[k] for k in ('glRenderer','glVersion','displayType','softwareRendering','passthroughCmdDecoder','directRenderingVersion') if k in aux}
            if 'glRenderer' in result['graphics']:
                result['graphics']['glRenderer']=re.sub(r'\s*\(0x[0-9a-fA-F]+\)','',result['graphics']['glRenderer'])
            result['feature_status']=gpu.get('featureStatus',{})
        except Exception as error:result['graphics_unavailable']=type(error).__name__
    finally:cdp.detach()
    return result
