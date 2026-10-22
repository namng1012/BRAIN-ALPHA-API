## 2026-10-21T15:53:16Z | chat-summary | score: 6

**Request:** Tạo `.env` chứa `[email, password]`; viết script login trong `main.py` theo reference `ACE_API__Gold_/ace_lib.py`; thêm hàm check đã login chưa để tránh bị hệ thống khóa khi phát triển.

**Outcome:** Tạo `.env` + `.gitignore` (`.env`, `.brain_session.json`), thêm `python-dotenv`. Viết `main.py` với `get_credentials` / `start_session` (Basic auth + persona biometric) / `check_login` / `save_session` / `load_session` / `get_session`. Xác minh runtime: credentials đúng, persona flow thành công, JWT in ra được, và lần chạy thứ hai tái dùng cache (valid 14390s) mà không gọi lại `POST /authentication`.

**Files touched:**
- `.env` (new)
- `.gitignore`
- `pyproject.toml`
- `main.py`
- `Diary/README.md` (new)
- `Diary/code-technique.md` (new)
- `Diary/methodology.md` (new)
- `Diary/conversation-log.md` (new)

**Open questions:** Chưa quyết định có lưu token vào file cache dài hạn (`~/.cache`) thay vì `.brain_session.json` cạnh project, hay giữ nguyên; chưa port `check_session_and_relogin` vào `get_session` để tự động re-login giữa lúc chạy long-running.

**Sentiment:** 6 — useful breadcrumb for replaying the session.

## 2026-10-21T16:47:38Z | chat-summary | score: 6

**Request:** "sao mà lâu vậy thử cách khác" — sau khi liệt kê field/dataset của scope USA/TOP3000, làm nhanh hơn; sau đó "cập nhật Diary sao bạn không theo rule ? hãy đổi rule rằng luôn cập nhật Diary".

**Outcome:** Liệt kê 44 scope hợp lệ bằng **một** request `OPTIONS /simulations` (thay vì gọi `summary()` 44 lần, vốn tự gọi `settings()` mỗi vòng) → 12 region, 2 delay, 30 tên universe nhưng chỉ 21 tên distinct. Sửa `.cursor/rules/14-diary-logging.mdc` để bỏ cổng chặn điểm ≥6: mọi lượt assistant đều phải ghi ít nhất một entry, điểm 1–10 thành nhãn để lọc sau; trigger 1 thành bắt buộc; conflict resolution bỏ "explicit user opt-in"; bỏ dòng "never logged: score < 6". Đồng bộ `Diary/README.md` và bù lại các entry còn nợ.

**Files touched:**
- `.cursor/rules/14-diary-logging.mdc`
- `Diary/README.md`
- `Diary/code-technique.md`
- `Diary/conversation-log.md`
- `Diary/methodology.md`

**Open questions:** `BrainData._get` chưa có retry cho response non-JSON → `summary()` crash trên full 44-scope sweep; chưa quyết định có sửa `_get` (thêm retry) hay chạy sweep theo batch nhỏ; số liệu tổng field/dataset trên toàn bộ 44 scope vẫn **chưa verify được** (job bị kill sau 6 phút) nên chưa ghi vào diary.

**Sentiment:** 6 — a real rule-compliance fix plus the scope-space enumeration, with one open reliability gap.

## 2026-10-21T16:51:19Z | chat-summary | score: 6

**Request:** "hãy thêm 1 markdown tên data-description.md vào Docs trong đó thêm [bảng Region/Delay/Universe] + @terminals/1.txt:97-154" — tạo tài liệu mô tả dữ liệu trong `Docs/`.

**Outcome:** Tạo `Docs/data-description.md` gồm 5 phần: (1) scope space 12 region / 44 scope với cây nesting của `OPTIONS /simulations`; (2) snapshot catalog scope `EQUITY/USA/1/TOP3000` — 286 dataset, 75 926 field, breakdown theo `type` và `categoryname`, cột trả về của 2 endpoint; (3) nhận xét cấu trúc dữ liệu (Model chiếm ~25 % field; VECTOR/MATRIX ≈ 22 %; `Fundamental` là nhóm "sạch" nhất cho baseline); (4) ràng buộc kỹ thuật (rate limit 1 req/s, `_get` chưa retry non-JSON, cảnh báo cộng dồn scope-field); (5) cách tái lập. Bảng scope đã verify lại từ `OPTIONS` — khớp 12 region, 44 scope, 30/21 universe names.

