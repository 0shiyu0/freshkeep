-- =============================================================================
-- 鲜度 FreshKeep · 数据库初始化脚本（权威 DDL）
--
-- 说明：
--   1. 本文件是数据库结构的**唯一真相**。Alembic 迁移只做版本登记，不另写 DDL。
--   2. 金额 NUMERIC(14,2)、数量/重量 NUMERIC(14,3)、营养 NUMERIC(14,4)、时间 TIMESTAMPTZ（UTC 存储）。
--   3. 所有历史表外键 ON DELETE RESTRICT：历史不可物理删除（PRD §3.2）。
--   4. 枚举一律用 text + CHECK，不用 PG ENUM 类型（便于后续追加取值而不锁表）。
--
-- 执行：psql -h localhost -U freshkeep -d freshkeep -f database/001_init.sql
-- =============================================================================

BEGIN;

CREATE EXTENSION IF NOT EXISTS pg_trgm;      -- 食材名模糊搜索

-- -----------------------------------------------------------------------------
-- 0. 通用触发器：自动维护 updated_at
-- -----------------------------------------------------------------------------
CREATE OR REPLACE FUNCTION set_updated_at() RETURNS trigger AS $$
BEGIN
  NEW.updated_at = now();
  RETURN NEW;
END;
$$ LANGUAGE plpgsql;

-- =============================================================================
-- A. 账号、设备与文件
-- =============================================================================

-- A1. 用户。个人自用，只有一行 owner；password_hash 为将来预留，当前恒为 NULL。
CREATE TABLE users (
  id            uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  username      text NOT NULL UNIQUE,
  display_name  text NOT NULL DEFAULT '',
  password_hash text,
  created_at    timestamptz NOT NULL DEFAULT now(),
  updated_at    timestamptz NOT NULL DEFAULT now()
);
COMMENT ON TABLE users IS '用户。单用户系统，仅一行 owner，承担审计归属';
CREATE TRIGGER trg_users_updated BEFORE UPDATE ON users
  FOR EACH ROW EXECUTE FUNCTION set_updated_at();

-- A2. 已授权设备（配对码换来的令牌，只存哈希）
CREATE TABLE devices (
  id           uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  user_id      uuid NOT NULL REFERENCES users(id) ON DELETE RESTRICT,
  name         text NOT NULL,
  platform     text NOT NULL CHECK (platform IN ('web', 'ios', 'android')),
  token_hash   text NOT NULL UNIQUE,
  ip           text,
  user_agent   text,
  created_at   timestamptz NOT NULL DEFAULT now(),
  last_seen_at timestamptz,
  revoked_at   timestamptz
);
COMMENT ON TABLE devices IS '设备令牌。Web 走 Cookie、App 走 Bearer，均映射到本表';
CREATE INDEX ix_devices_active ON devices (user_id) WHERE revoked_at IS NULL;

-- A3. 一次性配对码
CREATE TABLE pair_codes (
  id         uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  code_hash  text NOT NULL UNIQUE,
  expires_at timestamptz NOT NULL,
  used_at    timestamptz,
  created_at timestamptz NOT NULL DEFAULT now()
);
COMMENT ON TABLE pair_codes IS '一次性配对码，10 分钟过期、用后即废，只存 SHA-256';
CREATE INDEX ix_pair_codes_open ON pair_codes (expires_at) WHERE used_at IS NULL;

-- A4. 文件资源（食材图片、导出文件、AI 识别原图）
CREATE TABLE file_assets (
  id           uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  storage_path text NOT NULL,
  mime_type    text NOT NULL,
  size_bytes   bigint NOT NULL CHECK (size_bytes >= 0),
  checksum     text NOT NULL,              -- sha256，用于去重与完整性校验
  category     text NOT NULL DEFAULT 'image'
               CHECK (category IN ('image', 'export', 'backup', 'temp')),
  created_at   timestamptz NOT NULL DEFAULT now(),
  UNIQUE (checksum)
);
COMMENT ON TABLE file_assets IS '文件资源。checksum 唯一，实现同图不重复存储';

