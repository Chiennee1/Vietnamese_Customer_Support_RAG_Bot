# Backup và restore

## Mục tiêu

Backup phải bao phủ:

1. PostgreSQL: transaction data, knowledge metadata/chunks, conversation/ticket.
2. Upload originals tại `/app/uploads`.
3. Source-controlled policy files, migration và app version.

Docker volume không tự được coi là backup. Mỗi restore drill phải ghi RPO/RTO
thực đo, người thực hiện, backup ID và kết quả smoke.

## Lịch đề xuất

| Dữ liệu | Cơ chế | Lịch |
|---|---|---|
| PostgreSQL volume snapshot | Railway native backup | daily + weekly + monthly |
| Logical PostgreSQL dump | `pg_dump` mã hoá ngoài Railway project | daily trước release quan trọng |
| Upload volume snapshot | Railway native backup | daily + trước publish hàng loạt |
| Source/policy | Git remote protected branch/tag | mỗi thay đổi |
| Restore drill | Environment tách biệt | hàng tháng |

Native Railway retention hiện phụ thuộc loại lịch/plan; kiểm tra lại trên dashboard
thay vì hard-code giả định dài hạn.

## Logical backup

Chạy từ trusted operator host có PostgreSQL client tương thích. Lấy public database
URL từ secret manager/Railway, không đưa URL vào command history dùng chung hoặc
log CI.

```powershell
$stamp = Get-Date -Format 'yyyyMMdd-HHmmss'
$backupPath = "support-rag-$stamp.dump"
pg_dump $env:DATABASE_PUBLIC_URL `
  --format=custom `
  --no-owner `
  --no-privileges `
  --file=$backupPath
Get-FileHash $backupPath -Algorithm SHA256
```

Mã hoá file, upload vào storage tách project với least privilege và retention
policy. Lưu checksum riêng. Không commit dump vào Git.

## Restore drill an toàn

1. Tạo database pgvector mới trong environment restore/staging.
2. Kiểm tra `vector` extension có sẵn.
3. Restore logical dump:

```powershell
pg_restore `
  --dbname $env:RESTORE_DATABASE_URL `
  --clean --if-exists `
  --no-owner --no-privileges `
  .\support-rag-<timestamp>.dump
```

4. Trỏ một backend staging đúng app tag vào database này.
5. Chạy `alembic current`; chỉ `upgrade head` nếu restore là revision cũ và đã
   review migration.
6. Verify row counts, checksum/version của knowledge, vector dimension/index.
7. Chạy auth, ownership, product/order/warranty, policy citation và retention
   smoke.
8. Ghi RPO/RTO thực tế rồi huỷ environment restore theo retention policy.

Không restore trực tiếp vào production để “thử”. Railway native restore tạo/stage
volume thay thế; review staged change và giữ volume cũ tới khi xác minh xong.

## Upload originals

Railway volume gắn ở `/app/uploads`. Native volume backup bao phủ nội dung này.
Sau restore:

- so sánh document count/checksum với database;
- kiểm tra file path không thoát mount;
- mở thử Markdown/PDF được phê duyệt;
- không re-publish tự động;
- nếu raw file mất nhưng chunks còn, chuyển case sang admin/human review.

## Disaster recovery

Thứ tự:

1. Freeze deployment/write nếu cần bảo toàn bằng chứng.
2. Chọn backup trước incident và xác minh checksum.
3. Restore sang project/environment mới.
4. Deploy app tag tương thích với DB revision.
5. Rotate secrets nếu incident liên quan credential.
6. Full smoke + eval + security ownership tests.
7. Chuyển domain/traffic sau approval.
8. Postmortem, cập nhật RPO/RTO và runbook.

Tham khảo Railway:

- <https://docs.railway.com/volumes/backups>
- <https://docs.railway.com/databases/postgresql>
