"""Screenshots of the running demo site (serve.py) with headless Chrome over the DevTools protocol."""
import asyncio, base64, json, os, subprocess, sys, tempfile, time
import aiohttp, requests

BASE = 'http://127.0.0.1:5055'
CHROME = r'C:\Program Files\Google\Chrome\Application\chrome.exe'
OUT = sys.argv[1]
ONLY = set(sys.argv[2:])
ANDROID_UA = ('Mozilla/5.0 (Linux; Android 14; Pixel 8) AppleWebKit/537.36 (KHTML, like Gecko) '
              'Chrome/126.0.0.0 Mobile Safari/537.36')


def login_student(i):
    s = requests.Session()
    s.post(BASE + '/c/join', data={'code': 'ECON101', 'password': 'nudge'})
    s.post(BASE + '/c/ECON101/signin', data={'step': 'id', 'sis_id': f'91200{i:04d}'})
    s.post(BASE + '/c/ECON101/signin', data={'step': 'password', 'password': 'secret1'})
    for t in ('lobby', 'builder', 'builder_edit'):
        s.post(BASE + f'/c/ECON101/tour/{t}/seen')
    return s.cookies.get('session')


def login_host():
    s = requests.Session()
    s.post(BASE + '/c/host-join', data={'code': 'ECON101', 'password': 'host'})
    return s.cookies.get('session')


COOKIES = {'host': login_host(), 'sofia': login_student(1), 'noah': login_student(4), 'mateo': login_student(7), 'henry': login_student(18)}

DESK = (1280, 900, False)
PHONE = (390, 844, True)
PREVIEW_SUBMITTED = """
document.querySelectorAll('.state-panel').forEach(function(p){p.classList.remove('active')});
document.getElementById('state-submitted').classList.add('active');
document.dispatchEvent(new CustomEvent('survey-submitted', {detail: {surveyId: 2}}));
"""
SHOTS = [
    # name, who, path, viewport, js, selectors, wait
    ('07_editor_top', 'sofia', '/c/ECON101/builder/1/edit', DESK, '', ['#members-card', '#details-card', '#arms-card'], 1.2),
    ('09_group_members', 'sofia', '/c/ECON101/builder/1/edit', DESK,
     "document.querySelector('#members-card .collapse-toggle').click();", ['#members-card'], 1.2),
    ('08_editor_question', 'sofia', '/c/ECON101/builder/1/edit', DESK, '', ['#questions-container .question-block:nth-child(1)'], 1.2),
    ('20_questions_collapsed', 'sofia', '/c/ECON101/builder/1/edit', DESK,
     "document.getElementById('collapse-all-questions').click();", ['#questions-card'], 1.2),
    ('21_advanced_options', 'sofia', '/c/ECON101/builder/1/edit', DESK,
     "document.querySelectorAll('.q-advanced-btn')[2].click();", ['.modal.show .modal-content'], 1.6),
    ('22_two_part', 'noah', '/c/ECON101/builder/2/edit', DESK,
     "document.getElementById('collapse-all-questions').click();", ['#questions-card', '#two-part-card'], 1.4),
    ('23_notifications', 'noah', '/c/ECON101/builder/2/edit', DESK,
     "var t=document.querySelectorAll('.reminder-arm')[1].querySelector('.rem-rule .rem-toggle'); t.click();"
     "document.querySelector('.reminder-arm .rem-toggle').click();", ['#reminders-card'], 1.6),
    ('24_preview_piping', 'sofia', '/c/ECON101/builder/1/preview?arm=1', PHONE,
     "var i=document.querySelector('.numeric-answer-input'); i.value='30'; i.dispatchEvent(new Event('input',{bubbles:true}));"
     "document.getElementById('next-question').click();", ['#state-answering .card'], 2.5),
    ('25_preview_break', 'noah', '/c/ECON101/builder/2/preview?arm=1', PHONE, PREVIEW_SUBMITTED, ['#state-submitted'], 2.5),
    ('26_notifications_phone', 'mateo', '/c/ECON101/reminders/2', PHONE, '', ['#reminders-box'], 1.8),
    ('27_lobby_followups', 'mateo', '/c/ECON101/lobby', DESK, '', ['#followups-card'], 1.2),
    ('28_flow_chart', 'sofia', '/c/ECON101/builder/1/flow', DESK, '', ['body > .container'], 3.5),
    ('12_preview_dashboard', 'sofia', '/c/ECON101/builder/1/preview-dashboard?n=40&seed=7', DESK, "Object.values(Chart.instances).forEach(function(c){c.options.animation=false;c.resize();c.update('none');});", ['body > .container'], 3.0),
    ('29_group_finder', 'henry', '/c/ECON101/lobby', DESK, '', ['#finder-card'], 1.2),
    # Instructor guide
    ('i01_home', 'host', '/c/ECON101/host/home', DESK, '', ['body > .container'], 1.2),
    ('i02_surveys', 'host', '/c/ECON101/builder/', DESK, '', ['body > .container'], 1.2),
    ('i03_roster_filter', 'host', '/c/ECON101/host/roster/', DESK,
     "var g=document.getElementById('f-group'); g.value='no'; g.dispatchEvent(new Event('change',{bubbles:true}));",
     ['#roster-filters', '#roster-table'], 1.2),
    ('i04_live_dashboard', 'host', '/c/ECON101/host/dashboard', DESK, '', ['body > .container'], 1.5),
    ('i05_demo_dashboard', 'host', '/c/ECON101/host/demo?survey=1&n=40&seed=3', DESK, "Object.values(Chart.instances).forEach(function(c){c.options.animation=false;c.resize();c.update('none');});", ['body > .container'], 3.0),
    ('hover_roster', 'host', '/c/ECON101/host/roster/', DESK,
     "var e=document.querySelectorAll('#roster-table [data-bs-toggle=tooltip]')[0]; e.scrollIntoView({block:'center'}); e.dispatchEvent(new MouseEvent('mouseover',{bubbles:true}));",
     ['#roster-table tbody tr:nth-child(1)', '.tooltip'], 1.2),
    ('i06_approve', 'host', '/c/ECON101/survey/2/view', DESK, '', ['#reminders'], 1.2),
]


