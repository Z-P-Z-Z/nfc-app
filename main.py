# -*- coding: utf-8 -*-
"""
NFC 助手 v1.2.0 —— Android NFC 读写 App
技术栈: Python 3.10 + Kivy 2.3.0 + pyjnius

v1.2.0 重点 (修复"贴标签毫无反应")
  1. 双通道读取:
     - 读卡模式(Reader Mode): 用 NfcAdapter.enableReaderMode + ReaderCallback,
       完全不依赖 Activity 的 Intent 派发, 标签一贴必有回调
     - 系统派发(Foreground Dispatch): 传统 on_new_intent 方式, 作为备选
  2. 修复 Intent 构造: activity.getClass() (原来误用 PythonActivity.getClass())
  3. byte[] 兼容转换: pyjnius 可能返回 bytes / 有符号 int 列表, 统一处理
  4. 诊断面板: 通道状态、回调次数、异常原文全部可见, 不再"静默失败"
  5. 启动加固 / 中文字体 / 日志落盘 沿用 v1.1.0
"""

import os
import sys
import traceback
import datetime

from kivy.app import App
from kivy.lang import Builder
from kivy.clock import Clock
from kivy.core.text import LabelBase
from kivy.core.window import Window
from kivy.core.clipboard import Clipboard
from kivy.metrics import dp
from kivy.properties import StringProperty, BooleanProperty, ListProperty
from kivy.uix.boxlayout import BoxLayout
from kivy.uix.popup import Popup
from kivy.uix.scrollview import ScrollView
from kivy.uix.label import Label

# ---------------------------------------------------------------------------
# 早期日志
# ---------------------------------------------------------------------------
LOG_LINES = []
LOG_PATH = [None]


def log(msg):
    line = '[%s] %s' % (datetime.datetime.now().strftime('%H:%M:%S'), msg)
    LOG_LINES.append(line)
    del LOG_LINES[:-800]
    try:
        print(line)
    except Exception:
        pass
    if LOG_PATH[0]:
        try:
            with open(LOG_PATH[0], 'a', encoding='utf-8') as f:
                f.write(line + '\n')
        except Exception:
            pass


def log_exc(prefix):
    log('%s: %s' % (prefix, traceback.format_exc().replace('\n', ' | ')))


def err_text(exc_or_tb=None):
    """取异常最后一行, 便于在状态栏简短显示"""
    tb = exc_or_tb or traceback.format_exc()
    lines = [l for l in str(tb).strip().split('\n') if l.strip()]
    return lines[-1] if lines else '未知错误'


# ---------------------------------------------------------------------------
# 环境
# ---------------------------------------------------------------------------
try:
    from kivy.utils import platform as _platform
    IS_ANDROID = (_platform == 'android')
except Exception:
    IS_ANDROID = False

autoclass = None
PythonActivity = None
ActivityRef = None
PythonJavaClass = None
java_method = None


def _init_android_bridge():
    """导入 jnius / android 模块并准备日志路径; 返回错误字符串(空串=成功)"""
    global autoclass, PythonActivity, ActivityRef, PythonJavaClass, java_method
    if not IS_ANDROID:
        return ''
    try:
        from jnius import autoclass as _autoclass, PythonJavaClass as _PJC, java_method as _jm
        autoclass = _autoclass
        PythonJavaClass = _PJC
        java_method = _jm
        PythonActivity = autoclass('org.kivy.android.PythonActivity')
        log('PythonActivity 已加载')

        try:
            activity = PythonActivity.mActivity
            target_dir = None
            ext = activity.getExternalFilesDir(None)
            if ext is not None:
                target_dir = str(ext.getAbsolutePath())
            if not target_dir:
                target_dir = str(activity.getFilesDir().getAbsolutePath())
            if not os.path.isdir(target_dir):
                os.makedirs(target_dir, exist_ok=True)
            LOG_PATH[0] = os.path.join(target_dir, 'nfc_log.txt')
            log('日志文件: %s' % LOG_PATH[0])
        except Exception:
            log_exc('准备日志目录失败')

        try:
            from android import activity as _activity
            ActivityRef = _activity
            log('android.activity 已加载')
        except Exception:
            log_exc('android.activity 导入失败')
        return ''
    except Exception:
        log_exc('安卓桥接初始化失败')
        return traceback.format_exc()


# 中文字体候选
FONT_CANDIDATES = [
    '/system/fonts/NotoSansSC-Regular.otf',
    '/system/fonts/NotoSansCJK-Regular.ttc',
    '/system/fonts/NotoSansHans-Regular.otf',
    '/system/fonts/DroidSansFallback.ttf',
    '/system/fonts/DroidSansChinese.ttf',
    'C:/Windows/Fonts/msyh.ttc',
    'C:/Windows/Fonts/msyh.ttf',
    'C:/Windows/Fonts/simhei.ttf',
]


def register_cjk_font():
    for path in FONT_CANDIDATES:
        try:
            if os.path.exists(path):
                LabelBase.register(name='CJK', fn_regular=path)
                log('已加载中文字体: %s' % path)
                return 'CJK'
        except Exception:
            log_exc('字体加载失败 %s' % path)
    log('未找到中文字体, 使用默认字体')
    return 'Roboto'