-- =============================================================================
-- B. 基础档案
-- =============================================================================

-- B1. 食材分类（支持两级）
CREATE TABLE categories (
  id         uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  name       text NOT NULL,
  parent_id  uuid REFERENCES categories (id) ON DELETE RESTRICT,
  sort_order integer NOT NULL DEFAULT 0,
  is_active  boolean NOT NULL DEFAULT true,
  created_at timestamptz NOT NULL DEFAULT now()
);
COMMENT ON TABLE categories IS '食材分类。同级不重名由两个 partial unique index 保证';
-- 同级不重名；NULL 不参与唯一比较，所以根节点单独一条索引
CREATE UNIQUE INDEX ux_categories_root_name  ON categories (name) WHERE parent_id IS NULL;
CREATE UNIQUE INDEX ux_categories_child_name ON categories (parent_id, name) WHERE parent_id IS NOT NULL;

-- B2. 计量单位。dimension 决定能否互相换算：quantity 与 weight 不可混用
CREATE TABLE units (
  id         uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  name       text NOT NULL UNIQUE,
  symbol     text NOT NULL DEFAULT '',
  dimension  text NOT NULL CHECK (dimension IN ('quantity', 'weight', 'volume')),
  precision  smallint NOT NULL DEFAULT 3 CHECK (precision BETWEEN 0 AND 4),
  is_system  boolean NOT NULL DEFAULT false,
  created_at timestamptz NOT NULL DEFAULT now()
);
COMMENT ON TABLE units IS '计量单位。dimension 隔离数量/重量/体积，禁止跨维度相加';

-- B3. 储存位置
CREATE TABLE storage_locations (
  id          uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  name        text NOT NULL UNIQUE,
  description text NOT NULL DEFAULT '',
  sort_order  integer NOT NULL DEFAULT 0
);
COMMENT ON TABLE storage_locations IS '储存位置：冷藏 / 冷冻 / 常温 / 橱柜 …';

-- B4. 食材档案（"是什么"，与批次的"哪一次买的"分离）
CREATE TABLE ingredients (
  id                       uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  name                     text NOT NULL,
  name_pinyin              text NOT NULL DEFAULT '',   -- 全拼，写入时由后端生成
  name_initials            text NOT NULL DEFAULT '',   -- 首字母，写入时由后端生成
  category_id              uuid REFERENCES categories (id) ON DELETE RESTRICT,
  image_asset_id           uuid REFERENCES file_assets (id) ON DELETE SET NULL,
  brand                    text NOT NULL DEFAULT '',
  specification            text NOT NULL DEFAULT '',
  default_quantity_unit_id uuid REFERENCES units (id) ON DELETE RESTRICT,
  default_weight_unit_id   uuid REFERENCES units (id) ON DELETE RESTRICT,
  -- 1 个数量单位 = N 克。NULL 表示"数量与重量无换算关系"，此时禁止自动换算
  default_unit_weight      numeric(14,3) CHECK (default_unit_weight > 0),
  -- 营养基准的默认值，仅用于录入时预填，**不参与计算**（计算基准见 ingredient_nutrition）
  nutrition_basis_amount   numeric(14,3) CHECK (nutrition_basis_amount > 0),
  nutrition_basis_unit_id  uuid REFERENCES units (id) ON DELETE RESTRICT,
  -- 食材的默认存放位置（批次可覆盖）；PRD §4.3 表 65「默认储存位置」
  default_storage_location_id uuid REFERENCES storage_locations (id) ON DELETE SET NULL,
  minimum_quantity         numeric(14,3) NOT NULL DEFAULT 0 CHECK (minimum_quantity >= 0),
  minimum_weight           numeric(14,3) NOT NULL DEFAULT 0 CHECK (minimum_weight >= 0),
  note                     text NOT NULL DEFAULT '',
  is_active                boolean NOT NULL DEFAULT true,
  created_at               timestamptz NOT NULL DEFAULT now(),
  updated_at               timestamptz NOT NULL DEFAULT now()
);
COMMENT ON TABLE ingredients IS '食材档案。不含任何库存数字，库存全部由批次与流水推导';
CREATE INDEX ix_ingredients_active  ON ingredients (is_active, category_id);
CREATE INDEX ix_ingredients_name_trgm ON ingredients USING gin (name gin_trgm_ops);
CREATE INDEX ix_ingredients_py_trgm   ON ingredients USING gin (name_pinyin gin_trgm_ops);
CREATE TRIGGER trg_ingredients_updated BEFORE UPDATE ON ingredients
  FOR EACH ROW EXECUTE FUNCTION set_updated_at();

