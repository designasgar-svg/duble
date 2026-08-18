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
        # اجرای سرور پایتون در پس‌زمینه
        threading.Thread(target=start_server, daemon=True).start()
        time.sleep(1.5)  # مهلت به سرور برای بالا آمدن
        
        self.init_webview()
        return BoxLayout()

    @run_on_ui_thread
    def init_webview(self):
        from activity import mActivity
        from jnius import autoclass
        
        WebView = autoclass('android.webkit.WebView')
        WebViewClient = autoclass('android.webkit.WebViewClient')
        
        webview = WebView(mActivity)
        webview.getSettings().setJavaScriptEnabled(True)
        webview.getSettings().setDomStorageEnabled(True)
        webview.getSettings().setAllowFileAccess(True)
        webview.getSettings().setMediaPlaybackRequiresUserGesture(False)
        webview.setWebViewClient(WebViewClient())
        webview.loadUrl('http://127.0.0.1:5000')
        
        mActivity.setContentView(webview)

if __name__ == '__main__':
    DubberApp().run()