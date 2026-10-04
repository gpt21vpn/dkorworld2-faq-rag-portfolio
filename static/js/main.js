window.DKORConversationHistory = window.DKORConversationHistory || [];

document.addEventListener('DOMContentLoaded', () => {
  initReveal();
  initTilt();
  initHeroScene();
  initPointerGlow();
  initScrollUI();
  initForms();
  initTooltips();
  initChatWidget();
  initHeroParticles();
  initTheme();
  initCapabilities();
  initVoiceDemo();
  initChatVoice();
});

function initReveal() {
  const items = document.querySelectorAll('.benefit-card,.service-feature,.secondary-card,.visual-work,.showcase-card,.process-step,.review-card,.proof-shell,.about-card,.contact-shell,.case-list-item,.case-story,.contact-info-panel,.large-form');
  if (!items.length) return;
  if (!('IntersectionObserver' in window)) {
    items.forEach(el => el.classList.add('reveal-visible'));
    return;
  }
  items.forEach(el => el.classList.add('reveal-item'));
  const observer = new IntersectionObserver(entries => {
    entries.forEach(entry => {
      if (entry.isIntersecting) {
        entry.target.classList.add('reveal-visible');
        observer.unobserve(entry.target);
      }
    });
  }, { threshold: 0.1, rootMargin: '0px 0px -35px 0px' });
  items.forEach(el => observer.observe(el));
}

function initTilt() {
  if (window.matchMedia('(prefers-reduced-motion: reduce)').matches) return;
  if (window.matchMedia('(pointer: coarse)').matches) return;
  document.querySelectorAll('[data-tilt]').forEach(card => {
    card.addEventListener('mousemove', e => {
      const r = card.getBoundingClientRect();
      const x = (e.clientX - r.left) / r.width - 0.5;
      const y = (e.clientY - r.top) / r.height - 0.5;
      card.style.transform = `perspective(900px) rotateX(${(-y*5.5).toFixed(2)}deg) rotateY(${(x*7).toFixed(2)}deg) translateY(-3px)`;
    });
    card.addEventListener('mouseleave', () => { card.style.transform = ''; });
  });
}

function initHeroScene() {
  const scene = document.getElementById('hero-scene');
  const wrap = scene ? scene.parentElement : null;
  if (!scene || !wrap) return;
  if (window.matchMedia('(prefers-reduced-motion: reduce)').matches) return;
  if (window.matchMedia('(pointer: coarse)').matches) return;
  wrap.addEventListener('mousemove', e => {
    const r = wrap.getBoundingClientRect();
    const x = (e.clientX - r.left) / r.width - 0.5;
    const y = (e.clientY - r.top) / r.height - 0.5;
    scene.style.transform = `rotateX(${8-y*10}deg) rotateY(${-10+x*15}deg)`;
  });
  wrap.addEventListener('mouseleave', () => { scene.style.transform = 'rotateX(8deg) rotateY(-10deg)'; });
}

function initPointerGlow() {
  const glow = document.getElementById('pointer-glow');
  if (!glow || window.matchMedia('(pointer: coarse)').matches) return;
  window.addEventListener('pointermove', e => {
    glow.style.left = `${e.clientX}px`;
    glow.style.top = `${e.clientY}px`;
  }, { passive:true });
}

function initScrollUI() {
  const nav = document.querySelector('.site-nav');
  const progress = document.getElementById('scroll-progress');
  const update = () => {
    const y = window.scrollY || 0;
    if (nav) nav.classList.toggle('scrolled', y > 16);
    if (progress) {
      const max = document.documentElement.scrollHeight - window.innerHeight;
      progress.style.width = `${max > 0 ? Math.min(100,(y/max)*100) : 0}%`;
    }
  };
  update();
  window.addEventListener('scroll', update, { passive:true });
}

