/* Страница «Акция».
 *
 * Здесь только форма, показ и форматирование. Ни одной расчетной формулы:
 * считает ядро на Python, и если хоть одно число посчитать тут, у проекта
 * станет три расчета вместо двух, а расходиться они начнут молча.
 */

'use strict';

const state = {
  fields: [],          // описание полей, пришло с сервера
  values: {},          // что сейчас в форме, в долях
  sections: [],
  request: 0,          // номер последнего отправленного запроса
  shown: 0,            // номер последнего показанного
  answer: null,
  timer: null,
};

const money = new Intl.NumberFormat('ru-RU', { maximumFractionDigits: 0 });
const decimal = new Intl.NumberFormat('ru-RU', { minimumFractionDigits: 2, maximumFractionDigits: 2 });

function percent(fraction, digits) {
  const value = (fraction || 0) * 100;
  return value.toFixed(digits === undefined ? 1 : digits).replace('.', ',') + '%';
}

function toPercentInput(fraction) {
  // 0.05 -> 5, без хвоста из-за двоичной дроби.
  return Math.round((fraction || 0) * 1e6) / 1e4;
}

function millions(value) {
  return money.format(Math.round((value || 0) / 1e6 * 10) / 10).replace(/\s/g, ' ') + ' млн';
}

function element(tag, attrs, children) {
  const node = document.createElement(tag);
  Object.entries(attrs || {}).forEach(([name, value]) => {
    if (name === 'class') node.className = value;
    else if (name === 'text') node.textContent = value;
    else if (value !== null && value !== undefined) node.setAttribute(name, value);
  });
  (children || []).forEach((child) => node.appendChild(child));
  return node;
}

/* --- форма ------------------------------------------------------------- */

function fieldBox(field, control) {
  const box = element('div', { class: 'field', 'data-field': field.name });
  box.appendChild(element('label', { text: field.label }));
  box.appendChild(control);
  if (field.hint) box.appendChild(element('small', { class: 'hint', text: field.hint }));
  return box;
}

function numberInput(field, value, step, min, max) {
  const input = element('input', {
    type: 'number', value: value, step: step,
    min: min === null || min === undefined ? null : min,
    max: max === null || max === undefined ? null : max,
  });
  input.addEventListener('input', () => {
    state.values[field.name] = readControl(field, input);
    schedule();
  });
  return input;
}

function readControl(field, input) {
  const raw = input.value.trim().replace(',', '.');
  if (raw === '') return null;
  const number = Number(raw);
  if (Number.isNaN(number)) return raw;
  return field.kind === 'fraction' ? number / 100 : number;
}

function buildField(field) {
  const value = state.values[field.name];

  if (field.kind === 'date') {
    const input = element('input', { type: 'date', value: value || '' });
    input.addEventListener('input', () => {
      state.values[field.name] = input.value;
      schedule();
    });
    return fieldBox(field, input);
  }

  if (field.kind === 'fraction') {
    // Ползунок и число рядом: доля объема без акции — главный рычаг расчета,
    // ее крутят, а не набирают.
    const pair = element('div', { class: 'pair' });
    const step = (field.step || 0.01) * 100;
    const slider = element('input', {
      type: 'range', min: (field.low || 0) * 100, max: (field.high || 1) * 100,
      step: step, value: toPercentInput(value),
    });
    const number = element('input', {
      type: 'number', step: step, value: toPercentInput(value),
      min: (field.low || 0) * 100, max: (field.high || 1) * 100,
    });
    const sync = (source, other) => {
      other.value = source.value;
      state.values[field.name] = readControl(field, source);
      schedule();
    };
    slider.addEventListener('input', () => sync(slider, number));
    number.addEventListener('input', () => sync(number, slider));
    pair.appendChild(slider);
    pair.appendChild(number);
    return fieldBox(field, pair);
  }

  if (field.kind === 'choice') {
    const box = element('div', { class: 'choice' });
    field.options.forEach((option) => {
      const label = element('label');
      const radio = element('input', {
        type: 'radio', name: field.name, value: option.value,
      });
      radio.checked = option.value === value;
      radio.addEventListener('change', () => {
        state.values[field.name] = option.value;
        schedule();
      });
      label.appendChild(radio);
      label.appendChild(document.createTextNode(option.label));
      box.appendChild(label);
    });
    return fieldBox(field, box);
  }

  if (field.kind === 'table') return fieldBox(field, distributionTable(field));

  if (field.kind === 'levels') {
    const input = element('input', {
      type: 'text', value: (value || []).map((item) => toPercentInput(item)).join(', '),
    });
    input.addEventListener('input', () => {
      state.values[field.name] = input.value
        .split(',')
        .map((part) => Number(part.trim().replace(',', '.')) / 100)
        .filter((number) => !Number.isNaN(number));
      schedule();
    });
    return fieldBox(field, input);
  }

  return fieldBox(field, numberInput(field, value, field.step || 1, field.low, field.high));
}

