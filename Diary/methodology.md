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

**Bổ sung (2026-10-22, đo trên cache thật của `main.py`):** nhận định "frame = `(region, delay)`" phải đọc là *"frame = tập **field id**"* — **không** phải "frame = cả nội dung metadata". Đo trên 16 scope đã cache: 16 folder nhưng chỉ **7 `catalog_frame_id` distinct**. `EUR/0/{TOP400,TOP1200,TOP2500,TOP800,TOPCS1600}` có **cùng id và cùng `coverage`/`dateCoverage`** (5 universe → 5 folder, 1 catalog). Nhưng `ASI/1/{TOP500,MINVOL1M,MINVOL10M}` có **cùng id nhưng `coverage` khác ở 1 274 / 15 755 dòng**, và đa số là `TOP500 = 0.0` → `MINVOL1M = 1.0/0.96/0.9` (999 dòng), tập trung ở `pv37` (622), `analyst14` (147), `analyst4` (104). ⇒ `coverage` là **tỉ lệ phủ trên tập instrument của universe đó**, và với `MINVOL1M`/`TOP500` (cùng top ~N theo tiêu chí khác nhau) việc một field không có trong `TOP500` là có thật.

**Alternatives considered:**
- Bỏ qua, coi mọi scope cùng `(region, delay)` là giống hệt nhau (như entry trước) — rejected, sai ở `ASI/1`: `ASI_1_TOP500` có **7 541** field eligible ở `MIN_COVERAGE=0.7`, `ASI_1_MINVOL1M` có **8 161**; tập eligible lệch **626 vị trí** (`|A−B|=3`, `|B−A|=623`).
- Xem `coverage` là thuộc tính không đổi của field — rejected, đo trực tiếp trên cache.
- Gộp 41 scope thành 16 catalog để tiết kiệm tải — deferred, xem entry 2026-10-22T15:46 về weighting.

**Rationale:** `coverage` là tỉ lệ phủ theo universe, nên nó là **thành phần của frame**, không phải metadata cố định. Frame đầy đủ = `(region, delay, universe)` + `catalog_frame_id`, và phải kèm cả fingerprint của tập eligible nếu muốn tái lập *đúng tập field lấy mẫu được*.

**Impact on reported results:** Mọi tỷ lệ "eligible / catalog" phải tính **trong scope đã ghi nhãn**, không được gộp 41 scope rồi chia tổng: `grand_eligible / grand_total` hiện in trong `main.py:193` cộng dồn 41 scope, tức **đếm trùng cùng một field 5–6 lần**. Đây là con số scope-field, không phải catalog size — khác hẳn khi claim "số field dùng được".

**Sentiment:** 8 — sửa một nhận định đã ghi vào `Docs/random-field-pipeline-proposal.md` §2 và vào `Diary/methodology.md`; frame sai thì mọi tỷ lệ eligible sau đó sai.
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

## 2026-10-22T08:27:00Z | methodology | score: 7

**Decision:** Cache catalog trên **đĩa vật lý** dạng `.npz` columnar theo lưới (cột × block 8192 dòng), kèm `frame_id = sha256(sorted(field_ids))[:8]` trong metadata; tập eligible lưu **riêng** dưới dạng `.npy` chỉ chứa row position.

**Alternatives considered:**
- Giữ CSV — rejected: đọc 3 dòng cũng phải parse cả file; CSV không giữ được thứ tự dòng như một khái niệm, nên "lấy vài dòng" không có nghĩa.
- Parquet + `pyarrow` — rejected: cần dependency mới, và parquet cho lazy *row group* nhưng không cho tổ hợp "block × cột" tự do như npz; đổi dependency để lấy lợi ích nhỏ hơn giá trị.
- 1 file npz per (cột, block) — rejected: 47 706 × 19 dòng → hàng trăm file, quản lý file nặng hơn lợi ích.
- Lưu eligible dưới dạng CSV riêng — rejected: nhân bản dữ liệu, và phải parse lại đúng cái ta muốn bỏ.
- Nén toàn bộ 1 array lớn — rejected: một member = một lần giải nén toàn bộ, mất đúng lợi ích lazy.