# NDEF URI 前缀表
URI_PREFIXES = [
    '', 'http://www.', 'https://www.', 'http://', 'https://', 'tel:', 'mailto:',
    'ftp://anonymous:anonymous@', 'ftp://ftp.', 'ftps://', 'sftp://', 'smb://',
    'nfs://', 'ftp://', 'dav://', 'news:', 'telnet://', 'imap:', 'rtsp://',
    'urn:', 'pop:', 'sip:', 'sips:', 'tftp:', 'btspp://', 'btl2cap://',
    'btgoep://', 'tcpobex://', 'irdaobex://', 'file://', 'urn:epc:id:',
    'urn:epc:tag:', 'urn:epc:pat:', 'urn:epc:raw:', 'urn:epc:', 'urn:nfc:',
]


def to_bytes(obj):
    """把 pyjnius 可能给出的各种 byte[] 形式统一转成 Python bytes
       (可能是 bytes / bytearray / 有符号 int 列表 / Java 数组代理)"""
    if obj is None:
        return b''
    if isinstance(obj, (bytes, bytearray)):
        return bytes(obj)
    out = bytearray()
    try:
        n = len(obj)
    except Exception:
        return b''
    for i in range(n):
        try:
            v = obj[i]
        except Exception:
            break
        if isinstance(v, (bytes, bytearray)):
            out += bytes(v)
            continue
        try:
            out.append(int(v) & 0xFF)
        except Exception:
            pass
    return bytes(out)


# ---------------------------------------------------------------------------
# Reader Mode 回调 (Python 实现 Java 接口)
# ---------------------------------------------------------------------------
if IS_ANDROID:
    from jnius import PythonJavaClass as _PJC_BASE, java_method as _java_method

    class ReaderCallback(_PJC_BASE):
        __javainterfaces__ = ['android/nfc/NfcAdapter$ReaderCallback']
        __javacontext__ = 'app'

        def __init__(self, on_tag):
            _PJC_BASE.__init__(self)
            self._on_tag = on_tag

        @_java_method('(Landroid/nfc/Tag;)V')
        def onTagDiscovered(self, tag):
            try:
                self._on_tag(tag)
            except Exception:
                log_exc('读卡回调处理异常')
else:
    ReaderCallback = None


# ---------------------------------------------------------------------------
# NFC 管理
# ---------------------------------------------------------------------------
CH_READER = 'reader'     # 读卡模式: enableReaderMode, 不依赖 Intent
CH_INTENT = 'intent'     # 系统派发: enableForegroundDispatch + on_new_intent


