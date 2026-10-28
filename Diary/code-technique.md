## 2026-10-21T15:53:16Z | code-technique | score: 7

**Where:** `main.py` — `check_login` / `save_session` / `load_session` / `get_session`

**Pattern:** Session cache via persisted cookies + live expiry probe

**Why:** The BRAIN platform rate-limits `POST /authentication` (header `X-RateLimit-Limit-Minute: 5`, and Persona warns against more than 25 logins/day). Re-logging on every development run risks an account lockout. The JWT is issued as the session cookie `t`, and `GET /authentication` returns `{"token": {"expiry": <seconds_remaining>}}` for a live session (401 for a dead one) — so a cached cookie jar can be validated with a cheap GET instead of a full login.

**Reusable in:** Any script in this project that talks to the BRAIN API; the same `check_login` probe should gate every entry point before calling simulation endpoints.

**Sentiment:** 7 — non-obvious that the JWT lives in a cookie rather than the JSON body, and a reviewer would ask how lockout was avoided.

## 2026-10-21T16:08:34Z | code-technique | score: 8

**Where:** `main.py` — `start_session` (persona branch), `PERSONA_URL_PATH`

**Pattern:** Poll-based Persona verification with an out-of-band URL file

**Why:** The upstream `ace_lib.py` blocks on `input()` after printing the Persona inquiry URL, which forces the operator back to the terminal. Replaced with a `time.monotonic()`-based poll loop against the inquiry endpoint (`201` = verified) plus a 600 s deadline, so the script progresses unattended. Because a run may be detached (nohup/systemd/cron) or driven over SSH from a second machine, the inquiry URL is also written to `.brain_persona_url.txt` alongside the `print(..., flush=True)` — otherwise the link is lost to stdout buffering when no TTY is attached.

**Reusable in:** Any long-running BRAIN job that may need re-auth mid-run (simulation submits, data downloads) — the same "expose the link through a file, not just stdout" pattern applies to every interactive-auth step.

**Sentiment:** 8 — cross-cutting: it removes a hard human-in-the-loop block from every unattended run and is the only way the operator can verify from a different machine.

## 2026-10-21T16:15:16Z | code-technique | score: 6

**Where:** `Functions/login.py` — `class BrainLogin`

**Pattern:** Session-scoped class instead of module-level functions with globals

**Why:** The login logic needed per-instance state (`base_url`, `state_dir`, resolved file paths) that were previously module-level constants. `BrainLogin.__init__` resolves `state_dir` relative to the *package* (`Path(__file__).parent.parent / ".brain"`) rather than the CWD, so the script works regardless of where it is invoked from — relevant because the project is driven over SSH from arbitrary directories. The class also makes the `base_url` and `state_dir` overridable for tests without monkeypatching module globals.

**Reusable in:** Every future BRAIN module (simulation submit, data download) should take a `BrainLogin` instance rather than re-deriving the session — the session object is stateful and must be shared, not rebuilt per call.

**Sentiment:** 6 — a reviewer would ask why the state paths are not CWD-relative; the answer (SSH + arbitrary CWD) is not obvious from the diff.

## 2026-10-21T16:26:18Z | code-technique | score: 7

**Where:** `Functions/data.py` — `_flatten` / `_to_frame` / `BrainData.settings`

**Pattern:** Recursive flatten of nested catalog JSON into flat DataFrame columns

**Why:** The BRAIN catalog endpoints return nested objects (`category: {id, name}`, `dataset: {id, name}`, `themes: [...]`) whose key names collide across records — the existing `ace_lib.expand_dict_columns` renames to `category_id` but loses the sibling `name` key entirely when the nested dicts have different shapes, and it indexes `data[x].iloc[0]` which breaks on an empty result set. `_flatten` recurses with a `prefix` accumulator so every leaf becomes `parent_child` (`categoryid`, `categoryname`, `datasetid`, `datasetname`) with no collision and no row loss.

**Reusable in:** Any BRAIN endpoint returning nested JSON — simulations, alphas, `/options` settings payloads. The same helper replaces `expand_dict_columns` from `ACE_API__Gold_/helpful_functions.py` (which should then be deleted to avoid two divergent flatteners).

**Sentiment:** 7 — reviewer would ask "why not `json_normalize`"; the answer is that the BRAIN payload has same-named nested dicts with different inner keys, which `pd.json_normalize` leaves partly ambiguous.

## 2026-10-21T16:47:38Z | code-technique | score: 7

**Where:** `Functions/data.py` — `BrainData.settings`, `BrainData.combinations`

**Pattern:** Enumerate the valid scope space from a single `OPTIONS` call, not from N data calls

**Why:** The set of valid `(instrumentType, region, delay, universe)` scopes is fully described by the `OPTIONS /simulations` payload: `region` nests under `instrumentType` directly, but `delay` and `universe` nest one level deeper under `instrumentType -> region`. Reading that tree directly yields **44 valid scopes** (12 regions × their allowed delays × their allowed universes) in one HTTP request. The alternative — deriving the scope space by probing `/data-sets` and `/data-fields` — costs 2 requests per scope and cannot distinguish "scope is invalid" from "scope has no data", so it is both 88× more expensive and logically wrong. A separate check confirmed the counts: 30 universe names across regions but only **21 distinct** names, so `TOP3000` under USA and `TOP3000` under GLB are different scopes and a universe name alone is not a valid key.

**Reusable in:** Any simulation-submit / data-download module that needs to fan out over the scope space; the same `OPTIONS` tree is the authoritative source for what the platform accepts, and it should be fetched once and reused rather than re-fetched per call (see `combinations()` calling `settings()` on every invocation).

**Sentiment:** 7 — the "scope space is a tree, not a flat list" nesting difference is invisible until you diff the raw JSON, and a reviewer would question why a single universe name was being treated as a unique key.

## 2026-10-21T16:47:38Z | code-technique | score: 6

**Where:** `Functions/data.py` — `BrainData._get`, `BrainData.summary`

**Pattern:** Known fragility: catalog GET has no retry on a non-JSON body

**Why:** `BrainData._get` sleeps based on the `X-RateLimit-Remaining-Second` header and then calls `r.json()` with no error handling. Running `summary()` over the full 44-scope space (88 catalog requests) reproduces a crash: `GET /data-fields` returns a non-JSON body under rate limiting, and `requests` raises `requests.exceptions.JSONDecodeError: Expecting value: line 1 column 1 (char 0)`. The header-based sleep is not sufficient protection because the limit applies per-second across the whole session, and a single scope's two requests are back-to-back.

**Reusable in:** Any long fan-out over the BRAIN catalog — a retry-on-non-JSON wrapper (parse attempt, sleep, re-request) belongs in `_get` so that every caller inherits it, rather than being re-implemented per script.

**Sentiment:** 6 — a reproducible failure of the main catalog path; not a subtle scientific issue but it blocks the full-scope sweep.

## 2026-10-21T16:47:38Z | code-technique | score: 5

**Where:** ad-hoc enumeration scripts (not committed)

**Pattern:** Reading the settings tree by hand instead of reusing `BrainData.settings`

**Why:** The first attempt at listing regions/delays/universes re-derived the `OPTIONS` nesting inline and called `settings()` three times in one script, wasting requests against the rate limit. The committed `BrainData.settings` already normalises the tree into `{"instrumentType": [...], "region": {...}, "delay": {...}, "universe": {...}}` and should be the single entry point.

**Reusable in:** All ad-hoc catalog exploration scripts.

**Sentiment:** 5 — routine mistake, no paper impact, recorded only as a reminder that `settings()` is the canonical accessor.

## 2026-10-21T17:21:58Z | code-technique | score: 8

**Where:** `Docs/random-field-pipeline-proposal.md` §1.2 — filter key phẳng vs phân cấp trên `GET /data-fields`

**Pattern:** API filter dạng phân cấp bị server bỏ qua âm thầm; chỉ key dạng phẳng mới lọc thật

**Why:** Theo schema `OPTIONS /data-fields`, filter hợp lệ về mặt tài liệu là `category.id` / `category.name` / `dataset.id`. Thực tế đo được: `&category=model` lọc đúng (50/50 record đúng category), còn `&category.id=model` và `&category.name=Model` bị **bỏ qua hoàn toàn** — HTTP 200, `count=10000`, 50 record trả về trộn `model`/`fundamental`/`earnings`/`analyst`. Riêng `&dataset.id=model109` thì lại chạy đúng (count=544). Thêm nữa, `count` bị cap 10 000 khi có `limit`, nên `count` không phản ánh số lượng thật của tập đã lọc.

**Bài học (generalise):** với API filter phân cấp kiểu `a.b=c`, phải **verify bằng cách kiểm tra giá trị trong record trả về**, không tin `count` và không tin schema. Một query trả 200 nhưng lọc sai là kiểu bug im lặng tệ nhất vì không có tín hiệu nào báo sai.

**Reusable in:** Mọi lần gọi `GET /data-fields` / `GET /data-sets` có filter; và bất kỳ API nào khác trong project có filter dạng phân cấp.

**Sentiment:** 8 — silent-wrong-answer trap, ảnh hưởng trực tiếp tính đúng của mọi tập dữ liệu lấy từ catalog.

## 2026-10-21T17:21:58Z | code-technique | score: 8

**Where:** `Docs/random-field-pipeline-proposal.md` §1.1, §2 — pagination window và ý nghĩa thật của `universe`

**Pattern:** API chỉ cho cửa sổ 10 000 item, nhưng một request không filter trả ra toàn bộ; và `universe` là tham số trang trí, `region`/`delay` mới là tham số thật

**Why:** Hai phát hiện đo được bằng cách so tập `id` giữa các scope: (1) `GET /data-fields?<scope>` **không** `limit` trả về đúng 75 926 records trong 1 request 41.4 MB / 5.5 s, `count` khớp `len(results)`; nhưng `limit` tối đa 50, `offset+limit ≤ 10 000`, có filter mà không `limit` → 400, và `type=MATRIX` (57 356 field) không enumerate hết được → buộc phải tải unfiltered rồi lọc local. (2) `USA/1/TOP3000` và `USA/1/TOP500` trả về **cùng một tập 75 926 id** (Jaccard 1.000), còn `delay` cắt 82 % field (13 547/75 926 chung) và `region` gần như tách rời (Jaccard 0.239). Server cũng không hỗ trợ `sort`/`random`/`seed` (đều 400).

**Bài học (generalise):** trước khi xây pipeline phân trang, hãy thử **bỏ tham số phân trang** — nhiều API trả toàn bộ collection trong một response. Và đừng giả định mọi tham số scope đều có tác dụng: phải đo overlap thực tế để biết tham số nào thực sự lọc.

**Reusable in:** `Functions/data.py` (`_get`, `datafields`) và bất kỳ module fan-out nào sau này; mọi tính toán "kích thước catalog" phải dedup theo `id` chứ không cộng dồn theo scope.

**Sentiment:** 8 — thay đổi kiến trúc pipeline (1 request thay vì 44 request × phân trang) và sửa một nhận định sai đã viết trong `Docs/data-description.md`.

## 2026-10-21T17:21:58Z | methodology | score: 8

**Decision:** Frame lấy mẫu phải được **đóng băng bằng content-hash của tập field id**, không chỉ bằng `seed`; và `frame_id` phải ghi kèm cặp `(region, delay)`.