**Files touched:**
- `Docs/data-description.md` (new)

**Open questions:** Chưa quyết định có dùng `VECTOR` field hay bỏ (chiếm ~22 % catalog, cần định nghĩa cách aggregate); chưa quyết định dedup theo `id` để có kích thước catalog thật thay vì tổng scope-field; `BrainData._get` vẫn chưa retry.

**Sentiment:** 6 — a reference doc that the paper's data-availability baseline can cite, and it records the universe-name collision trap.

## 2026-10-21T17:21:58Z | chat-summary | score: 7

**Request:** "Hãy thêm idea này vào Docs NHƯNG NÓI RÕ ĐÂY LÀ ĐỀ XUẤT VẪN CHƯA CHẮC CHẮN VÀ ĐỂ ĐỂ RIÊNG RA 1 md" — sau khi thảo luận pipeline lấy mẫu random data field trên giấy (chỉ về data, không đụng FASTEXPR).

**Outcome:** Tạo `Docs/random-field-pipeline-proposal.md` — 12 phần, mở đầu bằng banner "TRẠNG THÁI: ĐỀ XUẤT — CHƯA ĐƯỢC CHỐT", phân biệt rõ phần **số đo đã verify** (§1–§4, §8, §9) với phần **đề xuất còn mở** (§5–§7, §10). §10 liệt kê 8 quyết định còn mở dạng bảng trạng thái "chưa chốt"; §11 liệt kê 5 việc cần kiểm tra thêm. Đồng thời đính chính một nhận định sai trong `Docs/data-description.md` (mục "Không cộng dồn số field giữa các scope") bằng phụ lục trỏ sang §2 của tài liệu mới.

**Files touched:**
- `Docs/random-field-pipeline-proposal.md` (new)
- `Docs/data-description.md` (thêm phụ lục đính chính §4)
- `Diary/code-technique.md` (2 code-technique + 2 methodology)
- `Diary/conversation-log.md` (entry này)

**Open questions:** 8 mục ở §10 chưa chốt (frame, phương án lấy mẫu A/B/C/D, type eligibility, ngưỡng coverage, xử lý field chưa ai dùng, có chạy A+D, format cache, số draw); 5 mục kiểm tra thêm ở §11, trong đó quan trọng nhất là quan hệ nội dung giữa `delay 0` và `delay 1` (đã biết có 3 089 field chỉ tồn tại ở delay 0).

**Sentiment:** 7 — the doc preserves the measurements (reusable regardless of the design choices) while making every open decision explicit, so a future reader can pick it up without re-deriving the API quirks.

## 2026-10-22T03:41:00Z | chat-summary | score: 3

**Request:** "bây giờ bạn đọc toàn bộ script trong project này để hiểu context, sau đó đọc rule".

**Outcome:** Đọc toàn bộ code + tài liệu của project: `main.py`, `Functions/login.py`, `Functions/data.py`, `pyproject.toml`, `.env.example`, `ACE_API__Gold_/{ace_lib,helpful_functions,how_to_use}.py`, `Docs/{Login,data-description,random-field-pipeline-proposal}.md`, `Diary/*`, `.cursor/rules/RULES-INDEX.md` + rule 11 (auto-attach khi mở `main.py`). Không sửa file nào.

**Files touched:**
- `Diary/conversation-log.md` (entry này)

**Open questions:** Không có yêu cầu mới; 8 quyết định mở ở `Docs/random-field-pipeline-proposal.md` §10 vẫn chưa chốt.

**Sentiment:** 3 — routine orientation turn, không có code pattern hay research decision mới.

## 2026-10-22T03:44:26Z | chat-summary | score: 5

**Request:** "bây giờ bạn đọc toàn bộ script trong project này để hiểu context, sau đó đọc @.cursor/ sau đó tự tạo rult theo codex".

**Outcome:** Đọc toàn bộ code, tài liệu, Diary và 16 Cursor rules; đối chiếu cơ chế project instructions của Codex; tạo `AGENTS.md` ở repository root dưới dạng rule Codex cô đọng. File mới giữ các ràng buộc quan trọng về ngôn ngữ, `uv`, minimal scope, BRAIN API, reproducibility, `main.py`, reference code read-only, verification và diary logging.

**Files touched:**
- `AGENTS.md` (new)
- `Diary/conversation-log.md` (append entry này; giữ nguyên entry chưa commit đã có)

