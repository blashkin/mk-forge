/* Три графика, нарисованные руками.
 *
 * Библиотеку взять неоткуда: страница не ходит наружу, а чужой файл рядом
 * с числами по реальному пулу ничем не лучше. Зато и рисовать здесь нечего —
 * кривая, две колонки и полосы.
 *
 * Считать здесь тоже нечего: все числа приходят посчитанными. Доли от итога —
 * единственная арифметика, и она нужна для длины полосы, а не для ответа.
 */

'use strict';

const NS = 'http://www.w3.org/2000/svg';
const INK = '#1b1b1b';
const MUTED = '#6b6b6b';
const LINE = '#dcdcdc';
const DEEP = '#1f5f8b';
const SHALLOW = '#9dc3dc';
const WARN = '#9a3412';
const GOOD = '#1f6f43';

function node(tag, attrs) {
  const made = document.createElementNS(NS, tag);
  Object.entries(attrs || {}).forEach(([name, value]) => {
    if (value !== null && value !== undefined) made.setAttribute(name, String(value));
  });
  return made;
}

function label(x, y, text, attrs) {
  const made = node('text', Object.assign({
    x: x, y: y, fill: MUTED, 'font-size': 11, 'font-family': 'inherit',
  }, attrs || {}));
  made.textContent = text;
  return made;
}

function frame(title, caption) {
  const box = document.createElement('div');
  box.className = 'chart';
  const head = document.createElement('h3');
  head.textContent = title;
  box.appendChild(head);
  if (caption) {
    const line = document.createElement('p');
    line.className = 'caption';
    line.textContent = caption;
    box.appendChild(line);
  }
  return box;
}

function legend(items) {
  const box = document.createElement('div');
  box.className = 'legend';
  items.forEach(([color, text]) => {
    const item = document.createElement('span');
    const mark = document.createElement('i');
    mark.style.background = color;
    item.appendChild(mark);
    item.appendChild(document.createTextNode(text));
    box.appendChild(item);
  });
  return box;
}

/* --- 1. Окупаемость по доле объема без акции ---------------------------- */

function paybackChart(data) {
  const W = 720, H = 300, L = 46, R = 18, T = 16, B = 40;
  const plotW = W - L - R, plotH = H - T - B;
  const usable = data.points.filter((point) => point.costs > 0);

  const values = usable.map((point) => point.payback)
    .concat(usable.map((point) => point.roi)).concat([1]);
  const lo = Math.min.apply(null, values);
  const hi = Math.max.apply(null, values);
  const pad = (hi - lo) * 0.12 || 0.5;
  const low = lo - pad, high = hi + pad;

  const x = (share) => L + share * plotW;
  const y = (value) => T + plotH - ((value - low) / (high - low)) * plotH;

  const svg = node('svg', { viewBox: `0 0 ${W} ${H}`, role: 'img' });
  const title = node('title');
  title.textContent = 'Окупаемость и ROI как функция доли объема без акции';
  svg.appendChild(title);

  // Оси.
  svg.appendChild(node('line', { x1: L, y1: T + plotH, x2: L + plotW, y2: T + plotH, stroke: LINE }));
  svg.appendChild(node('line', { x1: L, y1: T, x2: L, y2: T + plotH, stroke: LINE }));
  [0, 0.25, 0.5, 0.75, 1].forEach((share) => {
    svg.appendChild(node('line', {
      x1: x(share), y1: T + plotH, x2: x(share), y2: T + plotH + 4, stroke: LINE,
    }));
    svg.appendChild(label(x(share), T + plotH + 17, percent(share, 0), {
      'text-anchor': 'middle',
    }));
  });
  [low, (low + high) / 2, high].forEach((value) => {
    svg.appendChild(label(L - 6, y(value) + 4, value.toFixed(1).replace('.', ','), {
      'text-anchor': 'end',
    }));
  });

  // Единица: ниже нее акция не окупается.
  svg.appendChild(node('line', {
    x1: L, y1: y(1), x2: L + plotW, y2: y(1),
    stroke: MUTED, 'stroke-dasharray': '4 4',
  }));
  svg.appendChild(label(L + plotW, y(1) - 6, 'не уходим в минус', { 'text-anchor': 'end' }));

  const path = (key, color, width) => {
    const points = usable.map((point) => `${x(point.share)},${y(point[key])}`);
    svg.appendChild(node('polyline', {
      points: points.join(' '), fill: 'none', stroke: color, 'stroke-width': width,
    }));
  };
  path('roi', SHALLOW, 1.5);
  path('payback', DEEP, 2);

  // Пороги. Их отсутствие — тоже новость, и говорится словами под графиком.
  const mark = (share, color, text) => {
    if (share === null || share === undefined) return;
    svg.appendChild(node('line', {
      x1: x(share), y1: T, x2: x(share), y2: T + plotH,
      stroke: color, 'stroke-dasharray': '3 3',
    }));
    svg.appendChild(label(x(share) + 4, T + 12, text, { fill: color }));
  };
  mark(data.breakeven_payback, WARN, 'порог ' + percent(data.breakeven_payback));
  mark(data.breakeven_roi, GOOD, 'ROI = 1 при ' + percent(data.breakeven_roi));

  // Где мы сейчас.
  const now = usable.filter((point) => point.share === data.current_share)[0];
  if (now) {
    svg.appendChild(node('circle', {
      cx: x(now.share), cy: y(now.payback), r: 4, fill: DEEP,
    }));
    svg.appendChild(label(
      x(now.share) + 8, y(now.payback) - 8,
      'сейчас ' + now.payback.toFixed(2).replace('.', ','),
      { fill: INK, 'font-weight': 600 },
    ));
  }

  const box = frame(
    'Окупаемость по доле объема без акции',
    'Единственное допущение, которое решает знак результата. Порог важнее самого '
    + 'числа: он показывает, где допущение перестает держать акцию выше нуля.',
  );
  box.appendChild(svg);
  box.appendChild(legend([[DEEP, 'окупаемость'], [SHALLOW, 'ROI']]));
  const verdict = document.createElement('p');
  verdict.className = 'caption';
  verdict.textContent = thresholdWords(data);
  box.appendChild(verdict);
  return box;
}

