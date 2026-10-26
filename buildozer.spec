[app]
# 应用基本信息
title = NFC助手
package.name = nfchelper
package.domain = org.xxpyhton
source.dir = .
source.include_exts = py,png,jpg,kv,atlas
version = 1.1.0

# 依赖: android 模块由 python-for-android 提供 (on_new_intent 支持)
requirements = python3,kivy==2.3.0,pyjnius==1.6.1,android

# 权限与 NFC
android.permissions = NFC
android.api = 34
android.minapi = 24
android.ndk = 25b
android.archs = arm64-v8a, armeabi-v7a
android.accept_sdk_license = True

# 固定 python-for-android 版本: v2024.01.21 使用 Python 3.10 工具链,
# 与 kivy 2.3.0 的预生成 C 代码兼容 (最新 p4a master 用 Python 3.14 会编译失败)
# 注意: p4a.* 配置必须写在 [app] 区块内才会生效
p4a.branch = v2024.01.21

orientation = portrait
fullscreen = 0

# 日志 (调试时可看 python 错误)
android.logcat = True

[buildozer]
log_level = 2
warn_on_root = 1