-- B5. 条码
CREATE TABLE ingredient_barcodes (
  id            uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  ingredient_id uuid NOT NULL REFERENCES ingredients (id) ON DELETE CASCADE,
  barcode       text NOT NULL,
  barcode_type  text NOT NULL DEFAULT 'ean13'
                CHECK (barcode_type IN ('ean8', 'ean13', 'upc', 'code128', 'qr', 'other')),
  created_at    timestamptz NOT NULL DEFAULT now(),
  UNIQUE (barcode)                                  -- 一个条码只对应一个食材
);
COMMENT ON TABLE ingredient_barcodes IS '食材条码。全局唯一，扫码即定位食材';

-- B6. 营养项目定义
CREATE TABLE nutrition_definitions (
  id         uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  code       text NOT NULL UNIQUE,     -- calories / protein / fat / carbs / fiber / sodium
  name       text NOT NULL,
  unit       text NOT NULL,            -- kcal / g / mg
  sort_order integer NOT NULL DEFAULT 0,
  is_active  boolean NOT NULL DEFAULT true
);
COMMENT ON TABLE nutrition_definitions IS '营养项目字典。项目可扩展，不需改表结构';

-- B7. 食材营养档案（版本化：改档案不覆盖历史）
CREATE TABLE ingredient_nutrition (
  id                      uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  ingredient_id           uuid NOT NULL REFERENCES ingredients (id) ON DELETE CASCADE,
  nutrition_definition_id uuid NOT NULL REFERENCES nutrition_definitions (id) ON DELETE RESTRICT,
  value                   numeric(14,4) NOT NULL CHECK (value >= 0),
  basis_amount            numeric(14,3) NOT NULL CHECK (basis_amount > 0),  -- 如 100
  basis_unit_id           uuid NOT NULL REFERENCES units (id) ON DELETE RESTRICT,
  source                  text NOT NULL DEFAULT 'manual'
                          CHECK (source IN ('manual', 'packaging_label', 'database')),
  version                 integer NOT NULL DEFAULT 1,
  is_current              boolean NOT NULL DEFAULT true,
  created_at              timestamptz NOT NULL DEFAULT now()
);
COMMENT ON TABLE ingredient_nutrition IS
  '食材营养档案。每个营养项目同时只有一条 is_current；改值 = 新版本行 + 旧行置 false';
CREATE UNIQUE INDEX ux_ing_nutrition_current
  ON ingredient_nutrition (ingredient_id, nutrition_definition_id) WHERE is_current;

-- B8. 营养目标
CREATE TABLE nutrition_targets (
  id                      uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  nutrition_definition_id uuid NOT NULL REFERENCES nutrition_definitions (id) ON DELETE CASCADE,
  target_value            numeric(14,4) NOT NULL CHECK (target_value > 0),
  period                  text NOT NULL DEFAULT 'daily' CHECK (period IN ('daily', 'weekly')),
  effective_from          date NOT NULL DEFAULT current_date,
  created_at              timestamptz NOT NULL DEFAULT now(),
  UNIQUE (nutrition_definition_id, period, effective_from)
);
COMMENT ON TABLE nutrition_targets IS '营养目标。按生效日期留痕，历史统计用当时目标';

