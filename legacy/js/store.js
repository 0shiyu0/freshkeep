/*!
 * 鲜度 FreshKeep · 数据层
 * 纯前端、零依赖，数据全部保存在浏览器 localStorage。
 * 设计：items 只存"当前状态"，logs 存"变更流水"，
 *      库存数量是唯一真值，流水可回滚（撤销）也可用于趋势统计。
 */
(function (global) {
  'use strict';

  var STORAGE_KEY = 'freshkeep.v1';
  var SCHEMA_VERSION = 1;
  var DAY = 86400000;

  var DEFAULT_SETTINGS = {
    expiryWarnDays: 7,    // 多久之内到期算"临期"
    expiryUrgentDays: 3   // 多久之内到期算"紧急"
  };

  var CATEGORIES = ['蔬菜', '水果', '肉禽蛋', '水产', '乳品', '主食粮油', '调料', '冷冻', '饮品', '零食', '其他'];

  var UNIT_LIST = ['个', '根', '把', '颗', '块', '袋', '盒', '瓶', '罐', '包', '斤', 'g', 'kg', 'ml', 'L'];

  /* ================= 基础工具 ================= */

  function now() { return Date.now(); }

  function uid() {
    try {
      if (global.crypto && typeof global.crypto.randomUUID === 'function') {
        return global.crypto.randomUUID();
      }
    } catch (e) { /* ignore */ }
    return 'id-' + now().toString(36) + '-' + Math.random().toString(36).slice(2, 9);
  }

  function pad(n) { return (n < 10 ? '0' : '') + n; }

  function toISO(d) {
    return d.getFullYear() + '-' + pad(d.getMonth() + 1) + '-' + pad(d.getDate());
  }

  function todayISO() { return toISO(new Date()); }

  function parseISO(s) {
    if (typeof s !== 'string') return null;
    var m = /^(\d{4})-(\d{2})-(\d{2})$/.exec(s);
    if (!m) return null;
    var d = new Date(+m[1], +m[2] - 1, +m[3]);
    if (isNaN(d.getTime())) return null;
    if (d.getMonth() !== +m[2] - 1) return null; // 拒绝 2026-02-31 这类
    return d;
  }

  function startOfDay(d) { return new Date(d.getFullYear(), d.getMonth(), d.getDate()); }

  function addDays(days) {
    var d = new Date();
    d.setDate(d.getDate() + Number(days || 0));
    return toISO(d);
  }

  /** 距离到期还有几天：正数未到期，0 今天到期，负数已过期；无保质期返回 null */
  function daysLeft(expiry) {
    var d = parseISO(expiry);
    if (!d) return null;
    return Math.round((startOfDay(d) - startOfDay(new Date())) / DAY);
  }

  function round2(n) { return Math.round(n * 100) / 100; }

  function num(v, fallback) {
    var n = typeof v === 'number' ? v : parseFloat(v);
    if (!isFinite(n)) return fallback === undefined ? 0 : fallback;
    return n;
  }

  function clampInt(v, min, max, fallback) {
    var n = Math.round(num(v, fallback));
    if (n < min) n = min;
    if (n > max) n = max;
    return n;
  }

  function str(v, max) {
    return String(v == null ? '' : v).trim().slice(0, max || 40);
  }

  /* ================= 状态 ================= */

  var state = null;

  function blank() {
    return {
      version: SCHEMA_VERSION,
      items: [],
      logs: [],
      settings: Object.assign({}, DEFAULT_SETTINGS),
      createdAt: now(),
      updatedAt: now()
    };
  }

  function normalizeItem(raw) {
    var it = raw && typeof raw === 'object' ? raw : {};
    var qty = round2(num(it.qty, 0));
    if (qty < 0) qty = 0;
    return {
      id: it.id || uid(),
      name: str(it.name, 40),
      emoji: str(it.emoji, 8) || '🍽️',
      category: CATEGORIES.indexOf(it.category) >= 0 ? it.category : (str(it.category, 12) || '其他'),
      qty: qty,
      unit: str(it.unit, 8) || '个',
      expiry: parseISO(it.expiry) ? it.expiry : '',
      threshold: Math.max(0, round2(num(it.threshold, 1))),
      note: str(it.note, 80),
      createdAt: num(it.createdAt, now()),
      updatedAt: num(it.updatedAt, now())
    };
  }

  var LOG_TYPES = ['use', 'restock', 'waste'];

  function normalizeLog(raw) {
    var l = raw && typeof raw === 'object' ? raw : null;
    if (!l || !l.itemId) return null;
    var type = LOG_TYPES.indexOf(l.type) >= 0 ? l.type : 'use';
    var amount = Math.abs(round2(num(l.amount, 0)));
    if (!amount) return null;
    var delta = type === 'restock' ? amount : -amount;
    return {
      id: l.id || uid(),
      itemId: String(l.itemId),
      name: str(l.name, 40),
      emoji: str(l.emoji, 8) || '🍽️',
      unit: str(l.unit, 8) || '个',
      type: type,
      amount: amount,
      delta: delta,
      at: num(l.at, now()),
      note: str(l.note, 80)
    };
  }

  function normalizeState(raw) {
    var s = blank();
    if (!raw || typeof raw !== 'object') return s;

    if (Array.isArray(raw.items)) {
      s.items = raw.items.map(normalizeItem).filter(function (i) { return i.name; });
    }
    if (Array.isArray(raw.logs)) {
      s.logs = raw.logs.map(normalizeLog).filter(Boolean);
      s.logs.sort(function (a, b) { return a.at - b.at; });
      if (s.logs.length > 3000) s.logs = s.logs.slice(-3000);
    }
    if (raw.settings && typeof raw.settings === 'object') {
      s.settings.expiryWarnDays = clampInt(raw.settings.expiryWarnDays, 1, 60, DEFAULT_SETTINGS.expiryWarnDays);
      s.settings.expiryUrgentDays = clampInt(raw.settings.expiryUrgentDays, 1, 30, DEFAULT_SETTINGS.expiryUrgentDays);
    }
    s.createdAt = num(raw.createdAt, s.createdAt);
    return s;
  }

  function load() {
    var raw = null;
    try {
      raw = JSON.parse(global.localStorage.getItem(STORAGE_KEY) || 'null');
    } catch (e) {
      raw = null;
    }
    state = normalizeState(raw);
    if (!raw) flush(); // 首次使用写入空结构，确保 key 存在
    return state;
  }

  function flush() {
    state.updatedAt = now();
    try {
      global.localStorage.setItem(STORAGE_KEY, JSON.stringify(state));
      return true;
    } catch (e) {
      // 配额超限 / 隐私模式：数据仍在内存里，仅本次会话有效
      return false;
    }
  }

  function save() { return flush(); }

  /* ================= 查询 ================= */

  function getState() { return state; }
  function items() { return state.items.slice(); }
  function getItem(id) {
    for (var i = 0; i < state.items.length; i++) {
      if (state.items[i].id === id) return state.items[i];
    }
    return null;
  }
  function logs() { return state.logs.slice().sort(function (a, b) { return b.at - a.at; }); }
  function logsOf(itemId) {
    return state.logs.filter(function (l) { return l.itemId === itemId; })
      .sort(function (a, b) { return b.at - a.at; });
  }
  function settings() { return state.settings; }

  /** 临期 / 已过期清单（不含无保质期的） */
  function expiring() {
    var warn = state.settings.expiryWarnDays;
    var out = [];
    state.items.forEach(function (it) {
      var d = daysLeft(it.expiry);
      if (d === null) return;
      if (d <= warn) out.push({ item: it, days: d });
    });
    out.sort(function (a, b) { return a.days - b.days; });
    return out;
  }

  function lowStock() {
    return state.items.filter(function (it) { return it.qty <= it.threshold; });
  }

  function isLow(it) { return it.qty <= it.threshold; }

  /* ================= 变更 ================= */

  function pushLog(item, amount, type, note, at) {
    var log = normalizeLog({
      itemId: item.id,
      name: item.name,
      emoji: item.emoji,
      unit: item.unit,
      type: type,
      amount: amount,
      at: at || now(),
      note: note
    });
    if (!log) return null;
    state.logs.push(log);
    if (state.logs.length > 3000) state.logs = state.logs.slice(-3000);
    return log;
  }

  function addItem(input) {
    var item = normalizeItem(Object.assign({}, input, {
      id: uid(),
      createdAt: now(),
      updatedAt: now()
    }));
    if (!item.name) return null;
    state.items.unshift(item);
    if (item.qty > 0) pushLog(item, item.qty, 'restock', '初始入库');
    save();
    return item;
  }

  function updateItem(id, patch) {
    var item = getItem(id);
    if (!item) return null;
    var merged = normalizeItem(Object.assign({}, item, patch, { id: item.id, createdAt: item.createdAt }));
    Object.keys(merged).forEach(function (k) { item[k] = merged[k]; });
    item.updatedAt = now();
    save();
    return item;
  }

  function removeItem(id) {
    var idx = -1;
    for (var i = 0; i < state.items.length; i++) {
      if (state.items[i].id === id) { idx = i; break; }
    }
    if (idx < 0) return false;
    state.items.splice(idx, 1);
    // 流水保留：统计与历史仍需要它，日志里已存名称/单位快照
    save();
    return true;
  }

  /**
   * 记录一次变动并扣减 / 增加库存
   * @param {string} id
   * @param {number} amount 正数
   * @param {'use'|'restock'|'waste'} type
   * @param {string} note
   * @returns {{item:object, delta:number, log:object}|null}
   */
  function consume(id, amount, type, note) {
    var item = getItem(id);
    if (!item) return null;
    var amt = Math.abs(round2(num(amount, 0)));
    if (!amt) return null;
    type = LOG_TYPES.indexOf(type) >= 0 ? type : 'use';

    var before = item.qty;
    var after = type === 'restock' ? round2(before + amt) : round2(Math.max(0, before - amt));
    var delta = round2(after - before);
    if (delta === 0) return { item: item, delta: 0, log: null };

    item.qty = after;
    item.updatedAt = now();
    var log = pushLog(item, Math.abs(delta), type, note);
    save();
    return { item: item, delta: delta, log: log };
  }

  /** 撤销一条流水：把它对库存的影响反向还原 */
  function undoLog(logId) {
    var idx = -1;
    for (var i = 0; i < state.logs.length; i++) {
      if (state.logs[i].id === logId) { idx = i; break; }
    }
    if (idx < 0) return null;
    var log = state.logs[idx];
    var item = getItem(log.itemId);
    if (item) {
      item.qty = round2(Math.max(0, item.qty - log.delta));
      item.updatedAt = now();
    }
    state.logs.splice(idx, 1);
    save();
    return log;
  }

  function saveSettings(patch) {
    if (patch && typeof patch === 'object') {
      if (patch.expiryWarnDays !== undefined) {
        state.settings.expiryWarnDays = clampInt(patch.expiryWarnDays, 1, 60, DEFAULT_SETTINGS.expiryWarnDays);
      }
      if (patch.expiryUrgentDays !== undefined) {
        state.settings.expiryUrgentDays = clampInt(patch.expiryUrgentDays, 1, 30, DEFAULT_SETTINGS.expiryUrgentDays);
      }
    }
    save();
    return state.settings;
  }

  /* ================= 统计 ================= */

  /**
   * 近 N 天消耗统计
   * @param {number} days
   */
  function stats(days) {
    days = clampInt(days, 1, 365, 7);
    var end = startOfDay(new Date());
    var series = [];
    var buckets = {};
    for (var i = days - 1; i >= 0; i--) {
      var key = toISO(new Date(end.getTime() - i * DAY));
      var b = { date: key, uses: 0, amount: 0, restocks: 0, waste: 0 };
      buckets[key] = b;
      series.push(b);
    }

    var topMap = {};
    var totalUse = 0, useCount = 0, wasteCount = 0, restockCount = 0;

    state.logs.forEach(function (l) {
      var key = toISO(new Date(l.at));
      var b = buckets[key];
      if (!b) return;
      if (l.type === 'use') {
        b.uses += 1;
        b.amount = round2(b.amount + l.amount);
        totalUse = round2(totalUse + l.amount);
        useCount += 1;
        var t = topMap[l.itemId];
        if (!t) {
          t = topMap[l.itemId] = { itemId: l.itemId, name: l.name, emoji: l.emoji, unit: l.unit, count: 0, amount: 0 };
        }
        t.count += 1;
        t.amount = round2(t.amount + l.amount);
      } else if (l.type === 'waste') {
        b.waste += 1;
        wasteCount += 1;
      } else if (l.type === 'restock') {
        b.restocks += 1;
        restockCount += 1;
      }
    });

    var top = Object.keys(topMap).map(function (k) { return topMap[k]; })
      .sort(function (a, b) { return b.count - a.count || b.amount - a.amount; })
      .slice(0, 5);

    return {
      days: days,
      series: series,
      top: top,
      totalUse: totalUse,
      useCount: useCount,
      wasteCount: wasteCount,
      restockCount: restockCount,
      avgPerDay: Math.round((useCount / days) * 10) / 10
    };
  }

  /* ================= 导入 / 导出 ================= */

  function exportJSON() { return JSON.stringify(state, null, 2); }

  function importJSON(text) {
    var raw;
    try {
      raw = JSON.parse(text);
    } catch (e) {
      return { ok: false, error: '不是合法的 JSON 文件' };
    }
    if (!raw || !Array.isArray(raw.items)) {
      return { ok: false, error: '文件结构不符合预期（缺少 items 数组）' };
    }
    var next = normalizeState(raw);
    if (!next.items.length) return { ok: false, error: '文件里没有可用的食材记录' };
    state = next;
    save();
    return { ok: true, count: state.items.length, logs: state.logs.length };
  }

  function exportCSV() {
    var head = ['类型', '食材', '数量', '单位', '时间', '备注'];
    var label = { use: '消耗', restock: '补货', waste: '丢弃' };
    var rows = [head.join(',')];
    logs().forEach(function (l) {
      var d = new Date(l.at);
      rows.push([
        label[l.type] || l.type,
        l.name,
        l.amount,
        l.unit,
        d.getFullYear() + '-' + pad(d.getMonth() + 1) + '-' + pad(d.getDate()) + ' ' + pad(d.getHours()) + ':' + pad(d.getMinutes()),
        l.note || ''
      ].map(csvCell).join(','));
    });
    return '\ufeff' + rows.join('\r\n');
  }

  function csvCell(v) {
    var s = String(v == null ? '' : v);
    return /[",\r\n]/.test(s) ? '"' + s.replace(/"/g, '""') + '"' : s;
  }

  function clearAll() {
    state = blank();
    save();
  }

  function usage() {
    try {
      var s = JSON.stringify(state);
      return { bytes: new Blob([s]).size, chars: s.length, items: state.items.length, logs: state.logs.length };
    } catch (e) {
      return { bytes: 0, chars: 0, items: state.items.length, logs: state.logs.length };
    }
  }

  /* ================= 示例数据 ================= */

  function seedDemo() {
    var preset = [
      { name: '牛奶', emoji: '🥛', category: '乳品', qty: 2, unit: '盒', shelf: 3, threshold: 1 },
      { name: '鸡蛋', emoji: '🥚', category: '肉禽蛋', qty: 6, unit: '个', shelf: 18, threshold: 4 },
      { name: '西红柿', emoji: '🍅', category: '蔬菜', qty: 3, unit: '个', shelf: 4, threshold: 2 },
      { name: '小青菜', emoji: '🥬', category: '蔬菜', qty: 1, unit: '把', shelf: 2, threshold: 1 },
      { name: '鸡胸肉', emoji: '🍗', category: '肉禽蛋', qty: 2, unit: '袋', shelf: 60, threshold: 1 },
      { name: '鲈鱼', emoji: '🐟', category: '水产', qty: 1, unit: '条', shelf: -1, threshold: 1 },
      { name: '酸奶', emoji: '🥣', category: '乳品', qty: 4, unit: '杯', shelf: 9, threshold: 2 },
      { name: '吐司面包', emoji: '🍞', category: '主食粮油', qty: 0.5, unit: '袋', shelf: 2, threshold: 1 },
      { name: '大米', emoji: '🍚', category: '主食粮油', qty: 8, unit: '斤', shelf: 200, threshold: 2 },
      { name: '生抽', emoji: '🧴', category: '调料', qty: 1, unit: '瓶', shelf: 300, threshold: 0 },
      { name: '香蕉', emoji: '🍌', category: '水果', qty: 5, unit: '根', shelf: 3, threshold: 2 },
      { name: '速冻饺子', emoji: '🥟', category: '冷冻', qty: 1, unit: '袋', shelf: 90, threshold: 1 }
    ];

    state = blank();

    var made = preset.map(function (p) {
      var item = normalizeItem({
        id: uid(),
        name: p.name,
        emoji: p.emoji,
        category: p.category,
        qty: p.qty,
        unit: p.unit,
        expiry: p.shelf === null ? '' : addDays(p.shelf),
        threshold: p.threshold
      });
      state.items.push(item);
      return item;
    });

    // 造 24 天的历史流水，让趋势图有内容（确定性伪随机，保证每次一致）
    var seed = 20261108;
    function rnd() {
      seed = (seed * 1103515245 + 12345) % 2147483648;
      return seed / 2147483648;
    }

    var start = startOfDay(new Date()).getTime();
    var cutoff = Date.now();
    for (var d = 23; d >= 0; d--) {
      var times = 1 + Math.floor(rnd() * 3);
      for (var k = 0; k < times; k++) {
        var it = made[Math.floor(rnd() * made.length)];
        var at = start - d * DAY + (7 + Math.floor(rnd() * 13)) * 3600000;
        if (at > cutoff) continue; // 今天还没到的时段不造假记录
        var amount = it.unit === '斤' ? 0.5 : 1;
        state.logs.push(normalizeLog({
          itemId: it.id, name: it.name, emoji: it.emoji, unit: it.unit,
          type: 'use', amount: amount, at: at
        }));
      }
      if (d % 6 === 0) {
        var r = made[Math.floor(rnd() * made.length)];
        var atR = start - d * DAY + 10 * 3600000;
        if (atR <= cutoff) {
          state.logs.push(normalizeLog({
            itemId: r.id, name: r.name, emoji: r.emoji, unit: r.unit,
            type: 'restock', amount: 2, at: atR
          }));
        }
      }
      if (d % 9 === 0) {
        var w = made[Math.floor(rnd() * made.length)];
        var atW = start - d * DAY + 20 * 3600000;
        if (atW <= cutoff) {
          state.logs.push(normalizeLog({
            itemId: w.id, name: w.name, emoji: w.emoji, unit: w.unit,
            type: 'waste', amount: 1, at: atW, note: '放坏了'
          }));
        }
      }
    }
    state.logs = state.logs.filter(Boolean).sort(function (a, b) { return a.at - b.at; });
    save();
    return state;
  }

  /* ================= 导出 ================= */

  global.FreshKeep = {
    CATEGORIES: CATEGORIES,
    UNITS: UNIT_LIST,
    STORAGE_KEY: STORAGE_KEY,
    load: load,
    save: save,
    state: getState,
    items: items,
    item: getItem,
    logs: logs,
    logsOf: logsOf,
    settings: settings,
    expiring: expiring,
    lowStock: lowStock,
    isLow: isLow,
    addItem: addItem,
    updateItem: updateItem,
    removeItem: removeItem,
    consume: consume,
    undoLog: undoLog,
    saveSettings: saveSettings,
    stats: stats,
    exportJSON: exportJSON,
    importJSON: importJSON,
    exportCSV: exportCSV,
    clearAll: clearAll,
    usage: usage,
    seedDemo: seedDemo,
    daysLeft: daysLeft,
    addDays: addDays,
    todayISO: todayISO,
    toISO: toISO,
    parseISO: parseISO,
    uid: uid,
    round2: round2
  };
})(window);