function initForms() {
  document.querySelectorAll('form[id^="contactForm"]').forEach(form => {
    const phone = form.querySelector('[name="phone"]');
    if (!phone) return;

  form.addEventListener('submit', e => {
      const digits = phone.value.replace(/\D/g,'');
      if (phone.value && (digits.length < 10 || digits.length > 11)) {
        e.preventDefault();
        phone.classList.add('is-invalid');
        let err = phone.parentNode.querySelector('.client-phone-error');
        if (!err) {
          err = document.createElement('div');
          err.className = 'invalid-feedback d-block client-phone-error';
          err.textContent = 'Введите корректный номер телефона (10–11 цифр)';
          phone.parentNode.appendChild(err);
        }
      }
    });

    phone.addEventListener('input', e => {
      let value = e.target.value.replace(/\D/g,'').slice(0,11);
      if (value[0] === '8') value = '7' + value.slice(1);
      if (value.length && value[0] !== '7') value = '7' + value;
      let f = value.length ? '+7' : '';
      if (value.length > 1) f += ' (' + value.slice(1,4);
      if (value.length >= 4) f += ') ' + value.slice(4,7);
      if (value.length >= 7) f += '-' + value.slice(7,9);
      if (value.length >= 9) f += '-' + value.slice(9,11);
      e.target.value = f;
      phone.classList.remove('is-invalid');
      const err = phone.parentNode.querySelector('.client-phone-error');
      if (err) err.remove();
    });
  });
}

function initTooltips() {
  if (typeof bootstrap === 'undefined') return;
  document.querySelectorAll('[data-bs-toggle="tooltip"]').forEach(el => new bootstrap.Tooltip(el));
}

function initChatWidget() {
  const launcher = document.getElementById('chat-launcher');
  const widget = document.getElementById('chat-widget');
  const closeBtn = widget ? widget.querySelector('.chat-close-btn') : null;
  const form = document.getElementById('chat-form');
  const input = document.getElementById('chat-input');
  const messages = document.getElementById('chat-messages');
  const typing = document.getElementById('chat-typing');
  if (!launcher || !widget || !form || !input || !messages) return;

  const open = () => { widget.classList.remove('closed'); widget.setAttribute('aria-hidden','false'); input.focus(); };
  const close = () => { widget.classList.add('closed'); widget.setAttribute('aria-hidden','true'); };
  launcher.addEventListener('click', () => widget.classList.contains('closed') ? open() : close());
  if (closeBtn) closeBtn.addEventListener('click', close);

  // Показываем реплики этого визита, если пользователь уже общался на другой странице
  setTimeout(restoreHistory, 0);

  const chatHistory = window.DKORConversationHistory;

  // Переписка живёт в рамках одного визита: sessionStorage держит её до закрытия
  // вкладки, поэтому переход на другую страницу сайта диалог больше не теряет.
  const HISTORY_KEY = 'dkor_chat_history';

  function saveHistory() {
    try { sessionStorage.setItem(HISTORY_KEY, JSON.stringify(chatHistory.slice(-16))); } catch (_) {}
  }

  function restoreHistory() {
    let saved = [];
    try { saved = JSON.parse(sessionStorage.getItem(HISTORY_KEY) || '[]'); } catch (_) { return; }
    if (!Array.isArray(saved) || !saved.length) return;
    saved.forEach(item => {
      if (!item || !item.content) return;
      chatHistory.push(item);
      append(item.content, item.role === 'user' ? 'user' : 'bot',
             item.role === 'user' ? '' : 'Из этого визита');
    });
  }

  function append(text, who='bot', meta='') {
    const row = document.createElement('div');
    row.className = `chat-message ${who}`;
    const label = document.createElement('span');
    label.className = 'chat-who';
    label.textContent = who === 'user' ? 'Вы' : 'AI-консультант';
    row.appendChild(label);
    const bubble = document.createElement('div');
    bubble.className = 'chat-bubble';
    bubble.textContent = text;
    row.appendChild(bubble);
    if (meta && who === 'bot') {
      const note = document.createElement('small');
      note.className = 'chat-source';
      note.textContent = meta;
      row.appendChild(note);
    }
    messages.appendChild(row);
    messages.scrollTop = messages.scrollHeight;
  }

  async function send(message) {
    if (!message) return;
    append(message,'user');
    chatHistory.push({role:'user', content:message});
    saveHistory();
    input.value = '';
    if (typing) typing.classList.remove('d-none');
    try {
      const res = await fetch('/chat', {
        method:'POST',
        headers:{'Content-Type':'application/json','X-CSRFToken':getCsrfToken()},
        body:JSON.stringify({message,top_k:4,history:chatHistory.slice(-6)})
      });
      const data = await res.json().catch(() => ({}));
      if (!res.ok) throw new Error(data.error || 'Ошибка сети');
      const answerText = data.answer || data.error || 'Ответ не получен.';
      const sourceTitle = Array.isArray(data.sources) && data.sources[0]?.title ? data.sources[0].title : '';
      const modeTitle = (data.mode === 'rag' || data.mode === 'rag_faiss') ? 'RAG + FAISS + база знаний'
        : data.mode === 'refusal' ? 'Нет данных в базе знаний'
        : data.mode === 'kb_fallback' ? 'Локальная база знаний (резерв)'
        : 'База знаний (быстрый ответ)';
      append(answerText, 'bot', sourceTitle ? `${modeTitle} · ${sourceTitle}` : modeTitle);
      DKORSpeech.say(answerText);
      chatHistory.push({role:'assistant', content:answerText});
      saveHistory();
      while (chatHistory.length > 12) chatHistory.shift();
    } catch (err) {
      append(err.message || 'Не удалось обратиться к AI-ассистенту.');
    } finally {
      if (typing) typing.classList.add('d-none');
    }
  }

  window.DKORChatSend = send;

  form.addEventListener('submit', e => {
    e.preventDefault();
    const msg = input.value.trim();
    if (msg) send(msg);
  });
}

