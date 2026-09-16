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
  uploadLimit: 0,      // сколько байт сервер примет за один файл
  dataNote: null,      // что сказать о данных после перерисовки страницы
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
      watch(started.job, steps, (job) => {
        button.disabled = false;
        if (job.state === 'failed') {
          said.className = 'said broken';
          said.textContent = job.error || 'сборка не дошла до конца';
          return;
        }
        showDelivery(box, said, job.result);
      });
    });
}

function watch(id, steps, finish) {
  fetch('/api/jobs/' + id)
    .then((response) => response.json())
    .then((job) => {
      showSteps(steps, job.steps);
      if (job.state === 'running') {
        // Опрашиваем, а не держим соединение: пересчет идет минутами, и
        // сколько именно — заранее неизвестно, поэтому шаги, а не проценты.
        window.setTimeout(() => watch(id, steps, finish), 700);
        return;
      }
      finish(job);
    })
    .catch(() => finish({ state: 'failed', error: 'сервер не ответил' }));
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
  if (result.deliverable) {
    // В том руками не ходят: книга уходит только скачиванием.
    const line = element('p', { class: 'said' });
    line.appendChild(bookLink(result.deliverable.name, 'скачать книгу'));
    done.appendChild(line);
    done.appendChild(element('p', {
      class: 'said',
      text: 'настоящих номеров договоров подставлено: ' + result.deliverable.contracts,
    }));
  } else {
    done.appendChild(element('p', {
      class: 'said', text: 'в готовые книги не попала: ' + result.book.name,
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
  showBooks();
}

/* --- готовые книги ----------------------------------------------------- */

function bookLink(name, text) {
  return element('a', {
    href: '/api/books/' + encodeURIComponent(name), download: name, text: text || name,
  });
}

function showBooks() {
  fetch('/api/books')
    .then((response) => response.json())
    .then((answer) => {
      const box = document.getElementById('books');
      box.textContent = '';
      box.appendChild(element('h2', { text: 'Готовые книги' }));
      if (!answer.books.length) {
        box.appendChild(element('p', {
          class: 'said', text: 'пока нет: книга появится здесь, когда сборка сойдется',
        }));
        return;
      }
      const list = element('ul');
      answer.books.forEach((book) => {
        const item = element('li');
        item.appendChild(bookLink(book.name));
        item.appendChild(element('small', {
          class: 'hint',
          text: new Date(book.modified * 1000).toLocaleString('ru-RU')
            + ' · ' + money.format(Math.max(1, Math.round(book.size / 1024))) + ' КБ',
        }));
        list.appendChild(item);
      });
      box.appendChild(list);
    });
}

/* --- без данных -------------------------------------------------------- */

function showWaiting(waiting) {
  document.getElementById('title').textContent = 'Акция';
  document.getElementById('source').textContent =
    'конфиг ' + waiting.config_path + ' · данные ' + waiting.inputs_dir;
  document.getElementById('actions').hidden = true;
  // Сюда можно прийти и с готовой страницы, когда новая выгрузка еще не сошлась
  // с таблицей отделений: прежние числа посчитаны по другим данным.
  document.getElementById('numbers').textContent = '';
  document.getElementById('charts').textContent = '';
  document.getElementById('result').classList.remove('stale');

  const form = document.getElementById('form');
  form.textContent = '';
  const box = element('div', { class: 'invite' });
  box.appendChild(element('h2', { text: 'Загрузите выгрузку' }));
  box.appendChild(element('p', {
    text: 'Считать пока не по чему. Нужны выгрузка транзакций и договоров, '
      + 'уведомление о СТП и таблица отделений: выгрузку и уведомление загружают '
      + 'в блоке «Данные» ниже, таблицу отделений заполняют там же после загрузки.',
  }));
  const list = (title, items, tone) => {
    if (!items.length) return;
    box.appendChild(element('p', { class: tone || '', text: title }));
    const ul = element('ul');
    items.forEach((item) => ul.appendChild(element('li', { class: tone || '', text: item })));
    box.appendChild(ul);
  };
  list('Не хватает файлов:', waiting.missing);
  list('Данные есть, но не годятся:', waiting.problems, 'broken');
  form.appendChild(box);
}

/* --- данные: загрузка выгрузки и таблица отделений ------------------------ */

function showData(payload) {
  const box = document.getElementById('data');
  box.hidden = !payload.upload;
  box.textContent = '';
  if (!payload.upload) return;
  box.appendChild(element('h2', { text: 'Данные' }));

  // В том руками не ходят: выгрузка попадает туда только отсюда.
  const input = element('input', { type: 'file', multiple: '', accept: '.xlsx,.docx' });
  const zone = element('label', { class: 'drop' });
  zone.appendChild(element('span', {
    text: 'Перетащите сюда выгрузку .xlsx и уведомление о СТП .docx — или нажмите, '
      + 'чтобы выбрать. Уведомление можно не загружать: без него в книге не будет '
      + 'трассовых ставок.',
  }));
  zone.appendChild(input);
  box.appendChild(zone);

  const said = element('p', { class: 'said' });
  const steps = element('div', { class: 'steps' });
  box.appendChild(said);
  box.appendChild(steps);
  if (state.dataNote) {
    said.className = 'said ' + (state.dataNote.tone || '');
    said.textContent = state.dataNote.text;
  }

  input.addEventListener('change', () => upload(Array.from(input.files), zone, said, steps));
  zone.addEventListener('dragover', (event) => {
    event.preventDefault();
    zone.classList.add('over');
  });
  zone.addEventListener('dragleave', () => zone.classList.remove('over'));
  zone.addEventListener('drop', (event) => {
    event.preventDefault();
    zone.classList.remove('over');
    upload(Array.from(event.dataTransfer.files), zone, said, steps);
  });

  showBranches(box);
}

function refuseFiles(files) {
  const bad = files.filter((file) => !/\.(xlsx|docx)$/i.test(file.name));
  if (bad.length) {
    return '«' + bad[0].name + '» не подходит: нужна выгрузка .xlsx или уведомление .docx';
  }
  const exports = files.filter((file) => /\.xlsx$/i.test(file.name));
  if (exports.length !== 1) {
    return exports.length ? 'выгрузка одна — выберите один файл .xlsx'
      : 'нужна выгрузка .xlsx; уведомление загружают вместе с ней';
  }
  if (files.filter((file) => /\.docx$/i.test(file.name)).length > 1) {
    return 'уведомление одно — выберите один файл .docx';
  }
  const large = files.find((file) => state.uploadLimit && file.size > state.uploadLimit);
  if (large) return '«' + large.name + '» слишком большой — это не похоже на выгрузку';
  return null;
}

async function upload(files, zone, said, steps) {
  if (!files.length) return;
  steps.textContent = '';
  state.dataNote = null;
  const refusal = refuseFiles(files);
  if (refusal) {
    said.className = 'said broken';
    said.textContent = refusal;
    return;
  }
  zone.classList.add('busy');
  const fail = (message) => {
    zone.classList.remove('busy');
    said.className = 'said broken';
    said.textContent = message;
  };

  // По файлу на запрос, сырым телом. Имя идет кодированным: кириллица
  // в заголовке как есть не проходит.
  for (const file of files) {
    said.className = 'said';
    said.textContent = 'загружаю «' + file.name + '»';
    let answer;
    try {
      const response = await fetch('/api/upload', {
        method: 'POST',
        headers: {
          'Content-Type': 'application/octet-stream',
          'X-File-Name': encodeURIComponent(file.name),
        },
        body: file,
      });
      answer = await response.json();
    } catch (error) {
      answer = { ok: false, message: 'сервер не ответил' };
    }
    if (!answer.ok) {
      fail(answer.message || 'файл не принят');
      return;
    }
  }

  said.textContent = 'обрабатываю выгрузку';
  let started;
  try {
    const response = await fetch('/api/prepare', {
      method: 'POST', headers: { 'Content-Type': 'application/json' }, body: '{}',
    });
    started = await response.json();
  } catch (error) {
    started = { ok: false, message: 'сервер не ответил' };
  }
  if (!started.job) {
    fail(started.message || 'обработка не запустилась');
    return;
  }
  watch(started.job, steps, (job) => {
    zone.classList.remove('busy');
    if (job.state === 'failed') {
      // Старые данные на месте: обработка заменяет их только после проверки.
      fail((job.error || 'обработка не дошла до конца') + ' — прежние данные остались на месте');
      return;
    }
    state.dataNote = { tone: 'done', text: loadedText(job.result) };
    start();
  });
}

function loadedText(result) {
  const parts = [
    'выгрузка загружена: договоров ' + money.format(result.contracts)
      + ', транзакций ' + money.format(result.transactions)
      + ', отделений ' + money.format(result.branches),
    result.notice ? 'шкала СТП из уведомления' : 'уведомления нет, трассовых ставок в книге не будет',
  ];
  (result.warnings || []).forEach((warning) => parts.push(warning));
  if (!result.ready) parts.push('считать пока нельзя — что не так, видно выше');
  return parts.join('; ');
}

function showBranches(box) {
  fetch('/api/branches')
    .then((response) => response.json())
    .then((described) => {
      if (!described.ok) return;
      const missing = described.missing.length;
      const details = element('details', { class: 'branches' });
      details.open = missing > 0;
      details.appendChild(element('summary', {
        text: 'Таблица отделений' + (missing ? ' — не заполнено: ' + missing : ''),
      }));
      details.appendChild(element('p', {
        class: 'said',
        text: 'К какому региону прогноза маржи относится каждое отделение из выгрузки. '
          + 'По названию пары не подбираются: если не уверены, уточните, прежде чем сохранять.',
      }));

      const table = element('table', { class: 'rows' });
      const head = element('tr');
      head.appendChild(element('th', { text: 'Отделение' }));
      head.appendChild(element('th', { text: 'Регион прогноза маржи' }));
      table.appendChild(head);
      const selects = {};
      described.branches.forEach((row) => {
        const line = element('tr', { 'data-branch': row.branch });
        line.appendChild(element('td', { text: row.branch }));
        const select = element('select');
        select.appendChild(element('option', { value: '', text: '— не выбран —' }));
        described.regions.forEach((region) => {
          const option = element('option', { value: region, text: region });
          option.selected = region === row.region;
          select.appendChild(option);
        });
        selects[row.branch] = select;
        const cell = element('td');
        cell.appendChild(select);
        if (row.region && !row.known) {
          cell.appendChild(element('small', {
            class: 'error', text: 'записан «' + row.region + '», а в прогнозе маржи такого региона нет',
          }));
        }
        line.appendChild(cell);
        table.appendChild(line);
      });
      details.appendChild(table);

      const said = element('p', { class: 'said' });
      const write = element('button', { type: 'button', text: 'Сохранить таблицу отделений' });
      details.appendChild(write);
      details.appendChild(said);
      write.addEventListener('click', () => {
        const pairs = {};
        Object.entries(selects).forEach(([branch, select]) => { pairs[branch] = select.value; });
        write.disabled = true;
        fetch('/api/branches', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ pairs: pairs }),
        })
          .then((response) => response.json())
          .then((answer) => {
            write.disabled = false;
            if (!answer.ok) {
              said.className = 'said broken';
              said.textContent = answer.message
                || (answer.errors || []).map((e) => (e.branch ? e.branch + ': ' : '') + e.message).join('; ');
              return;
            }
            state.dataNote = {
              tone: answer.ready ? 'done' : '',
              text: answer.ready ? 'таблица отделений сохранена, можно считать'
                : 'таблица отделений сохранена, но считать пока нельзя — что не так, видно выше',
            };
            start();
          })
          .catch(() => {
            write.disabled = false;
            said.className = 'said broken';
            said.textContent = 'сервер не ответил';
          });
      });
      box.appendChild(details);
    });
}

/* --- запуск ------------------------------------------------------------ */

function start() {
  fetch('/api/state')
    .then((response) => response.json())
    .then((payload) => {
      showBooks();
      // Версию задает тег при сборке образа; по ней видно, какой образ запущен.
      document.getElementById('version').textContent = /^\d/.test(payload.version)
        ? 'версия ' + payload.version : payload.version;
      state.uploadLimit = payload.upload_limit;
      showData(payload);
      if (!payload.ready) {
        showWaiting(payload.waiting);
        return;
      }
      document.getElementById('actions').hidden = false;
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
