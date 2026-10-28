# Hướng thử nghiệm: làm phong phú FASTEXPR khi BRAIN là black box

**Trạng thái: ĐANG THỬ NGHIỆM**

Tài liệu này ghi lại các hướng suy nghĩ ban đầu, không phải đặc tả đã chốt hay kết quả thực nghiệm. Chưa có implementation nào được đề xuất ở đây.

## 1. Bài toán và điểm mù

Expression được tạo trong dự án, nhưng cách BRAIN thực thi toàn bộ FASTEXPR và tính kết quả mô phỏng chưa được tái tạo độc lập. Ta có thể quan sát kết quả do platform trả về khi submit, nhưng hiện chưa có local oracle tương đương để tính cùng kết quả.

Vì vậy, các phương pháp cần reward tính được cục bộ (ví dụ RL policy được train bằng loss/reward từ IC hoặc Sharpe) chưa có điều kiện để áp dụng một cách kiểm chứng được. Việc thử trên platform có thể cung cấp quan sát thực nghiệm, nhưng chi phí, quota và tính chất black-box khiến nó không tương đương với training loop có reward rẻ và liên tục.

Đây không phải bằng chứng rằng mọi nghiên cứu đều chỉ là “thử và sai”. Có thể nghiên cứu và xác minh các thuộc tính của **bộ sinh** (syntax, số operator, cấu trúc, quy tắc đại số có điều kiện), đồng thời ghi nhận kết quả platform như quan sát black-box. Nhưng các thuộc tính đó không tự chứng minh expression có alpha tốt hoặc BRAIN áp dụng chúng theo cùng semantics.

## 2. Mục tiêu hẹp: giữ Algebraic Simplification, mở rộng ngoài binary tree

Ý tưởng ban đầu là tránh để cấu trúc expression bị đồng nhất thành cây nhị phân thuần, đồng thời giữ tiêu chí Algebraic Simplification. Đây mới là hướng khảo sát; không mặc định rằng cấu trúc phức tạp hơn tốt hơn, hay rằng số toán hạng lớn hơn tạo ra tín hiệu tốt hơn.

### 2.1 Kết quả đo: hình dạng đã bão hòa, vocabulary thì chưa

Đo trên generator hiện tại (`ExpressionBuilder`), 8000 mẫu cho mỗi cấu hình:

| Metric | N=2 | N=3 | N=4 | N=6 |
|---|---|---|---|---|
| Structure (bỏ mọi số) | 6515 | 7857 | 7991 | 8000 |
| Topology family | 1678 | 2860 | 2986 | 3000 |
| Binding (field nào đi với field nào) | 32 | 85 | 180 | — |
| Collapse theo commutativity | 0.2% | 0.1% | 0.0% | — |

Kết luận:

- **Structure bão hòa.** 8000/8000 ở N=6 là combinatorics thuần (40 operator × 84 field × số cách xếp), không phải diversity có ý nghĩa. Thêm hình dạng cây không mở được operator mới.
- **Commutativity-normalization gần như không collapse** (0.1%). Dedupe theo canonicalization không phải nút thắt.
- **Binding thấp và đây mới là nút thắt.** Mỗi field chỉ xuất hiện đúng một lần, nên `ts_delta(f, 5) - ts_mean(f, 20)` — idiom alpha kinh điển — không bao giờ sinh ra được. Thử bật reuse đo được: gain cấu trúc ~0, và sinh case tự triệt tiêu (`rank(f) - rank(f)` = 0) nếu không ràng buộc transform phải khác nhau. Đã bỏ hướng này.
- **21/50 operator unary+group chưa bao giờ xuất hiện ở vị trí trên join** (đo trên 4000 mẫu N=3). `rank` chiếm 1370/4000 vì scale-fix bọc `rank` mọi operand của join, đẩy các operator khác hết xuống tầng lá.

Cơ chế: tầng lá chỉ bọc từng field riêng lẻ, nên **giá trị đã kết hợp của hai field trở lên không bao giờ tới được một phép biến đổi**. Đó là lỗ hổng cấu trúc, không phải hạn chế của vocabulary.

### 2.2 Hai lever composition-layer đã triển khai

Cả hai nằm ngoài primitive operator — không đổi quy tắc của bất kỳ operator nào.

**Lever 1 — post-join wrapper** (`ExpressionBuilder._post_wrap`): 0..2 transform phủ lên cây đã join. Mở đúng vị trí mà tầng lá không với tới.

