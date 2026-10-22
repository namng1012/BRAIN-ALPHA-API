## 2026-10-21T15:53:16Z | methodology | score: 7

**Decision:** Re-authenticate only when the cached session has less than 2000 seconds of validity left; reuse the cached JWT otherwise.

**Alternatives considered:**
- Re-login on every run — rejected, hits the 5 logins/minute rate limit and risks an account lockout.
- Persist the JWT with an absolute expiry timestamp read from the token payload — rejected, the `exp` claim is not the same clock as the server-side session expiry, and a stale-but-unexpired JWT would still 401 mid-run.
- Trust the cached cookie without probing — rejected, a dead session would surface as a confusing 401 on the first real API call instead of at the login gate.

**Rationale:** The 2000-second threshold is the same constant used by `ace_lib.check_session_and_relogin` in `ACE_API__Gold_/ace_lib.py`, so re-auth happens while the session is still alive rather than after it dies. The probe itself is a cheap `GET /authentication` and does not count against the login rate limit.

**Impact on reported results:** None — this affects only session lifecycle, not any simulation or metric. It does mean a run started more than ~4 hours after the last login will trigger one persona flow, which is the intended behaviour.

**Sentiment:** 7 — defensible via the existing ACE convention, and it prevents a silent account lockout.

## 2026-10-21T16:47:38Z | methodology | score: 7

**Decision:** Treat the BRAIN scope space as the 44 tuples enumerated by the `OPTIONS /simulations` tree, and treat the universe name as **scoped to its region** rather than a global key.

**Alternatives considered:**
- Probe `/data-sets` + `/data-fields` to discover which scopes have data — rejected, it costs 88 requests and cannot separate "invalid scope" from "empty scope", so the resulting scope set would be data-dependent rather than platform-defined.
- Key everything by universe name alone (21 names) — rejected, `TOP3000` exists under both USA and GLB, `MINVOL1M` under both GLB and ASI, and `TOP500` under four different regions; the same name denotes different instruments, so any per-scope statistics would be silently merged.

**Rationale:** The platform publishes the admissible scope set in the `OPTIONS` payload, which is the authoritative and cheapest source. Keeping the tuple `(region, delay, universe)` as the unit of analysis is what makes per-region and per-delay comparisons meaningful later; collapsing to universe names would conflate instruments across markets and make the resulting counts non-comparable.

**Impact on reported results:** Any "how much data is available" figure must be stated per scope and labelled with the full tuple. Aggregating across the 44 scopes double-counts fields that exist in several universes within the same region, so a raw sum of per-scope field counts is **not** a catalog size and must not be reported as one.

**Sentiment:** 7 — affects how the data-availability baseline for the paper is defined, and the universe-name collision is a silent-wrong-answer trap.

## 2026-10-21T16:51:19Z | methodology | score: 8

**Decision:** Report the data-availability baseline as a **per-scope** figure (`EQUITY / USA / delay 1 / TOP3000` → 286 datasets, 75 926 data fields), never as a platform-wide total.

**Alternatives considered:**
- Sum `n_datafields` over all 44 scopes — rejected, the same field id appears in several universes of the same region and across regions, so the sum counts each field many times and is not a catalog size.
- Deduplicate by field `id` across all scopes — deferred, it is the correct catalog size but needs a full 88-request sweep, which currently fails on the missing retry in `BrainData._get`.
- Quote the 75 926 figure without its scope label — rejected, a bare number invites the reviewer to read it as platform-wide.

**Rationale:** 75 926 fields over 286 datasets, of which 18 971 are `Model` and 12 825 are `Price Volume`, describes **one liquid equity universe**, not the platform. `Model` dominating at ~25 % means a large part of the catalog is user-trained published models rather than raw vendor data — which changes how "available features" should be characterised in the paper. `Fundamental` (11 041 fields, 23 datasets) is the cleanest semantic group for a defensible baseline because it is vendor financial-statement data with no model or sentiment dependence.

**Impact on reported results:** The baseline is only defensible if labelled with the full tuple `EQUITY/USA/1/TOP3000`. A per-region figure must not be compared to this USA-only number without saying so, and if the paper later claims breadth across regions the scope tuple must be reported next to every count.

**Sentiment:** 8 — this is the number a reviewer will ask about first, and mislabelling it as platform-wide would be a factual error in the paper.

## 2026-10-21T17:21:58Z | methodology | score: 8