function distributionTable(field) {
  const box = element('div');
  const table = element('table', { class: 'rows' });
  const head = element('tr');
  head.appendChild(element('th', { text: 'Скидка' }));
  head.appendChild(element('th', { text: 'Доля пула' }));
  head.appendChild(element('th', { class: 'tail' }));
  table.appendChild(head);

  const rows = state.values[field.name] || [];
  rows.forEach((row, index) => {
    const line = element('tr');
    ['depth', 'share'].forEach((key) => {
      const cell = element('td');
      const input = element('input', {
        type: 'number', step: key === 'depth' ? 0.5 : 1, min: 0,
        value: toPercentInput(row[key]),
      });
      input.addEventListener('input', () => {
        const raw = Number(input.value.trim().replace(',', '.'));
        rows[index][key] = Number.isNaN(raw) ? 0 : raw / 100;
        updateShareTotal(box, rows);
        schedule();
      });
      cell.appendChild(input);
      line.appendChild(cell);
    });
    const tail = element('td', { class: 'tail' });
    const remove = element('button', { class: 'small', type: 'button', text: '−' });
    remove.addEventListener('click', () => {
      rows.splice(index, 1);
      redrawForm();
      schedule();
    });
    tail.appendChild(remove);
    line.appendChild(tail);
    table.appendChild(line);
  });

  box.appendChild(table);
  const add = element('button', { class: 'small', type: 'button', text: 'добавить строку' });
  add.addEventListener('click', () => {
    rows.push({ depth: 0.01, share: 0 });
    redrawForm();
    schedule();
  });
  box.appendChild(add);
  box.appendChild(element('p', { class: 'total' }));
  updateShareTotal(box, rows);
  return box;
}

function updateShareTotal(box, rows) {
  const total = rows.reduce((sum, row) => sum + (row.share || 0), 0);
  const line = box.querySelector('.total');
  line.textContent = 'Сумма долей: ' + percent(total);
  line.classList.toggle('broken', Math.abs(total - 1) > 1e-6);
}

function redrawForm() {
  const form = document.getElementById('form');
  form.textContent = '';
  state.sections.forEach((section) => {
    const fields = state.fields.filter((field) => field.section === section.key);
    if (!fields.length) return;
    const collapsed = section.key === 'reference';
    const box = element(collapsed ? 'details' : 'section', { class: 'section' });
    box.appendChild(element(collapsed ? 'summary' : 'h2', { text: section.title }));
    fields.forEach((field) => box.appendChild(buildField(field)));
    form.appendChild(box);
  });
  if (state.answer) showProblems(state.answer.errors || []);
}

/* --- обмен с сервером -------------------------------------------------- */

function schedule() {
  // Пауза, чтобы не слать запрос на каждую цифру, и номер запроса, потому что
  // ответы приходят не в том порядке, в котором ушли.
  window.clearTimeout(state.timer);
  state.timer = window.setTimeout(send, 200);
  document.getElementById('result').classList.add('stale');
}

function send() {
  state.request += 1;
  const number = state.request;
  fetch('/api/calculate', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ overrides: state.values, request: number }),
  })
    .then((response) => response.json())
    .then((answer) => {
      if (number < state.shown) return;  // устаревший ответ, выбрасываем
      state.shown = number;
      render(answer);
    })
    .catch(() => showProblems([{ field: '', message: 'сервер не ответил' }]));
}

function render(answer) {
  state.answer = answer;
  showProblems(answer.errors || []);
  if (!answer.ok) return;                 // числа на экране остаются прошлые
  document.getElementById('result').classList.remove('stale');
  showNumbers(answer);
  if (window.drawCharts) window.drawCharts(answer);
}

function showProblems(errors) {
  document.querySelectorAll('.field').forEach((box) => {
    box.classList.remove('broken');
    const shown = box.querySelector('.error');
    if (shown) shown.remove();
  });
  const general = [];
  errors.forEach((error) => {
    const box = document.querySelector('.field[data-field="' + error.field + '"]');
    if (!box) {
      general.push(error.message);
      return;
    }
    box.classList.add('broken');
    box.appendChild(element('small', { class: 'error', text: error.message }));
  });

  const panel = document.getElementById('numbers');
  const old = panel.querySelector('.problems');
  if (old) old.remove();
  if (general.length) {
    const box = element('div', { class: 'problems wide card' });
    box.appendChild(element('strong', { text: 'Не посчитать:' }));
    const list = element('ul');
    general.forEach((message) => list.appendChild(element('li', { text: message })));
    box.appendChild(list);
    panel.prepend(box);
  }
}

