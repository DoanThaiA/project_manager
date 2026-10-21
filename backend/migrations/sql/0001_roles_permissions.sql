-- =====================================================================
-- Dữ liệu gốc: chức năng (permissions), vai trò (roles), ma trận phân quyền
-- =====================================================================

INSERT INTO permissions (code, module, name) VALUES
    -- Người dùng & phân quyền
    ('user.view',             'user',        'Xem danh sách người dùng'),
    ('user.create',           'user',        'Tạo người dùng'),
    ('user.update',           'user',        'Cập nhật người dùng'),
    ('user.lock',             'user',        'Khoá / mở khoá người dùng'),
    ('role.manage',           'role',        'Quản lý vai trò & phân quyền'),
    -- Khách hàng
    ('customer.view',         'customer',    'Xem khách hàng'),
    ('customer.create',       'customer',    'Tạo khách hàng'),
    ('customer.update',       'customer',    'Cập nhật khách hàng'),
    ('customer.delete',       'customer',    'Xoá khách hàng'),
    -- Dự án
    ('project.view',          'project',     'Xem dự án'),
    ('project.create',        'project',     'Tạo dự án'),
    ('project.update',        'project',     'Cập nhật thông tin dự án'),
    ('project.delete',        'project',     'Xoá / lưu trữ dự án'),
    ('project.member.manage', 'project',     'Quản lý thành viên dự án'),
    -- Sprint
    ('sprint.view',           'sprint',      'Xem sprint'),
    ('sprint.manage',         'sprint',      'Tạo / bắt đầu / kết thúc sprint'),
    -- Yêu cầu khách hàng
    ('requirement.view',      'requirement', 'Xem yêu cầu khách hàng'),
    ('requirement.create',    'requirement', 'Tạo yêu cầu khách hàng'),
    ('requirement.update',    'requirement', 'Cập nhật yêu cầu'),
    ('requirement.delete',    'requirement', 'Xoá yêu cầu'),
    ('requirement.assign',    'requirement', 'Phân công người phụ trách yêu cầu'),
    ('requirement.approve',   'requirement', 'Duyệt / từ chối yêu cầu'),
    ('requirement.comment',   'requirement', 'Bình luận yêu cầu'),
    ('requirement.view_internal', 'requirement', 'Xem bình luận nội bộ'),
    -- Công việc (backlog)
    ('work_item.view',        'work_item',   'Xem công việc / backlog'),
    ('work_item.create',      'work_item',   'Tạo công việc'),
    ('work_item.update',      'work_item',   'Cập nhật công việc'),
    ('work_item.delete',      'work_item',   'Xoá công việc'),
    ('work_item.assign',      'work_item',   'Giao việc'),
    ('backlog.prioritize',    'work_item',   'Sắp xếp độ ưu tiên Product Backlog'),
    -- Log công việc
    ('work_log.view',         'work_log',    'Xem log công việc của dự án'),
    ('work_log.create',       'work_log',    'Ghi log công việc của mình'),
    ('work_log.manage',       'work_log',    'Sửa / xoá log công việc của người khác'),
    -- Log hoạt động & báo cáo
    ('activity_log.view',     'activity_log','Xem lịch sử hoạt động'),
    ('report.view',           'report',      'Xem báo cáo');

INSERT INTO roles (code, name, scope, is_builtin, description) VALUES
    ('SYSTEM_ADMIN',   'Quản trị hệ thống',  'system',  true, 'Toàn quyền (kèm users.is_system_admin)'),
    ('PROJECT_MANAGER','Quản lý dự án',      'system',  true, 'Tạo dự án, quản lý khách hàng'),
    ('STAFF',          'Nhân viên',          'system',  true, 'Người dùng nội bộ cơ bản'),
    ('PRODUCT_OWNER',  'Product Owner',      'project', true, 'Quản lý Product Backlog, duyệt yêu cầu'),
    ('SCRUM_MASTER',   'Scrum Master',       'project', true, 'Điều phối sprint, quản lý thành viên'),
    ('BA',             'Business Analyst',   'project', true, 'Tiếp nhận & phân tích yêu cầu'),
    ('DEVELOPER',      'Developer',          'project', true, 'Thành viên Development Team'),
    ('TESTER',         'Tester / QA',        'project', true, 'Kiểm thử'),
    ('VIEWER',         'Người xem',          'project', true, 'Chỉ xem'),
    ('CUSTOMER',       'Đại diện khách hàng','project', true, 'Gửi & theo dõi yêu cầu của mình');