**Rationale:** Yêu cầu là "chỉ load các idx cần thiết". Điều đó đòi hỏi hai điều kiện: (i) một tập chỉ số dòng tồn tại được ngoài bảng dữ liệu (→ `.npy` row position), và (ii) địa chỉ hóa giữa chỉ số dòng và byte trên đĩa mà không phải parse (→ lưu theo block, block = member). `frame_id` ghi vào metadata để một run sau có thể xác nhận nó đang chạy trên đúng snapshot catalog, không chỉ "đúng seed".

**Impact on reported results:** Không đổi bất kỳ con số nào. Nhưng nó làm *có thể* chốt `frame_id` cho mọi lần lấy mẫu — một điều kiện tiên quyết đã nêu ở `Docs/random-field-pipeline-proposal.md` §7 và chưa có cơ chế thực thi. Lưu ý: cache là snapshot của thời điểm tải; catalog có dòng chảy mạnh (4 042 field mới trong 2026-04) nên `frame_id` phải được báo cáo cùng mọi kết quả.

**Sentiment:** 7 — là quyết định hạ tầng quyết định khả năng tái lập, không đổi kết quả; cần nêu rõ trong paper rằng frame được đóng băng bằng content-hash.

## 2026-10-22T09:27:00Z | methodology | score: 7

**Decision:** Loại region `ALL` khỏi scope space, và **enumerate** toàn bộ 41 scope hợp lệ thay vì mô tả cấu trúc lồng của API.

**Alternatives considered:**
- Giữ `ALL` — rejected: `ALL` không phải một equity market region mà là phân tách theo size của toàn platform; universe của nó (LARGE / MEDIUM / SMALL) không dùng được cho region nào khác. Nếu để vào, sampling sẽ sinh scope có ý nghĩa khác hẳn (cross-section toàn bộ platform thay vì một thị trường).
- Giữ cây `region → delay → universe` như API — rejected: không phục vụ mục tiêu lấy mẫu. Yêu cầu thực tế là "random một scope hợp lệ", mà cây bắt buộc phải biết region trước mới biết delay hợp lệ → 3 bước lồng nhau, mỗi bước là một phép lọc có thể rỗng.
- Liệt kê 462 tổ hợp phẳng (11 × 2 × 21) rồi lọc — rejected: 421 scope không tồn tại; nếu lọc sai thì im lặng sinh ra scope giả.
- Suy ra tập universe chung cho mọi region — rejected: universe phụ thuộc region (TOP3000 có ở USA và GLB nhưng không có ở EUR).

**Rationale:** Kiểm chứng trên live API: tập universe của một region **giống hệt nhau ở mọi delay** mà region đó hỗ trợ (cả 11 region, không ngoại lệ). Nghĩa là lồng của API chỉ là artefact của settings widget chứ không phải ràng buộc dữ liệu → phép cross product `{region} × {delays(region)} × {universes(region)}` **không mất scope nào**. Enumerate kết quả đó thành 41 dòng phẳng: mỗi dòng hợp lệ *by construction*, nên lấy mẫu là một draw duy nhất và không cần bước kiểm tra sau draw.

**Impact on reported results:** Không có con số nào đổi — đây là định nghĩa tập scope, không phải phép đo. Điều cần nêu khi báo cáo: draw đều trên 41 scope là **uniform trên scope**, không uniform trên region (USA 12/41 ≈ 29 %, KOR và IND mỗi region 1/41 ≈ 2.4 %). Nếu mục tiêu là phủ đều các thị trường thì phải draw 2 tầng, và đó là quyết định sampling chưa chốt. `ALL` bị loại là một quyết định định nghĩa tập, cần được nêu rõ vì nó thu hẹp scope space từ 44 xuống 41.

**Sentiment:** 7 — flatten được là có điều kiện (verify trên toàn bộ region, không phải suy ra từ vài ví dụ), và loại `ALL` là quyết định định nghĩa tập mà reviewer sẽ hỏi.

## 2026-10-22T15:46:39Z | methodology | score: 9

**Decision:** Khi lấy mẫu trên 41 scope, **phải ghi rõ đây là uniform trên scope, không phải uniform trên catalog** — và phải báo cáo cái giá của sự khác biệt đó thay vì coi là vô hại.