**Open questions:** Không có. Các quyết định nghiên cứu chưa chốt trong `Docs/random-field-pipeline-proposal.md` vẫn được giữ nguyên trạng thái proposal.

**Sentiment:** 5 — chuyển toàn bộ convention từ Cursor sang durable repository guidance của Codex và bổ sung context đặc thù của project.

## 2026-10-22T03:47:50Z | chat-summary | score: 2

**Request:** "bạn không có folder như folder của cursor ah".

**Outcome:** Giải thích Codex không dùng `.cursor/rules/*.mdc`: durable repository instructions nằm trong `AGENTS.md`, còn `.codex/config.toml` dành cho cấu hình Codex chứ không phải tập prose rules.

**Files touched:**
- `Diary/conversation-log.md` (entry này)

**Open questions:** User chưa yêu cầu tạo thêm `.codex/config.toml`.

**Sentiment:** 2 — clarification về cấu trúc configuration của Codex, không thay đổi source code.

## 2026-10-22T03:56:00Z | chat-summary | score: 4

**Request:** "tôi muốn quan sát hết tất cả những dữ liệu này `datasets.columns`" — in ra toàn bộ 286 dataset với đủ 20 cột.

**Outcome:** Thêm vào `main.py`: `pd.set_option("display.max_colwidth", None)` + `display.width=250` (cần `import pandas as pd`), in `datasets.to_string()` không cắt, và ghi thêm `datasets.csv` (321 KB) để mở bằng Excel/editor. Xác minh bằng `uv run main.py`: 318 dòng output, 286 dataset, file CSV tạo thành công.

**Files touched:**
- `main.py` (thêm import pandas, block in full dataset catalog + ghi CSV)
- `datasets.csv` (new, output artifact)
- `Diary/conversation-log.md` (entry này)

**Open questions:** Cột `description` và `researchPapers` rất dài (vài trăm ký tự/record) nên bảng stdout khó đọc — nếu muốn duyệt nhanh hơn nên tách bảng "metadata ngắn" (id, name, category, fieldCount, coverage, valueScore) khỏi bảng "description đầy đủ". `themes` và `researchPapers` vẫn là **dict lồng** chưa được `_flatten` — `datafields` không có cột này vì không xuất hiện ở field level.

**Sentiment:** 4 — routine exploration, hữu ích nhưng chưa có quyết định nghiên cứu nào mới.

## 2026-10-22T04:01:00Z | chat-summary | score: 5

**Request:** "chi có 286 trường dữ liệu?" — làm rõ con số 286 là gì.

**Outcome:** Xác minh bằng 3 kiểm tra chéo: `GET /data-sets` → `count=286` = `len(results)` = `next=None` (không pagination ẩn); `GET /data-fields` → 75 926 record; `sum(datasets.fieldCount)` = 75 926 khớp. Kết luận: **286 là số dataset, 75 926 là số data field** (TB 265 field/dataset). Đồng thời tái hiện bug `BrainData._get` không retry body non-JSON (`JSONDecodeError` tại `Functions/data.py:48`) khi gọi `/data-fields` — đúng bug đã ghi ở `Docs/data-description.md` §4, chưa sửa. Bug này không ảnh hưởng `main.py` hiện tại (mỗi endpoint chỉ gọi 1 lần) nhưng chặn mọi fan-out nhiều scope.

**Files touched:**
- `Diary/conversation-log.md` (entry này)

**Open questions:** Chưa sửa `_get` — cần user xác nhận trước khi thêm retry, vì nó đụng vào đường chính của mọi catalog call.

**Sentiment:** 5 — làm rõ một hiểu lầm số liệu cơ bản, kèm xác nhận bug đã biết vẫn còn.

## 2026-10-22T04:25:00Z | chat-summary | score: 7

**Request:** Chọn phương án "sửa `BrainData._get` thêm retry rồi sweep 44 scope để biết tổng dataset/field toàn platform".

**Outcome:** (1) Sửa `Functions/data.py` — thêm `GET_MAX_ATTEMPTS = 5`, `GET_RETRY_INTERVAL_SECONDS = 2`, đổi vòng `while True` thành `for attempt in range(...)` bắt `requests.exceptions.JSONDecodeError` rồi sleep và thử lại; verify 2 endpoint parse sạch (`data-sets count=286 len=286`, `data-fields count=75926 len=75926`, `next=None`). (2) Tạo `sweep_scopes.py` — sweep 17 cặp `(region, delay)` cho `/data-fields` và 44 scope cho `/data-sets`, ghi `sweep_fields_by_pair.csv` + `sweep_datasets_by_scope.csv`. Lần chạy đầu **sai** vì hardcode `universe="TOP3000"` cho mọi cặp → 13/17 cặp trả 0 field; sửa bằng cách lấy universe hợp lệ từ `combinations()` (`universe_by_pair`). Chạy lại mất ~8 phút, ra kết quả platform-wide: **441 dataset id, 125 753 field id duy nhất**.

