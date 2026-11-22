'use strict';
const el=id=>document.getElementById(id);
let registering=false;
function switchTab(next){
  registering=next;
  el('nameField').classList.toggle('hidden',!next);
  el('passwordHelp').classList.toggle('hidden',!next);
  el('formTitle').innerHTML=next?'Your next<br><span>chapter.</span>':'Welcome<br><span>back.</span>';
  el('formSubtitle').textContent=next?'Create a private space for your interview practice and progress.':'Sign in to pick up where your last interview left off.';
  el('submitAuth').innerHTML=next?'CREATE YOUR ACCOUNT <span>↗</span>':'ENTER INTERVIEWX <span>↗</span>';
  el('password').setAttribute('autocomplete',next?'new-password':'current-password');
  el('signInTab').classList.toggle('active',!next);
  el('registerTab').classList.toggle('active',next);
  el('signInTab').setAttribute('aria-selected',String(!next));
  el('registerTab').setAttribute('aria-selected',String(next));
  el('authError').classList.add('hidden');
}
el('signInTab').addEventListener('click',()=>switchTab(false));
el('registerTab').addEventListener('click',()=>switchTab(true));
el('togglePassword').addEventListener('click',()=>{
  const p=el('password');const visible=p.type==='text';p.type=visible?'password':'text';
  el('togglePassword').textContent=visible?'SHOW':'HIDE';
  el('togglePassword').setAttribute('aria-label',visible?'Show password':'Hide password');
});
el('authForm').addEventListener('submit',async event=>{
  event.preventDefault();
  const name=el('name').value.trim(),email=el('email').value.trim(),password=el('password').value;
  const error=el('authError');error.classList.add('hidden');
  if(!el('email').checkValidity()){error.textContent='Enter a valid email address.';error.classList.remove('hidden');return;}
  if(registering && (name.length<2||password.length<10)){
    error.textContent='Enter your name and a password of at least 10 characters.';error.classList.remove('hidden');return;
  }
  const btn=el('submitAuth');btn.disabled=true;
  try{
    const res=await fetch(registering?'/api/auth/register':'/api/auth/login',{
      method:'POST',headers:{'Content-Type':'application/json'},credentials:'same-origin',
      body:JSON.stringify(registering?{name,email,password}:{email,password})
    });
    const payload=await res.json();
    if(!res.ok)throw new Error(typeof payload.detail==='string'?payload.detail:'Could not sign in.');
    window.location.assign('/');
  }catch(err){error.textContent=err.message;error.classList.remove('hidden');btn.disabled=false;}
});
