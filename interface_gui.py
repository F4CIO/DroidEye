import urllib.request
import threading
import os

from kivy.app import App
from kivy.clock import Clock
from kivy.uix.boxlayout import BoxLayout
from kivy.uix.scrollview import ScrollView
from kivy.uix.label import Label
from kivy.uix.button import Button
from kivy.uix.floatlayout import FloatLayout
from kivy.uix.image import Image
from kivy.metrics import dp


class DroidEyeApp(App):
    """Kivy GUI for DroidEye."""

    def __init__(self, logger, port: int, preview_last_photo: bool = False, capture_timeout: int = 10, **kwargs):
        super().__init__(**kwargs)
        self.logger = logger
        self.port = port
        self.preview_last_photo = preview_last_photo
        self.capture_timeout = capture_timeout
        self.lines_processed = 0
        self.last_photo_path = None
        self.photo_preview_widget = None

    def build(self):
        self.title = 'DroidEye'

        root = BoxLayout(orientation='vertical', padding=(dp(2), dp(2), dp(2), dp(2)))

        # Title label
        title_label = Label(text='DroidEye', size_hint=(1, 0.1), font_size='20sp')
        root.add_widget(title_label)

        # Scrollable log view with photo preview container
        self.log_container = FloatLayout(size_hint=(1, 0.7))  # Use FloatLayout for absolute positioning
        # Add a BoxLayout to provide margins for the log box, filling most of the space
        log_box = BoxLayout(padding=(dp(2), dp(2), dp(2), dp(2)), size_hint=(1, 1), pos_hint={'x': 0, 'y': 0})
        self.scroll_view = ScrollView(size_hint=(1, 1), do_scroll_x=True, do_scroll_y=True)
        self.log_label = Label(size_hint=(None, None), halign='left', valign='top')
        self.log_label.bind(texture_size=self._update_label_size)
        self.scroll_view.add_widget(self.log_label)
        log_box.add_widget(self.scroll_view)
        self.log_container.add_widget(log_box)
        # Photo preview will be added as a separate widget below if needed
        
        # No need to hide preview on touch; keep preview persistent unless capture fails

        root.add_widget(self.log_container)

        # Buttons
        btn_box = BoxLayout(size_hint=(1, 0.1))
        btn_capture = Button(text='Test Capture')
        btn_exit = Button(text='Exit')
        btn_capture.bind(on_release=self._on_capture)
        btn_exit.bind(on_release=lambda *a: self.stop())
        btn_box.add_widget(btn_capture)
        btn_box.add_widget(btn_exit)
        root.add_widget(btn_box)

        # Periodically refresh log
        Clock.schedule_interval(self._refresh_log, 0.25)

        return root

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------
    def _update_label_size(self, instance, size):  # pylint: disable=unused-argument
        # Ensure label is wide enough to avoid word wrap and enable horizontal scrolling
        self.log_label.width = self.log_label.texture_size[0]
        self.log_label.height = self.log_label.texture_size[1]
        self.log_label.text_size = (None, None)

    def _refresh_log(self, _):
        new_lines = self.logger.get_new_lines(self.lines_processed)
        if not new_lines:
            return
        self.lines_processed += len(new_lines)
        if self.log_label.text:
            self.log_label.text += '\n' + '\n'.join(new_lines)
        else:
            self.log_label.text = '\n'.join(new_lines)
        self.log_label.texture_update()
        # Auto scroll to bottom
        self.scroll_view.scroll_y = 0

    def _on_capture(self, _):
        url = f'http://127.0.0.1:{self.port}/capture?id=UiTest'
        self.logger.add_line(f'Sending capture request to {url}')

        # Run the blocking HTTP call in a background thread so the UI remains responsive.
        def _worker():
            try:
                with urllib.request.urlopen(url, timeout=self.capture_timeout) as resp:
                    response_body = resp.read()
                    response_text = response_body.decode('utf-8', errors='replace')
            except Exception as exc:
                from kivy.clock import Clock
                Clock.schedule_once(lambda *_: self.logger.add_line(f'Capture request failed: {exc}'), 0)
                return

            # Schedule response processing on the UI thread
            from kivy.clock import Clock
            Clock.schedule_once(lambda *_: self._process_capture_response(response_body, response_text), 0)

        threading.Thread(target=_worker, daemon=True).start()

    # ------------------------------------------------------------------
    # Internal helpers – async response processing
    # ------------------------------------------------------------------
    def _process_capture_response(self, response_body: bytes, response_text: str):
        """Handle /capture HTTP response on the UI thread."""
        # Log (truncate long output to keep GUI responsive)
        self.logger.add_line(f'Capture response: {response_text[:500]}')

        if not self.preview_last_photo:
            return

        self.logger.add_line('Photo preview enabled, processing response…')
        try:
            import json
            data = json.loads(response_body.decode('utf-8'))
            self.logger.add_line(f'Response parsed successfully, has_error={data.get("has_error", False)}')
            if 'file_path' in data and not data.get('has_error', False):
                self.last_photo_path = data['file_path']
                self.logger.add_line(f'Photo path extracted: {self.last_photo_path}')
                self._show_photo_preview()
            else:
                self.logger.add_line('Response has error or no file_path, hiding preview')
                self._hide_photo_preview()
        except Exception as e:
            self.logger.add_line(f'Failed to parse response for preview: {e}')
            self._hide_photo_preview()

    def _on_log_touch(self, instance, touch):
        # Preview is persistent; do not hide on touch. Keep for potential future use.
        return False  # Don't consume the touch event

    # Removed _on_log_scroll to keep preview visible during auto-scroll

    # ------------------------------------------------------------------
    # External notifications
    # ------------------------------------------------------------------
    def notify_photo_captured(self, photo_path: str):
        """External call (from other threads) to update preview with the new photo."""
        # Schedule on Kivy thread for safety
        from kivy.clock import Clock

        def _update(_):
            self.last_photo_path = photo_path
            self._show_photo_preview()

        Clock.schedule_once(_update, 0)

    def notify_capture_failed(self):
        """External call to hide preview if capture failed."""
        from kivy.clock import Clock

        def _hide(_):
            self._hide_photo_preview()

        Clock.schedule_once(_hide, 0)

    def _show_photo_preview(self):
        if not self.preview_last_photo or not self.last_photo_path:
            return
        # Check if file exists
        if not os.path.exists(self.last_photo_path):
            return
        # Remove existing preview if any
        self._hide_photo_preview()
        # Create photo preview widget
        self.photo_preview_widget = Image(
            source=self.last_photo_path,
            size_hint=(None, None),
            size=(dp(200), dp(200)),
            pos_hint={'right': 0.98, 'top': 0.98}
        )
        # Add to log container (floating in top-right)
        self.log_container.add_widget(self.photo_preview_widget)

    def _hide_photo_preview(self):
        if self.photo_preview_widget:
            self.log_container.remove_widget(self.photo_preview_widget)
            self.photo_preview_widget = None

 