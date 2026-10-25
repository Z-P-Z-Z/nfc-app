# NFC 助手 — 打包安卓 APK 指南

一个用 **Python (Kivy + pyjnius)** 编写的安卓 NFC 读写 App。

- **读取模式**：贴近 NFC 标签，显示 UID 和 NDEF 内容（文本 / 网址等）
- **写入模式**：输入文本或网址，贴近标签即写入（支持自动格式化空白卡）

## 项目文件

| 文件 | 说明 |
|------|------|
| `main.py` | 全部应用代码（界面 + NFC 逻辑） |
| `buildozer.spec` | 打包配置（权限、依赖、SDK 版本） |
| `打包APK-Colab.ipynb` | Google Colab 云端打包笔记本（推荐，最简单） |
| `.github/workflows/build-apk.yml` | GitHub Actions 云端自动打包配置 |
| `../nfc-app.zip` | 已打好的项目压缩包（供 Colab 上传用） |

## 打包方式对比

| 方式 | 难度 | 说明 |
|------|------|------|
| **Google Colab**（推荐） | ⭐ 最简单 | 浏览器打开笔记本，依次点运行，最后自动下载 APK。无需注册（只需 Google 账号） |
| **GitHub Actions** | ⭐⭐ | 把项目推送到 GitHub 仓库，云端自动打包，APK 在 Actions 页面下载 |
| **WSL2 本地打包** | ⭐⭐⭐ | 需下载 SDK（3-5 GB），首次 30-60 分钟，适合需要频繁打包的情况 |

### 方式一：Google Colab（推荐）

1. 打开 https://colab.research.google.com
2. "文件 → 上传笔记本"，选择本项目里的 `打包APK-Colab.ipynb`
3. 从上到下依次运行每个单元格：
   - 第 1 格：安装工具（约 2 分钟）
   - 第 2 格：上传 `nfc-app.zip`（本项目已打好，就在 `D:\xxpyhton\nfc-app.zip`）
   - 第 3 格：开始打包（首次约 25-40 分钟）
   - 第 4 格：自动下载 APK 到你的电脑
4. 把 APK 传到手机安装即可（需允许"安装未知应用"）

### 方式二：GitHub Actions 自动打包

1. 在 GitHub 上新建一个仓库
2. 把 `nfc-app` 文件夹的内容推送上去（包含 `.github/workflows/build-apk.yml`）
3. 打开仓库的 **Actions** 页面，等待自动构建完成
4. 在构建结果页底部的 **Artifacts** 下载 `nfchelper-apk`

推送到 GitHub 的命令示例：

```bash
cd D:/xxpyhton/nfc-app
git init && git add -A && git commit -m "NFC app"
git remote add origin https://github.com/<你的用户名>/nfc-app.git
git push -u origin main
```

### 方式三：WSL2 本地打包

## 打包步骤（Windows + WSL2）

### 1. 安装 WSL2（已安装可跳过）

以管理员身份打开 PowerShell：

```powershell
wsl --install -d Ubuntu
```

重启后进入 Ubuntu，设置用户名密码。

### 2. 安装依赖（在 WSL Ubuntu 中）

```bash
sudo apt update
sudo apt install -y git zip unzip openjdk-17-jdk python3-pip autoconf libtool pkg-config zlib1g-dev libncurses5-dev libncursesw5-dev libtinfo5 cmake libffi-dev libssl-dev adb
pip3 install --user buildozer cython==0.29.36
echo 'export PATH=$PATH:~/.local/bin' >> ~/.bashrc
source ~/.bashrc
```

### 3. 拷贝项目并打包

把本文件夹（`D:\xxpyhton\nfc-app`）拷到 WSL 中，例如：

```bash
cp -r /mnt/d/xxpyhton/nfc-app ~/nfc-app
cd ~/nfc-app
buildozer android debug
```

> 首次打包会自动下载 Android SDK/NDK（约 3-5 GB，耗时 30-60 分钟），请耐心等待。

成功后 APK 生成在：

```
bin/nfchelper-1.0.0-arm64-v8a-debug.apk
```

### 4. 安装到手机

用 USB 连接手机（开启"开发者选项 → USB 调试"），或直接把 APK 传到手机安装：

```bash
adb install bin/*.apk
```

### 5. 使用

1. 打开 App，确保手机 NFC 已开启
2. **读取**：手机背面贴近公交卡/门禁卡/NFC 标签 → 显示 UID 和内容
3. **写入**：切到"写入模式" → 输入文本或网址 → 点"写入下一个碰到的标签" → 贴近标签

## 常见问题

| 问题 | 解决 |
|------|------|
| `Cython` 版本报错 | 确认安装的是 `cython==0.29.36` |
| 下载 SDK 超时 | 换网络或配置代理；`~/.buildozer` 可删掉重试 |
| 手机上闪退 | `adb logcat \| grep python` 查看报错 |
| 读到 UID 但读不到内容 | 标签可能是空白卡或加密卡（如门禁卡），属正常现象 |
| 写入门禁卡失败 | 加密卡无法用 NDEF 写入，本 App 仅支持标准 NDEF 标签 |

## 注意

- 只能**读取**加密卡（如部分门禁卡/银行卡）的 UID，**无法**复制或写入加密卡
- 写入会覆盖标签原有 NDEF 数据，重要标签请先备份
