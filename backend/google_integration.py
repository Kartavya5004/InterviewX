"""Optional, consent-based Google OAuth: Gmail review queue + Calendar event creation.

Gmail email body/snippet stays on the local app until deletion; nothing is sent to
third-party AI. Google account access is separate from InterviewX login.
"""
from __future__ import annotations
import asyncio, base64, hashlib, json, os, re, secrets, uuid
from datetime import datetime, timedelta, timezone
from email.utils import parseaddr
from urllib.parse import urlencode
from zoneinfo import ZoneInfo
import httpx
from cryptography.fernet import Fernet, InvalidToken
from dotenv import load_dotenv
from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import RedirectResponse
from pydantic import BaseModel, Field
from .auth import current_user, mutation_user
from .main import connection, stamp
from .career import own_application, safe_schedule

load_dotenv()
router=APIRouter(prefix='/api/google',tags=['google'])
GOOGLE_AUTH='https://accounts.google.com/o/oauth2/v2/auth'
GOOGLE_TOKEN='https://oauth2.googleapis.com/token'
GMAIL='https://www.googleapis.com/auth/gmail.readonly'
CALENDAR='https://www.googleapis.com/auth/calendar.events'
TARGET_SCOPES={'gmail':GMAIL,'calendar':CALENDAR}


def config():
 client=os.getenv('GOOGLE_CLIENT_ID','').strip()
 secret=os.getenv('GOOGLE_CLIENT_SECRET','').strip()
 redirect=os.getenv('GOOGLE_REDIRECT_URI','http://127.0.0.1:8001/api/google/callback').strip()
 key=os.getenv('INTERVIEWX_TOKEN_ENCRYPTION_KEY','').strip()
 if not all((client,secret,key)):
  raise HTTPException(503,'Configure GOOGLE_CLIENT_ID, GOOGLE_CLIENT_SECRET, and INTERVIEWX_TOKEN_ENCRYPTION_KEY in .env.')
 try:crypto=Fernet(key.encode())
 except (ValueError,TypeError):raise HTTPException(503,'INTERVIEWX_TOKEN_ENCRYPTION_KEY is invalid; generate a new Fernet key.')
 return client,secret,redirect,crypto


def initialize_google():
 with connection() as db:
  db.execute('''CREATE TABLE IF NOT EXISTS google_links(
   user_id TEXT NOT NULL,target TEXT NOT NULL,email TEXT NOT NULL,
   encrypted_refresh_token TEXT NOT NULL,connected_at TEXT NOT NULL,
   PRIMARY KEY(user_id,target))''')
  db.execute('''CREATE TABLE IF NOT EXISTS oauth_pending(
   state_hash TEXT PRIMARY KEY,user_id TEXT NOT NULL,target TEXT NOT NULL,expires_at TEXT NOT NULL)''')
  db.execute('''CREATE TABLE IF NOT EXISTS mail_suggestions(
    id TEXT PRIMARY KEY,user_id TEXT NOT NULL,message_id TEXT NOT NULL,
    subject TEXT NOT NULL,sender TEXT NOT NULL,excerpt TEXT NOT NULL,
    company TEXT NOT NULL,role TEXT NOT NULL,status TEXT NOT NULL,
    interview_at TEXT,confidence TEXT NOT NULL,review_status TEXT NOT NULL DEFAULT 'pending',
    created_at TEXT NOT NULL, UNIQUE(user_id,message_id))''')
  db.execute('''CREATE TABLE IF NOT EXISTS gmail_preferences(
    user_id TEXT PRIMARY KEY, auto_sync INTEGER NOT NULL DEFAULT 0,
    last_sync TEXT, last_error TEXT)''')
  db.execute('''CREATE TABLE IF NOT EXISTS calendar_exports(
    user_id TEXT NOT NULL,application_id TEXT NOT NULL,event_id TEXT NOT NULL,
    created_at TEXT NOT NULL,PRIMARY KEY(user_id,application_id))''')


def utc():return datetime.now(timezone.utc)