// ===== Portrait hero: sphere rotation, parallax and clickable satellites =====
(function initPortfolioHero(){
  const stage = document.getElementById('portrait-stage');
  const orb = document.getElementById('hand-orb');
  if(!stage || !orb) return;

  const frame = stage.querySelector('.portrait-frame');
  const coarse = window.matchMedia('(pointer: coarse)').matches;
  const reduced = window.matchMedia('(prefers-reduced-motion: reduce)').matches;

  if(!coarse && !reduced){
    stage.addEventListener('mousemove', (e) => {
      const r = stage.getBoundingClientRect();
      const x = (e.clientX - r.left) / r.width - .5;
      const y = (e.clientY - r.top) / r.height - .5;
      if(frame) frame.style.transform = `perspective(1100px) rotateY(${-4 + x*5}deg) rotateX(${2 - y*4}deg)`;
      orb.style.setProperty('--ry', `${x*18}deg`);
      orb.style.setProperty('--rx', `${-y*14}deg`);
    });
    stage.addEventListener('mouseleave', () => {
      if(frame) frame.style.transform = 'perspective(1100px) rotateY(-4deg) rotateX(2deg)';
      orb.style.setProperty('--ry','0deg');
      orb.style.setProperty('--rx','0deg');
    });
  }

  stage.querySelectorAll('a[href^="#"]').forEach(link => {
    link.addEventListener('click', (e) => {
      const target = document.querySelector(link.getAttribute('href'));
      if(!target) return;
      e.preventDefault();
      target.scrollIntoView({behavior:'smooth',block:'start'});
    });
  });
})();


function initHeroParticles() {
  const stage = document.getElementById('portrait-stage');
  if (!stage || window.matchMedia('(prefers-reduced-motion: reduce)').matches) return;
  const count = window.innerWidth < 700 ? 8 : 18;
  for (let i = 0; i < count; i++) {
    const p = document.createElement('span');
    p.className = 'hero-particle';
    p.style.left = `${8 + Math.random() * 86}%`;
    p.style.top = `${8 + Math.random() * 72}%`;
    p.style.setProperty('--s', `${1 + Math.random() * 2.5}px`);
    p.style.setProperty('--d', `${5 + Math.random() * 8}s`);
    p.style.setProperty('--delay', `${-Math.random() * 8}s`);
    stage.appendChild(p);
  }
}