class NfcManager(object):
    def __init__(self, on_event):
        self.on_event = on_event
        self.ready = False
        self.adapter = None
        self.activity = None
        self.write_armed = False
        self.write_text = ''
        self.write_url = ''
        self._classes = {}
        self._reader_cb = None
        self.channel = CH_READER
        self.channel_ok = False
        self.channel_error = ''
        self.tag_count = 0
        self.intent_count = 0
        self.last_error = ''

    # ---------------- 初始化 ----------------
    def init(self):
        if not IS_ANDROID or autoclass is None:
            return False, '非安卓环境'
        try:
            c = self._classes
            c['NfcAdapter'] = autoclass('android.nfc.NfcAdapter')
            c['Intent'] = autoclass('android.content.Intent')
            c['IntentFilter'] = autoclass('android.content.IntentFilter')
            c['PendingIntent'] = autoclass('android.app.PendingIntent')
            c['Bundle'] = autoclass('android.os.Bundle')
            c['Ndef'] = autoclass('android.nfc.tech.Ndef')
            c['NdefFormatable'] = autoclass('android.nfc.tech.NdefFormatable')
            c['NdefRecord'] = autoclass('android.nfc.NdefRecord')
            c['NdefMessage'] = autoclass('android.nfc.NdefMessage')
            self.activity = PythonActivity.mActivity
            self.adapter = c['NfcAdapter'].getDefaultAdapter(self.activity)
            self.ready = True
            log('NFC 适配器: %s' % ('已就绪' if self.adapter is not None else '无硬件'))
            if ActivityRef is not None:
                try:
                    ActivityRef.bind(on_new_intent=self._on_new_intent)
                    log('已绑定 on_new_intent 回调')
                except Exception:
                    log_exc('绑定 on_new_intent 失败')
            return True, ''
        except Exception:
            log_exc('NFC 初始化失败')
            return False, traceback.format_exc()

    def has_hardware(self):
        return self.adapter is not None

    def is_enabled(self):
        try:
            return self.adapter is not None and bool(self.adapter.isEnabled())
        except Exception:
            log_exc('查询 NFC 状态失败')
            return False

    # ---------------- 通道控制 ----------------
    def start(self, channel=None):
        """开启读取通道; 返回 (ok, message)"""
        if channel:
            self.channel = channel
        if not self.ready or self.adapter is None:
            return False, 'NFC 未就绪'
        self.stop()
        if self.channel == CH_READER:
            ok, msg = self._start_reader()
            if not ok:
                # 读卡模式失败 → 自动退回系统派发
                log('读卡模式失败, 自动改用系统派发: %s' % msg)
                self.channel = CH_INTENT
                ok2, msg2 = self._start_dispatch()
                if not ok2:
                    self.channel_error = '%s | %s' % (msg, msg2)
                    return False, self.channel_error
                self.channel_ok = True
                self.channel_error = ''
                return True, '系统派发'
            self.channel_ok = True
            self.channel_error = ''
            return True, '读卡模式'
        ok, msg = self._start_dispatch()
        if not ok:
            log('系统派发失败, 自动改用读卡模式: %s' % msg)
            self.channel = CH_READER
            ok2, msg2 = self._start_reader()
            if not ok2:
                self.channel_error = '%s | %s' % (msg, msg2)
                return False, self.channel_error
            self.channel_ok = True
            self.channel_error = ''
            return True, '读卡模式'
        self.channel_ok = True
        self.channel_error = ''
        return True, '系统派发'

    def stop(self):
        try:
            if self.ready and self.adapter is not None:
                self.adapter.disableForegroundDispatch(self.activity)
        except Exception:
            pass
        try:
            if self._reader_cb is not None and self.adapter is not None:
                self.adapter.disableReaderMode(self.activity)
                log('读卡模式已关闭')
        except Exception:
            log_exc('关闭读卡模式失败')
        self.channel_ok = False

    def _start_reader(self):
        try:
            c = self._classes
            flags = 0
            for name in ('FLAG_READER_NFC_A', 'FLAG_READER_NFC_B',
                         'FLAG_READER_NFC_F', 'FLAG_READER_NFC_V',
                         'FLAG_READER_NFC_BARCODE', 'FLAG_READER_SKIP_NDEF_CHECK'):
                try:
                    flags |= int(getattr(c['NfcAdapter'], name))
                except Exception:
                    pass
            if not flags:
                flags = 0x1 | 0x2 | 0x4 | 0x8
            self._reader_cb = ReaderCallback(self._on_tag_from_reader)
            self.adapter.enableReaderMode(self.activity, self._reader_cb,
                                          flags, c['Bundle']())
            log('读卡模式已开启 (flags=0x%X)' % flags)
            return True, ''
        except Exception:
            log_exc('开启读卡模式失败')
            return False, err_text()

    def _start_dispatch(self):
        try:
            c = self._classes
            # 关键修复: 必须用 activity 实例的 getClass(), 不能用 PythonActivity.getClass()
            intent = c['Intent'](self.activity, self.activity.getClass())
            intent.setFlags(c['Intent'].FLAG_ACTIVITY_SINGLE_TOP)

            flags = c['PendingIntent'].FLAG_UPDATE_CURRENT
            try:
                flags = flags | c['PendingIntent'].FLAG_MUTABLE
            except Exception:
                pass
            pending = c['PendingIntent'].getActivity(self.activity, 0, intent, flags)

            filters = []
            try:
                f = c['IntentFilter'](c['NfcAdapter'].ACTION_NDEF_DISCOVERED)
                f.addCategory(c['Intent'].CATEGORY_DEFAULT)
                try:
                    f.addDataType('*/*')
                except Exception:
                    log_exc('addDataType 失败(忽略)')
                filters.append(f)
            except Exception:
                log_exc('构造 NDEF IntentFilter 失败')
            try:
                f2 = c['IntentFilter'](c['NfcAdapter'].ACTION_TAG_DISCOVERED)
                f2.addCategory(c['Intent'].CATEGORY_DEFAULT)
                filters.append(f2)
            except Exception:
                log_exc('构造 TAG IntentFilter 失败')

            self.adapter.enableForegroundDispatch(
                self.activity, pending, filters, [])
            log('前台调度已开启 (%d 个 filter)' % len(filters))
            return True, ''
        except Exception:
            log_exc('开启前台调度失败')
            return False, err_text()

    def toggle_channel(self):
        new = CH_INTENT if self.channel == CH_READER else CH_READER
        ok, msg = self.start(new)
        self.on_event({'event': 'channel', 'channel': self.channel,
                       'ok': ok, 'message': msg})
        return ok

    def channel_name(self):
        return '读卡模式' if self.channel == CH_READER else '系统派发'

    def arm_write(self, text='', url=''):
        self.write_armed = True
        self.write_text = text or ''
        self.write_url = url or ''
        self.on_event({'event': 'info',
                       'message': '已就绪，请把手机背面贴近 NFC 标签…'})

    # ---------------- 标签入口 ----------------
    def _on_tag_from_reader(self, tag):
        self.intent_count += 1
        try:
            self._handle_tag(tag, None, source='读卡模式')
        except Exception:
            log_exc('读卡模式处理标签失败')
            self.on_event({'event': 'error',
                           'message': '处理标签失败：%s' % err_text()})

    def _on_new_intent(self, intent):
        self.intent_count += 1
        log('收到 NFC Intent (#%d)' % self.intent_count)
        try:
            c = self._classes
            tag = intent.getParcelableExtra(c['NfcAdapter'].EXTRA_TAG)
            if tag is None:
                self.on_event({'event': 'error',
                               'message': '系统派发未携带 Tag（试试切到读卡模式）'})
                return
            msgs = None
            try:
                msgs = intent.getParcelableArrayExtra(c['NfcAdapter'].EXTRA_NDEF_MESSAGES)
            except Exception:
                log_exc('读取 EXTRA_NDEF_MESSAGES 失败')
            self._handle_tag(tag, msgs, source='系统派发')
        except Exception:
            log_exc('处理 NFC Intent 失败')
            self.on_event({'event': 'error',
                           'message': '处理标签失败：%s' % err_text()})

    # ---------------- 统一处理 ----------------
    def _handle_tag(self, tag, ndef_msgs, source=''):
        self.tag_count += 1
        log('标签事件 #%d (%s)' % (self.tag_count, source))

        uid_hex = '未知'
        try:
            raw = to_bytes(tag.getId())
            if raw:
                uid_hex = ':'.join('%02X' % b for b in raw)
        except Exception:
            log_exc('读取 UID 失败')

        tech_list = ''
        try:
            techs = tag.getTechList()
            names = [str(t).split('.')[-1] for t in techs] if techs else []
            tech_list = ', '.join(names)
        except Exception:
            log_exc('读取技术列表失败')

        if self.write_armed:
            self.write_armed = False
            try:
                self._write_tag(tag)
                target = self.write_url or self.write_text
                self.on_event({'event': 'write', 'uid': uid_hex,
                               'message': '已写入: %s' % target})
            except Exception:
                log_exc('写入失败')
                self.on_event({'event': 'error',
                               'message': '写入失败: %s' % err_text()})
            return

        records = []
        if ndef_msgs:
            for m in ndef_msgs:
                try:
                    for rec in m.getRecords():
                        records.append(self._parse_record(rec))
                except Exception:
                    log_exc('解析 NDEF 消息失败')
        if not records:
            records = self._read_from_tag(tag)

        self.on_event({'event': 'read', 'uid': uid_hex, 'tech': tech_list,
                       'records': records, 'source': source})

    def _read_from_tag(self, tag):
        """直接连标签读 NDEF (读卡模式下唯一途径)"""
        c = self._classes
        ndef = None
        try:
            ndef = c['Ndef'].get(tag)
        except Exception:
            log_exc('获取 Ndef 失败')
        if ndef is None:
            return [('提示', '该标签不含 NDEF 数据（仅能读出 UID 与技术类型）')]

        connected = False
        try:
            ndef.connect()
            connected = True
        except Exception:
            log_exc('连接标签失败')

        msg = None
        try:
            msg = ndef.getCachedNdefMessage()
        except Exception:
            log_exc('getCachedNdefMessage 失败')
        if msg is None:
            try:
                msg = ndef.getNdefMessage()
            except Exception:
                log_exc('getNdefMessage 失败')
        if connected:
            try:
                ndef.close()
            except Exception:
                pass

        if msg is None:
            return [('提示', '标签可连接，但其中没有 NDEF 数据')]
        out = []
        try:
            for r in msg.getRecords():
                out.append(self._parse_record(r))
        except Exception:
            log_exc('遍历 NDEF 记录失败')
        return out or [('提示', 'NDEF 消息为空')]

    def _parse_record(self, rec):
        tnf = 0
        rtype = ''
        try:
            tnf = int(rec.getTnf())
            rtype = to_bytes(rec.getType()).decode('ascii', 'replace')
        except Exception:
            pass
        try:
            payload = to_bytes(rec.getPayload())
        except Exception:
            payload = b''

        try:
            if tnf == 1 and rtype == 'T' and payload:
                status = payload[0]
                lang_len = status & 0x3F
                enc = 'utf-16-be' if (status & 0x80) else 'utf-8'
                return ('文本', payload[1 + lang_len:].decode(enc, 'replace'))
            if tnf == 1 and rtype == 'U' and payload:
                idx = payload[0]
                prefix = URI_PREFIXES[idx] if idx < len(URI_PREFIXES) else ''
                return ('网址', prefix + payload[1:].decode('utf-8', 'replace'))
            if tnf == 0:
                return ('空白', '(空记录)')
            if tnf == 1 and rtype in ('Sp', 'Ss') and payload:
                return ('智能海报', payload.decode('utf-8', 'replace'))
            if tnf == 2 and rtype == 'android.com:pkg' and payload:
                return ('安卓应用', payload.decode('utf-8', 'replace'))
        except Exception:
            log_exc('解析单条记录失败')

        return ('数据', 'TNF=%s  类型=%s\n十六进制: %s'
                % (tnf, rtype or '(无)', payload[:64].hex() or '(空)'))

    def _write_tag(self, tag):
        c = self._classes
        if self.write_url:
            record = c['NdefRecord'].createUri(self.write_url)
        else:
            record = c['NdefRecord'].createTextRecord('zh', self.write_text)
        message = c['NdefMessage']([record])
        size = int(message.getByteArrayLength())

        ndef = c['Ndef'].get(tag)
        if ndef is not None:
            ndef.connect()
            try:
                if not ndef.isWritable():
                    raise RuntimeError('标签已设为只读')
                max_size = int(ndef.getMaxSize())
                if max_size < size:
                    raise RuntimeError('标签容量不足 (需要 %d, 可用 %d 字节)'
                                       % (size, max_size))
                ndef.writeNdefMessage(message)
                log('写入成功, %d 字节' % size)
            finally:
                try:
                    ndef.close()
                except Exception:
                    pass
            return

        fmt = c['NdefFormatable'].get(tag)
        if fmt is not None:
            fmt.connect()
            try:
                fmt.format(message)
                log('格式化并写入成功, %d 字节' % size)
            finally:
                try:
                    fmt.close()
                except Exception:
                    pass
            return

        raise RuntimeError('该标签不支持 NDEF 写入（可能是加密卡或只读卡）')

    # ---------------- 诊断 ----------------
    def diag_lines(self):
        c = self._classes
        enabled = '—'
        try:
            enabled = '是' if self.is_enabled() else '否'
        except Exception:
            pass
        return [
            '—— 诊断信息 ——',
            '安卓桥接: %s' % ('OK' if autoclass is not None else '失败'),
            '适配器: %s' % ('存在' if self.adapter is not None else '无'),
            '系统 NFC 开关: %s' % enabled,
            '当前通道: %s' % self.channel_name(),
            '通道状态: %s' % ('已开启' if self.channel_ok else '未开启'),
            '通道异常: %s' % (self.channel_error or '无'),
            '收到事件: %d 次 (标签 %d)' % (self.intent_count, self.tag_count),
            '日志文件: %s' % (LOG_PATH[0] or '不可用'),
            '————————————————',
        ]


