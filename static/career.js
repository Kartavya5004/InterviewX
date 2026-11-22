'use strict';
const $=id=>document.getElementById(id);
const h=v=>String(v??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
let csrf='', apps=[], suggestions=[], connected={}, selectedTab='pipeline';
const stages=[['saved','Saved'],['applied','Applied'],['screening','Screening'],['interview','Interview'],['completed','Completed'],['offer','Offer'],['rejected','Rejected']];
function msg(message,problem=false){const n=$('notice');n.textContent=message;n.hidden=false;n.style.background=problem?'#ffe6db':'#eaffbe';n.style.borderColor=problem?'#fa8f75':'#b8df66';clearTimeout(msg.t);msg.t=setTimeout(()=>n.hidden=true,6500)}
async function api(url,options={}){
 const method=options.method||'GET',headers={'Content-Type':'application/json',...(options.headers||{})};
 if(method!=='GET')headers['X-CSRF-Token']=csrf;
 const response=await fetch(url,{credentials:'same-origin',...options,headers});
 if(response.status===401){location.href='/login';throw Error('Sign in required')}
 let data;try{data=await response.json()}catch{throw Error('The server could not return JSON')}
 if(!response.ok)throw Error(data.detail||`Request failed (${response.status})`);
 return data;
}
function busy(el,value){if(el)el.disabled=value}
function show(tab){
 selectedTab=tab;document.querySelectorAll('.screen').forEach(s=>s.hidden=s.id!==tab);
 document.querySelectorAll('button[data-tab]').forEach(b=>b.classList.toggle('active',b.dataset.tab===tab));
 $('breadcrumb').textContent=({pipeline:'APPLICATION PIPELINE',learning:'SKILL PRESCRIPTIONS',inbox:'INBOX INTELLIGENCE',agenda:'INTERVIEW PLANNER'})[tab];
 window.scrollTo({top:0,behavior:'smooth'});
 if(tab==='learning')refreshCourses();if(tab==='inbox')refreshInbox();if(tab==='agenda')refreshAgenda();
}
async function refreshApps(){
 apps=await api('/api/career/applications');renderBoard();
}
function count(s){return apps.filter(a=>a.status===s).length}
function renderBoard(){
 $('statTotal').textContent=apps.length;
 $('statScheduled').textContent=apps.filter(a=>a.status==='interview'&&a.interview_at).length;
 $('statOffer').textContent=count('offer');$('statFollow').textContent=count('applied')+count('screening');
 $('pipelineInsight').textContent=apps.length?
  `${count('applied')+count('screening')} application(s) are waiting for an outcome. ${count('interview')} interview-stage opportunity(ies). ${count('rejected')} recorded rejections — the tracker cannot infer why unless recruiter feedback was provided.`:
  'Add a company and role to begin. Drag it across the board as the application progresses; every move saves to your private account.';
 $('kanban').innerHTML=stages.map(([key,name])=>{
 const items=apps.filter(a=>a.status===key);
 return `<section class="lane" data-stage="${key}" aria-label="${h(name)} column"><div class="lane-head"><i class="stage-dot stage-${key}"></i><strong>${h(name)}</strong><span>${items.length}</span></div>${items.length?items.map(a=>`<article class="job" draggable="true" data-job="${h(a.id)}" tabindex="0"><strong>${h(a.role)}</strong><span class="company">${h(a.company)}</span><span class="source">${a.source==='gmail'?'◉ EMAIL CONFIRMED':'◈ MANUAL'}</span>${a.interview_at?`<span class="date">◷ ${h(a.interview_at.replace('T',' · '))}</span>`:''}<div class="job-actions"><button type="button" data-edit="${h(a.id)}">Edit ↗</button><select aria-label="Move ${h(a.company)} to a new stage" data-move="${h(a.id)}">${stages.map(([k,n])=>`<option value="${k}" ${k===key?'selected':''}>${h(n)}</option>`).join('')}</select></div></article>`).join(''):'<p class="empty-lane">Drop a card here</p>'}</section>`}).join('');
 attachDrag();
}
function attachDrag(){
 document.querySelectorAll('.job[draggable]').forEach(node=>node.addEventListener('dragstart',ev=>{ev.dataTransfer.setData('text/plain',node.dataset.job);ev.dataTransfer.effectAllowed='move'}));
 document.querySelectorAll('.lane').forEach(lane=>{
  lane.addEventListener('dragover',e=>{e.preventDefault();lane.classList.add('drag-over')});
  lane.addEventListener('dragleave',()=>lane.classList.remove('drag-over'));
  lane.addEventListener('drop',async e=>{e.preventDefault();lane.classList.remove('drag-over');const id=e.dataTransfer.getData('text/plain');if(id)await moveApplication(id,lane.dataset.stage)});
 });
}
async function moveApplication(id,status){
 try{await api(`/api/career/applications/${encodeURIComponent(id)}`,{method:'PATCH',body:JSON.stringify({status})});await refreshApps();msg('Application stage saved.')}catch(err){msg(err.message,true);renderBoard()}
}
function openApplication(id=''){
 const a=apps.find(a=>a.id===id);
 $('dialogTitle').textContent=a?'Edit application':'New application';$('editId').value=a?.id||'';$('deleteApp').hidden=!a;
 $('formCompany').value=a?.company||'';$('formRole').value=a?.role||'';$('formStage').value=a?.status||'applied';
 $('formInterview').value=(a?.interview_at||'').slice(0,16);$('formApplied').value=a?.applied_on||'';
 $('formLocation').value=a?.location||'';$('formJD').value=a?.job_description||'';$('formNotes').value=a?.notes||'';$('formFeedback').value=a?.feedback||'';
 $('appDialog').showModal();
}
async function saveApplication(ev){
 ev.preventDefault();if(!$('appForm').checkValidity())return $('appForm').reportValidity();
 const id=$('editId').value, data={company:$('formCompany').value.trim(),role:$('formRole').value.trim(),status:$('formStage').value,
   interview_at:$('formInterview').value||null,applied_on:$('formApplied').value||null,location:$('formLocation').value,
   job_description:$('formJD').value,notes:$('formNotes').value,feedback:$('formFeedback').value};
 const b=$('saveApp');busy(b,true);
 try{await api(id?`/api/career/applications/${id}`:'/api/career/applications',{method:id?'PATCH':'POST',body:JSON.stringify(data)});
  $('appDialog').close();await refreshApps();msg('Application saved to your account.');}
 catch(err){msg(err.message,true)}finally{busy(b,false)}
}
async function refreshCourses(){
 try{
  const filter=$('skillFilter').value;const d=await api('/api/career/courses'+(filter?'?skill='+encodeURIComponent(filter):''));
  const current=$('skillFilter').value;
  $('skillFilter').innerHTML='<option value="">Personalized recommendation</option>'+d.skills.map(s=>`<option value="${h(s)}" ${s===current?'selected':''}>${h(s)}</option>`).join('');
  $('skillFocus').textContent=d.selected_skill;$('skillReason').textContent=d.focus.reason;
  const missions=await api('/api/career/missions');$('missions').innerHTML=missions.tasks.map(t=>`<li>${h(t)}</li>`).join('');
  $('courses').innerHTML=d.courses.map((c,i)=>`<article class="course"><div class="course-head"><span class="kind">${h(c.skill.toUpperCase())} · ${h(c.level)}</span><span class="mark">${c.sponsored?'SPONSORED':'NOT SPONSORED'}</span></div><h3>${h(c.title)}</h3><p>${h(c.provider)} · ${h(c.price)}</p><p style="margin-top:10px">${h(c.summary)}</p><div class="course-footer"><a href="${h(c.url)}" rel="noopener noreferrer" target="_blank">VIEW COURSE ↗</a><select data-progress="${h(c.id)}" aria-label="Learning progress for ${h(c.title)}"><option value="not_started" ${c.progress==='not_started'?'selected':''}>Not started</option><option value="in_progress" ${c.progress==='in_progress'?'selected':''}>In progress</option><option value="completed" ${c.progress==='completed'?'selected':''}>Completed ✓</option></select></div></article>`).join('');
 }catch(err){msg(err.message,true)}
}
async function refreshInbox(){
 try{
  const status=await api('/api/google/status');connected={};status.links.forEach(l=>connected[l.target]=l);
  $('gmailStatus').textContent=connected.gmail?'Connected to '+connected.gmail.email:status.configured?'Ready to connect using Google consent.':'Google OAuth environment variables are not configured.';
  $('calendarStatus').textContent=connected.calendar?'Google Calendar connected':'Optional: connect to export interviews after your confirmation.';
  for(const x of ['Gmail','Calendar']){$('connect'+x).hidden=!!connected[x.toLowerCase()];$('disconnect'+x).hidden=!connected[x.toLowerCase()];}
  $('autoSyncWrapper').hidden=!connected.gmail;
  $('autoGmail').checked=!!status.auto_sync;
  $('autoSyncStatus').textContent=status.last_error?'Last sync error: '+status.last_error:status.last_sync?'Last check: '+status.last_sync.slice(0,19).replace('T',' · ')+' UTC':'Automatic Gmail checking is opt-in.';
  suggestions=await api('/api/google/suggestions');renderSuggestions();
 }catch(err){msg(err.message,true)}
}
function renderSuggestions(){
 const pending=suggestions.filter(s=>s.review_status==='pending');
 $('suggestions').innerHTML=pending.length?pending.map(s=>`<article class="suggestion"><div><span class="tag">${h(s.status.toUpperCase())} · ${h(s.confidence)} confidence</span><h3>${h(s.subject)}</h3><div class="meta">FROM ${h(s.sender)} ${s.message_id.startsWith('demo-')?' · FICTIONAL DEMO MESSAGE':''}</div><p>${h(s.excerpt)}</p><p>${h(s.company)} / ${h(s.role)} ${s.interview_at?' · Potential interview: '+h(s.interview_at):''}</p></div><div class="suggestion-actions"><button class="primary" data-review="${h(s.id)}">REVIEW</button><button class="secondary" data-dismiss="${h(s.id)}">Dismiss</button></div></article>`).join(''):
 '<div class="empty-state"><strong>No pending email suggestions.</strong>Connect Gmail and scan on demand, or load fictional examples to test the workflow.</div>';
}
function openMailReview(id){
 const s=suggestions.find(x=>x.id===id);if(!s)return;
 $('mailSuggestionId').value=id;$('mailCompany').value=s.company;$('mailRole').value=s.role;
 $('mailStage').value=s.status;$('mailDate').value=(s.interview_at||'').slice(0,16);
 $('mailExisting').innerHTML='<option value="">Create new application</option>'+apps.map(a=>`<option value="${h(a.id)}">${h(a.company)} — ${h(a.role)}</option>`).join('');
 $('mailDialog').showModal();
}
async function acceptSuggestion(e){
 e.preventDefault();if(!$('mailForm').checkValidity())return $('mailForm').reportValidity();
 const body={company:$('mailCompany').value,role:$('mailRole').value,status:$('mailStage').value,
 interview_at:$('mailDate').value||null,application_id:$('mailExisting').value||null};
 try{await api(`/api/google/suggestions/${$('mailSuggestionId').value}/accept`,{method:'POST',body:JSON.stringify(body)});
  $('mailDialog').close();await Promise.all([refreshApps(),refreshInbox()]);msg('Email suggestion confirmed; application and preparation plan updated.');}
 catch(err){msg(err.message,true)}
}
async function refreshAgenda(){
 try{
  const d=await api('/api/career/agenda');
  $('agendaItems').innerHTML=d.interviews.length?d.interviews.map(a=>`<article class="agenda-card"><span class="date">◷ ${h(a.label)}</span><h3>${h(a.role)}</h3><p class="subtle">${h(a.company)}</p><ol>${a.prep.map(p=>`<li><strong>${h(p.offset)}:</strong> ${h(p.task)}</li>`).join('')}</ol><div class="btn-row"><button class="primary" data-calendar="${h(a.application_id)}">ADD TO GOOGLE CALENDAR ↗</button><button class="secondary" data-edit="${h(a.application_id)}">Edit schedule</button></div></article>`).join(''):
  '<div class="empty-state"><strong>No scheduled interviews yet.</strong>Set an interview date on an application or confirm an email suggestion to automatically create a preparation plan.</div>';
 }catch(err){msg(err.message,true)}
}
async function initialize(){
 try{
  const d=await api('/api/auth/me');csrf=d.csrf_token;
  $('identity').textContent=d.user.name+' · '+d.user.email;
  $('avatar').textContent=d.user.name.split(' ').map(x=>x[0]).join('').slice(0,2).toUpperCase();
  await refreshApps();
  try{const ins=await api('/api/career/insights');if(ins.themes.length){$('pipelineInsight').textContent=ins.themes.map(x=>`${x.theme}: ${x.count} recruiter-feedback note(s). For example, ${x.evidence[0].company} wrote: “${x.evidence[0].excerpt}”`).join(' • ')} }catch{}
  if(location.search.includes('integration=connected')){show('inbox');msg('Google connection completed. You can now sync on demand.');history.replaceState({},'', '/career')}
  else if(location.search.includes('integration=cancelled')){show('inbox');msg('Google connection cancelled. No access was granted.',true);history.replaceState({},'', '/career')}
 }catch(err){msg(err.message,true)}
}
document.querySelectorAll('.nav[data-tab]').forEach(el=>el.addEventListener('click',()=>show(el.dataset.tab)));
document.querySelectorAll('[data-go]').forEach(el=>el.addEventListener('click',()=>show(el.dataset.go)));
$('addApp').addEventListener('click',()=>openApplication());$('closeDialog').addEventListener('click',()=>$('appDialog').close());$('cancelDialog').addEventListener('click',()=>$('appDialog').close());$('appForm').addEventListener('submit',saveApplication);
$('deleteApp').addEventListener('click',async()=>{
 const id=$('editId').value;if(!id||!confirm('Delete this application record? This cannot be undone.'))return;
 try{await api('/api/career/applications/'+id,{method:'DELETE'});$('appDialog').close();await refreshApps();msg('Application deleted.')}catch(err){msg(err.message,true)}
});
$('closeMailDialog').addEventListener('click',()=>$('mailDialog').close());$('cancelMail').addEventListener('click',()=>$('mailDialog').close());$('mailForm').addEventListener('submit',acceptSuggestion);
$('kanban').addEventListener('click',ev=>{const el=ev.target.closest('[data-edit]');if(el)openApplication(el.dataset.edit)});
$('kanban').addEventListener('change',async ev=>{const el=ev.target.closest('[data-move]');if(el)await moveApplication(el.dataset.move,el.value)});
$('skillFilter').addEventListener('change',refreshCourses);
$('courses').addEventListener('change',async ev=>{const el=ev.target.closest('[data-progress]');if(el){try{await api('/api/career/courses/'+encodeURIComponent(el.dataset.progress)+'/progress',{method:'PUT',body:JSON.stringify({status:el.value})});msg('Learning progress saved.')}catch(err){msg(err.message,true)}}});
$('autoGmail').addEventListener('change',async ev=>{
 try{const d=await api('/api/google/auto-sync',{method:'PUT',body:JSON.stringify({enabled:ev.target.checked})});msg(d.message)}
 catch(err){ev.target.checked=!ev.target.checked;msg(err.message,true)}
});
$('connectGmail').addEventListener('click',()=>location.href='/api/google/connect/gmail');
$('connectCalendar').addEventListener('click',()=>location.href='/api/google/connect/calendar');
for(const target of ['Gmail','Calendar'])$('disconnect'+target).addEventListener('click',async()=>{if(!confirm(`Disconnect ${target} and remove locally stored credentials${target==='Gmail'?' and email suggestion excerpts':''}?`))return;try{await api(`/api/google/disconnect/${target.toLowerCase()}`,{method:'POST'});await refreshInbox();msg(target+' disconnected.')}catch(err){msg(err.message,true)}});
$('syncMail').addEventListener('click',async()=>{busy($('syncMail'),true);try{const d=await api('/api/google/sync',{method:'POST'});await refreshInbox();msg(`Gmail scanned ${d.scanned} messages; found ${d.new_suggestions} new suggestions for review.`)}catch(err){msg(err.message,true)}finally{busy($('syncMail'),false)}});
$('loadDemoMail').addEventListener('click',async()=>{try{await api('/api/google/demo-suggestions',{method:'POST'});await refreshInbox();msg('Fictional demonstration messages loaded; these are not real Gmail messages.')}catch(err){msg(err.message,true)}});
$('suggestions').addEventListener('click',async ev=>{const review=ev.target.closest('[data-review]'),dismiss=ev.target.closest('[data-dismiss]');if(review)openMailReview(review.dataset.review);if(dismiss){try{await api('/api/google/suggestions/'+dismiss.dataset.dismiss+'/dismiss',{method:'POST'});await refreshInbox()}catch(err){msg(err.message,true)}}});
$('agendaItems').addEventListener('click',async ev=>{const edit=ev.target.closest('[data-edit]'),cal=ev.target.closest('[data-calendar]');if(edit)openApplication(edit.dataset.edit);if(cal){busy(cal,true);try{const r=await api('/api/google/calendar/export/'+cal.dataset.calendar,{method:'POST'});msg(r.already_exported?'This interview was already added to Google Calendar.':'Interview event added to Google Calendar.');if(r.url)window.open(r.url,'_blank','noopener')}catch(err){msg(err.message,true)}finally{busy(cal,false)}}});
$('logout').addEventListener('click',async()=>{try{await api('/api/auth/logout',{method:'POST'});location.assign('/login')}catch(err){msg(err.message,true)}});
initialize();
