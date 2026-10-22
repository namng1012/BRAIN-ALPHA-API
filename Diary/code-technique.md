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
