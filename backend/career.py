"""Account-scoped job pipeline, interview scheduling, and evidence-based learning suggestions.

All application writes require the session's X-CSRF-Token. Training content uses a small
curated catalogue; there are no undisclosed affiliate links or fictitious sponsorships.
"""
from __future__ import annotations
import json, re, sqlite3, uuid
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Literal
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from .auth import current_user, mutation_user
from .main import connection, stamp

router=APIRouter(prefix='/api/career',tags=['career'])
STATUS=('saved','applied','screening','interview','completed','offer','rejected')

COURSES=[
 {'id':'cs50','title':'CS50x — Introduction to Computer Science','provider':'Harvard CS50','skill':'DSA','level':'Foundation','price':'Free to learn','url':'https://cs50.harvard.edu/x/','summary':'Build programming and computational-thinking fundamentals.'},
 {'id':'pw-cpp','title':'DSA with C++','provider':'PW Skills','skill':'DSA','level':'Structured','price':'Check provider pricing','url':'https://pwskills.com/dsa-courses/matering-c-with-dsa-ipp/','summary':'Structured C++ data structures and algorithm practice.'},
 {'id':'pw-java','title':'DSA with Java','provider':'PW Skills','skill':'DSA','level':'Structured','price':'Check provider pricing','url':'https://pwskills.com/dsa-courses/java-dsa-interview-preparation/','summary':'Algorithm preparation using Java.'},
 {'id':'fcc-js','title':'JavaScript Algorithms and Data Structures','provider':'freeCodeCamp','skill':'DSA','level':'Practice','price':'Free','url':'https://www.freecodecamp.org/learn/javascript-algorithms-and-data-structures-v8/','summary':'Hands-on algorithms, arrays, loops and objects.'},
 {'id':'kaggle-intro','title':'Intro to Machine Learning','provider':'Kaggle Learn','skill':'AI & ML','level':'Foundation','price':'Free','url':'https://www.kaggle.com/learn/intro-to-machine-learning','summary':'Practical modeling and validation exercises.'},
 {'id':'kaggle-inter','title':'Intermediate Machine Learning','provider':'Kaggle Learn','skill':'AI & ML','level':'Intermediate','price':'Free','url':'https://www.kaggle.com/learn/intermediate-machine-learning','summary':'Missing values, leakage, pipelines and model quality.'},
 {'id':'cs50ai','title':'CS50 Introduction to Artificial Intelligence with Python','provider':'Harvard CS50','skill':'AI & ML','level':'Intermediate','price':'Free to learn','url':'https://cs50.harvard.edu/ai/','summary':'Search, knowledge, optimization, and machine learning concepts.'},
 {'id':'kaggle-sql','title':'Intro to SQL','provider':'Kaggle Learn','skill':'SQL','level':'Foundation','price':'Free','url':'https://www.kaggle.com/learn/intro-to-sql','summary':'Querying structured datasets with SQL.'},
 {'id':'kaggle-advsql','title':'Advanced SQL','provider':'Kaggle Learn','skill':'SQL','level':'Practice','price':'Free','url':'https://www.kaggle.com/learn/advanced-sql','summary':'Analytical SQL and complex queries.'},
 {'id':'fcc-rwd','title':'Responsive Web Design','provider':'freeCodeCamp','skill':'Web & APIs','level':'Foundation','price':'Free','url':'https://www.freecodecamp.org/learn/2022/responsive-web-design/','summary':'Build accessible web interfaces and layouts.'},
 {'id':'pw-fullstack','title':'Full Stack Web Development','provider':'PW Skills','skill':'Web & APIs','level':'Structured','price':'Check provider pricing','url':'https://pwskills.com/web-development/full-stack-web-development-course/','summary':'Structured full-stack project learning.'},
 {'id':'toast','title':'Toastmasters — Find a Club','provider':'Toastmasters International','skill':'Communication','level':'Speaking practice','price':'Membership may cost','url':'https://www.toastmasters.org/find-a-club','summary':'Practice speaking, feedback and presenting in a group.'},
 {'id':'mitcomm','title':'Communication for Leaders — OpenCourseWare','provider':'MIT OpenCourseWare','skill':'Communication','level':'Reading/practice','price':'Free','url':'https://ocw.mit.edu/search/?q=communication','summary':'Browse open communication and presentation learning materials.'},
 {'id':'openlearn-comm','title':'Effective Communication in the Workplace','provider':'The Open University — OpenLearn','skill':'Communication','level':'Foundation','price':'Free','url':'https://www.open.edu/openlearn/money-business/effective-communication-the-workplace','summary':'Practice communication and earn a learning badge.'},
 {'id':'wharton-comm','title':'Improving Communication Skills','provider':'Wharton / Coursera','skill':'Communication','level':'Structured','price':'Check Coursera access/pricing','url':'https://www.coursera.org/learn/wharton-communication-skills','summary':'Clear, persuasive communication in professional settings.'},
 {'id':'kaggle-python','title':'Python — Practical Programming','provider':'Kaggle Learn','skill':'Technical depth','level':'Foundation','price':'Free','url':'https://www.kaggle.com/learn/python','summary':'Python syntax, functions, data manipulation and practice.'},
 {'id':'fcc-python','title':'Scientific Computing with Python','provider':'freeCodeCamp','skill':'Technical depth','level':'Projects','price':'Free','url':'https://www.freecodecamp.org/learn/scientific-computing-with-python','summary':'Strengthen coding foundations through hands-on practice.'},
 {'id':'microsoftlearn','title':'Microsoft Learn — Technical Learning Paths','provider':'Microsoft Learn','skill':'Technical depth','level':'Role-based','price':'Free learning','url':'https://learn.microsoft.com/en-us/training/','summary':'Hands-on modules for cloud, coding, and professional skills.'},
]