-- =============================================================================
-- C. 库存核心（流水为唯一真相，批次余额是缓存）
-- =============================================================================

-- C1. 库存批次：一次采购一批，永不覆盖历史
CREATE TABLE batches (
  id                  uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  ingredient_id       uuid NOT NULL REFERENCES ingredients (id) ON DELETE RESTRICT,
  batch_no            text NOT NULL,
  purchase_date       date NOT NULL,
  production_date     date,
  expiry_date         date,
  opened_date         date,
  storage_location_id uuid REFERENCES storage_locations (id) ON DELETE RESTRICT,
  initial_quantity    numeric(14,3) NOT NULL DEFAULT 0 CHECK (initial_quantity >= 0),
  remaining_quantity  numeric(14,3) NOT NULL DEFAULT 0 CHECK (remaining_quantity >= 0),
  initial_weight      numeric(14,3) NOT NULL DEFAULT 0 CHECK (initial_weight >= 0),
  remaining_weight    numeric(14,3) NOT NULL DEFAULT 0 CHECK (remaining_weight >= 0),
  purchase_cost       numeric(14,2) NOT NULL DEFAULT 0 CHECK (purchase_cost >= 0),
  remaining_cost      numeric(14,2) NOT NULL DEFAULT 0 CHECK (remaining_cost >= 0),
  status              text NOT NULL DEFAULT 'active'
                      CHECK (status IN ('active', 'depleted', 'void')),
  note                text NOT NULL DEFAULT '',
  created_at          timestamptz NOT NULL DEFAULT now(),
  updated_at          timestamptz NOT NULL DEFAULT now(),
  CONSTRAINT ck_batch_remaining_le_initial CHECK (
    remaining_quantity <= initial_quantity
    AND remaining_weight <= initial_weight
    AND remaining_cost <= purchase_cost
  ),
  CONSTRAINT ck_batch_expiry_after_production CHECK (
    expiry_date IS NULL OR production_date IS NULL OR expiry_date >= production_date
  )
);
COMMENT ON TABLE batches IS
  '库存批次。remaining_* 是可重算缓存，权威来源是 transaction_allocations 的聚合（每日对账）';
COMMENT ON COLUMN batches.remaining_cost IS '剩余成本缓存。每次扣减按 分摊成本 递减，扣完必须为 0（尾差结清）';
CREATE UNIQUE INDEX ux_batches_no ON batches (ingredient_id, batch_no);
-- FEFO 取用顺序：到期日升序 → 无到期日排最后 → 同到期日按采购日 → 再按 id
CREATE INDEX ix_batches_fefo ON batches (ingredient_id, expiry_date NULLS LAST, purchase_date, id)
  WHERE status = 'active';
CREATE INDEX ix_batches_expiring ON batches (expiry_date)
  WHERE status = 'active' AND remaining_weight > 0;
CREATE TRIGGER trg_batches_updated BEFORE UPDATE ON batches
  FOR EACH ROW EXECUTE FUNCTION set_updated_at();

-- C2. 库存流水：所有库存变化的唯一入口
CREATE TABLE inventory_transactions (
  id                  uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  transaction_no      text NOT NULL UNIQUE,
  type                text NOT NULL
                      CHECK (type IN ('purchase', 'consume', 'spoilage', 'adjustment', 'reverse')),
  ingredient_id       uuid NOT NULL REFERENCES ingredients (id) ON DELETE RESTRICT,
  quantity_delta      numeric(14,3) NOT NULL DEFAULT 0,
  weight_delta        numeric(14,3) NOT NULL DEFAULT 0,
  cost_delta          numeric(14,2) NOT NULL DEFAULT 0,
  related_object_type text CHECK (related_object_type IN
                      ('consumption', 'spoilage', 'adjustment', 'transaction', 'batch')),
  related_object_id   uuid,
  reason              text NOT NULL DEFAULT '',
  device_id           uuid REFERENCES devices (id) ON DELETE SET NULL,
  created_at          timestamptz NOT NULL DEFAULT now(),
  -- 符号约束：入库只能为正，消耗/报损只能为负，调整与冲销不受限
  CONSTRAINT ck_tx_sign CHECK (
    (type = 'purchase' AND quantity_delta >= 0 AND weight_delta >= 0 AND cost_delta >= 0)
    OR (type IN ('consume', 'spoilage') AND quantity_delta <= 0 AND weight_delta <= 0 AND cost_delta <= 0)
    OR type IN ('adjustment', 'reverse')
  )
);
COMMENT ON TABLE inventory_transactions IS
  '库存流水。余额 = 初始 + 全部流水之和；撤销通过新增 reverse 流水实现，不删原记录';