/* --- числа ------------------------------------------------------------- */

function card(label, value, note, tone) {
  const box = element('div', { class: 'card' + (tone ? ' ' + tone : '') });
  box.appendChild(element('div', { class: 'label', text: label }));
  box.appendChild(element('div', { class: 'value', text: value }));
  if (note) box.appendChild(element('div', { class: 'note', text: note }));
  return box;
}

function breakevenNote(plan) {
  if (plan.breakeven_payback === null) {
    return 'порога нет: в диапазоне от нуля до единицы окупаемость единицу не пересекает';
  }
  return 'до доли ' + percent(plan.breakeven_payback) + ' акция не уходит в минус';
}

function showNumbers(answer) {
  const plan = answer.plan;
  const effect = plan.effect;
  const panel = document.getElementById('numbers');
  panel.textContent = '';

  panel.appendChild(card(
    'Окупаемость', decimal.format(effect.payback),
    breakevenNote(plan), effect.payback >= 1 ? 'good' : 'bad',
  ));
  panel.appendChild(card(
    'ROI', decimal.format(effect.roi),
    plan.breakeven_roi === null ? 'порога ROI в диапазоне нет'
      : 'ROI выше единицы до доли ' + percent(plan.breakeven_roi),
  ));
  panel.appendChild(card(
    'Средняя эффективная скидка', percent(plan.effective_discount, 2),
    'надбавка к СТП в среднем ' + percent(plan.markup, 2),
  ));
  panel.appendChild(card(
    'Участников', money.format(plan.pool_size + plan.forecast_size),
    'действующих ' + money.format(plan.pool_size)
      + ', прогноз новых ' + money.format(plan.forecast_size),
  ));
  panel.appendChild(card('Затраты акции', millions(effect.costs) + ' ₽'));
  panel.appendChild(card('Дополнительная маржа', millions(effect.margin) + ' ₽'));
  panel.appendChild(card(
    'Дополнительный объем', money.format(Math.round(effect.tons)) + ' т',
    'за ' + decimal.format(plan.months_current) + ' мес. акции у действующих',
  ));
  panel.appendChild(card(
    'Раздача скидки',
    plan.by_volume ? 'глубже крупным' : 'вне зависимости от размера',
    'взвешенная по объему глубина ' + percent(plan.volume_weighted_depth, 2),
    'text',
  ));
}

/* --- сохранение в конфиг ----------------------------------------------- */

function actionsPanel() {
  const box = document.getElementById('actions');
  box.textContent = '';

  const row = element('div', { class: 'row' });
  const ask = element('button', { type: 'button', text: 'Сохранить параметры в конфиг' });
  const make = element('button', { type: 'button', text: 'Собрать книгу' });
  row.appendChild(ask);
  row.appendChild(make);
  box.appendChild(row);

  const said = element('p', { class: 'said' });
  box.appendChild(said);
  make.addEventListener('click', () => buildBook(box, said, make));

  ask.addEventListener('click', () => {
    said.className = 'said';
    said.textContent = 'смотрю, что изменится…';
    fetch('/api/config/preview', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ overrides: state.values }),
    })
      .then((response) => response.json())
      .then((shown) => showDiff(box, said, shown));
  });
}

function showDiff(box, said, shown) {
  box.querySelectorAll('pre, .confirm').forEach((node) => node.remove());
  if (!shown.ok) {
    said.className = 'said broken';
    said.textContent = (shown.errors[0] || {}).message || 'сохранить не получилось';
    return;
  }
  if (!shown.changed.length) {
    said.className = 'said';
    said.textContent = 'в конфиге менять нечего: параметры те же';
    return;
  }

  said.className = 'said';
  said.textContent = 'изменится: ' + shown.changed.join(', ');
  box.appendChild(colouredDiff(shown.diff));

  const confirm = element('div', { class: 'row confirm' });
  const write = element('button', { type: 'button', text: 'Записать' });
  const cancel = element('button', { type: 'button', text: 'Отмена' });
  confirm.appendChild(write);
  confirm.appendChild(cancel);
  box.appendChild(confirm);

  cancel.addEventListener('click', () => {
    box.querySelectorAll('pre, .confirm').forEach((node) => node.remove());
    said.textContent = '';
  });
  write.addEventListener('click', () => {
    write.disabled = true;
    fetch('/api/config/save', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ overrides: state.values }),
    })
      .then((response) => response.json())
      .then((answer) => {
        box.querySelectorAll('pre, .confirm').forEach((node) => node.remove());
        said.className = 'said ' + (answer.ok ? 'done' : 'broken');
        said.textContent = answer.ok
          ? answer.message
          : (answer.errors[0] || {}).message || 'записать не получилось';
        if (answer.ok) start();   // конфиг перечитан, форма берет значения из него
      });
  });
}

