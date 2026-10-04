// Запись на консультацию. Все времена — московские (МСК, UTC+3).
(function () {
  const daysBox = document.getElementById('booking-days');
  const form = document.getElementById('booking-form');
  if (!daysBox || !form) return;

  const slotField = document.getElementById('booking-slot');
  const chosenLabel = document.getElementById('booking-chosen');
  const submitBtn = document.getElementById('booking-submit');
  const resultBox = document.getElementById('booking-result');

  function csrf() {
    const meta = document.querySelector('meta[name="csrf-token"]');
    return meta ? meta.getAttribute('content') : '';
  }

  function showResult(html, ok) {
    if (!resultBox) return;
    resultBox.className = `booking-result ${ok ? 'ok' : 'fail'}`;
    resultBox.innerHTML = html;
  }

  function renderDays(payload) {
    const days = payload.days || [];
    if (!days.length) {
      daysBox.innerHTML = '<p class="text-muted small mb-0">Свободных слотов на две недели вперёд нет. Напишите в Telegram @dimaseo2 — подберём время вручную.</p>';
      return;
    }
    daysBox.innerHTML = days.map(day => `
      <div class="booking-day">
        <div class="booking-day-head"><strong>${day.date_label}</strong><span>${day.weekday}</span></div>
        <div class="booking-slots">
          ${day.slots.map(slot => `
            <button type="button" class="booking-slot" data-slot="${slot.start}"
                    data-label="${day.date_label} ${day.weekday}, ${slot.label} МСК">${slot.label}</button>
          `).join('')}
        </div>
      </div>
    `).join('');

    daysBox.querySelectorAll('.booking-slot').forEach(btn => {
      btn.addEventListener('click', () => {
        daysBox.querySelectorAll('.booking-slot.selected').forEach(el => el.classList.remove('selected'));
        btn.classList.add('selected');
        slotField.value = btn.dataset.slot || '';
        if (chosenLabel) chosenLabel.textContent = btn.dataset.label || 'не выбрано';
        if (submitBtn) submitBtn.disabled = false;
      });
    });
  }

  async function loadSlots() {
    try {
      const res = await fetch('/api/booking-slots');
      const data = await res.json();
      renderDays(data);
    } catch (e) {
      daysBox.innerHTML = '<p class="text-muted small mb-0">Не удалось загрузить расписание. Обновите страницу.</p>';
    }
  }

  form.addEventListener('submit', async (e) => {
    e.preventDefault();
    const payload = {
      slot: slotField.value,
      name: (document.getElementById('booking-name').value || '').trim(),
      contact: (document.getElementById('booking-contact').value || '').trim(),
      comment: (document.getElementById('booking-comment').value || '').trim(),
    };
    if (!payload.slot) { showResult('Сначала выберите время из списка.', false); return; }
    if (payload.name.length < 2 || payload.contact.length < 5) {
      showResult('Укажите имя и контакт для связи.', false);
      return;
    }

    submitBtn.disabled = true;
    submitBtn.innerHTML = 'Записываю…';
    try {
      const res = await fetch('/api/booking-create', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json', 'X-CSRFToken': csrf() },
        body: JSON.stringify(payload),
      });
      const data = await res.json().catch(() => ({}));
      if (!res.ok) {
        showResult(data.error || 'Не удалось записаться.', false);
        // Слот могли занять параллельно — обновляем расписание.
        if (data.code === 'SLOT_TAKEN') {
          slotField.value = '';
          if (chosenLabel) chosenLabel.textContent = 'не выбрано';
          await loadSlots();
        }
        return;
      }
      showResult(`
        <strong>Записал на ${data.slot_label}.</strong>
        <div class="booking-result-links">
          <a href="${data.ics_url}">Добавить в свой календарь</a>
          <a href="${data.cancel_url}">Отменить запись</a>
        </div>
        <p class="mb-1">Ссылку на отмену лучше сохранить.</p>
        <p class="mb-0 booking-sync-note">${data.calendar_synced
          ? 'Google Calendar: событие синхронизировано.'
          : 'Запись сохранена. Синхронизация Google Calendar зависит от n8n.'}</p>
      `, true);
      form.reset();
      slotField.value = '';
      if (chosenLabel) chosenLabel.textContent = 'не выбрано';
      await loadSlots();
    } catch (err) {
      showResult('Сеть недоступна. Попробуйте ещё раз.', false);
    } finally {
      submitBtn.disabled = !slotField.value;
      submitBtn.innerHTML = 'Записаться <i class="bi bi-calendar-check"></i>';
    }
  });

  loadSlots();
})();
