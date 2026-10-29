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

## 2026-10-24T08:37:06Z | methodology | score: 8

**Decision:** Trong 40 builder `MATRIX_UNARY`, **chỉ rút tham số có miền giá trị đã được platform document**; tham số mà catalog không liệt kê thì giữ nguyên giá trị platform ship.

**Alternatives considered:**
- Rút `ts_returns`' `mode` từ một miền tự đặt (ví dụ `(1, 2)`) — **bịa thuật toán**: platform chỉ ship `mode = 1`, mô tả chỉ nói "Returns the relative change in the x value", và web search (WorldQuant docs, AlphaLab, Tymen wiki, các repo `world-quant-brain`) **không tìm được** tài liệu nào liệt kê mode. Đây là vi phạm trực tiếp "never fabricate methods" — không có nguồn thì không được giả định miền giá trị.
- Bỏ hẳn `mode` khỏi expression (`ts_returns(x, d)`) — sai: platform ship `mode = 1` **có mặt trong definition**, nên bỏ đi là lệch với cú pháp platform nhận, và `config` sẽ mất thông tin về tham số đó.
- Rút cả `mode` lẫn `constant`/`hump`/`sigma`/`target_tvr` — cùng lý do: các tham số này có giá trị cố định do chính operator định nghĩa, không phải người dùng chọn. Rút chúng sẽ tạo ra biến thể không có ý nghĩa nghiên cứu (ví dụ `hump = 0.37`).

**Rationale:** Ranh giới là **tính chất của tham số**, không phải "tham số nào có thể rút":

| Loại | Ví dụ | Hành động |
|---|---|---|
| Ngưỡng/độ dài | `d` (window), `k` (thứ hạng), `std` (số lệch chuẩn) | rút trong khoảng có ý nghĩa |
| Lựa chọn hữu hạn | `driver` (gaussian/cauchy/uniform), `dense` (bool) | rút trong tập đã nêu ở mô tả platform |
| Hằng của operator | `mode = 1`, `constant = 0`, `sigma = 1.0`, `hump = 0.01`, `lambda_min/max`, `target_tvr` | giữ nguyên, không vào `config` |

`driver` là trường hợp rõ nhất: mô tả platform nêu tên cả ba phân phối ("gaussian, cauchy, or uniform") nên rút được và miền là **có căn cứ**. `std` của `winsorize` cũng vậy: mô tả khuyến nghị "std values range from 2 to 5" và liệt kê xác suất cắt cho từng giá trị — đó là miền có nguồn. Ngược lại `mode` không có bất kỳ mô tả nào, nên rút nó là **đoán**.

**Impact on reported results:** Chưa có con số nào được báo cáo (đây là bước sinh expression, chưa phải backtest). Nhưng nó quyết định **không gian alpha** được khám phá: nếu `mode` được rút trong miền bịa, thì 50% alpha sinh ra sẽ dùng một chế độ tính lợi nhuận mà **không ai biết nó nghĩa là gì** — không giải thích được, không tái lập được, không kiểm chứng được. Giữ `mode = 1` nghĩa là mọi alpha `ts_returns` đều dùng một chế độ đã biết, và biến thể chưa rõ thì để ngỏ cho tới khi có tài liệu.

**Sentiment:** 8 — reviewer sẽ hỏi "alpha nào của bạn dùng `mode` khác 1?" và câu trả lời "không có, vì platform không document mode nào khác" là câu trả lời có căn cứ; ngược lại, miền giá trị bịa sẽ là điểm reviewer bắt được ngay.

## 2026-10-24T19:41:06Z | methodology | score: 9

**Decision:** Tách `OperatorProfile` thành 3 keys (`category`, `name`, `config`) và return tuple `(expression, profile)` từ mọi builder, thay vì return chỉ expression string và giữ inputs/matrics/expression trong profile.

**Alternatives considered:**
- **Giữ `expression` trong `OperatorProfile`**: profile sẽ self-contained, caller chỉ cần nhận một object. Loại bỏ vì expression là artifact phái sinh từ config, không phải config input — ghi lại nó trong profile là trùng lặp thông tin và gây nhầm lẫn về nguồn gốc (config sinh ra expression, hay expression sinh ra config?).
- **Giữ `inputs` và `matrics` trong profile**: có thể truy vết được các toán hạng đầu vào. Loại bỏ vì `inputs` chỉ là tên biến placeholder (`x`, `y`) không mang thông tin tái tạo; `matrics` là typo của "matrices" và chưa rõ ngữ nghĩa — cả hai không phải config mà là metadata về kiểu toán tử, đã có trong `category`.
- **Return chỉ expression, không có profile**: đơn giản nhất, giống code cũ. Loại bỏ vì mất khả năng reproduce — khi một expression tạo ra alpha tốt, không biết được nó dùng `seed` bao nhiêu, `distribution` nào, `d` bao nhiêu để replay hay debug.

**Rationale:** Pipeline tự động sinh alpha cần hai đầu ra riêng biệt:
1. **Expression** (ready-to-run FASTEXPR) để submit lên BRAIN API — đây là sản phẩm cuối.
2. **Config audit trail** (seed/stream/distribution/parameters) để ghi log, replay, debug — đây là metadata cho reproducibility.

Nhét cả hai vào một object thì caller phải biết key nào để lấy expression → coupling tăng. Tách ra tuple thì caller unpack ngay `expr, prof = ...` — code rõ ràng hơn, và caller chỉ dùng expression để submit thường không cần giữ profile (trừ khi ghi log). Convention này khớp với chuẩn Python: function thường return data trước, metadata sau (ví dụ `np.unique(return_counts=True)` return `(values, counts)`, không phải dict).

`config` dict chứa tất cả parameters ảnh hưởng đến expression: `seed`, `stream`, `d`, `method`, `distribution`, `driver`, `useStd`, v.v. — đủ để tái tạo expression bit-exact. Không chứa constant của operator platform (vd. `mode=1`, `constant=0`) vì chúng không phải config được sample mà là hằng số hard-code.

**Impact on reported results:** Chưa có số liệu backtest. Nhưng kiến trúc này quyết định liệu pipeline có thể **tái tạo alpha** hay không: nếu một alpha đạt Sharpe 2.5 nhưng không biết config, thì không thể verify lại expression, không thể ablation study trên từng parameter, không thể giải thích cho reviewer "alpha này khác alpha kia ở chỗ nào". Với `OperatorProfile` chứa đủ config, mọi alpha có audit trail đầy đủ từ lúc sinh ra.

**Sentiment:** 9 — cross-cutting, ảnh hưởng toàn bộ codebase operator (50 operators hiện tại, ~200 operators khi đủ 9 categories), quyết định reproducibility của toàn bộ pipeline, reviewer sẽ bắt buộc hỏi về design choice này.

## 2026-10-25T03:21:00Z | methodology | score: 10

**Decision:** Builder signatures phải nhận tất cả sampled parameters như optional arguments (`d=None`, `k=None`, `hump=None`, v.v.), chỉ sample khi parameter là `None`. Pattern: `if d is None: d = IntegerSampler.sample(...)` thay vì `d = IntegerSampler.sample(...)` luôn.

**Alternatives considered:**
- **Giữ pattern cũ — sample luôn bên trong, signature không nhận parameter:** đơn giản hơn, ít code hơn. Loại bỏ vì `config` lưu `{"d": 238}` nhưng không có cách gọi lại builder với `d=238` → không reproduce được bit-exact expression → phá vỡ audit trail.
- **Tách làm 2 methods — `random_last_diff_value()` và `fixed_last_diff_value(d)`:** rõ ràng về ý đồ (random vs fixed), tránh `if is None`. Loại bỏ vì nhân đôi số method (80 thay vì 40 cho MatrixUnary), và caller phải biết gọi method nào khi replay từ config → coupling tăng, DRY vi phạm.
- **Thêm parameter `seed` vào signature, dùng seed để reproduce:** signature `last_diff_value(x, seed)`, caller truyền seed cũ thì sẽ sample ra `d` giống cũ. Loại bỏ vì: (1) seed là implementation detail, không phải config user-visible; (2) khi cần ablation study (thử `d=21` vs `d=63` giữ nguyên mọi thứ khác), không thể chỉ thay `d` — phải tìm seed nào sinh ra `d=21`, seed nào sinh ra `d=63` → không khả thi.