# ---------------------------------------------------------------------------
# 界面
# ---------------------------------------------------------------------------
KV = '''
#:import dp kivy.metrics.dp

<Card@BoxLayout>:
    orientation: 'vertical'
    size_hint_y: None
    padding: dp(14), dp(12), dp(14), dp(12)
    spacing: dp(9)
    canvas.before:
        Color:
            rgba: 0.105, 0.118, 0.145, 1
        RoundedRectangle:
            pos: self.pos
            size: self.size
            radius: [dp(16)]
        Color:
            rgba: 1, 1, 1, 0.06
        Line:
            rounded_rectangle: self.x, self.y, self.width, self.height, dp(16)
            width: 1

<Seg@ToggleButton>:
    background_normal: ''
    background_color: 0, 0, 0, 0
    font_name: app.font_name
    font_size: dp(15)
    color: (1, 1, 1, 1) if self.state == 'down' else (0.62, 0.67, 0.76, 1)
    canvas.before:
        Color:
            rgba: (0.24, 0.58, 1, 0.30) if self.state == 'down' else (1, 1, 1, 0.05)
        RoundedRectangle:
            pos: self.pos
            size: self.size
            radius: [dp(11)]
        Color:
            rgba: (0.32, 0.66, 1, 1) if self.state == 'down' else (0, 0, 0, 0)
        Line:
            rounded_rectangle: self.x, self.y, self.width, self.height, dp(11)
            width: 1.1

<Primary@Button>:
    background_normal: ''
    background_color: 0, 0, 0, 0
    color: 1, 1, 1, 1
    bold: True
    font_name: app.font_name
    font_size: dp(16)
    canvas.before:
        Color:
            rgba: (0.24, 0.58, 1, 1) if self.state == 'normal' else (0.17, 0.42, 0.76, 1)
        RoundedRectangle:
            pos: self.pos
            size: self.size
            radius: [dp(13)]

<Ghost@Button>:
    background_normal: ''
    background_color: 0, 0, 0, 0
    color: 0.74, 0.78, 0.86, 1
    font_name: app.font_name
    font_size: dp(12.5)
    canvas.before:
        Color:
            rgba: (1, 1, 1, 0.07) if self.state == 'normal' else (1, 1, 1, 0.15)
        RoundedRectangle:
            pos: self.pos
            size: self.size
            radius: [dp(10)]

<Field@TextInput>:
    background_color: 0, 0, 0, 0
    foreground_color: 0.95, 0.96, 1, 1
    hint_text_color: 0.45, 0.51, 0.60, 1
    cursor_color: 0.32, 0.66, 1, 1
    selection_color: 0.24, 0.58, 1, 0.35
    font_name: app.font_name
    font_size: dp(15)
    padding: dp(13), dp(11), dp(13), dp(11)
    multiline: False
    write_tab: False
    size_hint_y: None
    height: dp(48)
    canvas.before:
        Color:
            rgba: 0.062, 0.072, 0.094, 1
        RoundedRectangle:
            pos: self.pos
            size: self.size
            radius: [dp(12)]
        Color:
            rgba: (0.30, 0.64, 1, 1) if self.focus else (1, 1, 1, 0.09)
        Line:
            rounded_rectangle: self.x, self.y, self.width, self.height, dp(12)
            width: 1.1

<Root>:
    orientation: 'vertical'
    padding: dp(16), 0, dp(16), dp(8)
    spacing: dp(9)
    canvas.before:
        Color:
            rgba: 0.052, 0.059, 0.075, 1
        Rectangle:
            pos: self.pos
            size: self.size

    BoxLayout:
        orientation: 'vertical'
        size_hint_y: None
        height: dp(62)
        spacing: dp(2)
        Label:
            text: 'NFC 助手'
            font_name: app.font_name
            font_size: dp(22)
            bold: True
            color: 0.96, 0.97, 1, 1
            text_size: self.size
            halign: 'left'
            valign: 'middle'
        Label:
            text: '读取 / 写入 NFC 标签'
            font_name: app.font_name
            font_size: dp(12)
            color: 0.52, 0.58, 0.68, 1
            text_size: self.size
            halign: 'left'
            valign: 'middle'

    BoxLayout:
        size_hint_y: None
        height: dp(50)
        padding: dp(14), dp(6), dp(14), dp(6)
        canvas.before:
            Color:
                rgba: root.banner_bg
            RoundedRectangle:
                pos: self.pos
                size: self.size
                radius: [dp(12)]
        Label:
            text: root.status_text
            font_name: app.font_name
            font_size: dp(13)
            color: root.banner_fg
            text_size: self.width, None
            halign: 'left'
            valign: 'middle'

    BoxLayout:
        size_hint_y: None
        height: dp(44)
        spacing: dp(10)
        Seg:
            text: '读取'
            state: 'down' if not root.write_mode else 'normal'
            on_release: root.set_mode('read')
        Seg:
            text: '写入'
            state: 'down' if root.write_mode else 'normal'
            on_release: root.set_mode('write')

    BoxLayout:
        size_hint_y: None
        height: dp(32)
        spacing: dp(8)
        Ghost:
            text: '通道: ' + root.channel_label
            on_release: root.toggle_channel()
        Ghost:
            text: '诊断'
            size_hint_x: None
            width: dp(70)
            on_release: root.show_log()

    Card:
        opacity: 1 if root.write_mode else 0
        disabled: not root.write_mode
        height: (dp(196) if root.write_mode else 0)
        BoxLayout:
            size_hint_y: None
            height: dp(22)
            Label:
                text: '写入内容'
                font_name: app.font_name
                font_size: dp(13.5)
                bold: True
                color: 0.80, 0.84, 0.92, 1
                text_size: self.size
                halign: 'left'
                valign: 'middle'
            Label:
                text: root.byte_hint
                font_name: app.font_name
                font_size: dp(11.5)
                color: 0.45, 0.51, 0.62, 1
                text_size: self.size
                halign: 'right'
                valign: 'middle'
        Field:
            id: txt_input
            hint_text: '文本，或以 http 开头的网址'
            on_text: root.update_hint(self.text)
        BoxLayout:
            size_hint_y: None
            height: dp(46)
            spacing: dp(10)
            Primary:
                text: '写入下一个标签'
                on_release: root.arm_write()
            Ghost:
                text: '清空'
                size_hint_x: None
                width: dp(66)
                on_release: root.clear_inputs()

    Card:
        size_hint_y: 1
        BoxLayout:
            size_hint_y: None
            height: dp(28)
            spacing: dp(8)
            Label:
                text: root.result_title
                font_name: app.font_name
                font_size: dp(13.5)
                bold: True
                color: 0.80, 0.84, 0.92, 1
                text_size: self.size
                halign: 'left'
                valign: 'middle'
            Ghost:
                text: '复制'
                size_hint_x: None
                width: dp(54)
                height: dp(26)
                on_release: root.copy_result()
        ScrollView:
            do_scroll_x: False
            bar_width: dp(3)
            Label:
                id: output
                text: root.output_text
                font_name: app.font_name
                font_size: dp(14)
                color: 0.86, 0.89, 0.95, 1
                size_hint_y: None
                height: self.texture_size[1] if self.texture_size[1] > dp(40) else dp(40)
                text_size: self.width, None
                valign: 'top'
                halign: 'left'
'''


