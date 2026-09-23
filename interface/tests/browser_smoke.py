"""Isolated Chromium tests against built assets; never attach to a user's browser."""
from pathlib import Path
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from functools import partial
import threading
import json
from playwright.sync_api import sync_playwright

ROOT=Path(__file__).resolve().parents[1]
ARTIFACTS=ROOT/'artifacts'
ARTIFACTS.mkdir(exist_ok=True)
class Quiet(SimpleHTTPRequestHandler):
    def log_message(self,*args):pass
server=ThreadingHTTPServer(('127.0.0.1',0),partial(Quiet,directory=str(ROOT/'dist')))
threading.Thread(target=server.serve_forever,daemon=True).start()
base=f'http://127.0.0.1:{server.server_port}'
with sync_playwright() as p:
    browser=p.chromium.launch(headless=True,executable_path='/usr/bin/google-chrome',args=['--no-sandbox'])
    page=browser.new_page(viewport={'width':1200,'height':900})
    errors=[]
    page.on('pageerror',lambda e:errors.append(str(e)))
    page.goto(base+'/manage.html');page.get_by_role('heading',name='Good answers deserve a second use.').wait_for()
    page.screenshot(path=str(ARTIFACTS/'management.png'),full_page=True)
    for name in ['Answers','Variables','Categories','Provider & budget','Diagnostics']:
        page.get_by_role('button',name=name,exact=True).click()
        page.get_by_role('heading',name=name,exact=True).wait_for()
    page.set_viewport_size({'width':360,'height':900})
    page.goto(base+'/panel.html');page.get_by_role('heading',name='A little less repetition.').wait_for()
    assert page.evaluate('document.documentElement.scrollWidth <= innerWidth')
    page.screenshot(path=str(ARTIFACTS/'panel.png'),full_page=True)
    page.goto(base+'/demo.html');page.get_by_role('heading',name='A safe place to try your answers.').wait_for()
    # A fake Chrome transport isolates the content adapter; no host or paid requests are possible.
    page.evaluate('''() => {window.reports=[];window.adapter=[];window.chrome={runtime:{id:'test',sendMessage:async(m)=>{window.reports.push(m);return {};},onMessage:{addListener:f=>window.adapter.push(f)}}};}''')
    page.add_script_tag(path=str(ROOT/'dist'/'content.js'))
    page.wait_for_function('window.reports.some(r=>r.type==="snapshot")')
    snapshot=page.evaluate('window.reports.filter(r=>r.type==="snapshot").at(-1).page')
    assert not any('password' in f['question'].lower() or 'authentication' in f['question'].lower() or 'read-only' in f['question'].lower() for f in snapshot['fields'])
    first=next(f for f in snapshot['fields'] if f['question']=='Why are you interested in this role?')
    target={**first,'documentToken':snapshot['documentToken']}
    def send(kind,target,**rest):
        return page.evaluate('''m=>new Promise(resolve=>{for(const f of window.adapter) f(m,{id:'test'},resolve);})''',{'type':kind,'target':target,**rest})
    assert send('insert',target,text='<b>Synthetic answer</b>',replace=False)['ok']
    assert page.locator('#practice-answer').input_value()=='<b>Synthetic answer</b>'
    page.locator('#practice-answer').fill('My later edit')
    assert not send('undo',target)['ok']
    assert page.locator('#practice-answer').input_value()=='My later edit'
    assert not send('insert',target,text='Late result',replace=True)['ok']
    skill=next(f for f in snapshot['fields'] if f['question']=='Describe your strongest technical skill.')
    page.get_by_role('button',name='Replace skill field').click()
    assert not send('insert',{**skill,'documentToken':snapshot['documentToken']},text='Late result',replace=True)['ok']
    assert not send('insert',{**target,'documentToken':'old-document'},text='Wrong document',replace=True)['ok']
    page.get_by_role('button',name='Toggle another question').click()
    page.wait_for_function('window.reports.filter(r=>r.type==="snapshot").at(-1).page.fields.some(f=>f.question==="Would you consider moving for this role?")')
    ui=browser.new_page(viewport={'width':380,'height':900})
    ui.add_init_script(r"""
    window.testState={events:[],insertions:[],forms:{},paid:0};
    const candidate=(variant)=>({id:variant,question_id:'q1',variant,body:'Synthetic '+variant+' answer.',variables:[],evidence_refs:[],template_refs:['T'],status:'valid',form_revision:'revision',validation:{}});
    window.chrome={runtime:{id:'test',sendMessage:async(m)=>{
      const s=window.testState;let data=null;
      if(m.type==='page')data={documentToken:'doc',documentId:'document',tabId:1,url:'https://synthetic.example/form',title:'Synthetic application',activeId:'q1',fields:[{id:'q1',formId:'form',question:'Why this role?',constraints:{max_length:600},prefilled:false,version:0,signature:'sig'}]};
      if(m.type==='pending')data=[];
      if(m.type==='state.get')data=s.forms[m.key]||null;
      if(m.type==='state.set')s.forms[m.key]=m.state;
      if(m.type==='host'){
        if(m.operation==='hello')data={version:'test',configured:true,generationReady:true,settings:{},budget:{max_session_cost_usd:.5},capabilities:{}};
        if(m.operation==='render')data={text:m.data.body,problems:[]};
        if(m.operation==='event'){
          const e=m.data.event;s.events.push(e);
          if(['generate_initial','regenerate_question'].includes(e.type)){if(!m.data.authorized)throw Error('Not authorized');s.paid++;}
          const cs=e.type==='generate_initial'?[candidate('standard'),candidate('concise')]:e.type==='get_candidate'&&s.paid?[candidate(e.payload.variant||'standard')]:[];
          data={event_id:e.event_id,status:e.type==='get_candidate'&&!s.paid?'partial':'ready',revision:'revision',candidates:cs,cached:{},unresolved:[],usage:{calls:s.paid,tokens:100,cost_usd:.001,uncertain:0},diagnostics:[]};
        }
      }
      if(m.type==='insert'){s.insertions.push(m);data={inserted:true};}
      return {ok:true,data};
    }},storage:{onChanged:{addListener(){},removeListener(){}}},tabs:{onActivated:{addListener(){},removeListener(){}}}};
    """)
    ui.goto(base+'/panel.html')
    ui.get_by_role('button',name='AI help',exact=True).click()
    ui.get_by_text('No cached answer is available. Generation requires your approval.').wait_for()
    assert ui.evaluate('window.testState.paid')==0
    ui.get_by_role('button',name='Generate answers…',exact=True).click()
    assert ui.evaluate('window.testState.paid')==0
    ui.get_by_role('button',name='Authorize generation',exact=True).click()
    ui.get_by_text('Synthetic standard answer.',exact=True).wait_for()
    ui.wait_for_function("window.testState.events.some(e=>e.type==='record_feedback'&&e.payload.outcome==='shown')")
    assert ui.evaluate('window.testState.paid')==1
    assert ui.evaluate('window.testState.insertions.length')==0
    assert ui.evaluate("window.testState.events.filter(e=>e.type==='record_feedback'&&e.payload.outcome==='shown').every(e=>e.payload.shown.length===1&&e.payload.shown[0]==='standard')")
    ui.get_by_role('button',name='Use concise version',exact=True).click()
    ui.get_by_text('Synthetic concise answer.',exact=True).wait_for()
    assert ui.evaluate('window.testState.paid')==1
    ui.get_by_role('button',name='Use answer',exact=True).click()
    ui.wait_for_function('window.testState.insertions.length===1')
    assert ui.evaluate("window.testState.insertions[0].text")=='Synthetic concise answer.'
    ui.wait_for_function("window.testState.events.some(e=>e.type==='record_feedback'&&e.payload.outcome==='selected')")
    assert ui.evaluate('document.documentElement.scrollWidth <= innerWidth')
    ui.screenshot(path=str(ARTIFACTS/'panel-synthetic-connected.png'),full_page=True)
    ui.keyboard.press('Tab')
    assert ui.evaluate('document.activeElement !== document.body')
    assert not errors, errors
    (ARTIFACTS/'browser-report.json').write_text(json.dumps({'passed':True,'checks':['management navigation','360px panel overflow','inert insertion','concurrent edit guard','guarded undo','dynamic replacement','document identity','dynamic discovery','excluded controls','explicit paid authorization','cached concise without generation','only displayed candidates exposed','selected only after insertion','keyboard focus'],'console_errors':errors},indent=2))
    browser.close()
server.shutdown()
print('Browser smoke checks passed')