async def main():
    profile = tempfile.mkdtemp()
    chrome = subprocess.Popen([CHROME, '--headless=new', '--remote-debugging-port=9333', f'--user-data-dir={profile}',
                               '--no-first-run', '--hide-scrollbars', 'about:blank'],
                              stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    try:
        for _ in range(50):
            try:
                tabs = requests.get('http://127.0.0.1:9333/json').json()
                page = next(t for t in tabs if t['type'] == 'page')
                break
            except Exception:
                time.sleep(0.2)
        async with aiohttp.ClientSession() as http:
            async with http.ws_connect(page['webSocketDebuggerUrl'], max_msg_size=0) as ws:
                counter = [0]

                async def send(method, **params):
                    counter[0] += 1
                    my = counter[0]
                    await ws.send_json({'id': my, 'method': method, 'params': params})
                    while True:
                        msg = await ws.receive_json()
                        if msg.get('id') == my:
                            if 'error' in msg:
                                raise RuntimeError(f'{method}: {msg["error"]}')
                            return msg.get('result', {})

                await send('Page.enable')
                await send('Network.enable')
                for name, who, path, (w, h, mobile), js, selectors, wait in SHOTS:
                    if ONLY and name not in ONLY:
                        continue
                    await send('Network.clearBrowserCookies')
                    await send('Network.setCookie', name='session', value=COOKIES[who], url=BASE)
                    await send('Emulation.setDeviceMetricsOverride', width=w, height=h, deviceScaleFactor=2, mobile=mobile)
                    await send('Emulation.setUserAgentOverride', userAgent=ANDROID_UA if mobile else
                               'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36')
                    await send('Emulation.setEmulatedMedia', features=[{'name': 'prefers-color-scheme', 'value': 'light'}])
                    await send('Page.navigate', url=BASE + path)
                    await asyncio.sleep(wait)
                    if js:
                        await send('Runtime.evaluate', expression=js)
                        await asyncio.sleep(0.9)
                    expr = ('(function(){var r=null;' + ''.join(
                        f"var e=document.querySelector({json.dumps(s)}); if(e){{var b=e.getBoundingClientRect();"
                        f"var x=b.left+scrollX,y=b.top+scrollY; r=r?{{x1:Math.min(r.x1,x),y1:Math.min(r.y1,y),x2:Math.max(r.x2,x+b.width),y2:Math.max(r.y2,y+b.height)}}"
                        f":{{x1:x,y1:y,x2:x+b.width,y2:y+b.height}};}}" for s in selectors) + 'return JSON.stringify(r);})()')
                    res = await send('Runtime.evaluate', expression=expr, returnByValue=True)
                    rect = json.loads(res['result']['value'] or 'null')
                    if not rect:
                        print('MISSING', name, selectors)
                        continue
                    pad = 8
                    clip = {'x': max(rect['x1'] - pad, 0), 'y': max(rect['y1'] - pad, 0),
                            'width': min(rect['x2'] - rect['x1'] + 2 * pad, w), 'height': rect['y2'] - rect['y1'] + 2 * pad, 'scale': 1}
                    shot = await send('Page.captureScreenshot', format='png', clip=clip, captureBeyondViewport=True)
                    with open(os.path.join(OUT, name + '.png'), 'wb') as f:
                        f.write(base64.b64decode(shot['data']))
                    print('ok', name, int(clip['width']), 'x', int(clip['height']))
    finally:
        chrome.terminate()


asyncio.run(main())
