/* Sadaa dashboard — plain JS, no build step. */
const api = {
  async get(p) { const r = await fetch("/api" + p); return r.json(); },
  async post(p, b) {
    const r = await fetch("/api" + p, { method: "POST",
      headers: { "Content-Type": "application/json" }, body: JSON.stringify(b || {}) });
    return r.json();
  },
  async put(p, b) {
    const r = await fetch("/api" + p, { method: "PUT",
      headers: { "Content-Type": "application/json" }, body: JSON.stringify(b || {}) });
    return r.json();
  },
  async patch(p, b) {
    const r = await fetch("/api" + p, { method: "PATCH",
      headers: { "Content-Type": "application/json" }, body: JSON.stringify(b || {}) });
    return r.json();
  },
  async del(p) { const r = await fetch("/api" + p, { method: "DELETE" }); return r.json(); },
};

let agents = [];
let activeCall = null;   // {id, agent, state}
let micOn = false;
let replayStop = false;

const $ = (id) => document.getElementById(id);
const esc = (s) => String(s ?? "").replace(/[&<>"]/g, c => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]));

/* ---------- navigation ---------- */
function show(view) {
  document.querySelectorAll(".view").forEach(v => v.classList.remove("active"));
  $("view-" + view).classList.add("active");
  document.querySelectorAll(".nav button").forEach(b => b.classList.toggle("active", b.dataset.view === view));
  if (view === "dashboard") loadDashboard();
  if (view === "agents") loadAgents();
  if (view === "history") loadHistory();
  if (view === "leads") loadLeads();
  if (view === "tickets") loadTickets();
  if (view === "analytics") loadAnalytics();
  if (view === "dialer") loadCampaigns();
}

/* ---------- dashboard ---------- */
async function loadDashboard() {
  const a = await api.get("/analytics");
  if (!a.ok) return;
  $("kpi-calls").textContent = a.total_calls;
  $("kpi-resolved").textContent = Math.round((a.resolution_rate || 0) * 100) + "%";
  $("kpi-duration").textContent = Math.round(a.avg_duration_sec || 0) + "s";
  $("kpi-csat").textContent = a.avg_csat ? a.avg_csat.toFixed(1) + " / 5" : "—";
  $("kpi-tickets").textContent = a.open_tickets;
  $("kpi-leads").textContent = a.leads_new;
  const calls = await api.get("/calls?limit=8");
  $("recent-calls").innerHTML = (calls.calls || []).map(c =>
    `<tr><td>${esc(c.id)}</td><td>${esc(c.agent_id)}</td><td>${esc(c.direction)}</td>
     <td>${esc(c.contact_name || "—")}</td><td>${esc(c.state)}</td>
     <td>${esc(c.outcome || "—")}</td><td>${c.duration_sec}s</td></tr>`).join("") ||
    `<tr><td colspan="7">No calls yet — start one from Live Calls.</td></tr>`;
}

/* ---------- agents ---------- */
async function loadAgents() {
  const d = await api.get("/agents");
  agents = d.agents || [];
  $("agent-list").innerHTML = agents.map(a => `
    <div class="card agent-card">
      <h3>${esc(a.name)} <span class="tag">${esc(a.role)}</span></h3>
      <p class="muted">${esc(a.persona)}</p>
      <p><b>Voice:</b> ${esc(a.voice.name || a.voice.lang)} · rate ${a.voice.rate} · pitch ${a.voice.pitch}</p>
      <p><b>Tools:</b> ${a.tools.map(esc).join(", ") || "—"}</p>
      <details><summary>Sample dialogue</summary>
        ${(a.sample_dialogue || []).map(l => `<p><b>${esc(l[0])}:</b> ${esc(l[1])}</p>`).join("")}
      </details>
      <p><button onclick="editAgent('${a.id}')">Edit</button>
         <button onclick="callAgent('${a.id}')">Call with this agent</button></p>
    </div>`).join("");
  const sel = $("call-agent");
  sel.innerHTML = agents.map(a => `<option value="${a.id}">${esc(a.name)} — ${esc(a.role)}</option>`).join("");
  const dsel = $("campaign-agent");
  if (dsel) dsel.innerHTML = sel.innerHTML;
}

function editAgent(id) {
  const a = agents.find(x => x.id === id);
  if (!a) return;
  $("agent-form-title").textContent = "Edit agent — " + a.name;
  $("af-id").value = a.id;
  $("af-name").value = a.name;
  $("af-role").value = a.role;
  $("af-persona").value = a.persona;
  $("af-greeting").value = a.greeting;
  $("af-prompt").value = a.system_prompt;
  $("af-voice-name").value = a.voice.name || "";
  $("af-voice-rate").value = a.voice.rate;
  $("af-voice-pitch").value = a.voice.pitch;
  $("agent-form").style.display = "block";
  window.scrollTo(0, 0);
}

function newAgent() {
  $("agent-form-title").textContent = "New agent";
  ["af-id", "af-name", "af-role", "af-persona", "af-greeting", "af-prompt", "af-voice-name"].forEach(i => $(i).value = "");
  $("af-voice-rate").value = 1.0;
  $("af-voice-pitch").value = 1.0;
  $("agent-form").style.display = "block";
}

async function saveAgent(ev) {
  ev.preventDefault();
  const body = {
    id: $("af-id").value.trim(), name: $("af-name").value.trim(),
    role: $("af-role").value.trim(), persona: $("af-persona").value.trim(),
    greeting: $("af-greeting").value.trim(), system_prompt: $("af-prompt").value.trim(),
    voice_name: $("af-voice-name").value.trim(),
    voice_rate: parseFloat($("af-voice-rate").value) || 1.0,
    voice_pitch: parseFloat($("af-voice-pitch").value) || 1.0,
    tools: [], intents: [], sample_dialogue: [],
  };
  const existing = agents.find(x => x.id === body.id);
  const res = existing ? await api.put("/agents/" + body.id, body)
                       : await api.post("/agents", body);
  if (!res.ok) { alert(res.error || "Could not save agent."); return; }
  $("agent-form").style.display = "none";
  loadAgents();
}

/* ---------- live calls ---------- */
function addTurn(speaker, text) {
  const box = $("live-transcript");
  const div = document.createElement("div");
  div.className = "turn " + speaker;
  div.innerHTML = `<b>${esc(speaker)}:</b> ${esc(text)}`;
  box.appendChild(div);
  box.scrollTop = box.scrollHeight;
}

function setCallStatus(s) { $("call-status").textContent = s; }

async function callAgent(agentId) {
  show("live");
  $("call-agent").value = agentId;
  startCall();
}

async function startCall() {
  if (activeCall) { alert("A call is already active — end it first."); return; }
  const agentId = $("call-agent").value;
  const name = $("call-contact").value.trim();
  const direction = $("call-direction").value;
  const res = await api.post("/calls/start", { agent_id: agentId, direction, contact_name: name });
  if (!res.ok) { alert(res.error || "Could not start call."); return; }
  activeCall = { id: res.call_id, agent: res.agent, state: "RINGING" };
  $("live-transcript").innerHTML = "";
  $("supervisor-panel").style.display = "block";
  $("call-controls").style.display = "block";
  $("call-start-panel").style.display = "none";
  setCallStatus("Ringing… (simulated dialling — browser call, no phone line)");
  addTurn("system", `Call ${res.call_id} started with ${res.agent.name} (${res.agent.role}).`);
  setTimeout(async () => {
    if (!activeCall) return;
    await api.post(`/calls/${activeCall.id}/state`, { state: "ACTIVE" });
    activeCall.state = "ACTIVE";
    setCallStatus("Active — speak now, or type below");
    addTurn("agent", res.agent.greeting);
    Voice.speak(res.agent.greeting, res.agent);
    startMic();
  }, 1500);
}

function startMic() {
  if (!Voice.supported) {
    $("mic-note").textContent = "This browser has no SpeechRecognition (try Chrome or Edge). Type your replies in the text box below — the agent still answers by voice.";
    return;
  }
  const ok = Voice.startListening(onCallerSpeech, (s) => {
    $("mic-state").textContent = s.listening ? (s.speaking ? "Agent speaking… (speak to interrupt)" : "Listening…") : "Mic off";
  });
  micOn = ok;
  if (!ok) $("mic-note").textContent = "Microphone could not start — check browser permission, or type below.";
}

async function onCallerSpeech(text) {
  if (!activeCall || activeCall.state !== "ACTIVE") return;
  addTurn("caller", text);
  const res = await api.post(`/calls/${activeCall.id}/turn`, { text });
  if (!res.ok) { addTurn("system", res.error || "Turn failed."); return; }
  if (res.mode === "supervisor") {
    addTurn("system", "Supervisor has taken over — the agent is silent.");
    return;
  }
  if (res.reply) {
    addTurn("agent", res.reply);
    Voice.speak(res.reply, activeCall.agent, () => {
      if (res.end_call) endCallPrompt();
    });
  }
}

async function sendTyped() {
  const inp = $("typed-input");
  const text = inp.value.trim();
  if (!text || !activeCall) return;
  inp.value = "";
  await onCallerSpeech(text);
}

function endCallPrompt() {
  if (!activeCall) return;
  if (confirm("The agent has finished. End this call now?")) endCall("resolved");
}

async function endCall(outcome) {
  if (!activeCall) return;
  Voice.stopListening();
  Voice.stopSpeaking();
  micOn = false;
  const csat = parseInt($("call-csat").value || "0", 10);
  const res = await api.post(`/calls/${activeCall.id}/end`, { outcome: outcome || "ended", csat: csat || 0 });
  addTurn("system", `Call ended. Duration ${res.duration_sec || 0}s. Outcome: ${outcome || "ended"}.`);
  setCallStatus("Ended");
  activeCall = null;
  $("call-controls").style.display = "none";
  $("call-start-panel").style.display = "block";
  $("supervisor-panel").style.display = "none";
  loadDashboard();
}

/* ---------- supervisor ---------- */
async function supervise(action) {
  if (!activeCall) return;
  const msg = action === "whisper" ? $("whisper-input").value.trim() : "";
  if (action === "whisper" && !msg) { alert("Type a whisper message first."); return; }
  const res = await api.post(`/calls/${activeCall.id}/supervise`, { action, message: msg });
  if (!res.ok) { alert(res.error || "Supervisor action failed."); return; }
  if (action === "whisper") {
    addTurn("system", `Supervisor whisper (only the agent hears this): ${msg}`);
    $("whisper-input").value = "";
  }
  if (action === "barge") {
    addTurn("system", "Supervisor barged in — the agent is silent. Type below to speak as the agent.");
    $("supervisor-say-box").style.display = "block";
  }
  if (action === "resume") {
    addTurn("system", "Supervisor handed the call back to the agent.");
    $("supervisor-say-box").style.display = "none";
  }
  if (action === "listen") addTurn("system", "Supervisor is listening to the live transcript.");
}

async function supervisorSay() {
  const inp = $("supervisor-say-input");
  const text = inp.value.trim();
  if (!text || !activeCall) return;
  inp.value = "";
  const res = await api.post(`/calls/${activeCall.id}/supervisor-say`, { text });
  if (!res.ok) { alert(res.error || "Could not send."); return; }
  addTurn("agent", text);
  Voice.speak(text, activeCall.agent);
}

/* ---------- dialer / campaigns ---------- */
async function loadCampaigns() {
  const d = await api.get("/campaigns");
  $("campaign-list").innerHTML = (d.campaigns || []).map(c => {
    const done = c.contacts.filter(x => x.status === "done").length;
    return `<div class="card"><h3>${esc(c.name)}</h3>
      <p>Agent: ${esc(c.agent_id)} · Status: ${esc(c.status)} · ${done}/${c.contacts.length} done</p>
      <p><button onclick="runCampaign(${c.id})" ${c.status === "active" ? "" : "disabled"}>Dial next (simulated)</button>
      ${c.status === "draft" ? `<button onclick="startCampaign(${c.id})">Start campaign</button>` : ""}</p>
      <p class="muted">Contacts are demo labels (SIM-001…). No real phone numbers are dialled — this is a simulated dialler until Twilio is connected.</p>
    </div>`;
  }).join("") || "<p>No campaigns yet.</p>";
}

async function createCampaign(ev) {
  ev.preventDefault();
  const lines = $("campaign-contacts").value.split("\n").map(s => s.trim()).filter(Boolean);
  const contacts = lines.map((l, i) => ({ ref: "SIM-" + String(i + 1).padStart(3, "0"), name: l }));
  const res = await api.post("/campaigns", {
    name: $("campaign-name").value.trim(),
    agent_id: $("campaign-agent").value, contacts,
  });
  if (!res.ok) { alert(res.error || "Could not create campaign."); return; }
  $("campaign-name").value = "";
  $("campaign-contacts").value = "";
  loadCampaigns();
}

async function startCampaign(id) {
  await api.post(`/campaigns/${id}/start`, {});
  loadCampaigns();
}

async function runCampaign(id) {
  const d = await api.get(`/campaigns/${id}/next`);
  if (d.done) { alert("Campaign finished — no pending contacts."); loadCampaigns(); return; }
  show("live");
  $("call-agent").value = $("campaign-agent").value;
  $("call-contact").value = d.contact.name;
  $("call-direction").value = "outbound";
  await startCall();
  // mark contact done when the call ends — poll for it
  const contactId = d.contact.id;
  const iv = setInterval(async () => {
    if (!activeCall) {
      await api.patch(`/campaigns/${id}/contacts/${contactId}`, { status: "done" });
      clearInterval(iv);
      loadCampaigns();
    }
  }, 2000);
}

/* ---------- history / replay ---------- */
async function loadHistory() {
  const d = await api.get("/calls?limit=50");
  $("history-list").innerHTML = (d.calls || []).map(c =>
    `<tr><td>${esc(c.id)}</td><td>${esc(c.agent_id)}</td><td>${esc(c.direction)}</td>
     <td>${esc(c.contact_name || "—")}</td><td>${esc(c.started_at.slice(0, 16).replace("T", " "))}</td>
     <td>${c.duration_sec}s</td><td>${esc(c.outcome || "—")}</td>
     <td>${c.csat ? c.csat + "/5" : "—"}</td>
     <td><button onclick="viewCall('${c.id}')">Transcript</button></td></tr>`).join("") ||
    `<tr><td colspan="9">No calls yet.</td></tr>`;
}

async function viewCall(id) {
  const d = await api.get("/calls/" + id);
  if (!d.ok) return;
  const c = d.call;
  $("modal-title").textContent = `Call ${c.id} — ${c.agent.name} (${c.agent.role})`;
  $("modal-body").innerHTML =
    `<p>Direction: ${esc(c.direction)} · Contact: ${esc(c.contact_name || "—")} · State: ${esc(c.state)} · Outcome: ${esc(c.outcome || "—")} · Duration: ${c.duration_sec}s</p>` +
    (c.turns || []).map(t => `<div class="turn ${esc(t.speaker)}"><b>${esc(t.speaker)}:</b> ${esc(t.text)}</div>`).join("") +
    `<p class="muted">Replay re-synthesises the transcript with text-to-speech — it is not a stored audio recording.</p>
     <p><button onclick="replayCall('${c.id}')">Replay transcript (TTS)</button>
        <button onclick="stopReplay()">Stop replay</button></p>`;
  $("modal").style.display = "block";
}

async function replayCall(id) {
  const d = await api.get("/calls/" + id);
  if (!d.ok) return;
  replayStop = false;
  const lines = (d.call.turns || []).filter(t => t.speaker === "agent");
  for (const line of lines) {
    if (replayStop) break;
    await new Promise(res => Voice.speak(line.text, d.call.agent, res));
  }
}
function stopReplay() { replayStop = true; Voice.stopSpeaking(); }
function closeModal() { $("modal").style.display = "none"; stopReplay(); }

/* ---------- leads / tickets ---------- */
async function loadLeads() {
  const d = await api.get("/leads");
  $("leads-list").innerHTML = (d.leads || []).map(l =>
    `<tr><td>${esc(l.name)}</td><td>${esc(l.phone || "—")}</td><td>${esc(l.email || "—")}</td>
     <td>${esc(l.interest)}</td><td>${esc(l.source)}</td><td>${esc(l.status)}</td>
     <td>${esc((l.created_at || "").slice(0, 10))}</td></tr>`).join("") ||
    `<tr><td colspan="7">No leads captured yet — they land here from calls.</td></tr>`;
}

async function loadTickets() {
  const d = await api.get("/tickets");
  $("tickets-list").innerHTML = (d.tickets || []).map(t =>
    `<tr><td>TKT-${String(t.id).padStart(4, "0")}</td><td>${esc(t.subject)}</td>
     <td>${esc(t.priority)}</td><td>${esc(t.status)}</td><td>${esc(t.caller_name || "—")}</td>
     <td>${esc((t.created_at || "").slice(0, 10))}</td>
     <td>${t.status === "open" ? `<button onclick="closeTicket(${t.id})">Close</button>`
        : `<button onclick="reopenTicket(${t.id})">Reopen</button>`}</td></tr>`).join("") ||
    `<tr><td colspan="7">No tickets yet.</td></tr>`;
}
async function closeTicket(id) { await api.patch("/tickets/" + id, { status: "closed" }); loadTickets(); }
async function reopenTicket(id) { await api.patch("/tickets/" + id, { status: "open" }); loadTickets(); }

/* ---------- analytics ---------- */
async function loadAnalytics() {
  const a = await api.get("/analytics");
  if (!a.ok) return;
  const max = Math.max(1, ...a.calls_per_day.map(x => x.n));
  $("analytics-bars").innerHTML = (a.calls_per_day || []).slice().reverse().map(x =>
    `<div class="bar-row"><span>${esc(x.day)}</span>
     <div class="bar" style="width:${Math.round(x.n / max * 100)}%"></div><b>${x.n}</b></div>`).join("") ||
    "<p>No calls yet.</p>";
  $("analytics-agents").innerHTML = (a.calls_per_agent || []).map(x =>
    `<tr><td>${esc(x.agent_id)}</td><td>${x.n}</td></tr>`).join("") || `<tr><td colspan="2">—</td></tr>`;
}

/* ---------- boot ---------- */
document.addEventListener("DOMContentLoaded", () => {
  loadAgents();
  loadDashboard();
  if (!Voice.supported) $("voice-warning").style.display = "block";
});