**Decision (đính chính entry trước):** `universe` **không** phải là tham số lọc tập field — nó là tham số chọn *tập instrument* để backtest. Frame hiệu dụng của catalog là **cặp `(region, delay)`**, không phải tuple 4 thành phần.

**Alternatives considered:**
- Giữ tuple `(region, delay, universe)` làm đơn vị phân tích (như entry 16:51) — rejected, đo overlap thực tế: `USA/1/TOP3000` và `USA/1/TOP500` trả về **cùng một tập 75 926 id** (Jaccard 1.000). Universe không đổi tập id.
- Dùng `dataset` (286) làm frame thứ cấp thay vì `field` — deferred, chưa rõ có hợp với mục tiêu "3 field ngẫu nhiên" hay không.

**Rationale:** Đo trực tiếp trên tập id cho thấy `delay` mới là chiều cắt mạnh (82 % field chỉ ở delay 1; intersection `USA/1` ∩ `USA/0` = 13 547) và `region` gần như tách rời (Jaccard 0.239 với EUR). `ALL/delay 1/LARGE` rỗng. Nghĩa là: universe quyết định *backtest trên tập instrument nào*, còn `(region, delay)` quyết định *field nào tồn tại*.

**Impact on reported results:** Mọi figure "số field trong scope" phải gắn `(region, delay)`; gắn thêm `universe` thì vẫn đúng nhưng gây hiểu nhầm rằng universe đóng vai trò lọc. Entry `16:51` giữ nguyên phần "per-scope, không cộng dồn" — phần đó vẫn đúng; chỉ cần hiểu là dedup theo `id` **trong từng cặp `(region, delay)`**, không phải trong 44 scope.

**Sentiment:** 8 — corrects a claim already written into `Docs/data-description.md`; a wrong unit of analysis propagates into every count downstream.

## 2026-10-21T17:21:58Z | methodology | score: 7

**Decision:** Với câu hỏi "cho tôi 3 data field ngẫu nhiên", **không dùng một tiêu chí lọc duy nhất** — mọi lựa chọn lọc đều là quyết định nghiên cứu và phải báo cáo kèm, không ẩn.

**Alternatives considered:**
- Lọc theo `coverage ≥ 0.5` (đề xuất v1) — bỏ 5 565 field, còn ~70 361. Rủi ro: đây là tiêu chí *do ta chọn*, nên "random trong 70 361" không còn là random trong catalog.
- Không lọc gì ngoài `coverage == 0` — trung thực hơn về mặt phân phối, nhưng 82 field chết vẫn vào frame và mọi draw có xác suất nhỏ rơi vào chúng.
- Lọc `userCount > 0` (bỏ 25 549 field) — rejected as a silent default: field được dùng nhiều thường là field tốt → bỏ nó là survivorship bias theo hướng *tăng* tỉ lệ thành công, và phải nêu rõ trong paper.
- Lọc theo `dateCreated` gần đây — rejected, 22 736 field sinh trong 2026-03 và 4 042 trong 2026-04 → lọc theo thời gian tạo là data-snooping risk khi backtest trùng kỳ.

**Rationale:** Mỗi bộ lọc khác nhau trả lời một câu hỏi khác nhau và cho ra "random baseline" khác nhau. Bởi vậy frame phải được **ghi rõ trong output** (số field eligible, tỉ lệ lọc, phân phối category sau lọc) để người đọc biết baseline này là baseline của *frame nào*.

**Impact on reported results:** Bảng kết quả phải kèm cột mô tả frame (eligible count, filter đã dùng). Claim "random 3 field" chỉ có nghĩa cùng với claim "random 3 field trong frame F", và F phải được nêu.

**Sentiment:** 7 — this is the "sampling frame" question every reviewer of an empirical paper asks first.

## 2026-10-22T06:42:00Z | methodology | score: 8

**Decision:** Với câu hỏi "khi `valueScore` tăng/giảm thì có gì thay đổi", **đo theo từng nhóm `valueScore` (bảng mean-per-level + crosstab) thay vì suy đoán định nghĩa**. Vì `valueScore` là biến phân loại thứ tự 1–7 và chỉ có 1 quan sát ở mức 7, không dùng được hồi quy tuyến tính.