function thresholdWords(data) {
  if (data.breakeven_payback !== null && data.breakeven_payback !== undefined) {
    return 'Акция не уходит в минус, пока без нее сохранилось бы не больше '
      + percent(data.breakeven_payback) + ' объема.';
  }
  // Порога нет — но это две противоположные новости, и различать их обязательно.
  const ends = data.ends;
  if (ends.payback_at_0 >= 1 && ends.payback_at_1 >= 1) {
    return 'Окупаемость выше единицы при любой доле объема без акции.';
  }
  if (ends.payback_at_0 < 1 && ends.payback_at_1 < 1) {
    return 'Окупаемость ниже единицы при любой доле: акция не сходится ни при '
      + 'каком допущении об объеме.';
  }
  return 'Порог вне диапазона от нуля до единицы.';
}

/* --- 2. Из чего собраны затраты и что возвращается ---------------------- */

function moneyChart(data) {
  const W = 720, H = 260, T = 16, B = 34;
  const plotH = H - T - B;
  const top = Math.max(data.costs.total, data.returns.total) || 1;
  const svg = node('svg', { viewBox: `0 0 ${W} ${H}`, role: 'img' });
  const title = node('title');
  title.textContent = 'Затраты акции и то, что возвращается';
  svg.appendChild(title);

  const column = (x, parts, caption, total) => {
    let offset = 0;
    parts.forEach(([value, color, name]) => {
      if (value <= 0) return;
      const height = (value / top) * plotH;
      const y = T + plotH - offset - height;
      svg.appendChild(node('rect', {
        x: x, y: y, width: 150, height: height, fill: color, rx: 2,
      }));
      if (height > 15) {
        svg.appendChild(label(x + 160, y + height / 2 + 4, name + ' — ' + millions(value), {
          fill: INK,
        }));
      }
      offset += height;
    });
    svg.appendChild(label(x + 75, T + plotH + 16, caption, {
      'text-anchor': 'middle', fill: INK, 'font-weight': 600,
    }));
    svg.appendChild(label(x + 75, T + plotH + 30, millions(total) + ' ₽', {
      'text-anchor': 'middle',
    }));
  };

  column(10, [
    [data.costs.discount, DEEP, 'скидка'],
    [data.costs.opex, SHALLOW, 'OPEX'],
    [data.costs.comms, '#c8dced', 'коммуникация'],
  ], 'затраты', data.costs.total);

  column(380, [
    [data.returns.gross_margin, GOOD, 'валовая маржа'],
    [data.returns.service_fee, '#9ecab1', 'сервисный сбор'],
  ], 'возвращается', data.returns.total);

  const box = frame(
    'Из чего собраны затраты и что возвращается',
    'Считается по разнице сценариев: окупаемость — это отношение приростов, '
    + 'а не итогов.',
  );
  box.appendChild(svg);
  const line = document.createElement('p');
  line.className = 'caption';
  line.textContent = 'На рубль затрат возвращается '
    + data.payback.toFixed(2).replace('.', ',') + ' руб., из них сверх самого рубля — '
    + data.roi.toFixed(2).replace('.', ',') + ' руб.';
  box.appendChild(line);
  return box;
}