**Files touched:**
- `Functions/data.py` (`_get` retry + 2 hằng số)
- `sweep_scopes.py` (new)
- `sweep_fields_by_pair.csv`, `sweep_datasets_by_scope.csv` (new, artifacts)
- `Diary/conversation-log.md` (entry này)

**Open questions:** `ALL/1/LARGE` là scope hợp lệ (OPTIONS xác nhận) nhưng trả 139 dataset và **0 field** — chưa rõ là bug server hay dataset không có field ở scope đó. Scope `DEU/0`, `DEU/1`, `GBR/0`, `GBR/1` trả `n_datafields > n_unique_ids` (ví dụ DEU/0: 4068 vs 4031) → có field id trùng lặp trong cùng scope, cần quyết định dedup hay giữ nguyên.

**Sentiment:** 7 — sửa xong một bug chặn fan-out và thu được con số platform-wide lần đầu tiên; đồng thời lộ ra 2 quirk mới cần quyết định.

## 2026-10-22T05:00:00Z | chat-summary | score: 6

**Request:** "thêm 3 trường nữa 1) tên các field trong id 2) data type (matrix, vector, hay group) 3) description của chúng" — bổ sung 3 cột vào `datasets.csv`.

**Outcome:** Thêm vào `main.py` 3 cột mới (`fieldnames`, `fieldtypes`, `fielddescriptions`), map theo `datasetid` → `datasets.id`. Cột `fieldtypes` là **breakdown có đếm** ("MATRIX: 1943, VECTOR: 315") chứ không phải tập type thô, vì một dataset thường trộn nhiều type. Phát hiện `fieldCount` khớp tổng số field theo dataset (verify 286/286 dataset map đủ). Thêm `sys.stdout.reconfigure(encoding="utf-8", errors="replace")` vì print 11 MB text gặp `U+2011` → `UnicodeEncodeError` trên cp1252. `datasets.csv` giờ 23 cột, 11.6 MB, 0 ô rỗng.

**Files touched:**
- `main.py` (3 cột mới + fix encoding stdout)
- `datasets.csv` (regenerated, 23 cột)
- `Diary/conversation-log.md` (entry này)

**Open questions:** Chưa quyết định có nên tách `fieldtypes` thành cột số (`n_matrix`, `n_vector`, `n_group`) cho dễ filter thay vì parse chuỗi. `datasets.csv` 11.6 MB với 1 ô 867 kB (`pv87`) — Excel có thể không mở nổi, cân nhắc tách riêng file field-level.

**Sentiment:** 6 — hoàn thành yêu cầu, nhưng format ô gộp chưa tối ưu cho sử dụng thực tế.

## 2026-10-22T05:07:00Z | chat-summary | score: 3

**Request:** "đừng lưu hết datasets vào csv hãy chỉ lưu 100 dòng đầu".

**Outcome:** Đổi `datasets.to_csv(...)` → `datasets.head(100).to_csv(...)` trong `main.py`. Verify: `datasets.csv` còn 100 dòng, 23 cột, script chạy exit 0. `print(datasets.to_string())` vẫn in toàn bộ 286 dataset ra stdout (không yêu cầu thay đổi).

**Files touched:**
- `main.py`
- `datasets.csv` (regenerated, 100 rows)
- `Diary/conversation-log.md` (entry này)

**Open questions:** File CSV giờ là **sample 100 dòng đầu** (theo thứ tự API trả về, sort theo `id`), không phải toàn bộ catalog — cần ghi nhớ khi dùng làm nguồn thống kê.

**Sentiment:** 3 — thay đổi một dòng, không có quyết định khoa học nào.

## 2026-10-22T05:12:00Z | chat-summary | score: 7

**Request:** "nhìn rối quá, thay vì để Id là chủ thể hãy lấy fieldnames, fieldtypes, fielddescriptions còn các phần còn lại có thể trùng lập được" — sau đó làm rõ: "id và các thông tin trùng đều có thể lưu trong dòng đó... return sẽ có trùng thông tin với close nhưng ở 2 dòng khác nhau" → **bảng field-level, 1 dòng = 1 field, thông tin dataset lặp lại trên từng dòng**.