function colouredDiff(text) {
  const box = element('pre');
  text.split('\n').forEach((line) => {
    const kind = line.startsWith('+') && !line.startsWith('+++') ? 'add'
      : line.startsWith('-') && !line.startsWith('---') ? 'cut' : '';
    box.appendChild(element('span', { class: kind, text: line + '\n' }));
  });
  return box;
}

/* --- сборка книги ------------------------------------------------------ */

function buildBook(box, said, button) {
  box.querySelectorAll('pre, .confirm, .steps, .done').forEach((n) => n.remove());
  button.disabled = true;
  said.className = 'said';
  said.textContent = 'сохраняю параметры и собираю книгу';
  const steps = element('div', { class: 'steps' });
  box.appendChild(steps);

  fetch('/api/book', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ overrides: state.values }),
  })
    .then((response) => response.json())
    .then((started) => {
      if (!started.job) {
        said.className = 'said broken';
        said.textContent = started.message || 'не запустилось';
        button.disabled = false;
        return;
      }
      poll(started.job, box, said, steps, button);
    });
}

function poll(id, box, said, steps, button) {
  fetch('/api/book/' + id)
    .then((response) => response.json())
    .then((job) => {
      showSteps(steps, job.steps);
      if (job.state === 'running') {
        // Опрашиваем, а не держим соединение: пересчет идет минутами, и
        // сколько именно — заранее неизвестно, поэтому шаги, а не проценты.
        window.setTimeout(() => poll(id, box, said, steps, button), 700);
        return;
      }
      button.disabled = false;
      if (job.state === 'failed') {
        said.className = 'said broken';
        said.textContent = job.error || 'сборка не дошла до конца';
        return;
      }
      showDelivery(box, said, job.result);
    });
}

function showSteps(box, steps) {
  box.textContent = '';
  steps.forEach((step) => {
    const mark = step.state === 'done' ? '✓'
      : step.state === 'failed' ? '×'
      : step.state === 'skipped' ? '–' : '…';
    const line = element('p', { class: 'step ' + step.state });
    line.textContent = mark + ' ' + step.text
      + (step.seconds >= 1 ? ' (' + Math.round(step.seconds) + ' с)' : '');
    box.appendChild(line);
  });
}

function showDelivery(box, said, result) {
  if (!result) return;
  if (result.errors && result.errors.length) {
    said.className = 'said broken';
    said.textContent = result.errors[0].message;
    return;
  }
  said.className = 'said ' + (result.ok ? 'done' : 'broken');
  said.textContent = result.ok
    ? 'книга собрана и сошлась с расчетом'
    : 'книга собрана, но не сошлась — отдавать нельзя';

  const done = element('div', { class: 'done' });
  const where = result.deliverable || result.book;
  done.appendChild(element('p', { class: 'said', text: 'файл: ' + where.path }));
  if (result.deliverable) {
    done.appendChild(element('p', {
      class: 'said',
      text: 'настоящих номеров договоров подставлено: ' + result.deliverable.contracts,
    }));
  }

  done.appendChild(element('p', { class: 'said', text: 'Черновик для пересылки:' }));
  const text = element('pre', { text: result.paragraph });
  done.appendChild(text);
  const copy = element('button', { type: 'button', class: 'small', text: 'скопировать' });
  copy.addEventListener('click', () => {
    navigator.clipboard.writeText(result.paragraph).then(
      () => { copy.textContent = 'скопировано'; },
      () => { copy.textContent = 'не вышло, выделите вручную'; },
    );
  });
  done.appendChild(copy);
  box.appendChild(done);
}

/* --- запуск ------------------------------------------------------------ */

function start() {
  fetch('/api/state')
    .then((response) => response.json())
    .then((payload) => {
      const described = payload.form;
      state.fields = described.fields;
      state.sections = described.sections;
      described.fields.forEach((field) => { state.values[field.name] = field.value; });
      document.getElementById('title').textContent =
        described.campaign.name + ' — ' + described.campaign.product;
      document.getElementById('source').textContent =
        'конфиг ' + described.config_path + ' · данные ' + described.inputs_dir
        + (described.soffice ? '' : ' · LibreOffice не найден, книгу пересчитать будет нечем');
      redrawForm();
      actionsPanel();
      render(payload.answer);
    });
}

start();
