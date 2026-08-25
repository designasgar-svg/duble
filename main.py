import threading
import time
from kivy.app import App
from kivy.uix.boxlayout import BoxLayout
from android.runnable import run_on_ui_thread
import duble

def start_server():
    duble.socketio.run(duble.app, host='127.0.0.1', port=5000, debug=False)

class DubberApp(App):
    def build(self):
        threading.Thread(target=start_server, daemon=True).start()
        time.sleep(2)  # زمان دادن به وب‌سرور برای بالا آمدن کامل
        self.init_webview()
        return BoxLayout()

    @run_on_ui_thread
    def init_webview(self):
        from activity import mActivity
        from jnius import autoclass
        
        WebView = autoclass('android.webkit.WebView')
        WebViewClient = autoclass('android.webkit.WebViewClient')
        WebChromeClient = autoclass('android.webkit.WebChromeClient')
        
        webview = WebView(mActivity)
        settings = webview.getSettings()
        
        # تنظیمات لازم برای اجازه پخش صدا و اسکریپت در تبلت
        settings.setJavaScriptEnabled(True)
        settings.setDomStorageEnabled(True)
        settings.setAllowFileAccess(True)
        settings.setAllowContentAccess(True)
        settings.setMediaPlaybackRequiresUserGesture(False)  # برداشتن قفل صدا
        
        webview.setWebViewClient(WebViewClient())
        webview.setWebChromeClient(WebChromeClient())
        webview.loadUrl('http://127.0.0.1:5000')
        
        mActivity.setContentView(webview)

if __name__ == '__main__':
    DubberApp().run()