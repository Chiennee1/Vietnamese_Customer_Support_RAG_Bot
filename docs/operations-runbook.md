# Operations và incident runbook

## SLO ban đầu

Áp dụng sau khi có traffic production đủ đại diện:

| Tín hiệu | Mục tiêu/cảnh báo ban đầu |
|---|---|
| Readiness | 100% trong deployment; alert sau 2 lần fail liên tiếp |
| Chat success | ≥ 99%; alert nếu < 97% trong 15 phút |
| HTTP p95 deterministic | < 1 giây; release smoke gate < 6 giây |
| LLM/tool timeout | alert nếu > 2% trong 15 phút |
| No-evidence policy | review nếu tăng > 2 lần baseline |
| Critical security bypass | luôn bằng 0 |
| Database volume | warning 70%, critical 85% |
| Upload volume | warning 70%, critical 85% |

Không suy ra SLO LLM từ load smoke greeting; cần baseline traffic thật trước khi
cam kết.

## Dashboard

Admin có thể đọc snapshot tại `GET /api/v1/admin/metrics`. Theo dõi:

- API count/latency theo route template và status class;
- chat success/error, intent, tool, p50/p95/max;
- RAG latency và no-evidence;
- human escalation/ticket;
- feedback positive rate.

Snapshot reset khi process restart và không chứa PII. Production nghiêm túc cần
ship structured logs/metrics sang hệ thống central với retention/access control.

## Deploy checklist

- [ ] Commit/tag mục tiêu đã review; CI xanh.
- [ ] Eval report pass và dataset không giảm.
- [ ] Migration `alembic check` sạch; downgrade đã test nếu migration cho phép.
- [ ] Database + upload backup mới.
- [ ] Không có secret trong diff/build log.
- [ ] Backend deploy, migration và readiness pass.
- [ ] Frontend deploy và CSP/CORS pass.
- [ ] Auth/chat/citation/ownership/ticket/admin smoke pass.
- [ ] Theo dõi 15–30 phút; ghi deployment ID và metric.

## Incident: LLM provider lỗi/chậm

Triệu chứng: `REQUEST_TIMEOUT`, provider error, chat error tăng.

1. Kiểm tra provider status và outbound network.
2. Không tăng retry vô hạn; giữ request/tool timeout.
3. Xác nhận order/product endpoint không bị expose riêng cho browser.
4. Thông báo dịch vụ AI tạm gián đoạn; không đoán câu trả lời.
5. Với case cần hỗ trợ, đưa human handoff; ticket chỉ tạo khi khách xác nhận.
6. Sau hồi phục, chạy policy + combined workflow smoke và xem error rate.

## Incident: database/readiness fail

1. External monitor xác nhận `/health/live` còn sống nhưng `/health/ready` fail.
2. Kiểm tra Railway Postgres deployment, connection limit, disk và backup status.
3. Dừng rollout; không trả order/stock/warranty giả.
4. Nếu migration vừa chạy, đối chiếu revision và deployment log.
5. Khôi phục service/roll-forward; chỉ restore theo
   [backup-restore.md](backup-restore.md).
6. Chạy ownership + CRUD smoke trước khi mở lại.

## Incident: vector/RAG lỗi hoặc no-evidence tăng

1. Kiểm tra embedding provider, dimension, document status/effective date.
2. Xác nhận `vector` extension/index và published chunks tồn tại.
3. Không fallback sang model memory cho policy.
4. Archive bad version nếu liên quan publish gần nhất; republish version đúng.
5. Rerun eval + các query no-result đã redacted.

## Incident: bad document publish

1. Ghi document ID/version/category và thời điểm.
2. Archive version lỗi ngay; không xoá audit history.
3. Publish lại version gần nhất còn hiệu lực sau review.
4. Kiểm tra citation trả đúng version.
5. Sửa file nguồn, tăng version, ingest/publish theo lifecycle.
6. Rerun RAG eval và ghi postmortem.

## Incident: nghi rò rỉ dữ liệu/secret

1. Hạn chế truy cập, giữ bằng chứng và báo security owner.
2. Rotate/revoke key/JWT secret liên quan; không dán secret vào ticket/chat.
3. Kiểm tra structured logs, access logs và affected deployment.
4. Disable bad document/account theo quy trình được phê duyệt.
5. Xác định scope/timeline; làm nghĩa vụ thông báo theo pháp lý/chính sách.
6. Không để AI tự kết luận fraud hoặc breach.

## Incident: prompt injection/bypass

1. Lưu case đã redacted vào `security_eval.jsonl`.
2. Xác nhận tool trace và ownership; nếu có data exposure, theo data incident.
3. Sửa boundary/backend guard trước, prompt chỉ là defense bổ sung.
4. Rerun toàn bộ 509+ cases; gate critical bypass phải bằng 0.
5. Deploy theo checklist và theo dõi intent/tool distribution.

## Retention

Background task chạy ngay lúc startup và theo interval. Admin có thể chạy
`POST /api/v1/admin/retention/run`. Kết quả chỉ trả cutoff và số conversation bị
xoá. Nếu cleanup fail, app tiếp tục phục vụ nhưng log `retention_cleanup_failed`;
operator phải sửa trước chu kỳ kế tiếp.

## Knowledge maintenance hàng tháng

- Review effective/expiry date và version đang publish.
- Kiểm tra top no-evidence/no-result đã redacted.
- Review extraction/chunk/citation của policy thay đổi.
- Dependency update chỉ qua PR + test/eval.
- Model/embedding change luôn tạo baseline mới; dimension change cần re-embed và
  migration/index plan.
