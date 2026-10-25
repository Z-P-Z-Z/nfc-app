# -*- coding: utf-8 -*-
"""
NFC 助手 —— Android NFC 读写 App
技术栈: Python 3 + Kivy (界面) + pyjnius (调用安卓 NFC API)

功能:
  1. 读取模式: 靠近 NFC 标签时, 自动读取 UID 和 NDEF 数据(文本/网址等)
  2. 写入模式: 输入文本或网址, 点击"写入"后, 靠近标签即完成写入
"""

from kivy.app import App
from kivy.lang import Builder
from kivy.metrics import dp
from kivy.properties import StringProperty, BooleanProperty
from kivy.uix.boxlayout import BoxLayout

# ---------------------------------------------------------------
# Android 环境检测 (桌面上运行时自动降级为演示模式)
# ---------------------------------------------------------------
ANDROID = False
try:
    from jnius import autoclass
    from android import activity as p4a_activity
    ANDROID = True
except ImportError:
    pass

# NDEF well-known URI 前缀表 (按 Record Type Definition)
URI_PREFIXES = [
    "", "http://www.", "https://www.", "http://", "https://", "tel:", "mailto:",
    "ftp://anonymous:anonymous@", "ftp://ftp.", "ftps://", "sftp://", "smb://",
    "nfs://", "ftp://", "dav://", "news:", "telnet://", "imap:", "rtsp://",
    "urn:", "pop:", "sip:", "sips:", "tftp:", "btspp://", "btl2cap://",
    "btgoep://", "tcpobex://", "irdaobex://", "file://", "urn:epc:id:",
    "urn:epc:tag:", "urn:epc:pat:", "urn:epc:raw:", "urn:epc:", "urn:nfc:",
]