**Rationale:** Reproducibility requirement của research codebase đòi hỏi: **từ `config` dict có thể tái tạo bit-exact expression**. Config chứa các giá trị đã sample (`{"d": 238, "driver": "gaussian"}`), không chứa seed/stream (vì đó là implementation detail). Khi replay, caller gọi `MatrixUnary.last_diff_value("field_a", d=238, driver="gaussian")` — builder nhận values cụ thể, không sample nữa, return expression giống hệt lần đầu.

Pattern này khớp với convention của MatrixBinary (đã có từ đầu): `ts_corr(x, y, d=None, seed=None)` — có thể gọi random `ts_corr(x, y)` hoặc fixed `ts_corr(x, y, d=96)`. Refactor này làm MatrixUnary đồng nhất với MatrixBinary.

31 trong 40 MatrixUnary operators có sampled parameters được refactor; 9 operators không đổi (không có parameters: `abs_`, `inverse`, `log`, v.v.). Seed logic giữ nguyên 100% (không thay đổi gì về `IntegerSampler.sample` hay stream constants) — chỉ thêm `if param is None:` guard.

Verified: `uv run python main.py` exit 0. Audit: rà soát toàn bộ `IntegerSampler.sample` với `WINDOW_DAYS` → xác nhận tất cả dùng `distribution="balanced"` (không có vi phạm convention).

**Impact on reported results:** Kiến trúc này là **foundation của reproducibility**. Mọi alpha expression từ giờ có thể:
1. **Replay bit-exact:** lưu config vào database, replay sau 6 tháng / 1 năm → expression giống hệt.
2. **Ablation study:** so sánh alpha A (`d=21`) vs alpha B (`d=63`) giữ nguyên mọi thứ khác — chỉ cần gọi builder với `d` khác nhau.
3. **Paper appendix:** liệt kê exact config của 100 top alphas trong table — reviewer có thể verify từng cái một.

Nếu không có pattern này, pipeline chỉ có thể sinh alpha mới, không thể tái tạo alpha cũ → không qualify làm research codebase.

**Sentiment:** 10 — đây là điều kiện tiên quyết (prerequisite) của reproducibility, ảnh hưởng toàn bộ workflow từ alpha generation → backtesting → publication. Không có quyết định này thì không thể đạt publication-grade reproducibility. Reviewer sẽ reject paper nếu không thể verify lại alphas.

## 2026-10-25T17:28:07Z | methodology | score: 6

**Decision:** Ngưỡng t1 (trigger `ts_rank(x, 252) > t1`) và t2 (đối số thứ hai của `ts_zscore`) lấy từ `FloatSampler` trong [0, 0.1], distribution mặc định "balanced", stream 1 và 2.

**Alternatives considered:**
- Giá trị cố định 0.01 và 0.002: bị user thay bằng random.
- Range mặc định 0..3 của `FloatSampler`: quá rộng cho ngưỡng trên ts_rank (∈ [0, 1]).

**Rationale:** Theo yêu cầu user. Range [0, 0.1] giữ trigger ở vùng đuôi thấp của ts_rank.

**Impact on reported results:** Đổi range thay đổi tần suất trigger của `trade_when`, ảnh hưởng turnover và PnL của alpha.

**Sentiment:** 6 — reviewer sẽ hỏi vì sao 0.1 và t2 có phải window hay không.

## 2026-10-25T17:29:46Z | methodology | score: 6

**Decision:** Exit condition của `trade_when` là `abs(ts_zscore(x, 252)) < t2`, t2 ~ FloatSampler [0, 0.1]; window của ts_zscore cố định 252, cùng window với trigger `ts_rank(x, 252) > t1`.

**Alternatives considered:**
- `abs(ts_zscore(x, t2))` với t2 là window: sai, t2 ∈ [0, 0.1] không phải window hợp lệ.

**Rationale:** Theo user. Cả hai thành phần dùng cùng lookback 252 ngày (một năm giao dịch), nhất quán với `if_else`.

**Impact on reported results:** t2 nhỏ nghĩa là chỉ giữ lệnh khi x gần trung bình 252 ngày của chính nó; đổi range của t2 thay đổi turnover.

**Sentiment:** 6 — reviewer sẽ hỏi vì sao range [0, 0.1] và vì sao 252 cố định.

## 2026-10-25T17:30:52Z | methodology | score: 6

**Decision:** Hai window của `trade_when` (d1 cho `ts_rank`, d2 cho `ts_zscore`) rút độc lập từ [1, 252], balanced, stream 3 và 4; stream 1 và 2 giữ nguyên cho t1 và t2 nên giá trị t1, t2 không đổi khi thêm draw.

**Alternatives considered:**
- Một window dùng chung cho cả hai: đơn giản hơn nhưng thu hẹp không gian tìm kiếm.
- Window cố định 252: bị user thay bằng random.

**Rationale:** Theo yêu cầu user. Range lấy từ `MatrixUnary.WINDOW_DAYS` để cùng phân phối với các ts_* operator khác.

**Impact on reported results:** Không gian alpha của `trade_when` rộng ra 4 chiều (d1, d2, t1, t2); window ngắn làm trigger nhiễu hơn và tăng turnover.

**Sentiment:** 6 — reviewer sẽ hỏi vì sao hai window độc lập.

## 2026-10-25T17:34:10Z | methodology | score: 6

**Decision:** Window d1 (`ts_rank`) và d2 (`ts_zscore`) của `trade_when` rút từ [100, 252], balanced, thay cho [1, 252].

**Alternatives considered:**
- [1, 252] (`MatrixUnary.WINDOW_DAYS`): window ngắn làm `ts_rank` và `ts_zscore` nhiễu, trigger thất thường.

**Rationale:** Theo user. Window dài (xấp xỉ nửa năm đến một năm giao dịch) cho ước lượng rank và z-score ổn định hơn.

**Impact on reported results:** Bỏ window < 100 làm giảm turnover và bỏ các biến thể phản ứng nhanh; range này lệch khỏi `WINDOW_DAYS` dùng cho các ts_* khác.

**Sentiment:** 6 — reviewer sẽ hỏi vì sao 100 và vì sao khác range của các ts_* operator còn lại.

## 2026-10-25T17:43:49Z | methodology | score: 7

**Decision:** Window của `ts_rank` bọc operand trong `if_else` rút ngẫu nhiên từ [60, 252] (độc lập cho x và y), thay cho hằng số 252.

**Alternatives considered:**
- Giữ 252 cố định: ổn định nhưng không khám phá được horizon ngắn hơn.
- Dùng chung một window cho x và y: so sánh `s1*rank_x > s2*rank_y` cùng horizon, nhưng user chưa yêu cầu.

**Rationale:** Theo user; cùng range [60, 252] với `trade_when`, nên hai template selector nhất quán.

**Impact on reported results:** Alpha sinh bởi `if_else` không còn tái lập từ expression cũ có 252 cố định. Phải ghi `dx`, `dy` trong profile để replay (đã làm). Hai operand có thể có horizon khác nhau, nên so sánh rank giữa hai thang thời gian khác nhau.

**Sentiment:** 7 — đổi phân phối alpha sinh ra, reviewer sẽ hỏi vì sao dx và dy độc lập.

## 2026-10-25T17:52:00Z | methodology | score: 8

**Decision:** Chốt giai đoạn 1 (expression cơ bản) ở 68/84 operator có builder; không sửa lỗi phát hiện ở `Group` mà ghi lại chờ user quyết định.