**Alternatives considered:**
- Draw uniform trên 16 catalog (`(region, delay)`) để mỗi field-set được chọn đều nhau — rejected (chưa quyết định, nhưng đây là ứng viên chính): 41 scope phủ **16** catalog khác nhau, nên draw uniform trên scope **tăng trọng số** cho catalog nhiều universe.
- Draw uniform trên 16 catalog, mỗi catalog lại chọn 1 universe uniform — chưa chốt, xem entry kế.
- Tuyên bố "uniform trên 41 scope" là đủ trung thực — rejected, con số 53.7 % là đủ để reviewer hỏi ngay.

**Rationale (đo trên `config/scopes.yaml`, 41 scope → 16 catalog):**

| catalog | số universe | tỉ trọng draw uniform trên scope |
|---|---|---|
| `USA/0`, `USA/1` | 6 mỗi cái | 14.6 % mỗi cái |
| `EUR/0`, `EUR/1` | 5 mỗi cái | 12.2 % mỗi cái |
| `GLB/1` | 4 | 9.8 % |
| `ASI/1` | 3 | 7.3 % |
| `HKG/1`, `TWN/1` | 2 mỗi cái | 4.9 % mỗi cái |
| 8 catalog còn lại (`CHN/0,1`, `DEU/0,1`, `GBR/0,1`, `IND/1`, `KOR/1`) | 1 mỗi cái | 2.4 % mỗi cái |

Nói cách khác: **`EUR` + `USA` chiếm 22/41 = 53.7 % draw nhưng chỉ 4/16 = 25 % catalog**; ngược lại mỗi catalog "lẻ" (`KOR/1`, `IND/1`, `GBR/0`, …) chỉ 2.4 % thay vì 6.25 % (= 1/16) như kỳ vọng của uniform. Và vì `EUR/1` lớn hơn `KOR/1` rất nhiều (35 225 vs ~3 000), draw uniform trên scope **lệch mạnh về catalog lớn**, không chỉ lệch về region.

**Impact on reported results:** Bảng phân phối draw phải cột **`region` + `delay` + `universe` + `catalog_frame_id`**, và phải có một dòng nêu rõ quy ước weighting. Nếu kết luận phụ thuộc vào việc mẫu có phủ đều 16 catalog hay không (ví dụ: claim "kết luận không nhạy với region"), thì draw uniform trên scope **không** đủ để chứng minh claim đó — phải chạy thêm uniform trên catalog rồi so sánh.

**Sentiment:** 9 — ảnh hưởng trực tiếp kết luận nghiên cứu (liệu claim có nhạy với region hay không), và dễ bị reviewer bắt vì 22/41 là con số rất rõ.

## 2026-10-22T18:31:01Z | methodology | score: 8

**Decision:** `check_login()` chỉ là **điểm kiểm tra một lần lúc đầu run**, không phải đếm ngược liên tục giữa các scope.

**Alternatives considered:**
- Gọi `check_login()` giữa mỗi scope trong `run()` — tốn 41 `GET /authentication`, và chỉ phát hiện hậu quá (token chết ở scope 30 thì 29 scope đã tải xoong rồi mới biết).
- Đặt deadline cứng (`sleep` tới khi hết hạn rồi login lại) — sai với `RELOGIN_THRESHOLD_SECONDS` vốn cố ý *kiểm tra trước khi dùng* chứ không ngủ chờ.
- Gọi lại trước mỗi `fetch_scope` — nhiều nhất khi 41 scope đều miss cùng lúc, tức là đúng trường hợp cần nó nhất.

**Rationale:** Số giây còn lại là thời gian token **sống**, đếm từ lúc `check_login()` chạy — không phải deadline của một run dài. Ước tính 41 scope hết hạn cùng lúc ⇒ vài trăm request; nếu mỗi request ~1 s theo rate limit thì vượt 67 min, tức là có thể vượt cả token 72 min. Một số kiểm tra ở đầu không bảo đảm token sống tới cuối.