**Alternatives considered:**
- Chỉ pin `seed` — rejected, catalog là mục tiêu động (4 042 field mới sinh trong 2026-04, 22 736 trong 2026-03), nên cùng `seed=42` ở tuần sau ra bộ khác → kết quả không tái lập được.
- Ghi `scope` chuỗi vào log — insufficient, vì `universe` không đổi tập id: `USA/1/TOP3000` và `USA/1/TOP500` cho cùng tập id nhưng là hai backtest khác nhau về ngữ nghĩa.
- Pin theo timestamp tải — rejected, timestamp không xác định nội dung tập; phải là hash của chính tập id.

**Rationale:** Reproducibility của một nghiên cứu alpha phụ thuộc vào việc "3 field này" có tái lập được hay không, và điều đó phụ thuộc tập field chứ không phụ thuộc tham số RNG. `frame_id = sha256(sorted(field_ids))[:8]` + `(region, delay)` là đại lượng tối thiểu để tái lập bit-exact sau này.

**Impact on reported results:** Mọi bảng kết quả phải kèm `frame_id` và `(region, delay)`; nếu không, "random 3 field" là một claim không kiểm chứng được. Khi catalog thay đổi, `frame_id` đổi → kết quả cũ không cộng dồn được với mới → phải tái chạy toàn bộ.

**Sentiment:** 8 — a reviewer will ask "which 3 fields, and can I re-run that?"; the hash is the whole answer.

## 2026-10-21T17:21:58Z | methodology | score: 7

**Decision:** Trong `Docs/random-field-pipeline-proposal.md` §8, đề xuất chạy **song song hai phương án lấy mẫu**: A (uniform trên field, làm null baseline) và D (cluster-aware, mỗi id-prefix family 1 field), kèm báo cáo phân phối category/dataset của các draw.

**Alternatives considered:**
- Chỉ A — rejected, uniform trên field cho phân phối Model+Analyst ≈ 47 %, nên "random feature baseline" thực chất là *Model-heavy baseline*; gọi tên như vậy là sai lệch.
- Chỉ D — rejected, D dễ bị reviewer chất vấn là đã cấu trúc sẵn (mỗi draw đều "đẹp" theo family) → thiếu null baseline để so sánh.
- Chỉ B (stratified theo category) — deferred, phủ nghĩa 16 nhóm nhưng vẫn để lệch ở cấp dataset (dataset lớn nhất chiếm 8.8 % field, HHI 0.0216 → hiệu dụng 46.3/286 dataset).
- Bỏ qua kiểm soát family — rejected: 1 278 id-prefix nhưng top 5 prefix đã chiếm 12 972 field; 3 field có thể ra 3 biến thể của cùng khái niệm → chỉ 1 feature độc lập, và đây là lỗi thiết kế reviewer dễ chỉ ra.

**Rationale:** Bất kỳ baseline ngẫu nhiên nào cũng phải trả lời được "feature của bạn có thực sự độc lập không" và "baseline của bạn thiên về nhóm nào". A cho null trung thực, D cho kiểm soát independence, và báo cáo phân phối mẫu là câu trả lời bắt buộc cho cả hai.

**Impact on reported results:** Hai bảng kết quả riêng, không gộp; mọi claim về "random feature" phải kèm phương án lấy mẫu đã dùng. Nếu chỉ chạy A và bỏ D, claim "3 feature độc lập" không đứng được.

**Sentiment:** 7 — this is the difference between a defensible null baseline and a reviewer-obvious design flaw.

## 2026-10-22T04:25:00Z | code-technique | score: 7

**Where:** `Functions/data.py` — `BrainData._get`; `sweep_scopes.py`

**Pattern:** Retry-on-non-JSON trong `_get`, và phải suy ra `universe` hợp lệ từ `combinations()` chứ không hardcode

**Why:** (1) Rate limit tính theo *giây* trên toàn session, nên request liên tiếp có thể nhận body HTML; `r.json()` raise `JSONDecodeError`. Bọc `for attempt in range(GET_MAX_ATTEMPTS)` với `except requests.exceptions.JSONDecodeError` → sleep → thử lại, giữ nguyên hành vi cũ (raise) khi hết attempt. Sau khi sửa, 61 request sweep chạy sạch. (2) Lần sweep đầu **âm thầm cho kết quả sai**: hardcode `universe="TOP3000"` cho mọi cặp `(region, delay)` → 13/17 cặp trả 0 field, tổng field chỉ 89 629 thay vì 125 753. `TOP3000` chỉ hợp lệ với USA; phải map `(region, delay) → universe` từ `combinations()`.

**Bài học (generalise):** scope không hợp lệ **không** báo lỗi — API trả HTTP 200 với tập rỗng. Số 0 là tín hiệu của tham số sai, không phải "vùng dữ liệu trống". Khi fan-out catalog, luôn lấy giá trị tham số từ `OPTIONS` thay vì viết cứng.

**Reusable in:** Mọi module gọi catalog; `sweep_scopes.py` là script đo baseline dùng lại được.

**Sentiment:** 7 — lỗi "0 record" là loại bug im lặng tệ nhất: sweep vẫn chạy xong, vẫn in số liệu, nhưng số liệu sai 29 %.

## 2026-10-22T04:25:00Z | methodology | score: 8

**Decision:** Kích thước catalog toàn platform phải báo cáo là **số id duy nhất sau dedup** (441 dataset id, 125 753 field id), không phải tổng cộng theo scope (6 805 dataset-scope, 332 171 field-scope).

**Alternatives considered:**
- Báo tổng theo scope — rejected, đếm trùng 12–15 lần; con số 332 171 gây ấn tượng giả và sai về mặt khoa học.
- Chỉ báo scope `USA/1/TOP3000` (286 dataset / 75 926 field) — insufficient, đây là 1 trong 44 scope hợp lệ và không đại diện platform.

**Rationale:** "Có bao nhiêu data trên BRAIN" là một câu hỏi phải trả lời được ở cấp *catalog*, không phải cấp *scope*. `region` và `delay` cắt tập id gần như tách rời (Jaccard 0.239 giữa USA và GLB) nên cộng dồn theo scope đòi hỏi giả định overlap mà ta đo được chứ không giả định.

**Impact on reported results:** Mọi claim về "toàn bộ data của BRAIN" trong paper phải ghi rõ: 441 dataset id, 125 753 field id, dedup theo `id` trên 17 cặp `(region, delay)` + 44 scope. Ứng dụng chỉ dùng 1 scope thì con số là 286/75 926, và phải nói rõ đó là phạm vi nghiên cứu chứ không phải giới hạn nền tảng.

**Sentiment:** 8 — con số này sẽ xuất hiện trong abstract/intro; reviewer sẽ hỏi "platform-wide hay scope-specific?" và câu trả lời phải là con số dedup.

## 2026-10-22T05:00:00Z | code-technique | score: 6

**Where:** `main.py` — `sys.stdout.reconfigure(encoding="utf-8", errors="replace")`

**Pattern:** Re-encode stdout trước khi in text lớn chứa ký tự ngoài cp1252

**Why:** `datasets.to_string()` với cột `fielddescriptions` sinh ~11 MB text có chứa `U+2011` (non-breaking hyphen). Trên Windows console mặc định cp1252, `print` raise `UnicodeEncodeError: 'charmap' codec can't encode character '\u2011' in position 10393792` — tức là crash **sau khi** toàn bộ API call đã xong, mất công. `sys.stdout.reconfigure(encoding="utf-8", errors="replace")` ở đầu `main()` sửa cả hai vấn đề: encoding và ký tự thay thế.

**Bài học (generalise):** trên Windows, bất kỳ code nào in text tải từ API có thể gặp ký tự ngoài cp1252 thì phải re-encode stdout **trước** khi in, không phải sửa sau khi đã crash. `errors="replace"` biến ký tự lạ thành `?` thay vì abort cả job.

**Reusable in:** Mọi entry point in dữ liệu thô ra stdout; `sweep_scopes.py` hiện chỉ in số đếm nên chưa cần, nhưng nếu in danh sách field thì cần.

**Sentiment:** 6 — lỗi môi trường đặc thù Windows, không phải vấn đề khoa học, nhưng chặn cả pipeline.

## 2026-10-22T08:27:00Z | code-technique | score: 8

**Where:** `Functions/cache.py` — `save_cache`, `ScopeCache.take`

**Pattern:** Lưu table vào `.npz` theo lưới (cột × block) để đọc là lazy theo từng archive member, rồi trả về đúng thứ tự yêu cầu

**Why:** `np.load` giải nén **mỗi member khi member đó được chạm tới**, không phải cả archive. Nên nếu mỗi (cột, block 8192 dòng) là một member riêng, thao tác "lấy 3 dòng ở 4 cột" chỉ nạp ≤ 12 member thay vì toàn bộ 115. Đo thật trên catalog 47 706 dòng × 19 cột (4.4 MB): đọc 3 dòng × 4 cột = **12.2 ms**, đọc 3 dòng × 19 cột = 168 ms, full scan = 820 ms → chọn lọc nhanh hơn full scan 66.9×.

Hai lỗi phải sửa khi làm:
1. **Thứ tự**: gom dòng theo block rồi phải scatter về thứ tự gọi — cần `restore = np.argsort(order)` với `order = np.argsort(idx)`. Thiếu bước này trả về đúng *dữ liệu* nhưng sai *thứ tự*, và test bằng `frame.iloc[idx].equals(...)` mới bắt được.
2. **dtype**: một bản dtype không đủ. `numpy_dtypes` (bản ghi vào archive, dùng `U`/`int8`/`float64` để **không cần pickle**, nên `allow_pickle=False` vẫn hợp lệ) khác `pandas_dtypes` (bản khôi phục, phải trả về `str`/`bool`/`int64` gốc). Lưu 1 bản → round-trip đổi `str`→`object`, `bool`→`int8`, `int`→`float64`.

**Bài học (generalise):** format "phẳng" một cột (CSV) buộc phải parse toàn bộ file để biết record nào ở dòng nào. Format lưu trữ theo *block* + *lazy member* biến "đọc vài dòng" thành thao tác O(cột cần × block chạm), và quan trọng hơn là **giữ được thứ tự dòng bằng row position** — nên tập eligible phải lưu là `.npy` chỉ chứa index, không phải một bản copy của dữ liệu.

**Reusable in:** Mọi cache catalog cần đọc theo lựa chọn (sample, filter, backtest theo tập field); và mọi bảng lớn cần tra cứu ngẫu nhiên mà không muốn nạp hết vào RAM.

**Sentiment:** 8 — reviewer sẽ hỏi "vì sao không parquet"; câu trả lời là parquet cần `pyarrow` (dependency mới) và không cho lazy row-block trong khi npz có sẵn trong numpy.

## 2026-10-22T08:53:00Z | code-technique | score: 7

**Where:** `Functions/cache.py` — `save_cache`, `ScopeCache.eligible`; `main.py` — vòng lặp `FIELD_TYPES`

**Pattern:** Một archive per (scope, field type), với tập eligible là **member bên trong** archive chứ không phải file `.npy` rời

**Why:** Layout cũ (`1 npz` + `3 npy` rời) có 2 vấn đề: (1) người đọc phải biết quy ước ghép file nào với file nào, và phải chịu 4 file cho 3 khái niệm; (2) file `.npy` rời không mang metadata scope/type nên không tự mô tả được. Layout mới: `{scope_key}_{type.lower()}.npz` chứa snapshot **chưa lọc** của type đó + member `eligible` (row position) + `meta` có `field_type` và `catalog_frame_id` (hash chung của toàn catalog → biết 3 archive cùng snapshot).