**Alternatives considered:**
- Sửa ngay `Group` mode 5: bị loại vì chưa biết mode 5 định dựng gì; sửa đoán là đổi hành vi khoa học mà không có nguồn.
- Đợi làm đủ 84 operator mới chốt: bị loại vì 16 operator còn lại (BOOLEAN, VARIADIC, GROUPING, `ts_step`) có độ phức tạp ghép nối khác hẳn, thuộc phạm vi giai đoạn sau.

**Rationale:** Mốc chốt cần kiểm được. Số 68 lấy bằng cách chạy từng tên của `cache/operators.csv` qua `get()`, không đếm tay.

**Latent scientific issue (không sửa, theo rule 04/09):** `Group` mode 4 và 5 ra cùng chuỗi `densify(group_cartesian_product(bucket(rank(x), ...), group))` cho cả 9 operator. `mode` rút đều `{1..5}` nên dạng này chiếm 40% mẫu thay vì 20%, và mode 5 không phải một biến thể riêng. Cần user chỉ nguồn hoặc ý định của mode 5.

**Impact on reported results:** Phân phối cấu trúc group trong alpha sinh ra bị lệch về dạng cartesian-product. Nếu sửa mode 5 thì mọi alpha `Group` sinh từ mode 5 sẽ đổi expression.

**Sentiment:** 8 — ảnh hưởng phân phối alpha, reviewer sẽ hỏi vì sao mode trùng nhau.

## 2026-10-25T17:52:00Z.1 | methodology | score: 5

**Decision:** Hai builder `SELECT` (`if_else`, `trade_when`) nằm trong class matrix và gắn `category` `MATRIX_BINARY` / `MATRIX_UNARY`, không phải `SELECT`.

**Alternatives considered:**
- Class `Select` riêng với `category="SELECT"`: khớp bảng §5 nhưng user chưa yêu cầu, và hai builder dùng chung `_profile` của class matrix.

**Rationale:** Giữ nguyên hiện trạng; ghi vào Docs §10.3 để giai đoạn 2 quyết định, vì bước ghép expression sẽ cần biết operator nào là selector.

**Impact on reported results:** Không đổi expression; chỉ đổi nhãn trong profile.

**Sentiment:** 5 — nhãn, nhưng có thể gây nhầm khi lọc theo bucket.

## 2026-10-25T18:08:37Z | methodology | score: 7

**Decision:** Chưa implement Theme; ghi lại phân bố `categoryid` của MATRIX `USA_1_TOP3000` (36854 field) làm cơ sở thiết kế.

**Alternatives considered:**
- Implement ngay: bị hoãn theo yêu cầu user. Đã chốt theme = `categoryid` và theme không có field thì bỏ qua; còn chờ chốt trọng số khi có nhiều theme (theo dòng hay đều theo theme).

**Rationale:** Random hiện tại rút đều theo dòng nên bị chi phối bởi vài category lớn: model 14591, analyst 6269, other 5834 (tổng 72.4% field); các category nhỏ như imbalance (2 field) gần như không bao giờ được chọn. Nếu theme chọn nhiều category, rút đều theo dòng sẽ lặp lại độ lệch này bên trong theme.

**Impact on reported results:** Cách trọng số theme (theo dòng hay theo theme) đổi phân phối field đầu vào của mọi expression sinh ra.

**Sentiment:** 7 — đổi phân phối lấy mẫu field, reviewer sẽ hỏi về trọng số.

## 2026-10-25T18:11:26Z | methodology | score: 6

**Decision:** Ghi nhận phạm vi theo scope của `categoryid`: chỉ 4/16 category có mặt ở cả 41 scope.

**Alternatives considered:**
- Chỉ ghi số liệu của `USA_1_TOP3000`: bị loại vì Theme sẽ dùng cho mọi scope, và category vắng làm theme ra rỗng.

**Rationale:** Với quy tắc "theme không có field thì bỏ qua" mà user đã chốt, nếu mọi category của theme đều vắng ở scope đang bốc thì kết quả rỗng. Cần biết điều này trước khi implement để quyết định rỗng thì xử lý thế nào.

**Impact on reported results:** Theme giống nhau cho ra tập field khác nhau giữa các scope; kết quả giữa scope không so sánh trực tiếp được nếu không ghi category thực sự có mặt.

**Sentiment:** 6 — ảnh hưởng thiết kế Theme, reviewer sẽ hỏi về scope thiếu category.

## 2026-10-25T18:15:27Z | methodology | score: 8

**Decision:** Theme khớp `categoryid`; khi có nhiều category, rút đều theo dòng trên tập field thuộc theme (pool), không chia đều theo category.

**Alternatives considered:**
- Chọn category đều trước rồi mới rút field: giữ cân bằng ngữ nghĩa, nhưng đổi cấu trúc rút (nhiều bước, mỗi category cần stream riêng). User chưa chốt nên chưa làm.
- Áp theme cho GROUP: bị loại. GROUP chỉ có 3 category (model, other, pv); với theme ['analyst','model','news'] chỉ còn đúng 1 field (một field `model`), nên mọi expression sẽ dùng cùng một group field.

**Rationale:** Cách đơn giản nhất giữ nguyên cơ chế cũ (`choice` không hoàn lại) trên tập con vị trí. Đo với theme đã thử, MATRIX 2000 draw: model 1383, analyst 578, news 39 (khớp tỉ lệ field 14591 : 6269 : 502). Tức `news` gần như vắng mặt, và độ lệch về category lớn vẫn còn bên trong theme.

**Impact on reported results:** Nếu đổi sang đều theo category, phân phối field đầu vào đổi và mọi alpha sinh ra theo theme không tái lập được với bản này. Theme rỗng không đổi gì (đã kiểm bit-exact với seed 42).

**Sentiment:** 8 — đổi phân phối lấy mẫu; reviewer sẽ hỏi vì sao news chỉ ~2%.

## 2026-10-25T18:17:01Z | methodology | score: 7

**Decision:** Áp `theme` cho cả GROUP theo yêu cầu user, dù pool GROUP dưới theme gần như rỗng.

**Alternatives considered:**
- Không áp theme cho GROUP (làm ở lượt trước): giữ đa dạng group field, nhưng không nhất quán với MATRIX/VECTOR; user yêu cầu áp đủ.

**Rationale:** Đo pool GROUP dưới theme ['analyst','model','news']: rỗng ở 35/41 scope, và là 1 field (`mdl10_group_name`) ở `USA_1_TOPSP500`. GROUP chỉ có 3 category (model, other, pv) nên theme không chứa `other`/`pv` loại gần hết (`other` 1200 và `pv` 469 field ở `USA_1_TOP3000`).

**Impact on reported results:** Mọi expression GROUP trong run dùng cùng một group field; kết quả group-wise không đại diện cho đa dạng group của catalog.

**Sentiment:** 7 — thu hẹp mạnh không gian group field, reviewer sẽ hỏi.

## 2026-10-26T15:54:54Z | methodology | score: 8

**Decision:** (đang chờ user chốt) Dùng `distribution="uniform"` cho bốc kiểu field MATRIX/VECTOR.

**Alternatives considered:**
- `"balanced"` (mặc định của `FloatSampler`) — bucket là quintile của range nên 4/5 bucket rơi vào [0, 0.5) → lệch 80/20 về MATRIX (đo thực tế: MATRIX 1614 / VECTOR 386 trong 2000 draw với seed 12345).
- `"uniform"` — 50/50 thực (đo: MATRIX 974 / VECTOR 1026 trong 2000 draw).

**Rationale:** Bucket của `balanced` thiết kế cho *parameter* có phân phối lệch tự nhiên (window, lag), không phải cho *lựa chọn nhị phân*. Ở đây MATRIX vs VECTOR là hai nhánh ngang hàng, nên phải đều tỉ lệ.