function getCsrfToken() {
  return document.querySelector('meta[name="csrf-token"]')?.getAttribute('content') || '';
}

function initTheme() {
  const btn = document.getElementById('theme-switch');
  const saved = localStorage.getItem('dkor-theme');
  const set = (light) => {
    document.body.classList.toggle('light-theme', light);
    if (btn) {
      btn.innerHTML = light ? '<i class="bi bi-sun-fill"></i><span>Тема</span>' : '<i class="bi bi-moon-stars-fill"></i><span>Тема</span>';
      btn.setAttribute('aria-pressed', String(light));
    }
  };
  set(saved ? saved === 'light' : true);
  const updateThemeMeta = () => {
    const meta = document.querySelector('meta[name="theme-color"]');
    if (meta) meta.setAttribute('content', document.body.classList.contains('light-theme') ? '#efe6d8' : '#080b12');
  };
  updateThemeMeta();
  btn?.addEventListener('click', () => {
    const light = !document.body.classList.contains('light-theme');
    set(light);
    localStorage.setItem('dkor-theme', light ? 'light' : 'dark');
    updateThemeMeta();
  });
}

let DKOR_CAPABILITIES = {chat:true, kb:true, rag:false, groq_voice:false, telegram_leads:false};
async function initCapabilities() {
  try {
    const res = await fetch('/api/capabilities');
    if (res.ok) DKOR_CAPABILITIES = await res.json();
  } catch (_) {}
  const mode = document.getElementById('chat-mode');
  if (mode) {
    mode.innerHTML = DKOR_CAPABILITIES.rag
      ? '<span class="status-dot"></span><span>RAG + база знаний DKORWORLD2</span>'
      : '<span class="status-dot"></span><span>Локальная база знаний DKORWORLD2</span>';
  }
  const provider = document.getElementById('voice-provider');
  if (provider) provider.textContent = DKOR_CAPABILITIES.groq_voice ? 'GROQ VOICE' : 'BROWSER VOICE';
}

async function askAssistant(text) {
  if (!text) return '';
  const history = window.DKORConversationHistory;
  history.push({role:'user', content:text});
  try {
    const res = await fetch('/chat', {
      method:'POST',
      headers:{'Content-Type':'application/json','X-CSRFToken':getCsrfToken()},
      body:JSON.stringify({message:text, top_k:4, history:history.slice(-6)})
    });
    const data = await res.json().catch(() => ({}));
    if (!res.ok) throw new Error(data.error || 'Ошибка ответа');
    const reply = data.answer || 'Ответ не получен.';
    history.push({role:'assistant', content:reply});
    while (history.length > 12) history.shift();
    return reply;
  } catch (e) {
    // Remove the just-added user turn if the request itself failed.
    if (history.length && history[history.length-1]?.role === 'user' && history[history.length-1]?.content === text) history.pop();
    return e.message || 'Не удалось получить ответ.';
  }
}

function browserSpeechOnce({onStart, onResult, onError, onEnd}) {
  const SR = window.SpeechRecognition || window.webkitSpeechRecognition;
  if (!SR) { onError?.('Браузерное распознавание речи недоступно. Используйте Chrome/Edge или подключите Groq.'); return null; }
  const r = new SR();
  r.lang = 'ru-RU'; r.interimResults = false; r.maxAlternatives = 1;
  r.onstart = () => onStart?.();
  r.onresult = (e) => onResult?.(e.results?.[0]?.[0]?.transcript || '');
  r.onerror = (e) => onError?.(`Ошибка распознавания: ${e.error || 'unknown'}`);
  r.onend = () => onEnd?.();
  r.start();
  return r;
}

/* Живое распознавание речи.
   По умолчанию Web Speech API работает с continuous=false и interimResults=false:
   он обрывается на первой же паузе и отдаёт только финальный текст, а всё
   сказанное после паузы теряется. Здесь оба флага включены, финальные куски
   копятся в буфер, а промежуточный текст отдаётся отдельно — его рисуем серым.
   Chrome всё равно периодически сам вызывает onend, поэтому пока пользователь
   не нажал «стоп», распознавание перезапускается. */