Lỗi logic phải tránh: layout cũ cache `fields` **đã** lọc `coverage`/`dateCoverage` rồi mới tính `eligible_idx` → tập eligible trùng toàn bộ. Layout mới cache snapshot chưa lọc, suy ra eligible local → đúng nguyên tắc "cache raw, lọc local".

**Bài học (generalise):** khi một file cache phục vụ nhiều "view" (type, split, filter), để các view nằm **trong** file chính dưới dạng member thay vì là file rời — file chính tự mô tả đầy đủ, và không có "orphan index" khi copy/move cache. Đồng thời: điều kiện lọc phải được áp dụng **đúng một lần**, và cache phải chứa trạng thái *trước* lọc nếu ta muốn đổi ngưỡng lọc mà không tải lại.

**Reusable in:** Mọi cache cần tách nhiều "view" từ một tải về; mọi pipeline có bước lọc tham số hoá (`MIN_COVERAGE`) — ngưỡng lọc phải nằm ngoài cache để đổi được mà không tải lại.

**Sentiment:** 7 — reviewer sẽ hỏi "tại sao eligible nằm trong npz chứ không phải file riêng"; câu trả lời là khả năng tái lậc (self-describing cache) và tránh lỗi lọc hai lần.

## 2026-10-22T09:22:00Z | code-technique | score: 7

**Where:** `Functions/cache.py` — `cached_scope`, `ScopeCache.eligible_positions`; `main.py` — `fetch_scope` / `main`

**Pattern:** Cache-hit theo *folder scope* (all-or-nothing), và suy ra view từ raw snapshot thay vì lưu sẵn view

**Why:** Folder scope là ranh giới tự nhiên của một lần tải: nếu `cache/{region}_{delay}_{universe}/` tồn tại với đủ 3 file type thì snapshot đã được pin, không cần login và tải lại 41 MB (đo: 22.7 s → 9.0 s). Điều kiện **all-or-nothing** là bắt buộc: scope chỉ có 2/3 file thì phải tải lại toàn bộ, vì nếu chấp nhận partial thì sẽ trộn catalog mới với catalog cũ trong cùng một "scope" — đúng loại bug im lặng.

Bước thứ hai là bỏ member `eligible` khỏi archive: `eligible_positions(min_coverage)` tính lại từ cột raw `coverage`/`dateCoverage` đã lưu. Lý do: `eligible` lưu sẵn là **giá trị đóng băng tại thời điểm save** — đổi `MIN_COVERAGE` thì phải tải lại catalog, tức là ngưỡng lọc biến thành tham số "đòi tải lại". Với raw snapshot, ngưỡng là tham số sống. Chi phí: đọc 2 cột float64 × N dòng thay vì đọc 1 member int64 — vô hại (vài chục ms).

**Bài học (generalise):** khi cache phục vụ nhiều view, cache **dữ liệu gốc + hàm suy ra view**, không cache từng view. Và ranh giới "cache hit" phải là đơn vị nguyên tử: nếu một scope gồm nhiều file thì cache hit = đủ bộ file, không phải "file này tồn tại".

**Reusable in:** Mọi cache nhiều file theo scope; mọi pipeline có bước lọc tham số hoá sau bước tải.

**Sentiment:** 7 — "all-or-nothing" là điều kiện dễ bỏ sót (partial cache trông vẫn chạy được và cho ra kết quả sai).

## 2026-10-22T09:20:00Z | code-technique | score: 6

**Where:** `config/scopes.yaml`

**Pattern:** Ghi scope space của API dưới dạng cây region → delay → universe, kèm block `counts`, thay vì list phẳng

**Why:** `OPTIONS /simulations` **lồng** delay và universe dưới region, nên phép toán "region × delay × universe" (12 × 2 × 21) cho ra 504 tổ hợp — trong đó chỉ **44** là hợp lệ. Ghi list phẳng 504 dòng sẽ khẳng định những scope không tồn tại, và đó là loại bug im lặng đã ghi nhận ở sweep (scope sai trả HTTP 200 với 0 record). Cây giữ đúng quan hệ API và cho phép đếm lại 44 bằng `sum(n_scopes)`.

**Bài học (generalise):** khi snapshot một API có cấu trúc phân cấp, **giữ nguyên cấu trúc** trong file config. Dạng phẳng làm mất đúng thông tin quan trọng nhất (tổ hợp nào hợp lệ) và thay bằng một con số lớn hơn trông có vẻ "đầy đủ" nhưng sai.

**Reusable in:** Mọi config sinh từ API có nested choices; mọi tài liệu tham chiếu scope.

**Sentiment:** 6 — nguyên tắc rõ ràng nhưng file hiện chưa được code nào đọc nên chưa có tác dụng chống bug.

## 2026-10-22T09:27:00Z | code-technique | score: 7

**Where:** `config/scopes.yaml` (bản enumerate)

**Pattern:** Enumerate tập hợp hợp lệ thành list phẳng, thay vì giữ cấu trúc lồng của API

**Why:** Entry trước (09:20) khuyên "giữ nguyên cấu trúc API" — **sai trong trường hợp này**, và đây là correction. Lồng của API là artefact của settings widget, không phải ràng buộc: tập universe của một region không đổi theo delay (verify cả 11 region). Nên cây vừa phức tạp hơn, vừa không thuận tiện cho lấy mẫu. List phẳng 41 dict `{region, delay, universe}` làm mọi draw hợp lệ *by construction* → một lần `random.choice` là xong, không cần bước lọc/validate sau draw.

**Bài học (generalise):** "giữ nguyên cấu trúc nguồn" chỉ đúng khi cấu trúc mang **ý nghĩa**. Trước khi flatten, phải kiểm tra tính chất độc lập bằng dữ liệu thật chứ không suy ra từ vài ví dụ — ở đây mối quan hệ "universe ⊥ delay | region" là điều kiện để flatten mà không mất scope nào. Và cấu trúc phải phục vụ **cách sử dụng dự kiến**, không phục vụ hình dạng của API.

**Reusable in:** Mọi config sinh từ API nested; mọi bảng tra cứu mà mục đích là lấy mẫu.

**Sentiment:** 7 — sửa lại một khuyến nghị trước đó bằng bằng chứng đo trên live API, và làm file dùng được ngay cho mục đích đã nêu.

## 2026-10-22T09:36:00Z | code-technique | score: 7

**Where:** `main.py` — `load_scopes`, `fetch_scope(data, scope)`, `main`

**Pattern:** Tách session khỏi hàm tải scope, để **một** session phục vụ toàn bộ vòng lặp scope

**Why:** `fetch_scope` trước đây tự gọi `BrainLogin().get_session()` — chạy lặp 41 scope sẽ tốn **41 lần login**, vượt giới hạn nền tảng (5 lần/phút, 25 lần/ngày). Tách `BrainData` ra tham số và đăng nhập một lần ở `main()` giữ toàn bộ vòng lặp trong **1 session**. Điều kiện: chỉ login khi thật sự còn scope thiếu cache — nếu đã cache đủ thì cả run không cần auth, và phần "Login successful. JWT" không lộ token ra log.

**Bài học (generalise):** khi lặp trên một tài nguyên bị **giới hạn tần suất theo chính sách** (login, quota API), đơn vị tài nguyên phải được nâng lên một tầng — tách thứ bị giới hạn (auth) ra khỏi thứ bị lặp (tải scope), và chỉ xin nó khi thật sự cần. Ngược lại thì một vòng lặp hợp lệ vẫn chết vì hết quota.

**Reusable in:** Mọi batch job gọi API có auth rate-limit; mọi vòng lặp trên phạm vi lớn hơn số lần auth cho phép.

**Sentiment:** 7 — lỗi này chỉ lộ ra khi quy mô lặp vượt ngưỡng (41 > 25), nên dễ bị bỏ sót trong review.

## 2026-10-22T15:46:39Z | code-technique | score: 8

**Where:** `main.py` — `main()` (vòng lặp scope), `totals` / `grand_eligible` / `grand_total`

**Pattern:** Duyệt N scope dùng chung **một** biến tổng `catalog_total` gán đè trong vòng lặp, rồi cộng dồn — tạo ra con số scope-field bị đếm trùng mà vẫn trông như catalog size

**Why:** `catalog_total` được khởi tạo `0` **bên trong** mỗi scope, rồi `catalog_total = cache.catalog_total` gán đè 3 lần (MATRIX → VECTOR → GROUP), sau đó `totals.append((scope_key, n_eligible, catalog_total))`. Vì cả 3 archive của một scope cùng mang `catalog_total` nên bản thân vòng trong đúng; nhưng khi `grand_total = sum(t for _, _, t in totals)` cộng trên 41 scope thì **cùng một field được đếm 5–6 lần** (`EUR/1` có 5 universe cùng catalog). Đo trên cache hiện tại: 16 scope đã tải mới dùng **7** `catalog_frame_id` distinct → `grand_total` lớn hơn tổng field thật khoảng 2–3×, và `grand_eligible / grand_total` là **tỷ lệ theo scope-field**, không phải tỷ lệ field dùng được.

Cách phát hiện lỗi loại này không cần sửa code: đếm `catalog_frame_id` distinct trong cache và so với số folder. Không khớp ⇒ đang cộng dồn scope, chưa cộng dồn catalog.

**Bài học (generalise):** khi một pipeline duyệt nhiều "phiên bản" của cùng một dữ liệu và in tổng cuối, phải hỏi **"tổng này đếm cái gì, theo đơn vị nào?"**. Nếu 2 scope có cùng `content_hash`, chúng là cùng một đối tượng và mọi phép cộng phải deduplicate trước. Đây là biến thể của lỗi đã ghi ở `Docs/data-description.md` §4.

**Reusable in:** Mọi chỗ in "tổng X / tổng Y" cuối pipeline; mọi bảng tổng hợp nhiều partition có nội dung trùng nhau.

**Sentiment:** 8 — con số in ra trông hợp lệ và sẽ vào bảng kết quả, nhưng đơn vị đo sai; reviewer chỉ cần hỏi "trong số field này có bao nhiêu field thật" là lộ.

## 2026-10-22T15:46:39Z | code-technique | score: 7

**Where:** `main.py:147` — `rng = np.random.default_rng()`; `Functions/cache.py` — `save_cache` (khối `meta`)

**Pattern:** RNG không seed, còn snapshot thì đã được pin bằng content-hash — độ lặp được chỉ đúng một nửa

**Why:** `main.py` dùng `np.random.default_rng()` **không truyền seed** → mỗi lần chạy ra bộ 5 field khác nhau, không tái lập được. Nhưng phần "có thể tái lập" thì đã làm rất chặt: `save_cache` ghi `meta` chứa `fetched_at`, `frame_id`, `catalog_frame_id`, `scope`, `field_type`. Thiếu duy nhất là `seed` của RNG (và index draw) trong `meta` hoặc output. Vấn đề phụ: 41 scope có 16 catalog khác nhau nhưng `catalog_frame_id` trùng nhau, nên `meta` **không phân biệt được scope nào sinh ra draw** nếu ta chỉ nhìn `frame_id`.

**Bài học (generalise):** "có seed" và "có seed + fingerprint của dữ liệu mà seed áp dụng lên" là hai mức tái lập khác nhau. `default_rng()` không seed = mức 0; `default_rng(42)` = mức 1, vẫn hỏng nếu cache đổi; `frame_id + seed + scope` = mức 2. Repo đã ở mức 2 cho phần dữ liệu nhưng mức 0 cho phần draw.