**Impact on reported results:** Quyết định này làm thay đổi tỉ lệ type trong mọi expression → thay đổi phân phối hành vi alpha được sample. Nếu để `balanced`, kết quả bị thiên 80% về MATRIX và reviewer sẽ hỏi tại sao VECTOR (pool chỉ 1794 field) xuất hiện hiếm.

**Sentiment:** 8 — ảnh hưởng trực tiếp phân phối expression, reviewer chắc chắn hỏi.

## 2026-10-26T17:39:16Z | methodology | score: 8

**Decision:** Chưa đưa expression builder vào `main.py` cho tới khi 5 blocker dưới đây được chốt. Đo trước, sửa sau.

**Alternatives considered:**
- Viết builder thẳng vào `main.py` rồi test sau: nhanh hơn nhưng 5 lỗi trên đều là lỗi *âm thầm* (expression vẫn render ra, chỉ hỏng khi tái tạo hoặc khi submit) → phát hiện muộn, tốn slot.
- Test bằng `try/except` bao quanh: che lỗi, không biết lỗi gì.

**Rationale:** Đo được 5 blocker (tất cả trong `/tmp/proto/`, script có thể chạy lại):
1. **Không tái lập được**: cùng seed → 5/5 expression khác nhau. Nguyên nhân: `MatrixUnary`/`Group` sample tham số với `seed=None` (`Functions/operators.py` dòng 743, 763, 789, 818, 846, 862, 881, 922–933, 958–964, 1032–1039, 1073–1080, 1268, 1335–1343, 1364–1372, 1409–1413, 1617–1619, 1632–1634, 1656–1662) và `MatrixBinary` chỉ có `ts_corr`/`ts_covariance`/`ts_regression` nhận `seed`.
2. **`get()` không replay được**: 42/68 builder raise TypeError khi truyền `config`; 4 builder còn lại lệch tên key (`kth_element`, `normalize`, `scale`, `ts_backfill`) và `group_backfill` crash với `ValueError: Unknown format code 'f'` vì `config["std"]` đã bị format thành string.
3. **`Group` bucket range không hợp lệ 9.06%**: `step >= (max - min)` ⇒ `range='a, b, s'` chỉ tạo 1 bucket. `min == max` không xảy ra (đã swap trước).
4. **Field id lặp lại trong 70% expression**: draw field không chống trùng giữa các lá, nên `multiply(f, f)` (alpha hằng) xảy ra.
5. **Slot đầu của platform**: đo lại, **KHÔNG có bug**. `MatrixBinary.get(name, x, y)` gọi builder *theo vị trí*, nên arg đầu của caller luôn vào slot đầu khi render: `get("ts_covariance", A, B)` → `ts_covariance(A, B)` → platform đọc `y=A, x=B`. Việc `ts_covariance` có signature `(y, x, d)` chỉ là quy ước *tên* của platform; builder đã map đúng. Hệ quả: **đảo operand là hợp lệ** cho mọi operator không giao hoán (`subtract`, `divide`, `power`, `signed_power`, `ts_corr`, `ts_covariance`, `ts_regression`, `vector_neut` — đo: cả 8 đều khác nhau khi đảo).

**Impact on reported results:** Không có con số nào được report trước khi sửa 4 điểm blocker đầu. Nếu bỏ qua điểm 1 thì toàn bộ run không replay được ⇒ mọi "alpha tốt" tìm được là do may rủi, không tái tạo. Điểm 4 làm giảm hiệu quả tìm kiếm vì một phần ngân sách chạy rơi vào expression hằng. Điểm 3 làm hỏng 9% expression GROUP. Điểm 5 (sai slot) đã bị bác sau khi đo lại — xem "Tín hiệu sai" bên dưới.

**Tín hiệu sai đã bác (sau khi đo lại):** test đầu tiên báo "`ts_covariance`/`ts_regression` render sai slot đầu platform". Sai. `get()` gọi builder theo vị trí nên arg đầu của caller luôn vào slot đầu khi render; `ts_covariance` có signature `(y, x, d)` chỉ là *tên* platform dùng, builder đã map đúng. Bài học: kiểm tra lại claim bằng một test độc lập trước khi ghi vào diary.

**Sentiment:** 8 — ảnh hưởng trực tiếp mọi con số sẽ report; reviewer sẽ hỏi ở từng điểm.

## 2026-10-26T17:50:41Z | methodology | score: 8

**Decision:** Bộ build trong `main.py` dùng 4 pool operator cố định, `BINARY_POOL` **loại `divide` và `power`**.

**Alternatives considered:**
- Giữ `divide`: không có `filter=true` nên mẫu số 0 raise ngay trên platform ⇒ mất slot. Giữ `power`: base âm + số mũ phân số ⇒ NaN.
- Dùng `multiply` thay cho `divide`: `multiply` có `filter=true` nên NaN thành 1, an toàn hơn, và đã có trong pool.

**Rationale:** Cả hai operator lỗi **chỉ lộ ra lúc simulate**, tức là lúc đã tốn slot. Loại khỏi pool là cách rẻ nhất; nếu sau này muốn giữ chúng thì phải bọc epsilon cho `divide` và ép exponent nguyên cho `power`.

**Số layer thật (đo, không phải suy ra):** tổng layer = 1 + số vòng ghép cặp, số vòng = số lần lặp `m → ceil(m/2)`.

| N | 1 | 2 | 3 | 4 | 5 | 6 | 7 | 8 | 9 | 12 |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| layer | 1 | 2 | 3 | 3 | 4 | 4 | 4 | 4 | 5 | 5 |
| binary op | 0 | 1 | 2 | 3 | 4 | 5 | 6 | 7 | 8 | 11 |

Công thức `ceil(n/2)+1` mà user đưa ra **đúng tới N=6 và sai từ N=7 trở đi** (N=8: công thức cho 5, thật là 4; N=12: cho 7, thật là 5).

**Impact on reported results:** Độ dài expression tăng nhanh theo N: N=1 → 60–70 ký tự, N=3 → 160–650, N=6 → tới 2603 trong một draw. Không có giới hạn độ dài nào của platform được xác nhận, nên chưa đặt trần; nếu N lớn hơn thì phải đặt.

**Sentiment:** 8 — quyết định loại operator ảnh hưởng không gian tìm kiếm; số layer là thứ user sẽ hỏi lại.

## 2026-10-26T18:05:00Z | methodology | score: 9

**Decision:** Số layer của expression là `1 + ceil(log2 N)`, và bộ build được chứng minh đúng cho **mọi N từ 1 đến 64**.

**Alternatives considered:**
- Dùng công thức `ceil(N/2)+1` của user: sai, vì nó đếm **số expression còn lại sau vòng ghép cặp đầu tiên**, không phải số vòng. Trùng khớp một cách tình cờ khi N ∈ [2,6].
- Dùng `1 + ceil(log2 N)`: đúng với mọi N, đo khớp tuyệt đối trên N=1..1000.

**Rationale:** Mỗi vòng ghép cặp giảm số lá từ `m` xuống `ceil(m/2)`, nên số vòng để còn 1 lá là số lần lặp `m → ceil(m/2)`, tức `ceil(log2 N)`. Ngoài layer lá, còn `ceil(log2 N)` layer ghép cặp ⇒ tổng `1 + ceil(log2 N)`.

| N | 1 | 2 | 3 | 4 | 5 | 6 | **7** | 8 | 9 | 16 | 32 | 64 |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| `ceil(N/2)+1` (sai) | 2 | 2 | 3 | 3 | 4 | 4 | **5** | 5 | 6 | 9 | 17 | 33 |
| `1+ceil(log2 N)` (đúng) | **1** | 2 | 3 | 3 | 4 | 4 | **4** | 4 | 5 | 5 | 6 | 7 |

