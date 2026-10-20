-- =====================================================================
-- PROJECT MANAGER - Quản lý dự án phần mềm theo Scrum/Agile
-- V1: Người dùng & phân quyền, Khách hàng, Dự án, Sprint,
--     Yêu cầu khách hàng, Backlog, Log công việc, Log hoạt động (audit)
-- PostgreSQL >= 15
-- =====================================================================

CREATE EXTENSION IF NOT EXISTS citext;

-- ---------------------------------------------------------------------
-- 1. KIỂU DỮ LIỆU (ENUM)
-- ---------------------------------------------------------------------
CREATE TYPE user_status        AS ENUM ('active', 'inactive', 'locked');
CREATE TYPE role_scope         AS ENUM ('system', 'project');
CREATE TYPE customer_status    AS ENUM ('active', 'inactive');
CREATE TYPE project_status     AS ENUM ('planning', 'active', 'on_hold', 'completed', 'cancelled');
CREATE TYPE sprint_status      AS ENUM ('planned', 'active', 'completed', 'cancelled');
CREATE TYPE priority_level     AS ENUM ('lowest', 'low', 'medium', 'high', 'critical');

CREATE TYPE requirement_type   AS ENUM ('feature', 'change_request', 'bug', 'improvement', 'support', 'other');
CREATE TYPE requirement_source AS ENUM ('email', 'meeting', 'phone', 'chat', 'ticket', 'document', 'other');
CREATE TYPE requirement_status AS ENUM (
    'new',              -- Mới tiếp nhận
    'analyzing',        -- Đang phân tích
    'pending_approval', -- Chờ duyệt (PO / khách hàng xác nhận)
    'approved',         -- Đã duyệt, đưa vào backlog
    'rejected',         -- Từ chối
    'in_progress',      -- Đang thực hiện
    'done',             -- Đã hoàn thành
    'closed',           -- Đã đóng (khách hàng nghiệm thu)
    'cancelled'         -- Huỷ
);

CREATE TYPE work_item_type     AS ENUM ('epic', 'story', 'task', 'bug', 'subtask');
CREATE TYPE work_item_status   AS ENUM ('backlog', 'todo', 'in_progress', 'in_review', 'testing', 'done', 'cancelled');
CREATE TYPE work_activity_type AS ENUM (
    'analysis', 'design', 'development', 'testing', 'review',
    'meeting', 'deployment', 'support', 'documentation', 'other'
);

-- ---------------------------------------------------------------------
-- 2. HÀM TIỆN ÍCH
-- Ứng dụng đặt ngữ cảnh trong mỗi transaction:
--   SET LOCAL app.current_user_id = '12';
--   SET LOCAL app.client_ip       = '10.0.0.5';
--   SET LOCAL app.status_note     = 'Khách hàng xác nhận qua email';
-- ---------------------------------------------------------------------
CREATE FUNCTION fn_current_user_id() RETURNS bigint
LANGUAGE sql STABLE AS $$
    SELECT NULLIF(current_setting('app.current_user_id', true), '')::bigint
$$;

CREATE FUNCTION fn_set_updated_at() RETURNS trigger
LANGUAGE plpgsql AS $$
BEGIN
    NEW.updated_at := now();
    RETURN NEW;
END $$;

-- ---------------------------------------------------------------------
-- 3. KHÁCH HÀNG
-- ---------------------------------------------------------------------
CREATE TABLE customers (
    id            bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    code          varchar(30)  NOT NULL UNIQUE,
    name          varchar(255) NOT NULL,
    tax_code      varchar(30),
    email         citext,
    phone         varchar(30),
    address       text,
    website       varchar(255),
    status        customer_status NOT NULL DEFAULT 'active',
    note          text,
    created_by    bigint,
    created_at    timestamptz NOT NULL DEFAULT now(),
    updated_at    timestamptz NOT NULL DEFAULT now(),
    deleted_at    timestamptz
);

