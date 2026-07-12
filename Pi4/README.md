# Hệ thống AIoT phát hiện sâu bệnh trên lá cà chua
Repository này chứa chương trình chạy trên Raspberry Pi 4 của hệ thống AIoT phát hiện và cảnh báo sâu bệnh trên lá cà chua.

Raspberry Pi 4 có nhiệm vụ thu nhận ảnh từ Camera Module V3, chạy pipeline suy luận tại thiết bị biên, giao tiếp với ESP32 qua BLE và đồng bộ kết quả với Firebase, Cloudinary.

## Phạm vi repository
Thư mục này chứa phần mềm trên Raspberry Pi 4. Tổng quan toàn hệ thống nằm trong `../README.md`.
Các thành phần khác của hệ thống gồm:
- Firmware ESP32 điều khiển ray trượt
- Cơ cấu ray trượt, động cơ bước và driver DM542
- Ứng dụng Flutter dùng để cấu hình và giám sát
- Firebase và Cloudinary dùng để đồng bộ, lưu trữ dữ liệu

## Chức năng chính
- Kết nối Raspberry Pi 4 với ESP32 qua BLE
- Nhận trạng thái ray đã đến vị trí chụp
- Thu nhận ảnh từ Camera Module V3
- Phát hiện vùng lá bằng YOLO Pro
- Phân loại lá khỏe hoặc lá bệnh bằng MobileNetV2
- Phân loại LeafMiner hoặc EarlyBlight khi phát hiện lá bệnh
- Tổng hợp kết quả theo vị trí quét
- Lưu ảnh có nhãn khi phát hiện bệnh
- Đồng bộ trạng thái và kết quả lên Firebase, Cloudinary
- Gửi lệnh NEXT cho ESP32 để tiếp tục chu trình quét

## Pipeline xử lý ảnh
Pipeline gồm ba mô hình được huấn luyện trên Edge Impulse và xuất sang định dạng `.eim` để chạy trên Linux ARM64.
| Mô hình          | Nhiệm vụ                             | Kích thước đầu vào |
|---|---|---:|
| YOLO Pro         | Phát hiện vùng lá                    | 640 x 640          |
| MobileNetV2 1.0  | Phân loại Healthy hoặc Diseased      | 160 x 160          |
| MobileNetV2 0.35 | Phân loại LeafMiner hoặc EarlyBlight | 96 x 96            |

Các mô hình được lượng tử hóa INT8 trước khi triển khai trên Raspberry Pi 4.

## Kết quả thử nghiệm
| Chỉ số                                            | Kết quả  |
|---|---:|
| F1-score phát hiện lá                             | 92,7%    |
| Độ chính xác phân loại Healthy hoặc Diseased      | 97,8%    |
| Độ chính xác phân loại LeafMiner hoặc EarlyBlight | 93,75%   |
| Độ chính xác toàn hệ thống                        | 94,0%    |
| Tỷ lệ hoàn thành chu kỳ quét                      | 98,0%    |
| Thời gian xử lý trung bình mỗi vị trí             | 7,8 giây |

Kết quả được ghi nhận trên mô hình thử nghiệm trong nhà với 50 chu trình quét, tương ứng 150 vị trí kiểm thử.

## Cấu trúc thư mục
```text
Pi4/
├── core/
│   ├── __init__.py
│   ├── camera.py
│   ├── capture_mode.py
│   ├── classifier.py
│   ├── crop_enhance.py
│   ├── detector.py
│   ├── disease_classifier.py
│   ├── hsv_filter.py
│   └── preprocess.py
├── models/
│   ├── classifier.eim
│   ├── detector.eim
│   └── disease_classifier.eim
├── scripts/
│   └── pipeline.py
├── tests/
│   └── test_pipeline_output.py
├── .env.example
├── .gitignore
├── pi4_brain_ble_device_auth_rest.py
├── README.md
└── requirements.txt
```

## Phần cứng và môi trường
Hệ thống đã được triển khai với:
- Raspberry Pi 4 Model B, RAM 4 GB
- Raspberry Pi OS 64-bit
- Raspberry Pi Camera Module V3
- ESP32 DevKit
- Python 3
- Edge Impulse Linux Python SDK
- OpenCV
- Bleak
Các file `.eim` trong thư mục `models` được biên dịch cho Linux ARM64. Chúng không chạy trực tiếp trên máy tính Windows x86.

## Cài đặt
Cài các gói hệ thống cần thiết trên Raspberry Pi:
sudo apt update
sudo apt install -y python3-picamera2 --no-install-recommends
sudo apt install -y libportaudio2 portaudio19-dev

Tạo môi trường Python và cài thư viện:
python3 -m venv --system-site-packages .venv
source .venv/bin/activate
pip install --upgrade pip
pip install -r requirements.txt

Tạo file cấu hình môi trường:
cp .env.example .env

Tạo file `.env` cục bộ từ `.env.example`, sau đó điền thông tin cấu hình của môi trường triển khai. File `.env` không được đưa lên GitHub.

Sao chép `.env.example` thành `.env`, sau đó điền cấu hình thật trên máy cục bộ. Không commit `.env` hoặc bất kỳ credential nào lên Git.

## Chạy test
python3 -m unittest discover -s tests -v

## Chạy pipeline tại một vị trí
Lệnh sau chụp ảnh, chạy pipeline và lưu kết quả JSON:
python3 scripts/pipeline.py \
  --single-shot \
  --position 24 \
  --json-out ai_results/result.json


Ví dụ kết quả:
```json
{
  "has_disease": true,
  "final_label": "LeafMiner",
  "confidence": 0.88,
  "leaf_count": 3,
  "scan_status": "diseased",
  "position_cm": 24.0,
  "summary": {
    "Healthy": 2,
    "LeafMiner": 1
  }
}
```

## Chạy chương trình điều phối
python3 pi4_brain_ble_device_auth_rest.py

Chương trình điều phối thực hiện các nhiệm vụ:
- Đọc cấu hình và lệnh từ Firebase
- Kết nối, trao đổi dữ liệu với ESP32 qua BLE
- Gọi pipeline khi nhận trạng thái ARRIVED
- Lưu kết quả phát hiện bệnh
- Cập nhật trạng thái hệ thống
- Gửi lệnh NEXT để ray tiếp tục di chuyển

## Các phần đã thực hiện
- Thu thập, lọc và gán nhãn dữ liệu ảnh
- Cấu hình, huấn luyện và đánh giá mô hình trên Edge Impulse
- Xuất mô hình INT8 để chạy trên Raspberry Pi 4
- Tích hợp camera và pipeline suy luận
- Tích hợp giao tiếp BLE với ESP32
- Tích hợp Firebase và Cloudinary
- Kiểm thử từng khối và kiểm thử toàn hệ thống
- Điều chỉnh tham số dựa trên kết quả chạy thực tế

## Hạn chế
- Hệ thống hiện chỉ hỗ trợ Healthy, LeafMiner và EarlyBlight
- Dữ liệu chưa bao phủ đầy đủ mọi điều kiện ánh sáng và mức độ che khuất
- Hệ thống mới được kiểm thử trên mô hình thử nghiệm trong nhà
- Chưa thực hiện kiểm thử dài hạn trong nhà kính thực tế

## Trạng thái dự án
Dự án hiện không còn được phát triển tiếp trên phần cứng. Repository được duy trì như một dự án portfolio kỹ thuật và tài liệu tham khảo.