**Impact on reported results:** Không con số nào đổi, nhưng công thức layer là thứ dùng để giải thích độ phức tạp của expression trong bài báo. Dùng công thức sai sẽ khiến reviewer đặt nghi vấn về toàn bộ mô tả cây. Độ dài expression đo được: n=1 → 67–343 ký tự, n=6 → 479–1418, n=16 → 2101–4433, n=64 → 16024–18457. Biên độ rất rộng ở n nhỏ vì số wrapper ngẫu nhiên (0..2) nhân với hệ số phình của operator (`if_else` 10.9×, `group_zscore` 12.0×).

**Sentiment:** 9 — sửa được một công thức sai đã đi vào lời giải thích, và chứng minh bằng sweep chứ không bằng suy luận.

## 2026-10-26T18:18:52Z | methodology | score: 8

**Decision:** Một field type chỉ được coi là dùng được khi pool của nó có **≥ 3 field** (VECTOR, GROUP); MATRIX giữ ngưỡng 1. Pool dưới ngưỡng bị coi là rỗng: nhánh operator của type đó **tắt hoàn toàn** trong expression.

**Alternatives considered:**
- Ngưỡng 3 cho cả 3 type: loại bỏ scope có MATRIX < 3 (không có scope nào như vậy trong cache hiện tại, nhưng `DEU_0_TOP500` với `THEME=['pv']` có MATRIX = 0).
- Ngưỡng 1 cho tất cả: `USA_1_*` với `THEME=['model']` có đúng 1 GROUP field (`model10`) ⇒ mọi expression trong scope dùng chung một group id, không có biến thiên ⇒ vô nghĩa về mặt thống kê.

**Rationale:** Ngưỡng 3 là quyết định của user. Một pool 1–2 field không tạo ra biến thiên giữa các expression, nên nhánh đó bị tắt thay vì dùng.

**Impact on reported results:** Với `THEME=['model']`, nhánh group tắt ở **41/41 scope** (GROUP pool = 1 ở `USA_1_*`, = 0 ở phần còn lại) ⇒ không expression nào chứa `group_*`. Với `THEME=[]`, nhánh group chỉ tắt ở `DEU_0_TOP500` và `GBR_0_TOP700` (GROUP pool = 0).

**Quy tắc phân bổ field (đã sửa):** MATRIX và VECTOR là **một pool**, không phải hai pool độc lập. Mỗi type nhận đúng phần draw yêu cầu, bị chặn bởi kích thước pool; phần thiếu chuyển cho type còn dư field. Bản cũ lấy `min(n, pool)` từ *mỗi* type nên tổng bị chặn ở `min(n,M) + min(n,V)` — ở `DEU_0_TOP500` (M=10, V=10) với n=24 chỉ ra 20 field.

**Sentiment:** 8 — ngưỡng ảnh hưởng trực tiếp expression nào được sinh ra, reviewer sẽ hỏi vì sao một số scope không có `group_*`.

## 2026-10-26T19:21:07Z | methodology | score: 9

**Decision:** Giới hạn của platform là **số operator call trong FASTEXPR** (`PLATFORM_OPERATOR_LIMIT = 64`), đếm trên text đã render, kể cả operator lồng bên trong argument của operator khác. Số field `n` bị giới hạn theo hệ quả: một cây n lá cần ≥ n-1 operator cho các join, nên **n ≤ 65**, và để expression còn "thú vị" thì `n ≤ 24` (còn 40 operator cho wrapper).

**Alternatives considered:**
- Chỉ giới hạn `n` bằng hằng số: không đủ, vì cost phụ thuộc operator được bốc, không chỉ số lá. Cùng n=6 đã cho 10..57 operator.
- Bỏ `sqrt`/`trade_when`/`if_else` khỏi pool: mất 4 operator có giá trị (sqrt xử lý âm, trade_when là điều kiện thời gian) để trán một rủi ro hiếm. Giữ pool, chỉ loại khi thật sự cần.

**Rationale:** Mô hình đếm được **xác thực bằng chính lỗi platform**: `sqrt(f)` = 5 operator, `sqrt(sqrt(f))` = 25, `sqrt^3(f)` = 105 — khớp đúng con số "105 found" trong lỗi. Cơ chế nhân: một operator render argument nhiều lần (`sqrt` ×4, `trade_when` ×3, `if_else` ×2, group ×2 qua `bucket(rank(x))`), nên cost của một subtree bị toán tử cha nhân lên, và cost của cây **không phải tổng các phần**.

**Impact on reported results:** `FIELD_COUNTS` đổi từ `(1,2,3,60)` → `(1,2,3,6,12,24)`. Trước đó mọi expression ở n=60 đều vượt 64 và bị platform từ chối, nên **không có con số nào báo cáo được** ở n=60. Các n ≤ 24 giữ nguyên hành vi trước đây.

**Quy tắc cấp ngân sách operator:** mỗi lá được cấp một allowance = (64 - (n-1)) / n operator. Wrapper vượt allowance thì bỏ. Nếu tổng vẫn vượt 64, allowance bị halve và cây dựng lại; các tầng pool sau lần lượt bỏ operator lặp argument, rồi tới fallback `add` thuần.

## 2026-10-27T16:59:10Z | methodology | score: 8 | tag: scale-fix

**Tags:** scale-fix

**Decision:** Before add/subtract/multiply/signed_power, each operand is wrapped in cross-sectional rank(), mapping it to [0, 1].

**Alternatives considered:**
ts_rank(x, 252): per-stock time-series rank, loses cross-sectional level information, 252-day NaN warm-up, hard-coded window.
zscore(x): keeps distribution shape, sensitive to outliers.
No normalization: the larger-scale operand dominates (e.g. ts_arg_max(cap,15) in 0..14 vs ts_delta(returns,4) near 0.0x).

**Rationale:** rank is scale-free, needs no window, costs 1 operator per operand. ts_corr is scale-free and if_else already rank-wraps (Docs/all-operators.md line 491), so both are excluded.

**Impact on reported results:** every add/subtract/multiply/signed_power join changes meaning and the operator budget shrinks by 2 per join; flipping this restores raw-scale joins. ts_covariance and ts_regression remain unnormalized.

**Sentiment:** 8 — reviewer would ask about scale comparability of joined signals.

## 2026-10-27T18:53:25Z | methodology | score: 8 | tag: composition-layer

**Tags:** composition-layer

**Decision:** Đo độ bão hòa của generator bằng 4 metric riêng biệt thay vì một metric "độ đa dạng" duy nhất, rồi chỉ mở lever ở composition-layer — không thay đổi quy tắc của primitive operator nào.

**Alternatives considered:**
Metric shape duy nhất (đếm skeleton khác nhau): bỏ vì tham số ngẫu nhiên (window, float) tạo ra entropy vô hạn, nên 8000/8000 skeleton khác nhau là hệ quả combinatorics chứ không phải diversity có ý nghĩa.
Thêm operator mới vào `Functions/operators.py` (bucket BOOLEAN): bỏ vì phần lớn trong số đó là so sánh infix (`input1 > input2`), không phải function call — `OPERATOR_CALL` không match nên ngân sách operator sẽ đếm thiếu; cần sửa bộ đếm trước khi dùng.
Dùng lại field (một field xuất hiện ở nhiều slot): bỏ vì đo cho thấy gain cấu trúc ~0 và sinh nhiều case tự triệt tiêu (`rank(f) - rank(f)` = 0).

**Rationale:** bốn metric tách ra bốn câu hỏi khác nhau. Structure (bỏ mọi số) cho câu hỏi "bao nhiêu hình dạng". Topology cho "cây có đủ kiểu không". Binding cho "field nào đi với field nào". Commutativity-normalization cho "có bao nhiêu chuỗi là bản sao giá trị của nhau". Kết quả: shape đã bão hòa (structure 7857/8000 ở N=3, tăng chậm; topology 2860/3000; collapse theo commutativity chỉ 0.1%), binding thấp (32 ở N=2, 180 ở N=4) — nghĩa là generator đã khám phá hết không gian mà kiến trúc cho phép, và nút thắt là **operator chưa dùng** chứ không phải hình dạng.