**Reusable in:** Mọi `rng` dùng để lấy mẫu trong pipeline nghiên cứu; và mọi output cần tái lập.

**Sentiment:** 7 — fix một dòng, nhưng thiếu nó thì toàn bộ công sức pin snapshot (`frame_id`, cache all-or-nothing) trở nên vô nghĩa vì không biết draw đó là từ đâu.

## 2026-10-22T18:31:01Z | code-technique | score: 7

**Where:** `main.py` — nhánh `else` của `if builder.needs_auth():`

**Pattern:** Báo cáo trạng thái hết hạn của một tài nguyên bằng cách gọi hàm kiểm tra **ở nhánh không tiêu thụ tài nguyên đó**, thay vì nhét hàm kiểm tra vào đường dẫn vốn đã tiêu thụ nó

**Why:** Cơ chế đếm ngược session **đã có sẵn** — `login.check_login()` trả về số giây còn lại qua `GET /authentication`. Nhưng nó nằm trong `get_session()`, mà `get_session()` chỉ chạy khi `needs_auth()` là `True`. Khi cache còn tươi thì nhánh login bị bỏ qua hoàn toàn ⇒ không có gì để in ⇒ user hỏi "tôi không thấy còn bao lâu". Đây không phải lỗi cơ chế mà là dòng báo cáo chưa từng được viết ra terminal.

Cách sửa đúng: `else: load_session()` rồi `check_login()`. Nhánh này **vốn đã có session trên đĩa** nên `check_login()` chỉ là 1 `GET` read-only — không tốn login nào, giữ nguyên ngân sách 25 login/ngày. Nếu đặt báo cáo vào `get_session()` thì bắt buộc phải login mới được báo cáo login → tự phá mục đích.

**Bài học (generalise):** khi một API có sẵn hàm "còn bao lâu", đừng gọi nó ở đường dẫn đắt tiền nhất. Tách báo cáo (read-only) khỏi hành động (tiêu thụ tài nguyên) — báo cáo thuộc về nhánh rẻ. Cách phổ biến hơn: `if needs_auth(): spend() else: report()`.

**Reusable in:** Mọi cặp "tiêu thụ / báo cáo" — token, quota, file lock, license seat.

**Sentiment:** 7 — không phải mới, nhưng dễ làm ngược lại: đặt báo cáo vào đường dẫn login vẫn "chạy được" nên trông như đúng cho tới khi người dùng hỏi không thấy gì.

## 2026-10-22T18:31:01Z.1 | code-technique | score: 7

**Where:** `Functions/cache.py` — `CatalogCache.expires_in_seconds()`

**Pattern:** Suy ra countdown từ **chính** hằng số mà quyết định hành vi dùng, thay vì khai một hằng số thứ hai cho mục đích hiển thị

**Why:** `CatalogBuilder.stale_scopes()` quyết định refetch bằng cách so `age_seconds(paths) > CATALOG_MAX_AGE_SECONDS`. Nếu viết `expires_in = MAX_AGE - age` với một hằng số riêng cho báo cáo, số in ra và quyết định của run có thể lệch nhau sau nàa khi ai đó đổi cadence. Viết `return CATALOG_MAX_AGE_SECONDS - self.age_seconds(paths)` buộc hai bên dùng **cùng một nguồn sự thật**, nên báo cáo không bao giờ tương phản với hành vi.

Quy ước dấu: âm = đã hết hạn. Cùng kiểu với `RELOGIN_THRESHOLD_SECONDS` trong `login.py` — deadline đo từ lúc lấy tài nguyên, kiểm tra **trước** khi dùng chứ không phải sau khi hỏng.

Một quyết định khác đáng ghi: chỉ in scope **hết hạn sớm nhất** (`min` theo `expires_in`) thay vì cả 41 scope. Vì `min` chính là cái quyết định run mai có phải login không — in hết sẽ làm nhiễu đúng thông tin cần đọc.

**Bài học (generalise):** mọi biểu hiển thị trạng thái hết hạn nên là hàm của điều kiện quyết định, không phải phép tính độc lập. Nếu đường báo cáo và đường quyết định tách rời, chúng sẽ nói dối nhau.

**Reusable in:** Quota theo tháng, EOL của thư viện, TTL của cache key khác.

**Sentiment:** 7 — reviewer sẽ hỏi "tại sao không hardcode 15 ngày trong chuỗi in?", và câu trả lời (buộc dùng chung hằng số quyết định) là điều đáng giữ.

## 2026-10-23T07:12:00Z | code-technique | score: 7

**Where:** `Functions/data.py` — `BrainData.operators()`; `main.py` — khối in bảng operator cuối `main()`

**Pattern:** `/operators` là endpoint **duy nhất** của BRAIN không scope-scoped: không nhận `instrumentType`/`region`/`delay`/`universe`, trả list phẳng (không có `{"results": [...]}` như `/data-sets` và `/data-fields`), và `scope` là **list** cần `explode()`.

**Why:** Đọc được `/operators` mà **không tốn login**: `login.load_session()` đọc cookie đã cache, `check_login` xác nhận còn sống, `GET /operators` trả 200 — quota 25/ngày không bị trừ. Khác `/data-fields`: cái đó cần `BrainData` có session nên `run(None)` chỉ an toàn khi cache đầy đủ, còn `/operators` không có cache layer (không cần — 103 record, ~0.2 MB) và chỉ cần một session bất kỳ.

**Đo (2026-10-23, live):** 103 operator publish; `scope` = COMBO 101 / REGULAR 84 / SELECTION 27 → **84 REGULAR** trong 7 category: Time Series 30, Arithmetic 16, Logical 11, Group 10, Cross Sectional 7, Vector 7, Transformational 3. `level` chỉ có 2 giá trị thật: `"ALL"` (66/84) và `null` (18/84) — **không phải thiếu key** (đã kiểm tra: cả 103 record đều có key `level`), mà là platform chưa xếp hạng operator đó. `generate_stats`, `reduce_*`, `combo_a`, `self_corr` là COMBO-only; `in`, `universe_size` là SELECTION-only — không cái nào dùng được cho REGULAR alpha.

**Reusable in:** Bất kỳ endpoint BRAIN nào cần trả lời "có thực sự cần session không" trước khi đưa vào đường cache-only — câu trả lời phụ thuộc endpoint có scope-scoped hay không, không phụ thuộc nó nằm chung "nhóm catalog".

## 2026-10-23T17:31:00Z | code-technique | score: 7

**Where:** `Functions/operators.py` — class `OperatorTable` (`load` / `fetch` / `arg_names` / `bucket_of`); `main.py` — khối `/operators` sau login

**Pattern:** Tách quy tắc thuần tuý (`arg_names`, `bucket_of`) và đường I/O (`fetch`, `load`) vào **một** class, với `staticmethod` cho phần không phụ thuộc session. Đường đọc và đường ghi **trả cùng kiểu** (`DataFrame`), nên `main.py` chỉ cần một biến `operators` bất kể CSV có sẵn trên đĩa hay không.

**Why:** `save()` trả `Path` còn lời gọi muốn dữ liệu để dùng tiếp → buộc phải đọc lại CSV (`pd.read_csv`) lần nữa. Đổi cả hai vế thành `DataFrame` làm một lần đọc là đủ. Đồng thời `load()` là `staticmethod` vì đọc từ đĩa **không cần session** — đây là điểm quan trọng với `LOGIN_ALLOW = False`: bảng operator vẫn dùng được khi pipeline bị cấm gọi platform.

**Thứ tự trong `main.py`:** login → `/operators` → catalog. Nhánh 3 của `/operators` (không có CSV **và** `LOGIN_ALLOW = False`) phải **dừng** — không có gì để load, cũng không được phép fetch. Nhưng `return` ở nhánh lỗi phải nằm **sau** khối `/operators`, không phải trong nhánh `else` của login: nếu check `builder.needs_download()` nằm trong nhánh login thì `LOGIN_ALLOW = False` với catalog thiếu sẽ `return` **trước** khi tới xử lý `/operators`, và bảng operator trên đĩa sẽ không bao giờ được load.

**Reusable in:** mọi bước xử lý có hai đường (cache-hit / fetch) — cache-hit phải **trả cùng kiểu** với fetch, nếu không thì người gọi phải biết nó đang ở đường nào.

**Sentiment:** 7 — reviewer sẽ hỏi "tại sao `load` là staticmethod?", và câu trả lời (đọc đĩa không cần session → `LOGIN_ALLOW=False` vẫn dùng được) là điều đáng giữ; bug thứ tự early-return là loại reviewer tìm ra khi đọc luồng điều khiển.

## 2026-10-23T17:31:00Z.1 | code-technique | score: 6

**Where:** `Functions/operators.py` — `bucket_of()`; `Docs/all-operators.md`

**Pattern:** Verify refactor bằng **byte-identical**, không bằng "trông giống": `cmp` file CSV trước và sau, cộng md5. Với bảng phân loại, byte-identical là bằng chứng mạnh hơn nhiều so với so sánh shape/dtype.

**Why:** Khi đổi tên bucket (`MATRIX_CONSTANT` → `MATRIX_GENERATED`) hoặc refactor hàm → class, rủi ro lớn nhất là **âm thầm** đổi phân loại. `cmp` trên file CSV regenerate loại bỏ khả năng đó: cùng md5 `85b986a9...` nghĩa là 84 dòng, thứ tự, bucket, `expression`, `description` — tất cả y nguyên. Ba nhánh còn lại (CSV có / CSV không + login / CSV không + không login) chạy thật để xác nhận luồng điều khiển, không chỉ đọc code.

**Reusable in:** mọi thay đổi có thể tác động tới bảng sinh ra — cache CSV, parquet, snapshot archive. Chụp baseline trước khi sửa, `cmp` sau.

**Sentiment:** 6 — kỹ thuật quen thuộc nhưng dễ bỏ qua; ở đây nó là thứ duy nhất chứng minh việc đổi tên không đổi dữ liệu.

## 2026-10-24T07:13:11Z | code-technique | score: 7

**Where:** `Functions/operators.py` — `_balanced_buckets()`, `sample_int()`, `class MatrixBinary`

**Pattern:** Chia một khoảng số nguyên thành N bucket **theo tỉ lệ**, không theo số tuyệt đối: `_BUCKET_FRACTIONS = (5/252, 22/252, 66/252, 126/252)` × `count = max - min + 1`, rồi mỗi bucket được chọn **đều** (20% mỗi bucket) và một giá trị bên trong bucket được chọn đều.

**Why:** Khoảng lấy mẫu trong codebase này **không cố định** — window là `(1, 252)`, lag là `(0, 5)`. Bản đầu dùng `_REFERENCE_RANGE_SIZE = 252` + `_REFERENCE_CUTS = (5, 22, 66, 126)` rồi scale `round(count * cut / 252)`: nhìn có vẻ động nhưng vẫn **hard-code 252**, và cắt sai ở range không cùng tham chiếu. Chuyển sang tỉ lệ làm 252 thành **tham chiếu định nghĩa tỉ lệ** chứ không phải giả định về range: `(0, 100)` → `0-1, 2-8, 9-25, 26-49, 50-100` (đúng 1.98/8.73/17.46/23.81/48.02%) thay vì cắt theo ngày.