CREATE INDEX ix_tx_ingredient_time ON inventory_transactions (ingredient_id, created_at DESC);
CREATE INDEX ix_tx_time            ON inventory_transactions (created_at DESC);
CREATE INDEX ix_tx_related         ON inventory_transactions (related_object_type, related_object_id);

-- C3. 流水 → 批次分配（多批次消耗的落点，对账与撤销的依据）
CREATE TABLE transaction_allocations (
  id             uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  transaction_id uuid NOT NULL REFERENCES inventory_transactions (id) ON DELETE CASCADE,
  batch_id       uuid NOT NULL REFERENCES batches (id) ON DELETE RESTRICT,
  quantity_delta numeric(14,3) NOT NULL DEFAULT 0,
  weight_delta   numeric(14,3) NOT NULL DEFAULT 0,
  cost_delta     numeric(14,2) NOT NULL DEFAULT 0,
  unit_cost      numeric(14,4),      -- 快照：本次使用的批次单位成本（元/g 或 元/个）
  created_at     timestamptz NOT NULL DEFAULT now(),
  UNIQUE (transaction_id, batch_id)  -- 同一笔流水对同一批次只有一条分配
);
COMMENT ON TABLE transaction_allocations IS
  '流水对批次的分配。SUM(weight_delta) 按 batch 聚合必须等于批次消耗总量；对账与撤销的唯一依据';
CREATE INDEX ix_alloc_batch ON transaction_allocations (batch_id);
CREATE INDEX ix_alloc_tx    ON transaction_allocations (transaction_id);

-- C4. 消耗记录（一次消耗 = 一条头记录 + N 条批次分配 + N 条营养快照）
CREATE TABLE consumption_records (
  id                         uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  consumption_no             text NOT NULL UNIQUE,
  ingredient_id              uuid NOT NULL REFERENCES ingredients (id) ON DELETE RESTRICT,
  transaction_id             uuid NOT NULL UNIQUE REFERENCES inventory_transactions (id) ON DELETE RESTRICT,
  quantity                   numeric(14,3) NOT NULL DEFAULT 0 CHECK (quantity >= 0),
  weight                     numeric(14,3) NOT NULL DEFAULT 0 CHECK (weight >= 0),
  quantity_unit_id           uuid REFERENCES units (id) ON DELETE RESTRICT,
  weight_unit_id             uuid REFERENCES units (id) ON DELETE RESTRICT,
  cost                       numeric(14,2) NOT NULL DEFAULT 0 CHECK (cost >= 0),
  consumed_at                timestamptz NOT NULL,
  note                       text NOT NULL DEFAULT '',
  status                     text NOT NULL DEFAULT 'completed'
                             CHECK (status IN ('completed', 'reversed')),
  reversed_by_transaction_id uuid REFERENCES inventory_transactions (id) ON DELETE RESTRICT,
  device_id                  uuid REFERENCES devices (id) ON DELETE SET NULL,
  idempotency_key            text,
  created_at                 timestamptz NOT NULL DEFAULT now(),
  CONSTRAINT ck_consumption_has_amount CHECK (quantity > 0 OR weight > 0),
  CONSTRAINT ck_consumption_reversed CHECK (
    (status = 'completed' AND reversed_by_transaction_id IS NULL)
    OR (status = 'reversed' AND reversed_by_transaction_id IS NOT NULL)
  )
);
COMMENT ON TABLE consumption_records IS
  '消耗记录头。transaction_id 1:1 指向库存流水；status=reversed 时保留原记录并新增 reverse 流水';
