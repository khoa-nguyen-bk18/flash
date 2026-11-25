# ⚡ Flash CLI Suite (Android, Xcode / iOS & KMP)

[![CodeQL](https://github.com/khoa-nguyen-bk18/flash/actions/workflows/codeql.yml/badge.svg)](https://github.com/khoa-nguyen-bk18/flash/actions/workflows/codeql.yml)
[![Secret Scanning](https://img.shields.io/badge/Secret%20Scanning-Protected-green?logo=github)](https://github.com/khoa-nguyen-bk18/flash/security)
[![Quality Gate Status](https://sonarcloud.io/api/project_badges/measure?project=khoa-nguyen-bk18_flash&metric=alert_status)](https://sonarcloud.io/summary/new_code?id=khoa-nguyen-bk18_flash)
[![Security Rating](https://sonarcloud.io/api/project_badges/measure?project=khoa-nguyen-bk18_flash&metric=security_rating)](https://sonarcloud.io/summary/new_code?id=khoa-nguyen-bk18_flash)
[![Vulnerabilities](https://sonarcloud.io/api/project_badges/measure?project=khoa-nguyen-bk18_flash&metric=vulnerabilities)](https://sonarcloud.io/summary/new_code?id=khoa-nguyen-bk18_flash)
[![Maintainability Rating](https://sonarcloud.io/api/project_badges/measure?project=khoa-nguyen-bk18_flash&metric=sqale_rating)](https://sonarcloud.io/summary/new_code?id=khoa-nguyen-bk18_flash)
[![Reliability Rating](https://sonarcloud.io/api/project_badges/measure?project=khoa-nguyen-bk18_flash&metric=reliability_rating)](https://sonarcloud.io/summary/new_code?id=khoa-nguyen-bk18_flash)

Bộ công cụ dòng lệnh cho lập trình viên **Android**, **Xcode (iOS Native)** và **Kotlin Multiplatform (KMP)** — cho phép build, cài đặt, chạy, quản lý thiết bị/Simulator, thao tác nhanh và theo dõi Log trực tiếp từ Command Line mà không phụ thuộc vào IDE.

---

## 🚀 Tính năng nổi bật

- **Zero External Dependencies**: Viết hoàn toàn bằng Python 3 Standard Library + các công cụ CLI gốc (`adb`, `xcodebuild`, `xcrun simctl`, `xcrun devicectl`), chạy ngay lập tức không cần `pip install`.
- **Đa nền tảng thông minh (Android, Native Xcode & KMP)**:
  - Tự động nhận diện **Android-only**, **Native Xcode** (`.xcworkspace` / `.xcodeproj`), hoặc **KMP** (`settings.gradle.kts` + `iosApp/`).
  - Trong dự án KMP: đứng trong `iosApp/` tự động chạy iOS, đứng trong `androidApp/` tự động chạy Android, hoặc chuyển đổi tức thì bằng `--ios` / `--android` / `flash platform select`.
- **One-Click Run (Android & iOS)**:
  - **Android**: `./flash run` tự động Build -> Tìm APK -> `adb install -r` -> Tìm Launcher Activity -> Khởi chạy app.
  - **Xcode / iOS**: `./flash run --ios` tự động Boot Simulator (nếu đang tắt) -> `xcodebuild` (dùng `.flash/DerivedData` riêng biệt) -> Đọc `Info.plist` -> Cài đặt & Khởi chạy qua `simctl` (Simulator) hoặc `devicectl` (iPhone/iPad thật iOS 17+ USB & Wi-Fi). Hỗ trợ chạy song song nhiều thiết bị!
- **Smart Artifact Discovery**: Quét đệ quy APK (Android) và `.app` / `.xcarchive` / `.ipa` (iOS), hỗ trợ Product Flavors Matrix & Xcode Schemes/Configurations.
- **Real-Time Device Monitoring**: Lắng nghe sự kiện thiết bị Android (`adb track-devices`) và iOS (`xcrun xcdevice observe`).
- **Wireless Debugging**: Kết nối không dây qua **mã QR trực tiếp trên terminal** (`flash wireless qr` cho Android 11+), tự động chuyển USB sang Wi-Fi cho Android, dò tìm mDNS (`flash wireless discover`), và hỗ trợ thiết bị iOS qua Wi-Fi với Xcode 15+ `devicectl`.
- **Colored Log Streaming**: Stream Logcat (Android) và Unified Logs (iOS Simulator) tô màu ANSI trực quan, tự động lọc theo App, TAG/Subsystem hoặc Level (V, D, I, W, E, F).
- **Quick Actions 1-Click**: Restart, Kill, Clear Data & Restart, Grant/Revoke Permissions, Screenshot, và các tiện ích iOS Simulator (Boot/Shutdown/Erase, Toggle Dark/Light Mode, Open Deep Link URL).
- **Keystore Wizard & Multi-Module & Fastlane**: Tạo `.jks`, quản lý Gradle modules / Xcode workspaces, và chạy Fastlane lanes cho cả Android lẫn iOS (`iosApp/fastlane/Fastfile`, `ios/fastlane/Fastfile`).

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
./wrappers/fastlane.sh
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
./flash restart -c             # Xóa dữ liệu và khởi động lại app

# Xóa sạch dữ liệu và khởi động lại app (Clear Data & Restart)
./flash clear-restart          # (Aliases tiện lợi: ./flash reset hoặc ./flash cr)
./flash clear-restart -f vietnamese

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
Hỗ trợ ghép đôi trực tiếp qua **mã QR trên terminal** cho **Android 11+** (không cần cắm cáp USB): Flash tự tạo mã QR thuần Python hiển thị liền mạch bằng ANSI 256-color, lắng nghe dịch vụ mDNS (`adb mdns services`) khi điện thoại quét từ **Settings -> Developer options -> Wireless debugging -> Pair device with QR code**, rồi tự động chạy `adb pair` và `adb connect`.

```bash
# Kết nối không dây bằng mã QR trên terminal (Android 11+, không cần cáp USB)
./flash wireless qr              # (Aliases: ./flash wireless scan, ./flash wireless qrcode, ./flash wireless pair --qr)
./flash wireless qr --compact    # Hiển thị dạng thu gọn (half-block) cho cửa sổ terminal nhỏ
./flash wireless qr --invert     # Đảo màu QR nếu cần
./flash wireless qr -t 180       # Tùy chỉnh timeout chờ quét (giây, mặc định: 120)
./flash wireless qr --no-connect # Chỉ ghép đôi (pair), không tự động chạy adb connect
./flash wireless qr --name dev1  # Tùy chỉnh tên service mDNS cho mã QR

# Dò tìm thiết bị đang bật Wireless Debugging trong mạng Wi-Fi (mDNS)
./flash wireless discover        # (Aliases: ./flash wireless list, ./flash wireless ls)

# Tự động lấy IP qua USB và kích hoạt kết nối Wi-Fi (Android 4.0+)
./flash wireless setup

# Ghép đôi thiết bị tương tác (chọn QR hoặc mã 6 số) hoặc nhập trực tiếp Pairing Code (Android 11+)
./flash wireless pair
./flash wireless pair 192.168.1.100:45678 123456

# Kết nối tới IP thiết bị (hoặc bỏ trống để tự dò qua mDNS)
./flash wireless connect
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

---

### 12. Tự Động Hóa Fastlane (Fastlane / Lane)
Tự động quét cấu hình `Fastfile` và `Gemfile` trong dự án, hiển thị danh sách các option có thể thực thi với `bundle exec fastlane`, cho phép chọn theo index hoặc chạy trực tiếp tương tự cơ chế của `flash run`:

```bash
# Hiển thị menu danh sách lanes và chọn theo index (hỗ trợ nhập số hoặc 'a' để chạy tất cả)
./flash fastlane
# hoặc alias ngắn gọn:
./flash lane
./flash fl

# Chạy trực tiếp theo số thứ tự index
./flash fastlane 1

# Chạy trực tiếp theo tên lane
./flash fastlane build_debug
./flash fastlane distribute_debug

# Chỉ hiển thị danh sách lanes có sẵn mà không thực thi
./flash fastlane -l

# Chạy không thông qua Bundler (gọi trực tiếp lệnh fastlane toàn cục)
./flash fastlane build_debug --no-bundle

# Truyền thêm tham số bổ sung cho Fastlane (ví dụ options / flags)
./flash fastlane distribute_debug groups:internal-testers --verbose

# Sử dụng shell wrapper script tiện lợi
./wrappers/fastlane.sh
```

---

### 13. Hỗ Trợ Xcode (iOS Native) & Kotlin Multiplatform (KMP)

Trong **Native Xcode project**, mọi lệnh `flash` tự động chạy ở chế độ iOS mà không cần thêm cờ. Trong **KMP project**, bạn có thể thêm `--ios` / `--android` (hoặc `-P ios` / `-P android`), đứng trực tiếp trong thư mục `iosApp/` / `androidApp/`, hoặc ghim nền tảng mặc định:

```bash
# Kiểm tra môi trường cả Android + Xcode/iOS (trên KMP)
./flash doctor
./flash doctor --ios

# Quản lý nền tảng mặc định cho KMP project
./flash platform list
./flash platform select ios
./flash platform clear

# Quản lý thiết bị iOS (Physical Devices USB/Wi-Fi + Simulators)
./flash devices --ios
./flash devices --ios -s          # Chọn thiết bị iOS mặc định
./flash devices --ios --watch     # Giám sát thiết bị thời gian thực

# Quản lý Xcode Schemes & Configurations
./flash scheme list               # (hoặc ./flash flavor list --ios)
./flash scheme select iosApp
./flash scheme clear

# Build & Run trên iOS Simulator / Physical Device
./flash build --ios
./flash build --ios -f iosApp -v Release --signed
./flash run --ios                 # Tự Boot Simulator nếu đang tắt -> Build -> Install -> Launch
./flash run --ios --no-build      # Dùng lại .app đã build trong .flash/DerivedData
./flash run --ios --logs          # Chạy app và stream iOS Unified Logs tô màu

# Thao tác nhanh iOS (Quick Actions)
./flash quick --ios               # Popup menu (kèm Boot/Shutdown/Erase Simulator, Dark/Light, Deep Link)
./flash clear-restart --ios       # Xóa dữ liệu app container trên Simulator & mở lại
./flash perm grant --ios          # Cấp toàn bộ quyền Simulator (simctl privacy)
./flash screenshot --ios --open   # Chụp màn hình Simulator và mở xem
./flash logs --ios                # Stream iOS logs có lọc theo app / subsystem / level

# Dọn dẹp & Đồng bộ dependencies (CocoaPods, SwiftPM, KMP)
./flash clean --ios               # Clean Xcode + xóa .flash/DerivedData
./flash clean --ios --all         # Clean cả Xcode lẫn Gradle (KMP)
./flash sync --ios                # Chạy KMP generateDummyFramework (nếu có) + pod install + SPM resolve
```