Kỹ thuật quan trọng đi kèm: **clamp cut để mọi bucket có ít nhất một số nguyên**. `cuts.append(max(cuts[-1] + 1, min(scaled_cut, count - (BUCKET_COUNT - index))))` — nếu không clamp, một khoảng lệch tỉ lệ có thể tạo bucket rỗng, và `rng.integers(low, high+1)` với `low > high` sẽ raise. Bucket rỗng cũng làm mất tính chất "mỗi bucket 20%".

**Reusable in:** mọi bài "chia khoảng thành bucket có xác suất bằng nhau" — sampling horizon, bucketing feature, stratified draw. Cùng pattern cho `bin_edges` khi cần dùng lại nhưng không phải uniform trong bucket.

**Sentiment:** 7 — reviewer sẽ hỏi "tại sao không dùng `_REFERENCE_CUTS` scale theo 252?", và câu trả lời (252 là tham chiếu định nghĩa tỉ lệ, không phải giả định về range) là điều đáng giữ; kỹ thuật clamp cut chống bucket rỗng là thứ chỉ lộ ra khi range lệch tỉ lệ.

## 2026-10-24T07:13:11Z.1 | code-technique | score: 7

**Where:** `Functions/operators.py` — `OperatorProfile`, `MatrixBinary._profile()`

**Pattern:** Builder trả về **profile dict có kiểu** thay vì trả chuỗi: `category` + `name` + `config` (tham số **được rút ngẫu nhiên**, kèm giá trị platform thực sự nhận) + `inputs matrics` (field theo đúng thứ tự platform) + `expression` (FASTEXPR cuối). `TypedDict` dùng **functional syntax** vì key `'inputs matrics'` có khoảng trắng — class syntax của `TypedDict` không biểu diễn được key có space (đã verify: `SyntaxError` trên Python 3.14).

**Why:** Chuỗi FASTEXPR là **sink** — không parse được ngược, không biết field nào là input, không biết tham số nào được rút ngẫu nhiên. Bước sinh alpha sau này cần đúng ba thứ: danh sách field để chọn, giá trị tham số để replay, và chuỗi để gửi. Profile giữ cả ba trong một object, và `config` tách **tham số đã rút** khỏi **expression** đã render — nên replay chỉ cần `(seed, stream)` chứ không cần parse lại chuỗi.

Ranh giới của `config` là **tham số biến theo seed**, không phải "mọi tham số không phải matrix field": tham số cố định của operator (ví dụ `filter = true` của `add`/`multiply`/`subtract`) **không** nằm trong `config` — nó không đổi theo seed nên không cần lưu để replay. Đưa cả nó vào `config` sẽ làm profile phải chứa dữ liệu tĩnh, tức là dữ liệu mà đọc ra từ `expression` là biết.

Điểm dễ sai: thứ tự field. Platform đặt tên tham số **không nhất quán** — `ts_corr(x, y, d)` nhưng `ts_covariance(y, x, d)` và `ts_regression(y, x, d, …)`. Nên `inputs matrics` ghi theo thứ tự platform **thực sự nhận** (`ts_corr` → `[x, y]`, `ts_covariance`/`ts_regression` → `[y, x]`), và mỗi builder tự biết thứ tự riêng thay vì `get()` áp một quy tắc chung.

**Reusable in:** mọi bước sinh expression cho bucket còn lại (`MATRIX_UNARY` 40 operator, `VECTOR` 7, `GROUP` 9) — mỗi bucket một class, cùng kiểu `OperatorProfile`, thêm `category` riêng.

**Sentiment:** 7 — ranh giới "config chỉ chứa tham số biến theo seed" là điều reviewer sẽ hỏi khi thấy `filter` không nằm trong `config`; trả lời bằng lập luận replay là điều đáng giữ.

## 2026-10-24T07:23:07Z | code-technique | score: 7

**Where:** `Functions/operators.py` — `class IntegerSampler` (`buckets()`, `sample()`)

**Pattern:** Gom hằng số + hàm module-level thành class dùng `classmethod` khi hàm **đọc hằng số của chính class**: `BUCKET_FRACTIONS` / `BUCKET_COUNT` là hằng số class, `buckets()` và `sample()` là `classmethod` vì `buckets()` cần `cls.BUCKET_FRACTIONS` để cắt bucket.

**Why:** `staticmethod` sẽ buộc viết `IntegerSampler.BUCKET_FRACTIONS` thủ công ở mọi chỗ dùng — mỗi lần gõ tên class là một cơ hội để lệch. Với `classmethod`, `cls.BUCKET_FRACTIONS` là **một nguồn sự thật duy nhất**, và subclass đổi hằng số thì mọi method tự động theo. Đây là cùng nguyên tắc đã dùng cho `OperatorTable.arg_names()` / `bucket_of()`: quy tắc thuần tuý → `staticmethod`; quy tắc đọc hằng số class → `classmethod`.

Tên method cũng đổi theo: `_balanced_buckets()` → `buckets()`. Tiền tố `_balanced_` chỉ có tác dụng phân biệt với hàm module-level; bên trong class, "balanced" đã là ngữ nghĩa mặc định của `distribution="balanced"`, nhắc lại là thừa.

**Reusable in:** mọi cặp "hằng số + hàm dùng hằng số" — bảng tham số + hàm tra cứu, danh sách bucket + hàm chia bucket, từ điển + hàm build. Khi đó dùng `classmethod` chứ không phải module-level constant + `staticmethod`.

**Sentiment:** 7 — reviewer sẽ hỏi "vì sao `classmethod` chứ không phải `staticmethod`?", và câu trả lời (một nguồn sự thật cho hằng số bucket) là điều đáng giữ; verify bit-exact 240/240 trên bản refactor là thứ chứng minh việc đổi cấu trúc không đổi số.

## 2026-10-24T08:37:06Z | code-technique | score: 7

**Where:** `main.py` — 40 builder `MATRIX_UNARY` (dòng ~40-540), `MATRIX_UNARY_BUILDERS`, `abs_`

**Pattern:** Sinh FASTEXPR theo bucket dạng **hàm module-level, không class** — mỗi operator một `def` trả về profile dict, cộng một dict `MATRIX_UNARY_BUILDERS` làm bảng tra. Không dùng `get(name, x)` như `MatrixBinary` vì 40 operator unary **không cùng chữ ký**: `ts_mean(x, d)` nhận window, còn `abs(x)` không nhận gì, `kth_element(x, d, k)` nhận hai tham số phụ.

**Why:** Điểm cần giữ cho mọi builder trong nhóm này:

1. **Tên hàm không được trùng builtin.** `def abs(...)` ở cấp module đã shadow builtin `abs`, khiến `abs(left)` trong `main()` gọi nhầm function của tôi → `TypeError: unsupported format string passed to dict.__format__`. Sửa bằng `abs_` (tên platform vẫn là `abs` qua key trong dict). Bài học: traceback chỉ ra dòng lỗi nhưng không chỉ ra nơi gây ra; phải `hasattr(builtins, name)` quét toàn bộ tên module-level mới ra. Ruff **không** cảnh báo loại này.

2. **Chỉ rút tham số có miền giá trị đã được platform document.** `d` (1-252), `k` (1-d), `std` (2-5, khoảng platform khuyến nghị), `driver` (gaussian/cauchy/uniform, nêu tên trong mô tả), `dense` (bool) được rút. `ts_returns` **không** rút `mode`: platform chỉ ship `mode = 1`, mô tả không liệt kê mode khác, và web search không tìm được tài liệu — giữ nguyên `mode = 1` thay vì bịa miền.

3. **Render đúng cú pháp của platform, không đồng nhất giữa các operator.** `quantile` dùng `driver = gaussian` (identifier trần) còn `ts_quantile` dùng `driver="gaussian"` (chuỗi có quotes) — hai operator cùng tên tham số nhưng cú pháp khác nhau, theo đúng definition platform.

4. **`config` chỉ chứa tham số biến theo seed.** Tham số cố định (`hump = 0.01`, `sigma = 1.0`, `constant = 0`, `mode = 1`, `lambda_min/max`, `target_tvr`) không vào `config` — chúng đọc ra từ `expression` là biết.

**Reusable in:** bucket `VECTOR` (7), `GROUP` (9), `GROUPING`, `MATRIX_GENERATED` — cùng nguyên tắc: một `def` mỗi operator, key trong dict tra, tham số rút chỉ khi có miền đã document, render bám definition của từng operator.

**Sentiment:** 7 — reviewer sẽ hỏi "vì sao `mode` không rút mà `std` thì rút?" và "vì sao `quantile` và `ts_quantile` render khác nhau"; hai câu trả lời đều dựa trên definition platform, đáng giữ.

## 2026-10-24T08:52:51Z | code-technique | score: 7

**Where:** `main.py` — 40 builder `MATRIX_UNARY` (đã đổi từ profile sang chuỗi thuần)

**Pattern:** Builder trả về **chuỗi FASTEXPR thuần** (`-> str`) thay vì profile dict. `_unary_profile()` và `UnaryProfile` TypedDict bị xóa hoàn toàn; `main()` in thẳng `builder(x)`.

**Why:** Profile chỉ hữu ích khi cần **replay** — tức là biết tham số nào đã được rút để tái tạo lại lời gọi. Ở tầng hiện tại chưa có bước replay nào, nên profile là dữ liệu dư thừa: chuỗi FASTEXPR đã chứa đủ thông tin để đọc lại tham số bằng `parse`, và thêm `category`/`name`/`config` chỉ là nhân bản thứ đã biết từ tên hàm.

Điểm đáng lưu: đây là **sự phân tách trách nhiệm** đúng — `MATRIX_BINARY` vẫn trả profile (`Functions/operators.py`), vì tầng đó có `MatrixBinary.get(name, x, y)` với chữ ký đồng nhất cho mọi operator nên profile là điều kiện cần để dispatch. Ngược lại 40 operator unary có **chữ ký khác nhau** (`abs(x)` vs `ts_mean(x, d)` vs `kth_element(x, d, k)`), nên chỉ cần một `def` riêng mỗi operator — và chỉ cần trả về thứ duy nhất mà caller dùng.

**Bài học (về refactor bằng script):** lần đầu tôi chuyển đổi 40 chỗ bằng script parse-string. Script **làm hỏng 6 hàm** có f-string chứa quote lồng nhau (`f'kth_element({x}, {d}, {k}, ignore = "NaN")'`, `f'ts_quantile(..., driver = "{driver}")'`, `f"... dense = {'true' if dense else 'false'}"`) — parser string-aware của tôi không phân biệt được quote của f-string với quote của biểu thức, nên 6 hàm bị cắt thành `return` rỗng. Ruff **không bắt** (`return` rỗng là code hợp lệ về cú pháp) và `py_compile` cũng không bắt — chỉ đến khi chạy verify "return type là `str`" mới lộ ra 6/40 hỏng. Bài học: refactor hàng loạt bằng script **phải** có một assert hậu kiểm về *kiểu trả về*, không chỉ lint + compile.

**Reusable in:** mọi builder sinh expression — nếu chưa có bước replay thì trả chuỗi; khi nào thực sự cần replay (log tham số đã rút, regenerate expression từ seed) mới nâng lên profile.

**Sentiment:** 7 — ranh giới "profile chỉ đáng có khi đã có bước replay" là nguyên tắc reviewer sẽ hỏi ("tại sao bạn bỏ thông tin replay?"), và câu trả lời là chưa tới lúc dùng.

