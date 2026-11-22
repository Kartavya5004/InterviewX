'use strict';
// InterviewX Voice Studio: lightweight, framework-free frontend.
const $ = id => document.getElementById(id);
const e = text => String(text ?? '').replace(/[&<>"']/g, ch => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[ch]));
let session = null;
let csrfToken = '';
let accountId = '';
let selectedMode = 'technical';
let currentView = 'setup';
let busy = false;
let lastReport = null;
let synthToken = 0;
const SpeechRecognitionCtor = window.SpeechRecognition || window.webkitSpeechRecognition;
const capture = {
  recognition: null, listening: false, target: 'answer', baseText: '',
  startedAt: 0, lastFinalAt: 0, pauseCount: 0, processedFinalCount: 0, voiceUsed: false, heardSpeech: false,
  durationSeconds: null, silentTimer: null, suppressAuto: false,
  stream: null, ctx: null, analyser: null, frame: 0, level: 0,
};
const DIMENSIONS = [
  {key:'technical', name:'Technical depth', color:'#fb593c'},
  {key:'clarity', name:'Clarity', color:'#7765e8'},
  {key:'structure', name:'Structure', color:'#181d18'},
  {key:'evidence', name:'Evidence', color:'#48bda8'},
  {key:'delivery', name:'Delivery cues', color:'#b5d744'},
];
function alertUser(message) { $('notice').textContent=message; $('notice').classList.remove('hidden'); }
function clearAlert(){ $('notice').classList.add('hidden'); }
function setBusy(v) {
  busy=v;
  ['startBtn','retryBtn','nextQuestion'].forEach(id=>{if($(id)) $(id).disabled=v;});
  $('submitAnswer').disabled=v || !session || session.status==='complete';
  $('micButton').disabled=v || !SpeechRecognitionCtor || !session || session.status==='complete';
  if(v) setVoiceState('ANALYZING ANSWER');
}
async function api(path, options={}) {
  const headers={'Content-Type':'application/json', ...(options.headers||{})};
  if(options.method && options.method.toUpperCase()!=='GET') headers['X-CSRF-Token']=csrfToken;
  const res=await fetch(path, {...options, headers});
  if(res.status===401){ window.location.assign('/login'); throw new Error('Session expired. Please sign in.'); }
  let data; try{data=await res.json();} catch{throw new Error('The server did not return JSON. Check FastAPI.');}
  if(!res.ok) throw new Error(typeof data.detail==='string'?data.detail:`Server error ${res.status}`);
  return data;
}
function view(name) {
  currentView=name;
  ['setup','interview','insights'].forEach(id=>$(id).classList.toggle('hidden',id!==name));
  document.querySelectorAll('.rail-link[data-view]').forEach(btn=>btn.classList.toggle('active',btn.dataset.view===name));
  $('crumbLabel').textContent=({setup:'OVERVIEW',interview:'INTERVIEW ROOM',insights:'PERFORMANCE DNA'})[name];
  clearAlert(); window.scrollTo({top:0,behavior:'smooth'});
  if(name==='insights') renderInsights();
}
function question() { return session?.questions[session.turns.length] ?? null; }
function setVoiceState(message) { $('voiceState').textContent=message; }
function currentInput(){return capture.target==='retry'?$('retryText'):$('answerText');}
function updatePreview(){
  const text=$('answerText').value.trim();
  $('transcriptPreview').textContent=text||'Your spoken answer will appear here in real time. You can correct transcription errors before sending it for analysis.';
  $('transcriptPreview').classList.toggle('has-answer',Boolean(text));
  $('wordsLive').textContent=(text.match(/\b[\w']+\b/g)||[]).length;
  const fillers=(text.match(/\b(?:um+|uh+|erm+|basically|you know|kind of|sort of)\b/gi)||[]);
  $('fillersLive').textContent=fillers.length;
  $('pausesLive').textContent=capture.voiceUsed?String(capture.pauseCount):'—';
  const duration=capture.listening? (Date.now()-capture.startedAt)/1000 : capture.durationSeconds;
  $('paceLive').textContent=capture.voiceUsed&&duration>3?String(Math.round((text.match(/\b[\w']+\b/g)||[]).length/duration*60)):'—';
}
function updateVoiceVisual(isListening=false,isTalking=false){
  $('orb').classList.toggle('listening',isListening);
  $('orb').classList.toggle('talking',isTalking);
  $('waveform').classList.toggle('active',isListening||isTalking);
  $('transcriptStatus').textContent=isListening?'● CAPTURING':'STANDBY';
  $('transcriptStatus').classList.toggle('live',isListening);
  $('micButton').textContent=isListening?'■ Stop listening':'◉ Start speaking';
  $('endSpeaking').disabled=!isListening;
  $('retryMic').textContent=isListening&&capture.target==='retry'?'■ Finish retry':'◉ Speak retry';
}
function stopAudioMeter(){
  if(capture.frame) cancelAnimationFrame(capture.frame);
  capture.frame=0;
  if(capture.stream){capture.stream.getTracks().forEach(track=>track.stop());capture.stream=null;}
  if(capture.ctx){capture.ctx.close().catch(()=>{});capture.ctx=null;}
  capture.analyser=null;
}
async function startAudioMeter(){
  if(!navigator.mediaDevices?.getUserMedia) return;
  try {
    capture.stream=await navigator.mediaDevices.getUserMedia({audio:true,video:false});
    if(!capture.listening){stopAudioMeter();return;}
    const Ctx=window.AudioContext||window.webkitAudioContext;
    if(!Ctx) return;
    capture.ctx=new Ctx();
    const source=capture.ctx.createMediaStreamSource(capture.stream);
    capture.analyser=capture.ctx.createAnalyser(); capture.analyser.fftSize=512;
    source.connect(capture.analyser);
    const arr=new Uint8Array(capture.analyser.fftSize);
    const bars=Array.from($('waveform').children);
    function animate(){
      if(!capture.listening||!capture.analyser)return;
      capture.analyser.getByteTimeDomainData(arr);
      let sq=0; for(const x of arr){const v=(x-128)/128;sq+=v*v;}
      const rms=Math.sqrt(sq/arr.length);
      const strength=Math.min(1,rms*6);
      bars.forEach((bar,i)=>{const weight=0.35+0.65*Math.abs(Math.sin(i*1.8+Date.now()/400));bar.style.height=`${Math.max(5,Math.round(7+strength*38*weight))}px`;bar.style.opacity=String(.45+strength*.5);});
      capture.frame=requestAnimationFrame(animate);
    }
    animate();
  } catch(err) { // Meter visualization is optional; speech recognition handles its own permissions.
    stopAudioMeter();
  }
}
function cancelTTS(){
  synthToken++;
  if('speechSynthesis' in window) window.speechSynthesis.cancel();
}
function tts(text, after){
  if(!$('voiceEnabled').checked || !('speechSynthesis' in window)) { if(after)after(); return; }
  cancelTTS();
  const token=synthToken;
  const utterance=new SpeechSynthesisUtterance(text);
  utterance.rate=.96; utterance.pitch=.96; utterance.lang='en-US';
  const voices=window.speechSynthesis.getVoices();
  const selected=voices.find(v=>v.voiceURI===$('voiceSelect').value);
  if(selected)utterance.voice=selected;
  setVoiceState('INTERVIEWER SPEAKING');
  updateVoiceVisual(false,true);
  const ended=()=>{if(token!==synthToken)return;updateVoiceVisual(false,false);setVoiceState('YOUR TURN TO SPEAK');if(after)after();};
  utterance.onend=ended;
  utterance.onerror=ended;
  window.speechSynthesis.speak(utterance);
}
function speakQuestion(){
  if(!question())return;
  tts(question(),()=>{if($('voiceEnabled').checked && $('autoListen').checked && session?.status==='active')startListening('answer');});
}
function stopCapture(suppressAuto=true){
  clearTimeout(capture.silentTimer);
  capture.silentTimer=null;
  capture.suppressAuto=suppressAuto;
  if(capture.listening && capture.recognition){
    try{capture.recognition.stop();}catch{}
  }
  capture.listening=false;
  if(capture.startedAt)capture.durationSeconds=Math.max(0,(Date.now()-capture.startedAt)/1000);
  stopAudioMeter();
  updateVoiceVisual(false,false);
  setVoiceState('READY TO ANALYZE');
  updatePreview();
}
function resetCapture(){
  stopCapture(true);
  capture.recognition=null;
  capture.baseText=''; capture.startedAt=0; capture.lastFinalAt=0;
  capture.pauseCount=0; capture.voiceUsed=false;capture.heardSpeech=false;capture.durationSeconds=null;capture.suppressAuto=false;
  $('answerText').value='';updatePreview();
}
function buildSpeechMetrics(target='answer'){
  const isVoice=capture.voiceUsed&&capture.target===target;
  return {input_mode:isVoice?'voice':'typed',duration_seconds:isVoice?(capture.durationSeconds??Math.max(0,(Date.now()-capture.startedAt)/1000)):null,pause_count:isVoice?capture.pauseCount:null};
}
async function startListening(target='answer'){
  if(busy)return;
  if(!SpeechRecognitionCtor){alertUser('This browser does not provide SpeechRecognition. Try recent Chrome or Edge, or use the typing fallback.');return;}
  if(capture.listening){ stopCapture(false); return; }
  if(target==='answer' && session?.status!=='active')return;
  cancelTTS();
  clearTimeout(capture.silentTimer);
  capture.target=target;
  capture.baseText=currentInput().value.trim();
  capture.startedAt=Date.now();capture.lastFinalAt=0;capture.pauseCount=0;capture.processedFinalCount=0;
  capture.voiceUsed=true;capture.heardSpeech=false;capture.suppressAuto=false;capture.durationSeconds=null;
  let recognition;
  try {recognition=new SpeechRecognitionCtor();}catch(err){alertUser('Speech recognition could not be initialized: '+err.message);return;}
  capture.recognition=recognition;
  recognition.lang='en-IN';recognition.continuous=true;recognition.interimResults=true;recognition.maxAlternatives=1;
  recognition.onresult=evt=>{
    if(capture.recognition!==recognition)return;
    let finalized='',interim='',newFinal=0;
    for(let i=0;i<evt.results.length;i++){
      const part=evt.results[i][0]?.transcript||'';
      if(evt.results[i].isFinal){finalized+=' '+part;if(i>=capture.processedFinalCount)newFinal++;} else interim+=' '+part;
    }
    if((finalized+interim).trim())capture.heardSpeech=true;
    const total=[capture.baseText,finalized,interim].filter(x=>x&&x.trim()).join(' ').replace(/\s+/g,' ').trim();
    currentInput().value=total;
    updatePreview();
    if(newFinal){
      capture.processedFinalCount=evt.results.length;
      const now=Date.now();
      if(capture.lastFinalAt&&now-capture.lastFinalAt>=1800)capture.pauseCount++;
      capture.lastFinalAt=now;
    }
    clearTimeout(capture.silentTimer);
    if($('autoSubmit').checked && total.split(/\s+/).length>=6){
      capture.silentTimer=setTimeout(()=>{if(capture.listening)stopCapture(false);},3500);
    }
  };
  recognition.onerror=evt=>{
    if(evt.error!=='aborted' && evt.error!=='no-speech')
      alertUser(`Microphone / speech recognition: ${evt.error}. If necessary, switch to the typing fallback.`);
  };
  recognition.onend=()=>{
    if(capture.recognition!==recognition)return;
    const shouldSubmit=capture.heardSpeech && !capture.suppressAuto && $('autoSubmit').checked && currentInput().value.trim().split(/\s+/).length>=6;
    const targetAtStop=capture.target;
    capture.listening=false;
    if(capture.startedAt)capture.durationSeconds=Math.max(0,(Date.now()-capture.startedAt)/1000);
    stopAudioMeter();updateVoiceVisual(false,false);setVoiceState('RESPONSE READY');updatePreview();
    if(shouldSubmit&&!busy){if(targetAtStop==='retry')retry();else submitAnswer();}
  };
  try {
    recognition.start();capture.listening=true;setVoiceState('LISTENING TO YOU');updateVoiceVisual(true,false);
    $('voiceHint').textContent='Speak naturally. The transcript is shown below. Finish manually, or let silence detection submit your answer.';
    await startAudioMeter();
  } catch(err){capture.listening=false;updateVoiceVisual();alertUser('Cannot start microphone: '+err.message);}
}
function renderMiniBars(){
  const last=session?.turns.at(-1)?.assessment;
  if(!last){$('liveSkillBars').innerHTML='<p class="empty-hint">Your first evaluated answer will populate these bars.</p>';return;}
  $('liveSkillBars').innerHTML=DIMENSIONS.map((dim)=>{
    const value=last.dimensions?.[dim.key];
    return `<div><div class="skill-bar-head"><span>${e(dim.name)}</span><span>${value==null?'—':e(value)+'/100'}</span></div><div class="skill-track"><div style="width:${value==null?0:Math.max(0,Math.min(100,value))}%;background:${dim.color}"></div></div></div>`;
  }).join('');
}
function renderInterview(){
  if(!session)return;
  const idx=session.turns.length;
  const total=session.questions.length;
  $('roundLabel').textContent=`ROUND ${String(Math.min(idx+1,total)).padStart(2,'0')} / ${String(total).padStart(2,'0')}`;
  $('questionIndex').textContent=`${String(Math.min(idx+1,total)).padStart(2,'0')} / ${String(total).padStart(2,'0')}`;
  $('interviewCaption').textContent=`${session.role} · ${session.company} · ${session.mode.toUpperCase()} MODE`;
  $('questionText').textContent=question()||'Your session is complete. Review your Performance DNA and try a stronger answer.';
  $('questionMode').textContent=({technical:'Technical round',project:'Project defense',pressure:'Challenge mode'})[session.mode]||'Practice';
  $('questionSkill').textContent=idx===0?'RESUME CLAIM':(session.skills[(idx-1)%session.skills.length]||'FOLLOW-UP').toUpperCase();
  $('submitAnswer').disabled=busy||session.status==='complete';
  $('micButton').disabled=busy||session.status==='complete';
  renderMiniBars();
  $('inlineFeedback').classList.add('hidden');
  if(session.status==='complete'){
    setVoiceState('SESSION COMPLETE');
    $('voiceHint').textContent='Great work. Visit Performance DNA for scores, communication feedback and answer repair.';
  } else {
    setVoiceState('READY TO SPEAK');
  }
}
function feedbackCard(assessment, complete){
  $('inlineFeedback').classList.remove('hidden');
  $('quickHeadline').textContent=`${assessment.score}/100 · ${assessment.mode==='gemini'?'AI COACHING':'DEMO PRACTICE PROXY'}`;
  $('quickMode').textContent=assessment.mode==='gemini'?'GEMINI REVIEW':'HEURISTIC DEMO';
  $('quickGap').textContent=assessment.gaps[0]||'Add precise technical evidence and a concrete result.';
  $('quickIdeal').textContent=assessment.ideal_answer||'Use your real experience and verifiable examples to answer with clarity.';
  $('nextQuestion').textContent=complete?'SEE YOUR PERFORMANCE ↗':'HEAR NEXT QUESTION ↗';
  $('inlineFeedback').scrollIntoView({behavior:'smooth',block:'center'});
}
async function startSession(){
  const payload={role:$('role').value.trim(),company:$('company').value.trim(),resume:$('resume').value.trim(),job_description:$('jd').value.trim(),mode:selectedMode};
  if(payload.resume.length<20||payload.job_description.length<15){alertUser('Please add a resume excerpt (20+ characters) and job description (15+ characters), or load the demo profile.');return;}
  try{
    setBusy(true);
    session=await api('/api/start',{method:'POST',body:JSON.stringify(payload)});
    localStorage.setItem('interviewx-session-id:'+accountId,session.id);
    resetCapture();renderInterview();view('interview');
    // First spoken prompt begins from the user's Launch action.
    if($('voiceEnabled').checked)speakQuestion();
  }catch(err){alertUser(err.message);}finally{setBusy(false);}
}
async function submitAnswer(){
  if(busy||!session||session.status==='complete')return;
  if(capture.listening)stopCapture(true);
  const answer=$('answerText').value.trim();
  if(!answer){alertUser('Please speak an answer or open the typing fallback.');return;}
  const speech_metrics=buildSpeechMetrics('answer');
  try{
    setBusy(true);
    session=await api(`/api/sessions/${encodeURIComponent(session.id)}/answer`,{
      method:'POST',body:JSON.stringify({answer,confidence:Number($('confidence').value),speech_metrics})
    });
    const last=session.turns.at(-1)?.assessment;
    resetCapture();renderInterview();feedbackCard(last,session.status==='complete');
    setVoiceState('COACHING AVAILABLE');
    if($('voiceEnabled').checked){tts(`Here's your feedback. ${last.gaps?.[0]||'Add more specific evidence.'} A concise improved answer could be: ${last.short_answer||'State your role, decision, and result.'}`);}
  }catch(err){alertUser('Answer evaluation failed: '+err.message);}finally{setBusy(false);}
}
function nextQuestion(){
  if(!session)return;
  if(session.status==='complete'){view('insights');return;}
  $('inlineFeedback').classList.add('hidden');
  $('interview').scrollIntoView({behavior:'smooth',block:'start'});
  speakQuestion();
}
function dimsFromReport(r){return r?.dimension_averages||{};}
function svgNode(type, attrs, text=null){
  const node=document.createElementNS('http://www.w3.org/2000/svg',type);
  for(const [key,value] of Object.entries(attrs))node.setAttribute(key,String(value));
  if(text!==null)node.textContent=String(text);
  return node;
}
function radarGraph(scores){
  const svg=$('radarChart');svg.innerHTML='';
  const cx=215,cy=170,maxR=111,n=5;
  const point=(i,r)=>{const a=(-Math.PI/2)+i*(Math.PI*2/n);return [cx+Math.cos(a)*r,cy+Math.sin(a)*r];};
  const polygon=arr=>arr.map(([x,y])=>`${x.toFixed(1)},${y.toFixed(1)}`).join(' ');
  for(const level of [.25,.5,.75,1]){
    svg.append(svgNode('polygon',{points:polygon(Array.from({length:n},(_,i)=>point(i,maxR*level))),fill:level===1?'#eeefe3':'none',stroke:'#d2d5c9','stroke-width':1}));
  }
  DIMENSIONS.forEach((dim,i)=>{
    const [ax,ay]=point(i,maxR);svg.append(svgNode('line',{x1:cx,y1:cy,x2:ax,y2:ay,stroke:'#d2d5c9','stroke-width':1}));
    const [tx,ty]=point(i,149);
    svg.append(svgNode('text',{x:tx,y:ty,'font-size':12,'text-anchor':Math.abs(tx-cx)<12?'middle':tx>cx?'start':'end','font-family':'DM Sans, sans-serif','font-weight':700,fill:'#515a50'},dim.name));
    const val=scores[dim.key];
    svg.append(svgNode('text',{x:tx,y:ty+15,'font-size':11,'text-anchor':Math.abs(tx-cx)<12?'middle':tx>cx?'start':'end','font-weight':800,fill:'#8a8e83'},val==null?'Not measured':val+'/100'));
  });
  const available=DIMENSIONS.map((dim,i)=>({i,value:scores[dim.key]})).filter(x=>typeof x.value==='number');
  if(available.length>=3){
    const plot=available.map(({i,value})=>point(i,maxR*value/100));
    svg.append(svgNode('polygon',{points:polygon(plot),fill:'#d9fd62','fill-opacity':.55,stroke:'#263429','stroke-width':2.7,'stroke-linejoin':'round'}));
    const min=available.reduce((a,b)=>a.value<=b.value?a:b);
    available.forEach(({i,value})=>{const [x,y]=point(i,maxR*value/100);svg.append(svgNode('circle',{cx:x,cy:y,r:i===min.i?7:5,fill:i===min.i?'#fb593c':'#263429',stroke:'#fffdf7','stroke-width':2}));});
  }else{
    svg.append(svgNode('text',{x:215,y:173,'font-size':13,'text-anchor':'middle',fill:'#858b80'},'ANSWER A QUESTION TO BEGIN'));
  }
}
function trendGraph(values){
  const svg=$('trendChart');svg.innerHTML='';
  [25,50,75,100].forEach(val=>{const y=152-(val/100)*125;svg.append(svgNode('line',{x1:37,x2:415,y1:y,y2:y,stroke:'#e1e2d7','stroke-width':1}));svg.append(svgNode('text',{x:9,y:y+4,'font-size':10,fill:'#7d8379'},val));});
  if(!values.length){svg.append(svgNode('text',{x:215,y:95,'font-size':13,'text-anchor':'middle',fill:'#899084'},'Your trend will appear after an answer'));return;}
  const coords=values.map((val,i)=>[values.length===1?225:50+i*(345/(values.length-1)),152-(val/100)*125]);
  if(coords.length>1){svg.append(svgNode('polyline',{points:coords.map(p=>p.join(',')).join(' '),stroke:'#fb593c','stroke-width':3.5,fill:'none','stroke-linecap':'round','stroke-linejoin':'round'}));}
  coords.forEach(([x,y],i)=>{svg.append(svgNode('circle',{cx:x,cy:y,r:6.5,fill:'#d9fd62',stroke:'#232a21','stroke-width':2.5}));svg.append(svgNode('text',{x,y:y-15,'font-size':12,'font-weight':800,'text-anchor':'middle',fill:'#273228'},values[i]));svg.append(svgNode('text',{x,y:174,'font-size':10,'text-anchor':'middle',fill:'#7d8379'},'Q'+(i+1)));});
}
function historyHtml(turn,i){
  const a=turn.assessment;
  const fix=(a.communication_fixes||[]).map(item=>`<li><b>Heard:</b> “${e(item.heard)}” → <b>Try:</b> ${e(item.try_instead)} <small>(${e(item.why)})</small></li>`).join('');
  const gaps=(a.gaps||[]).map(s=>`<li>${e(s)}</li>`).join('');
  const grammar=(a.grammar_notes||[]).map(s=>`<li>${e(s)}</li>`).join('');
  const speech=a.speech||{};
  const stats=speech.input_mode==='voice'?`${speech.pace_wpm??'—'} WPM · ${speech.filler_count??0} filler expressions · ${speech.pause_count??'—'} approximate pause cues`:'Typed answer; delivery not measured';
  return `<article class="history-item"><div class="history-top"><h4><span class="eyebrow">QUESTION ${String(i+1).padStart(2,'0')} · ${e(a.target_skill||'Practice')}</span><br>${e(turn.question)}</h4><span class="history-score">${e(a.score)}/100</span></div>
    <p><b>Your words:</b> “${e(turn.answer)}”</p><p class="quote-text"><b>What to strengthen:</b> ${e(a.gaps?.[0]||'Give a more specific example.')}</p>
    <details><summary>Open detailed communication & technical breakdown ↓</summary><div class="history-detail"><p><b>Observed speaking signals:</b> ${e(stats)}</p><b>Where to improve</b><ul>${gaps}</ul><b>Wording / grammar observations</b><ul>${grammar||'<li>No transcript-specific grammar issue reported.</li>'}</ul><b>Suggested phrasing changes</b><ul>${fix||'<li>Include precise evidence and state the reasoning directly.</li>'}</ul><b>Example stronger answer</b><p>${e(a.ideal_answer)}</p><b>Concise version</b><p>${e(a.short_answer||'')}</p><p class="micro-note">${e(a.disclaimer||'Practice-only feedback.')}</p></div></details>
    <div class="history-actions"><button type="button" class="small-action" data-read-answer="${i}">♪ Hear example answer</button><button type="button" class="small-action" data-retry-index="${i}">↺ Practice again</button>${turn.retry?`<span class="tiny-tag">RETRY ${turn.retry.delta>=0?'+':''}${turn.retry.delta} POINTS</span>`:''}</div>
  </article>`;
}
function insightMetrics(report){
  const d=dimsFromReport(report), clarity=d.clarity, structure=d.structure;
  $('avgScore').textContent=report.average_score==null?'—':report.average_score+'/100';
  $('techScore').textContent=d.technical==null?'—':d.technical+'/100';
  $('commScore').textContent=clarity==null||structure==null?'—':Math.round((clarity+structure)/2)+'/100';
  $('gapScore').textContent=report.confidence_gap_average==null?'—':report.confidence_gap_average+' pts';
  $('techFootnote').textContent=report.practice_mode==='Gemini AI'?'AI practice rubric':'Demo depth proxy (not correctness)';
  $('radarMode').textContent=report.practice_mode==='Gemini AI'?'AI REVIEW':'DEMO RULES';
  $('answeredBadge').textContent=`${report.questions_answered} ANSWERS`;
  radarGraph(d);trendGraph(report.score_trend);
  $('dimensionRows').innerHTML=DIMENSIONS.map(dim=>{
    const v=d[dim.key];
    return `<div><div class="score-row-name"><span>${e(dim.name)}</span><span>${v==null?'—':v+'/100'}</span></div><div class="score-track"><i style="width:${v??0}%;background:${dim.color}"></i></div></div>`;
  }).join('');
}
async function renderInsights(){
  if(!session){$('historyList').innerHTML='<p class="empty-hint">Start an interview to generate your practice report.</p>';radarGraph({});trendGraph([]);return;}
  try{lastReport=await api(`/api/sessions/${encodeURIComponent(session.id)}/report`);insightMetrics(lastReport);}catch(err){alertUser('Could not load report: '+err.message);}
  const turns=session.turns;
  $('historyList').innerHTML=turns.length?turns.map(historyHtml).join(''):'<p class="empty-hint">Speak an answer to get coaching linked to your own words.</p>';
  $('retrySelect').innerHTML=turns.map((turn,i)=>`<option value="${i}">Q${i+1} · ${e(turn.assessment.target_skill)} · ${turn.assessment.score}/100</option>`).join('')||'<option value="">No responses yet</option>';
  if(turns.length){
    const weak=turns.reduce((a,b)=>a.assessment.score<=b.assessment.score?a:b);
    $('missionTitle').textContent=`Rebuild: ${weak.assessment.target_skill}`;
    $('missionCopy').textContent=(weak.assessment.gaps?.[0]||'Add concrete evidence.')+' Use the Time Machine and compare against your first attempt.';
  }else{$('missionTitle').textContent='Answer one question first.';$('missionCopy').textContent='Your next practice mission appears after your first response.';}
  document.querySelectorAll('[data-read-answer]').forEach(btn=>btn.addEventListener('click',()=>{
    const t=session.turns[Number(btn.dataset.readAnswer)];tts(t?.assessment.ideal_answer||'');
  }));
  document.querySelectorAll('[data-retry-index]').forEach(btn=>btn.addEventListener('click',()=>{
    $('retrySelect').value=btn.dataset.retryIndex;
    $('retryText').focus(); $('retryText').scrollIntoView({behavior:'smooth',block:'center'});
  }));
}
async function retry(){
  if(!session||busy)return;
  if(capture.listening)stopCapture(true);
  const index=Number($('retrySelect').value);
  const text=$('retryText').value.trim();
  if(!text){alertUser('Speak or type a revised answer before comparing attempts.');return;}
  try{
    setBusy(true);
    session=await api(`/api/sessions/${encodeURIComponent(session.id)}/retry`,{method:'POST',body:JSON.stringify({
      turn_index:index,answer:text,confidence:Number($('confidence').value),speech_metrics:buildSpeechMetrics('retry')
    })});
    const t=session.turns[index];
    $('retryResult').classList.remove('hidden');
    $('retryResult').innerHTML=`<b>${t.retry.delta>=0?'+':''}${t.retry.delta} pts</b><br>Original: ${t.assessment.score}/100 · Retry: ${t.retry.assessment.score}/100<br><small>${e(t.retry.assessment.gaps?.[0]||'Answer evaluated.')}</small><br><small>Practice scores are estimates, not proof of real-world improvement.</small>`;
    $('retryText').value='';capture.voiceUsed=false;capture.heardSpeech=false;capture.durationSeconds=null;
    await renderInsights();
  }catch(err){alertUser('Could not compare answers: '+err.message);}finally{setBusy(false);}
}
async function deleteSession(){
  if(!session||!confirm('Delete this interview session and its transcripts from the local SQLite database?'))return;
  try{await api(`/api/sessions/${encodeURIComponent(session.id)}`,{method:'DELETE'});
    localStorage.removeItem('interviewx-session-id:'+accountId);session=null;lastReport=null;resetCapture();view('setup');alertUser('Interview session deleted.');
  }catch(err){alertUser('Deletion failed: '+err.message);}
}
function loadVoices(){
  if(!('speechSynthesis' in window))return;
  const voices=window.speechSynthesis.getVoices().filter(v=>v.lang.toLowerCase().startsWith('en'));
  const existing=$('voiceSelect').value;
  $('voiceSelect').innerHTML='<option value="">System default</option>'+voices.map(v=>`<option value="${e(v.voiceURI)}">${e(v.name)} (${e(v.lang)})</option>`).join('');
  if(voices.some(v=>v.voiceURI===existing))$('voiceSelect').value=existing;
}
async function boot(){
  document.querySelectorAll('.rail-link[data-view]').forEach(b=>b.addEventListener('click',()=>view(b.dataset.view)));
  document.querySelectorAll('.mode-option').forEach(b=>b.addEventListener('click',()=>{
    selectedMode=b.dataset.mode;
    document.querySelectorAll('.mode-option').forEach(node=>node.classList.toggle('selected',node===b));
  }));
  $('loadDemo').addEventListener('click',async()=>{try{const d=await api('/api/demo');$('role').value=d.role;$('company').value=d.company;$('resume').value=d.resume;$('jd').value=d.job_description;}catch(err){alertUser(err.message);}});
  $('startBtn').addEventListener('click',startSession);
  $('repeatQuestion').addEventListener('click',speakQuestion);
  $('micButton').addEventListener('click',()=>capture.listening?stopCapture(false):startListening('answer'));
  $('endSpeaking').addEventListener('click',()=>stopCapture(false));
  $('submitAnswer').addEventListener('click',submitAnswer);
  $('nextQuestion').addEventListener('click',nextQuestion);
  $('goInsights').addEventListener('click',()=>view('insights'));
  $('backInterview').addEventListener('click',()=>view('interview'));
  $('readFeedback').addEventListener('click',()=>tts($('quickGap').textContent+' '+$('quickIdeal').textContent));
  $('retryMic').addEventListener('click',()=>capture.listening&&capture.target==='retry'?stopCapture(false):startListening('retry'));
  $('retryBtn').addEventListener('click',retry);
  $('deleteSession').addEventListener('click',deleteSession);
  $('signOut').addEventListener('click', async()=>{
    try{await api('/api/auth/logout', {method:'POST',body:'{}'});}
    finally{session=null;window.location.assign('/login');}
  });
  $('confidence').addEventListener('input',()=>{$('confidenceValue').textContent=$('confidence').value+'%';});
  $('answerText').addEventListener('input',updatePreview);
  if(!SpeechRecognitionCtor){$('voiceSupport').textContent='Speech recognition is not supported here. Use a current Chrome/Edge browser, or type as a fallback.';$('micButton').disabled=true;$('retryMic').disabled=true;}
  else $('voiceSupport').textContent='Microphone speech recognition available. Recognition may require a network service and permission. Best tested on localhost or HTTPS in Chrome/Edge.';
  if('speechSynthesis' in window){loadVoices();window.speechSynthesis.onvoiceschanged=loadVoices;}
  else{$('voiceSupport').textContent+=' Spoken question output is unavailable in this browser.';$('voiceEnabled').checked=false;}
  radarGraph({});trendGraph([]);
  try{
    const identity=await api('/api/auth/me');
    csrfToken=identity.csrf_token;
    accountId=identity.user.id;
    $('accountName').textContent=identity.user.name;
    $('accountEmail').textContent=identity.user.email;
    $('topAvatar').textContent=identity.user.name.slice(0,1).toUpperCase();
    const health=await api('/api/health');
    $('apiDot').classList.add('good');
    $('aiLabel').textContent=health.ai_enabled?'GEMINI AI CONNECTED':'DEMO ENGINE ACTIVE';
    $('aiSub').textContent=health.ai_enabled?'AI interview coaching enabled':'Connect an AI key for deep grading';
    $('loadDemo').click();
    const sid=localStorage.getItem('interviewx-session-id:'+accountId);
    if(sid){
      try{session=await api('/api/sessions/'+encodeURIComponent(sid));renderInterview();}
      catch{localStorage.removeItem('interviewx-session-id:'+accountId);}
    }
  }catch(err){$('aiLabel').textContent='SERVER OFFLINE';$('aiSub').textContent='Run the FastAPI startup script';alertUser('Backend unavailable: '+err.message);}
}
boot();
