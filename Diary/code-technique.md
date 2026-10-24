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