CREATE INDEX ix_cons_time       ON consumption_records (consumed_at DESC);
CREATE INDEX ix_cons_ingredient ON consumption_records (ingredient_id, consumed_at DESC);
CREATE UNIQUE INDEX ux_cons_idem ON consumption_records (idempotency_key)
  WHERE idempotency_key IS NOT NULL;

-- C5. 消耗营养快照（历史不可变）
CREATE TABLE consumption_nutrition (
  id                      uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  consumption_id          uuid NOT NULL REFERENCES consumption_records (id) ON DELETE CASCADE,
  nutrition_definition_id uuid NOT NULL REFERENCES nutrition_definitions (id) ON DELETE RESTRICT,
  actual_value            numeric(14,4) NOT NULL CHECK (actual_value >= 0),
  unit                    text NOT NULL,
  basis_snapshot          jsonb NOT NULL,
  created_at              timestamptz NOT NULL DEFAULT now(),
  UNIQUE (consumption_id, nutrition_definition_id)
);
COMMENT ON TABLE consumption_nutrition IS
  '消耗时的营养快照。basis_snapshot 记录当时的 value/basis/source/version，改档案不影响历史统计';
CREATE INDEX ix_cons_nutrition_def ON consumption_nutrition (nutrition_definition_id);

-- =============================================================================
-- D. 采购清单与菜谱
-- =============================================================================

CREATE TABLE shopping_lists (
  id           uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  name         text NOT NULL,
  status       text NOT NULL DEFAULT 'open' CHECK (status IN ('open', 'completed', 'archived')),
  created_at   timestamptz NOT NULL DEFAULT now(),
  completed_at timestamptz
);
COMMENT ON TABLE shopping_lists IS '采购清单（一次采购一张单）';

CREATE TABLE shopping_list_items (
  id                  uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  shopping_list_id    uuid NOT NULL REFERENCES shopping_lists (id) ON DELETE CASCADE,
  ingredient_id       uuid REFERENCES ingredients (id) ON DELETE SET NULL,
  free_text_name      text NOT NULL DEFAULT '',   -- 尚未建档的食材允许只写名字
  suggested_quantity  numeric(14,3),
  suggested_weight    numeric(14,3),
  unit_id             uuid REFERENCES units (id) ON DELETE RESTRICT,
  source              text NOT NULL DEFAULT 'manual'
                      CHECK (source IN ('manual', 'low_stock', 'recipe', 'expiring')),
  is_completed        boolean NOT NULL DEFAULT false,
  note                text NOT NULL DEFAULT '',
  CONSTRAINT ck_sli_target CHECK (ingredient_id IS NOT NULL OR free_text_name <> '')
);
COMMENT ON TABLE shopping_list_items IS
  '采购清单项。source 保留自动来源，用户删除后不再自动加回（P2 的 dismissed_at 扩展位）';
CREATE INDEX ix_sli_list ON shopping_list_items (shopping_list_id, is_completed);

CREATE TABLE recipes (
  id               uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  name             text NOT NULL,
  image_asset_id   uuid REFERENCES file_assets (id) ON DELETE SET NULL,
  category         text NOT NULL DEFAULT '',
  servings         numeric(6,2) NOT NULL DEFAULT 1 CHECK (servings > 0),
  duration_minutes integer CHECK (duration_minutes >= 0),
  steps            text NOT NULL DEFAULT '',
  note             text NOT NULL DEFAULT '',
  created_at       timestamptz NOT NULL DEFAULT now()
);
COMMENT ON TABLE recipes IS '菜谱。V1.2 仅用于库存匹配与采购建议，不自动扣库存';

