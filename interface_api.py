import threading
from http.server import BaseHTTPRequestHandler, HTTPServer
from urllib.parse import urlparse, parse_qs
import json
import html


class ApiInterface:
    """Minimal HTTP API exposing /capture?id=<photo_id>."""

    def __init__(self, port: int, camera_handler, logger):
        self.port = port
        self.camera_handler = camera_handler
        self.logger = logger

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------
    def start(self):
        """Blocking call that starts the HTTP server."""
        logger = self.logger
        camera_handler = self.camera_handler
        timeout = getattr(camera_handler, 'wait_x_seconds_on_ui_capture', 60)
        api_interface = self

        class RequestHandler(BaseHTTPRequestHandler):
            def do_GET(self):
                try:
                    parsed = urlparse(self.path)
                    if parsed.path == '/capture':
                        qs = parse_qs(parsed.query)
                        photo_id = qs.get('id', ['no_id'])[0]
                        logger.add_line(f'/capture request received with id={photo_id}')
                        success, file_path, file_size, error_msg = camera_handler.capture_photo_sync(photo_id, timeout)
                        has_error = not success
                        message = 'Ok' if not has_error else error_msg
                        log_body = logger.get_body()
                        # Escape for JSON
                        message_escaped = html.escape(message)
                        log_escaped = html.escape(log_body)
                        response = {
                            'has_error': has_error,
                            'message': message_escaped,
                            'id': photo_id,  
                            'file_size_in_bytes': file_size,
                            'file_path': file_path,
                            'log': log_escaped
                        }
                        response_bytes = json.dumps(response).encode('utf-8')
                        # Log the response (limit to 500 chars)
                        log_response = response_bytes[:500].decode('utf-8', errors='replace')
                        logger.add_line(f'/capture response: {log_response}')
                        self.send_response(200)
                        self.send_header('Content-Type', 'application/json')
                        self.send_header('Content-Length', str(len(response_bytes)))
                        self.end_headers()
                        self.wfile.write(response_bytes)
                        # Notify Kivy GUI about capture result
                        try:
                            from kivy.app import App
                            from kivy.clock import Clock
                            gui_app = App.get_running_app()
                            if gui_app is not None:
                                if success and hasattr(gui_app, 'notify_photo_captured'):
                                    Clock.schedule_once(lambda _dt, p=file_path: gui_app.notify_photo_captured(p), 0)
                                elif not success and hasattr(gui_app, 'notify_capture_failed'):
                                    Clock.schedule_once(lambda _dt: gui_app.notify_capture_failed(), 0)
                        except Exception as exc_notify:
                            logger.add_line(f'Failed to notify GUI about capture result: {exc_notify}')
                        # End GUI notification
                    elif parsed.path == '/get_file_chunk':
                        qs = parse_qs(parsed.query)
                        photo_id = qs.get('id', ['no_id'])[0]
                        file_path = qs.get('file_path', [''])[0]
                        try:
                            offset_in_bytes = int(qs.get('offset_in_bytes', ['0'])[0])
                        except Exception:
                            offset_in_bytes = 0
                        try:
                            chunk_size_in_bytes = int(qs.get('chunk_size_in_bytes', ['1048576'])[0])
                        except Exception:
                            chunk_size_in_bytes = 1048576
                        logger.add_line(f'/get_file_chunk request: id={photo_id}, file_path={file_path}, offset={offset_in_bytes}, chunk_size={chunk_size_in_bytes}')
                        response = api_interface.get_file_chunk_response(photo_id, file_path, offset_in_bytes, chunk_size_in_bytes)
                        response_bytes = json.dumps(response).encode('utf-8')
                        log_response = response_bytes[:500].decode('utf-8', errors='replace')
                        logger.add_line(f'/get_file_chunk response: {log_response}')
                        self.send_response(200)
                        self.send_header('Content-Type', 'application/json')
                        self.send_header('Content-Length', str(len(response_bytes)))
                        self.end_headers()
                        self.wfile.write(response_bytes)
                    elif parsed.path == '/get_img':
                        qs = parse_qs(parsed.query)
                        photo_id = qs.get('id', ['no_id'])[0]
                        file_name = qs.get('file_name', [''])[0]
                        logger.add_line(f'/get_img request: id={photo_id}, file_name={file_name}')
                        # Resolve photo folder and dummy file path
                        import os
                        photo_folder = getattr(camera_handler, 'photo_folder_path', os.path.join(os.getcwd(), 'photos'))
                        ini_path = os.path.abspath('DroidEye.ini')
                        ini_dir = os.path.dirname(ini_path)
                        dummy_file_path = os.path.join(ini_dir, 'dummy.jpg')
                        # Try to read dummy_file_path from ini if present
                        import configparser
                        config = configparser.ConfigParser()
                        config.read(ini_path)
                        dummy_file_path = config['DEFAULT'].get('dummy_file_path', dummy_file_path)
                        # Build the requested file path
                        requested_path = os.path.abspath(os.path.join(photo_folder, file_name))
                        # Security: ensure requested_path is inside photo_folder
                        if not requested_path.startswith(os.path.abspath(photo_folder) + os.sep):
                            logger.add_line(f'/get_img: Access denied for file_name={file_name}')
                            requested_path = dummy_file_path
                        # Try to serve the file, fallback to dummy if not found
                        file_to_serve = requested_path
                        if not os.path.isfile(file_to_serve):
                            logger.add_line(f'/get_img: File not found, serving dummy: {file_to_serve}')
                            file_to_serve = dummy_file_path
                        try:
                            with open(file_to_serve, 'rb') as f:
                                img_bytes = f.read()
                            # Guess content type by extension
                            import mimetypes
                            content_type, _ = mimetypes.guess_type(file_to_serve)
                            if not content_type:
                                content_type = 'application/octet-stream'
                            self.send_response(200)
                            self.send_header('Content-Type', content_type)
                            self.send_header('Content-Length', str(len(img_bytes)))
                            self.end_headers()
                            self.wfile.write(img_bytes)
                        except Exception as exc:
                            logger.add_line(f'/get_img: Error serving file: {exc}')
                            self.send_response(500)
                            self.end_headers()
                            self.wfile.write(b'Internal Server Error')
                    else:
                        self.send_response(404)
                        self.end_headers()
                except Exception as exc:
                    logger.add_line(f'Error handling request: {exc}')
                    self.send_response(500)
                    self.end_headers()
                    self.wfile.write(b'Internal Server Error')

            def log_message(self, format, *args):  # noqa: N802, pylint: disable=invalid-name
                # Silence default HTTP server logging
                return 

        # ------------------------------------------------------------------
        # Create and run server
        # ------------------------------------------------------------------
        try:
            httpd = HTTPServer(('0.0.0.0', self.port), RequestHandler)
            logger.add_line(f'HTTP API started on port {self.port}')
            httpd.serve_forever()
        except Exception as exc:
            logger.add_line(f'HTTP API failed/stopped: {exc}') 

    def get_file_chunk_response(self, photo_id, file_path, offset_in_bytes, chunk_size_in_bytes):
        import os, html
        logger = self.logger
        camera_handler = self.camera_handler
        allowed_folder = os.path.abspath(getattr(camera_handler, 'photo_folder_path', '.'))
        abs_file_path = os.path.abspath(file_path)
        if not abs_file_path.startswith(allowed_folder + os.sep):
            message = f'Access denied: file_path not in allowed photo folder ({allowed_folder})'
            logger.add_line(message)
            return {
                'has_error': True,
                'message': html.escape(message),
                'id': photo_id,
                'file_size_in_bytes': 0,
                'file_path': file_path,
                'is_last_chunk': True,
                'offset_in_bytes': offset_in_bytes,
                'chunk_size_in_bytes': chunk_size_in_bytes,
                'chunk_body_as_base64': '',
                'log': html.escape(logger.get_body())
            }
        try:
            file_size = os.path.getsize(abs_file_path)
        except Exception as exc:
            message = f'Error reading file size: {exc}'
            logger.add_line(message)
            return {
                'has_error': True,
                'message': html.escape(message),
                'id': photo_id,
                'file_size_in_bytes': 0,
                'file_path': file_path,
                'is_last_chunk': True,
                'offset_in_bytes': offset_in_bytes,
                'chunk_size_in_bytes': chunk_size_in_bytes,
                'chunk_body_as_base64': '',
                'log': html.escape(logger.get_body())
            }
        has_error, message, is_last_chunk, chunk_body_as_base64 = self.get_file_chunk(abs_file_path, offset_in_bytes, chunk_size_in_bytes, file_size)
        return {
            'has_error': has_error,
            'message': html.escape(message),
            'id': photo_id,
            'file_size_in_bytes': file_size,
            'file_path': file_path,
            'is_last_chunk': is_last_chunk,
            'offset_in_bytes': offset_in_bytes,
            'chunk_size_in_bytes': chunk_size_in_bytes,
            'chunk_body_as_base64': chunk_body_as_base64,
            'log': html.escape(logger.get_body())
        }

    def get_file_chunk(self, abs_file_path, offset_in_bytes, chunk_size_in_bytes, file_size):
        import base64
        try:
            with open(abs_file_path, 'rb') as f:
                f.seek(offset_in_bytes)
                chunk = f.read(chunk_size_in_bytes)
            chunk_body_as_base64 = base64.b64encode(chunk).decode('ascii')
            is_last_chunk = (offset_in_bytes + len(chunk) >= file_size)
            message = 'Ok'
            has_error = False
        except Exception as exc:
            message = f'Error reading file: {exc}'
            chunk_body_as_base64 = ''
            is_last_chunk = True
            has_error = True
        return has_error, message, is_last_chunk, chunk_body_as_base64 