function createLiveSpeech({onStart, onPartial, onFinal, onError, onEnd, autoStopMs = 5000}) {
  const SR = window.SpeechRecognition || window.webkitSpeechRecognition;
  if (!SR) { onError?.('Браузерное распознавание недоступно. Нужен Chrome или Edge.'); return null; }

  let wantListening = false;
  let finalText = '';
  let silenceTimer = null;
  let recognition = null;

  function armSilence() {
    clearTimeout(silenceTimer);
    // В Groq/server mode autoStopMs=0: пауза вообще не завершает запись.
    // В browser-only mode 5 секунд тишины — страховка для автоматического ответа.
    if (!autoStopMs || autoStopMs <= 0) return;
    silenceTimer = setTimeout(() => { if (wantListening) api.stop(); }, autoStopMs);
  }

  function build() {
    const r = new SR();
    r.lang = 'ru-RU';
    r.continuous = true;
    r.interimResults = true;
    r.maxAlternatives = 1;

    r.onstart = () => { onStart?.(); armSilence(); };
    r.onresult = (event) => {
      let interim = '';
      for (let i = event.resultIndex; i < event.results.length; i++) {
        const chunk = event.results[i][0]?.transcript || '';
        if (event.results[i].isFinal) finalText += (finalText ? ' ' : '') + chunk.trim();
        else interim += chunk;
      }
      onPartial?.((finalText + ' ' + interim).trim(), interim.trim());
      armSilence();
    };
    r.onerror = (event) => {
      const code = event.error || 'unknown';
      // no-speech и aborted при перезапуске — рабочая ситуация, не ошибка для пользователя
      if (code !== 'no-speech' && code !== 'aborted') onError?.(`Ошибка распознавания: ${code}`);
      if (code === 'not-allowed' || code === 'service-not-allowed') wantListening = false;
    };
    r.onend = () => {
      if (wantListening) {
        try { r.start(); } catch (_) { /* InvalidStateError при частом перезапуске */ }
        return;
      }
      clearTimeout(silenceTimer);
      onFinal?.(finalText.trim());
      onEnd?.();
    };
    return r;
  }

  const api = {
    start() {
      finalText = '';
      wantListening = true;
      recognition = build();
      try { recognition.start(); } catch (_) {}
    },
    stop() {
      wantListening = false;
      clearTimeout(silenceTimer);
      try { recognition?.stop(); } catch (_) {}
    },
    get listening() { return wantListening; },
    get text() { return finalText.trim(); },
  };
  return api;
}

/* Озвучка ответа. Браузерный синтез: без ключей и задержки.
   Список голосов приходит асинхронно, поэтому ждём onvoiceschanged.
   Длинный текст режем — часть движков обрывает реплику после ~300 символов. */
const DKORSpeech = (function () {
  let enabled = false;
  let ruVoice = null;

  function pickVoice() {
    if (!('speechSynthesis' in window)) return;
    const voices = window.speechSynthesis.getVoices() || [];
    ruVoice = voices.find(v => /ru[-_]RU/i.test(v.lang)) || voices.find(v => /^ru/i.test(v.lang)) || null;
  }
  if ('speechSynthesis' in window) {
    pickVoice();
    window.speechSynthesis.addEventListener?.('voiceschanged', pickVoice);
  }

  function chunk(text) {
    const parts = [];
    let rest = (text || '').trim();
    while (rest.length > 220) {
      let cut = rest.lastIndexOf('. ', 220);
      if (cut < 80) cut = rest.lastIndexOf(' ', 220);
      if (cut < 80) cut = 220;
      parts.push(rest.slice(0, cut + 1));
      rest = rest.slice(cut + 1).trim();
    }
    if (rest) parts.push(rest);
    return parts;
  }

  return {
    get supported() { return 'speechSynthesis' in window; },
    get enabled() { return enabled; },
    setEnabled(value) { enabled = !!value; if (!enabled) this.stop(); },
    stop() { if ('speechSynthesis' in window) window.speechSynthesis.cancel(); },
    say(text) {
      if (!enabled || !text || !('speechSynthesis' in window)) return;
      window.speechSynthesis.cancel();
      chunk(text).forEach(part => {
        const u = new SpeechSynthesisUtterance(part);
        u.lang = 'ru-RU';
        if (ruVoice) u.voice = ruVoice;
        u.rate = 1.0;
        window.speechSynthesis.speak(u);
      });
    },
  };
})();