MAP_SKILLS={
 'Python':'Technical depth','SQL':'SQL','Machine Learning':'AI & ML','Data Structures':'DSA',
 'APIs':'Web & APIs','JavaScript':'Web & APIs','Cloud':'Technical depth','Testing':'Technical depth',
 'Project Defense':'Communication',
}


def initialize_career():
 with connection() as db:
  db.execute('''CREATE TABLE IF NOT EXISTS applications (
    id TEXT PRIMARY KEY, user_id TEXT NOT NULL, company TEXT NOT NULL, role TEXT NOT NULL,
    status TEXT NOT NULL, location TEXT NOT NULL DEFAULT '', source TEXT NOT NULL DEFAULT 'manual',
    applied_on TEXT, interview_at TEXT, job_description TEXT NOT NULL DEFAULT '',
    notes TEXT NOT NULL DEFAULT '', feedback TEXT NOT NULL DEFAULT '',
    source_message_id TEXT, created_at TEXT NOT NULL, updated_at TEXT NOT NULL,
    FOREIGN KEY(user_id) REFERENCES users(id))''')
  db.execute('CREATE INDEX IF NOT EXISTS ix_application_user ON applications(user_id)')
  db.execute('CREATE UNIQUE INDEX IF NOT EXISTS ix_application_mail ON applications(user_id,source_message_id) WHERE source_message_id IS NOT NULL')
  db.execute('''CREATE TABLE IF NOT EXISTS learning_progress(
     user_id TEXT NOT NULL, course_id TEXT NOT NULL, progress TEXT NOT NULL,
     updated_at TEXT NOT NULL, PRIMARY KEY(user_id,course_id))''')


class ApplicationIn(BaseModel):
 company:str=Field(min_length=2,max_length=120)
 role:str=Field(min_length=2,max_length=160)
 status:Literal['saved','applied','screening','interview','completed','offer','rejected']='applied'
 location:str=Field(default='',max_length=160)
 applied_on:str|None=Field(default=None,max_length=10)
 interview_at:str|None=Field(default=None,max_length=40)
 job_description:str=Field(default='',max_length=6000)
 notes:str=Field(default='',max_length=3000)
 feedback:str=Field(default='',max_length=3000)

class ApplicationUpdate(BaseModel):
 company:str|None=Field(default=None,min_length=2,max_length=120)
 role:str|None=Field(default=None,min_length=2,max_length=160)
 status:Literal['saved','applied','screening','interview','completed','offer','rejected']|None=None
 location:str|None=Field(default=None,max_length=160)
 applied_on:str|None=None
 interview_at:str|None=None
 job_description:str|None=Field(default=None,max_length=6000)
 notes:str|None=Field(default=None,max_length=3000)
 feedback:str|None=Field(default=None,max_length=3000)


def safe_schedule(value):
 if not value:return None
 try: return datetime.fromisoformat(value.replace('Z','+00:00')).isoformat(timespec='minutes')
 except ValueError: raise HTTPException(422,'Interview date must be ISO 8601, for example 2026-11-26T10:30.')