CREATE TABLE customer_contacts (
    id            bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    customer_id   bigint NOT NULL REFERENCES customers(id) ON DELETE CASCADE,
    full_name     varchar(150) NOT NULL,
    position      varchar(100),
    email         citext,
    phone         varchar(30),
    is_primary    boolean NOT NULL DEFAULT false,
    created_at    timestamptz NOT NULL DEFAULT now(),
    updated_at    timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX idx_customer_contacts_customer ON customer_contacts(customer_id);
-- Mỗi khách hàng tối đa 1 đầu mối chính
CREATE UNIQUE INDEX uq_customer_primary_contact ON customer_contacts(customer_id) WHERE is_primary;

-- ---------------------------------------------------------------------
-- 4. NGƯỜI DÙNG & PHÂN QUYỀN (RBAC)
--   permissions  : danh sách chức năng (module.action)
--   roles        : vai trò cấp hệ thống (system) hoặc cấp dự án (project)
--   user_roles   : gán vai trò hệ thống cho user
--   project_members: gán vai trò dự án cho user trong từng dự án
-- ---------------------------------------------------------------------
CREATE TABLE users (
    id              bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    username        varchar(50)  NOT NULL UNIQUE,
    email           citext       NOT NULL UNIQUE,
    password_hash   varchar(255),                 -- NULL nếu đăng nhập SSO
    full_name       varchar(150) NOT NULL,
    phone           varchar(30),
    avatar_url      varchar(500),
    job_title       varchar(100),
    customer_id     bigint REFERENCES customers(id) ON DELETE SET NULL, -- NOT NULL = tài khoản phía khách hàng
    status          user_status  NOT NULL DEFAULT 'active',
    is_system_admin boolean      NOT NULL DEFAULT false,
    last_login_at   timestamptz,
    created_at      timestamptz NOT NULL DEFAULT now(),
    updated_at      timestamptz NOT NULL DEFAULT now(),
    deleted_at      timestamptz
);
CREATE INDEX idx_users_customer ON users(customer_id) WHERE customer_id IS NOT NULL;

ALTER TABLE customers
    ADD CONSTRAINT fk_customers_created_by FOREIGN KEY (created_by) REFERENCES users(id) ON DELETE SET NULL;

CREATE TABLE permissions (
    id          integer GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    code        varchar(80)  NOT NULL UNIQUE,   -- vd: requirement.approve
    module      varchar(50)  NOT NULL,          -- vd: requirement
    name        varchar(150) NOT NULL,
    description text
);

CREATE TABLE roles (
    id          integer GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    code        varchar(50)  NOT NULL UNIQUE,   -- vd: SCRUM_MASTER
    name        varchar(100) NOT NULL,
    scope       role_scope   NOT NULL,
    description text,
    is_builtin  boolean NOT NULL DEFAULT false, -- vai trò mặc định, không cho xoá
    created_at  timestamptz NOT NULL DEFAULT now(),
    updated_at  timestamptz NOT NULL DEFAULT now(),
    UNIQUE (id, scope)                          -- phục vụ FK kiểm tra scope
);

CREATE TABLE role_permissions (
    role_id       integer NOT NULL REFERENCES roles(id) ON DELETE CASCADE,
    permission_id integer NOT NULL REFERENCES permissions(id) ON DELETE CASCADE,
    PRIMARY KEY (role_id, permission_id)
);

CREATE TABLE user_roles (
    user_id     bigint  NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    role_id     integer NOT NULL,
    role_scope  role_scope NOT NULL DEFAULT 'system' CHECK (role_scope = 'system'),
    granted_by  bigint REFERENCES users(id) ON DELETE SET NULL,
    granted_at  timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (user_id, role_id),
    FOREIGN KEY (role_id, role_scope) REFERENCES roles(id, scope) ON DELETE CASCADE
);

-- ---------------------------------------------------------------------
-- 5. DỰ ÁN
-- ---------------------------------------------------------------------
CREATE TABLE projects (
    id                   bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    key                  varchar(10)  NOT NULL UNIQUE
                         CHECK (key ~ '^[A-Z][A-Z0-9]{1,9}$'),   -- tiền tố mã: ERP-12, ERP-REQ-0003
    name                 varchar(255) NOT NULL,
    description          text,
    customer_id          bigint REFERENCES customers(id) ON DELETE SET NULL,
    product_owner_id     bigint REFERENCES users(id) ON DELETE SET NULL,
    scrum_master_id      bigint REFERENCES users(id) ON DELETE SET NULL,
    status               project_status NOT NULL DEFAULT 'planning',
    start_date           date,
    end_date             date,
    sprint_duration_days smallint NOT NULL DEFAULT 14 CHECK (sprint_duration_days BETWEEN 1 AND 60),
    budget_hours         numeric(10,2) CHECK (budget_hours >= 0),
    requirement_seq      integer NOT NULL DEFAULT 0,  -- bộ đếm sinh mã yêu cầu
    work_item_seq        integer NOT NULL DEFAULT 0,  -- bộ đếm sinh mã công việc
    created_by           bigint REFERENCES users(id) ON DELETE SET NULL,
    created_at           timestamptz NOT NULL DEFAULT now(),
    updated_at           timestamptz NOT NULL DEFAULT now(),
    deleted_at           timestamptz,
    CHECK (end_date IS NULL OR start_date IS NULL OR end_date >= start_date)
);
CREATE INDEX idx_projects_customer ON projects(customer_id);
CREATE INDEX idx_projects_status   ON projects(status) WHERE deleted_at IS NULL;

-- Một user có thể giữ nhiều vai trò trong cùng dự án (vd: BA + Tester)
CREATE TABLE project_members (
    project_id  bigint  NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    user_id     bigint  NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    role_id     integer NOT NULL,
    role_scope  role_scope NOT NULL DEFAULT 'project' CHECK (role_scope = 'project'),
    added_by    bigint REFERENCES users(id) ON DELETE SET NULL,
    joined_at   timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (project_id, user_id, role_id),
    FOREIGN KEY (role_id, role_scope) REFERENCES roles(id, scope)
);
CREATE INDEX idx_project_members_user ON project_members(user_id);

-- ---------------------------------------------------------------------
-- 6. SPRINT
-- ---------------------------------------------------------------------
CREATE TABLE sprints (
    id                 bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    project_id         bigint NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    sprint_no          integer NOT NULL CHECK (sprint_no > 0),
    name               varchar(150) NOT NULL,
    goal               text,
    start_date         date NOT NULL,
    end_date           date NOT NULL,
    status             sprint_status NOT NULL DEFAULT 'planned',
    capacity_hours     numeric(8,2) CHECK (capacity_hours >= 0),
    review_note        text,   -- Sprint Review
    retrospective_note text,   -- Sprint Retrospective
    created_by         bigint REFERENCES users(id) ON DELETE SET NULL,
    created_at         timestamptz NOT NULL DEFAULT now(),
    updated_at         timestamptz NOT NULL DEFAULT now(),
    UNIQUE (project_id, sprint_no),
    UNIQUE (project_id, id),
    CHECK (end_date >= start_date)
);
-- Mỗi dự án chỉ có 1 sprint đang chạy
CREATE UNIQUE INDEX uq_sprints_one_active ON sprints(project_id) WHERE status = 'active';

-- ---------------------------------------------------------------------
-- 7. YÊU CẦU KHÁCH HÀNG
-- ---------------------------------------------------------------------
CREATE TABLE requirements (
    id                  bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    project_id          bigint NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    seq_no              integer NOT NULL,                -- tự sinh theo dự án
    code                varchar(30) NOT NULL,            -- tự sinh: <KEY>-REQ-0001
    parent_id           bigint REFERENCES requirements(id) ON DELETE SET NULL,
    customer_id         bigint REFERENCES customers(id) ON DELETE SET NULL,
    customer_contact_id bigint REFERENCES customer_contacts(id) ON DELETE SET NULL,
    title               varchar(500) NOT NULL,
    description         text,
    acceptance_criteria text,                            -- tiêu chí nghiệm thu
    type                requirement_type   NOT NULL DEFAULT 'feature',
    source              requirement_source NOT NULL DEFAULT 'email',
    priority            priority_level     NOT NULL DEFAULT 'medium',
    status              requirement_status NOT NULL DEFAULT 'new',
    business_value      smallint CHECK (business_value BETWEEN 1 AND 100),
    estimated_hours     numeric(8,2) CHECK (estimated_hours >= 0),
    received_at         timestamptz NOT NULL DEFAULT now(),  -- thời điểm tiếp nhận
    expected_date       date,                                -- ngày khách hàng mong muốn
    due_date            date,                                -- ngày cam kết
    target_release      varchar(50),
    assignee_id         bigint REFERENCES users(id) ON DELETE SET NULL, -- người phụ trách (BA/PO)
    approved_by         bigint REFERENCES users(id) ON DELETE SET NULL,
    approved_at         timestamptz,
    rejected_reason     text,
    resolved_at         timestamptz,
    closed_at           timestamptz,
    tags                text[] NOT NULL DEFAULT '{}',
    created_by          bigint REFERENCES users(id) ON DELETE SET NULL,
    created_at          timestamptz NOT NULL DEFAULT now(),
    updated_at          timestamptz NOT NULL DEFAULT now(),
    deleted_at          timestamptz,
    UNIQUE (project_id, seq_no),
    UNIQUE (code),
    UNIQUE (project_id, id),
    CHECK (status <> 'rejected' OR rejected_reason IS NOT NULL)
);
CREATE INDEX idx_requirements_project_status ON requirements(project_id, status) WHERE deleted_at IS NULL;
CREATE INDEX idx_requirements_customer       ON requirements(customer_id);
CREATE INDEX idx_requirements_assignee       ON requirements(assignee_id) WHERE deleted_at IS NULL;
CREATE INDEX idx_requirements_parent         ON requirements(parent_id);
CREATE INDEX idx_requirements_tags           ON requirements USING gin(tags);
CREATE INDEX idx_requirements_search         ON requirements
    USING gin(to_tsvector('simple', title || ' ' || coalesce(description, '')));

CREATE TABLE requirement_comments (
    id              bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    requirement_id  bigint NOT NULL REFERENCES requirements(id) ON DELETE CASCADE,
    parent_id       bigint REFERENCES requirement_comments(id) ON DELETE CASCADE,
    user_id         bigint REFERENCES users(id) ON DELETE SET NULL,
    content         text NOT NULL,
    is_internal     boolean NOT NULL DEFAULT false,  -- true: chỉ nội bộ, khách hàng không thấy
    created_at      timestamptz NOT NULL DEFAULT now(),
    updated_at      timestamptz NOT NULL DEFAULT now(),
    deleted_at      timestamptz
);
CREATE INDEX idx_req_comments_requirement ON requirement_comments(requirement_id, created_at);

-- Lịch sử chuyển trạng thái yêu cầu (tự ghi bằng trigger)
CREATE TABLE requirement_status_history (
    id              bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    requirement_id  bigint NOT NULL REFERENCES requirements(id) ON DELETE CASCADE,
    from_status     requirement_status,
    to_status       requirement_status NOT NULL,
    changed_by      bigint REFERENCES users(id) ON DELETE SET NULL,
    note            text,
    changed_at      timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX idx_req_status_history ON requirement_status_history(requirement_id, changed_at);

-- ---------------------------------------------------------------------
-- 8. PRODUCT BACKLOG / CÔNG VIỆC (Epic, Story, Task, Bug, Subtask)
-- ---------------------------------------------------------------------
CREATE TABLE work_items (
    id                      bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    project_id              bigint NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    seq_no                  integer NOT NULL,
    code                    varchar(30) NOT NULL,          -- tự sinh: <KEY>-12
    type                    work_item_type   NOT NULL DEFAULT 'task',
    title                   varchar(500) NOT NULL,
    description             text,
    acceptance_criteria     text,
    status                  work_item_status NOT NULL DEFAULT 'backlog',
    priority                priority_level   NOT NULL DEFAULT 'medium',
    story_points            numeric(5,1) CHECK (story_points >= 0),
    original_estimate_hours numeric(8,2) CHECK (original_estimate_hours >= 0),
    remaining_hours         numeric(8,2) CHECK (remaining_hours >= 0),
    requirement_id          bigint,     -- yêu cầu khách hàng gốc
    sprint_id               bigint,     -- NULL = nằm trong Product Backlog
    parent_id               bigint REFERENCES work_items(id) ON DELETE CASCADE,
    assignee_id             bigint REFERENCES users(id) ON DELETE SET NULL,
    reporter_id             bigint REFERENCES users(id) ON DELETE SET NULL,
    backlog_rank            double precision NOT NULL DEFAULT 0,  -- thứ tự ưu tiên trong backlog
    start_date              date,
    due_date                date,
    completed_at            timestamptz,
    tags                    text[] NOT NULL DEFAULT '{}',
    created_at              timestamptz NOT NULL DEFAULT now(),
    updated_at              timestamptz NOT NULL DEFAULT now(),
    deleted_at              timestamptz,
    UNIQUE (project_id, seq_no),
    UNIQUE (code),
    UNIQUE (project_id, id),
    -- FK kép đảm bảo sprint / yêu cầu thuộc CÙNG dự án
    FOREIGN KEY (project_id, sprint_id)      REFERENCES sprints(project_id, id)      ON DELETE SET NULL (sprint_id),
    FOREIGN KEY (project_id, requirement_id) REFERENCES requirements(project_id, id) ON DELETE SET NULL (requirement_id)
);
CREATE INDEX idx_work_items_sprint      ON work_items(sprint_id, status) WHERE deleted_at IS NULL;
CREATE INDEX idx_work_items_backlog     ON work_items(project_id, backlog_rank) WHERE sprint_id IS NULL AND deleted_at IS NULL;
CREATE INDEX idx_work_items_requirement ON work_items(requirement_id);
CREATE INDEX idx_work_items_assignee    ON work_items(assignee_id, status) WHERE deleted_at IS NULL;
CREATE INDEX idx_work_items_parent      ON work_items(parent_id);

-- ---------------------------------------------------------------------
-- 9. LOG CÔNG VIỆC (time tracking / worklog)
--   Ghi giờ làm theo công việc, theo yêu cầu, hoặc chung cho dự án (họp...)
-- ---------------------------------------------------------------------
CREATE TABLE work_logs (
    id              bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    project_id      bigint NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    user_id         bigint NOT NULL REFERENCES users(id),
    work_item_id    bigint,
    requirement_id  bigint,
    sprint_id       bigint,
    log_date        date NOT NULL DEFAULT current_date,
    hours           numeric(5,2) NOT NULL CHECK (hours > 0 AND hours <= 24),
    activity_type   work_activity_type NOT NULL DEFAULT 'development',
    description     text NOT NULL,
    is_billable     boolean NOT NULL DEFAULT true,
    created_at      timestamptz NOT NULL DEFAULT now(),
    updated_at      timestamptz NOT NULL DEFAULT now(),
    FOREIGN KEY (project_id, work_item_id)   REFERENCES work_items(project_id, id)   ON DELETE SET NULL (work_item_id),
    FOREIGN KEY (project_id, requirement_id) REFERENCES requirements(project_id, id) ON DELETE SET NULL (requirement_id),
    FOREIGN KEY (project_id, sprint_id)      REFERENCES sprints(project_id, id)      ON DELETE SET NULL (sprint_id)
);
CREATE INDEX idx_work_logs_user_date    ON work_logs(user_id, log_date);
CREATE INDEX idx_work_logs_project_date ON work_logs(project_id, log_date);
CREATE INDEX idx_work_logs_work_item    ON work_logs(work_item_id);
CREATE INDEX idx_work_logs_requirement  ON work_logs(requirement_id);
CREATE INDEX idx_work_logs_sprint       ON work_logs(sprint_id);

-- ---------------------------------------------------------------------
-- 10. FILE ĐÍNH KÈM (dùng chung cho yêu cầu, công việc, bình luận)
-- ---------------------------------------------------------------------
CREATE TABLE attachments (
    id           bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    project_id   bigint NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    entity_type  varchar(30) NOT NULL
                 CHECK (entity_type IN ('requirement', 'work_item', 'requirement_comment', 'sprint')),
    entity_id    bigint NOT NULL,
    file_name    varchar(255) NOT NULL,
    storage_key  varchar(500) NOT NULL,   -- đường dẫn S3/MinIO/local
    mime_type    varchar(100),
    size_bytes   bigint CHECK (size_bytes >= 0),
    uploaded_by  bigint REFERENCES users(id) ON DELETE SET NULL,
    created_at   timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX idx_attachments_entity ON attachments(entity_type, entity_id);

-- ---------------------------------------------------------------------
-- 11. LOG HOẠT ĐỘNG (audit log)
--   Ghi tự động bởi trigger (create/update/delete) + ứng dụng ghi thêm
--   (login, logout, export, ...). Không đặt FK để log vẫn còn khi dữ liệu
--   gốc bị xoá. Khi dữ liệu lớn có thể chuyển sang partition theo tháng.
-- ---------------------------------------------------------------------
CREATE TABLE activity_logs (
    id           bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    occurred_at  timestamptz NOT NULL DEFAULT now(),
    actor_id     bigint,                  -- user thực hiện
    project_id   bigint,
    entity_type  varchar(50) NOT NULL,    -- tên bảng / đối tượng
    entity_id    bigint,
    action       varchar(30) NOT NULL,    -- create, update, delete, soft_delete, login, export...
    old_values   jsonb,                   -- chỉ các trường thay đổi
    new_values   jsonb,
    ip_address   inet,
    user_agent   text,
    message      text
);
CREATE INDEX idx_activity_logs_entity  ON activity_logs(entity_type, entity_id, occurred_at DESC);
CREATE INDEX idx_activity_logs_project ON activity_logs(project_id, occurred_at DESC);
CREATE INDEX idx_activity_logs_actor   ON activity_logs(actor_id, occurred_at DESC);
CREATE INDEX idx_activity_logs_time    ON activity_logs USING brin(occurred_at);

-- =====================================================================
-- 12. TRIGGER
-- =====================================================================

-- 12.1 updated_at
DO $$
DECLARE t text;
BEGIN
    FOREACH t IN ARRAY ARRAY['customers', 'customer_contacts', 'users', 'roles', 'projects', 'sprints',
                             'requirements', 'requirement_comments', 'work_items', 'work_logs']
    LOOP
        EXECUTE format('CREATE TRIGGER trg_%1$s_updated_at BEFORE UPDATE ON %1$I
                        FOR EACH ROW EXECUTE FUNCTION fn_set_updated_at()', t);
    END LOOP;
END $$;

-- 12.2 Sinh mã yêu cầu: <KEY>-REQ-0001 (khoá dòng projects nên không bị trùng khi ghi đồng thời)
CREATE FUNCTION fn_requirement_assign_code() RETURNS trigger
LANGUAGE plpgsql AS $$
DECLARE
    v_key text;
BEGIN
    UPDATE projects SET requirement_seq = requirement_seq + 1
     WHERE id = NEW.project_id
    RETURNING requirement_seq, key INTO NEW.seq_no, v_key;

    NEW.code := v_key || '-REQ-' || lpad(NEW.seq_no::text, 4, '0');
    NEW.created_by := coalesce(NEW.created_by, fn_current_user_id());
    IF NEW.customer_id IS NULL THEN
        SELECT customer_id INTO NEW.customer_id FROM projects WHERE id = NEW.project_id;
    END IF;
    RETURN NEW;
END $$;

CREATE TRIGGER trg_requirements_assign_code
    BEFORE INSERT ON requirements
    FOR EACH ROW EXECUTE FUNCTION fn_requirement_assign_code();

-- 12.3 Sinh mã công việc: <KEY>-12
CREATE FUNCTION fn_work_item_assign_code() RETURNS trigger
LANGUAGE plpgsql AS $$
DECLARE
    v_key text;
BEGIN
    UPDATE projects SET work_item_seq = work_item_seq + 1
     WHERE id = NEW.project_id
    RETURNING work_item_seq, key INTO NEW.seq_no, v_key;

    NEW.code := v_key || '-' || NEW.seq_no;
    NEW.reporter_id := coalesce(NEW.reporter_id, fn_current_user_id());
    RETURN NEW;
END $$;

CREATE TRIGGER trg_work_items_assign_code
    BEFORE INSERT ON work_items
    FOR EACH ROW EXECUTE FUNCTION fn_work_item_assign_code();

-- 12.4 Tự cập nhật các mốc thời gian khi đổi trạng thái yêu cầu
CREATE FUNCTION fn_requirement_status_timestamps() RETURNS trigger
LANGUAGE plpgsql AS $$
BEGIN
    IF NEW.status IS DISTINCT FROM OLD.status THEN
        IF NEW.status = 'approved' THEN
            NEW.approved_at := coalesce(NEW.approved_at, now());
            NEW.approved_by := coalesce(NEW.approved_by, fn_current_user_id());
        END IF;
        IF NEW.status = 'done' THEN
            NEW.resolved_at := coalesce(NEW.resolved_at, now());
        END IF;
        IF NEW.status IN ('closed', 'cancelled') THEN
            NEW.closed_at := coalesce(NEW.closed_at, now());
        END IF;
    END IF;
    RETURN NEW;
END $$;

CREATE TRIGGER trg_requirements_status_timestamps
    BEFORE UPDATE OF status ON requirements
    FOR EACH ROW EXECUTE FUNCTION fn_requirement_status_timestamps();

-- 12.5 Ghi lịch sử trạng thái yêu cầu
CREATE FUNCTION fn_requirement_status_history() RETURNS trigger
LANGUAGE plpgsql AS $$
BEGIN
    IF TG_OP = 'INSERT' OR NEW.status IS DISTINCT FROM OLD.status THEN
        INSERT INTO requirement_status_history (requirement_id, from_status, to_status, changed_by, note)
        VALUES (NEW.id,
                CASE WHEN TG_OP = 'UPDATE' THEN OLD.status END,
                NEW.status,
                fn_current_user_id(),
                NULLIF(current_setting('app.status_note', true), ''));
    END IF;
    RETURN NULL;
END $$;

CREATE TRIGGER trg_requirements_status_history
    AFTER INSERT OR UPDATE OF status ON requirements
    FOR EACH ROW EXECUTE FUNCTION fn_requirement_status_history();

-- 12.6 Tự set completed_at cho công việc
CREATE FUNCTION fn_work_item_completed_at() RETURNS trigger
LANGUAGE plpgsql AS $$
BEGIN
    IF NEW.status = 'done' AND OLD.status IS DISTINCT FROM 'done' THEN
        NEW.completed_at := now();
        NEW.remaining_hours := 0;
    ELSIF NEW.status <> 'done' THEN
        NEW.completed_at := NULL;
    END IF;
    RETURN NEW;
END $$;

CREATE TRIGGER trg_work_items_completed_at
    BEFORE UPDATE OF status ON work_items
    FOR EACH ROW EXECUTE FUNCTION fn_work_item_completed_at();

-- 12.7 Audit log chung: chỉ lưu các trường thay đổi, bỏ trường nhạy cảm
CREATE FUNCTION fn_audit_log() RETURNS trigger
LANGUAGE plpgsql AS $$
DECLARE
    v_old     jsonb;
    v_new     jsonb;
    v_row     jsonb;
    v_action  text;
    v_ignored text[] := ARRAY['updated_at', 'password_hash', 'requirement_seq', 'work_item_seq'];
BEGIN
    IF TG_OP = 'INSERT' THEN
        v_action := 'create';
        v_new := to_jsonb(NEW) - v_ignored;
        v_row := v_new;
    ELSIF TG_OP = 'DELETE' THEN
        v_action := 'delete';
        v_old := to_jsonb(OLD) - v_ignored;
        v_row := v_old;
    ELSE
        v_row := to_jsonb(NEW);
        SELECT jsonb_object_agg(o.key, o.value), jsonb_object_agg(o.key, n.value)
          INTO v_old, v_new
          FROM jsonb_each(to_jsonb(OLD) - v_ignored) o
          JOIN jsonb_each(to_jsonb(NEW) - v_ignored) n USING (key)
         WHERE o.value IS DISTINCT FROM n.value;

        IF v_new IS NULL THEN
            RETURN NULL;  -- không có thay đổi thực sự
        END IF;
        v_action := CASE
            WHEN v_new ? 'deleted_at' AND (v_new->>'deleted_at') IS NOT NULL THEN 'soft_delete'
            WHEN v_new ? 'deleted_at' THEN 'restore'
            WHEN v_new ? 'status' THEN 'status_change'
            ELSE 'update'
        END;
    END IF;

    INSERT INTO activity_logs (actor_id, project_id, entity_type, entity_id, action,
                               old_values, new_values, ip_address)
    VALUES (fn_current_user_id(),
            CASE WHEN TG_TABLE_NAME = 'projects' THEN (v_row->>'id')::bigint
                 ELSE (v_row->>'project_id')::bigint END,
            TG_TABLE_NAME,
            (v_row->>'id')::bigint,
            v_action,
            v_old,
            v_new,
            NULLIF(current_setting('app.client_ip', true), '')::inet);
    RETURN NULL;
END $$;

DO $$
DECLARE t text;
BEGIN
    FOREACH t IN ARRAY ARRAY['users', 'customers', 'projects', 'sprints',
                             'requirements', 'requirement_comments', 'work_items', 'work_logs', 'attachments']
    LOOP
        EXECUTE format('CREATE TRIGGER trg_%1$s_audit AFTER INSERT OR UPDATE OR DELETE ON %1$I
                        FOR EACH ROW EXECUTE FUNCTION fn_audit_log()', t);
    END LOOP;
END $$;

-- project_members không có cột id -> audit riêng
CREATE FUNCTION fn_audit_project_members() RETURNS trigger
LANGUAGE plpgsql AS $$
DECLARE
    r project_members;
BEGIN
    r := CASE WHEN TG_OP = 'DELETE' THEN OLD ELSE NEW END;
    INSERT INTO activity_logs (actor_id, project_id, entity_type, entity_id, action, old_values, new_values, ip_address)
    VALUES (fn_current_user_id(), r.project_id, 'project_members', r.user_id,
            CASE TG_OP WHEN 'INSERT' THEN 'member_add' ELSE 'member_remove' END,
            CASE WHEN TG_OP = 'DELETE' THEN jsonb_build_object('role_id', r.role_id) END,
            CASE WHEN TG_OP = 'INSERT' THEN jsonb_build_object('role_id', r.role_id) END,
            NULLIF(current_setting('app.client_ip', true), '')::inet);
    RETURN NULL;
END $$;

CREATE TRIGGER trg_project_members_audit
    AFTER INSERT OR DELETE ON project_members
    FOR EACH ROW EXECUTE FUNCTION fn_audit_project_members();

-- =====================================================================
-- 13. HÀM KIỂM TRA QUYỀN
--   SELECT fn_user_has_permission(5, 'requirement.approve', 1);
-- =====================================================================
CREATE FUNCTION fn_user_has_permission(p_user_id bigint, p_permission varchar, p_project_id bigint DEFAULT NULL)
RETURNS boolean
LANGUAGE sql STABLE AS $$
    SELECT EXISTS (
        SELECT 1 FROM users u
         WHERE u.id = p_user_id AND u.status = 'active' AND u.deleted_at IS NULL AND u.is_system_admin
    )
    OR EXISTS (   -- quyền từ vai trò hệ thống
        SELECT 1
          FROM users u
          JOIN user_roles ur       ON ur.user_id = u.id
          JOIN role_permissions rp ON rp.role_id = ur.role_id
          JOIN permissions p       ON p.id = rp.permission_id
         WHERE u.id = p_user_id AND u.status = 'active' AND u.deleted_at IS NULL
           AND p.code = p_permission
    )
    OR EXISTS (   -- quyền từ vai trò trong dự án
        SELECT 1
          FROM users u
          JOIN project_members pm  ON pm.user_id = u.id
          JOIN role_permissions rp ON rp.role_id = pm.role_id
          JOIN permissions p       ON p.id = rp.permission_id
         WHERE u.id = p_user_id AND u.status = 'active' AND u.deleted_at IS NULL
           AND pm.project_id = p_project_id
           AND p.code = p_permission
    )
$$;

-- =====================================================================
-- 14. VIEW BÁO CÁO
-- =====================================================================

-- Tổng quan yêu cầu: số công việc, % hoàn thành, giờ đã log
CREATE VIEW v_requirement_overview AS
SELECT r.id, r.project_id, r.code, r.title, r.type, r.priority, r.status,
       c.name                                    AS customer_name,
       a.full_name                               AS assignee_name,
       r.received_at, r.due_date, r.estimated_hours,
       count(DISTINCT w.id)                      AS work_item_count,
       count(DISTINCT w.id) FILTER (WHERE w.status = 'done') AS work_item_done,
       coalesce((SELECT sum(l.hours) FROM work_logs l
                  LEFT JOIN work_items wi ON wi.id = l.work_item_id
                 WHERE l.requirement_id = r.id OR wi.requirement_id = r.id), 0) AS logged_hours,
       (r.due_date < current_date AND r.status NOT IN ('done', 'closed', 'cancelled', 'rejected')) AS is_overdue
  FROM requirements r
  LEFT JOIN customers c  ON c.id = r.customer_id
  LEFT JOIN users a      ON a.id = r.assignee_id
  LEFT JOIN work_items w ON w.requirement_id = r.id AND w.deleted_at IS NULL
 WHERE r.deleted_at IS NULL
 GROUP BY r.id, c.name, a.full_name;

-- Tiến độ sprint: story point kế hoạch / hoàn thành, giờ đã log
CREATE VIEW v_sprint_progress AS
SELECT s.id AS sprint_id, s.project_id, s.sprint_no, s.name, s.status, s.start_date, s.end_date,
       coalesce(sum(w.story_points), 0)                                   AS planned_points,
       coalesce(sum(w.story_points) FILTER (WHERE w.status = 'done'), 0)  AS completed_points,
       count(w.id)                                                        AS item_count,
       count(w.id) FILTER (WHERE w.status = 'done')                       AS done_count,
       coalesce((SELECT sum(l.hours) FROM work_logs l WHERE l.sprint_id = s.id), 0) AS logged_hours
  FROM sprints s
  LEFT JOIN work_items w ON w.sprint_id = s.id AND w.deleted_at IS NULL
 GROUP BY s.id;

-- Tổng giờ log theo người / dự án / ngày
CREATE VIEW v_work_log_daily AS
SELECT l.project_id, p.key AS project_key, l.user_id, u.full_name, l.log_date,
       sum(l.hours)                                  AS total_hours,
       sum(l.hours) FILTER (WHERE l.is_billable)     AS billable_hours
  FROM work_logs l
  JOIN projects p ON p.id = l.project_id
  JOIN users u    ON u.id = l.user_id
 GROUP BY l.project_id, p.key, l.user_id, u.full_name, l.log_date;
