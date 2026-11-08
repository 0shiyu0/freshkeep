-- =============================================================================
-- 验收用例的数据库侧自检（PRD §11 的三条关键用例）
--
-- 用途：在真实 PostgreSQL 上验证「金额精度」「FEFO 顺序」「营养快照」三件事
--       在**表结构与约束层面**成立，并验证对账视图与约束真的能拦住错误。
--
-- 关键约定（本脚本本身就是范例）：**入库也要写流水 + 分配**。
--   只有这样 `batches.remaining_*` 才恒等于 Σ transaction_allocations.*，
--   对账视图的三个 diff 才会是 0。首次写本脚本时漏了入库分配，
--   立刻被 v_batch_reconcile 抓到（diff = 500g / 18.00 元）——这正是它的用途。
--
-- 执行：psql -d freshkeep -f database/002_acceptance_check.sql
-- =============================================================================

BEGIN;

DO $$
DECLARE
  v_unit_g   uuid;
  v_ing      uuid;
  v_b1       uuid;
  v_b2       uuid;
  v_tx       uuid;
  v_cons     uuid;
  v_kcal_def uuid;
  v_cost     numeric(14,2);
  v_left     numeric(14,2);
  v_w        numeric(14,3);
  v_w2       numeric(14,3);
  v_kcal     numeric(14,4);
  v_diff     record;