def safe_date(value):
 if not value:return None
 try: return datetime.strptime(value,'%Y-%m-%d').date().isoformat()
 except ValueError:raise HTTPException(422,'Application date must be YYYY-MM-DD.')


def own_application(db, aid, owner):
 row=db.execute('SELECT * FROM applications WHERE id=? AND user_id=?',(aid,owner)).fetchone()
 if row is None:raise HTTPException(404,'Application not found')
 return dict(row)

@router.get('/applications')
def applications(user=Depends(current_user)):
 with connection() as db:
  return [dict(r) for r in db.execute('SELECT * FROM applications WHERE user_id=? ORDER BY updated_at DESC',(user['id'],)).fetchall()]

@router.post('/applications',status_code=201)
def create_application(item:ApplicationIn,user=Depends(mutation_user)):
 aid=uuid.uuid4().hex
 with connection() as db:
  db.execute('''INSERT INTO applications(id,user_id,company,role,status,location,source,applied_on,interview_at,job_description,notes,feedback,created_at,updated_at)
                VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)''',
      (aid,user['id'],item.company.strip(),item.role.strip(),item.status,item.location,'manual',safe_date(item.applied_on),safe_schedule(item.interview_at),item.job_description,item.notes,item.feedback,stamp(),stamp()))
  return own_application(db,aid,user['id'])

@router.patch('/applications/{aid}')
def update_application(aid:str,item:ApplicationUpdate,user=Depends(mutation_user)):
 with connection() as db:
  own_application(db,aid,user['id'])
  changes=item.model_dump(exclude_unset=True)
  if 'interview_at' in changes: changes['interview_at']=safe_schedule(changes['interview_at'])
  if 'applied_on' in changes:changes['applied_on']=safe_date(changes['applied_on'])
  if changes:
   columns=list(changes)
   db.execute('UPDATE applications SET '+','.join(f'{key}=?' for key in columns)+',updated_at=? WHERE id=? AND user_id=?',
     (*[changes[k] for k in columns],stamp(),aid,user['id']))
  return own_application(db,aid,user['id'])

@router.delete('/applications/{aid}')
def delete_application(aid:str,user=Depends(mutation_user)):
 with connection() as db:
  own_application(db,aid,user['id'])
  db.execute('DELETE FROM applications WHERE id=? AND user_id=?',(aid,user['id']))
 return {'deleted':True}


def course_needs(owner):
 """Transparent heuristic: low assessed dimensions or explicit target skill, not a diagnosis."""
 with connection() as db:
  rows=db.execute('SELECT skills,turns FROM sessions WHERE user_id=? ORDER BY created DESC LIMIT 15',(owner,)).fetchall()
 candidates=[]
 for row in rows:
  turns=json.loads(row['turns'] or '[]')
  for t in turns:
   a=t.get('assessment',{})
   dims=a.get('dimensions',{})
   skill=MAP_SKILLS.get(a.get('target_skill',''),'Technical depth')
   technical=dims.get('technical')
   if isinstance(technical,(int,float)) and technical<75: candidates.append((skill,technical,'Interview practice'))
   for dimension in ('clarity','structure','delivery'):
    v=dims.get(dimension)
    if isinstance(v,(int,float)) and v<75:
     candidates.append(('Communication',v,'Communication feedback'))
 if not candidates:return {'focus':'DSA','reason':'Start with a foundational track. Complete an interview for personalized recommendations.','evidence_count':0,'data_quality':'Starter suggestion'}
 aggregate={}
 for skill,value,src in candidates:aggregate.setdefault(skill,[]).append(value)
 focus=min(aggregate,key=lambda k:sum(aggregate[k])/len(aggregate[k]))
 return {'focus':focus,'reason':f'Your recent practice feedback suggests reviewing {focus}. This is an indicative practice signal, not a hiring assessment.','evidence_count':len(aggregate[focus]),'data_quality':'Practice-based'}

@router.get('/courses')
def courses(skill:str|None=None,user=Depends(current_user)):
 focus=course_needs(user['id'])
 chosen=skill if skill in {c['skill'] for c in COURSES} else focus['focus']
 with connection() as db:
  progress={r['course_id']:r['progress'] for r in db.execute('SELECT course_id,progress FROM learning_progress WHERE user_id=?',(user['id'],)).fetchall()}
 rank=[c for c in COURSES if c['skill']==chosen]
 other=[c for c in COURSES if c['skill']!=chosen]
 ranked=(rank+other)[:16]
 return {'focus':focus,'selected_skill':chosen,'skills':sorted({c['skill'] for c in COURSES}),
         'courses':[{**c,'progress':progress.get(c['id'],'not_started'),'sponsored':False,'affiliate':False} for c in ranked],
         'disclosure':'No paid partnerships or affiliate tracking are configured. If sponsored placements are introduced, they must be labeled and separated from relevance ranking.'}