**Impact on reported results:** Cache hiện tại đủ tươi (41/41, `ASI_1_MINVOL10M` còn 14.93 d) nên run hiện tại **không gọi API nào** ⇒ token không liên quan, con số `4068s` chỉ là thông tin. Nhưng khi 25 scope chưa cache kia hết hạn đồng loạt thì run đầu tiên là lúc con số này có ý nghĩa, và nếu run đó chết giữa chừng thì phải chạy lại từ đầu (không có resume theo scope). Nếu một reviewer hỏi "run dài bao lâu, token có đủ không", câu trả lời hiện tại là **không được đảm bảo** — cần ghi vào limitation, hoặc thêm checkpoint giữa các scope.

**Sentiment:** 8 — không ảnh hưởng số đã báo cáo, nhưng nó là giới hạn của thiết kế auth hiện tại mà reviewer rất dễ hỏi, và đã được nói ra rõ với user thay vì để ngầm.

## 2026-10-23T07:12:00Z | methodology | score: 6

**Decision:** Bảng operator lọc `scope == "REGULAR"` (84/103), in `level` nguyên trạng, hiển thị `null` thành `-`.

**Alternatives considered:**
- Lọc `level == "ALL"` (66 operator) — bỏ 18 operator chưa xếp hạng; sai vì mọi operator REGULAR đều dùng được trong expression, `level` là metadata quyền hạn chứ không phải điều kiện dùng được.
- Lọc thêm theo `field_type` (MATRIX/VECTOR/GROUP) — `/operators` không mang thông tin này; suy ra từ tiền tố `vec_` là heuristic không có trong API contract.
- Không in `level` — mất thông tin phân quyền mà reviewer cần khi hỏi "alpha này dùng operator có được không".

**Rationale:** `ace_lib.generate_alpha` đặt `"language": "FASTEXPR"` cho **mọi** alpha type, còn `how_to_use.py:186-190` ghi rõ `REGULAR` = operator dùng trong Alpha Expression, `SELECTION` = SuperAlpha Selection, `COMBO` = SuperAlpha Combo. Nên "chỉ REGULAR" = đúng tập operator hợp lệ để viết expression của một REGULAR alpha. `level = null` là một trong hai giá trị hợp lệ của trường, không phải dữ liệu thiếu — hiển thị `-` thay vì `nan` để không bị đọc nhầm là lỗi fetch.

**Impact on reported results:** Không đổi con số nào. Nhưng 84 operator này là **input của bước sinh expression**, và 5 trong 7 category có cả operator `level=null` (`ts_ir`, `vec_max`, `group_sum`, `vector_neut`, `tail`) — quy trình sinh alpha tự động có thể sinh expression mà tài khoản chưa đủ quyền chạy. Nếu sau này gate bằng `level`, phải chấp nhận mất 18 operator.

## 2026-10-23T07:30:00Z | methodology | score: 7

**Decision:** Chia 84 operator REGULAR thành 3 bucket theo **data field type đầu vào** thay vì 7 category của platform: MATRIX 67, VECTOR→MATRIX 7 (`vec_` prefix), GROUP 10 (`group_` prefix hoặc `\bgroup\b` trong definition).

**Alternatives considered:**
- Giữ 7 category của platform (`Time Series`/`Arithmetic`/...) — phân loại theo **hành vi toán học**, không theo **kiểu dữ liệu đầu vào**; không trả lời được câu "với field type nào thì dùng operator nào", tức là thứ quyết định expression có hợp lệ hay không.
- Bucket VECTOR dùng `category == "Vector"` của platform — dùng được nhưng khóa vào taxonomy API có thể đổi; tiền tố `vec_` là quy ước ổn định hơn và là điều `how_to_use.py:173` dùng để giải thích ("use `vec_` operator to aggregate vector data and transform it to a matrix").
- Bucket GROUP chỉ dựa vào arg tên `group` — bỏ sót `group_cartesian_product(g1, g2)`, là group operator không có arg matrix.
- Bucket GROUP dựa vào `category == "Group"` của platform — trùng kết quả, nhưng nhét 1 heuristic (prefix + regex) vào 1 heuristic (category) là thừa.

**Rationale:** Phân loại được kiểm chứng độc lập: `pd.crosstab(category, bucket)` trên dữ liệu live cho khớp **1-1 tuyệt đối** — `Vector` 7/7 vào VECTOR, `Group` 10/10 vào GROUP, 5 category còn lại 67/67 vào MATRIX, overlap `vec_ ∧ group` = 0. Vậy quy tắc suy ra từ tiền tố + nội dung definition **tái tạo đúng** taxonomy platform mà không cần đọc nó — tức là nó bắt đúng cái phân loại đó, chứ không phải một cách chia khác ngẫu nhiên.

