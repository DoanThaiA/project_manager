-- =====================================================================
-- Dữ liệu mẫu (chỉ dùng cho môi trường dev)
-- Mật khẩu của mọi tài khoản mẫu: Demo@123 (bcrypt)
-- =====================================================================
BEGIN;

INSERT INTO customers (code, name, email, phone, address) VALUES
    ('KH001', 'Công ty TNHH ABC', 'contact@abc.vn', '0281234567', 'Q.1, TP.HCM');

INSERT INTO customer_contacts (customer_id, full_name, position, email, is_primary)
SELECT id, 'Nguyễn Văn Khách', 'Trưởng phòng IT', 'khach@abc.vn', true FROM customers WHERE code = 'KH001';

INSERT INTO users (username, email, password_hash, full_name, job_title, is_system_admin, customer_id) VALUES
    ('admin',  'admin@example.com',  '$2b$12$YGiQugEJQF0HR7Mcd1QLbuFlDkPw2oPSXrert.CMuISbK3A2JLXWi', 'Quản trị viên',   'Admin',         true,  NULL),
    ('po.an',  'an@example.com',     '$2b$12$YGiQugEJQF0HR7Mcd1QLbuFlDkPw2oPSXrert.CMuISbK3A2JLXWi', 'Trần Văn An',     'Product Owner', false, NULL),
    ('sm.binh','binh@example.com',   '$2b$12$YGiQugEJQF0HR7Mcd1QLbuFlDkPw2oPSXrert.CMuISbK3A2JLXWi', 'Lê Thị Bình',     'Scrum Master',  false, NULL),
    ('dev.cuong','cuong@example.com','$2b$12$YGiQugEJQF0HR7Mcd1QLbuFlDkPw2oPSXrert.CMuISbK3A2JLXWi', 'Phạm Văn Cường',  'Developer',     false, NULL),
    ('qa.dung','dung@example.com',   '$2b$12$YGiQugEJQF0HR7Mcd1QLbuFlDkPw2oPSXrert.CMuISbK3A2JLXWi', 'Hoàng Thị Dung',  'Tester',        false, NULL),
    ('kh.abc', 'khach@abc.vn',       '$2b$12$YGiQugEJQF0HR7Mcd1QLbuFlDkPw2oPSXrert.CMuISbK3A2JLXWi', 'Nguyễn Văn Khách','Khách hàng',    false,
        (SELECT id FROM customers WHERE code = 'KH001'));

INSERT INTO user_roles (user_id, role_id)
SELECT u.id, r.id FROM users u JOIN roles r ON r.code = 'PROJECT_MANAGER' WHERE u.username = 'po.an'
UNION ALL
SELECT u.id, r.id FROM users u JOIN roles r ON r.code = 'STAFF' WHERE u.username IN ('sm.binh', 'dev.cuong', 'qa.dung');

-- Ngữ cảnh người thao tác (để trigger ghi log)
SELECT set_config('app.current_user_id', (SELECT id::text FROM users WHERE username = 'po.an'), true);

INSERT INTO projects (key, name, description, customer_id, product_owner_id, scrum_master_id, status, start_date, created_by)
SELECT 'ERP', 'Hệ thống ERP cho ABC', 'Quản lý kho, bán hàng, kế toán', c.id, po.id, sm.id, 'active', DATE '2026-10-01', po.id
  FROM customers c, users po, users sm
 WHERE c.code = 'KH001' AND po.username = 'po.an' AND sm.username = 'sm.binh';

INSERT INTO project_members (project_id, user_id, role_id)
SELECT p.id, u.id, r.id
  FROM (VALUES ('po.an', 'PRODUCT_OWNER'), ('sm.binh', 'SCRUM_MASTER'), ('dev.cuong', 'DEVELOPER'),
               ('qa.dung', 'TESTER'), ('kh.abc', 'CUSTOMER')) AS m(username, role_code)
  JOIN users u ON u.username = m.username
  JOIN roles r ON r.code = m.role_code
  JOIN projects p ON p.key = 'ERP';

INSERT INTO sprints (project_id, sprint_no, name, goal, start_date, end_date, status, capacity_hours)
SELECT id, 1, 'Sprint 1', 'Hoàn thành module quản lý kho cơ bản', DATE '2026-10-13', DATE '2026-10-26', 'active', 240
  FROM projects WHERE key = 'ERP';

INSERT INTO requirements (project_id, customer_contact_id, title, description, acceptance_criteria,
                          type, source, priority, due_date, assignee_id)
SELECT p.id, cc.id, x.title, x.descr, x.ac, x.type::requirement_type, 'meeting', x.prio::priority_level,
       DATE '2026-11-15', u.id
  FROM projects p
  JOIN customer_contacts cc ON cc.email = 'khach@abc.vn'
  JOIN users u ON u.username = 'po.an'
 CROSS JOIN (VALUES
    ('Quản lý nhập kho',  'Cho phép nhập kho theo phiếu, quét mã vạch', 'Tạo phiếu nhập, in phiếu, tồn kho cập nhật ngay', 'feature', 'high'),
    ('Báo cáo tồn kho',   'Báo cáo tồn kho theo kho / nhóm hàng',        'Xuất Excel được, lọc theo ngày',                    'feature', 'medium')
 ) AS x(title, descr, ac, type, prio)
 WHERE p.key = 'ERP';

-- Duyệt yêu cầu 1 (trigger ghi status_history + activity_logs)
SELECT set_config('app.status_note', 'Khách hàng xác nhận trong buổi họp 10/10', true);
UPDATE requirements SET status = 'approved' WHERE code = 'ERP-REQ-0001';

INSERT INTO work_items (project_id, type, title, status, story_points, original_estimate_hours, remaining_hours,
                        requirement_id, sprint_id, assignee_id, backlog_rank)
SELECT p.id, x.type::work_item_type, x.title, x.status::work_item_status, x.sp, x.est, x.est,
       r.id, s.id, u.id, x.rnk
  FROM projects p
  JOIN requirements r ON r.code = 'ERP-REQ-0001'
  JOIN sprints s      ON s.project_id = p.id AND s.sprint_no = 1
  JOIN users u        ON u.username = 'dev.cuong'
 CROSS JOIN (VALUES
    ('story', 'Màn hình tạo phiếu nhập kho', 'in_progress', 5.0, 24.0, 1.0),
    ('task',  'API quét mã vạch',            'todo',        3.0, 12.0, 2.0)
 ) AS x(type, title, status, sp, est, rnk)
 WHERE p.key = 'ERP';

SELECT set_config('app.current_user_id', (SELECT id::text FROM users WHERE username = 'dev.cuong'), true);

INSERT INTO work_logs (project_id, user_id, work_item_id, sprint_id, log_date, hours, activity_type, description)
SELECT w.project_id, u.id, w.id, w.sprint_id, DATE '2026-10-14', 6, 'development', 'Dựng layout + validate form phiếu nhập'
  FROM work_items w JOIN users u ON u.username = 'dev.cuong'
 WHERE w.code = 'ERP-1';

INSERT INTO work_logs (project_id, user_id, sprint_id, log_date, hours, activity_type, description, is_billable)
SELECT s.project_id, u.id, s.id, DATE '2026-10-13', 2, 'meeting', 'Sprint Planning', false
  FROM sprints s JOIN users u ON u.username = 'dev.cuong'
 WHERE s.sprint_no = 1;

COMMIT;