class CourseProgress(BaseModel):
 status:Literal['not_started','in_progress','completed']

@router.put('/courses/{cid}/progress')
def update_course(cid:str,item:CourseProgress,user=Depends(mutation_user)):
 if cid not in {c['id'] for c in COURSES}:raise HTTPException(404,'Course not found')
 with connection() as db:
  db.execute('INSERT INTO learning_progress VALUES(?,?,?,?) ON CONFLICT(user_id,course_id) DO UPDATE SET progress=excluded.progress,updated_at=excluded.updated_at',
   (user['id'],cid,item.status,stamp()))
 return {'course_id':cid,'progress':item.status}

@router.get('/agenda')
def agenda(user=Depends(current_user)):
 with connection() as db:
  rows=[dict(r) for r in db.execute("SELECT * FROM applications WHERE user_id=? AND interview_at IS NOT NULL AND status NOT IN ('rejected','offer','completed') ORDER BY interview_at",(user['id'],)).fetchall()]
 events=[]
 for a in rows:
  try: when=datetime.fromisoformat(a['interview_at']);label=when.strftime('%d %b %Y, %I:%M %p')
  except ValueError:continue
  events.append({'application_id':a['id'],'company':a['company'],'role':a['role'],'interview_at':a['interview_at'],'label':label,
                 'prep':[{'offset':'-2 days','task':f'Review the {a["role"]} requirements and identify three relevant projects.'},
                         {'offset':'-1 day','task':'Practice one technical interview and review your weakest answer.'},
                         {'offset':'-2 hours','task':'Check meeting details, equipment, and prepare concise project stories.'}]})
 return {'interviews':events,'note':'In-app preparation tasks are generated automatically when a confirmed interview date is saved. Google Calendar export is optional and requires consent.'}

@router.get('/insights')
def insights(user=Depends(current_user)):
 with connection() as db:
  rows=[dict(r) for r in db.execute('SELECT status,feedback,company FROM applications WHERE user_id=?',(user['id'],))]
 counts={k:sum(r['status']==k for r in rows) for k in STATUS}
 comments=[{'company':r['company'],'feedback':r['feedback'][:500]} for r in rows if r['feedback'].strip()]
 themes=[]
 theme_patterns={'Communication':['communication','speaking','presentation','clarity'],
    'Technical depth':['technical','fundamentals','coding','architecture'],
    'DSA':['algorithm','data structure','complexity'],
    'Project explanation':['project','explain','experience','ownership']}
 for label,terms in theme_patterns.items():
  matches=[{'company':r['company'],'excerpt':r['feedback'][:200]} for r in rows
           if r['feedback'] and any(term in r['feedback'].lower() for term in terms)]
  if matches:themes.append({'theme':label,'count':len(matches),'evidence':matches[:3]})
 return {'total':len(rows),'by_status':counts,'recruiter_feedback':comments[:8],'themes':themes,
         'recommendation':('Review role fit and resume evidence; rejection data alone cannot establish the cause.' if counts['rejected'] else 'Keep application stages and interview dates updated for more useful insights.')}

@router.get('/missions')
def missions(user=Depends(current_user)):
 focus=course_needs(user['id'])['focus']
 if focus=='Communication':
  tasks=['Record a 60-second STAR story about a project and remove repeated filler phrases.',
         'Answer “Why should we hire you?” in under 90 seconds with a specific example.',
         'Retry one previous interview answer and compare clarity and structure.']
 elif focus=='DSA':
  tasks=['Explain hash maps vs arrays aloud, including time complexity.',
         'Solve one two-pointer challenge and justify your complexity.',
         'Discuss an alternative solution and why you rejected it.']
 elif focus=='AI & ML':
  tasks=['Explain train/test leakage with a concrete example.',
         'Choose a metric for an imbalanced classification project and defend it.',
         'Describe an experiment that would expose model overfitting.']
 else:
  tasks=[f'Explain a {focus} concept in 60 seconds without reading notes.',
         f'Describe a real mistake you debugged using {focus} skills.',
         'Retry your weakest answer and support it with a real test or evidence.']
 return {'focus':focus,'tasks':tasks,'note':'Suggested practice exercises, not verified certificates or proof of skill.'}