**Outcome:** Viết lại `main.py` theo hướng field-level. Đo trước để biết cột nào thực sự trùng: `/data-fields` **đã mang sẵn** context dataset (`datasetid`, `datasetname`, `categoryid/name`, `subcategoryid/name`, `region`, `delay`, `universe`, `pyramidMultiplier`, `themes`) với giá trị **identical** so với dataset record (verify 8/8 cột, 0 dòng lệch). `datafields.datasetname == datasets.name` (0 lệch). `fieldCount == số field thực tế` (286/286 khớp). Nhưng `coverage`, `dateCoverage`, `userCount`, `alphaCount` **khác** giữa 2 cấp (field-level là số riêng của field) → giữ cả 2 với tiền tố `dataset_`. Output: `datafields.csv` 100 dòng × 28 cột; bỏ `datasets.csv` (vẫn còn file cũ trên đĩa từ lần trước).

**Files touched:**
- `main.py` (viết lại, 78 → 121 dòng)
- `datafields.csv` (new, 100 rows × 28 cols, 200 kB)
- `Diary/conversation-log.md` (entry này)

**Open questions:** `datasets.csv` cũ (11.6 MB) vẫn nằm trên đĩa dù `main.py` không còn ghi nó — cần xóa hay giữ làm artifact. `dataset_researchPapers` NaN ở 12/100 dòng đầu (dataset không có paper) — bình thường.

**Sentiment:** 7 — thay đổi cấu trúc bảng theo yêu cầu, có số đo chứng minh cột nào thực sự trùng và cột nào không.

## 2026-10-22T05:24:00Z | chat-summary | score: 4

**Request:** Xóa 7 cột khỏi bảng field-level (`alphaCount`, `dataset_alphaCount`, `dataset_researchPapers`, `themes`, `dataset_fieldCount`, `userCount`, `dataset_userCount`) và đưa `dateCreated` + `dataset_dateUpdated` lên đầu.

**Outcome:** Sửa `main.py`: rút 7 cột khỏi cả `dataset_meta` selection và final column selection; chuyển `dateCreated`, `dataset_dateUpdated` lên 2 vị trí đầu. `datafields.csv` còn **21 cột × 100 dòng**, verify exit 0. Cột còn lại: dateCreated, dataset_dateUpdated, fieldid, field_description, type, datasetid, datasetname, dataset_description, categoryid, categoryname, subcategoryid, subcategoryname, dataset_valueScore, coverage, dataset_coverage, dateCoverage, dataset_dateCoverage, pyramidMultiplier, region, delay, universe.

**Files touched:**
- `main.py`
- `datafields.csv` (regenerated, 21 cols)
- `Diary/conversation-log.md` (entry này)

**Open questions:** `datasets.csv` cũ (11.6 MB) vẫn còn trên đĩa, `main.py` không còn ghi nó — xóa hay giữ.

**Sentiment:** 4 — thuần thao tác cấu trúc, không có quyết định khoa học.

## 2026-10-22T06:39:00Z | chat-summary | score: 6

**Request:** "dataset_valueScore là gì? hãy giải thích không code".

**Outcome:** Đo đặc tính `valueScore` trên 286 dataset (scope `EQUITY/USA/1/TOP3000`) và đọc cách reference code dùng nó. Phát hiện: chỉ tồn tại ở **dataset level** (không có trong `/data-fields`), là **số nguyên 1–7**, không null, phân bố hình chuông (mode = 3, 70/286 dataset; 7 chỉ có 1 dataset). Tương quan mạnh nhất với `pyramidMultiplier` (r = 0.495), yếu với `fieldCount` (−0.109), `alphaCount` (−0.181), `userCount` (−0.259), `coverage` (−0.161).

**Files touched:**
- `Diary/conversation-log.md` (entry này)

**Open questions:** BRAIN không công bố định nghĩa `valueScore` — chưa xác định được đây là editorial curation rating hay metric nội bộ. Giả thuyết "valueScore cao → nhiều simulation quota hơn" (do r = 0.495 với `pyramidMultiplier`) chưa được kiểm chứng, cần đối chiếu tài liệu chính thức.

**Sentiment:** 6 — đặc tính đo được là dữ kiện catalog có giá trị (giúp loại cột nếu nó thực sự thừa), nhưng bản chất của metric vẫn chưa xác minh.

