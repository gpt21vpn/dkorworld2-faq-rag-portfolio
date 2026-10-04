(() => {
  const app = document.getElementById('quiz-app');
  if (!app) return;
  const form = document.getElementById('quiz-form');
  const steps = [...form.querySelectorAll('.quiz-step')];
  const next = document.getElementById('quiz-next');
  const back = document.getElementById('quiz-back');
  const controls = document.getElementById('quiz-controls');
  const bar = document.getElementById('quiz-progress-bar');
  const label = document.getElementById('quiz-step-label');
  const percent = document.getElementById('quiz-percent');
  const status = document.getElementById('quiz-submit-status');
  let current = 1;

  function selectedFor(step) {
    const block = steps.find(s => Number(s.dataset.step) === step);
    if (!block || step > 5) return true;
    return !!block.querySelector('input[type=radio]:checked');
  }

  function show(step) {
    current = step;
    steps.forEach(s => s.classList.toggle('active', Number(s.dataset.step) === step));
    const isFinish = step === 6;
    controls.style.display = isFinish ? 'none' : 'flex';
    back.disabled = step === 1;
    next.innerHTML = step === 5 ? 'К контактам <i class="bi bi-arrow-right"></i>' : 'Далее <i class="bi bi-arrow-right"></i>';
    const shown = Math.min(step, 5);
    const p = shown * 20;
    bar.style.width = `${p}%`;
    label.textContent = isFinish ? 'Бриф заполнен' : `Вопрос ${shown} из 5`;
    percent.textContent = `${p}%`;
    window.scrollTo({top: Math.max(0, app.offsetTop - 110), behavior:'smooth'});
  }

  next.addEventListener('click', () => {
    if (!selectedFor(current)) {
      const active = steps.find(s => Number(s.dataset.step) === current);
      active.classList.add('quiz-shake');
      setTimeout(() => active.classList.remove('quiz-shake'), 420);
      return;
    }
    show(Math.min(6, current + 1));
  });
  back.addEventListener('click', () => show(Math.max(1, current - 1)));

  form.querySelectorAll('input[type=radio]').forEach(input => input.addEventListener('change', () => {
    const labelEl = input.closest('label');
    labelEl?.parentElement?.querySelectorAll('label').forEach(l => l.classList.remove('selected'));
    labelEl?.classList.add('selected');
  }));

  form.addEventListener('submit', async (e) => {
    e.preventDefault();
    const name = document.getElementById('quiz-name').value.trim();
    const contact = document.getElementById('quiz-contact').value.trim();
    const consent = document.getElementById('quiz-consent').checked;
    if (!name || !contact || !consent) {
      status.textContent = 'Заполните имя, контакт и согласие.';
      status.className = 'quiz-submit-status error';
      return;
    }
    const answers = {};
    ['who','niche','need','readiness','budget'].forEach(key => {
      answers[key] = form.querySelector(`input[name="${key}"]:checked`)?.value || '';
    });
    const payload = {name, contact, comment: document.getElementById('quiz-comment').value.trim(), answers};
    const token = document.querySelector('meta[name="csrf-token"]')?.content || '';
    const submit = document.getElementById('quiz-submit');
    submit.disabled = true; status.textContent = 'Отправляю...'; status.className='quiz-submit-status';
    try {
      const res = await fetch('/api/quiz-submit', {method:'POST', headers:{'Content-Type':'application/json','X-CSRFToken':token}, body:JSON.stringify(payload)});
      const data = await res.json().catch(() => ({}));
      if (!res.ok) throw new Error(data.error || 'Ошибка отправки');
      const delivery = data.telegram_sent ? ' Копия уже отправлена владельцу в Telegram.' : '';
      status.innerHTML = `Готово. Заявка принята и сохранена.${delivery} <a href="https://t.me/dimaseo2" target="_blank" rel="noopener">Открыть Telegram</a>`;
      status.className = 'quiz-submit-status success';
    } catch (err) {
      status.textContent = err.message || 'Не удалось отправить.';
      status.className = 'quiz-submit-status error';
      submit.disabled = false;
    }
  });
})();