## 2026-10-24T15:29:51Z | code-technique | score: 7

**Where:** `Functions/operators.py` — `class FloatSampler` (đặt ngay sau `IntegerSampler`)

**Pattern:** Float sampler **song song cấu trúc** với `IntegerSampler`: cùng `BUCKET_FRACTIONS` / `BUCKET_COUNT` (tái dùng trực tiếp từ `IntegerSampler` qua `BUCKET_FRACTIONS = IntegerSampler.BUCKET_FRACTIONS`, không copy giá trị), cùng cặp `seed` / `stream`, cùng `distribution="uniform" | "balanced"`, cùng `rng = np.random.default_rng([seed, stream])`.

**Khác biệt cần thiết so với `IntegerSampler`:**
- Range là **liên tục** nên `buckets()` dùng **span** (`count = max - min`) thay vì **số phần tử** (`count = max - min + 1`), và cut là `count * fraction` chứ không phải `round(count * fraction)` — số phần tử nguyên cần làm tròn, span thập phân thì không.
- Giá trị trả về được `round(value, 4)` → **4 chữ số sau dấu phẩy**, để FASTEXPR render ổn định giữa các lần chạy.
- `rng.uniform(lo, hi)` thay cho `rng.integers`.

**Về ranh giới bucket:** công thức chặn dưới/nhưng phải dùng `upper_bound = count * (1 - (BUCKET_COUNT - index) / BUCKET_COUNT)` — đây là ranh giới *tương đối* (phần còn lại phân bổ đều cho các bucket sau), khác `IntegerSampler` dùng `count - (BUCKET_COUNT - index)` (ranh giới *tuyệt đối* theo số phần tử). Sai chỗ này thì bucket cuối có thể bị âm.

**Vì sao dùng chung `BUCKET_FRACTIONS` thay vì copy:** copy sẽ tạo **hai nguồn sự thật** — đổi một bên thì bên kia lệch, và phân phối balanced của int và float sẽ không còn cùng hình dạng. Ràng buộc bằng tham chiếu để `IntegerSampler` và `FloatSampler` **luôn** cùng tỉ lệ.

**Reusable in:** mọi sampler thêm sau này (bool sampler, categorical sampler) — lặp lại y hệt khuôn này: `BUCKET_FRACTIONS` tham chiếu chéo, `seed`/`stream` độc lập, `round()` ở cuối để text ổn định.

**Sentiment:** 7 — khác biệt "span vs số phần tử" và "ranh giới tương đối vs tuyệt đối" là hai chỗ dễ sai im lặng; reviewer sẽ hỏi tại sao float không dùng lại logic của int.

## 2026-10-24T15:32:12Z | code-technique | score: 7

**Where:** `main.py` — `hump()` builder (dòng ~49-60), `HUMP_STREAM = 6`

**Pattern:** Gắn `FloatSampler` vào một operator float của catalog. Platform định nghĩa `hump(x, hump = 0.01)` — keyword `hump` là **float**. Builder đổi từ hằng số cứng `0.01` sang rút ngẫu nhiên trong window `[0, 3]`, với `FloatSampler.sample(seed=seed, stream=HUMP_STREAM)`.

**Vì sao tên tham số là `hump_value` chứ không phải `hump`:** `hump` đã là tên của chính operator; tham số cùng tên sẽ che mất ý nghĩa khi đọc `hump(x, hump = {hump})`. Tên `hump_value` phân biệt được *tham số* với *operator*.

**Vì sao cần `HUMP_STREAM = 6` riêng:** `FloatSampler` dùng chung `np.random.default_rng([seed, stream])` với `IntegerSampler`. Nếu để `stream=0` (mặc định) thì `hump` sẽ dùng **chung** sub-stream với các draw khác trên `stream=0` → thêm một draw mới có thể **dịch chuyển giá trị** của các draw cũ. Stream riêng giữ đúng tính chất "thêm draw không làm đổi draw cũ" mà `IntegerSampler` đã cam kết. Đã dùng `stream=6` vì `1..5` đã cấp cho window / kth_element k / winsorize std / driver / dense.

**Về `P(hump < 0.01) = 0.36%`:** đây là hệ quả trực tiếp của việc rút uniform trên `[0, 3]` — giá trị **gần 0** (gần nghĩa "không giới hạn gì") rất hiếm. Với `hump` càng nhỏ thì turnover càng **ít** bị dẹp → alpha gần như không còn tác dụng giảm turnover. Đây là điểm cần reviewer hỏi: **uniform trên [0,3] không phải phân phối tự nhiên của tham số này**, và nếu kết quả phụ thuộc vào `hump` thì nên cân nhắc log-scale hoặc range hẹp hơn quanh 0.01.

**Reusable in:** mọi operator có tham số float trong catalog — `winsorize(std)`, `normalize(limit)`, `quantile(sigma)`, `ts_target_tvr_*(target_tvr, lambda_min, lambda_max)` — cùng khuôn: `FloatSampler.sample(seed=seed, stream=<riêng>)` + tham số tường minh để override.

**Sentiment:** 7 — "stream riêng cho float" và "tên tham số tránh trùng operator" là hai chi tiết dễ bỏ sót; phân phối uniform trên [0,3] cho tham số ngưỡng là một quan sát sẽ bị hỏi khi review.

## 2026-10-24T15:37:48Z | code-technique | score: 7

**Where:** `main.py` — `kth_element()`, hằng số `KTH_ELEMENT_KS` / `KTH_ELEMENT_IGNORE`

**Pattern:** Rút `k` của `kth_element` từ `(1, d)` (rút trong **toàn bộ** cửa sổ) → `(1, 2)` (uniform trên 2 giá trị), và **buộc `ignore` bám theo `k`** qua bảng tra `KTH_ELEMENT_IGNORE = {1: "NaN", 2: "NaN 0"}`.

**Vì sao `ignore` phải là hàm của `k` chứ không phải hằng số:** theo mô tả của platform, `k=1` bỏ qua NaN, còn `k=2` lấy "giá trị khác 0 và khác NaN gần nhất thứ hai" → phải bỏ qua **cả** 0 lẫn NaN. Nếu giữ `ignore = "NaN"` cố định, `k=2` sẽ trả về giá trị 0 — trái với ý nghĩa mà tham số khai báo. Vì vậy `ignore` được **tính từ** `k` sau khi rút, không phải hằng số viết cứng trong f-string.

