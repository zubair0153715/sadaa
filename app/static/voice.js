/* Sadaa — browser voice engine (free, no key, no card).
 * STT: webkitSpeechRecognition / SpeechRecognition
 * TTS: speechSynthesis
 * Barge-in: the moment the caller speaks, any agent speech is cancelled.
 * If the browser has no SpeechRecognition (Firefox, Safari), the text
 * box fallback still lets the user talk to the agent by typing.
 */
const Voice = (() => {
  const SR = window.SpeechRecognition || window.webkitSpeechRecognition;
  let recog = null;
  let listening = false;
  let speaking = false;
  let voices = [];
  let onFinal = null;      // fn(transcript)
  let onState = null;      // fn({listening, speaking})
  let wantListen = false;

  function loadVoices() {
    voices = window.speechSynthesis ? speechSynthesis.getVoices() : [];
  }
  if (window.speechSynthesis) {
    loadVoices();
    speechSynthesis.onvoiceschanged = loadVoices;
  }

  function pickVoice(agent) {
    if (!voices.length) return null;
    const pref = (agent && agent.voice) || {};
    const name = (pref.name || "").toLowerCase();
    const lang = pref.lang || "en-US";
    let v = name && voices.find(x => x.name.toLowerCase().includes(name));
    if (!v) v = voices.find(x => x.lang === lang);
    if (!v) v = voices.find(x => x.lang && x.lang.startsWith(lang.slice(0, 2)));
    return v || voices[0];
  }

  function speak(text, agent, onDone) {
    if (!window.speechSynthesis || !text) { onDone && onDone(); return; }
    speechSynthesis.cancel();
    const u = new SpeechSynthesisUtterance(text);
    const v = pickVoice(agent);
    if (v) u.voice = v;
    const pref = (agent && agent.voice) || {};
    u.rate = pref.rate || 1.0;
    u.pitch = pref.pitch || 1.0;
    u.lang = (pref.lang || "en-US");
    speaking = true;
    onState && onState({ listening, speaking });
    u.onend = () => { speaking = false; onState && onState({ listening, speaking }); onDone && onDone(); };
    u.onerror = () => { speaking = false; onState && onState({ listening, speaking }); onDone && onDone(); };
    speechSynthesis.speak(u);
  }

  function stopSpeaking() {
    if (window.speechSynthesis) speechSynthesis.cancel();
    speaking = false;
  }

  function startListening(onFinalText, onStateChange) {
    onFinal = onFinalText;
    onState = onStateChange || onState;
    if (!SR) return false;
    if (recog) { try { recog.stop(); } catch (e) {} }
    recog = new SR();
    recog.lang = "en-US";
    recog.interimResults = true;
    recog.continuous = true;
    wantListen = true;
    recog.onresult = (ev) => {
      for (let i = ev.resultIndex; i < ev.results.length; i++) {
        const r = ev.results[i];
        if (r.isFinal) {
          const text = r[0].transcript.trim();
          if (!text) continue;
          // Barge-in: caller spoke over the agent — cut the agent off.
          if (speaking) stopSpeaking();
          onFinal && onFinal(text);
        }
      }
    };
    recog.onend = () => {
      // Chrome stops recognition after a pause; restart while the call lives.
      if (wantListen && listening) { try { recog.start(); } catch (e) {} }
    };
    recog.onerror = () => {};
    try {
      recog.start();
      listening = true;
      onState && onState({ listening, speaking });
      return true;
    } catch (e) { return false; }
  }

  function stopListening() {
    wantListen = false;
    listening = false;
    if (recog) { try { recog.stop(); } catch (e) {} }
    onState && onState({ listening, speaking });
  }

  return {
    supported: !!SR,
    ttsSupported: !!window.speechSynthesis,
    speak, stopSpeaking, startListening, stopListening,
    get listening() { return listening; },
    get speaking() { return speaking; },
  };
})();