class NfcManager:
    """封装安卓 NFC 前台调度: 读取标签 UID / NDEF 内容, 向标签写入 NDEF"""

    def __init__(self, on_event):
        """
        on_event: 回调函数, 接收一个 dict:
            {event: 'read'|'write'|'error', uid: str, records: [...], message: str}
        """
        self.on_event = on_event
        self.write_armed = False      # True = 下一个碰到的标签将被写入
        self.write_text = ''
        self.write_url = ''

        if not ANDROID:
            return

        self.NfcAdapterCls = autoclass('android.nfc.NfcAdapter')
        self.IntentCls = autoclass('android.content.Intent')
        self.IntentFilterCls = autoclass('android.content.IntentFilter')
        self.PendingIntentCls = autoclass('android.app.PendingIntent')
        self.NdefCls = autoclass('android.nfc.tech.Ndef')
        self.NdefFormatableCls = autoclass('android.nfc.tech.NdefFormatable')
        self.NdefRecordCls = autoclass('android.nfc.NdefRecord')
        self.NdefMessageCls = autoclass('android.nfc.NdefMessage')
        self.PythonActivityCls = autoclass('org.kivy.android.PythonActivity')

        self.activity = self.PythonActivityCls.mActivity
        self.adapter = self.NfcAdapterCls.getDefaultAdapter(self.activity)

        # 注册 "新 Intent" 回调 (标签靠近时系统派发)
        p4a_activity.bind(on_new_intent=self._on_new_intent)

    # ---------------- 对外接口 ----------------

    def is_available(self):
        """手机是否具备 NFC 硬件且已开启"""
        if not ANDROID:
            return False
        return self.adapter is not None and self.adapter.isEnabled()

    def start(self):
        """开启前台调度, 使 App 在前台时独占 NFC 事件"""
        if not ANDROID or self.adapter is None:
            return
        intent = self.IntentCls(self.activity, self.PythonActivityCls.getClass())
        intent.setFlags(self.IntentCls.FLAG_ACTIVITY_SINGLE_TOP)

        # Android 12+ 要求 PendingIntent 必须声明可变性
        flags = self.PendingIntentCls.FLAG_UPDATE_CURRENT | self.PendingIntentCls.FLAG_MUTABLE
        pending = self.PendingIntentCls.getActivity(self.activity, 0, intent, flags)

        ndef_filter = self.IntentFilterCls(self.NfcAdapterCls.ACTION_NDEF_DISCOVERED)
        ndef_filter.addDataType('*/*')
        tag_filter = self.IntentFilterCls(self.NfcAdapterCls.ACTION_TAG_DISCOVERED)
        tag_filter.addCategory(self.IntentCls.CATEGORY_DEFAULT)

        self.adapter.enableForegroundDispatch(
            self.activity, pending, [ndef_filter, tag_filter], [])

    def stop(self):
        if not ANDROID or self.adapter is None:
            return
        self.adapter.disableForegroundDispatch(self.activity)

    def arm_write(self, text='', url=''):
        """武装写入: 下一个碰到的标签会被写入"""
        self.write_armed = True
        self.write_text = text or ''
        self.write_url = url or ''
        self.on_event({'event': 'info',
                       'message': '已就绪，请将手机背面贴近 NFC 标签…'})

    # ---------------- 内部实现 ----------------

    def _on_new_intent(self, intent):
        try:
            self._process_intent(intent)
        except Exception as e:
            self.on_event({'event': 'error', 'message': str(e)})

    def _process_intent(self, intent):
        tag = intent.getParcelableExtra(self.NfcAdapterCls.EXTRA_TAG)
        if tag is None:
            return

        uid = bytes(tag.getId())
        uid_hex = ':'.join('%02X' % b for b in uid)

        # ---- 写入模式 ----
        if self.write_armed:
            self.write_armed = False
            try:
                target = self.write_url if self.write_url else self.write_text
                self._write_tag(tag)
                self.on_event({'event': 'write', 'uid': uid_hex,
                               'message': '写入成功: %s' % target})
            except Exception as e:
                self.on_event({'event': 'error',
                               'message': '写入失败: %s' % e})
            return

        # ---- 读取模式 ----
        records = []
        msgs = intent.getParcelableArrayExtra(self.NfcAdapterCls.EXTRA_NDEF_MESSAGES)
        if msgs:
            for m in msgs:
                for rec in m.getRecords():
                    records.append(self._parse_record(rec))
            self.on_event({'event': 'read', 'uid': uid_hex,
                           'records': records})
        else:
            self.on_event({'event': 'read', 'uid': uid_hex,
                           'records': [('提示', '该标签不含 NDEF 数据 (可能是空白卡或非 NDEF 卡)')]})

    def _parse_record(self, rec):
        """把一条 NdefRecord 解析成 (类型, 内容)"""
        tnf = rec.getTnf()
        try:
            rtype = bytes(rec.getType()).decode('ascii', 'replace')
        except Exception:
            rtype = ''
        payload = bytes(rec.getPayload())

        if tnf == 1 and rtype == 'T':                       # 文本记录
            status = payload[0]
            lang_len = status & 0x3F
            enc = 'utf-16-be' if (status & 0x80) else 'utf-8'
            return ('文本', payload[1 + lang_len:].decode(enc, 'replace'))

        if tnf == 1 and rtype == 'U':                       # 网址记录
            idx = payload[0]
            prefix = URI_PREFIXES[idx] if idx < len(URI_PREFIXES) else ''
            return ('网址', prefix + payload[1:].decode('utf-8', 'replace'))

        return ('数据', 'TNF=%s Type=%s Payload=%s…'
                % (tnf, rtype, payload[:32].hex()))

    def _write_tag(self, tag):
        """把当前 write_text / write_url 写入标签"""
        if self.write_url:
            record = self.NdefRecordCls.createUri(self.write_url)
        else:
            record = self.NdefRecordCls.createTextRecord('zh', self.write_text)
        message = self.NdefMessageCls([record])

        ndef = self.NdefCls.get(tag)
        if ndef is not None:
            ndef.connect()
            try:
                if not ndef.isWritable():
                    raise RuntimeError('标签已设为只读')
                if ndef.getMaxSize() < message.getByteArrayLength():
                    raise RuntimeError('标签容量不足 (容量 %d 字节)'
                                       % ndef.getMaxSize())
                ndef.writeNdefMessage(message)
            finally:
                ndef.close()
            return

        # 标签存在但未格式化, 尝试格式化后写入
        fmt = self.NdefFormatableCls.get(tag)
        if fmt is not None:
            fmt.connect()
            try:
                fmt.format(message)
            finally:
                fmt.close()
            return

        raise RuntimeError('该标签不支持 NDEF 写入')


