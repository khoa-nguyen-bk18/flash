# ⚡ Android Studio Flash CLI Suite

Bộ công cụ dòng lệnh thay thế hoàn toàn extension **Android Studio Flash** trong Antigravity IDE / VS Code, cho phép lập trình viên build, cài đặt, chạy, quản lý thiết bị, gỡ lỗi không dây và theo dõi Logcat trực tiếp từ Command Line mà không phụ thuộc vào IDE.

---

## 🚀 Tính năng nổi bật

- **Zero External Dependencies**: Viết hoàn toàn bằng Python 3 Standard Library, chạy ngay lập tức không cần `pip install`.
- **Tự động nhận diện môi trường**: Tự phát hiện Android SDK, ADB, AAPT, JDK `keytool`, và tự tạo/cập nhật `local.properties`.
- **One-Click Run**: `./flash run` tự động Build -> Tìm file APK thông minh -> `adb install -r` -> Tìm Launcher Activity -> Khởi chạy app.
- **Smart APK Discovery**: Quét đệ quy thư mục build, bỏ qua test APK, tự động tìm APK mới nhất ngay cả khi có Build Flavors phức tạp.
- **Real-Time Device Monitoring**: Lắng nghe sự kiện cắm/rút USB thời gian thực qua `adb track-devices` mà không tốn CPU polling.
- **Wireless Debugging**: Tự động lấy địa chỉ IP của thiết bị qua USB (hỗ trợ cả Wi-Fi `wlan0`, Hotspot `ap0`, tethering `rndis0`), chuyển port và kết nối không dây chỉ bằng 1 lệnh. Hỗ trợ cả Android 11+ Pairing.
- **Colored Logcat Streaming**: Stream Logcat tô màu ANSI trực quan, tự động tìm PID của app để lọc chính xác log của ứng dụng, hỗ trợ lọc theo TAG hoặc Level (V, D, I, W, E, F).
- **Keystore Wizard**: Tạo file khóa `.jks` tương tác trực tiếp trên terminal bằng JDK `keytool` và hỗ trợ lưu vào `local.properties` để tự động ký.
- **Multi-Module Support**: Tự động phân tích `settings.gradle.kts` để xác định và nhắm mục tiêu các sub-module.

---

## 📦 Cài đặt & Sử dụng nhanh

Chạy trực tiếp từ thư mục repo:
```bash
./flash <command>
```
hoặc dùng các shell script tắt trong `wrappers/`:
```bash
./wrappers/run.sh
./wrappers/devices.sh
./wrappers/logcat.sh
./wrappers/quick.sh
```

### Cài đặt Global (Khuyên dùng)
Để có thể gõ lệnh `flash` ở bất kỳ thư mục hay project Android nào trong terminal:
```bash
./flash install-global
```

---

## 🎮 Bảng lệnh & Ví dụ

### 1. Kiểm tra môi trường (Doctor)
```bash
./flash doctor
```
Kiểm tra toàn diện Android SDK, ADB, ADB Server, JDK, quyền thực thi của Gradle wrapper và các thiết bị đang kết nối.

---

### 2. Quản lý thiết bị (Devices)
```bash
# Xem danh sách thiết bị kèm tên hãng, model và trạng thái
./flash devices

# Chọn thiết bị mặc định khi có nhiều máy kết nối
./flash devices -s

# Giám sát cắm/rút USB theo thời gian thực (Zero-CPU polling)
./flash devices --watch
```

---

### 3. Build APK & Product Flavors
```bash
# Build Debug APK (tự động hỏi flavor nếu project có nhiều flavors)
./flash build

# Chỉ định rõ flavor cần build
./flash build -f vietnamese
./flash build -f global

# Build tất cả các flavors cùng lúc
./flash build --all-flavors

# Clean trước rồi build Debug
./flash build --clean

# Build Release APK
./flash build -v release -f vietnamese

# Build Release APK có chữ ký tự động từ local.properties
./flash build -v release -f vietnamese --signed

# Build cho module cụ thể
./flash build -m :app -f global
```

---

### 4. Build, Cài đặt & Mở ứng dụng (Run)
```bash
# Biên dịch, cài đặt và mở app lên thiết bị (hỏi flavor nếu có nhiều hơn 1)
./flash run

# Chạy với flavor cụ thể
./flash run -f vietnamese
./flash run -f global

# Cài đặt và mở app, sau đó ngay lập tức stream Logcat của app
./flash run -f vietnamese --logcat

# Không build lại, dùng luôn file APK mới nhất có sẵn của flavor đó
./flash run -f vietnamese --no-build

# Chỉ định thiết bị cụ thể (nếu cắm nhiều máy)
./flash run -s 10AE5A2XY4000ZK -f vietnamese
```