-- Ma trận vai trò -> chức năng
INSERT INTO role_permissions (role_id, permission_id)
SELECT r.id, p.id
  FROM (VALUES
    ('SYSTEM_ADMIN',    '*'),
    ('PROJECT_MANAGER', 'user.view'), ('PROJECT_MANAGER', 'customer.*'), ('PROJECT_MANAGER', 'project.view'),
    ('PROJECT_MANAGER', 'project.create'), ('PROJECT_MANAGER', 'report.view'),
    ('STAFF',           'user.view'), ('STAFF', 'customer.view'),

    ('PRODUCT_OWNER',   'project.view'), ('PRODUCT_OWNER', 'project.update'), ('PRODUCT_OWNER', 'project.member.manage'),
    ('PRODUCT_OWNER',   'sprint.*'), ('PRODUCT_OWNER', 'requirement.*'), ('PRODUCT_OWNER', 'work_item.*'),
    ('PRODUCT_OWNER',   'backlog.prioritize'), ('PRODUCT_OWNER', 'work_log.view'), ('PRODUCT_OWNER', 'work_log.create'),
    ('PRODUCT_OWNER',   'activity_log.view'), ('PRODUCT_OWNER', 'report.view'),

    ('SCRUM_MASTER',    'project.view'), ('SCRUM_MASTER', 'project.member.manage'), ('SCRUM_MASTER', 'sprint.*'),
    ('SCRUM_MASTER',    'requirement.view'), ('SCRUM_MASTER', 'requirement.comment'), ('SCRUM_MASTER', 'requirement.view_internal'),
    ('SCRUM_MASTER',    'work_item.*'), ('SCRUM_MASTER', 'work_log.*'), ('SCRUM_MASTER', 'activity_log.view'),
    ('SCRUM_MASTER',    'report.view'),

    ('BA',              'project.view'), ('BA', 'sprint.view'), ('BA', 'requirement.view'), ('BA', 'requirement.create'),
    ('BA',              'requirement.update'), ('BA', 'requirement.assign'), ('BA', 'requirement.comment'),
    ('BA',              'requirement.view_internal'), ('BA', 'work_item.view'), ('BA', 'work_item.create'),
    ('BA',              'work_item.update'), ('BA', 'work_log.view'), ('BA', 'work_log.create'), ('BA', 'report.view'),

    ('DEVELOPER',       'project.view'), ('DEVELOPER', 'sprint.view'), ('DEVELOPER', 'requirement.view'),
    ('DEVELOPER',       'requirement.comment'), ('DEVELOPER', 'requirement.view_internal'),
    ('DEVELOPER',       'work_item.view'), ('DEVELOPER', 'work_item.create'), ('DEVELOPER', 'work_item.update'),
    ('DEVELOPER',       'work_log.view'), ('DEVELOPER', 'work_log.create'),

    ('TESTER',          'project.view'), ('TESTER', 'sprint.view'), ('TESTER', 'requirement.view'),
    ('TESTER',          'requirement.comment'), ('TESTER', 'requirement.view_internal'),
    ('TESTER',          'work_item.view'), ('TESTER', 'work_item.create'), ('TESTER', 'work_item.update'),
    ('TESTER',          'work_log.view'), ('TESTER', 'work_log.create'),

    ('VIEWER',          'project.view'), ('VIEWER', 'sprint.view'), ('VIEWER', 'requirement.view'),
    ('VIEWER',          'work_item.view'), ('VIEWER', 'report.view'),

    ('CUSTOMER',        'project.view'), ('CUSTOMER', 'requirement.view'), ('CUSTOMER', 'requirement.create'),
    ('CUSTOMER',        'requirement.comment')
  ) AS m(role_code, perm_pattern)
  JOIN roles r       ON r.code = m.role_code
  JOIN permissions p ON m.perm_pattern = '*'
                     OR p.code = m.perm_pattern
                     OR (m.perm_pattern LIKE '%.*' AND p.module = split_part(m.perm_pattern, '.', 1))
ON CONFLICT DO NOTHING;