Điểm mấu chốt về mặt nghiên cứu: **một operator không phải hàm một-input**. `ts_sum(x, d)` chỉ nhận MATRIX; `vec_avg(x)` chỉ nhận VECTOR và trả MATRIX; `group_zscore(x, group)` cần **cả hai** field type cùng lúc. Nếu bước sinh expression về sau lấy field ngẫu nhiên từ archive mà không biết bucket của operator, nó sẽ sinh ra expression không compile được — đây là lý do việc bucket này phải tồn tại **trước** bước sinh chứ không phải để cho đẹp bảng in ra.

**Impact on reported results:** Không đổi con số nào. Nhưng nó định nghĩa không gian mẫu cho bước sinh expression: 67 operator chấp nhận MATRIX, 7 chấp nhận VECTOR (và trả về MATRIX để đưa tiếp xuống 67 operator kia), 10 cần MATRIX + GROUP. Lưu ý: 6 operator MATRIX viết bằng **infix** chứ không phải hàm (`less` → `input1 < input2`, `greater`, `equal`, `not_equal`, `less_equal`, `greater_equal`) cộng `ts_step(1)` — parser args tự động sẽ không lấy được input cho chúng.

## 2026-10-23T17:31:00Z | methodology | score: 7

**Decision:** Đặt tên bucket của `ts_step` là `MATRIX_GENERATED`, không phải `MATRIX_CONSTANT`.

**Alternatives considered:**
- Giữ `MATRIX_CONSTANT` — sai về mặt ngữ nghĩa: tên gợi ý giá trị không đổi theo thời gian, trong khi `ts_step(1)` sinh ra chuỗi **1, 2, 3, 4, …** — thay đổi mỗi ngày. Tên cũ mô tả sai đối tượng mà nó gán nhãn.
- `MATRIX_NULLARY` — đúng về số argument (0 data field) nhưng nói về **arity** chứ không nói về **vai trò**: nhiều operator khác cũng có 0 data field (`ts_step` là ví dụ duy nhất trong 84, nhưng tên gọi chung sẽ không gợi ra rằng đây là nhóm sinh giá trị).
- Gộp `ts_step` vào `MATRIX_UNARY` — sai về typing: `ts_step` không biến đổi một field nào, nó **sinh** chuỗi. Gộp sẽ làm sai mô tả của cả 40 operator unary.

**Rationale:** `MATRIX_GENERATED` mô tả đúng cả hai vế: không tiêu thụ field nào (khác với `MATRIX_UNARY`) **và** vẫn trả về một MATRIX (khác với `GROUPING` vốn không có matrix nào đi ra). Bucket này có đúng 1 thành viên, nên tên của nó chính là định nghĩa của nhóm — một tên sai sẽ lan ra mọi nơi nó được nhắc tới.

**Impact on reported results:** Không đổi con số nào, không đổi phân loại của operator nào (CSV regenerate ra **byte-identical**, md5 `85b986a9...`). Nhưng tên bucket xuất hiện trong tài liệu (`Docs/all-operators.md`), trong cột `category` của CSV và trong entry diary cũ — nếu để sai, người đọc tài liệu sẽ hiểu `ts_step` trả về hằng số, tức là không dùng được làm trục thời gian cho `ts_regression`.

**Sentiment:** 7 — tên bucket là thứ reviewer đọc đầu tiên khi tra cứu operator; một tên sai về ngữ nghĩa là lỗi tài liệu, không chỉ là lỗi thẩm mỹ.

## 2026-10-24T07:13:11Z | methodology | score: 8

**Decision:** Rút tham số ngẫu nhiên của FASTEXPR theo **hai phân phối**: `uniform` (mặc định của `sample_int`) và `balanced` (chia 5 bucket theo tỉ lệ, mỗi bucket 20%). Phân phối `balanced` chỉ áp cho **window `d`**; `lag` và `rettype` luôn uniform.