---

### 5. Quản lý Product Flavors (Flavors)
```bash
# Xem danh sách flavors, dimensions, và package IDs tương ứng
./flash flavor list

# Chọn flavor mặc định (lưu vào .flash/config.json để không cần gõ -f mỗi lần)
./flash flavor select vietnamese

# Xóa cấu hình flavor mặc định
./flash flavor clear
```

---

### 6. Thao Tác Nhanh ADB & Thiết Bị (Quick Actions)
Công cụ hỗ trợ giao diện menu số 1-click tương tự popup trong Android Studio, đồng thời hỗ trợ gọi lệnh trực tiếp trên terminal:

#### 🎮 Popup Menu Tương Tác (Interactive Popup)
```bash
./flash action
# hoặc alias:
./flash quick
```
Hiển thị danh sách đầy đủ tất cả các action:
1. Restart App
2. Kill App (Force Stop)
3. Clear App Data
4. Clear App Data and Restart
5. Start App
6. Uninstall App
7. Install APK...
8. Grant Permissions (Cấp toàn bộ quyền runtime tự động)
9. Revoke Permissions (Reset quyền)
10. Revoke Permissions and Restart
11. Toggle Wi-Fi / Enable / Disable Wi-Fi
12. Toggle Mobile Data / Enable / Disable Mobile Data
13. Toggle Airplane Mode
14. Take Screenshot (Lưu PNG về máy tính host)
15. Open Interactive Shell

#### ⚡ Các Lệnh Tắt Trực Tiếp (Direct CLI Commands)
```bash
# Khởi động lại app
./flash restart
./flash restart -f vietnamese

# Buộc dừng app (Force Stop)
./flash kill

# Xóa dữ liệu app (Clear App Data)
./flash clear
# Xóa dữ liệu và khởi động lại ngay
./flash clear -r

# Quản lý quyền ứng dụng (Permissions)
./flash perm grant             # Cấp toàn bộ runtime permissions
./flash perm revoke            # Reset permissions về mặc định
./flash perm revoke -r         # Reset permissions và khởi động lại

# Chụp ảnh màn hình thiết bị và lưu về máy tính host
./flash screenshot             # Tự động lưu screenshot_YYYYMMDD_HHMMSS.png
./flash screenshot --open      # Chụp và tự động mở xem ảnh trên máy tính
./flash screenshot -o ~/Desktop/screen.png

# Điều khiển Wi-Fi
./flash wifi status            # Xem trạng thái Wi-Fi
./flash wifi toggle            # Bật/tắt đảo trạng thái Wi-Fi
./flash wifi on / ./flash wifi off

# Điều khiển Mobile Data (3G/4G/5G)
./flash data status            # Xem trạng thái Mobile Data
./flash data toggle            # Bật/tắt đảo trạng thái Data
./flash data on / ./flash data off

# Chế độ máy bay (Airplane Mode)
./flash airplane status
./flash airplane toggle

# Mở interactive ADB Shell
./flash shell
```

---

### 7. Gỡ lỗi không dây (Wireless Debugging)
```bash
# Tự động lấy IP qua USB và kích hoạt kết nối Wi-Fi (Android 4.0+)
./flash wireless setup

# Ghép đôi thiết bị qua Pairing Code (Android 11+)
./flash wireless pair 192.168.1.100:45678 123456

# Kết nối trực tiếp tới IP đã bật TCP/IP
./flash wireless connect 192.168.1.100:5555

# Tự động kết nối lại tất cả các thiết bị Wi-Fi đã nhớ trước đó
./flash wireless reconnect

# Ngắt kết nối không dây
./flash wireless disconnect
```

---

### 8. Xem Logcat thông minh (Logcat)
```bash
# Tự động nhận diện package của project, lấy PID và lọc log app có tô màu
./flash logcat

# Lọc theo TAG cụ thể
./flash logcat --tag MainActivity

# Lọc log từ mức Warning trở lên (W, E, F)
./flash logcat --level W

# Lọc log cho một package cụ thể
./flash logcat --app com.devindie.ghi

# Xóa sạch bộ đệm Logcat trên thiết bị
./flash logcat --clear
```

---

### 9. Tạo Keystore ký ứng dụng (Keystore)
```bash
# Mở wizard tương tác trên terminal để tạo file .jks
./flash keystore create
```

---

### 10. Quản lý Module (Multi-Module)
```bash
# Xem danh sách các module có trong settings.gradle.kts
./flash module list

# Chọn module mục tiêu cho các lệnh build/run/clean tiếp theo
./flash module select
```

---

### 11. Clean & Sync Gradle
```bash
# Dọn dẹp build artifacts
./flash clean

# Đồng bộ hóa dependencies Gradle (tasks)
./flash sync
```
