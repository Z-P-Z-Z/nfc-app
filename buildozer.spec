[app]
# 应用基本信息
title = NFC助手
package.name = nfchelper
package.domain = org.xxpyhton
source.dir = .
source.include_exts = py,png,jpg,kv,atlas
version = 1.0.0

# 依赖: android 模块由 python-for-android 提供 (on_new_intent 支持)
requirements = python3,kivy==2.3.0,pyjnius==1.6.1,android

# 权限与 NFC
android.permissions = NFC
android.api = 34
android.minapi = 24
android.ndk = 26b
android.archs = arm64-v8a, armeabi-v7a
android.accept_sdk_license = True

orientation = portrait
fullscreen = 0

# 日志 (调试时可看 python 错误)
android.logcat = True

[buildozer]
log_level = 2
warn_on_root = 1
