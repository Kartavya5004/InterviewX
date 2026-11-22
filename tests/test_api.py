"""InterviewX 2.1 account security and interview engine regression tests."""
import os
import tempfile
import uuid
from pathlib import Path

os.environ['INTERVIEWX_DB'] = str(Path(tempfile.gettempdir()) / f'interviewx_auth_suite_{uuid.uuid4().hex}.sqlite3')
os.environ.pop('GEMINI_API_KEY',None)
from fastapi.testclient import TestClient
from backend.main import app


def new_client(name, email=None):
    client=TestClient(app)
    email=email or f'{uuid.uuid4().hex[:12]}@example.com'
    register=client.post('/api/auth/register',json={'name':name,'email':email,'password':'valid-long-passphrase-123'})
    assert register.status_code==201,register.text
    me=client.get('/api/auth/me')
    assert me.status_code==200
    return client,me.json()['csrf_token'],register.json()['user'],email


def body():
    return {
        'role':'AI Engineer Intern','company':'Northstar',
        'resume':'Built a Python vector search assistant with REST APIs. Tested retrieval quality using sample questions and deployed the application.',
        'job_description':'Python, REST API, machine learning, testing and cloud development skills.',
        'mode':'project',
    }


def test_guest_login_page_and_protected_data():
    c=TestClient(app)
    assert c.get('/api/health').status_code==200
    assert c.get('/login').status_code==200
    assert 'CREATE ACCOUNT' in c.get('/login').text
    assert c.get('/',follow_redirects=False).status_code==303
    assert c.get('/api/auth/me').status_code==401
    assert c.get('/api/sessions/unknown').status_code==401
    assert c.post('/api/start',json=body()).status_code==401
    assert c.get('/static/auth.css').status_code==200
    assert c.get('/static/login.js').status_code==200


def test_register_login_logout_and_hashing():
    client,csrf,user,email=new_client('Test Candidate')
    assert client.get('/',follow_redirects=False).status_code==200
    assert client.get('/login',follow_redirects=False).status_code==303
    from backend.auth import conn
    with conn() as db:
        stored=db.execute('SELECT password_hash FROM users WHERE id=?',(user['id'],)).fetchone()['password_hash']
    assert 'valid-long-passphrase-123' not in stored
    assert stored.startswith('$argon2id$')
    bad=client.post('/api/auth/login',json={'email':email,'password':'wrong'})
    assert bad.status_code==401
    assert client.post('/api/auth/logout').status_code==403  # CSRF protection
    assert client.post('/api/auth/logout',headers={'X-CSRF-Token':'invalid'}).status_code==403
    assert client.post('/api/auth/logout',headers={'X-CSRF-Token':csrf}).status_code==200
    assert client.get('/api/auth/me').status_code==401
    assert client.post('/api/auth/login',json={'email':email,'password':'valid-long-passphrase-123'}).status_code==200
    assert client.get('/api/auth/me').status_code==200


def test_voice_interview_and_cross_account_access():
    a,csrf_a,user_a,_=new_client('Candidate A')
    b,csrf_b,user_b,_=new_client('Candidate B')
    no_csrf=a.post('/api/start',json=body());assert no_csrf.status_code==403
    started=a.post('/api/start',json=body(),headers={'X-CSRF-Token':csrf_a})
    assert started.status_code==200,started.text
    session=started.json();sid=session['id']
    assert b.get(f'/api/sessions/{sid}').status_code==404
    assert b.get(f'/api/sessions/{sid}/report').status_code==404
    assert b.post(f'/api/sessions/{sid}/answer',headers={'X-CSRF-Token':csrf_b},json={'answer':'Some answer'}).status_code==404
    assert b.delete(f'/api/sessions/{sid}',headers={'X-CSRF-Token':csrf_b}).status_code==404
    for i in range(4):
        response=a.post(f'/api/sessions/{sid}/answer',headers={'X-CSRF-Token':csrf_a},json={
           'answer':'I built a Python endpoint using FastAPI because it is simple to test. First I implemented validation and then verified the result with a test set.',
           'confidence':80,
           'speech_metrics':{'input_mode':'voice','duration_seconds':33,'pause_count':2}
        })
        assert response.status_code==200,response.text
        session=response.json()
    assert session['status']=='complete' and len(session['turns'])==4
    report=a.get(f'/api/sessions/{sid}/report').json()
    assert report['questions_answered']==4 and report['spoken_answers']==4
    retry=a.post(f'/api/sessions/{sid}/retry',headers={'X-CSRF-Token':csrf_a},json={
        'turn_index':0,'answer':'I tested a Python retrieval service with a sample dataset and monitored failure cases and data leakage.',
        'confidence':75
    })
    assert retry.status_code==200 and retry.json()['turns'][0]['retry']
    assert a.delete(f'/api/sessions/{sid}',headers={'X-CSRF-Token':csrf_a}).json()=={'deleted':True}
    assert a.get(f'/api/sessions/{sid}').status_code==404


def test_registration_validation_and_origin_policy():
    c=TestClient(app)
    assert c.post('/api/auth/register',json={'name':'Tester','email':'tester@test.org','password':'short'}).status_code==422
    assert c.post('/api/auth/register',json={'name':'Tester','email':'invalid-email','password':'valid-long-passphrase-123'}).status_code==422
    r=c.post('/api/auth/register',headers={'Origin':'https://attacker.example'},json={'name':'Tester','email':'x@example.com','password':'valid-long-passphrase-123'})
    assert r.status_code==403


def test_login_throttling():
    c,csrf,user,email=new_client('Brute Test')
    for _ in range(8):
        response=c.post('/api/auth/login',json={'email':email,'password':'incorrect-pass'})
        assert response.status_code==401
    assert c.post('/api/auth/login',json={'email':email,'password':'incorrect-pass'}).status_code==429