class Root(BoxLayout):
    status_text = StringProperty('正在启动…')
    status_kind = StringProperty('info')
    banner_bg = ListProperty([0.16, 0.30, 0.52, 0.55])
    banner_fg = ListProperty([0.78, 0.86, 1.0, 1.0])
    output_text = StringProperty('')
    result_title = StringProperty('读取结果')
    write_mode = BooleanProperty(False)
    byte_hint = StringProperty('')
    channel_label = StringProperty('读卡模式')

    def set_status(self, text, kind='info'):
        self.status_text = text
        self.status_kind = kind
        if kind == 'ok':
            self.banner_bg = [0.09, 0.40, 0.27, 0.60]
            self.banner_fg = [0.62, 0.94, 0.76, 1]
        elif kind == 'err':
            self.banner_bg = [0.52, 0.15, 0.17, 0.60]
            self.banner_fg = [1.0, 0.72, 0.72, 1]
        else:
            self.banner_bg = [0.15, 0.29, 0.50, 0.60]
            self.banner_fg = [0.78, 0.86, 1.0, 1]

    def set_mode(self, mode):
        self.write_mode = (mode == 'write')
        app = App.get_running_app()
        if self.write_mode:
            self.result_title = '写入记录'
            self.set_status('写入模式：填好内容后点「写入下一个标签」', 'info')
        else:
            self.result_title = '读取结果'
            if getattr(app, 'nfc_ready', False):
                self.set_status('读取模式：把标签贴到手机背面中心', 'info')
            else:
                self.set_status('NFC 不可用：请确认手机支持并已开启 NFC', 'err')

    def update_hint(self, text):
        text = (text or '').strip()
        if not text:
            self.byte_hint = ''
        elif text.startswith('http://') or text.startswith('https://'):
            self.byte_hint = '按网址写入'
        else:
            self.byte_hint = '约 %d 字节' % (len(text.encode('utf-8')) + 7)

    def clear_inputs(self):
        self.ids.txt_input.text = ''
        self.byte_hint = ''

    def arm_write(self):
        text = self.ids.txt_input.text.strip()
        if not text:
            self.set_status('请先输入要写入的内容', 'err')
            return
        app = App.get_running_app()
        nfc = getattr(app, 'nfc', None)
        if not getattr(app, 'nfc_ready', False) or nfc is None:
            self.set_status('NFC 不可用，无法写入', 'err')
            return
        if text.startswith('http://') or text.startswith('https://'):
            nfc.arm_write(url=text)
        else:
            nfc.arm_write(text=text)

    def toggle_channel(self):
        app = App.get_running_app()
        nfc = getattr(app, 'nfc', None)
        if nfc is None or not getattr(app, 'nfc_ready', False):
            self.set_status('NFC 不可用，无法切换通道', 'err')
            return
        nfc.toggle_channel()

    def copy_result(self):
        try:
            Clipboard.copy(self.output_text or '')
            self.set_status('已复制到剪贴板', 'ok')
        except Exception:
            self.set_status('复制失败', 'err')

    def show_log(self):
        try:
            app = App.get_running_app()
            nfc = getattr(app, 'nfc', None)
            head = []
            if nfc is not None:
                try:
                    head = nfc.diag_lines()
                except Exception:
                    head = ['(诊断信息获取失败)']
            body = '\n'.join(head + LOG_LINES[-120:]) or '(暂无日志)'
            content = BoxLayout(orientation='vertical', padding=dp(8), spacing=dp(6))
            sc = ScrollView(bar_width=dp(3))
            lbl = Label(text=body,
                        size_hint_y=None,
                        font_name=getattr(app, 'font_name', 'Roboto'),
                        font_size=dp(11),
                        color=(0.85, 0.88, 0.94, 1),
                        text_size=(dp(300), None),
                        halign='left', valign='top')
            lbl.bind(texture_size=lambda inst, val:
                     setattr(inst, 'height', val[1]))
            sc.add_widget(lbl)
            content.add_widget(sc)
            Popup(title=' 诊断 / 日志 ', content=content,
                  size_hint=(0.94, 0.82)).open()
        except Exception:
            log_exc('打开日志窗口失败')
            self.set_status('日志窗口打开失败', 'err')


