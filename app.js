/* Vibe Calling UI — robust event delegation edition */
(() => {
"use strict";
const $=s=>document.querySelector(s), $$=s=>[...document.querySelectorAll(s)];
const KEYS={providers:"vc_providers_v1",chats:"vc_chats_v1",notes:"vc_notes_v1",mcp:"vc_github_mcp_v1"};
const presets={custom:{name:"Custom provider",url:"",model:""},nvidia:{name:"NVIDIA NIM",url:"https://integrate.api.nvidia.com/v1",model:""},gemini:{name:"Google Gemini",url:"https://generativelanguage.googleapis.com/v1beta/openai",model:""},openai:{name:"OpenAI",url:"https://api.openai.com/v1",model:"gpt-4o-mini"},openrouter:{name:"OpenRouter",url:"https://openrouter.ai/api/v1",model:""},groq:{name:"Groq",url:"https://api.groq.com/openai/v1",model:""}};
const read=(k,d)=>{try{return JSON.parse(localStorage.getItem(k))??d}catch{return d}},write=(k,v)=>localStorage.setItem(k,JSON.stringify(v));
let providers=read(KEYS.providers,[]),chats=read(KEYS.chats,[]),notes=read(KEYS.notes,[]);
if(!Array.isArray(providers))providers=[];if(!Array.isArray(chats))chats=[];if(!Array.isArray(notes))notes=[];
let chatId=chats[0]?.id||null,editingId=null,busy=false,controller=null,pendingModels=[];
let mcpConfig=read(KEYS.mcp,{token:"",readOnly:true,sessionId:"",connected:false});
if(!mcpConfig||typeof mcpConfig!=="object")mcpConfig={token:"",readOnly:true,sessionId:"",connected:false};
let githubMcpTools=[],githubMcpToolMap={},skillCatalog=[],pendingAttachments=[];
const uid=()=>globalThis.crypto?.randomUUID?.()||("vc-"+Date.now()+"-"+Math.random().toString(36).slice(2));
const esc=s=>String(s??"").replace(/[&<>"']/g,c=>({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;"}[c]));
function toast(s){const el=$("#toast");if(!el){console.log(s);return}el.textContent=s;el.classList.add("show");clearTimeout(toast.timer);toast.timer=setTimeout(()=>el.classList.remove("show"),3000)}
function fatal(s){let el=$("#fatalError");if(!el){el=document.createElement("div");el.id="fatalError";el.style.cssText="position:fixed;z-index:99999;left:12px;right:12px;bottom:12px;padding:14px;background:#3b1720;color:white;border:1px solid #ff7180;border-radius:8px;font:13px/1.5 system-ui;white-space:pre-wrap";document.body.appendChild(el)}el.textContent="Vibe Calling error:\n"+s}
window.addEventListener("error",e=>fatal(e.message||"Unknown JavaScript error"));
window.addEventListener("unhandledrejection",e=>fatal(e.reason?.message||String(e.reason||"Unhandled promise rejection")));
const cleanUrl=s=>String(s||"").trim().replace(/\/+$/,"").replace(/\/chat\/completions$/i,"").replace(/\/models$/i,"");
const byId=id=>providers.find(p=>p.id===id),current=()=>chats.find(c=>c.id===chatId);
function setView(name){$$(".view").forEach(x=>x.classList.remove("active"));$("#"+name+"View")?.classList.add("active");$$(".nav-item").forEach(x=>x.classList.toggle("active",x.dataset.view===name));$("#crumb").textContent=({chat:"Chat",providers:"Providers",tools:"Agent tools",settings:"Settings"})[name]||name;$("#sidebar").classList.remove("open")}
function saveChats(){write(KEYS.chats,chats);renderHistory()}
function saveProviders(){write(KEYS.providers,providers);renderProviders();renderModels()}
function newChat(){const c={id:uid(),title:"New conversation",messages:[],createdAt:Date.now()};chats.unshift(c);chatId=c.id;saveChats();renderChat();setView("chat")}
function renderHistory(){const el=$("#historyList");el.innerHTML=chats.slice(0,50).map(c=>'<button type="button" class="history-item '+(c.id===chatId?"active":"")+'" data-chat="'+esc(c.id)+'">'+esc(c.title||"Conversation")+'</button>').join("")}
function renderModels(preferred){
 const el=$("#modelSelect"),old=preferred||el.value,opts=[];
 providers.forEach(p=>(Array.isArray(p.models)?p.models:[]).filter(Boolean).forEach(m=>opts.push({value:p.id+"::"+m,label:(p.name||"Provider")+" · "+m+" · FREE"})));
 el.innerHTML=opts.length?opts.map(o=>'<option value="'+esc(o.value)+'">'+esc(o.label)+'</option>').join(""):'<option value="">No verified free models found</option>';
 if(opts.some(o=>o.value===old))el.value=old;
 $("#tokenHint").textContent=opts.length?opts.length+" verified free model(s)":"Free models only · unverified models are hidden";
 $("#providerCount").textContent=String(providers.length);
}
function renderProviders(){const grid=$("#providerGrid");if(!grid)return;if(!providers.length){grid.innerHTML='<div class="empty-state">No providers connected yet.<br><br>Add NVIDIA, Gemini, OpenAI, Groq, OpenRouter, or a compatible endpoint.</div>';return}grid.innerHTML=providers.map(p=>{let host="Custom endpoint";try{host=new URL(p.baseUrl).hostname}catch{}return '<article class="provider-card"><div class="provider-card-head"><div class="provider-logo">'+esc((p.name||"P").slice(0,1).toUpperCase())+'</div><div><h3>'+esc(p.name||"Provider")+'</h3><small>'+esc(host)+'</small></div></div><div class="provider-model">'+esc(p.models?.length?p.models.length+" models available":p.defaultModel||"No model selected")+'</div><div class="provider-card-actions"><button type="button" data-edit="'+esc(p.id)+'">Edit</button><button type="button" data-refresh="'+esc(p.id)+'">Refresh models</button><button type="button" class="delete-provider" data-delete="'+esc(p.id)+'">Delete</button></div></article>'}).join("")}
function markdown(s){
 let x=esc(s),fence=String.fromCharCode(96).repeat(3);
 x=x.replace(new RegExp(fence+"([\\w-]*)\\n([\\s\\S]*?)"+fence,"g"),(_,l,c)=>"<pre><code>"+c+"</code></pre>");
 x=x.replace(/^### (.*)$/gm,"<h3>$1</h3>").replace(/^## (.*)$/gm,"<h2>$1</h2>").replace(/^# (.*)$/gm,"<h1>$1</h1>").replace(/\\*\\*(.*?)\\*\\*/g,"<b>$1</b>");
 x=x.replace(/\\[([^\\]]+)\\]\\((\\/api\\/download\\/[^)\\s]+)\\)/g,'<a class="file-download" href="$2" download>$1</a>');
 return x.split(/\\n{2,}/).map(p=>p.startsWith("<pre>")||p.startsWith("<h")?p:"<p>"+p.replace(/\\n/g,"<br>")+"</p>").join("");
}
function renderChat(){
 const box=$("#messages"),welcome=$("#welcome"),c=current();
 if(!c){box.innerHTML="";welcome.style.display="block";return}
 const arr=Array.isArray(c.messages)?c.messages:[];
 welcome.style.display=arr.length?"none":"block";
 box.innerHTML=arr.map((m,i)=>{
  const user=m.role==="user",files=Array.isArray(m.attachments)?m.attachments:[];
  return '<article class="message '+(user?"user":"assistant")+'"><div class="message-avatar">'+(user?"Y":"✳")+'</div><div class="message-body"><div class="message-content">'+markdown(m.content||"")+'</div>'+
  (files.length?'<div class="message-attachments">'+files.map(a=>'<span class="message-attachment">↳ '+esc(a.name)+'</span>').join("")+'</div>':"")+
  (m.toolLog?'<div class="tool-log">'+esc(m.toolLog)+'</div>':"")+
  '<div class="message-meta">'+(user?"YOU":"VIBE CALLING")+(m.model?" · "+esc(m.model):"")+'</div>'+
  (user?"":'<div class="message-actions"><button type="button" data-copy="'+esc(m.content||"")+'">Copy</button><button type="button" data-retry="'+i+'">Regenerate</button></div>')+
  '</div></article>';
 }).join("");
 $("#chatContent").scrollTo(0,$("#chatContent").scrollHeight);
}
function openProvider(providerId){pendingModels=[];editingId=providerId||null;const p=providerId?byId(providerId):null;$("#providerDialogTitle").textContent=p?"Edit provider":"Add a provider";$("#providerPreset").value="custom";$("#providerName").value=p?.name||"";$("#providerUrl").value=p?.baseUrl||"";$("#providerKey").value=p?.apiKey||"";$("#providerModel").value=p?.defaultModel||"";$("#providerHeader").value=p?.customHeader||"";$("#providerHeaderValue").value=p?.customHeaderValue||"";$("#providerFeedback").textContent="";$("#providerFeedback").className="feedback";$("#providerDialog").showModal()}
function providerFromForm(){return{id:editingId||uid(),name:$("#providerName").value.trim()||"My provider",baseUrl:cleanUrl($("#providerUrl").value),apiKey:$("#providerKey").value.trim(),defaultModel:$("#providerModel").value.trim(),models:pendingModels.length?pendingModels:(editingId?(byId(editingId)?.models||[]):[]),customHeader:$("#providerHeader").value.trim(),customHeaderValue:$("#providerHeaderValue").value}}
function requestBody(p,path,method,body){return{baseUrl:cleanUrl(p.baseUrl),path,method,apiKey:p.apiKey,customHeader:p.customHeader||"",customHeaderValue:p.customHeaderValue||"",body:body??null}}
async function api(p,path,method="GET",body=null,signal){let r;try{r=await fetch("/api/proxy",{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify(requestBody(p,path,method,body)),signal})}catch(e){if(e.name==="AbortError")throw e;throw new Error("Could not reach local server. Run start.bat and open http://127.0.0.1:8765")}const raw=await r.text();if(!r.ok)throw new Error("HTTP "+r.status+": "+raw.slice(0,450));try{return raw?JSON.parse(raw):{}}catch{throw new Error("Provider response is not valid JSON")}}
const GEMINI_FREE_MODELS=new Set(["gemini-3.8-flash","gemini-3.6-flash","gemini-3.5-flash-lite","gemini-3.1-flash-lite","gemini-3-flash-preview","gemini-2.5-flash","gemini-2.5-flash-lite"]);
function providerHost(p){try{return new URL(p.baseUrl).hostname.toLowerCase()}catch{return""}}
function hasZeroPricing(row){const pricing=row?.pricing;if(!pricing||typeof pricing!=="object")return false;const vals=["prompt","completion","input","output"].map(k=>pricing[k]).filter(v=>v!==undefined);return vals.length>=2&&vals.every(v=>Number(v)===0)}
function isVerifiedFreeModel(p,row){const id=String(row?.id||row?.name||"").replace(/^models\\//,""),host=providerHost(p);if(host==="generativelanguage.googleapis.com"||host.endsWith(".googleapis.com"))return GEMINI_FREE_MODELS.has(id);if(host==="openrouter.ai"||host.endsWith(".openrouter.ai"))return id.endsWith(":free")||hasZeroPricing(row);return hasZeroPricing(row)}
async function discover(p){const d=await api(p,"/models"),rows=d.data||d.models||[];return rows.filter(x=>isVerifiedFreeModel(p,x)).map(x=>String(x.id||x.name||"").replace(/^models\\//,"")).filter(Boolean)}
async function refresh(id){const p=byId(id);if(!p)return;toast("Checking free models…");try{p.models=await discover(p);if(p.defaultModel&&!p.models.includes(p.defaultModel))p.defaultModel="";saveProviders();toast("Found "+p.models.length+" verified free model(s)")}catch(e){toast("Model list failed: "+e.message)}}
async function testProvider(){
  const p=providerFromForm(),fb=$("#providerFeedback"),button=$("#testProvider");
  fb.className="feedback";fb.textContent="";
  if(!p.baseUrl||!p.apiKey){fb.className="feedback error";fb.textContent="Enter both Base URL and API Key before testing.";return;}
  try{if(new URL(p.baseUrl).protocol!=="https:")throw new Error("Base URL must start with https://");}
  catch(e){fb.className="feedback error";fb.textContent=e.message==="Base URL must start with https://" ? e.message : "Enter a valid HTTPS Base URL.";return;}
  const label=button.textContent;button.disabled=true;button.textContent="Testing…";button.classList.add("is-loading");
  fb.textContent="Contacting provider through your local proxy…";
  try{
    const list=await discover(p);pendingModels=list;p.models=list;
    fb.className="feedback success";
    fb.textContent="Connected successfully. "+list.length+" model(s) found.";
    if(list.length&&!p.defaultModel)$("#providerModel").value=list[0];
  }catch(e){fb.className="feedback error";fb.textContent="Connection failed: "+e.message+" You can still save the provider and enter a model ID manually.";}
  finally{button.disabled=false;button.textContent=label;button.classList.remove("is-loading");}
}
function addMessage(role,content,extra={}){const c=current();if(!c)return;c.messages.push({role,content,...extra});if(role==="user"&&c.title==="New conversation")c.title=content.slice(0,42)+(content.length>42?"…":"");saveChats();renderChat()}
function selected(){const v=$("#modelSelect").value,i=v.indexOf("::");return i<0?{}:{provider:byId(v.slice(0,i)),model:v.slice(i+2)}}
function calculate(expr){if(!/^[\d\s.+\-*/()%]+$/.test(expr)||!expr.trim())throw Error("Invalid expression");const ts=expr.match(/\d+(?:\.\d+)?|[()+\-*/%]/g)||[];if(ts.join("")!==expr.replace(/\s/g,""))throw Error("Invalid expression");const out=[],ops=[],pr={"+":1,"-":1,"*":2,"/":2,"%":2};let prev="start";for(const t of ts){if(/^\d/.test(t)){if(prev==="number"||prev===")")throw Error("Invalid expression");out.push(Number(t));prev="number"}else if(t==="("){if(prev==="number"||prev===")")throw Error("Invalid expression");ops.push(t);prev="("}else if(t===")"){while(ops.length&&ops.at(-1)!=="(")out.push(ops.pop());if(ops.pop()!=="(")throw Error("Mismatched parentheses");prev=")"}else{if(prev!=="number"&&prev!==")"){if((t==="-"||t==="+")&&["start","(","operator"].includes(prev))out.push(0);else throw Error("Invalid expression")}while(ops.length&&pr[ops.at(-1)]>=pr[t])out.push(ops.pop());ops.push(t);prev="operator"}}while(ops.length){const op=ops.pop();if(op==="(")throw Error("Mismatched parentheses");out.push(op)}const st=[];for(const t of out){if(typeof t==="number")st.push(t);else{const b=st.pop(),a=st.pop();st.push(t==="+"?a+b:t==="-"?a-b:t==="*"?a*b:t==="/"?a/b:a%b)}}if(st.length!==1||!Number.isFinite(st[0]))throw Error("Invalid result");return String(st[0])}
const activeProjectKey="vc_active_project_v1";
let activeProject=localStorage.getItem(activeProjectKey)||"";
const toolDef=(name,description,properties,required=[])=>({type:"function",function:{name,description,parameters:{type:"object",properties,required}}});
const tools=[
 toolDef("calculator","Calculate a basic arithmetic expression locally.",{expression:{type:"string"}},["expression"]),
 toolDef("get_current_datetime","Get the user's local date and time.",{}),
 toolDef("save_note","Save a note in this browser.",{title:{type:"string"},content:{type:"string"}},["title","content"]),
 toolDef("list_notes","List saved browser notes.",{}),
 toolDef("workspace_list_projects","List all project folders available to this Vibe Calling workspace.",{}),
 toolDef("workspace_create_project","Create a new isolated project folder. Use this before creating project files.",{name:{type:"string"}},["name"]),
 toolDef("workspace_list_files","List text files in one project. Large dependency/build folders and secrets are excluded.",{project:{type:"string"}},["project"]),
 toolDef("workspace_read_file","Read a UTF-8 text file inside one project.",{project:{type:"string"},path:{type:"string"}},["project","path"]),
 toolDef("workspace_write_file","Create or replace a UTF-8 text file inside one project. Parent folders are created automatically. Never write credentials or .env files.",{project:{type:"string"},path:{type:"string"},content:{type:"string"}},["project","path","content"]),
 toolDef("workspace_delete_file","Delete one file inside the project. The user must approve the deletion in a confirmation dialog.",{project:{type:"string"},path:{type:"string"}},["project","path"]),
 toolDef("workspace_run_command","Run one allowlisted build or test command in the project folder. Every command needs user approval. Supported commands: npm install, npm ci, npm run build/test/lint, npx playwright test, python -m compileall/pytest/unittest, git status/diff/log.",{project:{type:"string"},command:{type:"string"}},["project","command"]),
 toolDef("workspace_preview","Get the local preview URL for a project's index.html file.",{project:{type:"string"}},["project"])
];
async function workspaceRequest(payload){
 const response=await fetch("/api/workspace",{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify(payload)});
 const raw=await response.text();
 let data={};try{data=raw?JSON.parse(raw):{}}catch{}
 if(!response.ok)throw new Error(data.error||("Workspace request failed (HTTP "+response.status+")."));
 return data;
}
function setActiveProject(project){
 activeProject=project||"";
 if(activeProject)localStorage.setItem(activeProjectKey,activeProject);else localStorage.removeItem(activeProjectKey);
}
async function refreshWorkspacePanel(){
 const select=$("#projectSelect"),filesEl=$("#workspaceFiles"),status=$("#workspaceStatus");
 if(!select||!filesEl||!status)return;
 try{
  const data=await workspaceRequest({action:"list_projects"});
  const projects=data.projects||[];
  if(activeProject&&!projects.includes(activeProject))setActiveProject("");
  select.innerHTML='<option value="">Select a project</option>'+projects.map(p=>'<option value="'+esc(p)+'">'+esc(p)+'</option>').join("");
  select.value=activeProject;
  if(!activeProject){
   filesEl.textContent="No project selected. Create one here or ask Agent mode to create it.";
   status.textContent=projects.length+" project(s) available.";
   return;
  }
  const listing=await workspaceRequest({action:"list_files",project:activeProject});
  const items=listing.files||[];
  filesEl.textContent=items.length?items.map(x=>x.path+" · "+x.bytes+" bytes").join("\n"):"Project is empty. Ask the agent to create the first files.";
  status.textContent=activeProject+" · "+items.length+" file(s)";
 }catch(error){
  status.textContent="Workspace unavailable: "+error.message;
  filesEl.textContent="Start Vibe Calling with start.bat and refresh.";
 }
}
async function runTool(name,a){
 if(name==="calculator")return calculate(a.expression||"");
 if(name==="get_current_datetime")return new Date().toLocaleString();
 if(name==="save_note"){notes.unshift({id:uid(),title:String(a.title||"Note"),content:String(a.content||"")});write(KEYS.notes,notes);return"Note saved locally"}
 if(name==="list_notes")return notes.map(n=>"- "+n.title+": "+n.content).join("\n")||"No notes";
 if(name==="workspace_list_projects"){
  const data=await workspaceRequest({action:"list_projects"});
  return data.projects.length?("Projects: "+data.projects.join(", ")):"No projects exist yet. Use workspace_create_project first.";
 }
 if(name==="workspace_create_project"){
  const data=await workspaceRequest({action:"create_project",name:a.name});
  setActiveProject(data.project);await refreshWorkspacePanel();
  return "Created project "+data.project+" at "+data.path+". It is now the active project.";
 }
 if(name==="workspace_list_files"){
  const data=await workspaceRequest({action:"list_files",project:a.project});
  return data.files.length?data.files.map(x=>x.path+" ("+x.bytes+" bytes)").join("\n"):"Project is empty.";
 }
 if(name==="workspace_read_file"){
  const data=await workspaceRequest({action:"read_file",project:a.project,path:a.path});
  return "FILE: "+data.path+"\n"+data.content;
 }
 if(name==="workspace_write_file"){
  const data=await workspaceRequest({action:"write_file",project:a.project,path:a.path,content:a.content});
  if(a.project===activeProject)await refreshWorkspacePanel();
  return "Saved "+data.path+" ("+data.bytes+" bytes).";
 }
 if(name==="workspace_delete_file"){
  if(!confirm("The agent wants to permanently delete this file:\n\n"+a.project+"/"+a.path+"\n\nAllow this deletion?"))return "User declined the file deletion.";
  const data=await workspaceRequest({action:"delete_file",project:a.project,path:a.path,confirmed:true});
  if(a.project===activeProject)await refreshWorkspacePanel();
  return "Deleted "+data.deleted+".";
 }
 if(name==="workspace_run_command"){
  const warning="The agent wants to run this command in project '"+a.project+"':\n\n"+a.command+"\n\nCommands and project scripts run on your computer. Only approve if you trust this project and command.\n\nRun it?";
  if(!confirm(warning))return "User declined command execution. Do not retry unless the user asks.";
  const data=await workspaceRequest({action:"run_command",project:a.project,command:a.command});
  return "Exit code: "+data.exit_code+(data.timed_out?" (timed out)":"")+"\n\n"+(data.output||"(No command output)");
 }
 if(name==="workspace_preview"){
  const data=await workspaceRequest({action:"preview",project:a.project});
  return "Preview is ready: "+data.url+"\nOpen that URL in your browser. The project must contain index.html.";
 }
 throw Error("Unknown tool: "+name);
}
async function send(text){if(busy)return;const q=selected();if(!q.provider||!q.model){toast("Connect a provider and set a model ID first.");if(!providers.length)openProvider();else setView("providers");return}if(!chatId)newChat();addMessage("user",text);busy=true;$("#sendBtn").disabled=true;$("#messageInput").disabled=true;controller=new AbortController();const spinner=document.createElement("div");spinner.className="typing";spinner.innerHTML="<i></i><i></i><i></i>";$("#messages").appendChild(spinner);$("#welcome").style.display="none";try{const history=current().messages.map(m=>({role:m.role,content:m.content}));let answer="",used=[];for(let n=0;n<12;n++){const body={model:q.model,messages:history,temperature:.7,stream:false};if($("#agentToggle").checked){body.tools=tools;body.tool_choice="auto"}const res=await api(q.provider,"/chat/completions","POST",body,controller.signal),msg=res.choices?.[0]?.message;if(!msg)throw Error(res.error?.message||"Empty response from provider");if(msg.tool_calls?.length&&$("#agentToggle").checked){history.push(msg);for(const c of msg.tool_calls){let args={};try{args=JSON.parse(c.function.arguments||"{}")}catch{}let value;try{value=await runTool(c.function.name,args);used.push(c.function.name+" ✓")}catch(e){value="Tool error: "+e.message;used.push(c.function.name+" failed")}history.push({role:"tool",tool_call_id:c.id,name:c.function.name,content:String(value)})}continue}answer=msg.content||"";break}spinner.remove();addMessage("assistant",answer||"The model returned no final text.",{model:q.model,toolLog:used.length?"Tools used: "+used.join(" · "):""})}catch(e){spinner.remove();addMessage("assistant",e.name==="AbortError"?"Request stopped.":"**Request failed**\n\n"+e.message+"\n\nCheck Base URL, API key, model ID and provider compatibility.",{model:q.model})}finally{busy=false;controller=null;$("#sendBtn").disabled=false;$("#messageInput").disabled=false;$("#messageInput").focus()}}
function retry(index){const c=current();if(!c||busy)return;const u=c.messages.slice(0,index).reverse().find(m=>m.role==="user");if(!u)return;c.messages=c.messages.slice(0,index);if(c.messages.at(-1)?.role==="user")c.messages.pop();saveChats();renderChat();send(u.content)}
document.addEventListener("click",e=>{
  const button=e.target.closest("button");
  if(!button||button.disabled)return;
  button.classList.remove("tap-feedback");
  void button.offsetWidth;
  button.classList.add("tap-feedback");
  window.setTimeout(()=>button.classList.remove("tap-feedback"),320);
},{capture:true});
document.addEventListener("click",e=>{const b=e.target.closest("button");if(!b)return;
if(b.id==="newChatBtn"){newChat();return}
if(b.id==="welcomeAddProvider"||b.id==="addProviderBtn"){openProvider();return}
if(b.id==="openSettings"||b.id==="settingsShortcut"){setView("settings");return}
if(b.id==="mobileMenu"){$("#sidebar").classList.toggle("open");return}
if(b.id==="agentQuick"){$("#agentToggle").checked=!$("#agentToggle").checked;$("#toolState").textContent=$("#agentToggle").checked?"on":"off";toast("Agent mode "+($("#agentToggle").checked?"enabled":"disabled"));return}
if(b.id==="toggleKey"){$("#providerKey").type=$("#providerKey").type==="password"?"text":"password";return}
if(b.id==="testProvider"){testProvider();return}
if(b.id==="createProjectBtn"){(async()=>{const input=$("#projectNameInput"),name=input.value.trim();if(!name){toast("Enter a project name first.");return}try{const data=await workspaceRequest({action:"create_project",name});setActiveProject(data.project);input.value="";await refreshWorkspacePanel();toast("Project created: "+data.project)}catch(error){toast(error.message)}})();return}
if(b.id==="refreshWorkspaceBtn"){refreshWorkspacePanel();return}
if(b.id==="previewProjectBtn"){(async()=>{const tab=window.open("about:blank","_blank");try{if(!activeProject)throw Error("Select a project first.");const data=await workspaceRequest({action:"preview",project:activeProject});if(tab)tab.location=data.url;else toast(data.url)}catch(error){if(tab)tab.close();toast(error.message)}})();return}
if(b.id==="clearHistory"){if(confirm("Clear all conversations?")){chats=[];chatId=null;saveChats();renderChat()}return}
if(b.id==="clearAll"){$("#confirmDialog").showModal();return}
if(b.id==="confirmClear"){Object.values(KEYS).forEach(k=>localStorage.removeItem(k));providers=[];chats=[];notes=[];chatId=null;$("#confirmDialog").close();saveProviders();saveChats();renderChat();setView("chat");toast("Local data cleared");return}
if(b.id==="chatOptions"){toast("More options coming soon.");return}
if(b.dataset.view){setView(b.dataset.view);return}
if(b.dataset.close){$("#"+b.dataset.close)?.close();return}
if(b.dataset.chat){chatId=b.dataset.chat;renderChat();renderHistory();setView("chat");return}
if(b.dataset.edit){openProvider(b.dataset.edit);return}
if(b.dataset.delete){if(confirm("Delete this provider and saved key?")){providers=providers.filter(p=>p.id!==b.dataset.delete);saveProviders();toast("Provider deleted")}return}
if(b.dataset.refresh){refresh(b.dataset.refresh);return}
if(b.dataset.copy!==undefined){navigator.clipboard?.writeText(b.dataset.copy).then(()=>toast("Copied")).catch(()=>toast("Clipboard unavailable"));return}
if(b.dataset.retry!==undefined){retry(Number(b.dataset.retry));return}
if(b.dataset.prompt){$("#messageInput").value=b.dataset.prompt;$("#messageInput").focus();return}
});
$("#providerPreset").addEventListener("change",()=>{const p=presets[$("#providerPreset").value];if(p){$("#providerName").value=p.name;$("#providerUrl").value=p.url;$("#providerModel").value=p.model}});
$("#providerForm").addEventListener("submit",e=>{
  e.preventDefault();
  const p=providerFromForm(),fb=$("#providerFeedback"),save=$("#saveProvider");
  fb.className="feedback";fb.textContent="";
  if(!p.baseUrl||!p.apiKey){fb.className="feedback error";fb.textContent="Base URL and API Key are both required.";return;}
  try{if(new URL(p.baseUrl).protocol!=="https:")throw new Error("Use an HTTPS URL.");}
  catch(error){fb.className="feedback error";fb.textContent=error.message||"Enter a valid HTTPS Base URL.";return;}
  const previousProviders=providers.slice();
  const previous=providers.findIndex(x=>x.id===p.id);
  if(previous>=0)providers[previous]=p;else providers.unshift(p);
  save.disabled=true;save.textContent="Saving…";
  try{
    saveProviders();
    renderModels(p.defaultModel?p.id+"::"+p.defaultModel:undefined);
    $("#providerDialog").close();
    toast("Provider saved successfully");
  }catch(error){
    providers=previousProviders;
    try{renderProviders();renderModels();}catch{}
    fb.className="feedback error";fb.textContent="Could not save in this browser. Check site storage permissions and available space."
  }finally{save.disabled=false;save.textContent="Save provider";}
});
$("#chatForm").addEventListener("submit",e=>{e.preventDefault();const input=$("#messageInput"),s=input.value.trim();if(!s||busy)return;input.value="";input.style.height="auto";send(s)});
$("#messageInput").addEventListener("keydown",e=>{if(e.key==="Enter"&&!e.shiftKey){e.preventDefault();$("#chatForm").requestSubmit()}});
$("#messageInput").addEventListener("input",e=>{e.target.style.height="auto";e.target.style.height=Math.min(e.target.scrollHeight,180)+"px"});
$("#agentToggle").addEventListener("change",e=>{$("#toolState").textContent=e.target.checked?"on":"off"});
$("#projectSelect").addEventListener("change",e=>{setActiveProject(e.target.value);refreshWorkspacePanel()});
function init(){try{renderProviders();renderModels();renderHistory();renderChat();refreshWorkspacePanel();console.info("Vibe Calling initialized")}catch(e){fatal(e.stack||e.message||String(e))}}
init();
window.__vibeAppReady = true;
document.documentElement.dataset.vibeApp = 'ready';
})();