def month_date(text):
 """Only exact, explicit date/time expressions; never infer dates from email delivery time."""
 date=None
 m=re.search(r'\b(20\d\d)[-/.](0?[1-9]|1[012])[-/.]([0-2]?\d|3[01])\b',text)
 if m:
  try:date=datetime(int(m[1]),int(m[2]),int(m[3]))
  except ValueError:pass
 if not date:
  m=re.search(r'\b([0-2]?\d|3[01])[/.-](0?[1-9]|1[012])[/.-](20\d\d)\b',text)
  if m:
   try:date=datetime(int(m[3]),int(m[2]),int(m[1]))
   except ValueError:pass
 if not date:
  month=r'(January|February|March|April|May|June|July|August|September|October|November|December)'
  m=re.search(r'\b'+month+r'\s+([0-3]?\d)(?:st|nd|rd|th)?[,]?\s+(20\d\d)\b',text,re.I)
  if m:
   try:date=datetime.strptime(f'{m[1]} {m[2]} {m[3]}','%B %d %Y')
   except ValueError:pass
  if not date:
   m=re.search(r'\b([0-3]?\d)(?:st|nd|rd|th)?\s+'+month+r'[,]?\s+(20\d\d)\b',text,re.I)
   if m:
    try:date=datetime.strptime(f'{m[2]} {m[1]} {m[3]}','%B %d %Y')
    except ValueError:pass
 if not date:return None
 t=re.search(r'\b(?:at\s+)?(0?[1-9]|1[0-2]):([0-5]\d)\s*(AM|PM)\b',text,re.I)
 if t:
  h=int(t[1])%12+(12 if t[3].lower()=='pm' else 0);return date.replace(hour=h,minute=int(t[2])).isoformat(timespec='minutes')
 t=re.search(r'\b(?:at\s+)?([01]?\d|2[0-3]):([0-5]\d)\b',text)
 if t:return date.replace(hour=int(t[1]),minute=int(t[2])).isoformat(timespec='minutes')
 return None


def identify_email(subject,sender,snippet):
 txt=f'{subject}\n{snippet}'[:4500]
 low=txt.lower()
 # Reject newsletters and opportunistic marketing (non-exhaustive).
 if any(w in low for w in ('unsubscribe','weekly newsletter','webinar invitation','buy now','new courses for you')):
  return None
 status=None
 if re.search(r'\b(unfortunately|not selected|not moving forward|rejected|unsuccessful|cannot proceed)\b',low):status='rejected'
 elif re.search(r'\b(offer of employment|pleased to offer|job offer)\b',low):status='offer'
 elif re.search(r'\b(interview|meet the hiring team|schedule a call|interview invitation)\b',low):status='interview'
 elif re.search(r'\b(assessment|screening|shortlisted|next step)\b',low):status='screening'
 elif re.search(r'\b(thank you for applying|application received|submitted your application|application confirmation)\b',low):status='applied'
 if not status:return None
 address=parseaddr(sender)[1]
 domain=address.split('@')[-1].lower().split('.')[0] if '@' in address else ''
 generic={'gmail','outlook','yahoo','noreply','mail','email','notifications','greenhouse','lever','workday','smartrecruiters','ashbyhq','linkedin'}
 company=domain.title() if domain and domain not in generic else ''
 # Prefer company explicit in certain subject formats; avoids sender provider names.
 match=re.search(r'(?:interview (?:at|with)|application (?:to|at|for)|position at|offer (?:from|at))\s+([\w&. -]{2,55})',subject,re.I)
 if match:company=match[1].strip(' .,:—-')
 company=company[:80] or 'Company (review needed)'
 match=re.search(r'(?:for (?:the )?|position[:\s]+|role[:\s]+)([A-Za-z0-9 +/#.-]{3,65})(?:\s+(?:role|position)|[,.]|$)',subject,re.I)
 role=(match[1].strip() if match else 'Role (review needed)')[:95]
 explicit=month_date(txt) if status=='interview' else None
 return {'company':company,'role':role,'status':status,'interview_at':explicit,
         'confidence':'medium' if company!='Company (review needed)' else 'low'}