**Impact on reported results:** mọi expression sinh ra đều khác kiến trúc cũ. Lever post-join wrapper làm mean operator count tăng từ 14.2 lên 20.5 ở N=3 (tỉ lệ expression có transform-above-join 56.3% → 85.7%); lever variadic làm mean operator count giảm từ 14.2 xuống 13.1 ở N=3 và từ 28.5 xuống 26.4 ở N=6, vì một lệnh `max(a,b,c)` tốn 1 operator thay vì 2 join nhị phân. Nếu reviewer hỏi tại sao ngân sách operator thay đổi, đây là con số.

**Sentiment:** 8 — quyết định dựa trên phép đo, và cả hai lever đều mở vị trí biểu thức mà kiến trúc cũ không sinh ra được.

## 2026-10-28T17:05:57Z | methodology | score: 8 | tag: expression-profile

**Tags:** expression-profile

**Decision:** Profile của một expression gồm 3 phần: `data` (field + metadata catalog đầy đủ, gồm cả GROUP field), `levels` (dict theo tầng leaf/join/post → dict tên operator → list profile của các lần gọi), `counts` (operators per level, per category, số field, số operator khác nhau). Operator nội bộ của platform operator đưa vào profile với `config` rỗng, khai báo tường minh qua trường `implicit`. `rank` của scale-fix **không** vào profile.

**Alternatives considered:**
Profile là text đã render: bỏ vì không phân biệt được operator do generator chọn với operator do platform kéo theo, và không mang config.
Mọi operator trong text (kể cả rank của scale-fix) vào profile: bỏ vì `rank` của scale-fix xuất hiện ở *mọi* join scale-sensitive — nó là scaffolding bắt buộc để tạo lovel, không phải lựa chọn của generator. Đếm nó sẽ chiếm ~40% lượt operator và làm mờ phần thông tin còn lại. Quyết định này theo chỉ dẫn tag `scale-fix` trong `Diary/code-technique.md`.
Đếm operator theo số lần render để khớp text: bỏ vì operator lặp argument (`group_*` mode 3/4/5 nhúng lại `x` vào `bucket(rank(x))`; `trade_when` render 3 lần) khiến số lần render ≠ số lần gọi logic. Invariant đúng là coverage hai chiều theo **tên** operator.

**Rationale:** profile là đầu vào cho tầng heuristic/analysis sau, nên nó phải phản ánh **cái đã dựng** (logical call + config của nó), không phải cái đã render. Tách `implicit` khỏi `config` giữ nguyên nguyên tắc "config = tham số do draw sinh ra"; `implicit` là operator bị kéo theo, không có tham số do ta chọn.

**Impact on reported results:** verify bằng coverage hai chiều theo tên operator trên 200 expression ngẫu nhiên (N=1,2,3,6,12): 0 vi phạm. Trước khi thêm `implicit`, sai lệch là 87/100 expression — chủ yếu do `group_*` mode 3/4/5 (3/5 xác suất). Nếu reviewer hỏi "tại sao số operator trong profile ≠ số lần xuất hiện trong text", câu trả lời là operator lặp argument.

**Sentiment:** 8 — quyết định về ranh giới "operator nào thuộc về profile" ảnh hưởng mọi thống kê tầng sau, và chỉ đúng khi invariant verify được.

## 2026-10-28T17:47:35Z | methodology | score: 7

**Decision:** Replay bit-exact bằng config đã ghi, không bằng seed. Ghi thêm `bucket_range` (chỉ mode 3-5) vào config của Group và `tree` vào profile.

**Alternatives considered:**
- Seed replay: Docs §8.5 nói chỉ cố định được stream 1; các stream khác vẫn random.
- Parse lại text expression: dễ sai với implicit operator và tham số lặp.
- Ghi bucket_range ở mọi mode: thừa, mode 1-2 không render nó.

**Rationale:** config là nguồn sự thật duy nhất của tham số đã draw; cây cho cấu trúc.

**Impact on reported results:** Expression sinh ra không đổi: snapshot 260 expression Group trước/sau sửa giống hệt. Chỉ profile đổi hình dạng (thêm `tree`, thêm `bucket_range`, level "rank").

**Sentiment:** 7 — reviewer sẽ hỏi vì sao không dùng seed.

## 2026-10-28T18:05:01Z | methodology | score: 6 | tag: docs-expression-builder

**Tags:** docs-expression-builder

**Decision:** Tài liệu hóa bộ sinh như một thiết bị đã đo (số mẫu, kết quả, độ lệch) và tách rõ ba loại phát biểu: đã đo, chưa kiểm (giả thuyết), lựa chọn thiết kế chưa tối ưu theo kết quả platform.

**Alternatives considered:**
- Ghi một con số duy nhất cho n=22: bỏ vì hai lần đo (2/60 và 0/150) mâu thuẫn nhau, một con số che mất sự bất định.
- Ghi nguyên nhân n=22 như sự thật: bỏ vì chưa có phép đo xác nhận.
- Sửa lỗi n=22 trong lượt này: bỏ vì yêu cầu chỉ là cập nhật tài liệu; sửa sẽ đổi hành vi sinh expression.

**Rationale:** nhất quán với quy tắc không báo cáo kết luận chưa được kiểm chứng. Hằng số `VARIADIC_MAX_OPERANDS`, `VARIADIC_PROBABILITY`, `POST_WRAPPERS`, `max_wrappers` được ghi là lựa chọn thiết kế vì chưa có local oracle để so sánh chúng.

**Impact on reported results:** không đổi code hay expression sinh ra. Nếu reviewer hỏi về tỉ lệ expression vượt giới hạn operator, số liệu hiện có là hiếm (khoảng 1% ở n=22, 0 ở n <= 20) nhưng chưa đủ mẫu để khẳng định.

**Sentiment:** 6 — ranh giới giữa số đo và giả thuyết là thứ reviewer sẽ hỏi.

## 2026-10-28T18:30:18Z | methodology | score: 8 | tag: scope-as-filter

**Tags:** scope-as-filter

**Decision:** Chưa đổi code. Ghi lại số đo độ phong phú của không gian field theo từng trục scope, làm cơ sở cho quyết định coi region/delay/universe như bộ lọc.

**Alternatives considered:**
- Chọn scope đều trên 41 scope: thiên về USA (12) và EUR (10) vốn trùng catalog bên trong vùng; 19 catalog khác nhau.
- Chọn đều theo (region, delay) hoặc theo 19 catalog khác nhau: cân bằng hơn về field, nhưng bỏ qua khác biệt universe về tập cổ phiếu mà phép đo này không thấy.
- Chỉ dùng USA_1: pool lớn nhất (36854 MATRIX) nhưng một vùng duy nhất.

**Rationale:** số đo (cache 2026-10-22, MIN_COVERAGE=0.7, MATRIX+VECTOR theo fieldid):
- Universe: cùng region+delay, Jaccard nhỏ nhất 0.9247 (ASI), 1.0 ở EUR/GLB/HKG/TWN, 0.9785 ở USA d1.
- Delay: cùng region+universe, Jaccard 0.05 đến 0.17; d0-only 2203 id ở USA.
- Region (delay 1): USA vs vùng khác 0.03 đến 0.16; cụm ASI/HKG/KOR/TWN 0.55 đến 0.74; DEU/GBR 0.75.
- Hợp 41 scope 78059 id, scope lớn nhất 46022; 0 id có mặt ở cả 41 scope, 8603 id chỉ có ở 1 scope.
- Kích thước MATRIX min 137, median 7566, max 36854 (gấp 269 lần).
- Số category hiệu dụng (exp entropy, MATRIX, rút đều): min 1.51 (DEU_0, GBR_0: analyst 90%), median 4.41, max 6.19.

**Impact on reported results:** scope được chọn quyết định pool và phân phối category; main.py hiện cố định scopes[-3] = USA_1_TOP3000, scope giàu nhất. Kết quả trên scope này không suy ra được cho vùng khác.