# ---------------------------------------------------------------------------
# App
# ---------------------------------------------------------------------------
class NfcApp(App):
    title = 'NFC Helper'
    font_name = StringProperty('Roboto')
    _start_tries = 0

    def build(self):
        log('===== 应用启动 v1.2.0 =====')
        try:
            self.font_name = register_cjk_font()
        except Exception:
            log_exc('字体注册失败')

        try:
            Window.softinput_mode = 'below_target'
            Window.bind(on_keyboard=self._on_keyboard)
        except Exception:
            log_exc('Window 设置失败')

        self.nfc = None
        self.nfc_ready = False
        try:
            self.nfc = NfcManager(self.on_nfc_event)
        except Exception:
            log_exc('创建 NfcManager 失败')

        try:
            # Builder.load_string() 在 KV 只含 <Root>: 类规则时返回 None,
            # 必须先注册规则再显式实例化
            Builder.load_string(KV)
            self.root_widget = Root()
        except Exception:
            log_exc('界面加载失败')
            self.root_widget = self._fallback_ui()
        return self.root_widget

    def _fallback_ui(self):
        box = BoxLayout(orientation='vertical', padding=dp(16))
        lbl = Label(text='界面加载失败，请把这段内容反馈：\n\n%s'
                         % traceback.format_exc()[-1500:],
                    font_name=self.font_name, font_size=dp(12),
                    color=(1, 0.7, 0.7, 1), halign='left', valign='top')
        lbl.bind(size=lambda inst, val: setattr(inst, 'text_size', val))
        box.add_widget(lbl)
        return box

    def on_start(self):
        try:
            self._boot_android()
        except Exception:
            log_exc('启动流程异常')
            try:
                self.root_widget.set_status('启动失败（点诊断查看详情）', 'err')
            except Exception:
                pass

    def _boot_android(self):
        root = self.root_widget
        if not IS_ANDROID:
            root.set_status('桌面演示模式（装到手机上才能读写 NFC）', 'info')
            root.output_text = ('当前在电脑上运行，没有 NFC 硬件。\n\n'
                                '把 APK 装到手机上并打开 NFC 即可读写标签。')
            return

        err = _init_android_bridge()
        if err:
            root.set_status('安卓环境初始化失败（点诊断查看）', 'err')
            root.output_text = err[-900:]
            return

        if self.nfc is None:
            root.set_status('NFC 模块未能创建（点诊断查看）', 'err')
            return

        ok, err = self.nfc.init()
        if not ok:
            root.set_status('NFC 初始化失败（点诊断查看）', 'err')
            root.output_text = (err or '')[-900:]
            return

        if not self.nfc.has_hardware():
            root.set_status('这台手机没有 NFC 硬件', 'err')
            root.output_text = '系统未提供 NFC 适配器。'
            return

        self.nfc_ready = True
        enabled = self.nfc.is_enabled()
        root.channel_label = self.nfc.channel_name()
        self._try_start_channel(attempt=0)

        if enabled:
            if self.nfc.channel_ok:
                root.set_status('NFC 已就绪（%s）：把标签贴到手机背部'
                                % self.nfc.channel_name(), 'ok')
                root.output_text = ('等待 NFC 标签…\n\n'
                                    '• 读取：贴上去即可读出 UID 与内容\n'
                                    '• 无反应时：点上方「通道」切换另一种读取方式\n'
                                    '• 仍无反应：点「诊断」把信息发给我')
            else:
                root.set_status('读取通道开启失败（点诊断查看）', 'err')
                root.output_text = ('两种读取通道都没能开启：\n\n%s'
                                    % (self.nfc.channel_error or ''))
        else:
            root.set_status('NFC 未开启：请到系统设置打开 NFC', 'err')
            root.output_text = ('系统 NFC 开关处于关闭状态。\n'
                                '请下拉通知栏，或进入「设置 → 连接 → NFC」开启，'
                                '然后回到本页。')

    def _try_start_channel(self, attempt=0):
        """Activity 可能还没完全 resume, 失败就延迟重试几次"""
        if self.nfc is None:
            return
        try:
            ok, msg = self.nfc.start()
        except Exception:
            log_exc('启动读取通道异常')
            ok, msg = False, err_text()
        self.root_widget.channel_label = self.nfc.channel_name()
        if ok:
            log('读取通道就绪: %s' % msg)
            try:
                self.root_widget.set_status(
                    'NFC 已就绪（%s）：把标签贴到手机背部' % msg, 'ok')
            except Exception:
                pass
            return
        log('第 %d 次开启通道失败: %s' % (attempt + 1, msg))
        if attempt < 3:
            Clock.schedule_once(
                lambda dt: self._try_start_channel(attempt + 1), 1.2)
        else:
            try:
                self.root_widget.set_status('读取通道开启失败（点诊断查看）', 'err')
                self.root_widget.output_text = ('通道异常：\n\n%s\n\n'
                                                '可点上方「通道」再试一次。' % msg)
            except Exception:
                pass

    def on_pause(self):
        return True

    def on_resume(self):
        try:
            if self.nfc_ready and self.nfc is not None:
                # 恢复前台后通道需要重新开启 (系统会在暂停时自动关闭)
                self._try_start_channel(attempt=0)
        except Exception:
            log_exc('恢复时重开通道失败')

    def on_stop(self):
        try:
            if self.nfc is not None:
                self.nfc.stop()
        except Exception:
            pass
        log('===== 应用退出 =====')

    def _on_keyboard(self, window, key, *largs):
        if key == 27:
            try:
                if self.root_widget.write_mode:
                    self.root_widget.set_mode('read')
                    return True
            except Exception:
                pass
        return False

    # ---- NFC 事件回调 (可能来自非主线程) ----
    def on_nfc_event(self, event):
        def _apply():
            try:
                root = self.root_widget
                kind = event.get('event')
                if kind == 'read':
                    root.result_title = '读取结果'
                    root.set_status('读取成功 ✔（%s）' % event.get('source', ''),
                                    'ok')
                    lines = ['标签 UID: %s' % event.get('uid', '—'), '']
                    if event.get('tech'):
                        lines += ['支持技术: %s' % event['tech'], '']
                    recs = event.get('records', [])
                    if not recs:
                        lines.append('（标签内没有 NDEF 数据）')
                    for i, item in enumerate(recs, 1):
                        rtype, content = item
                        lines.append('[%d] %s' % (i, rtype))
                        lines.append(content)
                        lines.append('')
                    root.output_text = '\n'.join(lines).strip()
                elif kind == 'write':
                    root.result_title = '写入记录'
                    root.set_status('写入成功 ✔', 'ok')
                    root.output_text = ('标签 UID: %s\n\n%s'
                                        % (event.get('uid', '—'),
                                           event.get('message', '')))
                elif kind == 'channel':
                    root.channel_label = self.nfc.channel_name()
                    if event.get('ok'):
                        root.set_status('已切换到「%s」，再贴一次标签试试'
                                        % event.get('message', ''), 'ok')
                    else:
                        root.set_status('切换失败：%s' % event.get('message', ''), 'err')
                elif kind == 'error':
                    root.set_status('出错：%s' % event.get('message', ''), 'err')
                else:
                    root.set_status(event.get('message', ''), 'info')
            except Exception:
                log_exc('刷新界面失败')

        Clock.schedule_once(lambda dt: _apply(), 0)


def main():
    try:
        NfcApp().run()
    except Exception:
        log_exc('主循环异常退出')
        raise


if __name__ == '__main__':
    main()