@router.get('/status')
def status(user=Depends(current_user)):
 with connection() as db:
  links=[{'target':r['target'],'email':r['email'],'connected_at':r['connected_at']} for r in db.execute('SELECT target,email,connected_at FROM google_links WHERE user_id=?',(user['id'],))]
  pending=db.execute("SELECT count(*) FROM mail_suggestions WHERE user_id=? AND review_status='pending'",(user['id'],)).fetchone()[0]
  pref=db.execute('SELECT * FROM gmail_preferences WHERE user_id=?',(user['id'],)).fetchone()
 return {'configured':all(os.getenv(x) for x in ('GOOGLE_CLIENT_ID','GOOGLE_CLIENT_SECRET','INTERVIEWX_TOKEN_ENCRYPTION_KEY')),
         'links':links,'pending':pending,
         'auto_sync':bool(pref['auto_sync']) if pref else False,
         'last_sync':pref['last_sync'] if pref else None,
         'last_error':pref['last_error'] if pref else None,
         'note':'Auto sync is optional. When enabled, the running local server checks for updates approximately every 15 minutes. It stops when the app server stops.'}

@router.get('/connect/{target}')
def connect(target:str,user=Depends(current_user)):
 if target not in TARGET_SCOPES:raise HTTPException(404,'Unknown integration')
 client,secret,redirect,_=config()
 raw=secrets.token_urlsafe(32)
 with connection() as db:
  db.execute('INSERT INTO oauth_pending VALUES(?,?,?,?)',
    (hashlib.sha256(raw.encode()).hexdigest(),user['id'],target,(utc()+timedelta(minutes=10)).isoformat()))
 params={'client_id':client,'redirect_uri':redirect,'response_type':'code','scope':TARGET_SCOPES[target],
         'state':raw,'access_type':'offline','prompt':'consent','include_granted_scopes':'false'}
 return RedirectResponse(GOOGLE_AUTH+'?'+urlencode(params))

@router.get('/callback')
async def callback(state:str|None=None,code:str|None=None,error:str|None=None,user=Depends(current_user)):
 if error:return RedirectResponse('/career?integration=cancelled')
 if not state or not code:raise HTTPException(400,'Incomplete Google authorization response')
 statehash=hashlib.sha256(state.encode()).hexdigest()
 with connection() as db:
  row=db.execute('SELECT * FROM oauth_pending WHERE state_hash=?',(statehash,)).fetchone()
  db.execute('DELETE FROM oauth_pending WHERE state_hash=?',(statehash,))
  if not row or row['user_id']!=user['id'] or row['expires_at']<utc().isoformat():
   raise HTTPException(403,'OAuth state expired or account mismatch')
  target=row['target']
 client,secret,redirect,crypto=config()
 try:
  async with httpx.AsyncClient(timeout=20) as transport:
   resp=await transport.post(GOOGLE_TOKEN,data={'code':code,'client_id':client,'client_secret':secret,'redirect_uri':redirect,'grant_type':'authorization_code'})
   resp.raise_for_status(); tokens=resp.json()
   refresh=tokens.get('refresh_token')
   if not refresh:raise HTTPException(400,'Google did not provide a refresh token. Reconnect and grant offline access.')
   granted=tokens.get('scope','').split()
   if TARGET_SCOPES[target] not in granted:raise HTTPException(403,'Required Google permission not granted')
   label='Google Calendar'
   if target=='gmail':
    p=await transport.get('https://gmail.googleapis.com/gmail/v1/users/me/profile',headers={'Authorization':'Bearer '+tokens['access_token']})
    p.raise_for_status();label=p.json().get('emailAddress','Gmail account')
 except httpx.HTTPError:raise HTTPException(502,'Could not complete Google authorization')
 with connection() as db:
  db.execute('''INSERT INTO google_links VALUES(?,?,?,?,?) ON CONFLICT(user_id,target) DO UPDATE SET email=excluded.email,encrypted_refresh_token=excluded.encrypted_refresh_token,connected_at=excluded.connected_at''',
   (user['id'],target,label,crypto.encrypt(refresh.encode()).decode(),stamp()))
 return RedirectResponse('/career?integration=connected',status_code=303)

