"""Optional real Chromium DOM smoke; requires local Chromium and socket access."""
import base64
import json
import os
from pathlib import Path
import shutil
import signal
import subprocess
import sys
import tempfile
import threading
import time
from urllib.request import urlopen
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from websockets.sync.client import connect
from test_alpha50x_unified import RuntimeTests
from alpha50x_web import make_server
from alpha50x_stream import SpotStream
from test_alpha50x_unified import NOW

def main():
    output=Path(sys.argv[1] if len(sys.argv)>1 else '/tmp/alpha50x-browser-results');output.mkdir(parents=True,exist_ok=True)
    case=RuntimeTests();case.setUp();supervisor=case.make_supervisor();supervisor.engine.arm('ENABLE PAPER');supervisor.cycle();supervisor.engine.pause()
    stress=os.environ.get('ALPHA50X_BROWSER_STRESS')=='1'
    if stress:
        from alpha50x_runtime import load_config
        from alpha50x_models import FX
        from test_alpha50x_unified import quote
        from dataclasses import replace
        lists=load_config()['watchlists'];lists['derivatives']=['1000BONKUSDT',*['CONTRACT'+str(i)+'USDT' for i in range(521)]]
        crypto_count=int(os.environ.get('ALPHA50X_BROWSER_CRYPTO_COUNT',len(lists['crypto'])))
        lists['crypto'] += ['MOCKCOIN'+str(i)+'USDT' for i in range(max(0,crypto_count-len(lists['crypto'])))]
        supervisor.config['watchlists']=lists;supervisor.config['enabled_markets']=list(lists)
        rates={currency:FX(currency,1,1,NOW,'MOCK STRESS FX') for currency in ('USDT','USD','EUR','GBP','JPY','CHF','CAD','AUD','NZD')}
        quotes=[]
        for market,symbols in lists.items():
            for i,symbol in enumerate(symbols):
                if (market,symbol)==('crypto','BTCUSDT'):continue
                currency=symbol[3:] if market=='forex' else 'USD' if market=='stocks' else 'USDT'
                price=.00003 if symbol=='1000BONKUSDT' else 10+i*.07
                quotes.append(replace(quote(NOW,market,symbol,price),currency=currency,source='MOCK STRESS'))
        supervisor.ingest(quotes,rates,now=NOW)
        supervisor.providers.company_data=lambda kind,symbol:{'source':'MOCK COMPANY DATA','symbol':symbol,'kind':kind,'received_ms':NOW,
            'data':{'quarterlyEarnings':[{'reportedDate':'2026-10-20','fiscalDateEnding':'2026-09-30','reportedEPS':'2','estimatedEPS':'1.9','surprisePercentage':'5.2'}]},'trading_signal':False}
    server=make_server(supervisor,0);thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
    profile=tempfile.TemporaryDirectory(prefix='alpha50x-cdp-');log=(output/'chromium.log').open('w')
    binary=shutil.which('chromium') or shutil.which('google-chrome') or shutil.which('chrome')
    if not binary and os.name=='nt':
        binary=next((str(p) for base in (os.environ.get('PROGRAMFILES',''),os.environ.get('PROGRAMFILES(X86)','')) for p in (Path(base)/'Google/Chrome/Application/chrome.exe',Path(base)/'Microsoft/Edge/Application/msedge.exe') if p.is_file()),None)
    if not binary:raise RuntimeError('Chromium unavailable')
    proc=subprocess.Popen([binary,'--headless','--no-sandbox','--disable-dev-shm-usage','--disable-background-networking','--disable-gpu','--no-first-run','--user-data-dir='+profile.name,'--remote-debugging-port=0','about:blank'],stdout=subprocess.DEVNULL,stderr=log,start_new_session=True)
    try:
        active=Path(profile.name)/'DevToolsActivePort'
        for _ in range(100):
            if active.exists():break
            time.sleep(.1)
        if not active.exists():raise RuntimeError('Chromium DevTools did not start')
        port=active.read_text().splitlines()[0]
        with urlopen('http://127.0.0.1:'+port+'/json/list') as response:targets=json.load(response)
        page=next(t for t in targets if t['type']=='page');sequence=0;errors=[]
        with connect(page['webSocketDebuggerUrl'],proxy=None,open_timeout=3,max_size=8_000_000) as ws:
            def call(method,params=None):
                nonlocal sequence
                sequence+=1;ws.send(json.dumps({'id':sequence,'method':method,'params':params or {}}))
                while True:
                    message=json.loads(ws.recv(timeout=8))
                    if message.get('method')=='Runtime.exceptionThrown':errors.append(message['params']['exceptionDetails'])
                    if message.get('id')==sequence:
                        if 'error' in message:raise RuntimeError(message['error'])
                        return message.get('result',{})
            call('Page.enable');call('Runtime.enable');call('Emulation.setDeviceMetricsOverride',{'width':1536,'height':1024,'deviceScaleFactor':1,'mobile':False})
            call('Page.navigate',{'url':'http://127.0.0.1:'+str(server.server_port)+('/preview/5.5' if os.environ.get('ALPHA50X_UI_PREVIEW') else '/terminal')})
            for _ in range(50):
                body=call('Runtime.evaluate',{'expression':'document.body.innerText','returnByValue':True}).get('result',{}).get('value','')
                if 'АКТУАЛНИ ЦЕНИ' in body:break
                time.sleep(.1)
            (output/'initial-body.txt').write_text(body,encoding='utf-8')
            assert not errors,errors
            assert all(value in body for value in ('АКТУАЛНИ ЦЕНИ','Автономен агент','Recent Trades','Market Opportunities','News')),body[:1000]
            if stress:call('Runtime.evaluate',{'expression':"document.querySelector('#watchFilters [data-market=all]').click()"})
            checks=call('Runtime.evaluate',{'expression':"({hidden:document.getElementById('settingsDrawer').hidden,rows:document.getElementById('scanner').children.length,trades:document.getElementById('trades').innerText,cash:document.getElementById('cash').innerText})",'returnByValue':True})['result']['value']
            assert checks['hidden'] and checks['rows']>=1 and 'ПОКУПКА' in checks['trades'] and checks['cash'].startswith('€'),checks
            def evaluate(expression):
                result=call('Runtime.evaluate',{'expression':expression,'returnByValue':True,'awaitPromise':True})
                assert not result.get('exceptionDetails'),result
                return result['result'].get('value')
            # Use the actual settings event path. Scanning mode must persist
            # without arming a paused service or changing its risk limits.
            risk_before=dict(supervisor.config['limits'])
            for mode in ('standard','active'):
                evaluate("(()=>{const e=document.getElementById('axCryptoScanMode');e.value="+json.dumps(mode)+";e.dispatchEvent(new Event('change'));})()")
                for _ in range(50):
                    if supervisor.journal.state('crypto_scan_mode')==mode:break
                    time.sleep(.1)
                assert supervisor.config['crypto_scan_mode']==mode
                assert supervisor.journal.state('crypto_scan_mode')==mode
                assert not supervisor.journal.trading_enabled()
                assert supervisor.config['limits']==risk_before
            assert evaluate("document.getElementById('axCryptoScanInfo').innerText.length")>0
            if stress:assert checks['rows']==sum(map(len,lists.values())),checks
            for width in (1855,1536,1280):
                call('Emulation.setDeviceMetricsOverride',{'width':width,'height':1024,'deviceScaleFactor':1,'mobile':False})
                layout=evaluate("(()=>{const w=document.querySelector('.watch-scroll'),c=document.querySelector('#scanner tr td');return {width:w.clientWidth,scroll:w.scrollWidth,font:parseFloat(getComputedStyle(c).fontSize),page:document.documentElement.scrollWidth,screen:document.documentElement.clientWidth}})()")
                assert layout['scroll']<=layout['width']+1 and layout['font']>=13 and layout['page']<=layout['screen'],layout
                if os.environ.get('ALPHA50X_BROWSER_SCROLL_CHECK')=='1':
                    scroll=evaluate("(()=>{const w=document.querySelector('.watch-scroll'),p=w.closest('article'),y=scrollY;w.scrollTop=240;const result={height:w.clientHeight,content:w.scrollHeight,moved:w.scrollTop,pageMoved:scrollY!==y,panelHeight:p.getBoundingClientRect().height,lowerTop:document.querySelector('.daily-lower').getBoundingClientRect().top+scrollY};w.scrollTop=0;return result})()")
                    assert scroll['height']<=600 and scroll['panelHeight']<900 and scroll['lowerTop']<1800,scroll
                    assert scroll['content']>scroll['height']*2 and scroll['moved']>0 and not scroll['pageMoved'],scroll
            call('Emulation.setDeviceMetricsOverride',{'width':1855 if stress else 1536,'height':1024,'deviceScaleFactor':1,'mobile':False})
            before=evaluate("({price:document.getElementById('axSelectedPrice').innerText,equity:document.getElementById('equity').innerText,chart:document.getElementById('chart').innerHTML})")
            stream=SpotStream(['BTCUSDT']);stream.connected=True;supervisor.stream=stream
            stream.consume({'s':'EURUSDT','b':'1','a':'1.0001','B':'100000','A':'100000'},NOW)
            stream.consume({'s':'BTCUSDT','b':'12','a':'12.001','B':'10000','A':'10000'},NOW)
            for _ in range(30):
                after=evaluate("({price:document.getElementById('axSelectedPrice').innerText,equity:document.getElementById('equity').innerText})")
                if after['price'].startswith('12.00') and after['equity']!=before['equity']:break
                time.sleep(.1)
            assert after['price'].startswith('12.00') and after['equity']!=before['equity'],(before,after)
            if stress:
                evaluate("document.getElementById('axNewsEarnings').click()")
                for _ in range(30):
                    if 'MOCK COMPANY DATA' in evaluate("document.getElementById('axNewsDialog').innerText"):break
                    time.sleep(.1)
                assert '2026-10-20' in evaluate("document.getElementById('axNewsDialog').innerText")
                evaluate("document.getElementById('axNewsDialog').close()")
            interactive=evaluate("!!document.getElementById('axChartZoomIn')")
            if interactive:
                # Check changes in the rendered viewport, not just button labels.
                initial=evaluate("Number(document.getElementById('chart').dataset.visibleCount)")
                evaluate("document.getElementById('axChartZoomIn').click()")
                zoomed=evaluate("Number(document.getElementById('chart').dataset.visibleCount)")
                assert 12<=zoomed<initial,(initial,zoomed)
                evaluate("document.getElementById('axChartZoomOut').click()")
                assert evaluate("Number(document.getElementById('chart').dataset.visibleCount)")>zoomed
                evaluate("document.querySelector('#chart svg').dispatchEvent(new KeyboardEvent('keydown',{key:'ArrowLeft',bubbles:true}))")
                assert evaluate("document.getElementById('chart').dataset.viewportEnd")!='live'
                evaluate("document.getElementById('axChartTrend').click()")
                box=evaluate("(()=>{const r=document.getElementById('chart').getBoundingClientRect();return {x:r.x,y:r.y,w:r.width,h:r.height}})()")
                for x,y in ((.25,.4),(.7,.6)):
                    point={'x':box['x']+box['w']*x,'y':box['y']+box['h']*y}
                    call('Input.dispatchMouseEvent',{'type':'mousePressed','button':'left','clickCount':1,**point})
                    call('Input.dispatchMouseEvent',{'type':'mouseReleased','button':'left','clickCount':1,**point})
                assert evaluate("document.querySelectorAll('#chart [data-annotation=trend]').length")==1
                evaluate("document.getElementById('axChartZoomIn').click()")
                assert evaluate("document.querySelectorAll('#chart [data-annotation=trend]').length")==1
                evaluate("document.getElementById('axChartUndo').click()")
                assert evaluate("document.querySelectorAll('#chart [data-annotation]').length")==0
                evaluate("document.getElementById('axChartReset').click()")
                assert evaluate("document.getElementById('chart').dataset.viewportEnd")=='live'
                evaluate("document.getElementById('axCompareMode').value='strategies';document.getElementById('axCompareMode').dispatchEvent(new Event('change'))")
                for _ in range(50):
                    if 'Сигнал' in evaluate("document.getElementById('axCompareGrid').innerText") or 'Анализ' in evaluate("document.getElementById('axCompareGrid').innerText"):break
                    time.sleep(.1)
                assert evaluate("document.querySelectorAll('.compare-card').length")==3
                assert 'Само сравнение' in evaluate("document.getElementById('axCompareGrid').innerText")
            evaluate("document.querySelector('[data-view=trades]').click()")
            for _ in range(30):
                if evaluate("document.getElementById('axHistoryRows').children.length"):break
                time.sleep(.1)
            assert evaluate("document.getElementById('axHistoryRows').children.length")>=1
            evaluate("document.getElementById('axHistoryRows').firstChild.click()")
            assert 'USDT' in evaluate("document.getElementById('axTradeDetails').innerText")
            (output/'trades.png').write_bytes(base64.b64decode(call('Page.captureScreenshot',{'format':'png'})['data']))
            evaluate("document.getElementById('axHistorySide').value='SELL';document.getElementById('axHistorySide').dispatchEvent(new Event('change'))")
            for _ in range(30):
                if evaluate("document.getElementById('axHistoryCount').innerText")== '0':break
                time.sleep(.1)
            assert evaluate("document.getElementById('axHistoryRows').children.length")==0
            evaluate("document.querySelector('[data-view=strategies]').click()")
            assert 'стратегии' in evaluate("document.getElementById('axLearningMethod').innerText")
            if interactive:
                evaluate("document.getElementById('axStrategyPrompt').value='EMA 9 пресича EMA 26 нагоре, RSI между 45 и 70, стоп 1%, цел 2%. Изход при обратно пресичане.';document.getElementById('axParseStrategy').click()")
                for _ in range(50):
                    if 'RSI 45' in evaluate("document.getElementById('axParsedRules').innerText"):break
                    time.sleep(.1)
                assert 'RSI 45' in evaluate("document.getElementById('axParsedRules').innerText")
                assert 'Цел: 2' in evaluate("document.getElementById('axParsedRules').innerText")
                (output/'strategies.png').write_bytes(base64.b64decode(call('Page.captureScreenshot',{'format':'png'})['data']))
            evaluate("document.querySelector('[data-view=markets]').click()")
            # The prompt action can still be refreshing the shared snapshot
            # when navigation completes. Require the actual expected price,
            # with the same bounded wait used for header/history updates.
            market_rows=''
            for _ in range(50):
                market_rows=evaluate("document.getElementById('axMarketRows').innerText")
                if '12.00 USDT' in market_rows:break
                time.sleep(.1)
            assert '12.00 USDT' in market_rows,market_rows[:700]
            call('Runtime.evaluate',{'expression':"document.querySelector('[data-view=settings]').click()"})
            setup=call('Runtime.evaluate',{'expression':'document.body.innerText','returnByValue':True})['result']['value']
            assert 'Свързване на данни' in setup and 'PAPER_FILLED' in setup,setup[-1800:]
            call('Runtime.evaluate',{'expression':"document.getElementById('axSettingsClose').click();window.scrollTo({top:0,behavior:'instant'})"})
            dimensions=call('Runtime.evaluate',{'expression':'({width:document.documentElement.clientWidth,content:document.documentElement.scrollWidth})','returnByValue':True})['result']['value']
            assert dimensions['content']<=dimensions['width'],dimensions
            assert not errors,errors
            dom=call('Runtime.evaluate',{'expression':'document.documentElement.outerHTML','returnByValue':True})['result']['value']
            (output/'browser-dom.html').write_text(dom,encoding='utf-8')
            (output/'unified-terminal.png').write_bytes(base64.b64decode(call('Page.captureScreenshot',{'format':'png'})['data']))
            evaluate("document.getElementById('axEmergencyStop').click()")
            for _ in range(30):
                if supervisor.journal.state('kill_switch',False):break
                time.sleep(.1)
            assert supervisor.journal.state('kill_switch',False)
            call('Emulation.setDeviceMetricsOverride',{'width':390,'height':844,'deviceScaleFactor':1,'mobile':False})
            dimensions=evaluate('({width:document.documentElement.clientWidth,content:document.documentElement.scrollWidth})')
            assert dimensions['content']<=dimensions['width'],dimensions
            print('PASS: Chromium dashboard '+(str(checks['rows'])+' actual fixture assets; ' if stress else '')+'readable sidebar at 1280/1536/1855 without horizontal scroll; bounded vertical scroll when requested; live price/header; history/filter; navigation; stop; mobile overflow.')
    finally:
        if os.name=='nt':subprocess.run(['taskkill','/PID',str(proc.pid),'/T','/F'],stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
        else:
            try:os.killpg(proc.pid,signal.SIGKILL)
            except ProcessLookupError:pass
        proc.wait(timeout=15);log.close();profile.cleanup()
        server.shutdown();server.server_close();thread.join();supervisor.close();case.tearDown()

if __name__=='__main__':main()
