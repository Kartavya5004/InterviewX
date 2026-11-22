"""Acceptance tests for Career OS v3: app isolation, drag status API, personalization, Gmail suggestion review."""
from tests.test_api import new_client,body
from backend.google_integration import identify_email, month_date


def test_pipeline_create_move_ownership_agenda_and_course_progress():
 a,ta,ua,_=new_client('Career A')
 b,tb,ub,_=new_client('Career B')
 payload={'company':'Example Labs','role':'Machine Learning Engineer','status':'applied','interview_at':'2026-12-01T09:30','notes':'First HR round'}
 assert a.post('/api/career/applications',json=payload).status_code==403
 res=a.post('/api/career/applications',headers={'X-CSRF-Token':ta},json=payload)
 assert res.status_code==201,res.text
 row=res.json();aid=row['id']
 assert row['interview_at']=='2026-12-01T09:30'
 assert len(a.get('/api/career/applications').json())==1
 assert not b.get('/api/career/applications').json()
 assert b.patch('/api/career/applications/'+aid,headers={'X-CSRF-Token':tb},json={'status':'offer'}).status_code==404
 assert b.delete('/api/career/applications/'+aid,headers={'X-CSRF-Token':tb}).status_code==404
 moved=a.patch('/api/career/applications/'+aid,headers={'X-CSRF-Token':ta},json={'status':'interview'})
 assert moved.status_code==200 and moved.json()['status']=='interview'
 agenda=a.get('/api/career/agenda').json()['interviews']
 assert len(agenda)==1 and len(agenda[0]['prep'])==3
 assert not b.get('/api/career/agenda').json()['interviews']
 c=a.get('/api/career/courses').json()
 assert c['focus']['evidence_count']==0 and c['courses'][0]['skill']=='DSA'
 cid=c['courses'][0]['id']
 p=a.put('/api/career/courses/'+cid+'/progress',headers={'X-CSRF-Token':ta},json={'status':'in_progress'})
 assert p.status_code==200
 assert a.get('/api/career/courses').json()['courses'][0]['progress']=='in_progress'
 assert b.get('/api/career/courses').json()['courses'][0]['progress']=='not_started'
 assert a.get('/career').status_code==200
 assert b.delete('/api/career/applications/'+aid,headers={'X-CSRF-Token':tb}).status_code==404
 assert a.delete('/api/career/applications/'+aid,headers={'X-CSRF-Token':ta}).status_code==200


def test_review_queue_manual_confirmation_no_silent_import():
 a,csrf,user,_=new_client('Gmail Review Candidate')
 demo=a.post('/api/google/demo-suggestions',headers={'X-CSRF-Token':csrf})
 assert demo.status_code==200 and demo.json()['new_suggestions']==3
 assert a.get('/api/career/applications').json()==[]  # no silent changes
 data=a.get('/api/google/suggestions').json();assert len(data)==3
 interview=next(x for x in data if x['status']=='interview')
 assert interview['interview_at']=='2026-11-28T10:30'
 result=a.post('/api/google/suggestions/'+interview['id']+'/accept',headers={'X-CSRF-Token':csrf},json={
     'company':'BrightLabs','role':'Software Engineer','status':'interview','interview_at':'2026-11-28T10:30'})
 assert result.status_code==200,result.text
 assert len(a.get('/api/career/agenda').json()['interviews'])==1
 assert len(a.get('/api/career/applications').json())==1
 assert a.post('/api/google/suggestions/'+interview['id']+'/accept',headers={'X-CSRF-Token':csrf},json={
     'company':'BrightLabs','role':'Software Engineer','status':'interview','interview_at':'2026-11-28T10:30'}).status_code==404
 b,csrf_b,user_b,_=new_client('Other candidate')
 assert b.get('/api/google/suggestions').json()==[]
 assert b.post('/api/google/suggestions/'+interview['id']+'/dismiss',headers={'X-CSRF-Token':csrf_b}).status_code==404


def test_mail_inference_conservative_and_datetime():
 assert identify_email('Webinar invitation','education@example.com','Unsubscribe at bottom') is None
 assert identify_email('Update on application','jobs@company.io','Unfortunately, we are not moving forward.')['status']=='rejected'
 assert month_date('Please join us 28 November 2026 at 10:30 AM')=='2026-11-28T10:30'
 assert month_date('We will interview you next Tuesday') is None
 assert month_date('2026-12-01 at 14:30')=='2026-12-01T14:30'


def test_google_oauth_unconfigured_and_calendar_guard():
 a,csrf,user,_=new_client('No OAuth')
 response=a.get('/api/google/status').json()
 assert 'configured' in response and isinstance(response['links'],list)
 # Connection cannot succeed until the developer provides Google credentials.
 assert a.get('/api/google/connect/gmail',follow_redirects=False).status_code==503
 assert a.post('/api/google/sync',headers={'X-CSRF-Token':csrf}).status_code==503
 assert a.post('/api/google/calendar/export/not-real',headers={'X-CSRF-Token':csrf}).status_code==503