**Vì sao `(1, 2)` chứ không phải `(1, d)`:** trước đây `k` được rút trong `1..d` với lý do "k chỉ số vào cửa sổ vừa đọc". Nhưng mô tả của platform chỉ định nghĩa **đúng hai** ý nghĩa cho `k` (1 = backfill NaN, 2 = second most recent non-zero non-NaN). Một `k` lớn hơn sẽ chỉ số vào cửa sổ vừa đọc nhưng **không có ý nghĩa đã được tài liệu hoá** → không có "domain đã biết" để lấy mẫu (cùng lập luận đã dùng cho `ts_returns`' `mode`). Rút trên 2 giá trị = uniform, `P(k=1) ≈ P(k=2) ≈ 50%`.

**Hệ quả cần lưu ý (`k > d`):** vì `k` không còn bị ràng buộc bởi `d`, trường hợp `k=2, d=1` là hợp lệ về hình thức nhưng "giá trị khác 0 và khác NaN thứ hai trong 1 ngày" không tồn tại. Đo trên 50k mẫu: **0.246%** rơi vào `k > d`, và **toàn bộ** đều là `d=1 & k=2` (`d==1` chiếm 0.446%). Trước đây (rút trong `1..d`) tỉ lệ này là **0%** — đây là một thay đổi hành vi đã đo được, không phải suy đoán.

**Reusable in:** mọi operator có tham số *phụ thuộc lẫn nhau* — bảng tra là cách rẻ nhất để buộc chúng nhất quán; đặc biệt khi một tham số là **hàm** của tham số kia (`ignore` là hàm của `k`).

**Sentiment:** 7 — "k độc lập với d làm sinh trường hợp k>d ở 0.246%" là thay đổi hành vi đo được mà reviewer sẽ hỏi ("k có luôn ≤ d không?").

## 2026-10-24T15:40:56Z | code-technique | score: 7

**Where:** `main.py` — `normalize()`, hằng số `NORMALIZE_USE_STD_STREAM = 7`, `NORMALIZE_LIMIT_STREAM = 8`

**Pattern:** Operator có **hai tham số khác kiểu** → mỗi tham số một entropy stream riêng. `useStd` là bool nên rút bằng `IntegerSampler.sample((0, 1), ...)` rồi ép `bool(...)` (giống `ts_decay_linear`'s `dense`); `limit` là float nên rút bằng `FloatSampler.sample(seed=..., stream=...)` trên window `[0, 3]`. Platform định nghĩa `normalize(x, useStd = false, limit = 0.0)`.

**Vì sao `limit` phải dùng stream riêng (8) chứ không dùng chung stream 7 với `useStd`:** cả hai đều là draw từ `default_rng([seed, stream])`. Dùng chung stream thì `useStd` sẽ **tiêu tốn entropy** trước `limit`, và giá trị `limit` sẽ phụ thuộc vào giá trị `useStd` — hai tham số **không độc lập**, và thêm/bớt một draw sẽ dịch chuyển draw kia. Tách stream giữ được tính chất "thêm draw không làm đổi draw cũ".

**Về khoảng giá trị của `limit` — điểm khoa học cần chú ý:** `limit` là **bán kính clamp** của kết quả đã chuẩn hoá, nên nó **không cùng đơn vị** giữa hai chế độ:
- `useStd=true` → kết quả tính bằng **sigma**, nên `limit=0.05` là "chỉ giữ 0.05 sigma".
- `useStd=false` → kết quả vẫn tính bằng **đơn vị gốc của x** (chỉ trừ mean), nên `limit=0.05` là "0.05 đơn vị của x".

Hệ quả: **cùng một ngưỡng `limit` có ý nghĩa khác hẳn** giữa hai chế độ, và với field có đơn vị lớn (vd. `compustat_liquidity_metric_two`) thì `limit` uniform trên `[0,3]` gần như **không clamp gì cả** → `useStd=false` + `limit` nhỏ coi như vô nghĩa. Đo trên 100k mẫu: `P(limit < 0.1) = 3.28%`, `P(limit < 0.25) = 8.29%`. Trước đây `limit` **cố định 0.0** (nghĩa là **không clamp**, vì clamp về 0 sẽ xoá hết tín hiệu) → hành vi đã đổi, và theo hướng *bớt* nhất quán với việc chuẩn hoá.

**Reusable in:** `rank(rate=2)`, `scale(scale/longscale/shortscale=1)`, `tail(lower/upper/newval=0)`, `quantile(sigma=1.0)` — cùng khuôn "mỗi tham số float một stream riêng, rút bằng `FloatSampler`".

**Sentiment:** 7 — "cùng `limit` nhưng khác đơn vị giữa `useStd=true/false`" là điểm reviewer sẽ hỏi; và việc `limit` cố định 0.0 thực ra là *tắt* clamp chứ không phải "clamp về 0" — dễ hiểu sai.

## 2026-10-24T19:41:06Z | code-technique | score: 8

**Where:** `Functions/operators.py` — `OperatorProfile`, tất cả builder methods trong `MatrixBinary` và `MatrixUnary`

**Pattern:** Builders return `tuple[str, OperatorProfile]` thay vì chỉ `str`

**Why:** Trước đây builders chỉ return expression string, config parameters (seed/stream/distribution) không được lưu lại → không thể replay hay audit được cách một expression được sinh ra. Giờ `OperatorProfile` chứa 3 keys: `category` (e.g. "MATRIX_BINARY"), `name` (e.g. "ts_corr"), `config` (dict chứa tất cả parameters đã sample: `seed`, `stream`, `d`, `method`, v.v.). Caller unpack `expression, profile = MatrixBinary.get(...)` — expression dùng để submit lên BRAIN API, profile dùng để ghi log/replay/debug. Tách rời expression rendering (ready-to-run FASTEXPR) khỏi metadata (reproducibility audit trail).

**Reusable in:** Tất cả operator categories còn lại (`MATRIX_GENERATED`, `VARIADIC`, `SELECT`, `BOOLEAN`, `VECTOR`, `GROUP`, `GROUPING`) — cùng signature `get(...) -> tuple[str, OperatorProfile]`. Đặc biệt quan trọng cho pipeline tự động sinh alpha: mỗi alpha phải ghi lại toàn bộ config để có thể reproduce kết quả hoặc debug khi performance sụt.

**Sentiment:** 8 — ảnh hưởng kiến trúc cross-cutting, reviewer sẽ hỏi tại sao không nhét `expression` vào trong `profile` (câu trả lời: expression là artifact phái sinh, không phải config; và caller thường chỉ cần expression để submit, không cần profile cho đến lúc cần audit).

## 2026-10-25T03:21:00Z | code-technique | score: 9

**Where:** `Functions/operators.py:695-1335` — tất cả 31 MatrixUnary builders có sampled parameters

**Pattern:** Signature nhận sampled parameters như optional arguments, chỉ sample khi `param is None`

**Why:** Trước đây signature chỉ nhận `x: str` và `distribution`, các parameters như `d`, `k`, `hump`, `std` được sample bên trong function → `config` lưu `{"d": 238}` nhưng không có cách nào gọi lại builder với `d=238` để tái tạo bit-exact expression. Pattern mới:

```python
def last_diff_value(x: str, d: int | None = None, *, distribution="balanced"):
    if d is None:
        d = IntegerSampler.sample(WINDOW_DAYS, None, WINDOW_STREAM, distribution)
    return _profile("last_diff_value", {"d": d}, f"last_diff_value({x}, {d})")
```

Giờ caller có thể:
1. **Random sampling:** `expr, profile = MatrixUnary.last_diff_value("field_a")` → profile chứa `{"d": 238}`
2. **Bit-exact replay:** `expr2, _ = MatrixUnary.last_diff_value("field_a", d=238)` → `expr2 == expr`

Điều này giữ nguyên 100% seed logic (không thay đổi gì về `IntegerSampler.sample` hay stream constants), chỉ thay đổi **interface** để caller có thể bypass sampling và truyền giá trị cụ thể vào.

**Reusable in:** Mọi builder trong `MATRIX_GENERATED`, `VARIADIC`, `SELECT`, `BOOLEAN`, `VECTOR`, `GROUP`, `GROUPING` categories — cùng pattern: parameters đã sample phải xuất hiện trong signature như optional arguments. Đây là foundation cho:
- **Audit trail:** lưu `config` vào database/log, replay bất cứ lúc nào.
- **A/B testing:** so sánh hai alpha chỉ khác một parameter (e.g. `d=21` vs `d=63`).
- **Publication-grade reproducibility:** paper appendix có thể liệt kê exact config của mọi alpha.

**Sentiment:** 9 — quyết định này ảnh hưởng reproducibility của toàn bộ alpha generation pipeline. Không có pattern này thì không thể tái tạo bit-exact expression từ `config`, phá vỡ audit trail requirement của research codebase.

## 2026-10-25T17:31:47Z | code-technique | score: 4

**Where:** `main.py` — `trade_when`

**Pattern:** tham số ngẫu nhiên là `None` mặc định, chỉ rút khi caller không truyền; mỗi draw một stream cố định (1 đến 4).

**Why:** cho phép replay một alpha cụ thể bằng cách truyền lại config, và rút phần còn lại ngẫu nhiên. Stream cố định nên thêm draw mới không làm lệch giá trị của draw cũ.

**Reusable in:** mọi builder có tham số rút ngẫu nhiên (`MatrixBinary.if_else`).

**Sentiment:** 4 — pattern đã có trong codebase.

## 2026-10-25T17:36:11Z | code-technique | score: 4

**Where:** `main.py` — `trade_when`

**Pattern:** một tham số `distribution` keyword-only điều khiển toàn bộ draw của builder, truyền xuống từng `FloatSampler.sample` / `IntegerSampler.sample`.

**Why:** caller chọn uniform hoặc balanced một lần cho cả template, thay vì mỗi draw hardcode riêng.

**Reusable in:** mọi builder mới có tham số rút ngẫu nhiên.

**Sentiment:** 4 — giống `if_else`.

## 2026-10-25T17:39:06Z | code-technique | score: 3

**Where:** `Functions/operators.py` — `MatrixUnary.trade_when`

**Pattern:** builder chuyển từ `main.py` sang class operator; stream 1 đến 4 của `trade_when` trùng số với `WINDOW_STREAM=1`... nhưng không xung đột vì mỗi lần gọi dùng `seed=None` (entropy mới).

**Why:** nếu sau này truyền seed cố định vào `trade_when`, các stream 1 đến 4 nên chuyển thành hằng số `*_STREAM` riêng như các builder còn lại.

**Reusable in:** các builder khác của `MatrixUnary`.

**Sentiment:** 3 — ghi chú nhỏ.

## 2026-10-25T17:41:43Z | code-technique | score: 4

**Where:** `Functions/operators.py` — `MatrixUnary.get`, `MatrixUnary.trade_when`

**Pattern:** thêm builder mới vào `MatrixUnary` cần 3 chỗ: dict `builders`, tuple tên nhận `distribution` trong `get`, và trả `_profile(...)` để config replay được.

**Why:** thiếu chỗ nào là `get` lỗi `KeyError` hoặc `TypeError` (builder bị gọi với/không có `distribution`).

**Reusable in:** mọi builder mới của `MatrixUnary`.

**Sentiment:** 4 — checklist nhỏ.

## 2026-10-25T18:15:27Z | code-technique | score: 6

**Where:** `Functions/data.py` — `CatalogBuilder.sample_field_ids`

**Pattern:** lọc vị trí trước (`np.isin` trên cột), rồi `positions[rng.choice(positions.size, ...)]`; theme rỗng thì `positions = np.arange(n_rows)`.

**Why:** Với theme rỗng `positions[idx] == idx` và `choice(n_rows)` cùng seed ra cùng chỉ số, nên giữ bit-exact với bản trước khi có theme (đã kiểm seed 42). `ScopeCache.column` chỉ giải nén cột `categoryid`.

**Reusable in:** mọi bộ lọc theo cột khác (datasetid, subcategoryid) trước khi rút mẫu.

**Sentiment:** 6 — không phá tái lập khi thêm bộ lọc.

## 2026-10-26T15:50:38Z | code-technique | score: 6

**Where:** `main.py` — block "Pool in {scope} (theme=...)"

**Pattern:** đo pool size trước khi random bằng `np.isin(snapshot.column("categoryid"), THEME).sum()`, mở/đóng `ScopeCache` theo từng type.

**Why:** `sample_field_ids` trả về list rỗng khi pool của type đó không có field nào khớp theme → `[0]` ném `IndexError` ở chỗ không liên quan. Đếm pool trước biết ngay type nào không dùng được, và in ra pool size để đánh giá tính đại diện của draw.

**Reusable in:** mọi lần bổ sung bộ lọc trước khi rút mẫu (datasetid, subcategoryid) — cùng cách đếm trên cột rồi mới draw.

**Sentiment:** 6 — chặn lỗi im lặng, pattern tái dùng được.

## 2026-10-26T15:53:29Z | code-technique | score: 6

**Where:** `main.py` — vòng for bốc N field type

**Pattern:** dùng bảng `pools` đo trước số field theo type để làm guard cho mọi lần pick: type rỗng thì fallback sang type còn lại, cả hai rỗng thì print + break.

**Why:** `sample_field_ids` trả về list rỗng khi pool rỗng → `[0]` ném IndexError ở ngữ cảnh không liên quan (không biết vì sao field không tồn tại). Guard bằng pool size biến lỗi thành thông báo có kiến thức.

**Reusable in:** mọi bước rút mẫu từ pool hữu hạn (field, operator, dataset) — đo pool trước, pick sau.

**Sentiment:** 6 — chặn IndexError im lặng, tái dùng được.

## 2026-10-26T17:39:16Z | code-technique | score: 8

**Where:** `/tmp/proto/test_builder.py` — probe `get()` vs builder trực tiếp của cả 4 class trong `Functions/operators.py`.

**Pattern:** để replay được `profile["config"]`, phải gọi **builder trực tiếp** (`MatrixUnary.ts_mean(x, d=...)`), không phải `get()`. `get()` có signature cứng `(name, x, y, *, distribution)` nên không forward `**kwargs` ⇒ `get(name, *args, **config)` raise TypeError. Ngược lại builder trực tiếp vẫn hỏng ở 5 chỗ vì tên key trong `config` không khớp tên tham số: `kth_element` (`ignore` không có tham số), `normalize` (`useStd` vs `use_std`), `scale` (`scale` vs `book_size`), `ts_backfill` (`lookback` vs `d`), `group_backfill` (`std` bị format thành string `"{std:.2f}"` nên replay crash với `ValueError: Unknown format code 'f'`). Ngoài ra 5 operator `group_*` có **MISMATCH** (không raise, nhưng ra expression khác): `config` không lưu 3 tham số `bucket_range` nên `min`/`max`/`step` của `bucket` được bốc lại.

**Why:** `Docs/all-operators.md` §8.2 nói "bit-exact replay từ config (recommended)" — đo thực tế thì đường đó hỏng cho 41/68 builder. Đây là loại bug im lặng: expression vẫn chạy, chỉ hỏng lúc cần tái tạo.

**Reusable in:** bất kỳ chỗ nào `config` được dùng làm "replay key" — phải kiểm tra `inspect.signature(builder)` khớp key của `config` trước, hoặc lưu `config` theo đúng tên tham số của builder.

**Sentiment:** 8 — tài liệu hứa một khả năng mà code không có; reviewer sẽ yêu cầu chứng minh reproducibility.

## 2026-10-26T17:50:41Z | code-technique | score: 8

**Where:** `main.py` — `build_expression()` và các pool `BINARY_POOL` / `UNARY_POOL` / `VECTOR_POOL` / `GROUP_POOL`.

**Pattern:** đếm lời gọi builder để kiểm tra cấu trúc cây, thay vì đếm bằng regex trên chuỗi expression. Regex không phân biệt được "node của cây" với "operator mà operator tự nhúng" (`MatrixUnary.sqrt` render ra `if_else`, `Group` mode 3–5 render ra `bucket(rank(x))`), nên đếm sai tới 25/480 cây. Monkey-patch `MatrixBinary.get` / `MatrixUnary.get` / `Group.get` / `Vector.get` bằng hàm đếm, rồi assert count ⇒ kết quả 0 vi phạm trên 480 cây.

**Why:** Cấu trúc cây là thứ quyết định "layer" mà user hỏi, và nó phải đúng thì mọi đo đạc phía sau mới có nghĩa. Đếm bằng chuỗi là loại kiểmm tra cho kết quả sai.

**Reusable in:** bất kỳ cây biểu thức nào dựng bằng cách ghép chuỗi — kiểm tra số node bằng cách đếm lời gọi hàm dựng, không bằng cách đếm ký tự.

**Sentiment:** 8 — phát hiện ra lỗi trong chính cách kiểmm tra; reviewer sẽ hỏi "làm sao biết cây đúng?".

## 2026-10-26T18:05:00Z | code-technique | score: 8

**Where:** `main.py` — `draw_fields()`.

**Pattern:** khi một pool rỗng và phải fallback sang pool khác, **phải ghi lại type theo nguồn id thực sự**, không phải theo type đã định bốc. Ở đây type quyết định lá có cần bọc `vec_*` hay không; ghi sai type ⇒ `vec_*` bọc một matrix field ⇒ expression sai chỉ lộ ra lúc simulate.

**Why:** Bản đầu đổi `drawn_ids["VECTOR"] = drawn_ids["MATRIX"]` mà vẫn ghi `field_types.append("VECTOR")` ⇒ một field matrix bị bọc `vec_avg(...)`, tức là toán học sai (vec trên field scalar) chứ không chỉ là lỗi cú pháp.

**Reusable in:** mọi fallback pool-đến-pool: gắn nhãn theo nguồn, không theo ý định.

**Sentiment:** 8 — loại bug âm thầm chỉ lộ ra ở bước simulate, tốn slot; reviewer sẽ hỏi về type correctness.

## 2026-10-26T18:18:52Z | code-technique | score: 7

**Where:** `main.py` — `draw_fields()`, phân bổ field giữa MATRIX và VECTOR.

**Pattern:** khi hai pool field phải cùng thoả một yêu cầu số lượng, **coi chúng là một pool duy nhất**, không phải hai lần `min(n, pool)` độc lập. Cấp phần theo draw trước, chặn bởi kích thước pool, rồi chuyển phần thiếu sang pool còn dư.

**Why:** `min(n, M) + min(n, V)` nhỏ hơn `n` khi cả hai pool cùng nhỏ hơn n. Ở `DEU_0_TOP500` (M=10, V=10) với n=24 chỉ ra 20 field ⇒ expression có 20 lá thay vì 24 ⇒ số binary op là 19 thay vì 23 ⇒ cây lệch khỏi thiết kế.

**Reusable in:** mọi bài toán chia ngân sách lấy mẫu từ nhiều pool với tổng cố định.

**Sentiment:** 7 — lỗi im lặng, chỉ lộ ra khi sweep nhiều scope với theme hẹp.

## 2026-10-26T18:33:18Z | code-technique | score: 7

**Where:** `main.py` — `build_expression()` và `draw_fields()`.

**Pattern:** dùng `IntegerSampler.sample(value_range)` (seed mặc định `None`) cho **mọi** quyết định ngẫu nhiên: chọn operator, chọn số wrapper, coin-flip group/unary, thứ tự ghép cặp, loại field. Không giữ `np.random.Generator` song song.

**Why:** dự án đã có sẵn `Functions/random.py` với `IntegerSampler` / `FloatSampler`; giữ `np.random` ở `main.py` tạo ra hai hệ thống entropy cùng tồn tại, khó kiểm soát khi tái lập. Với `seed=None` mỗi draw lấy fresh entropy từ OS CSPRNG ⇒ mỗi alpha độc lập, không cần stream/scheme nào.

**Reusable in:** mọi entry point sinh alpha. Lưu ý: `FloatSampler.sample` mặc định `distribution="balanced"` (chia 5 bucket) nên **không** dùng nó cho coin-flip 50/50 — dùng `IntegerSampler.sample((0, 1))`.

**Bẫy khi verify:** không thể đếm cây bằng substring trên text FASTEXPR — `if_else` render thêm `multiply`/`ts_rank` bên trong, `tail` lặp lại field id. Phải instrument ở mức lời gọi builder (`MatrixBinary.get` v.v.) thì mới đếm đúng n-1 binary op và n field id lá.

**Sentiment:** 7 — reviewer sẽ hỏi vì sao có hai hệ thống random trong cùng một dự án.

## 2026-10-26T19:21:07Z | code-technique | score: 8

**Where:** `main.py` — `operator_count()`, `PLATFORM_OPERATOR_LIMIT`, `build_expression()`.

**Pattern:** đếm operator của một FASTEXPR bằng **regex trên text đã render** (`\b([A-Za-z_][A-Za-z0-9_]*)\s*\(`), không phải bằng cách đếm lời gọi builder.

**Why:** một số operator **render argument nhiều lần** — `sqrt` 4 lần, `trade_when` 3 lần, `if_else` 2 lần (mỗi argument), group 2 lần (qua `bucket(rank(x))`). Nên cost của subtree bị toán tử cha **nhân**, không cộng: `sqrt^3(f)` = 5 + 4·25 = 105, đúng bằng con số platform báo lỗi. Đếm bằng lời gọi builder sẽ **undercount** và bỏ sót lỗi.

**Reusable in:** mọi bước validate expression trước khi gửi platform. Cùng bài học: khi một builder sinh template có lặp, phải kiểm budget trên **text render**, không trên số lời gọi.

**Bẫy khi verify:** substring count trên text FASTEXPR không đáng tin cho *cấu trúc* (`if_else` render thêm `multiply`/`ts_rank` bên trong, `tail` lặp lại field id) — nhưng nó **đúng** cho *số operator*, vì mỗi operator đều là một lời gọi có ngoặc mở.

## 2026-10-27T15:23:08Z | code-technique | score: 4

**Where:** main.py ExpressionBuilder (draw_fields, build, _tree, _leaf, _join_round)

**Pattern:** Class holds scope-derived state (pools, group_id, fallback levels) once; per-N methods stay stateless.

**Why:** The old code recomputed pool sizes in main() and passed group_id and 6 pool arguments through build_expression/_build_tree. Verified with 30 draws x 6 scopes x N in (1,2,3,6,12,24): operator count never exceeds 64.

**Reusable in:** any later stage that needs the same scope/theme pools.

**Sentiment:** 4 — obvious in hindsight.

## 2026-10-27T16:59:10Z | code-technique | score: 6 | tag: scale-fix

**Tags:** scale-fix

**Where:** main.py ExpressionBuilder._join_round, SCALE_SENSITIVE, JOIN_COST

**Pattern:** rank-wrap operands at join time, charge the wrapper cost to the operator budget

**Why:** The operator budget (64) is checked on rendered text, so extra rank() calls must be counted up front (JOIN_COST=3 per join: 1 binary + 2 rank) or build() would only discover overflow after rendering.

**Reusable in:** any builder step that inserts fixed operators around operands.

**Sentiment:** 6 — small, but the budget accounting is easy to forget.

## 2026-10-27T18:53:25Z | code-technique | score: 7 | tag: composition-layer

**Tags:** composition-layer

**Where:** `main.py` `ExpressionBuilder._post_wrap`, `_variadic_join`, `_join_round`

**Pattern:** hai lever composition-layer nằm ngoài tầng lá — wrapper phủ lên cây đã join, và join nhiều operand trong một lệnh gọi

**Why:** tầng lá chỉ bọc từng field riêng lẻ, nên giá trị đã kết hợp của hai field trở lên không bao giờ tới được một phép biến đổi. Đo trên 4000 mẫu N=3: 21/50 operator unary+group không bao giờ xuất hiện ở vị trí trên join; `rank` chiếm 1370 lần vì scale-fix bọc rank mọi operand của join. Lever `_post_wrap` nâng tỉ lệ expression có transform-above-join từ 56.3% lên 85.7%.

**Reusable in:** bất kỳ builder nào ghép cây từ nhiều field — ngân sách operator tính trên text render, nên phải charge wrapper sau khi biết cây còn dư bao nhiêu chỗ.

**Sentiment:** 7 — reviewer sẽ hỏi vì sao `ts_zscore(add(a, b))` không bao giờ xuất hiện; câu trả lời nằm trong kiến trúc tầng.

## 2026-10-28T16:12:17Z | code-technique | score: 7 | tag: field-metadata

**Tags:** field-metadata

**Where:** `Functions/data.py` `CatalogBuilder.sample_field_ids`, `main.py` `ExpressionBuilder.draw_fields` / `_sample` / `__init__`

**Pattern:** trả DataFrame đầy đủ cột thay vì list id, và giữ frame theo đúng thứ tự draw

**Why:** archive đã lưu 19 cột metadata nhưng `take(picked, columns=["fieldid"])` chỉ lấy 1 cột rồi `.tolist()` — phần metadata bị bỏ dù đã nằm trên đĩa. `draw_fields` phải pop từ `queues[source]` theo thứ tự draw, nên frame phải được slice theo vị trí (`iloc[0]`, `iloc[1:]`), không phải `pd.concat` (concat gom theo type, sai thứ tự). Với DataFrame, `self._sample("GROUP", 1)[0]` không còn là id mà là Series theo cột → phải đổi thành `["fieldid"].iloc[0]`.

**Reusable in:** bất kỳ hàm nào sample từ cache theo vị trí rồi trả về cho call site — giữ quan hệ thứ tự giữa giá trị và metadata là điều kiện tiên quyết.

**Sentiment:** 7 — ba chỗ `[0]` trở thành Series/Series-of-Series là bug im lặng, reviewer sẽ hỏi tại sao đổi kiểu trả về mà không sửa hết call site.

## 2026-10-28T17:05:57Z | code-technique | score: 8 | tag: expression-profile

**Tags:** expression-profile

**Where:** `main.py` `ExpressionBuilder.build` / `_profile` / `_walk` / `_rank_wrap`, `Functions/operators.py` `OperatorProfile` + `implicit_profile`

**Pattern:** profile ba tầng — `data` (field + metadata), `levels` (operator name → list of calls), `counts` — dựng bằng cách đi trên cây đã build, không parse text render

**Why:** profile phải mô tả đúng cái đã dựng thì mới phân tích được. Ba điểm dễ sai: (1) operator nội bộ — `group_*` mode 3/4/5 kéo theo `densify`/`bucket`/`group_cartesian_product`, `sqrt` kéo theo `if_else`/`sign`/`abs`, `trade_when` kéo theo `ts_rank`/`ts_zscore`/`abs`, `if_else` kéo theo `ts_rank` — không có trong `get()` nên phải khai báo tường minh qua `implicit`; (2) operator **lặp argument** (`group_*` mode 3+ nhúng lại `x` vào `bucket(rank(x))`, `trade_when` 3x) nên đếm *rendered occurrence* trong text ≠ đếm *logical call* trong profile — invariant đúng là coverage hai chiều theo **tên operator**, không phải theo số lần; (3) `rank` của scale-fix là scaffolding bắt buộc để join, không phải lựa chọn của generator ⇒ loại khỏi profile, nếu không nó chiếm ~40% số lượt operator và drown phần còn lại.

**Reusable in:** bất kỳ hệ thống nào sinh rồi giải thích một biểu thức — nguyên tắc "profile đếm cái đã dựng, text đếm cái đã render, hai thứ khác nhau ở operator lặp argument" áp dụng cho mọi IR/query planner.

**Sentiment:** 8 — invariant phải chọn đúng mới verify được; đếm số lần sẽ báo động giả âm và che mất lỗi thật.
