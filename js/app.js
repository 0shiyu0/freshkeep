/*!
 * 鲜度 FreshKeep · 界面层
 * 原生 JS 渲染：状态变化 → 整页重绘（数据量小，逻辑最简单也最不容易出错）
 */
(function () {
  'use strict';

  var FK = window.FreshKeep;

  /* ==================== 图标 ==================== */

  var ICONS = {
    box: '<path d="M3.5 7.6 12 3.2l8.5 4.4v8.8L12 20.8 3.5 16.4V7.6Z"/><path d="M3.5 7.6 12 12l8.5-4.4M12 12v8.8"/>',
    bell: '<path d="M18 9.4a6 6 0 1 0-12 0c0 4.8-1.9 6.2-1.9 6.2h15.8S18 14.2 18 9.4Z"/><path d="M10.2 19.6a2.1 2.1 0 0 0 3.6 0"/>',
    list: '<path d="M8.5 6.5h11.5M8.5 12h11.5M8.5 17.5h11.5"/><circle cx="4.6" cy="6.5" r="1.1"/><circle cx="4.6" cy="12" r="1.1"/><circle cx="4.6" cy="17.5" r="1.1"/>',
    chart: '<path d="M3.2 20.4h17.6"/><rect x="4.6" y="12" width="3.6" height="6.2" rx="1.2"/><rect x="10.2" y="7" width="3.6" height="11.2" rx="1.2"/><rect x="15.8" y="14" width="3.6" height="4.2" rx="1.2"/>',
    sliders: '<path d="M4 7.5h9.2M18.4 7.5H20M4 16.5h3.4M12.6 16.5H20"/><circle cx="15.6" cy="7.5" r="2.2"/><circle cx="10" cy="16.5" r="2.2"/>',
    plus: '<path d="M12 5.2v13.6M5.2 12h13.6"/>',
    search: '<circle cx="10.8" cy="10.8" r="6.3"/><path d="M15.5 15.5 20 20"/>',
    close: '<path d="M6.4 6.4l11.2 11.2M17.6 6.4 6.4 17.6"/>',
    trash: '<path d="M4.2 6.8h15.6M9.4 6.8V4.2h5.2v2.6M6.4 6.8l.9 12.9h9.4l.9-12.9"/>',
    edit: '<path d="M4 20h4.2L19 9.2l-4.2-4.2L4 15.8V20Z"/><path d="M13.6 5.4 18 9.8"/>',
    undo: '<path d="M4 9.5h9.2a5.4 5.4 0 0 1 0 10.8H7.6"/><path d="M7.4 5.4 3.6 9.5l3.8 4.1"/>',
    chevron: '<path d="M9 5.5 15.5 12 9 18.5"/>',
    box2: '<rect x="3.4" y="6.6" width="17.2" height="12.8" rx="2.6"/><path d="M3.4 10.6h17.2M8 6.6v4"/>',
    leaf: '<path d="M20 4c-8.4 0-14 3.8-14 9.6a5 5 0 0 0 5 5C17 18.6 20 12.4 20 4Z"/><path d="M4.6 20c1.4-4.4 4.4-7.4 8.8-9.2"/>'
  };

  function icon(name, cls) {
    return '<svg class="ic ' + (cls || '') + '" viewBox="0 0 24 24" fill="none" stroke="currentColor" ' +
      'stroke-width="1.75" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">' +
      (ICONS[name] || '') + '</svg>';
  }

  /* ==================== 静态数据 ==================== */

  var CAT_EMOJI = {
    '蔬菜': '🥬', '水果': '🍎', '肉禽蛋': '🥩', '水产': '🐟', '乳品': '🥛',
    '主食粮油': '🍚', '调料': '🧂', '冷冻': '🧊', '饮品': '🥤', '零食': '🍪', '其他': '🍽️'
  };

  // 常用食材：点一下自动填好名称 / 分类 / 单位 / 建议保质期，减少每天的打字量
  var PRESETS = [
    { name: '牛奶', emoji: '🥛', category: '乳品', unit: '盒', days: 7 },
    { name: '鸡蛋', emoji: '🥚', category: '肉禽蛋', unit: '个', days: 30 },
    { name: '西红柿', emoji: '🍅', category: '蔬菜', unit: '个', days: 7 },
    { name: '青菜', emoji: '🥬', category: '蔬菜', unit: '把', days: 4 },
    { name: '猪肉', emoji: '🥩', category: '肉禽蛋', unit: '斤', days: 3 },
    { name: '鸡胸肉', emoji: '🍗', category: '肉禽蛋', unit: '袋', days: 90 },
    { name: '香蕉', emoji: '🍌', category: '水果', unit: '根', days: 5 },
    { name: '面包', emoji: '🍞', category: '主食粮油', unit: '袋', days: 5 },
    { name: '大米', emoji: '🍚', category: '主食粮油', unit: '斤', days: 180 },
    { name: '酸奶', emoji: '🥣', category: '乳品', unit: '杯', days: 14 }
  ];

  var TABS = [
    { key: 'inventory', label: '库存', icon: 'box' },
    { key: 'expiring', label: '临期', icon: 'bell' },
    { key: 'logs', label: '记录', icon: 'list' },
    { key: 'stats', label: '统计', icon: 'chart' },
    { key: 'settings', label: '设置', icon: 'sliders' }
  ];

  var ui = { tab: 'inventory', q: '', cat: 'all', range: 7, logFilter: 'all' };
  var pendingConfirm = null;

  /* ==================== 工具 ==================== */

  function $(sel, root) { return (root || document).querySelector(sel); }

  function esc(s) {
    return String(s == null ? '' : s).replace(/[&<>"']/g, function (c) {
      return { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c];
    });
  }

  function fmtQty(n) {
    var v = Number(n) || 0;
    return v % 1 === 0 ? String(v) : String(Math.round(v * 100) / 100);
  }

  function fmtBytes(b) {
    if (b < 1024) return b + ' B';
    if (b < 1024 * 1024) return (b / 1024).toFixed(1) + ' KB';
    return (b / 1048576).toFixed(2) + ' MB';
  }

  function pad2(n) { return (n < 10 ? '0' : '') + n; }

  function hm(ts) {
    var d = new Date(ts);
    return pad2(d.getHours()) + ':' + pad2(d.getMinutes());
  }

  function dayKey(ts) {
    var d = new Date(ts);
    return d.getFullYear() + '-' + pad2(d.getMonth() + 1) + '-' + pad2(d.getDate());
  }

  function dayTitle(ts) {
    var d = new Date(ts);
    var today = new Date();
    var t0 = new Date(today.getFullYear(), today.getMonth(), today.getDate()).getTime();
    var d0 = new Date(d.getFullYear(), d.getMonth(), d.getDate()).getTime();
    var diff = Math.round((t0 - d0) / 86400000);
    if (diff === 0) return '今天';
    if (diff === 1) return '昨天';
    if (diff === 2) return '前天';
    var week = ['周日', '周一', '周二', '周三', '周四', '周五', '周六'][d.getDay()];
    return (d.getMonth() + 1) + ' 月 ' + d.getDate() + ' 日 · ' + week;
  }

  function mdOf(iso) {
    var d = FK.parseISO(iso);
    return d ? (d.getMonth() + 1) + '/' + d.getDate() : '';
  }

  function daysText(d) {
    if (d === null) return '无保质期';
    if (d < 0) return '已过期 ' + Math.abs(d) + ' 天';
    if (d === 0) return '今天到期';
    return '剩 ' + d + ' 天';
  }

  function badgeOf(it) {
    var d = FK.daysLeft(it.expiry);
    var urgent = FK.settings().expiryUrgentDays;
    var warn = FK.settings().expiryWarnDays;
    if (it.qty <= 0) return '<span class="badge badge--muted">已用完</span>';
    if (d === null) {
      return FK.isLow(it) ? '<span class="badge badge--warn">该补货了</span>' : '';
    }
    if (d < 0) return '<span class="badge badge--danger">过期 ' + Math.abs(d) + ' 天</span>';
    if (d === 0) return '<span class="badge badge--danger">今天到期</span>';
    if (d <= urgent) return '<span class="badge badge--danger">剩 ' + d + ' 天</span>';
    if (d <= warn) return '<span class="badge badge--warn">剩 ' + d + ' 天</span>';
    return '';
  }

  function guessEmoji(name, category) {
    var n = String(name || '');
    for (var i = 0; i < PRESETS.length; i++) {
      if (n && (n.indexOf(PRESETS[i].name) >= 0 || PRESETS[i].name.indexOf(n) >= 0)) return PRESETS[i].emoji;
    }
    return CAT_EMOJI[category] || '🍽️';
  }

  /* ==================== 顶部 / 底部 ==================== */

  function tabMeta() {
    var items = FK.items();
    var exp = FK.expiring();
    var overdue = 0, urgent = 0;
    exp.forEach(function (e) {
      if (e.days < 0) overdue++;
      else if (e.days <= FK.settings().expiryUrgentDays) urgent++;
    });

    if (ui.tab === 'inventory') {
      var sub = items.length
        ? '共 ' + items.length + ' 种食材' +
          (exp.length ? ' · <b' + (overdue ? ' class="is-danger"' : '') + '>' + exp.length + ' 种临期</b>' : ' · 全部在保质期内')
        : '还没有记录任何食材';
      return { title: '库存', sub: sub };
    }
    if (ui.tab === 'expiring') {
      return {
        title: '临期提醒',
        sub: exp.length ? exp.length + ' 种食材需要优先处理' : '暂时没有临期食材'
      };
    }
    if (ui.tab === 'logs') {
      var n = FK.logs().length;
      return { title: '使用记录', sub: n ? '累计 ' + n + ' 条变动流水' : '还没有任何记录' };
    }
    if (ui.tab === 'stats') {
      return { title: '消耗统计', sub: '最近 ' + ui.range + ' 天的消耗情况' };
    }
    return { title: '鲜度', sub: '数据与提醒偏好' };
  }

  function renderTopbar() {
    var m = tabMeta();
    $('#topbar').innerHTML =
      '<div class="topbar__main"><h1>' + esc(m.title) + '</h1><p>' + m.sub + '</p></div>';
  }

  function renderTabbar() {
    var exp = FK.expiring().length;
    var html = TABS.map(function (t) {
      var on = t.key === ui.tab;
      var badge = (t.key === 'expiring' && exp) ? '<i class="tab__dot">' + (exp > 99 ? '99+' : exp) + '</i>' : '';
      return '<button class="tab' + (on ? ' is-on' : '') + '" data-act="tab" data-tab="' + t.key + '" ' +
        'aria-current="' + (on ? 'page' : 'false') + '">' + icon(t.icon) + '<span>' + t.label + '</span>' + badge + '</button>';
    }).join('');
    $('#tabbar').innerHTML = html;
  }

  /* ==================== 库存视图 ==================== */

  function searchBar() {
    return '<div class="searchbar">' + icon('search') +
      '<input id="q" type="search" placeholder="搜索食材 / 分类" value="' + esc(ui.q) + '" ' +
      'autocomplete="off" enterkeyhint="search" aria-label="搜索食材">' +
      '<button class="searchbar__clear" data-act="clear-q" ' + (ui.q ? '' : 'hidden') + ' aria-label="清空">✕</button>' +
      '</div>';
  }

  function summaryBar(items, exp) {
    var overdue = 0;
    exp.forEach(function (e) { if (e.days < 0) overdue++; });
    var low = FK.lowStock().length;
    return '<div class="summary">' +
      '<div class="summary__card"><span>食材品类</span><strong>' + items.length + '</strong><small>种</small></div>' +
      '<div class="summary__card' + (exp.length ? ' is-warn' : '') + '"><span>临期</span><strong>' + exp.length + '</strong><small>种</small></div>' +
      '<div class="summary__card' + (overdue || low ? ' is-danger' : '') + '"><span>需处理</span><strong>' + (overdue + low) + '</strong><small>项</small></div>' +
      '</div>';
  }

  function catChips(items) {
    var counts = {};
    items.forEach(function (it) { counts[it.category] = (counts[it.category] || 0) + 1; });
    var cats = FK.CATEGORIES.filter(function (c) { return counts[c]; });
    var html = '<div class="chips">' +
      '<button class="chip' + (ui.cat === 'all' ? ' is-on' : '') + '" data-act="cat" data-cat="all">全部 <em>' + items.length + '</em></button>';
    cats.forEach(function (c) {
      html += '<button class="chip' + (ui.cat === c ? ' is-on' : '') + '" data-act="cat" data-cat="' + esc(c) + '">' +
        esc(c) + ' <em>' + counts[c] + '</em></button>';
    });
    return html + '</div>';
  }

  function itemCard(it) {
    var d = FK.daysLeft(it.expiry);
    var out = it.qty <= 0;
    var cls = 'item' + (out ? ' is-out' : (FK.isLow(it) ? ' is-low' : ''));
    var meta = esc(it.category) + ' · ' + (it.expiry ? '到期 ' + mdOf(it.expiry) : '无保质期');
    if (it.note) meta += ' · ' + esc(it.note);
    return '<article class="' + cls + '" data-act="item" data-id="' + it.id + '" tabindex="0">' +
      '<div class="item__emoji">' + esc(it.emoji) + '</div>' +
      '<div class="item__body">' +
        '<div class="item__title"><span>' + esc(it.name) + '</span>' + badgeOf(it) + '</div>' +
        '<div class="item__meta">' + meta + '</div>' +
      '</div>' +
      '<div class="item__right">' +
        '<div class="qty"><strong>' + fmtQty(it.qty) + '</strong><span>' + esc(it.unit) + '</span></div>' +
        '<button class="minus" data-act="minus" data-id="' + it.id + '" ' + (out ? 'disabled' : '') +
          ' aria-label="消耗 1 ' + esc(it.unit) + '">−1</button>' +
      '</div>' +
      '</article>';
  }

  function itemListHTML() {
    var q = ui.q.toLowerCase();
    var list = FK.items().filter(function (it) {
      if (ui.cat !== 'all' && it.category !== ui.cat) return false;
      if (!q) return true;
      return (it.name + ' ' + it.category + ' ' + (it.note || '')).toLowerCase().indexOf(q) >= 0;
    });

    if (!list.length) {
      return '<div class="empty"><span class="empty__icon">🔍</span><h3>没有匹配的食材</h3>' +
        '<p>换个关键词，或者点下面按钮看清全部。</p>' +
        '<div class="empty__actions"><button class="btn btn--ghost btn--sm" data-act="reset-filter">清除筛选</button></div></div>';
    }

    // 分组：分类顺序固定，组内按到期时间从近到远
    var order = {};
    FK.CATEGORIES.forEach(function (c, i) { order[c] = i; });
    var groups = {};
    list.forEach(function (it) { (groups[it.category] = groups[it.category] || []).push(it); });

    var keys = Object.keys(groups).sort(function (a, b) {
      return (order[a] === undefined ? 99 : order[a]) - (order[b] === undefined ? 99 : order[b]);
    });

    var html = '';
    keys.forEach(function (k) {
      var arr = groups[k].sort(function (a, b) {
        var da = FK.daysLeft(a.expiry); var db = FK.daysLeft(b.expiry);
        if (da === null) da = 9999;
        if (db === null) db = 9999;
        return da - db || a.name.localeCompare(b.name, 'zh');
      });
      html += '<section class="group"><div class="group__head"><span>' + esc(k) + '</span>' +
        '<em>' + arr.length + ' 种</em></div>' +
        arr.map(itemCard).join('') + '</section>';
    });
    return html;
  }

  function viewInventory() {
    var items = FK.items();
    if (!items.length) return emptyHome();
    return searchBar() + summaryBar(items, FK.expiring()) + catChips(items) +
      '<div id="item-list">' + itemListHTML() + '</div>';
  }

  function emptyHome() {
    return '<div class="empty"><span class="empty__icon">🧺</span>' +
      '<h3>冰箱还是空的</h3>' +
      '<p>添加第一件食材。以后每次取用，点一下清单上的 −1 就会自动扣库存、记流水。</p>' +
      '<div class="empty__actions">' +
      '<button class="btn btn--primary" data-act="add">添加食材</button>' +
      '<button class="btn btn--ghost" data-act="demo">载入示例数据</button>' +
      '</div></div>';
  }

  /* ==================== 临期视图 ==================== */

  function viewExpiring() {
    var list = FK.expiring();
    if (!list.length) {
      return '<div class="empty"><span class="empty__icon">🎉</span><h3>没有临期食材</h3>' +
        '<p>所有带保质期的食材都还在安全期内。<br>添加食材时填上日期，这里就会自动提醒。</p>' +
        '<div class="empty__actions"><button class="btn btn--ghost btn--sm" data-act="add">添加食材</button></div></div>';
    }
    var urgent = FK.settings().expiryUrgentDays;
    var groups = [
      { key: 'expired', title: '已经过期', desc: '建议直接丢弃', filter: function (e) { return e.days < 0; } },
      { key: 'urgent', title: '3 天内到期', desc: '优先吃掉', filter: function (e) { return e.days >= 0 && e.days <= urgent; } },
      { key: 'soon', title: '本周到期', desc: '可以安排进菜单', filter: function (e) { return e.days > urgent; } }
    ];
    var html = '<p class="hint" style="padding:6px 4px 0">点 −1 记一次消耗，点卡片可丢弃或改保质期。</p>';
    var shown = 0;
    groups.forEach(function (g) {
      var arr = list.filter(g.filter);
      if (!arr.length) return;
      shown += arr.length;
      html += '<section class="group"><div class="group__head"><span>' + g.title + '</span>' +
        '<em>' + arr.length + ' 种 · ' + g.desc + '</em></div>' +
        arr.map(function (e) { return itemCard(e.item); }).join('') + '</section>';
    });
    if (!shown) return emptyHome();
    return html;
  }

  /* ==================== 记录视图 ==================== */

  var LOG_LABEL = { use: '消耗', restock: '补货', waste: '丢弃' };

  function viewLogs() {
    var all = FK.logs();
    if (!all.length) {
      return '<div class="empty"><span class="empty__icon">📋</span><h3>还没有任何流水</h3>' +
        '<p>每次扣减库存都会在这里留一条记录，<br>点错了一秒就能撤销。</p></div>';
    }
    var filters = [['all', '全部'], ['use', '消耗'], ['restock', '补货'], ['waste', '丢弃']];
    var chips = '<div class="chips" style="padding-top:6px">' + filters.map(function (f) {
      return '<button class="chip' + (ui.logFilter === f[0] ? ' is-on' : '') + '" data-act="log-filter" data-f="' + f[0] + '">' + f[1] + '</button>';
    }).join('') + '</div>';

    var list = ui.logFilter === 'all' ? all : all.filter(function (l) { return l.type === ui.logFilter; });
    if (!list.length) {
      return chips + '<div class="empty"><span class="empty__icon">🗂️</span><h3>这个分类还没有记录</h3></div>';
    }

    var groups = {};
    var order = [];
    list.forEach(function (l) {
      var k = dayKey(l.at);
      if (!groups[k]) { groups[k] = []; order.push(k); }
      groups[k].push(l);
    });

    var html = chips;
    order.forEach(function (k) {
      var arr = groups[k];
      html += '<section class="day"><div class="day__head"><span>' + dayTitle(arr[0].at) + '</span>' +
        '<em>' + arr.length + ' 条</em></div>' + arr.map(logRow).join('') + '</section>';
    });
    return html;
  }

  function logRow(l) {
    var sign = l.type === 'restock' ? '+' : '−';
    var cls = l.type === 'restock' ? 'is-plus' : (l.type === 'waste' ? 'is-waste' : 'is-minus');
    var meta = hm(l.at) + ' · ' + LOG_LABEL[l.type] + (l.note ? ' · ' + esc(l.note) : '');
    return '<div class="log">' +
      '<div class="log__emoji">' + esc(l.emoji) + '</div>' +
      '<div class="log__body">' +
        '<div class="log__title"><span>' + esc(l.name) + '</span>' +
          '<small class="t-' + l.type + '">' + LOG_LABEL[l.type] + '</small></div>' +
        '<div class="log__meta">' + meta + '</div>' +
      '</div>' +
      '<div class="log__delta ' + cls + '">' + sign + fmtQty(l.amount) + ' ' + esc(l.unit) + '</div>' +
      '<button class="log__undo" data-act="undo" data-id="' + l.id + '" aria-label="撤销这条记录">' + icon('undo') + '</button>' +
      '</div>';
  }

  /* ==================== 统计视图 ==================== */

  function viewStats() {
    var s = FK.stats(ui.range);
    var seg = '<div class="segmented">' +
      [7, 30].map(function (d) {
        return '<button class="' + (ui.range === d ? 'is-on' : '') + '" data-act="range" data-d="' + d + '">最近 ' + d + ' 天</button>';
      }).join('') + '</div>';

    if (!s.useCount && !s.restockCount) {
      return seg + '<div class="empty"><span class="empty__icon">📊</span><h3>还没有足够的消耗记录</h3>' +
        '<p>用上几天，这里就会出现每日消耗趋势和吃的最快的食材排行。</p></div>';
    }

    var html = seg;

    html += '<div class="card">' +
      '<div class="block__head" style="padding:0 0 6px"><h2>每日消耗笔数</h2>' +
      '<span>日均 ' + s.avgPerDay + ' 笔</span></div>' +
      chartSVG(s.series) +
      '</div>';

    html += '<div class="stats-grid">' +
      '<div class="stat"><span>消耗记录</span><strong>' + s.useCount + '</strong><small>笔</small></div>' +
      '<div class="stat"><span>补货</span><strong>' + s.restockCount + '</strong><small>次</small></div>' +
      '<div class="stat"><span>丢弃</span><strong>' + s.wasteCount + '</strong><small>次</small></div>' +
      '</div>';

    if (s.top.length) {
      var max = s.top[0].count || 1;
      html += '<div class="card"><div class="block__head" style="padding:0"><h2>吃的最快的食材</h2>' +
        '<span>按消耗次数</span></div><div class="rank">' +
        s.top.map(function (t, i) {
          var pct = Math.max(6, Math.round(t.count / max * 100));
          return '<div class="rank__row"><div class="rank__no">' + (i + 1) + '</div>' +
            '<div class="rank__body"><div class="rank__title"><span>' + esc(t.emoji) + ' ' + esc(t.name) +
            '</span><em>' + t.count + ' 次 · ' + fmtQty(t.amount) + ' ' + esc(t.unit) + '</em></div>' +
            '<div class="rank__bar"><i style="width:' + pct + '%"></i></div></div></div>';
        }).join('') + '</div></div>';
    }

    if (s.wasteCount) {
      html += '<div class="card"><p class="hint">最近 ' + s.days + ' 天丢弃了 <b>' + s.wasteCount +
        '</b> 次食材。临期清单配合“先吃快到期的”，基本能把它降到 0。</p></div>';
    }

    return html;
  }

  function chartSVG(series) {
    var W = 320, H = 160, padL = 24, padR = 6, padT = 12, padB = 26;
    var innerW = W - padL - padR;
    var innerH = H - padT - padB;
    var n = series.length;

    var max = 0;
    series.forEach(function (p) { if (p.uses > max) max = p.uses; });
    var step = Math.max(1, Math.ceil(max / 3));
    var top = step * 3;

    var gap = n > 14 ? 2 : 7;
    var bw = (innerW - gap * (n - 1)) / n;

    var out = ['<svg class="chart" viewBox="0 0 ' + W + ' ' + H + '" role="img" aria-label="每日消耗趋势图">'];

    for (var g = 0; g <= 3; g++) {
      var y = padT + innerH - (innerH * g / 3);
      out.push('<line x1="' + padL + '" y1="' + y.toFixed(1) + '" x2="' + (W - padR) + '" y2="' + y.toFixed(1) +
        '" stroke="' + (g === 0 ? '#ded8cb' : '#f1eee6') + '" stroke-width="1"/>');
      out.push('<text x="' + (padL - 7) + '" y="' + (y + 3).toFixed(1) +
        '" font-size="9" fill="#a0a69f" text-anchor="end">' + (step * g) + '</text>');
    }

    series.forEach(function (p, i) {
      var h = top ? innerH * p.uses / top : 0;
      var x = padL + i * (bw + gap);
      var y = padT + innerH - h;
      var isToday = i === n - 1;
      var fill = p.uses ? (isToday ? '#17803f' : '#9dcfad') : '#eeebe3';
      if (p.uses && h < 2) h = 2;
      if (!p.uses) h = 2;
      out.push('<rect x="' + x.toFixed(1) + '" y="' + (padT + innerH - h).toFixed(1) + '" width="' + bw.toFixed(1) +
        '" height="' + h.toFixed(1) + '" rx="' + Math.min(2.5, bw / 2).toFixed(1) + '" fill="' + fill + '">' +
        '<title>' + p.date + '：' + p.uses + ' 次消耗</title></rect>');
    });

    var lastLabeled = -99;
    series.forEach(function (p, i) {
      var need = (n <= 7) || (i % 5 === 0) || (i === n - 1);
      if (!need) return;
      if (i - lastLabeled < (n <= 7 ? 1 : 3)) return;
      lastLabeled = i;
      var cx = padL + i * (bw + gap) + bw / 2;
      out.push('<text x="' + cx.toFixed(1) + '" y="' + (H - 8) + '" font-size="9" fill="#a0a69f" text-anchor="middle">' +
        mdOf(p.date) + '</text>');
    });

    out.push('</svg>');
    return out.join('');
  }

  /* ==================== 设置视图 ==================== */

  function viewSettings() {
    var st = FK.settings();
    var u = FK.usage();
    return '<div class="brand"><div class="brand__logo">🥕</div><div>' +
      '<h3>鲜度 FreshKeep</h3><p>食材库存与消耗记录 · 数据只存在这台设备</p></div></div>' +

      '<div class="card" style="padding:0;overflow:hidden">' +
      '<div class="setting-row"><div class="setting-row__label">临期提醒<small>保质期还剩几天时开始提示</small></div>' +
      stepper('expiryWarnDays', st.expiryWarnDays, '天') + '</div>' +
      '<div class="setting-row"><div class="setting-row__label">紧急提醒<small>红色高亮的剩余天数</small></div>' +
      stepper('expiryUrgentDays', st.expiryUrgentDays, '天') + '</div>' +
      '</div>' +

      '<div class="card" style="padding:0;overflow:hidden">' +
      '<button class="link-row" data-act="export-json"><span>导出备份（JSON）</span><small>含全部食材与流水</small></button>' +
      '<button class="link-row" data-act="import-json"><span>导入备份</span><small>覆盖当前数据</small></button>' +
      '<button class="link-row" data-act="export-csv"><span>导出流水（CSV）</span><small>可用 Excel 打开</small></button>' +
      '<button class="link-row" data-act="demo"><span>载入示例数据</span><small>覆盖当前数据</small></button>' +
      '<button class="link-row is-danger" data-act="clear"><span>清空所有数据</span><small>不可恢复</small></button>' +
      '<input type="file" id="import-file" accept="application/json,.json" hidden>' +
      '</div>' +

      '<div class="card" style="padding:0;overflow:hidden">' +
      '<div class="setting-row"><div class="setting-row__label">存储用量</div>' +
      '<em style="color:var(--text-2);font-size:13px">' + fmtBytes(u.bytes) + '</em></div>' +
      '<div class="setting-row"><div class="setting-row__label">记录数量</div>' +
      '<em style="color:var(--text-2);font-size:13px">' + u.items + ' 种食材 / ' + u.logs + ' 条流水</em></div>' +
      '<div class="setting-row"><div class="setting-row__label">数据位置</div>' +
      '<em style="color:var(--text-2);font-size:13px">本机 localStorage</em></div>' +
      '</div>' +

      '<p class="footnote">数据保存在当前浏览器的 localStorage 中，不上传任何服务器。<br>' +
      '换设备或清理浏览器数据前，请先「导出备份」。<br>添加食材时填保质期，临期清单才会生效。</p>';
  }

  function stepper(key, value, unit) {
    return '<div class="stepper">' +
      '<button data-act="step" data-key="' + key + '" data-d="-1" aria-label="减少">−</button>' +
      '<b>' + value + ' ' + unit + '</b>' +
      '<button data-act="step" data-key="' + key + '" data-d="1" aria-label="增加">+</button>' +
      '</div>';
  }

  /* ==================== 渲染入口 ==================== */

  var VIEWS = {
    inventory: viewInventory,
    expiring: viewExpiring,
    logs: viewLogs,
    stats: viewStats,
    settings: viewSettings
  };

  function render() {
    renderTopbar();
    $('#view').innerHTML = (VIEWS[ui.tab] || viewInventory)();
    renderTabbar();
    // 统计 / 设置页不需要"随手加一件"，让位于内容
    var fab = $('#fab');
    if (fab) fab.hidden = (ui.tab === 'stats' || ui.tab === 'settings');
  }

  function switchTab(tab) {
    if (!VIEWS[tab]) return;
    ui.tab = tab;
    ui.q = '';
    closeSheet();
    render();
    if (window.history && history.replaceState) history.replaceState(null, '', '#' + tab);
    window.scrollTo(0, 0);
  }

  /* ==================== 弹层 ==================== */

  function sheetShell(title, body) {
    return '<div class="sheet-mask" data-act="sheet-close"></div>' +
      '<div class="sheet" role="dialog" aria-modal="true" aria-label="' + esc(title) + '">' +
      '<div class="sheet__handle"></div>' +
      '<div class="sheet__head"><h2>' + esc(title) + '</h2>' +
      '<button class="iconbtn" data-act="sheet-close" aria-label="关闭">' + icon('close') + '</button></div>' +
      '<div class="sheet__body">' + body + '</div></div>';
  }

  function openSheet(title, body) {
    var root = $('#sheet-root');
    var wasOpen = root.classList.contains('is-open');
    root.hidden = false;
    root.innerHTML = sheetShell(title, body);
    document.body.classList.add('is-locked');
    if (!wasOpen) {
      // 首次打开：先渲染再触发过渡，避免动画被跳帧
      requestAnimationFrame(function () { root.classList.add('is-open'); });
    }
  }

  function closeSheet() {
    var root = $('#sheet-root');
    if (!root || root.hidden) return;
    root.classList.remove('is-open');
    document.body.classList.remove('is-locked');
    pendingConfirm = null;
    setTimeout(function () {
      if (!root.classList.contains('is-open')) {
        root.hidden = true;
        root.innerHTML = '';
      }
    }, 300);
  }

  /* ---------- 添加 / 编辑表单 ---------- */

  function formHTML(item) {
    var isEdit = !!item;
    var it = item || { name: '', qty: 1, unit: '个', category: '蔬菜', expiry: '', threshold: 1 };
    var units = FK.UNITS.slice();
    if (units.indexOf(it.unit) < 0) units.push(it.unit);
    var cats = FK.CATEGORIES.slice();
    if (cats.indexOf(it.category) < 0) cats.push(it.category);

    var presetBar = isEdit ? '' :
      '<div class="presets">' + PRESETS.map(function (p) {
        return '<button type="button" data-act="preset" data-name="' + esc(p.name) + '">' +
          '<span>' + p.emoji + '</span>' + esc(p.name) + '</button>';
      }).join('') + '</div>' +
      '<p class="hint">点上面的常用食材可以一键填好分类、单位和建议保质期。</p>';

    return '<form id="item-form" data-mode="' + (isEdit ? 'edit' : 'add') + '" data-id="' + (isEdit ? it.id : '') + '">' +
      presetBar +
      '<label class="field"><span>名称</span>' +
      '<input name="name" required maxlength="40" placeholder="例如：牛奶" value="' + esc(it.name) + '" autocomplete="off"></label>' +
      '<div class="field-row">' +
      '<label class="field"><span>数量</span>' +
      '<input name="qty" type="number" inputmode="decimal" step="0.01" min="0" value="' + fmtQty(it.qty) + '"></label>' +
      '<label class="field"><span>单位</span><select name="unit">' +
      units.map(function (u) { return '<option value="' + esc(u) + '"' + (u === it.unit ? ' selected' : '') + '>' + esc(u) + '</option>'; }).join('') +
      '</select></label></div>' +
      '<label class="field"><span>分类</span><select name="category">' +
      cats.map(function (c) { return '<option value="' + esc(c) + '"' + (c === it.category ? ' selected' : '') + '>' + esc(c) + '</option>'; }).join('') +
      '</select></label>' +
      '<label class="field"><span>保质期（选填）</span>' +
      '<input name="expiry" type="date" value="' + esc(it.expiry) + '"></label>' +
      '<div class="quick-row">' +
      '<button type="button" data-act="quick-date" data-d="3">+3 天</button>' +
      '<button type="button" data-act="quick-date" data-d="7">+7 天</button>' +
      '<button type="button" data-act="quick-date" data-d="15">+15 天</button>' +
      '<button type="button" data-act="quick-date" data-d="30">+30 天</button>' +
      '<button type="button" data-act="quick-date" data-d="0">清除</button>' +
      '</div>' +
      '<label class="field"><span>低库存提醒（库存 ≤ 此值时提示）</span>' +
      '<input name="threshold" type="number" inputmode="numeric" step="1" min="0" value="' + fmtQty(it.threshold) + '"></label>' +
      (isEdit ? '<p class="hint">直接改数量用于纠错，不会记入消耗流水；日常取用请用清单上的 −1。</p>' : '') +
      '<button class="btn btn--primary btn--block" type="submit">' + (isEdit ? '保存修改' : '添加到库存') + '</button>' +
      '</form>';
  }

  function openForm(id) {
    var item = id ? FK.item(id) : null;
    openSheet(item ? '编辑食材' : '添加食材', formHTML(item));
    if (!item) {
      var input = $('#item-form input[name="name"]');
      if (input) setTimeout(function () { input.focus(); }, 260);
    }
  }

  /* ---------- 食材详情 ---------- */

  function openDetail(id) {
    var it = FK.item(id);
    if (!it) return;
    var d = FK.daysLeft(it.expiry);
    var last = FK.logsOf(id)[0];
    var dTxt = d === null ? '未设置' : (mdOf(it.expiry) + '（' + daysText(d) + '）');

    var body = '<div class="detail__top">' +
      '<div class="detail__emoji">' + esc(it.emoji) + '</div>' +
      '<div><h3>' + esc(it.name) + '</h3><p>' + esc(it.category) + ' · ' + daysText(d) + '</p></div>' +
      '</div>' +
      '<div class="detail__qty"><strong>' + fmtQty(it.qty) + '</strong><span>' + esc(it.unit) + '</span></div>' +
      '<div class="detail__actions">' +
      '<button class="is-primary" data-act="quick-use" data-id="' + it.id + '"><b>−1</b>消耗一份</button>' +
      '<button data-act="open-amount" data-id="' + it.id + '" data-type="use"><b>±</b>消耗其他数量</button>' +
      '<button data-act="open-amount" data-id="' + it.id + '" data-type="restock"><b>＋</b>补货入库</button>' +
      '<button data-act="open-amount" data-id="' + it.id + '" data-type="waste"><b>🗑</b>丢弃</button>' +
      '</div>' +
      '<div class="rows">' +
      '<div class="rows__item"><span>保质期</span><em>' + dTxt + '</em></div>' +
      '<div class="rows__item"><span>低库存阈值</span><em>' + fmtQty(it.threshold) + ' ' + esc(it.unit) + '</em></div>' +
      '<div class="rows__item"><span>最近一次变动</span><em>' +
      (last ? dayTitle(last.at) + ' ' + hm(last.at) + ' ' + LOG_LABEL[last.type] + ' ' + fmtQty(last.amount) + last.unit : '还没有记录') +
      '</em></div>' +
      '</div>' +
      '<div class="detail__footer">' +
      '<button class="btn btn--ghost" data-act="edit" data-id="' + it.id + '">' + icon('edit') + '编辑</button>' +
      '<button class="btn btn--danger" data-act="delete" data-id="' + it.id + '">' + icon('trash') + '删除</button>' +
      '</div>';

    openSheet('食材详情', body);
  }

  /* ---------- 数量输入 ---------- */

  function openAmount(id, type) {
    var it = FK.item(id);
    if (!it) return;
    var label = type === 'restock' ? '补货' : (type === 'waste' ? '丢弃' : '消耗');
    var body = '<form id="amount-form" data-id="' + it.id + '" data-type="' + type + '">' +
      '<p class="hint">当前库存 <b>' + fmtQty(it.qty) + ' ' + esc(it.unit) + '</b>（' + esc(it.name) + '）</p>' +
      '<label class="field" style="margin-top:12px"><span>' + label + '数量</span>' +
      '<input name="amount" type="number" inputmode="decimal" step="0.01" min="0.01" value="' +
      (type === 'restock' ? 1 : Math.min(1, it.qty || 1)) + '"></label>' +
      '<div class="quick-row">' +
      [1, 2, 5].map(function (n) {
        return '<button type="button" data-act="set-amount" data-n="' + n + '">' + n + ' ' + esc(it.unit) + '</button>';
      }).join('') +
      (type !== 'restock' && it.qty > 0 ? '<button type="button" data-act="set-amount" data-n="' + it.qty + '">全部</button>' : '') +
      '</div>' +
      '<label class="field"><span>备注（选填）</span>' +
      '<input name="note" maxlength="40" placeholder="例如：做晚饭" autocomplete="off"></label>' +
      '<button class="btn btn--primary btn--block" type="submit">确认' + label + '</button>' +
      '</form>';
    openSheet(label + ' · ' + it.name, body);
    var input = $('#amount-form input[name="amount"]');
    if (input) setTimeout(function () { input.focus(); input.select(); }, 260);
  }

  /* ---------- 二次确认 ---------- */

  function askConfirm(title, desc, okText, fn) {
    pendingConfirm = fn;
    openSheet(title, '<p class="hint" style="padding:4px 2px 16px;font-size:13.5px;line-height:1.7">' + desc + '</p>' +
      '<div class="detail__footer" style="margin-top:0">' +
      '<button class="btn btn--ghost" data-act="sheet-close">取消</button>' +
      '<button class="btn btn--danger" data-act="confirm">' + okText + '</button></div>');
  }

  /* ==================== 轻提示 ==================== */

  var toastTimer = null;

  function toast(msg, action) {
    var wrap = $('#toast-wrap');
    var el = document.createElement('div');
    el.className = 'toast';
    el.innerHTML = '<span>' + msg + '</span>' +
      (action ? '<button data-toast="1" type="button">' + esc(action.label) + '</button>' : '');

    function dismiss() {
      el.classList.add('is-out');
      setTimeout(function () { if (el.parentNode) el.parentNode.removeChild(el); }, 220);
    }

    if (action) {
      el.querySelector('[data-toast]').addEventListener('click', function () {
        dismiss();
        action.fn();
      });
    }
    wrap.appendChild(el);
    clearTimeout(toastTimer);
    toastTimer = setTimeout(dismiss, 4200);
    while (wrap.children.length > 2) wrap.removeChild(wrap.firstChild);
  }

  /* ==================== 业务动作 ==================== */

  function quickUse(id) {
    var r = FK.consume(id, 1, 'use', '');
    if (!r) return;
    if (r.delta === 0) {
      toast('「' + esc(r.item.name) + '」库存已经是 0 了');
      return;
    }
    render();
    toast('已记一笔：' + esc(r.item.name) + ' −1 ' + esc(r.item.unit), {
      label: '撤销',
      fn: function () {
        FK.undoLog(r.log.id);
        render();
        toast('已撤销');
      }
    });
  }

  function saveForm(form) {
    var mode = form.getAttribute('data-mode');
    var el = form.elements;
    var payload = {
      name: el.name.value,
      qty: el.qty.value,
      unit: el.unit.value,
      category: el.category.value,
      expiry: el.expiry.value,
      threshold: el.threshold.value
    };
    if (!String(payload.name).trim()) return;

    if (mode === 'edit') {
      var id = form.getAttribute('data-id');
      var before = FK.item(id);
      payload.emoji = before && before.name === payload.name ? before.emoji : guessEmoji(payload.name, payload.category);
      FK.updateItem(id, payload);
      closeSheet();
      render();
      toast('已保存修改');
    } else {
      payload.emoji = guessEmoji(payload.name, payload.category);
      var it = FK.addItem(payload);
      closeSheet();
      render();
      if (it) {
        toast('已入库：' + esc(it.name) + ' ' + fmtQty(it.qty) + ' ' + esc(it.unit), {
          label: '继续添加',
          fn: function () { openForm(null); }
        });
      }
    }
  }

  function submitAmount(form) {
    var id = form.getAttribute('data-id');
    var type = form.getAttribute('data-type');
    var amount = form.elements.amount.value;
    var note = form.elements.note.value;
    var r = FK.consume(id, amount, type, note);
    if (!r || !r.log) {
      toast('请输入大于 0 的数量');
      return;
    }
    closeSheet();
    render();
    toast(LOG_LABEL[type] + '已记录：' + esc(r.item.name) + ' ' + (r.delta > 0 ? '+' : '−') +
      fmtQty(Math.abs(r.delta)) + ' ' + esc(r.item.unit), {
      label: '撤销',
      fn: function () { FK.undoLog(r.log.id); render(); toast('已撤销'); }
    });
  }

  function download(filename, text, mime) {
    try {
      var blob = new Blob([text], { type: mime || 'application/json;charset=utf-8' });
      var url = URL.createObjectURL(blob);
      var a = document.createElement('a');
      a.href = url;
      a.download = filename;
      document.body.appendChild(a);
      a.click();
      setTimeout(function () {
        URL.revokeObjectURL(url);
        if (a.parentNode) a.parentNode.removeChild(a);
      }, 800);
      return true;
    } catch (e) {
      toast('导出失败，请检查浏览器是否允许下载');
      return false;
    }
  }

  function stamp() {
    var d = new Date();
    return d.getFullYear() + pad2(d.getMonth() + 1) + pad2(d.getDate()) + '-' + pad2(d.getHours()) + pad2(d.getMinutes());
  }

  /* ==================== 事件 ==================== */

  function onClick(e) {
    var el = e.target.closest ? e.target.closest('[data-act]') : null;
    if (!el) return;
    var act = el.getAttribute('data-act');
    var id = el.getAttribute('data-id');

    switch (act) {
      case 'tab': switchTab(el.getAttribute('data-tab')); break;

      case 'item':
        // 键盘回车 / 空格也能打开详情
        openDetail(id);
        break;

      case 'minus':
        e.stopPropagation();
        quickUse(id);
        break;

      case 'cat':
        ui.cat = el.getAttribute('data-cat');
        render();
        break;

      case 'clear-q':
        ui.q = '';
        render();
        break;

      case 'reset-filter':
        ui.q = '';
        ui.cat = 'all';
        render();
        break;

      case 'add':
        openForm(null);
        break;

      case 'demo':
        askConfirm('载入示例数据', '会用一份 12 种食材 + 24 天流水的示例覆盖当前数据，方便你快速看效果。', '确定载入', function () {
          FK.seedDemo();
          render();
          toast('示例数据已载入');
        });
        break;

      case 'preset': {
        var name = el.getAttribute('data-name');
        var p = PRESETS.filter(function (x) { return x.name === name; })[0];
        var form = $('#item-form');
        if (p && form) {
          form.elements.name.value = p.name;
          form.elements.category.value = p.category;
          form.elements.unit.value = p.unit;
          form.elements.expiry.value = FK.addDays(p.days);
          form.elements.qty.focus();
          form.elements.qty.select();
        }
        break;
      }

      case 'quick-date': {
        var f2 = $('#item-form');
        if (!f2) break;
        var d = +el.getAttribute('data-d');
        f2.elements.expiry.value = d ? FK.addDays(d) : '';
        break;
      }

      case 'sheet-close':
        closeSheet();
        break;

      case 'confirm':
        if (typeof pendingConfirm === 'function') {
          var fn = pendingConfirm;
          pendingConfirm = null;
          closeSheet();
          fn();
        } else {
          closeSheet();
        }
        break;

      case 'quick-use':
        quickUse(id);
        openDetail(id);
        break;

      case 'open-amount':
        openAmount(id, el.getAttribute('data-type'));
        break;

      case 'set-amount': {
        var f3 = $('#amount-form');
        if (f3) {
          f3.elements.amount.value = el.getAttribute('data-n');
          f3.elements.amount.focus();
        }
        break;
      }

      case 'edit':
        openForm(id);
        break;

      case 'delete': {
        var target = FK.item(id);
        if (!target) break;
        askConfirm('删除「' + esc(target.name) + '」', '食材会从库存里移除，已经产生的流水记录会保留（用于统计）。', '确认删除', function () {
          FK.removeItem(id);
          render();
          toast('已删除「' + esc(target.name) + '」');
        });
        break;
      }

      case 'undo': {
        var undone = FK.undoLog(id);
        if (undone) {
          render();
          toast('已撤销该笔记录，库存已还原');
        }
        break;
      }

      case 'log-filter':
        ui.logFilter = el.getAttribute('data-f');
        render();
        break;

      case 'range':
        ui.range = +el.getAttribute('data-d');
        render();
        break;

      case 'step': {
        var key = el.getAttribute('data-key');
        var delta = +el.getAttribute('data-d');
        var cur = FK.settings()[key] + delta;
        if (cur < 1 || cur > 60) break;
        FK.saveSettings({ [key]: cur });
        render();
        break;
      }

      case 'export-json':
        download('freshkeep-backup-' + stamp() + '.json', FK.exportJSON());
        toast('备份已导出');
        break;

      case 'export-csv':
        if (!FK.logs().length) { toast('还没有流水可以导出'); break; }
        download('freshkeep-logs-' + stamp() + '.csv', FK.exportCSV(), 'text/csv;charset=utf-8');
        toast('流水已导出为 CSV');
        break;

      case 'import-json': {
        var input = $('#import-file');
        if (input) input.click();
        break;
      }

      case 'clear':
        askConfirm('清空所有数据', '食材、流水、设置都会删掉，且无法恢复。建议先导出一份备份。', '确认清空', function () {
          FK.clearAll();
          render();
          toast('已清空');
        });
        break;
    }
  }

  function onSubmit(e) {
    var form = e.target;
    if (form.id === 'item-form') {
      e.preventDefault();
      saveForm(form);
    } else if (form.id === 'amount-form') {
      e.preventDefault();
      submitAmount(form);
    }
  }

  function onInput(e) {
    if (e.target.id === 'q') {
      ui.q = e.target.value;
      var list = $('#item-list');
      if (list) list.innerHTML = itemListHTML();
      var clear = $('.searchbar__clear');
      if (clear) clear.hidden = !ui.q;
    }
  }

  function onChange(e) {
    if (e.target.id === 'import-file') {
      var file = e.target.files && e.target.files[0];
      if (!file) return;
      var reader = new FileReader();
      reader.onload = function () {
        var r = FK.importJSON(String(reader.result));
        if (r.ok) {
          render();
          toast('已导入 ' + r.count + ' 种食材 / ' + r.logs + ' 条流水');
        } else {
          toast('导入失败：' + r.error);
        }
      };
      reader.onerror = function () { toast('读取文件失败'); };
      reader.readAsText(file);
      e.target.value = '';
    }
  }

  function onKeydown(e) {
    if (e.key === 'Escape') closeSheet();
    if (e.key === 'Enter' || e.key === ' ') {
      var card = e.target.closest && e.target.closest('.item');
      if (card && document.activeElement === card) {
        e.preventDefault();
        openDetail(card.getAttribute('data-id'));
      }
    }
  }

  /* ==================== 启动 ==================== */

  function registerSW() {
    if (!('serviceWorker' in navigator)) return;
    if (location.protocol !== 'http:' && location.protocol !== 'https:') return;
    window.addEventListener('load', function () {
      navigator.serviceWorker.register('sw.js').catch(function () { /* 离线增强失败不影响使用 */ });
    });
  }

  function boot() {
    FK.load();

    // 便于演示：?demo=1 且当前没有任何数据时载入示例
    if (/[?&]demo=1/.test(location.search) && !FK.items().length) FK.seedDemo();

    // 支持 #stats 之类的深链，刷新后仍停在同一个标签
    var hash = String(location.hash || '').replace('#', '');
    if (VIEWS[hash]) ui.tab = hash;

    render();

    document.addEventListener('click', onClick);
    document.addEventListener('submit', onSubmit);
    document.addEventListener('input', onInput);
    document.addEventListener('change', onChange);
    document.addEventListener('keydown', onKeydown);

    window.addEventListener('scroll', function () {
      document.querySelector('.app').classList.toggle('is-scrolled', window.scrollY > 4);
    }, { passive: true });

    registerSW();
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', boot);
  } else {
    boot();
  }
})();
