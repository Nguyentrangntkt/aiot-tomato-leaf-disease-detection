# Hệ thống AIoT phát hiện bệnh lá cà chua
Hệ thống AIoT dùng để phát hiện bệnh trên lá cà chua bằng camera gắn trên ray trượt, Raspberry Pi 4 để chạy mô hình AI, ESP32 để điều khiển chuyển động và ứng dụng Flutter để cấu hình, điều khiển và theo dõi hệ thống.

Hệ thống đã được xây dựng và kiểm thử trên phần cứng thực trong quá trình thực hiện dự án ban đầu. Repository này chứa phiên bản mã nguồn đã được làm sạch và đồng bộ lại để phục vụ mục đích lưu trữ và làm portfolio. Phần cứng hiện không còn được duy trì, vì vậy phiên bản chỉnh lý cuối chưa được kiểm thử lại trên hệ thống ban đầu.

## Chức năng chính
- Cấu hình vị trí quét và số chu kỳ quét từ ứng dụng Flutter
- Điều khiển hệ thống bằng các lệnh RUN, PAUSE, RESUME và STOP
- Di chuyển camera trên ray bằng ESP32 và động cơ bước
- Phát hiện lá cà chua và phân loại Healthy, LeafMiner hoặc EarlyBlight
- Lưu trạng thái hệ thống và kết quả phát hiện lên Firebase
- Tải ảnh phát hiện bệnh lên Cloudinary
- Hiển thị trạng thái quét và lịch sử kết quả trên ứng dụng

## Kiến trúc hệ thống
Dự án gồm ba phần chính:
- `App/`: mã nguồn Flutter cho đăng nhập, cấu hình quét, điều khiển hệ thống và hiển thị kết quả
- `Pi4/`: chương trình điều phối trên Raspberry Pi, xử lý Firebase, BLE, camera, AI và tải ảnh
- `Esp32/`: firmware ESP32 cho homing, điều khiển ray, công tắc hành trình, lệnh BLE và gửi trạng thái

Luồng hoạt động:
1. Ứng dụng ghi cấu hình quét và yêu cầu điều khiển lên Firebase.
2. Raspberry Pi đọc cấu hình và gửi lệnh đến ESP32 qua BLE.
3. ESP32 di chuyển camera đến từng vị trí đã cấu hình.
4. Khi đến vị trí chụp, ESP32 gửi trạng thái `ARRIVED`.
5. Raspberry Pi chụp ảnh và chạy pipeline AI.
6. Sau khi xử lý xong, Raspberry Pi gửi lệnh `NEXT`.
7. Kết quả được lưu lên Firebase và ảnh bệnh được tải lên Cloudinary.
8. Ứng dụng đọc Firebase để hiển thị trạng thái hiện tại và lịch sử quét.

## Pipeline AI
Pipeline AI gồm ba giai đoạn:
1. Phát hiện lá cà chua
2. Phân loại Healthy hoặc Diseased
3. Phân loại LeafMiner hoặc EarlyBlight
Trạng thái kết quả cuối cùng được lưu dưới dạng `healthy`, `diseased` hoặc `uncertain`.

## Cấu trúc thư mục
- `App/` — mã nguồn Dart chính của ứng dụng Flutter
- `Pi4/` — chương trình Raspberry Pi và pipeline AI
- `Esp32/` — firmware điều khiển ray trên ESP32
- `README.md` — tài liệu mô tả dự án
- `.gitignore` — danh sách file cục bộ và file sinh tự động không đưa lên Git

## Cài đặt

### Raspberry Pi 4
Tạo file cấu hình cục bộ từ `Pi4/.env.example`:
    cd Pi4
    cp .env.example .env
Điền các giá trị cần thiết vào file `.env` trên máy cục bộ. Không commit mật khẩu, token, private key, service account hoặc Cloudinary API secret lên Git.

Cài đặt thư viện và chạy chương trình:
    python3 -m venv --system-site-packages .venv
    source .venv/bin/activate
    pip install -r requirements.txt
    python3 pi4_brain_ble_device_auth_rest.py

### Ứng dụng Flutter
Thư mục `App` chỉ chứa phần mã nguồn Dart chính. Các thư mục nền tảng Flutter và file sinh tự động không được đưa vào repository.
Để chạy ứng dụng, đặt phần mã nguồn này vào một dự án Flutter đầy đủ, cài đặt các dependency cần thiết và cấu hình Firebase cho dự án.

### ESP32
Mở file `Esp32/esp32_rail.ino` bằng Arduino IDE hoặc toolchain ESP32 tương thích, chọn đúng board và nạp firmware.

## Kiểm thử
Có thể chạy unit test cho pipeline trên Raspberry Pi bằng lệnh:
    cd Pi4
    python3 -m unittest discover -s tests -v
Bộ test hiện tại bao phủ các trường hợp: healthy, diseased, uncertain, không phát hiện lá và nhiều loại bệnh.

## Kết quả thực nghiệm
Các kết quả sau được ghi nhận trên hệ thống phần cứng ban đầu:
| Chỉ số                                            | Kết quả  |
|---|---:|
| F1-score phát hiện lá                             | 92,7%    |
| Độ chính xác phân loại Healthy hoặc Diseased      | 97,8%    |
| Độ chính xác phân loại LeafMiner hoặc EarlyBlight | 93,75%   |
| Độ chính xác toàn hệ thống                        | 94,0%    |
| Tỷ lệ hoàn thành chu kỳ quét                      | 98,0%    |
| Thời gian xử lý trung bình mỗi vị trí             | 7,8 giây |

Quá trình đánh giá gồm 50 chu kỳ quét và 150 vị trí kiểm thử.

## Hạn chế
- Pipeline AI hiện hỗ trợ Healthy, LeafMiner và EarlyBlight.
- Bộ dữ liệu chưa bao phủ đầy đủ mọi điều kiện ánh sáng và mức độ che khuất.
- Hệ thống mới được kiểm thử trong nhà, chưa đánh giá dài hạn trong môi trường nhà kính.
- Phiên bản mã nguồn đã làm sạch chưa được kiểm thử lại trên phần cứng ban đầu.
- Repository không chứa đầy đủ cấu trúc nền tảng của một dự án Flutter hoàn chỉnh.

## Trạng thái dự án
Dự án hiện không còn được phát triển tiếp trên phần cứng. Repository được duy trì như một dự án portfolio kỹ thuật và tài liệu tham khảo.
