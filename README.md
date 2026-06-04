<h1 align="center"> 🏠 XÂY DỰNG THIẾT KẾ HỆ THỐNG NHÀ THÔNG MINH </h1>
 
<div align="center">

<p align="center">
  <img src="logoDaiNam.png" alt="DaiNam University Logo" width="200"/>
  <img src="LogoAIoTLab.png" alt="AIoTLab Logo" width="170"/>
</p>

[![Made by AIoTLab](https://img.shields.io/badge/Made%20by%20AIoTLab-blue?style=for-the-badge)](https://www.facebook.com/DNUAIoTLab)
[![Fit DNU](https://img.shields.io/badge/Fit%20DNU-green?style=for-the-badge)](https://fitdnu.net/)
[![DaiNam University](https://img.shields.io/badge/DaiNam%20University-red?style=for-the-badge)](https://dainam.edu.vn)

</div>
# BlockPlate

Ứng dụng smart contract trong quản lý và xác thực biển số xe.

BlockPlate kết hợp Flask, Web3.py, Solidity, MetaMask và OCR biển số xe Việt Nam. OCR chỉ đóng vai trò hỗ trợ nhập nhanh biển số; dữ liệu xác thực cuối cùng được lấy từ smart contract trên Sepolia.

## Trạng thái hiện tại

| Hạng mục | Giá trị |
| --- | --- |
| Mạng blockchain | Sepolia Testnet |
| Contract hiện tại | `0x43a36498d0A7B929018e1f9ae56D65038fE790D2` |
| Explorer | `https://sepolia.etherscan.io/address/0x43a36498d0A7B929018e1f9ae56D65038fE790D2` |
| File địa chỉ contract | `contracts/contract_address.json` |
| Smoke test gần nhất | 51/51 pass |
| Ngày cập nhật | 2026-06-04 |

## Vai trò của hệ thống

Đề tài chính là quản lý và xác thực biển số bằng smart contract, không phải chỉ nhận dạng ảnh. Vì vậy app được thiết kế theo nguyên tắc:

- Smart contract là nguồn dữ liệu tin cậy cuối cùng.
- OCR chỉ tạo biển số đề xuất, người dùng có thể kiểm tra và chỉnh sửa trước khi xác thực blockchain.
- Mỗi thao tác quan trọng như đăng ký, chuyển nhượng, khóa, mở khóa, ghi vi phạm được ghi nhận qua transaction hoặc timeline.
- Người dùng thường chỉ xem thống kê công khai, tra cứu, OCR, webcam OCR, timeline, xe mất cắp và lịch sử xác thực.
- Admin phải chọn **Đăng nhập Admin bằng MetaMask** và ký thông điệp nonce trước khi frontend hiển thị chức năng quản trị.
- Backend kiểm tra token Admin ngắn hạn cho mọi API thay đổi dữ liệu. Kết nối ví thông thường không tự cấp quyền Admin.
- Backend dùng ví ký giao dịch cấu hình trong `.env`; địa chỉ `ADMIN_ADDRESS` phải khớp `admin()` của contract đã deploy.

## Tính năng chính

- Đăng ký biển số mới lên smart contract.
- Xác thực biển số đã đăng ký, trạng thái active/inactive và thông tin chủ xe.
- Cập nhật loại xe, màu xe và tỉnh đăng ký bằng `updateVehicle()`.
- Chuyển nhượng chủ sở hữu.
- Khóa phương tiện bằng `deactivatePlate()` và mở khóa bằng `reactivatePlate()`.
- Ghi nhận vi phạm và xử lý trạng thái nộp phạt bằng `markViolationPaid()`.
- Báo cáo xe mất cắp có liên kết khóa phương tiện trên blockchain nếu biển đã đăng ký.
- Chuẩn hóa biển số trước khi ghi/tra cứu blockchain, ví dụ `59T160574`, `59-T1-60574` và `59-T1-605.74` được xử lý về cùng một dạng `59-T1-605.74`.
- Timeline giao dịch: đăng ký, cập nhật, chuyển nhượng, vi phạm, nộp phạt, khóa phương tiện, mở khóa phương tiện.
- Admin tạo QR xác minh có hỗ trợ tiếng Việt; người dùng có thể quét QR từ ảnh.
- OCR từ ảnh upload.
- Webcam OCR hỗ trợ nhập biển số trong điều kiện thực tế, không tự coi kết quả OCR là đúng tuyệt đối.
- Bảng tổng quan thống kê biển số duy nhất, biển active, inactive và số giao dịch.

## Cấu trúc thư mục

```text
D:\BlockChain
|-- web_app.py                         # Flask web app và REST API
|-- inference.py                       # Pipeline OCR/detect biển số
|-- video_recognition.py               # Xử lý video/webcam
|-- blockchain_service.py              # Giao tiếp smart contract
|-- blockchain_config.py               # Cấu hình RPC, ví, contract
|-- blockchain_timeline.py             # Timeline giao dịch nội bộ
|-- stolen_vehicles.py                 # Quản lý xe mất cắp
|-- qr_generator.py                    # Tạo/đọc QR xác minh
|-- compile_contract.py                # Compile Solidity contract
|-- deploy_contract.py                 # Deploy contract lên Sepolia
|-- contracts/
|   |-- LicensePlateRegistry.sol       # Smart contract chính
|   |-- LicensePlateRegistry_abi.json
|   |-- LicensePlateRegistry_bytecode.json
|   |-- contract_address.json
|-- static/
|   |-- app.js
|   |-- style.css
|-- templates/
|   |-- index.html
|-- scripts/
|   |-- smoke_test_app.py              # Kiểm thử nhanh API
|-- models/                            # Model nhận dạng đang dùng
|-- dataset_final/                     # Dataset huấn luyện/tham chiếu
|-- uploads/                           # Ảnh/video người dùng upload
|-- results/                           # Ảnh kết quả nhận dạng
|-- qr_codes/                          # QR được tạo
|-- TEST_REPORT.md                     # Báo cáo kiểm thử gần nhất
```

## Cài đặt

```powershell
cd D:\BlockChain
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
```

Tạo file `.env` từ `.env.example` nếu máy chưa có:

```powershell
Copy-Item .env.example .env
```

Sau đó điền RPC, private key, `ADMIN_ADDRESS` và `ADMIN_TOKEN_SECRET` phù hợp. Không commit private key hoặc secret token lên repository.

## Chạy web

Thông thường chỉ cần chạy file này:

```powershell
cd D:\BlockChain
python web_app.py
```

Mở trình duyệt tại:

```text
http://127.0.0.1:5000
```

Không cần Remix IDE để chạy web. VS Code + terminal là đủ nếu contract đã deploy và `contracts/contract_address.json` đang trỏ đúng địa chỉ.

## Khi nào cần compile/deploy lại contract

Không cần compile/deploy lại nếu chỉ sửa giao diện, OCR, Flask API, README hoặc file tĩnh.

Chỉ compile/deploy lại khi sửa `contracts/LicensePlateRegistry.sol`, ví dụ thêm hàm hoặc thay đổi dữ liệu lưu trên chain.

```powershell
python compile_contract.py
python deploy_contract.py
```

Lưu ý: redeploy tạo một contract address mới. Dữ liệu on-chain ở contract cũ không tự chuyển sang contract mới, trừ phần migration đã được script xử lý. Sau khi deploy, kiểm tra lại `contracts/contract_address.json`.

Sau cập nhật ngày 2026-06-04, contract Sepolia mới đã được deploy tại `0x43a36498d0A7B929018e1f9ae56D65038fE790D2` và đã có `updateVehicle()` cùng `markViolationPaid()`. Dữ liệu từ contract cũ `0xF51fDf3cb9931256E3A50202411f377d92c6545a` đã được migrate sang contract mới.

Script `deploy_contract.py` hiện dùng gas price thực tế từ Sepolia và kiểm tra số dư trước khi gửi transaction. Nếu ví deploy thiếu SepoliaETH, script sẽ dừng và báo số dự kiến cần nạp thêm. Có thể deploy contract trắng không migrate dữ liệu cũ bằng:

```powershell
python deploy_contract.py --no-migrate
```

## Smart contract

Contract chính nằm tại:

```text
contracts/LicensePlateRegistry.sol
```

Các nhóm hàm quan trọng:

- `registerPlate(...)`: đăng ký biển mới.
- `verifyPlate(...)`: kiểm tra biển số.
- `updateVehicle(...)`: cập nhật loại xe, màu xe và tỉnh/thành phố.
- `transferOwnership(...)`: chuyển chủ sở hữu.
- `deactivatePlate(...)`: khóa phương tiện bằng cách chuyển biển sang trạng thái inactive.
- `reactivatePlate(...)`: mở khóa phương tiện bằng cách chuyển biển về trạng thái active.
- `addViolation(...)`: ghi nhận vi phạm.
- `markViolationPaid(...)`: đánh dấu một lỗi vi phạm đã nộp phạt.

`reactivatePlate()` dùng khi biển số đã tồn tại trên blockchain nhưng bị chuyển sang trạng thái inactive. Hàm này không tạo biển mới và không xóa dữ liệu cũ, mà chỉ bật lại trạng thái active cho biển đã có.

## Luồng demo đề xuất cho giảng viên

1. Mở dashboard và xem các chức năng công khai ở chế độ người dùng.
2. Chọn **Đăng nhập Admin bằng MetaMask**, dùng ví Admin Sepolia và ký thông điệp xác thực.
3. Vào Quản trị, đăng ký một biển số mới.
4. Qua Timeline để thấy giao dịch đăng ký.
5. Dùng Xác thực nhanh để kiểm tra biển vừa đăng ký.
6. Nhập lại cùng biển theo dạng khác, ví dụ bỏ dấu gạch/chấm, để chứng minh hệ thống tự chuẩn hóa trước khi tra cứu smart contract.
7. Upload ảnh hoặc dùng webcam OCR để tạo biển số đề xuất.
8. Chỉnh biển nếu OCR sai, sau đó xác thực blockchain. Nhấn mạnh OCR chỉ là công cụ hỗ trợ, không phải nguồn xác thực chính.
9. Cập nhật thông tin phương tiện hoặc chuyển nhượng chủ sở hữu.
10. Ghi vi phạm, xử lý nộp phạt hoặc báo cáo xe mất cắp.
11. Khóa/mở khóa phương tiện và kiểm tra trạng thái biển thay đổi trong Dashboard, danh sách biển và Timeline.
12. Đăng xuất Admin và kiểm tra các nút quản trị đã bị ẩn.

## Kiểm thử

Chạy smoke test API:

```powershell
python scripts/smoke_test_app.py
```

Báo cáo gần nhất nằm ở:

```text
TEST_REPORT.md
```

Kết quả gần nhất: 51 test pass, 0 fail.

## Lưu ý về OCR và webcam

OCR có thể sai khi ảnh mờ, thiếu sáng, chụp qua màn hình điện thoại, biển bị nghiêng, biển hai dòng hoặc ký tự nhỏ. Vì vậy giao diện hiện tại không nên tự quyết định kết quả bằng OCR. Người dùng cần xác nhận hoặc sửa biển số trước khi đối chiếu blockchain.

Nếu cần tăng độ chính xác thực sự, hướng đúng là tạo bộ benchmark ảnh riêng và huấn luyện/cải thiện model nhận dạng, không chỉ sửa logic giao diện.

## File dữ liệu runtime

Các thư mục sau là dữ liệu phát sinh khi chạy app:

- `uploads/`: ảnh/video người dùng tải lên.
- `results/`: ảnh đã vẽ box/kết quả OCR.
- `qr_codes/`: QR xác minh được tạo.
- `blockchain_timeline.json`: timeline local hỗ trợ giao diện.
- `stolen_vehicles.json`: dữ liệu xe mất cắp local.

Không xoá các thư mục này khi đang chuẩn bị demo, trừ khi muốn reset dữ liệu runtime.

## Troubleshooting nhanh

| Lỗi | Cách xử lý |
| --- | --- |
| Không mở được web | Kiểm tra `python web_app.py` có đang chạy và port 5000 chưa bị chiếm |
| MetaMask offline | Chọn đúng Sepolia, reload trang, kết nối lại ví |
| Wallet is not the contract admin | Dùng đúng ví admin hoặc chỉ thao tác các chức năng người dùng |
| Admin token expired | Xác thực admin lại trên giao diện |
| Cập nhật/nộp phạt báo cần redeploy | Kiểm tra `contracts/contract_address.json` có đang trỏ đúng contract mới không; nếu dùng contract cũ thì chạy lại `python deploy_contract.py` |
| Deploy contract thất bại do hết thời gian hoặc status 0 | Kiểm tra SepoliaETH, gas limit và chạy lại `python deploy_contract.py`; script đã tự ước lượng gas deploy thay vì dùng cố định 3.5M |
| Contract không có dữ liệu | Kiểm tra `contracts/contract_address.json` có đúng contract mới nhất |
| OCR sai nhưng confidence cao | Xem OCR là gợi ý, sửa tay trước khi xác thực blockchain |
| QR không tạo được | Cài dependency trong `requirements.txt`, đặc biệt `qrcode` và `pillow` |

## Ghi chú bảo mật

- Không đưa private key vào README, screenshot hoặc commit.
- `.env` đã được ignore và phải giữ ở máy local.
- Không gửi giao dịch thật nếu chưa kiểm tra đúng mạng Sepolia và đúng ví admin.
- Frontend/backend đã che tên chủ xe đối với người dùng thường. Tuy nhiên Sepolia là blockchain công khai và contract hiện lưu tên chủ xe dạng chuỗi, nên dữ liệu on-chain vẫn có thể được đọc trực tiếp bằng công cụ blockchain. Muốn bảo mật dữ liệu cá nhân thực sự cần lưu hash hoặc mã tham chiếu on-chain và giữ dữ liệu chi tiết ở hệ thống off-chain có phân quyền; thay đổi này yêu cầu redeploy contract.

## Poster

<p align="center">
  <img src="docs/Poster.png" width="900">
</p>

<p align="center">
  📄 <a href="docs/Poster.pdf">Xem Poster PDF</a>
</p>