BEGIN
  -- ---------- 基础数据 ----------
  INSERT INTO users (username, display_name) VALUES ('owner', '主人');
  INSERT INTO units (name, symbol, dimension, is_system)
    VALUES ('克', 'g', 'weight', true) RETURNING id INTO v_unit_g;
  INSERT INTO nutrition_definitions (code, name, unit)
    VALUES ('calories', '热量', 'kcal') RETURNING id INTO v_kcal_def;
  INSERT INTO ingredients (name, default_weight_unit_id)
    VALUES ('鸡胸肉', v_unit_g) RETURNING id INTO v_ing;
  INSERT INTO ingredient_nutrition (ingredient_id, nutrition_definition_id, value,
                                    basis_amount, basis_unit_id, source)
    VALUES (v_ing, v_kcal_def, 165.0000, 100.000, v_unit_g, 'manual');

  -- =========================================================================
  -- 用例 1：批次成本（PRD §11 第 1 条）
  --   批次1 500g/18 元，批次2 1000g/35 元，消耗 300g
  --   期望：消耗成本 10.80 / 批次1 剩 200g·7.20 / 合计 42.20
  -- =========================================================================
  INSERT INTO batches (ingredient_id, batch_no, purchase_date, expiry_date,
                       initial_weight, remaining_weight, purchase_cost, remaining_cost)
    VALUES (v_ing, 'B1', '2026-11-01', '2026-11-10', 500, 500, 18.00, 18.00)
    RETURNING id INTO v_b1;
  INSERT INTO batches (ingredient_id, batch_no, purchase_date, expiry_date,
                       initial_weight, remaining_weight, purchase_cost, remaining_cost)
    VALUES (v_ing, 'B2', '2026-11-02', '2026-11-20', 1000, 1000, 35.00, 35.00)
    RETURNING id INTO v_b2;

  -- 入库也要落流水与分配（不变式 I1/I2 的要求）
  INSERT INTO inventory_transactions (transaction_no, type, ingredient_id, weight_delta, cost_delta)
    VALUES ('TX-P-0001', 'purchase', v_ing, 500, 18.00) RETURNING id INTO v_tx;
  INSERT INTO transaction_allocations (transaction_id, batch_id, weight_delta, cost_delta, unit_cost)
    VALUES (v_tx, v_b1, 500, 18.00, 0.0360);

  INSERT INTO inventory_transactions (transaction_no, type, ingredient_id, weight_delta, cost_delta)
    VALUES ('TX-P-0002', 'purchase', v_ing, 1000, 35.00) RETURNING id INTO v_tx;
  INSERT INTO transaction_allocations (transaction_id, batch_id, weight_delta, cost_delta, unit_cost)
    VALUES (v_tx, v_b2, 1000, 35.00, 0.0350);

  -- 消耗 300g：FEFO 命中到期更早的 B1
  v_cost := round(300 * (18.00 / 500), 2);   -- 10.80
  INSERT INTO inventory_transactions (transaction_no, type, ingredient_id, weight_delta, cost_delta)
    VALUES ('TX-C-0001', 'consume', v_ing, -300, -v_cost) RETURNING id INTO v_tx;
  INSERT INTO transaction_allocations (transaction_id, batch_id, weight_delta, cost_delta, unit_cost)
    VALUES (v_tx, v_b1, -300, -v_cost, 0.0360);
  UPDATE batches SET remaining_weight = remaining_weight - 300,
                     remaining_cost   = remaining_cost   - v_cost
   WHERE id = v_b1;

  INSERT INTO consumption_records (consumption_no, ingredient_id, transaction_id,
                                   weight, weight_unit_id, cost, consumed_at)
    VALUES ('CS-0001', v_ing, v_tx, 300, v_unit_g, v_cost, now()) RETURNING id INTO v_cons;

  -- 营养快照：165 kcal / 100g × 300g = 495
  v_kcal := round(300 * 165.0000 / 100.000, 4);
  INSERT INTO consumption_nutrition (consumption_id, nutrition_definition_id, actual_value, unit, basis_snapshot)
    VALUES (v_cons, v_kcal_def, v_kcal, 'kcal',
            jsonb_build_object('value', 165.0, 'basis_amount', 100, 'basis_unit', 'g',
                               'source', 'manual', 'version', 1));

  SELECT cost INTO v_cost FROM consumption_records WHERE id = v_cons;
  IF v_cost <> 10.80 THEN
    RAISE EXCEPTION '用例1失败：消耗成本应为 10.80，实际 %', v_cost;
  END IF;

  SELECT remaining_weight, remaining_cost INTO v_w, v_left FROM batches WHERE id = v_b1;
  IF v_w <> 200 OR v_left <> 7.20 THEN
    RAISE EXCEPTION '用例1失败：批次1 应剩 200g / 7.20 元，实际 % / %', v_w, v_left;
  END IF;

  SELECT SUM(remaining_cost) INTO v_left FROM batches WHERE ingredient_id = v_ing;
  IF v_left <> 42.20 THEN
    RAISE EXCEPTION '用例1失败：剩余库存成本应为 42.20，实际 %', v_left;
  END IF;

  IF v_kcal <> 495.0000 THEN
    RAISE EXCEPTION '用例3失败：营养快照应为 495 kcal，实际 %', v_kcal;
  END IF;

  -- 本阶段就要对账：缓存与分配必须已经一致
  FOR v_diff IN SELECT * FROM v_batch_reconcile WHERE ingredient_id = v_ing LOOP
    IF v_diff.diff_quantity <> 0 OR v_diff.diff_weight <> 0 OR v_diff.diff_cost <> 0 THEN
      RAISE EXCEPTION '用例1对账失败：批次 % 差异 (% / % / %)',
        v_diff.batch_id, v_diff.diff_quantity, v_diff.diff_weight, v_diff.diff_cost;
    END IF;
  END LOOP;

  RAISE NOTICE '用例1（批次成本）通过：成本 10.80 / 批次1 剩 200g·7.20 / 合计 42.20';
  RAISE NOTICE '用例3（营养快照）通过：300g × 165kcal/100g = 495 kcal';

  -- =========================================================================
  -- 用例 2：FEFO（PRD §11 第 2 条，独立数据集）
  --   A 500g 到期 11-10；B 1000g 到期 11-20；消耗 600g
  --   期望：A 清零、B 剩 900g
  -- =========================================================================
  DELETE FROM consumption_nutrition WHERE consumption_id = v_cons;
  DELETE FROM consumption_records WHERE id = v_cons;
  DELETE FROM transaction_allocations WHERE batch_id IN (v_b1, v_b2);
  DELETE FROM inventory_transactions WHERE ingredient_id = v_ing;
  DELETE FROM batches WHERE ingredient_id = v_ing;

  INSERT INTO batches (ingredient_id, batch_no, purchase_date, expiry_date,
                       initial_weight, remaining_weight, purchase_cost, remaining_cost)
    VALUES (v_ing, 'A', '2026-11-01', '2026-11-10', 500, 500, 18.00, 18.00) RETURNING id INTO v_b1;
  INSERT INTO batches (ingredient_id, batch_no, purchase_date, expiry_date,
                       initial_weight, remaining_weight, purchase_cost, remaining_cost)
    VALUES (v_ing, 'B', '2026-11-02', '2026-11-20', 1000, 1000, 35.00, 35.00) RETURNING id INTO v_b2;

  INSERT INTO inventory_transactions (transaction_no, type, ingredient_id, weight_delta, cost_delta)
    VALUES ('TX-P-0003', 'purchase', v_ing, 1500, 53.00) RETURNING id INTO v_tx;
  INSERT INTO transaction_allocations (transaction_id, batch_id, weight_delta, cost_delta, unit_cost)
    VALUES (v_tx, v_b1, 500, 18.00, 0.0360),
           (v_tx, v_b2, 1000, 35.00, 0.0350);

  -- 消耗 600g：A 全部 500g + B 的 100g
  INSERT INTO inventory_transactions (transaction_no, type, ingredient_id, weight_delta, cost_delta)
    VALUES ('TX-C-0002', 'consume', v_ing, -600, -21.50) RETURNING id INTO v_tx;
  INSERT INTO transaction_allocations (transaction_id, batch_id, weight_delta, cost_delta, unit_cost)
    VALUES (v_tx, v_b1, -500, -18.00, 0.0360),
           (v_tx, v_b2, -100, -3.50,  0.0350);

  UPDATE batches SET remaining_weight = 0,   remaining_cost = 0    WHERE id = v_b1;
  UPDATE batches SET remaining_weight = 900, remaining_cost = 31.50 WHERE id = v_b2;

  SELECT remaining_weight INTO v_w  FROM batches WHERE id = v_b1;
  SELECT remaining_weight INTO v_w2 FROM batches WHERE id = v_b2;
  IF v_w <> 0 OR v_w2 <> 900 THEN
    RAISE EXCEPTION '用例2失败：A 应清零、B 应剩 900g，实际 % / %', v_w, v_w2;
  END IF;

  FOR v_diff IN SELECT * FROM v_batch_reconcile WHERE ingredient_id = v_ing LOOP
    IF v_diff.diff_quantity <> 0 OR v_diff.diff_weight <> 0 OR v_diff.diff_cost <> 0 THEN
      RAISE EXCEPTION '用例2对账失败：批次 % 差异 (% / % / %)',
        v_diff.batch_id, v_diff.diff_quantity, v_diff.diff_weight, v_diff.diff_cost;
    END IF;
  END LOOP;

  RAISE NOTICE '用例2（FEFO）通过：A 清零、B 剩 900g；对账三个 diff 均为 0';

  -- =========================================================================
  -- 约束反向验证：错误必须被数据库拦住
  -- =========================================================================
  BEGIN
    UPDATE batches SET remaining_weight = -1 WHERE id = v_b2;
    RAISE EXCEPTION '约束缺失：remaining_weight 允许负数';
  EXCEPTION WHEN check_violation THEN
    RAISE NOTICE '约束通过：remaining_weight 负值被 CHECK 拒绝';
  END;

  BEGIN
    INSERT INTO transaction_allocations (transaction_id, batch_id, weight_delta)
      VALUES (v_tx, v_b2, -1);
    RAISE EXCEPTION '约束缺失：同一流水对同一批次允许重复分配';
  EXCEPTION WHEN unique_violation THEN
    RAISE NOTICE '约束通过：(transaction_id, batch_id) 重复分配被拒';
  END;

  BEGIN
    INSERT INTO inventory_transactions (transaction_no, type, ingredient_id, weight_delta)
      VALUES ('TX-BAD-1', 'consume', v_ing, 100);   -- 消耗却是正数
    RAISE EXCEPTION '约束缺失：consume 允许正 delta';
  EXCEPTION WHEN check_violation THEN
    RAISE NOTICE '约束通过：consume 的正 delta 被 ck_tx_sign 拒绝';
  END;

  BEGIN
    INSERT INTO consumption_nutrition (consumption_id, nutrition_definition_id, actual_value, unit, basis_snapshot)
      VALUES (gen_random_uuid(), v_kcal_def, 1, 'kcal', '{}'::jsonb);
    RAISE EXCEPTION '约束缺失：营养快照允许指向不存在的消耗';
  EXCEPTION WHEN foreign_key_violation THEN
    RAISE NOTICE '约束通过：营养快照的外键拒绝孤儿记录';
  END;

  RAISE NOTICE '=== 全部验收用例通过 ===';
END $$;

ROLLBACK;   -- 自检数据不落库