async def authorized_token(user_id,target):
 client,secret,_,crypto=config()
 with connection() as db:
  row=db.execute('SELECT encrypted_refresh_token FROM google_links WHERE user_id=? AND target=?',(user_id,target)).fetchone()
 if not row:raise HTTPException(409,f'Connect {target} before syncing.')
 try:refresh=crypto.decrypt(row['encrypted_refresh_token'].encode()).decode()
 except InvalidToken:raise HTTPException(503,'Encryption key changed; reconnect Google.')
 try:
  async with httpx.AsyncClient(timeout=20) as transport:
   resp=await transport.post(GOOGLE_TOKEN,data={'refresh_token':refresh,'client_id':client,'client_secret':secret,'grant_type':'refresh_token'})
   resp.raise_for_status();return resp.json()['access_token']
 except (httpx.HTTPError,KeyError):raise HTTPException(502,'Could not refresh Google authorization. Reconnect the account.')

@router.post('/disconnect/{target}')
def disconnect(target:str,user=Depends(mutation_user)):
 if target not in TARGET_SCOPES:raise HTTPException(404,'Unknown integration')
 with connection() as db:
  db.execute('DELETE FROM google_links WHERE user_id=? AND target=?',(user['id'],target))
  if target=='gmail':
   db.execute('DELETE FROM mail_suggestions WHERE user_id=?',(user['id'],))
   db.execute('DELETE FROM gmail_preferences WHERE user_id=?',(user['id'],))
 return {'disconnected':True,'note':'Local tokens and imported suggestion excerpts deleted. You may also revoke access in your Google Account permissions.'}

@router.get('/suggestions')
def suggestions(user=Depends(current_user)):
 with connection() as db:
  return [dict(r) for r in db.execute("SELECT * FROM mail_suggestions WHERE user_id=? ORDER BY created_at DESC LIMIT 80",(user['id'],))]

def save_suggestion(owner,message_id,subject,sender,snippet,parsed):
 with connection() as db:
  existing=db.execute('SELECT id FROM mail_suggestions WHERE user_id=? AND message_id=?',(owner,message_id)).fetchone()
  if existing:return False
  db.execute('''INSERT INTO mail_suggestions(id,user_id,message_id,subject,sender,excerpt,company,role,status,interview_at,confidence,review_status,created_at)
     VALUES(?,?,?,?,?,?,?,?,?,?,?,'pending',?)''',
     (uuid.uuid4().hex,owner,message_id,subject[:220],sender[:180],snippet[:450],parsed['company'],parsed['role'],parsed['status'],parsed['interview_at'],parsed['confidence'],stamp()))
 return True

class AutoSyncRequest(BaseModel):
 enabled:bool

@router.put('/auto-sync')
def configure_auto_sync(req:AutoSyncRequest,user=Depends(mutation_user)):
 with connection() as db:
  if req.enabled and not db.execute("SELECT 1 FROM google_links WHERE user_id=? AND target='gmail'",(user['id'],)).fetchone():
   raise HTTPException(409,'Connect Gmail before enabling automatic sync.')
  db.execute('INSERT INTO gmail_preferences(user_id,auto_sync,last_sync,last_error) VALUES(?,?,NULL,NULL) '
             'ON CONFLICT(user_id) DO UPDATE SET auto_sync=excluded.auto_sync', (user['id'],int(req.enabled)))
 return {'auto_sync':req.enabled,'message':'Automatic inbox checking is active only while the local server runs.' if req.enabled else 'Automatic inbox checking stopped.'}