**Alternatives considered:**
- Chỉ giữ `uniform` — đơn giản, nhưng 252 giá trị window có xác suất đều khiến **97.6% lần rút rơi vào 3 bucket đầu** (`d ≤ 66`). Các window dài (`d > 126`, tức 50% năm giao dịch) chỉ chiếm 0.4% mẫu → gần như không được thử.
- Chia bucket theo **số ngày cố định** (`_REFERENCE_CUTS = (5, 22, 66, 126)` scale theo 252) — vẫn hard-code 252, sai khi range không phải 252 ngày.
- Chia **nhiều hơn 5 bucket** (ví dụ 10) — tăng độ phân giải nhưng mỗi bucket càng nhỏ, xác suất rơi vào bucket ngắn vẫn phải bù cho độ dài bucket lớn; 5 là số đủ để phủ 5 vùng horizon mà một rolling window hay được dùng (1 tuần, 1 tháng, 1 quý, nửa năm, 1 năm).
- Áp `balanced` cho `lag` và `rettype` — **không có nghĩa**: `lag` (độ trễ) và `rettype` (loại đầu ra: residual, beta, alpha…) là *enum*, không phải *horizon*. Chia bucket theo tỉ lệ trên tập enum là vô nghĩa, và tạo ra phân phối lệch trong khi không có lý do thống kê.

**Rationale:** Mốc 252 là **năm giao dịch**, và 5 bucket `1-5, 6-22, 23-66, 67-126, 127-252` tương ứng 5 vùng horizon theo thói quen dùng thực tế: 1 tuần, 1 tháng, 1 quý, nửa năm, 1 năm. Tỉ lệ của chúng (`5/252, 22/252, 66/252, 126/252`) được giữ làm hằng số, còn **kích thước khoảng** thay đổi theo từng lần rút — vì vậy bucket không bị gắn cứng vào 252 ngày. Với khoảng `(1, 252)` (window) và `(0, 5)` (lag), cùng một bộ tỉ lệ cho ra 5 bucket trên cả hai, đúng như yêu cầu "252 không fixed nên cut point cũng không fixed được".

Điểm quan trọng về mặt phương pháp: `balanced` **không** làm mọi giá trị bằng nhau. Mỗi giá trị trong bucket thứ 5 (`127-252`, 126 phần tử) có xác suất `0.2/126 ≈ 0.16%`, còn mỗi giá trị trong bucket thứ nhất (`1-5`) có `0.2/5 = 4%`. Đây là hệ quả cố ý: mục tiêu là cân bằng **quy mô horizon** chứ không phải cân bằng **số ngày**.

**Impact on reported results:** Hiện **chưa có con số nào được báo cáo** bị ảnh hưởng — đây là bước sinh expression, chưa phải bước backtest. Nhưng nó quyết định **phân phối không gian alpha**: dưới `uniform`, khoảng thử nghiệm window tập trung ở ngắn hạn, nên alpha sinh ra chủ yếu là momentum/reversal ngắn hạn; dưới `balanced`, 20% mẫu rơi vào window ≥ 127 ngày, nên có alpha trung-dài hạn. Đây là bias **có hệ thống** trong kết quả, không phải nhiễu — reviewer sẽ hỏi "window của các alpha bạn là bao nhiêu" và câu trả lời phải nói rõ phân phối đã dùng.

Lưu ý phát hiện được, **chưa sửa**: default `distribution` không nhất quán giữa các tầng — `sample_int` và `MatrixBinary.get` mặc định `"uniform"`, còn `ts_corr`/`ts_covariance`/`ts_regression` mặc định `"balanced"`. Hệ quả: gọi trực tiếp hàm `ts_*` ra window balanced, còn gọi qua `get()` (đường mà `main.py` dùng) ra uniform. Cần một quyết định chung — hoặc mặc định `"uniform"` ở mọi tầng (giữ hành vi hiện tại của pipeline), hoặc `"balanced"` ở mọi tầng (giữ hành vi hiện tại của hàm `ts_*`). Đã ghi vào bảng giới hạn §9 của `Docs/all-operators.md`, chưa tự quyết.

**Sentiment:** 8 — quyết định này quyết định **bias của toàn bộ không gian alpha** sinh ra; reviewer chắc chắn hỏi về nó, và mặc định lệch giữa các tầng là loại lỗi âm thầm mà phải nói ra.