**Lever 2 — VARIADIC join** (`ExpressionBuilder._variadic_join`): `max`/`min` n-ary thay một chuỗi join nhị phân. Platform có sẵn hai operator này (bucket VARIADIC), dự án chưa có builder → thêm class `Variadic` trong `Functions/operators.py`.

Hiệu quả đo được (3000 mẫu, mean operator count):

| Cấu hình | N=3 | N=6 | expr có transform-above-join (N=3) |
|---|---|---|---|
| Cũ (binary only, không post-wrap) | 14.2 | 28.7 | 56.3% |
| + variadic | 13.1 | 26.4 | — |
| + post-wrap | 20.5 | 34.4 | 85.7% |
| + cả hai | 20.0 | 32.2 | — |

Hai lever có tính chất **đối lập về ngân sách**: post-wrap tiêu operator, variadic tiết kiệm operator (một lệnh `max(a,b,c)` tốn 1 operator thay vì 2 join nhị phân). Dùng cả hai thì ngân sách dành cho biến đổi có ý nghĩa rộng hơn.

### 2.3 Operator chưa dùng

| Nhóm | Số | Vì sao chưa dùng |
|---|---|---|
| BOOLEAN | 10 | Phần lớn là so sánh **infix** (`input1 > input2`), không phải function call. `OPERATOR_CALL` chỉ match function call → ngân sách operator sẽ đếm thiếu. Cần sửa bộ đếm trước khi dùng. |
| `max`, `min` | 2 | Đã thêm builder (lever 2). |
| `divide`, `power` | 2 | Đã có builder nhưng bị loại khỏi pool có chủ ý (`divide` raise khi mẫu bằng 0; `power` mất dấu với số mũ không nguyên). |
| `ts_step` | 1 | Không nhận matrix field nào — không dùng được trong cấu trúc cây hiện tại. |

Không còn thiếu `vec_*`: cả 7 operator đó xuất hiện bình thường khi pool có VECTOR field. (Một lần đo sai trước đó ép toàn bộ field là MATRIX.)

Các trục có thể khảo sát mà không cần huấn luyện RL:

- **Hình dạng cây:** cân bằng, lệch có kiểm soát, hoặc ghép theo nhóm; so sánh cấu trúc trong cùng ngân sách operator.
- **Độ sâu và phép biến đổi unary:** khảo sát các chuỗi operator trên từng operand trước khi kết hợp. Simplification chỉ áp dụng khi identity đúng dưới giả định đã nêu; không suy rộng từ tên operator.
- **Toán tử nhiều ngôi / template:** chỉ dùng nếu operator và cú pháp được xác nhận là được BRAIN hỗ trợ. Không tự tạo `add_all` hay operator giả định.
- **Biến thể selector/điều kiện:** có thể tạo họ expression khác binary, nhưng semantics và operator budget cần được ghi riêng; không coi chúng là đại số tương đương với phép cộng/nhân.
- **Dedupe cấu trúc:** loại expression trùng sau canonicalization cục bộ đã được chứng minh đúng. Dedupe chỉ giảm lặp trong tập ứng viên, không chứng minh các biểu thức còn lại độc lập về hành vi.

## 3. Vai trò và giới hạn của Algebraic Simplification

Algebraic Simplification có thể là ràng buộc về tính gọn, loại bỏ biểu thức dư thừa, hoặc cách chuẩn hoá representation. Nó không phải objective thay thế IC/Sharpe và không cho biết expression nào có hiệu quả dự báo.

Mỗi rewrite cần ghi rõ:

1. Identity toán học được dùng và các giả định miền/kiểu dữ liệu.
2. Có giữ nguyên semantics với NaN, missing values, ties, zero, clipping và xử lý cross-section/time-series hay không.
3. Rewrite đã được kiểm tra bằng toán học thuần, bằng local implementation có semantics khớp platform, hay chỉ là giả thuyết.

Nếu semantics của operator BRAIN chưa rõ, đánh dấu rewrite **chưa xác minh trên platform**; không áp dụng như phép biến đổi bảo toàn kết quả. Ví dụ, các tính chất hình thức của `abs` trên số thực không đủ để kết luận về toàn bộ biểu thức khi dữ liệu có NaN hoặc khi platform có quy tắc missing-value riêng.

## 4. Các hướng đánh giá khi chưa có local loss

