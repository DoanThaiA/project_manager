-- Ảnh đính kèm công việc: phân loại ảnh lỗi (trước khi sửa) / ảnh kết quả (sau khi sửa).
-- Ảnh lưu trên Cloudflare Images, storage_key là image id do Cloudflare sinh.
ALTER TABLE attachments
    ADD COLUMN category varchar(20) CHECK (category IN ('bug', 'result'));

COMMENT ON COLUMN attachments.category IS 'bug: ảnh chụp lỗi; result: ảnh kết quả sau khi sửa';