**Alternatives considered:**
- Suy đoán từ tên + tài liệu chính thức — rejected: BRAIN không publish định nghĩa `valueScore`, sẽ ra khẳng định không nền tảng.
- Chỉ báo cáo Pearson — rejected: che mất quan hệ phi tuyến; kết quả cho thấy nhánh "giảm" mạnh hơn nhánh "tăng", Pearson không nắm được.
- OLS trên 286 điểm — rejected: `alphaCount` cực lệch (5.6M vs 6), residuals vi phạm giả định. Đã log1p trước khi so sánh.

**Rationale:** Cách trung tính nhất là chỉ báo cáo cái quan sát được, không gán nhãn cơ chế khi chưa có bằng chứng — dạng "describe before you explain".

**Impact on reported results:** Nếu ai dùng `valueScore` như proxy "chất lượng dataset", kết quả này **phủ nhận** cách hiểu đó: `valueScore` cao gắn với dataset *ít* dùng hơn, *nhỏ* hơn, độ phủ *thấp* hơn; nhưng lại gắn với `pyramidMultiplier` cao hơn và được cập nhật gần đây hơn. Chưa kết luận được "mới" vs "tốt" — cần dữ liệu theo thời gian mới tách được.

**Kết quả đo (286 dataset, `EQUITY/USA/1/TOP3000`):**

| valueScore | n | pyramidMultiplier | coverage | fieldCount | alphaCount (median) | vector_share | updated 6 tháng |
|---|---|---|---|---|---|---|---|
| 1 | 56 | 1.159 | 0.800 | 363 | 13 340 | 0.285 | 0.66 |
| 2 | 64 | 1.208 | 0.844 | 305 | 2 502 | 0.315 | 0.58 |
| 3 | 70 | 1.239 | 0.797 | 237 | 501 | 0.358 | 0.63 |
| 4 | 48 | 1.248 | 0.762 | 253 | 176 | 0.401 | 0.75 |
| 5 | 33 | 1.364 | 0.730 | 175 | 74 | 0.617 | 0.82 |
| 6 | 14 | 1.350 | 0.726 | 111 | 47 | 0.458 | 0.93 |
| 7 | 1 | 1.400 | 0.438 | 8 | 6 | 1.000 | 1.00 |

Tổng `alphaCount` toàn scope: vs=1 → 5 609 938; vs=7 → 6. `pyramidMultiplier` **lồng nhau** theo `valueScore` (vs=1 có đủ 5 mức 1.0–1.4; vs=7 chỉ 1.4) → không phải hàm xác định của nhau.

**Sentiment:** 8 — đảo ngược cách hiểu mặc định về `valueScore`, ảnh hưởng trực tiếp tới cách chọn dataset cho mọi experiment sau này.

## 2026-10-22T07:20:00Z | methodology | score: 7

**Decision:** Hạ `RELOGIN_THRESHOLD_SECONDS` từ 2000 xuống **1000** (≈ 17 phút) trong `Functions/login.py`.

**Alternatives considered:**
- Giữ 2000s như `ace_lib.check_session_and_relogin` — rejected: đệm 33 phút là quá nhiều so với thời lượng quan sát thực tế của một lần chạy, và mỗi lần login đều tiêu tốn quota (5 lần/phút, 25 lần/ngày theo Persona).
- Suy ra threshold động từ `X-RateLimit-Remaining-*` header — rejected: header này báo rate limit của endpoint, không phải thời hạn session; hai khái niệm khác nhau.
- Bỏ `check_login()` live probe, chỉ so timestamp cache — rejected: `exp` trong JWT không cùng clock với session expiry phía server (đã loại ở entry 2026-10-21).

**Rationale:** Ngưỡng phải lớn hơn thời lượng tối đa của một lần chạy để không bao giờ thấy session chết giữa chừng. Quan sát được trong log: các lần chạy `main.py` kéo dài vài phút, session còn sống 1300–13700 s. 1000 s giữ được đệm ~17 phút — đủ cho một lần chạy thực tế — đồng thời giảm số lần phải login lại so với 2000 s. Đây là hằng số *vận hành*, không ảnh hưởng bất kỳ con số báo cáo nào.

**Impact on reported results:** None. Tác động duy nhất là số lần persona flow được kích hoạt. Với ngưỡng 1000 s, một run bắt đầu cách lần login gần nhất hơn ~17 phút sẽ login lại (trước đây là ~33 phút).

**Sentiment:** 7 — thay đổi nhỏ nhưng cần được nêu trong paper vì nó quyết định số lần chạy có thể thực hiện trong một ngày mà không bị khóa account.