async def sync_for_owner(owner_id):
 token=await authorized_token(owner_id,'gmail')
 params={'q':'newer_than:120d {interview application applied rejection assessment offer shortlisted}', 'maxResults':30}
 added=0;scanned=0
 try:
  async with httpx.AsyncClient(timeout=25) as transport:
   r=await transport.get('https://gmail.googleapis.com/gmail/v1/users/me/messages',params=params,headers={'Authorization':f'Bearer {token}'})
   r.raise_for_status()
   ids=r.json().get('messages',[])[:30]
   for entry in ids:
    msg=await transport.get('https://gmail.googleapis.com/gmail/v1/users/me/messages/'+entry['id'],params={'format':'full'},headers={'Authorization':f'Bearer {token}'})
    msg.raise_for_status();data=msg.json();scanned+=1
    headers={p['name'].lower():p.get('value','') for p in data.get('payload',{}).get('headers',[])}
    subject=headers.get('subject','');sender=headers.get('from','')
    snippet=data.get('snippet','')
    # Extract plain-text parts for scheduling details; never retrieve attachments.
    # Only a short preview is saved in SQLite. The full body is not persisted.
    def plain_text(part,depth=0):
     if depth>5:return ''
     mime=part.get('mimeType','')
     if mime=='text/plain':
      raw=part.get('body',{}).get('data','')
      if raw:
       try:return base64.urlsafe_b64decode(raw+'='*(-len(raw)%4)).decode('utf-8','replace')[:5000]
       except (ValueError,UnicodeDecodeError):return ''
     return '\n'.join(plain_text(p,depth+1) for p in part.get('parts',[])[:12])[:5000]
    body_text=plain_text(data.get('payload',{}))
    parsed=identify_email(subject,sender,body_text or snippet)
    if parsed and save_suggestion(owner_id,entry['id'],subject,sender,snippet or body_text,parsed):added+=1
 except httpx.HTTPError:raise HTTPException(502,'Gmail sync failed. Check Google permissions and network.')
 result={'scanned':scanned,'new_suggestions':added,'message':'Suggestions are pending review. Nothing changed in your application tracker.'}
 with connection() as db:
  db.execute('INSERT INTO gmail_preferences(user_id,auto_sync,last_sync,last_error) VALUES(?,0,?,NULL) '
             'ON CONFLICT(user_id) DO UPDATE SET last_sync=excluded.last_sync,last_error=NULL', (owner_id,stamp()))
 return result

@router.post('/sync')
async def sync_gmail(user=Depends(mutation_user)):
 return await sync_for_owner(user['id'])

async def autosync_loop():
 # Single-process local development helper. Does not run when the server is stopped.
 # Multi-worker production deployments should use a dedicated job queue instead.
 while True:
  await asyncio.sleep(60)
  with connection() as db:
   rows=db.execute('''SELECT p.user_id,p.last_sync FROM gmail_preferences p
      JOIN google_links l ON l.user_id=p.user_id AND l.target='gmail'
      WHERE p.auto_sync=1''').fetchall()
  now=utc()
  for row in rows:
   last=row['last_sync']
   if last:
    try:
     if now-datetime.fromisoformat(last)<timedelta(minutes=15):continue
    except ValueError:pass
   try:await sync_for_owner(row['user_id'])
   except Exception as exc:
    with connection() as db:
     db.execute('UPDATE gmail_preferences SET last_sync=?,last_error=? WHERE user_id=?',
                (stamp(),type(exc).__name__,row['user_id']))

@router.post('/demo-suggestions')
def demo_suggestions(user=Depends(mutation_user)):
 demo=[
 ('Interview invitation — Software Engineer','Hiring Team <recruiting@brightlabs.example>','We are pleased to invite you to an interview on 28 November 2026 at 10:30 AM. Please confirm.'),
 ('Thank you for applying — Data Analyst','Recruitment <careers@solstice.example>','We received your application for the Data Analyst role and will be in touch.'),
 ('Update on your application','Talent <jobs@northstar.example>','Unfortunately, we are not moving forward with your application at this time.')]
 added=0
 for i,(subject,sender,snippet) in enumerate(demo):
  parsed=identify_email(subject,sender,snippet)
  if parsed and save_suggestion(user['id'],'demo-message-'+str(i),subject,sender,snippet,parsed):added+=1
 return {'new_suggestions':added,'demo':True,'message':'Fictional examples only — not imported from your Gmail.'}

class Decision(BaseModel):
 company:str=Field(min_length=2,max_length=120)
 role:str=Field(min_length=2,max_length=160)
 status:str
 interview_at:str|None=None
 application_id:str|None=None