def test_mocked_google_oauth_gmail_calendar_and_user_approval(monkeypatch):
 """Integration test covers Google's OAuth protocol using deterministic fake HTTP responses."""
 import httpx,os,base64
 from urllib.parse import urlsplit,parse_qs
 from cryptography.fernet import Fernet
 a,token,user,_=new_client('OAuth Test Candidate')
 monkeypatch.setenv('GOOGLE_CLIENT_ID','local-client-id')
 monkeypatch.setenv('GOOGLE_CLIENT_SECRET','local-secret')
 monkeypatch.setenv('GOOGLE_REDIRECT_URI','http://127.0.0.1:8001/api/google/callback')
 monkeypatch.setenv('INTERVIEWX_TOKEN_ENCRYPTION_KEY',Fernet.generate_key().decode())
 def fake_google(req):
  path=req.url.path
  if path=='/token':
   form=parse_qs(req.content.decode())
   if form.get('grant_type')==['authorization_code']:
    scope='https://www.googleapis.com/auth/gmail.readonly' if form.get('code')==['gmail-demo'] else 'https://www.googleapis.com/auth/calendar.events'
    return httpx.Response(200,json={'access_token':'fake-access','refresh_token':'fake-refresh','scope':scope})
   return httpx.Response(200,json={'access_token':'refreshed-access'})
  if path.endswith('/profile'):
   return httpx.Response(200,json={'emailAddress':'candidate@gmail.com'})
  if path.endswith('/messages'):
   return httpx.Response(200,json={'messages':[{'id':'unique-mail-42'}]})
  if path.endswith('/messages/unique-mail-42'):
   body='We are inviting you to interview on 12 December 2026 at 11:00 AM. We are looking forward to meeting you.'
   return httpx.Response(200,json={'payload':{'headers':[{'name':'Subject','value':'Interview at Orion Labs for AI Engineer'}, {'name':'From','value':'careers@orionlabs.io'}],
                'mimeType':'text/plain','body':{'data':base64.urlsafe_b64encode(body.encode()).decode()}},'snippet':'Interview scheduled.'})
  if path.endswith('/events'):
   return httpx.Response(200,json={'id':'calendar-123','htmlLink':'https://calendar.google.com/event?eid=test'})
  return httpx.Response(404,json={'error':'unexpected '+path})
 transport=httpx.MockTransport(fake_google)
 orig=httpx.AsyncClient
 monkeypatch.setattr(httpx,'AsyncClient',lambda **k:orig(transport=transport,timeout=k.get('timeout',20)))
 def oauth(target,code):
  start=a.get('/api/google/connect/'+target,follow_redirects=False)
  assert start.status_code in (302,303,307)
  state=parse_qs(urlsplit(start.headers['location']).query)['state'][0]
  callback=a.get('/api/google/callback',params={'code':code,'state':state},follow_redirects=False)
  assert callback.status_code==303,callback.text
 oauth('gmail','gmail-demo')
 assert a.get('/api/google/status').json()['links'][0]['email']=='candidate@gmail.com'
 sync=a.post('/api/google/sync',headers={'X-CSRF-Token':token})
 assert sync.status_code==200,sync.text
 assert sync.json()['scanned']==1 and sync.json()['new_suggestions']==1
 sug=a.get('/api/google/suggestions').json()[0]
 assert sug['status']=='interview' and sug['interview_at']=='2026-12-12T11:00'
 assert not a.get('/api/career/applications').json()
 import_res=a.post('/api/google/suggestions/'+sug['id']+'/accept',headers={'X-CSRF-Token':token},json={
  'company':'Orion Labs','role':'AI Engineer','status':'interview','interview_at':sug['interview_at']})
 assert import_res.status_code==200,import_res.text
 aid=import_res.json()['application_id']
 auto=a.put('/api/google/auto-sync',headers={'X-CSRF-Token':token},json={'enabled':True})
 assert auto.status_code==200 and a.get('/api/google/status').json()['auto_sync']
 oauth('calendar','calendar-demo')
 created=a.post('/api/google/calendar/export/'+aid,headers={'X-CSRF-Token':token})
 assert created.status_code==200,created.text
 assert created.json()['event_id']=='calendar-123'
 assert a.post('/api/google/calendar/export/'+aid,headers={'X-CSRF-Token':token}).json()['already_exported']
 assert a.post('/api/google/disconnect/gmail',headers={'X-CSRF-Token':token}).status_code==200
 assert a.get('/api/google/suggestions').json()==[]
 # User-approved application records remain even if Gmail is disconnected.
 assert a.get('/api/career/applications').json()[0]['id']==aid