function initChatVoice() {
  const btn = document.getElementById('chat-mic-btn');
  const input = document.getElementById('chat-input');
  if (!btn || !input) return;
  let live = null;
  btn.addEventListener('click', () => {
    if (live?.listening) { live.stop(); return; }
    live = createLiveSpeech({
      onStart: () => { btn.classList.add('listening'); input.placeholder = 'Слушаю — нажмите микрофон, чтобы закончить'; },
      onPartial: (full) => { input.value = full; },
      onFinal: (text) => { input.value = text; input.focus(); },
      onError: (msg) => { input.placeholder = msg; setTimeout(() => input.placeholder='Напишите или скажите вопрос...', 2600); },
      onEnd: () => { btn.classList.remove('listening'); input.placeholder = 'Напишите или скажите вопрос...'; },
    });
    live?.start();
  });
}

function initVoiceDemo() {
  const btn = document.getElementById('voice-record-btn');
  const floating = document.getElementById('floating-voice');
  const transcript = document.getElementById('voice-transcript');
  const answer = document.getElementById('voice-answer');
  const status = document.getElementById('voice-status');
  const wave = document.getElementById('voice-wave');
  const speakToggle = document.getElementById('voice-speak-toggle');
  const stopSpeakBtn = document.getElementById('voice-speak-stop');

  if (speakToggle) {
    if (!DKORSpeech.supported) {
      speakToggle.disabled = true;
      speakToggle.parentElement?.setAttribute('title', 'Браузер не поддерживает синтез речи');
    }
    speakToggle.addEventListener('change', () => DKORSpeech.setEnabled(speakToggle.checked));
  }
  stopSpeakBtn?.addEventListener('click', () => DKORSpeech.stop());

  if (!btn) {
    floating?.addEventListener('click', () => document.getElementById('voice-demo')?.scrollIntoView({behavior:'smooth'}));
    return;
  }

  let mediaRecorder = null, chunks = [], stream = null;
  let live = null;          // живое браузерное распознавание (для текста по ходу речи)
  let groqPending = false;  // ждём ли точную расшифровку с сервера

  const setListening = (active, text) => {
    btn.classList.toggle('recording', active);
    wave?.classList.toggle('active', active);
    if (status) status.textContent = text;
  };

  function showTranscript(text, isInterim) {
    if (!transcript) return;
    transcript.textContent = text || 'Здесь появится ваш вопрос.';
    transcript.classList.toggle('interim', !!isInterim && !!text);
  }

  async function answerFor(text) {
    text = (text || '').trim();
    if (!text) { setListening(false, 'Речь не распознана'); return; }
    showTranscript(text, false);
    setListening(false, 'Готово');
    if (answer) answer.textContent = 'Формирую ответ...';
    const reply = await askAssistant(text);
    if (answer) answer.textContent = reply;
    DKORSpeech.say(reply);
  }

  // ---- серверное распознавание (точный финал) ----
  async function sendAudio(blob) {
    groqPending = true;
    setListening(false, 'Уточняю расшифровку через Groq...');
    const fd = new FormData();
    fd.append('audio', blob, 'voice.webm');
    try {
      const res = await fetch('/voice/transcribe', {method:'POST', headers:{'X-CSRFToken':getCsrfToken()}, body:fd});
      const data = await res.json().catch(() => ({}));
      if (!res.ok) throw new Error(data.error || 'Не удалось распознать запись');
      groqPending = false;
      await answerFor(data.text);
    } catch (e) {
      groqPending = false;
      // Серверное распознавание не ответило — берём то, что успел услышать браузер.
      const fallbackText = live?.text || '';
      if (fallbackText) {
        if (status) status.textContent = 'Groq недоступен, отвечаю по браузерной расшифровке';
        await answerFor(fallbackText);
      } else {
        setListening(false, e.message || 'Не удалось распознать запись');
      }
    }
  }

  function startLive({sendToGroq}) {
    live = createLiveSpeech({
      // Groq пишет аудио до явного «Стоп» (или общего лимита 60 сек):
      // паузы любой длины не завершают запись.
      // Browser-only: 5 секунд тишины автоматически заканчивают реплику.
      autoStopMs: 5000,
      onStart: () => setListening(
        true,
        sendToGroq
          ? 'Слушаю — говорите. Паузы не обрывают запись; нажмите Стоп, когда закончите.'
          : 'Слушаю — говорите. Короткие паузы не прерывают фразу.'
      ),
      onPartial: (full, interim) => showTranscript(full, !!interim),
      onFinal: (text) => {
        if (sendToGroq) {
          // Пауза 5 секунд = конец фразы: останавливаем и саму запись,
          // иначе Groq потом дописывает в расшифровку «Продолжение следует...».
          if (mediaRecorder?.state === 'recording') {
            setListening(false, 'Пауза — заканчиваю запись');
            mediaRecorder.stop();
          }
          return;
        }
        answerFor(text);
      },
      onError: (msg) => { if (!sendToGroq) setListening(false, msg); },
      onEnd: () => {},
    });
    live?.start();
  }

  async function startRecording() {
    const useGroq = !!DKOR_CAPABILITIES.groq_voice
      && !!navigator.mediaDevices?.getUserMedia
      && typeof MediaRecorder !== 'undefined';

    showTranscript('', false);
    if (answer) answer.textContent = 'После распознавания вопрос уйдёт в чат-консультант.';

    // Живой текст показываем всегда: с Groq он идёт как черновик и потом уточняется.
    startLive({sendToGroq: useGroq});

    if (!useGroq) return;

    try {
      stream = await navigator.mediaDevices.getUserMedia({audio:true});
      chunks = [];
      mediaRecorder = new MediaRecorder(stream, {mimeType: MediaRecorder.isTypeSupported('audio/webm;codecs=opus') ? 'audio/webm;codecs=opus' : undefined});
      mediaRecorder.ondataavailable = e => { if (e.data?.size) chunks.push(e.data); };
      mediaRecorder.onstop = () => {
        stream?.getTracks().forEach(t => t.stop()); stream = null;
        const blob = new Blob(chunks, {type: mediaRecorder.mimeType || 'audio/webm'});
        mediaRecorder = null; chunks = [];
        if (blob.size) sendAudio(blob); else setListening(false, 'Запись пустая');
      };
      mediaRecorder.start();
      setListening(true, 'Слушаю — пауза 5 секунд или нажмите ещё раз');
      setTimeout(() => { if (mediaRecorder?.state === 'recording') stopEverything(); }, 60000);
    } catch (e) {
      setListening(false, 'Нет доступа к микрофону');
      live?.stop();
    }
  }

  function stopEverything() {
    live?.stop();
    if (mediaRecorder?.state === 'recording') mediaRecorder.stop();
  }

  btn.addEventListener('click', () => {
    const active = live?.listening || mediaRecorder?.state === 'recording';
    if (active) { setListening(false, 'Обрабатываю...'); stopEverything(); return; }
    if (groqPending) return;
    startRecording();
  });

  floating?.addEventListener('click', () => {
    document.getElementById('voice-demo')?.scrollIntoView({behavior:'smooth', block:'center'});
    setTimeout(() => btn.click(), 450);
  });

  document.querySelectorAll('[data-voice-example]').forEach(example => example.addEventListener('click', async () => {
    const text = example.dataset.voiceExample || '';
    showTranscript(text, false);
    if (answer) answer.textContent = 'Формирую ответ...';
    const reply = await askAssistant(text);
    if (answer) answer.textContent = reply;
    DKORSpeech.say(reply);
  }));
}