CREATE TABLE recipe_steps (
  id               uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  recipe_id        uuid NOT NULL REFERENCES recipes (id) ON DELETE CASCADE,
  seq              integer NOT NULL CHECK (seq >= 0),
  text             text NOT NULL,
  duration_minutes integer CHECK (duration_minutes >= 0),
  created_at       timestamptz NOT NULL DEFAULT now(),
  UNIQUE (recipe_id, seq)
);

CREATE TABLE recipe_items (
  id            uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  recipe_id     uuid NOT NULL REFERENCES recipes (id) ON DELETE CASCADE,
  ingredient_id uuid NOT NULL REFERENCES ingredients (id) ON DELETE RESTRICT,
  quantity      numeric(14,3) CHECK (quantity >= 0),
  weight        numeric(14,3) CHECK (weight >= 0),
  unit_id       uuid REFERENCES units (id) ON DELETE RESTRICT,
  note          text NOT NULL DEFAULT '',
  CONSTRAINT ck_recipe_item_amount CHECK (quantity IS NOT NULL OR weight IS NOT NULL)
);
COMMENT ON TABLE recipe_items IS '菜谱所需食材。数量与重量二选一或同时给出';

-- =============================================================================
-- E. 系统
-- =============================================================================

CREATE TABLE notifications (
  id            uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  type          text NOT NULL CHECK (type IN ('expiring', 'expired', 'low_stock', 'backup')),
  batch_id      uuid REFERENCES batches (id) ON DELETE CASCADE,
  ingredient_id uuid REFERENCES ingredients (id) ON DELETE CASCADE,
  scheduled_at  timestamptz NOT NULL,
  sent_at       timestamptz,
  status        text NOT NULL DEFAULT 'pending'
                CHECK (status IN ('pending', 'scheduled', 'sent', 'skipped')),
  payload       jsonb NOT NULL DEFAULT '{}'::jsonb,
  created_at    timestamptz NOT NULL DEFAULT now()
);
COMMENT ON TABLE notifications IS
  '提醒排程记录。无 PWA，系统通知由 App 本地通知承载，本表记录排程与送达状态';
CREATE INDEX ix_notifications_due ON notifications (scheduled_at) WHERE status = 'pending';

CREATE TABLE app_settings (
  key        text PRIMARY KEY,
  value_json jsonb NOT NULL,
  updated_at timestamptz NOT NULL DEFAULT now()
);
COMMENT ON TABLE app_settings IS '系统设置键值对：提醒档位、时区、货币、主题等';

CREATE TABLE audit_logs (
  id         bigserial PRIMARY KEY,
  user_id    uuid REFERENCES users (id) ON DELETE SET NULL,
  device_id  uuid REFERENCES devices (id) ON DELETE SET NULL,
  action     text NOT NULL,
  object_type text NOT NULL,
  object_id  uuid,
  before_json jsonb,
  after_json  jsonb,
  created_at timestamptz NOT NULL DEFAULT now()
);
COMMENT ON TABLE audit_logs IS '操作审计与对账差异记录（action=reconcile_mismatch 时 before/after 为差异明细）';
CREATE INDEX ix_audit_time   ON audit_logs (created_at DESC);
CREATE INDEX ix_audit_object ON audit_logs (object_type, object_id);

CREATE TABLE idempotency_keys (
  key           text PRIMARY KEY,
  request_hash  text NOT NULL,
  status_code   integer NOT NULL,
  response_json jsonb NOT NULL,
  created_at    timestamptz NOT NULL DEFAULT now()
);
COMMENT ON TABLE idempotency_keys IS
  '写操作幂等。同 key 同 body 直接返回原响应；同 key 不同 body 返回 DUPLICATE_REQUEST；24h 清理';
CREATE INDEX ix_idem_created ON idempotency_keys (created_at);

-- =============================================================================
-- F. 视图（首页 / 库存页 / 采购建议统一只读这里）
-- =============================================================================