**A. Kiểm chứng generator cục bộ:** kiểm cú pháp do builder tạo, số operator sau render, ngân sách giới hạn, loại operand/return type, và các invariant cấu trúc. Đây là đánh giá tính đúng của generator, không phải chất lượng alpha.

**B. Kiểm chứng rewrite theo tầng:** phân loại identity thành (i) đúng theo đại số thuần với điều kiện rõ ràng, (ii) cần semantics operator cụ thể, (iii) cần so sánh thực nghiệm với BRAIN. Chỉ nhóm (i) có thể xác nhận hoàn toàn mà không cần platform; nhóm còn lại phải giữ trạng thái chưa kết luận.

**C. Thử nghiệm black-box có kiểm soát:** nếu sau này submit, so sánh các họ expression theo từng cặp/nhóm với cùng scope, input fields, simulation settings và khoảng thời gian; lưu FASTEXPR nguyên văn, metadata, lỗi submit và output platform. Đây là thiết kế tương lai, chưa chốt số lượng lần chạy hay tiêu chí thống kê. Không suy ra quan hệ nhân quả từ các lần chạy khác điều kiện.

**D. Diversity thay cho training:** có thể đo diversity cú pháp/cấu trúc và loại trùng trước khi submit. Diversity này chỉ là diversity của biểu diễn; chưa biết nó tương ứng với diversity của output hay hiệu quả dự báo.

## 5. RL/GP và reward oracle

Các bài về AlphaGen/AlphaForge và genetic programming được nhắc đến trong trao đổi trước như nguồn gợi ý về cách biểu diễn/search. Việc áp dụng các thuật toán đó thường cần fitness/reward để xếp hạng ứng viên. Trong dự án hiện tại, chưa có local evaluator tương đương BRAIN và chưa có dữ liệu đủ để train reward model. Vì thế:

- Không gọi entropy/diversity heuristic là “training” nếu không có objective được tối ưu.
- Không dùng kết quả của các bài báo như bằng chứng rằng phương pháp sẽ cải thiện expression hoặc alpha trong setup này.
- Có thể dùng tree mutation/crossover như cơ chế sinh ứng viên, nhưng nếu không có fitness thì đó là search/sampling, không phải tối ưu theo hiệu năng.
- Reward model học từ kết quả platform, nếu cân nhắc sau này, sẽ là một surrogate cần kiểm tra out-of-sample và có nguy cơ sai lệch; hiện chưa đề xuất triển khai.

## 6. Câu hỏi cần bàn trước khi chọn hướng

- “Phong phú” cần đo ở đâu: cú pháp, cấu trúc toán học sau simplification, nhóm operator, hay output alpha ít tương quan?
- Simplification là điều kiện bắt buộc cho mỗi expression, hay chỉ là tiêu chí ưu tiên trong generator?
- Có thể lấy kết quả platform nào, với chi phí/quota nào, và metadata nào được lưu để tạo một tập quan sát đáng tin?
- Trước khi biết semantics cụ thể của operator, ta muốn giới hạn simplification vào các rewrite nào?
- Mục tiêu trước mắt là tạo expression hợp lệ và đa dạng hơn, hay tìm expression có performance tốt hơn? Hai mục tiêu này cần bằng chứng khác nhau.

## Tài liệu tham khảo đã tìm thấy

- AlphaForge: *A Framework to Mine and Dynamically Combine Formulaic Alpha Factors*, arXiv: [2406.18394](https://arxiv.org/abs/2406.18394). Dùng biểu diễn expression và cơ chế khai thác/kết hợp alpha; không phải bằng chứng rằng ta có thể train khi thiếu reward oracle.
- AlphaEvolve: *A Learning Framework to Discover Novel Alphas in Quantitative Investment*, ACM SIGMOD 2021, DOI: [10.1145/3448016.3457324](https://doi.org/10.1145/3448016.3457324). Nguồn tham khảo về tìm kiếm alpha và pruning; cần đọc toàn văn/phương pháp chi tiết trước khi mượn cụ thể một thủ tục.
- Genetic programming cho formulaic alpha: *Alpha Mining and Enhancing via Warm Start Genetic Programming for Quantitative Investment*, arXiv: [2412.00896](https://arxiv.org/abs/2412.00896). Nguồn gợi ý về tree search; chưa đánh giá khả năng chuyển giao sang BRAIN API của dự án.

Các tài liệu trên là điểm xuất phát để đọc, không phải xác nhận rằng thuật toán hay giả định của chúng phù hợp với dữ liệu, quota, semantics và mục tiêu hiện tại.