/* --- 3. Участники по скидкам ------------------------------------------- */

function groupsChart(data) {
  const rows = data.groups;
  const totals = data.totals;
  const W = 720, L = 54, R = 150, T = 18;
  const bar = 11, gap = 3, block = bar * 3 + gap * 2 + 16;
  const H = T + rows.length * block + 10;
  const plotW = W - L - R;

  const shares = [];
  rows.forEach((row) => {
    shares.push((row.contracts + row.forecast_contracts)
      / (totals.contracts + totals.forecast_contracts));
    shares.push(row.tons / totals.tons);
    shares.push(row.costs / totals.costs);
  });
  const top = Math.max.apply(null, shares) || 1;
  const width = (share) => Math.max((share / top) * plotW, 1);

  const svg = node('svg', { viewBox: `0 0 ${W} ${H}`, role: 'img' });
  const title = node('title');
  title.textContent = 'Участники по скидкам и вклад каждой группы в объем и затраты';
  svg.appendChild(title);

  rows.forEach((row, index) => {
    const y = T + index * block;
    svg.appendChild(label(L - 8, y + 20, percent(row.depth, 0), {
      'text-anchor': 'end', fill: INK, 'font-weight': 600, 'font-size': 13,
    }));

    // Договоры: факт и прогноз одной полосой, но разной заливкой.
    const people = totals.contracts + totals.forecast_contracts;
    const own = width(row.contracts / people);
    const forecast = width((row.contracts + row.forecast_contracts) / people) - own;
    svg.appendChild(node('rect', { x: L, y: y, width: own, height: bar, fill: DEEP, rx: 1 }));
    svg.appendChild(node('rect', {
      x: L + own, y: y, width: forecast, height: bar, fill: SHALLOW, rx: 1,
    }));
    svg.appendChild(label(L + own + forecast + 8, y + bar - 1,
      money.format(Math.round(row.contracts + row.forecast_contracts)) + ' участников'));

    svg.appendChild(node('rect', {
      x: L, y: y + bar + gap, width: width(row.tons / totals.tons), height: bar,
      fill: '#7aa7c2', rx: 1,
    }));
    svg.appendChild(label(L + width(row.tons / totals.tons) + 8, y + bar * 2 + gap - 1,
      percent(row.tons / totals.tons) + ' объема'));

    svg.appendChild(node('rect', {
      x: L, y: y + (bar + gap) * 2, width: width(row.costs / totals.costs), height: bar,
      fill: '#b98b6a', rx: 1,
    }));
    svg.appendChild(label(L + width(row.costs / totals.costs) + 8, y + bar * 3 + gap * 2 - 1,
      percent(row.costs / totals.costs) + ' затрат'));
  });

  const box = frame(
    'Участники по скидкам',
    'Одна акция, а не пять сценариев: план расходится по скидкам, и доля пула, '
    + 'доля объема и доля затрат у группы — три разные величины.',
  );
  box.appendChild(svg);
  box.appendChild(legend([
    [DEEP, 'действующие'], [SHALLOW, 'прогноз новых'],
    ['#7aa7c2', 'доля объема'], ['#b98b6a', 'доля затрат'],
  ]));
  return box;
}

/* --- сборка ------------------------------------------------------------ */

window.drawCharts = function drawCharts(answer) {
  const panel = document.getElementById('charts');
  panel.textContent = '';
  panel.appendChild(paybackChart(answer.charts.payback));
  panel.appendChild(groupsChart(answer.charts.groups));
  panel.appendChild(moneyChart(answer.charts.money));
};