@router.post('/suggestions/{suggestion_id}/accept')
def accept(suggestion_id:str,item:Decision,user=Depends(mutation_user)):
 if item.status not in ('applied','screening','interview','rejected','offer','completed'):raise HTTPException(422,'Invalid application stage')
 scheduled=safe_schedule(item.interview_at)
 with connection() as db:
  row=db.execute("SELECT * FROM mail_suggestions WHERE id=? AND user_id=? AND review_status='pending'",(suggestion_id,user['id'])).fetchone()
  if not row:raise HTTPException(404,'Suggestion not found or already reviewed')
  if item.application_id:
   own_application(db,item.application_id,user['id'])
   db.execute('UPDATE applications SET company=?,role=?,status=?,interview_at=COALESCE(?,interview_at),updated_at=? WHERE id=? AND user_id=?',
     (item.company.strip(),item.role.strip(),item.status,scheduled,stamp(),item.application_id,user['id']))
   aid=item.application_id
  else:
   aid=uuid.uuid4().hex
   db.execute('''INSERT INTO applications(id,user_id,company,role,status,source,source_message_id,interview_at,created_at,updated_at)
                 VALUES(?,?,?,?,?,'gmail',?,?,?,?)''',
     (aid,user['id'],item.company.strip(),item.role.strip(),item.status,row['message_id'],scheduled,stamp(),stamp()))
  db.execute("UPDATE mail_suggestions SET review_status='accepted' WHERE id=?",(suggestion_id,))
 return {'accepted':True,'application_id':aid,'note':'Application updated with your confirmation. In-app preparation agenda is generated automatically from the saved interview time.'}

@router.post('/suggestions/{suggestion_id}/dismiss')
def dismiss(suggestion_id:str,user=Depends(mutation_user)):
 with connection() as db:
  cursor=db.execute("UPDATE mail_suggestions SET review_status='dismissed' WHERE id=? AND user_id=? AND review_status='pending'",(suggestion_id,user['id']))
  if not cursor.rowcount:raise HTTPException(404,'Suggestion not found')
 return {'dismissed':True}

@router.post('/calendar/export/{application_id}')
async def export_calendar(application_id:str,user=Depends(mutation_user)):
 token=await authorized_token(user['id'],'calendar')
 with connection() as db:
  app=own_application(db,application_id,user['id'])
  prior=db.execute('SELECT event_id FROM calendar_exports WHERE user_id=? AND application_id=?',(user['id'],application_id)).fetchone()
 if prior:return {'event_id':prior['event_id'],'already_exported':True,'message':'Already added to Google Calendar. Updates are not automatically propagated.'}
 if not app['interview_at']:raise HTTPException(422,'Add a confirmed interview date before exporting.')
 try:
  dt=datetime.fromisoformat(app['interview_at'])
  if dt.tzinfo is None:
   dt=dt.replace(tzinfo=ZoneInfo(os.getenv('INTERVIEWX_TIMEZONE','Asia/Kolkata')))
 except (ValueError,KeyError):raise HTTPException(422,'Invalid interview date or time zone')
 end=dt+timedelta(minutes=60)
 data={'summary':f'Interview · {app["company"]} · {app["role"]}',
       'description':'Created on your request by InterviewX. Verify the date, location and company details.',
       'start':{'dateTime':dt.isoformat()},'end':{'dateTime':end.isoformat()},
       'reminders':{'useDefault':False,'overrides':[{'method':'popup','minutes':60},{'method':'popup','minutes':1440}]}}
 try:
  async with httpx.AsyncClient(timeout=20) as transport:
   resp=await transport.post('https://www.googleapis.com/calendar/v3/calendars/primary/events',json=data,headers={'Authorization':f'Bearer {token}'})
   resp.raise_for_status();result=resp.json()
 except httpx.HTTPError:raise HTTPException(502,'Could not add the interview to Google Calendar.')
 with connection() as db:
  db.execute('INSERT OR REPLACE INTO calendar_exports VALUES(?,?,?,?)',(user['id'],application_id,result.get('id',''),stamp()))
 return {'event_id':result.get('id'),'url':result.get('htmlLink'),'already_exported':False}