KV = '''
<Root>:
    orientation: 'vertical'
    padding: dp(16)
    spacing: dp(10)

    Label:
        text: 'NFC 助手'
        font_size: dp(26)
        bold: True
        size_hint_y: None
        height: dp(40)
        color: 0.15, 0.55, 0.95, 1

    Label:
        id: status
        text: root.status
        font_size: dp(15)
        color: 0.9, 0.35, 0.1, 1
        size_hint_y: None
        height: dp(30)

    BoxLayout:
        size_hint_y: None
        height: dp(48)
        spacing: dp(10)

        ToggleButton:
            id: btn_read
            text: '读取模式'
            group: 'mode'
            state: 'down'
            font_size: dp(16)
            on_release: root.set_mode('read')
        ToggleButton:
            id: btn_write
            text: '写入模式'
            group: 'mode'
            font_size: dp(16)
            on_release: root.set_mode('write')

    # ---------- 写入区域 ----------
    BoxLayout:
        id: write_panel
        orientation: 'vertical'
        spacing: dp(8)
        opacity: 1 if root.write_mode else 0
        disabled: not root.write_mode
        height: dp(210) if root.write_mode else 0
        size_hint_y: None

        Label:
            text: '写入文本:'
            font_size: dp(14)
            size_hint_y: None
            height: dp(22)
            color: 0.3, 0.3, 0.3, 1
            text_size: self.size
            halign: 'left'
        TextInput:
            id: txt_input
            hint_text: '例如: 你好，这是我的 NFC 名片'
            multiline: False
            font_size: dp(15)
            size_hint_y: None
            height: dp(44)
        Label:
            text: '或写入网址:'
            font_size: dp(14)
            size_hint_y: None
            height: dp(22)
            color: 0.3, 0.3, 0.3, 1
            text_size: self.size
            halign: 'left'
        TextInput:
            id: url_input
            hint_text: '例如: https://example.com'
            multiline: False
            font_size: dp(15)
            size_hint_y: None
            height: dp(44)
        Button:
            id: btn_go
            text: '写入下一个碰到的标签'
            font_size: dp(16)
            background_normal: ''
            background_color: 0.15, 0.55, 0.95, 1
            size_hint_y: None
            height: dp(48)
            on_release: root.arm_write()

    # ---------- 读取结果 ----------
    Label:
        text: '读取结果:'
        font_size: dp(14)
        size_hint_y: None
        height: dp(22)
        color: 0.3, 0.3, 0.3, 1
        text_size: self.size
        halign: 'left'
    ScrollView:
        Label:
            id: output
            text: root.output
            font_size: dp(14)
            color: 0.2, 0.2, 0.2, 1
            size_hint_y: None
            height: self.texture_size[1]
            text_size: self.width, None
            valign: 'top'
            padding: dp(6)
'''


class Root(BoxLayout):
    status = StringProperty('')
    output = StringProperty('')
    write_mode = BooleanProperty(False)

    def set_mode(self, mode):
        self.write_mode = (mode == 'write')
        if self.write_mode:
            self.status = '写入模式: 填写内容后点击下方按钮'
        else:
            self.status = '读取模式: 请贴近 NFC 标签'

    def arm_write(self):
        txt = self.ids.txt_input.text.strip()
        url = self.ids.url_input.text.strip()
        if not txt and not url:
            self.status = '请先输入要写入的文本或网址'
            return
        app = App.get_running_app()
        app.nfc.arm_write(text=txt, url=url)


class NfcApp(App):
    title = 'NFC 助手'

    def build(self):
        self.root_widget = Builder.load_string(KV)
        self.nfc = NfcManager(self.on_nfc_event)

        if not ANDROID:
            self.root_widget.status = '演示模式: 请打包为 APK 后在安卓手机上运行'
            self.root_widget.output = ('桌面环境没有 NFC 硬件。\n\n'
                                       '使用 README.md 中的步骤打包 APK, '
                                       '安装到安卓手机即可读写 NFC 标签。')
        elif not self.nfc.is_available():
            self.root_widget.status = 'NFC 未开启: 请到系统设置打开 NFC'
        else:
            self.root_widget.status = '读取模式: 请贴近 NFC 标签'
        return self.root_widget

    def on_start(self):
        if ANDROID and self.nfc.is_available():
            self.nfc.start()

    def on_stop(self):
        if ANDROID:
            self.nfc.stop()

    # ---- NFC 事件回调 (子线程/主线程都可能触发) ----
    def on_nfc_event(self, event):
        def _apply():
            root = self.root_widget
            if event.get('event') == 'read':
                root.status = '读取成功'
                lines = ['标签 UID: %s' % event.get('uid', '')]
                for i, (rtype, content) in enumerate(event.get('records', []), 1):
                    lines.append('')
                    lines.append('记录 %d [%s]' % (i, rtype))
                    lines.append(content)
                root.output = '\n'.join(lines)
            elif event.get('event') == 'write':
                root.status = '写入成功 ✔'
                root.output = '标签 UID: %s\n%s' % (event.get('uid', ''),
                                                    event.get('message', ''))
            elif event.get('event') == 'error':
                root.status = '出错: %s' % event.get('message', '')
            else:
                root.status = event.get('message', '')

        # 保证 UI 更新在主线程执行
        from kivy.clock import Clock
        Clock.schedule_once(lambda dt: _apply(), 0)


if __name__ == '__main__':
    NfcApp().run()