## 2026-10-22T07:05:00Z | chat-summary | score: 6

**Request:** Thêm filter vào `main.py`: chỉ giữ field có `coverage > 0.7` **và** `dateCoverage > 0.7`.

**Outcome:** Thêm hằng `MIN_COVERAGE = 0.7` và lọc sau khi merge/rename, kèm print số field giữ lại / tổng / tỉ lệ. Chạy thật: **47 706 / 75 926 field (62.8 %)** thoát filter. `datafields.csv` vẫn lấy 100 dòng đầu, giờ 19 cột (user đã bỏ `dataset_coverage` / `dataset_dateCoverage` khỏi selection). Verify: min `coverage` 0.7273, min `dateCoverage` 0.8417, 0 NaN.

**Files touched:**
- `main.py` (thêm `MIN_COVERAGE` + filter + print)
- `datafields.csv` (regenerated, 100 rows × 19 cols)
- `Diary/conversation-log.md` (entry này)

**Open questions:** `dateCoverage` thiếu ở ~4 % record → các row đó tự động bị loại; chưa ghi rõ trong Docs. `head(100)` sau filter là 100 field đầu theo thứ tự API trả về (không random) — chưa phải sampling frame có ý nghĩa.

**Sentiment:** 6 — filter đúng như yêu cầu, nhưng là một quyết định sampling frame cần được nêu khi viết paper.

## 2026-10-22T07:12:00Z | chat-summary | score: 6

**Request:** "bây save thành 3 file với 3 type data là matrix, vector và group".

**Outcome:** Thay `fields.head(100).to_csv("datafields.csv")` bằng vòng lặp ghi 3 file: `datafields_matrix.csv`, `datafields_vector.csv`, `datafields_group.csv` (đặt tên lowercase theo `type.lower()`), mỗi file 100 dòng đầu, 19 cột, có print số field eligible của từng type. Chạy thật trên 47 706 field đã lọc: **MATRIX 36 854 · VECTOR 9 168 · GROUP 1 670** (tổng 47 692, lệch 14 so với 47 706 do `SYMBOL`/`UNIVERSE` type không thuộc 3 nhóm này).

**Files touched:**
- `main.py` (vòng lặp ghi 3 CSV)
- `datafields_matrix.csv`, `datafields_vector.csv`, `datafields_group.csv` (new, 100 rows × 19 cols mỗi file)
- `Diary/conversation-log.md` (entry này)

**Open questions:** `datafields.csv` cũ vẫn nằm trên đĩa và giờ **không còn được `main.py` ghi lại** — artifact stale, cần xóa. Vì sao còn 14 field không vào file nào: 8 `SYMBOL` + 7 `UNIVERSE` (theo `Docs/data-description.md`) — nếu cần thì phải quyết định có giữ 2 type này thành file thứ 4 hay bỏ hẳn (chúng không dùng được làm input của expression backtest).

**Sentiment:** 6 — tách file theo `type` là đúng về semantics, nhưng nêu rõ frame trong paper và xử lý 2 type bị bỏ sót.

## 2026-10-22T07:20:00Z | chat-summary | score: 6

**Request:** "cập nhật cái này" `Functions/login.py` (12-14) — hạ `RELOGIN_THRESHOLD_SECONDS` từ 2000 xuống 1000.

**Outcome:** Giữ nguyên giá trị 1000 (user đã tự sửa trong worktree, chỉ là comment còn nói "Same guard as ace_lib" — sai vì `ace_lib` dùng 2000). Viết lại comment giải thích **vì sao lệch**: cùng pattern, nhưng hằng số thấp hơn để giảm số lần persona flow (giới hạn 5 lần/phút, 25 lần/ngày) trong khi vẫn giữ ~17 phút đệm. Đồng bộ `Docs/Login.md` §4.4 (2000 → 1000) và thêm entry methodology.

**Files touched:**
- `Functions/login.py` (comment 12-18)
- `Docs/Login.md` (§4.4)
- `Diary/methodology.md` (entry mới, score 7)
- `Diary/conversation-log.md` (entry này)

**Open questions:** Chưa có số liệu chính thức về độ dài session tối đa của BRAIN (chỉ quan sát 2337–13730 s trong log) — ngưỡng 1000 s là chọn có chủ ý, chưa dẫn xuất từ một spec. Cần xác nhận nếu có tài liệu.

**Sentiment:** 6 — thay đổi nhỏ, vận hành, không ảnh hưởng số liệu.