**Latent behaviour found, not fixed:** theme được áp lên cả GROUP field (_pool_size và _sample). GROUP chỉ có category pv (39 scope), other (25), model (6). THEME=['fundamental','model'] đưa GROUP về 0 hoặc 1 field ở cả 41 scope, dưới MIN_POOL_SIZE nên group_* bị tắt ở 39 scope (2 scope còn lại vốn không đủ GROUP). Cần quyết định của user: theme có nên chỉ áp cho MATRIX/VECTOR.

**Sentiment:** 8 — universe gần như không thêm field trong khi bị đếm như 41 lựa chọn, và theme hiện tắt cả một họ operator mà không báo.

## 2026-10-28T18:47:29Z | methodology | score: 8 | tag: scope-as-filter

**Tags:** scope-as-filter

**Decision:** Scope được rút bằng 2 bước: region đều trong REGION (rỗng = cả 11 region), rồi scope đều trong region đó. Theme áp cho cả MATRIX, VECTOR, GROUP.

**Alternatives considered:**
- Rút đều trên 41 scope: USA 12 và EUR 10 chiếm 22/41 dù chỉ có 2 catalog khác nhau mỗi vùng theo delay.
- Rút đều trên 19 catalog khác nhau: cân bằng về field, bị loại vì user chỉ muốn lọc theo region.
- Theme chỉ áp cho MATRIX/VECTOR: bị loại theo quyết định của user.

**Rationale:** user muốn quản lý region như THEME, danh sách do user viết. Rút region trước rồi mới rút scope giữ cho mỗi region cùng xác suất; đo 11000 lần: REGION rỗng cho mỗi region 960 đến 1059 lần, ['USA','EUR'] cho 5425/5575. Trong region, delay và universe được rút đều, nên với USA delay 0 và delay 1 có xác suất ngang nhau (6 scope mỗi delay) dù pool delay 0 nhỏ hơn nhiều (MATRIX 6498 so với 36854).

**Impact on reported results:** mỗi lần chạy main thấy một scope ngẫu nhiên thay vì USA_1_TOP3000, nên số liệu giữa các lần chạy không so sánh trực tiếp. Với THEME = ['fundamental', 'model'], GROUP còn 0 hoặc 1 field ở hầu hết scope, group_* tắt, và pool delay 0 nhỏ hơn rõ (USA_0 MATRIX 1634 so với USA_1 17096).

**Sentiment:** 8 — quyết định ai được thấy field nào, reviewer sẽ hỏi vì sao delay 0 và 1 có trọng số bằng nhau.

## 2026-10-29T15:32:31Z | methodology | score: 6 | tag: ace-lib-docs

**Tags:** ace-lib-docs

**Decision:** Ghi lại 15 bất đối xứng của reference code thay vì sửa chúng, và đánh dấu rõ đây là code tham khảo không phải code dự án.

**Alternatives considered:**
- Copy `ace_lib.py` vào dự án: bị cấm theo rule 16 và làm mất ranh giới giữa code tham khảo và code của dự án.
- Chỉ ghi endpoint và không ghi quy ước: thiếu phần khó nhất, tức là cách biết một simulation đã xong.
- Sửa các bất đối xứng ngay trong reference: bị cấm theo rule 16.

**Rationale:** hai điểm lệch có ảnh hưởng đến kết luận khoa học nếu ai đó dùng lại logic kiểm tra: `check_prod_corr_test` dùng `<= threshold` còn `check_self_corr_test` dùng `<`; và khi thiếu dữ liệu thì prod corr trả "NONE" còn self corr trả "PASS". Code dự án mới phải viết lại với một quy ước thống nhất và ghi rõ quy ước đó.

**Impact on reported results:** không ảnh hưởng số liệu hiện có; dự án chưa dùng các hàm kiểm tra correlation này.

**Sentiment:** 6 — ranh giới giữa "ghi nhận" và "vá" là điều reviewer sẽ kiểm.

## 2026-10-29T15:47:40Z | methodology | score: 6

**Decision:** `if_else` mode 1 trả chỉ báo 0/1 cộng dồn qua `ts_sum(·, dz)`, `dz` rút từ [10, 52] theo `distribution`; `mode` rút đều từ {0, 1}.

**Alternatives considered:**
- `if_else(cond, 1, 0)` trần: user nhận xét đơn điệu.
- `dz` cố định: user yêu cầu random trong 10..52.

**Rationale:** chỉ báo nhị phân thô gần như không mang thông tin xếp hạng; cộng dồn theo cửa sổ (khoảng 2 tuần đến 1 năm giao dịch ở 52 ngày là 1/5 năm) cho tín hiệu liên tục hơn. Khoảng 10..52 do user chọn, chưa có trích dẫn.

**Impact on reported results:** phân phối alpha `if_else` đổi: một nửa số lần gọi cho ra dạng `ts_sum(...)`. Alpha `if_else` sinh trước đây không còn tái lập từ profile cũ (thiếu `mode`).

**Sentiment:** 6 — thay đổi phân phối expression, reviewer sẽ hỏi vì sao 10..52.

## 2026-10-29T15:56:38Z | methodology | score: 7

**Decision:** Chỉ bốc field có `dataset_valueScore < 4`, áp dụng lúc bốc, không lúc fetch.

**Alternatives considered:**
- Lọc lúc fetch như `MIN_COVERAGE`: phải fetch lại toàn bộ cache, và không đổi ngưỡng được bằng một dòng.
- `<= 4`: user viết `< 4`.

**Rationale:** theo yêu cầu user; ngưỡng đặt ở `main.py` như `MIN_COVERAGE`. `valueScore` là thuộc tính của dataset, nên cắt loại cả dataset. Chưa có trích dẫn vì sao 4; `how_to_use.py` dùng `0 < valueScore < 10` làm ví dụ.

**Impact on reported results:** tập field nguồn nhỏ đi (MATRIX còn 71.5 %, VECTOR 61.2 %, GROUP 68.8 % trên 123 archive), nên phân phối alpha đổi. Alpha sinh trước đây có thể dùng field score >= 4.

**Sentiment:** 7 — đổi tập field gốc, reviewer sẽ hỏi vì sao 4.

## 2026-10-29T16:01:03Z | methodology | score: 7

**Decision:** khi n field không thể vừa 64 operator, bỏ field cuối thay vì raise hoặc trả expression vượt giới hạn.

**Alternatives considered:**
- Raise `ValueError` như cũ: user yêu cầu không báo lỗi.
- Trả cây nhỏ nhất vượt giới hạn: platform từ chối.
- Bỏ field ngẫu nhiên: field đã được bốc ngẫu nhiên và độc lập nên bỏ cuối không thiên lệch phân phối field.

**Rationale:** yêu cầu của user: hàm phải luôn sinh expression hợp lệ.

**Impact on reported results:** với n >= 22, expression chứa ít field hơn n; n_data_fields trong profile là số thật. Đo: n = 23..100 cho 21 đến 22 field.

**Sentiment:** 7 — số field trong alpha khác số field yêu cầu.

## 2026-10-29T16:18:48Z | methodology | score: 8

**Decision:** profile là genotype tất định của expression: `tree` đầy đủ (kể cả rank scale-fix, gắn origin), các view đếm là hàm của tree, `rendered` nhân multiplicity đo từ text.

**Alternatives considered:**
- Profile là cây build nguyên trạng: thiếu gene (rank), thừa gene (data.group).
- Profile là bảng đếm theo text: text là phenotype, mất thông tin operator nào do generator chọn.

**Rationale:** lọc nên làm lúc phân tích, không lúc ghi; hệ số lặp của operator đo từ text thay vì hard-code.

**Impact on reported results:** counts của profile đổi nghĩa (unique so với rendered); heuristic stage phải chọn view.

**Sentiment:** 8 — đổi schema profile, ảnh hưởng mọi phân tích phía sau.

## 2026-10-29T16:28:37Z | methodology | score: 8

