"""Apply exact candidate UI functions to a frozen control host for isolated diagnostics."""
import hashlib
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
def inject(page):
 app=(ROOT/'web/app.js').read_text('utf8');native=(ROOT/'web/native_preview.js').read_text('utf8');audio=(ROOT/'web/audio.js').read_text('utf8')
 patch=audio[audio.index('function updateMeter()'):audio.index('function mixSource(')]
 patch+=app[app.index('function positionPlayhead()'):app.index('function seek(')]
 patch+=native[native.index('function nativeBoundsRect()'):native.index('function nativeSignature()')]
 patch+=native[native.index('async function nativePrepare()'):native.index('async function nativePlayPause()')]
 page.evaluate('source=>{(0,eval)(source);positionPlayhead();}',patch)
 page.add_style_tag(content='.playhead{will-change:transform}')
 return hashlib.sha256(patch.encode()).hexdigest()