CREATE VIEW v_inventory AS
SELECT
  i.id                                                   AS ingredient_id,
  i.name,
  i.category_id,
  COALESCE(SUM(b.remaining_quantity), 0)                 AS total_quantity,
  COALESCE(SUM(b.remaining_weight), 0)                   AS total_weight,
  COALESCE(SUM(b.remaining_cost), 0)                     AS total_cost,
  COUNT(b.id) FILTER (WHERE b.remaining_weight > 0
                        OR b.remaining_quantity > 0)     AS batch_count,
  MIN(b.expiry_date) FILTER (WHERE b.remaining_weight > 0
                               OR b.remaining_quantity > 0) AS nearest_expiry,
  (COALESCE(SUM(b.remaining_quantity), 0) <= i.minimum_quantity
   AND COALESCE(SUM(b.remaining_weight), 0) <= i.minimum_weight) AS is_low_stock
FROM ingredients i
LEFT JOIN batches b ON b.ingredient_id = i.id AND b.status = 'active'
WHERE i.is_active
GROUP BY i.id, i.name, i.category_id, i.minimum_quantity, i.minimum_weight;
COMMENT ON VIEW v_inventory IS '食材级库存汇总。所有页面与采购建议统一读此视图';

-- 批次余额与流水分配的对账视图：任何非零差异都需要修正缓存
CREATE VIEW v_batch_reconcile AS
SELECT
  b.id                                   AS batch_id,
  b.ingredient_id,
  b.remaining_quantity,
  COALESCE(SUM(a.quantity_delta), 0)     AS allocated_quantity,
  b.remaining_weight,
  COALESCE(SUM(a.weight_delta), 0)       AS allocated_weight,
  b.remaining_cost,
  COALESCE(SUM(a.cost_delta), 0)         AS allocated_cost,
  (b.remaining_quantity - COALESCE(SUM(a.quantity_delta), 0)) AS diff_quantity,
  (b.remaining_weight   - COALESCE(SUM(a.weight_delta), 0))   AS diff_weight,
  (b.remaining_cost     - COALESCE(SUM(a.cost_delta), 0))     AS diff_cost
FROM batches b
LEFT JOIN transaction_allocations a ON a.batch_id = b.id
GROUP BY b.id, b.ingredient_id, b.remaining_quantity, b.remaining_weight, b.remaining_cost;
COMMENT ON VIEW v_batch_reconcile IS
  '批次缓存余额 vs 分配聚合。三个 diff_* 应恒为 0；每日 03:00 对账任务检查并写 audit_logs';

COMMIT;

-- -----------------------------------------------------------------------------
-- AI 识别草稿（阶段 8）：AI 结果只进本表，禁止直接改库存；人工确认后才建档/入库
-- -----------------------------------------------------------------------------
CREATE TABLE recognition_drafts (
  id                    uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  image_asset_id        uuid REFERENCES file_assets (id) ON DELETE SET NULL,
  provider              text NOT NULL DEFAULT 'manual',
  model                 text NOT NULL DEFAULT '',
  status                text NOT NULL DEFAULT 'pending'
                        CHECK (status IN ('pending', 'confirmed', 'rejected')),
  draft                 jsonb NOT NULL DEFAULT '{}'::jsonb,
  warnings              jsonb NOT NULL DEFAULT '[]'::jsonb,
  confirmed_entity_type text CHECK (confirmed_entity_type IN ('ingredient', 'batch')),
  confirmed_entity_id   uuid,
  device_id             uuid REFERENCES devices (id) ON DELETE SET NULL,
  created_at            timestamptz NOT NULL DEFAULT now(),
  confirmed_at          timestamptz,
  CONSTRAINT ck_recognition_confirmed CHECK (
    (status = 'pending' AND confirmed_entity_type IS NULL AND confirmed_at IS NULL)
    OR (status = 'confirmed' AND confirmed_entity_type IS NOT NULL AND confirmed_at IS NOT NULL)
    OR (status = 'rejected' AND confirmed_entity_type IS NULL)
  )
);

CREATE INDEX ix_recognition_status ON recognition_drafts (status, created_at DESC);