**Decision:** `build` raise khi operator_limit < 3(n-1) + V, không bỏ field.

**Alternatives considered:**
- Bỏ lá cuối cho tới khi vừa (lượt trước): expression chứa ít field hơn draw, lệch profile/draw.
- Sàn = POST_WRAPPERS * n (đề xuất ban đầu của user): đo cho thấy thấp hơn sàn thật.

**Rationale:** sàn đo trực tiếp trên level nghèo nhất; mọi field draw đều có trong expression, nên draw và expression nhất quán.

**Impact on reported results:** n lớn cần OPERATOR_LIMIT lớn hơn; không còn trường hợp n_data_fields < n.

**Sentiment:** 8 — bảo toàn tương ứng draw và expression.

## 2026-10-29T16:39:40Z | methodology | score: 7

**Decision:** floor của build = JOIN_COST * (n - 1) + n (trường hợp xấu nhất toàn VECTOR), không dùng số VECTOR thật của draw.

**Alternatives considered:**
- 3(n-1) + V (chính xác): V ngẫu nhiên nên raise không nhất quán với cùng một limit.
- POST_WRAPPERS * n: thấp hơn sàn thật.

**Rationale:** ngưỡng chỉ phụ thuộc n nên user đặt OPERATOR_LIMIT một lần là chạy được mọi draw.

**Impact on reported results:** ngưỡng cao hơn mức cần khi draw ít VECTOR; không đổi expression được sinh.

**Sentiment:** 7 — đánh đổi nhất quán lấy ngưỡng bảo thủ.

## 2026-10-29T16:47:38Z | methodology | score: 7

**Decision:** floor không chứa POST_WRAPPERS; post wrapper là best-effort trên phần ngân sách còn dư.

**Alternatives considered:**
- floor = POST_WRAPPERS * n: thấp hơn sàn thật (đo ở lượt trước).
- floor worst case 4^P * floor + 5(4^P - 1)/3 (sqrt lặp 4x, +5): 297 với n = 5, P = 2, vượt trần platform 64 nên không dùng được.

**Rationale:** _post_wrap bỏ wrapper làm vượt limit, nên build không bao giờ vượt limit dù P lớn (0/300 vi phạm ở mọi limit đã đo).

**Impact on reported results:** số post wrapper thực tế <= POST_WRAPPERS và giảm khi limit sát floor (ở limit = floor, 57% build không có wrapper nào so với 33% kỳ vọng).

**Sentiment:** 7 — ảnh hưởng phân phối cấu trúc expression khi limit chặt.

## 2026-10-29T16:54:15Z | methodology | score: 6

**Decision:** giữ floor = join_cost * (n - 1) + n, không thay join_cost bằng POST_WRAPPERS + 1.

**Alternatives considered:**
- (POST_WRAPPERS + 1) * (n - 1) + n: khớp chỉ khi POST_WRAPPERS = 2; thấp hơn sàn thật khi P < 2, cao hơn cần thiết khi P > 2.

**Rationale:** join_cost là chi phí đo của một join (1 binary + 2 rank), không phụ thuộc số post wrapper; post wrapper chỉ áp một lần trên node gốc, không theo từng join.

**Impact on reported results:** none (không đổi code).

**Sentiment:** 6 — tránh ngưỡng sai khi đổi POST_WRAPPERS.

## 2026-10-29T17:10:18Z | methodology | score: 7

**Decision:** add, multiply, subtract được dùng như VARIADIC (n >= 3 operand) bên cạnh max, min; divide không.

**Alternatives considered:**
- Giữ chỉ max, min: không dùng khả năng n-ary của add, multiply, subtract mà mô tả platform ghi.
- Thêm divide: loại, chỉ nhận hai operand, và lý do loại khỏi BINARY_POOL (mẫu số 0) chưa đổi.

**Rationale:** mô tả platform: add "two or more inputs", multiply "two or more inputs", subtract "two or more inputs"; subtract tính trái sang phải. Một lời gọi n-ary tốn n + 1 operator sau khi rank-wrap, so với 3(n - 1) cho chuỗi join nhị phân.

**Impact on reported results:** tăng tỷ lệ join nhiều operand; subtract n-ary là phép trừ liên tiếp nên thứ tự operand ảnh hưởng giá trị. Chưa xác nhận trên simulation thật.

**Sentiment:** 7 — đổi phân phối join, chưa xác nhận bằng simulation.

## 2026-10-29T17:17:43Z | methodology | score: 7

**Decision:** divide trở lại BINARY_POOL, render divide(x, y + 0.0001).

**Alternatives considered:**
- divide(x, add(y, 0.0001)): đúng mô tả platform nhưng tốn thêm 1 operator mỗi lần dùng.
- Để divide ngoài pool (quyết định 2026-10-26): tránh lỗi mẫu số 0 nhưng bỏ một phép toán hợp lệ.

**Rationale:** epsilon 0.0001 lấy từ mô tả platform của divide trong cache/operators.csv; viết infix nên số operator không đổi. Epsilon chỉ chặn mẫu số đúng bằng 0; y gần -0.0001 vẫn cho giá trị rất lớn.

**Impact on reported results:** thêm một operator vào không gian join; divide không scale-fix nên một operand cỡ lớn có thể lấn át tỷ số. Chưa xác nhận trên simulation.

**Sentiment:** 7 — đổi không gian tìm kiếm, chưa kiểm.

## 2026-10-29T17:20:36Z | methodology | score: 8

**Decision:** divide render x / (x + y + 0.0001) thay vì x / (y + 0.0001).

**Alternatives considered:**
- divide(x, y + 0.0001): giữ nghĩa x / y, chỉ chống y = 0 đúng điểm.
- divide(x, add(y, 0.0001)): cùng ý, tốn thêm 1 operator.

**Rationale:** theo yêu cầu của user. Giá trị là tỷ trọng x trong x + y: giữ cùng dấu và cùng bậc với x, bị chặn trong [0, 1] khi x, y cùng dấu dương.

**Impact on reported results:** divide không còn là phép chia x cho y; một reviewer hỏi tên operator sẽ thấy không khớp phép tính. Mẫu số vẫn về 0 khi x + y = -0.0001.

**Sentiment:** 8 — tên operator không còn khớp phép tính, cần nói rõ trong paper.

## 2026-10-29T17:34:13Z | methodology | score: 8

**Decision:** Trạng thái cuối của pool join: VARIADIC_POOL = add, max, min, multiply (4 operator); subtract không phải VARIADIC; divide ở BINARY_POOL và render divide(x, y + x + 0.0001). Entry 2026-10-29T17:10:18Z (subtract là VARIADIC) và entry 2026-10-29T17:17:43Z (divide(x, y + 0.0001)) đã bị thay thế bởi entry này.

**Alternatives considered:**
- subtract n-ary (x - y - z): bị loại theo chỉ dẫn của user; subtract giữ làm join nhị phân.
- divide(x, y + 0.0001): giữ nghĩa x / y; user chọn dạng có x trong mẫu số.
- divide(x, add(y, 0.0001)): đúng mô tả platform nhưng tốn thêm 1 operator mỗi lần dùng.

**Rationale:** theo chỉ dẫn của user. Giá trị của divide là x / (x + y + 0.0001), tức tỷ trọng của x trong x + y, không phải x / y. Epsilon 0.0001 lấy từ mô tả divide trong cache/operators.csv. x được render hai lần nên divide vào REPEATING, nghĩa là level "calm" loại divide khỏi pool binary.

**Impact on reported results:** tên operator divide không còn khớp phép tính, cần nói rõ trong paper. Mẫu số vẫn về 0 khi x + y = -0.0001. divide chưa nằm trong SCALE_SENSITIVE nên không rank-wrap. Chưa xác nhận trên simulation rằng platform chấp nhận cú pháp infix này, hay đếm "+" infix là một operator.

**Sentiment:** 8 — đổi ngữ nghĩa một operator và phân phối join, chưa kiểm trên platform.
