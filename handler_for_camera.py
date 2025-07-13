import os
import platform
from datetime import datetime
import threading
import time


class CameraHandler:
    """Handle photo capture on Android using the native Camera API via Pyjnius.

    On non-Android platforms (or when dependencies are missing) a zero-byte dummy file
    is created so the rest of the pipeline can continue to operate.
    """

    def __init__(self, photo_folder_path: str, logger, wait_x_seconds_on_ui_capture=60):
        self.logger = logger
        self.photo_folder_path_setting = photo_folder_path
        self.is_android = platform.system() == 'Linux' and 'ANDROID_ARGUMENT' in os.environ
        self.photo_folder_path = self._resolve_photo_folder_path()
        self.wait_x_seconds_on_ui_capture = wait_x_seconds_on_ui_capture
        os.makedirs(self.photo_folder_path, exist_ok=True)
        self.logger.add_line(f'Photo folder resolved to: {self.photo_folder_path}')

    def _resolve_photo_folder_path(self) -> str:
        setting = self.photo_folder_path_setting.strip()
        if setting == 'default':
            if self.is_android:
                # On Android, default to the app's user_data_dir once Kivy app is running.
                from kivy.app import App
                try:
                    return App.get_running_app().user_data_dir  # type: ignore[attr-defined]
                except Exception:
                    return os.getcwd()
            # Desktop fallback
            return os.path.join(os.getcwd(), 'photos')
        if setting.startswith('//'):
            ini_dir = os.path.dirname(os.path.abspath('DroidEye.ini'))
            return os.path.join(ini_dir, setting.lstrip('//'))
        return setting  # Absolute or relative path as-is

    # ---------------------------------------------------------------------
    # Public API
    # ---------------------------------------------------------------------
    def capture_photo(self, photo_id: str):
        """Capture a single photo.

        * On Android  -> uses Pyjnius to invoke the platform Camera API on the UI thread.
        * Elsewhere  -> immediately creates a dummy file.
        """
        filename = self._build_filename(photo_id)

        if self.is_android:
            # Calling directly keeps us on the main Kivy/Python thread which is already
            # attached to the JVM, avoiding PyJNIus thread-hook issues (missing
            # NativeInvocationHandler on secondary threads).
            from kivy.clock import Clock  # imported lazily to keep desktop path clean
            self.logger.add_line(f'Scheduling Android camera capture to "{filename}" on UI thread')
            Clock.schedule_once(lambda *_: self._capture_android(filename), 0)
        else:
            self.logger.add_line(f'Non-Android environment – creating dummy photo "{filename}"')
            threading.Thread(target=self._create_dummy_file, args=(filename,), daemon=True).start()

    def capture_photo_sync(self, photo_id: str, timeout: int = None):
        filename = self._build_filename(photo_id)
        if timeout is None:
            timeout = self.wait_x_seconds_on_ui_capture
        self.logger.add_line(f'Starting synchronous capture for {filename} with timeout {timeout}s')
        self.push_app_to_foreground()
        # Remove file if it exists
        try:
            if os.path.exists(filename):
                os.remove(filename)
        except Exception:
            pass
        # Schedule capture
        if self.is_android:
            from kivy.clock import Clock
            Clock.schedule_once(lambda *_: self._capture_android(filename), 0)
        else:
            threading.Thread(target=self._create_dummy_file, args=(filename,), daemon=True).start()
        # Wait for file to appear
        start = time.time()
        while time.time() - start < timeout:
            if os.path.exists(filename) and os.path.getsize(filename) > 0:
                file_size = os.path.getsize(filename)
                return True, filename, file_size, ''
            time.sleep(0.2)
        # Timeout
        self.logger.add_line('Capture timed out waiting for file.')
        return False, filename, 0, 'DroidEye is not open as foreground app on android phone'

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------
    def _build_filename(self, photo_id: str) -> str:
        ts = datetime.now().strftime('%Y-%m-%d_%H-%M-%S')
        return os.path.join(self.photo_folder_path, f'DroidEye_{ts}_{photo_id}.jpg')

    def _create_dummy_file(self, filename: str):
        self.logger.add_line(f'Creating dummy photo file: {filename}')
        try:
            # Copy dummy.jpg from the app directory to the target filename
            src = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'dummy.jpg')
            if not os.path.exists(src):
                raise FileNotFoundError(f'dummy.jpg not found at {src}')
            with open(src, 'rb') as fsrc, open(filename, 'wb') as fdst:
                fdst.write(fsrc.read())
            self.logger.add_line(f'Dummy photo file copied from {src} to: {filename}')
        except Exception as exc:
            self.logger.add_line(f'Failed to copy dummy photo file: {exc}')

    def push_app_to_foreground(self):
        """Attempt to bring the DroidEye app to the foreground on Android.

        Falls back through multiple strategies so that at least one of them
        succeeds on most API levels / OEM skins.
        """
        if not self.is_android:
            return
        try:
            from jnius import autoclass, cast
            PythonActivity = autoclass('org.kivy.android.PythonActivity')
            activity = PythonActivity.mActivity
            Context = autoclass('android.content.Context')
            Intent = autoclass('android.content.Intent')
            PackageManager = autoclass('android.content.pm.PackageManager')
            ActivityManager = autoclass('android.app.ActivityManager')

            pkg_name = activity.getPackageName()
            pm = activity.getPackageManager()
            launch_intent = pm.getLaunchIntentForPackage(pkg_name)

            if launch_intent is not None:
                launch_intent.addFlags(Intent.FLAG_ACTIVITY_REORDER_TO_FRONT |  # bring to front if exists
                                        Intent.FLAG_ACTIVITY_SINGLE_TOP |     # avoid duplicate instances
                                        Intent.FLAG_ACTIVITY_NEW_TASK)
                activity.startActivity(launch_intent)
                self.logger.add_line('Requested app foreground via launch intent.')
                return

            # Fallback: move task to front via ActivityManager (may require permission on Android 11+)
            am = cast('android.app.ActivityManager', activity.getSystemService(Context.ACTIVITY_SERVICE))
            if am is not None:
                task_id = activity.getTaskId()
                am.moveTaskToFront(task_id, 0)
                self.logger.add_line('Requested app foreground via ActivityManager.moveTaskToFront.')
                return

            self.logger.add_line('Unable to obtain launch intent or ActivityManager to move app to foreground.')
        except Exception as exc:
            self.logger.add_line(f'Failed to move app to foreground: {exc}')

    # ------------------------------------------------------------------
    # Android implementation -------------------------------------------------
    def _capture_android(self, filename: str):
        """Run the photo capture flow on Android.

        This function delegates the heavy-lifting to a nested function executed on the
        Java UI thread via the `run_on_ui_thread` decorator provided by Kivy.
        """
        logger = self.logger

        # --------------------------------------------------------------
        # Ensure CAMERA runtime permission (Android 6+)
        # --------------------------------------------------------------
        try:
            from android.permissions import request_permissions, check_permission, Permission  # type: ignore

            if not check_permission(Permission.CAMERA):
                logger.add_line("Requesting CAMERA runtime permission…")

                # The permission dialog is asynchronous. When the user
                # answers, a callback fires. We capture that response and
                # schedule the actual capture afterwards.

                def _perm_callback(_permissions, grants):  # pylint: disable=unused-argument
                    if all(grants):
                        logger.add_line("CAMERA permission granted – retrying capture")
                        from kivy.clock import Clock  # local import to avoid desktop breakage
                        Clock.schedule_once(lambda *_: self._capture_android(filename), 0)
                    else:
                        logger.add_line("CAMERA permission denied by user – creating dummy file")
                        self._create_dummy_file(filename)

                request_permissions([Permission.CAMERA], _perm_callback)
                return  # wait for user response

        except Exception:
            # permissions helper not available on older APIs/bootstrap – continue
            pass

        # Import Android-specific dependencies lazily so desktop imports don't explode.
        try:
            from android.runnable import run_on_ui_thread  # type: ignore
            from jnius import autoclass, PythonJavaClass, java_method  # type: ignore
            from kivy.clock import Clock  # type: ignore
        except Exception as exc:  # pragma: no cover – only hit on non-Android.
            logger.add_line(f"Android camera dependencies not available: {exc}. Creating dummy file instead.")
            self._create_dummy_file(filename)
            return

        # Grab the requisite Java classes.
        try:
            Camera = autoclass('android.hardware.Camera')
            SurfaceTexture = autoclass('android.graphics.SurfaceTexture')
        except Exception as exc:
            logger.add_line(f"Failed to access Android Camera classes: {exc}")
            self._create_dummy_file(filename)
            return

        # ------------------------------------------------------------------
        # Define the PictureCallback wrapper
        # ------------------------------------------------------------------
        class JpegCallback(PythonJavaClass):
            """Receives the JPEG byte[] from Android and writes it to disk."""

            __javainterfaces__ = ['android/hardware/Camera$PictureCallback']
            __javacontext__ = 'app'

            def __init__(self):  # noqa: D401
                super().__init__()

            @java_method('([BLandroid/hardware/Camera;)V')
            def onPictureTaken(self, data, camera):  # pylint: disable=invalid-name
                logger.add_line(f'Camera callback: received image data, saving to {filename} (100% quality)')
                try:
                    # Try to use Android Bitmap to re-encode at 100% quality
                    try:
                        from jnius import autoclass
                        BitmapFactory = autoclass('android.graphics.BitmapFactory')
                        Bitmap = autoclass('android.graphics.Bitmap')
                        CompressFormat = autoclass('android.graphics.Bitmap$CompressFormat')
                        FileOutputStream = autoclass('java.io.FileOutputStream')

                        py_bytes = bytes(data)
                        bitmap = BitmapFactory.decodeByteArray(py_bytes, 0, len(py_bytes))
                        if bitmap is not None:
                            fos = FileOutputStream(filename)
                            success = bitmap.compress(CompressFormat.JPEG, 100, fos)
                            fos.close()
                            if success:
                                logger.add_line(f'Photo saved (JPEG 100%): {filename}')
                            else:
                                logger.add_line(f'Bitmap.compress failed, falling back to raw bytes for {filename}')
                                with open(filename, 'wb') as fh:
                                    fh.write(py_bytes)
                                logger.add_line(f'Photo saved (raw fallback): {filename}')
                        else:
                            logger.add_line(f'BitmapFactory.decodeByteArray failed, saving raw bytes for {filename}')
                            with open(filename, 'wb') as fh:
                                fh.write(py_bytes)
                            logger.add_line(f'Photo saved (raw fallback): {filename}')
                    except Exception as bitmap_exc:
                        logger.add_line(f'Bitmap/JPEG 100% save failed: {bitmap_exc}, saving raw bytes for {filename}')
                        py_bytes = bytes(data)
                        with open(filename, 'wb') as fh:
                            fh.write(py_bytes)
                        logger.add_line(f'Photo saved (raw fallback): {filename}')
                except Exception as exc_inner:  # noqa: BLE001
                    logger.add_line(f'Failed to save photo: {exc_inner}')
                finally:
                    try:
                        camera.release()
                    except Exception:  # pylint: disable=broad-except
                        pass

        # ------------------------------------------------------------------
        # Execute the Java-side capture on the UI thread
        # ------------------------------------------------------------------

        @run_on_ui_thread
        def _java_capture():  # noqa: D401, N802 – Android API naming conventions.
            logger.add_line(f'Android UI thread: opening camera for {filename}')
            # First try to obtain the camera instance separately so we can
            # handle connection failures cleanly.
            cam_instance = None
            try:
                cam_instance = Camera.open(0)
            except Exception as open_exc:  # noqa: BLE001
                logger.add_line(f"Android UI thread: Camera.open failed: {open_exc}. Will retry once after 0.5 s")
                from kivy.clock import Clock  # noqa: WPS433

                def _retry(_):
                    try:
                        cam_second = Camera.open(0)
                        cam_second.release()
                        self._capture_android(filename)
                    except Exception as exc_retry:  # noqa: BLE001
                        logger.add_line(f"Android UI thread: Second Camera.open failed: {exc_retry}. Creating dummy file.")
                        self._create_dummy_file(filename)

                Clock.schedule_once(_retry, 0.5)
                return

            # If we reach here we have a valid camera instance.
            logger.add_line(f'Android UI thread: Camera opened, configuring and starting preview for {filename}')
            try:
                params = cam_instance.getParameters()
                sizes = params.getSupportedPictureSizes()
                if sizes and len(sizes):
                    best_size = max(sizes, key=lambda s: s.width * s.height)
                    params.setPictureSize(best_size.width, best_size.height)
                    cam_instance.setParameters(params)
            except Exception:  # pylint: disable=broad-except
                pass  # Use default params if anything goes wrong

            try:
                dummy_surface = SurfaceTexture(0)
                cam_instance.setPreviewTexture(dummy_surface)
                cam_instance.startPreview()
                logger.add_line(f'Android UI thread: Starting camera preview and taking picture for {filename}')
                cam_instance.takePicture(None, None, JpegCallback())
            except Exception as exc_take:  # noqa: BLE001
                logger.add_line(f"Android UI thread: camera capture error: {exc_take}")
                try:
                    cam_instance.release()
                except Exception:  # pylint: disable=broad-except
                    pass
                from kivy.clock import Clock as _KClock  # local import to avoid desktop errors
                _KClock.schedule_once(lambda *_: self._create_dummy_file(filename), 0)

        # Kick off the Java-side capture.
        _java_capture()