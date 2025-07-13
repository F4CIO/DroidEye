import configparser
import threading
import sys
import traceback

from handler_for_CsLog import CsLog
from handler_for_camera import CameraHandler
from interface_api import ApiInterface
from interface_gui import DroidEyeApp


def load_config(ini_path: str = 'DroidEye.ini'):
    """Read config values from DroidEye.ini."""
    config = configparser.ConfigParser()
    config.read(ini_path)
    default = config['DEFAULT']
    port = int(default.get('port', 8080))
    photo_folder_path = default.get('photo_folder_path', 'default')
    wait_x_seconds_on_ui_capture = int(default.get('wait_x_seconds_on_ui_capture', 60))
    preview_last_photo = default.getboolean('preview_last_photo', False)
    return port, photo_folder_path, wait_x_seconds_on_ui_capture, preview_last_photo


def main():
    # Read configuration
    port, photo_folder_path, wait_x_seconds_on_ui_capture, preview_last_photo = load_config()

    # Initialise logging
    log = CsLog('---------------------------------- DroidEye started ----------------------------------', 'DroidEye.log')
    log.add_line(f'Config loaded: port={port}, photo_folder_path={photo_folder_path}, wait_x_seconds_on_ui_capture={wait_x_seconds_on_ui_capture}, preview_last_photo={preview_last_photo}')

    # ------------------------------------------------------------------
    # Global exception handling: capture any uncaught exception (main
    # thread or background threads) and write it to CsLog so it shows
    # up in the GUI.
    # ------------------------------------------------------------------

    def _log_unhandled(exc_type, exc_value, exc_tb):
        """Write uncaught exceptions to CsLog (and console)."""
        if issubclass(exc_type, KeyboardInterrupt):
            # Honour standard behaviour for Ctrl-C on desktop.
            sys.__excepthook__(exc_type, exc_value, exc_tb)
            return

        log.add_line('UNCAUGHT EXCEPTION:')
        for line in traceback.format_exception(exc_type, exc_value, exc_tb):
            for segment in line.rstrip().split('\n'):
                log.add_line(segment)

    # Hook for the main thread
    sys.excepthook = _log_unhandled

    # Hook for background threads (Python 3.8+)
    def _thread_exception_handler(args):  # type: (threading.ExceptHookArgs) -> None
        _log_unhandled(args.exc_type, args.exc_value, args.exc_traceback)

    threading.excepthook = _thread_exception_handler

    # Prepare camera handler
    camera_handler = CameraHandler(photo_folder_path, log, wait_x_seconds_on_ui_capture)

    # Start HTTP API server in background thread
    api_server = ApiInterface(port, camera_handler, log)
    log.add_line('Starting HTTP API server thread...')
    try:
        threading.Thread(target=api_server.start, daemon=True).start()
        log.add_line('HTTP API server thread started.')
    except Exception as exc:
        log.add_line(f'Failed to start HTTP API server thread: {exc}')

    # Run Kivy GUI (blocks until exit)
    DroidEyeApp(log, port, preview_last_photo, wait_x_seconds_on_ui_capture).run()


if __name__ == '__main__':
    main() 