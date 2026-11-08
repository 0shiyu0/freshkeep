#!/usr/bin/env node
/**
 * 无需安装 PostgreSQL 的数据库验证脚本（PGlite = PG16 内核的 WASM 版）。
 *
 *   npm i --no-save @electric-sql/pglite
 *   node scripts/verify-db.mjs
 *
 * 做三件事：
 *   1. 执行 database/001_init.sql（剔除 PGlite 不支持的 pg_trgm 与其 GIN 索引）
 *   2. 执行 database/002_acceptance_check.sql（内含断言，抛异常即失败）
 *   3. 用一组独立数据回读关键数值，作为可读证据
 */
import { PGlite } from '@electric-sql/pglite'
import { readFileSync } from 'node:fs'
import { fileURLToPath } from 'node:url'
import { dirname, join } from 'node:path'

const ROOT = join(dirname(fileURLToPath(import.meta.url)), '..')
const read = (p) => readFileSync(join(ROOT, p), 'utf8')

const ddl = read('database/001_init.sql')
  .replace(/CREATE EXTENSION IF NOT EXISTS pg_trgm;.*/i, '')
  .replace(/CREATE INDEX[^;]*gin_trgm_ops[^;]*;/gi, '')

const db = await new PGlite()
let failed = false

try {
  await db.exec(ddl)
  const t = await db.query(
    `SELECT count(*)::int n FROM information_schema.tables
     WHERE table_schema='public' AND table_type='BASE TABLE'`
  )
  const v = await db.query(`SELECT count(*)::int n FROM information_schema.views WHERE table_schema='public'`)
  const f = await db.query(
    `SELECT count(*)::int n FROM information_schema.table_constraints
     WHERE constraint_type='FOREIGN KEY' AND table_schema='public'`
  )
  console.log(`✅ DDL 执行成功：${t.rows[0].n} 张表 / ${v.rows[0].n} 个视图 / ${f.rows[0].n} 个外键`)
  if (t.rows[0].n !== 25) throw new Error(`表数应为 25，实际 ${t.rows[0].n}`)
} catch (e) {
  console.error('❌ DDL 失败：', e.message)
  process.exit(1)
}

try {
  await db.exec(read('database/002_acceptance_check.sql'))
  console.log('✅ 验收脚本：全部断言通过（含负库存/重复分配/符号错误/孤儿快照四类拦截）')
} catch (e) {
  console.error('❌ 验收脚本失败：', e.message)
  failed = true
}

// 独立数据集回读，给出可读证据（与验收脚本互不影响）
const U = {
  user: '11111111-1111-1111-1111-111111111111',
  g: '22222222-2222-2222-2222-222222222222',
  kcal: '33333333-3333-3333-3333-333333333333',
  ing: '44444444-4444-4444-4444-444444444444',
  b1: '55555555-5555-5555-5555-555555555555',
  b2: '66666666-6666-6666-6666-666666666666',
  txp1: '77777777-7777-7777-7777-777777777777',
  txp2: '88888888-8888-8888-8888-888888888888',
  txc: '99999999-9999-9999-9999-999999999999',
  cons: 'aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa',
}

await db.exec(`
INSERT INTO users (id, username) VALUES ('${U.user}', 'owner');
INSERT INTO units (id, name, symbol, dimension, is_system) VALUES ('${U.g}', '克', 'g', 'weight', true);
INSERT INTO nutrition_definitions (id, code, name, unit) VALUES ('${U.kcal}', 'calories', '热量', 'kcal');
INSERT INTO ingredients (id, name, default_weight_unit_id) VALUES ('${U.ing}', '鸡胸肉', '${U.g}');
INSERT INTO ingredient_nutrition (ingredient_id, nutrition_definition_id, value, basis_amount, basis_unit_id, source)
  VALUES ('${U.ing}', '${U.kcal}', 165.0000, 100.000, '${U.g}', 'manual');
INSERT INTO batches (id, ingredient_id, batch_no, purchase_date, expiry_date, initial_weight, remaining_weight, purchase_cost, remaining_cost)
  VALUES ('${U.b1}', '${U.ing}', 'B1', '2026-11-01', '2026-11-10', 500, 500, 18.00, 18.00),
         ('${U.b2}', '${U.ing}', 'B2', '2026-11-02', '2026-11-20', 1000, 1000, 35.00, 35.00);
INSERT INTO inventory_transactions (id, transaction_no, type, ingredient_id, weight_delta, cost_delta)
  VALUES ('${U.txp1}', 'TX-P-1', 'purchase', '${U.ing}', 500, 18.00),
         ('${U.txp2}', 'TX-P-2', 'purchase', '${U.ing}', 1000, 35.00),
         ('${U.txc}',  'TX-C-1', 'consume',  '${U.ing}', -300, -10.80);
INSERT INTO transaction_allocations (transaction_id, batch_id, weight_delta, cost_delta, unit_cost)
  VALUES ('${U.txp1}', '${U.b1}', 500, 18.00, 0.0360),
         ('${U.txp2}', '${U.b2}', 1000, 35.00, 0.0350),
         ('${U.txc}',  '${U.b1}', -300, -10.80, 0.0360);
UPDATE batches SET remaining_weight = 200, remaining_cost = 7.20 WHERE id = '${U.b1}';
INSERT INTO consumption_records (id, consumption_no, ingredient_id, transaction_id, weight, weight_unit_id, cost, consumed_at)
  VALUES ('${U.cons}', 'CS-1', '${U.ing}', '${U.txc}', 300, '${U.g}', 10.80, now());
INSERT INTO consumption_nutrition (consumption_id, nutrition_definition_id, actual_value, unit, basis_snapshot)
  VALUES ('${U.cons}', '${U.kcal}', 495.0000, 'kcal',
          jsonb_build_object('value',165.0,'basis_amount',100,'basis_unit','g','source','manual','version',1));
`)

const one = async (sql) => (await db.query(sql)).rows[0]
const cost = await one(`SELECT cost::text FROM consumption_records`)
const bs = await db.query(`SELECT batch_no, remaining_weight::text w, remaining_cost::text c FROM batches ORDER BY batch_no`)
const total = await one(`SELECT SUM(remaining_cost)::text t FROM batches`)
const kcal = await one(`SELECT actual_value::text v FROM consumption_nutrition`)
const diff = await db.query(
  `SELECT bt.batch_no, v.diff_weight::text dw, v.diff_cost::text dc
   FROM v_batch_reconcile v JOIN batches bt ON bt.id = v.batch_id ORDER BY bt.batch_no`
)

console.log('   消耗 300g    → 成本', cost.cost, '元（期望 10.80）')
console.log('   批次余量     →', bs.rows.map((r) => `${r.batch_no} ${r.w}g/${r.c}元`).join('，'))
console.log('   剩余总成本   →', total.t, '元（期望 42.20）')
console.log('   营养快照     →', kcal.v, 'kcal（期望 495）')
console.log('   对账差异     →', diff.rows.map((r) => `${r.batch_no} ${r.dw}/${r.dc}`).join('，'))

if (!failed && cost.cost === '10.80' && total.t === '42.20' && kcal.v === '495.0000') {
  console.log('✅ 全部通过')
} else {
  console.error('❌ 数值不符，见上')
  process.exit(1)
}
