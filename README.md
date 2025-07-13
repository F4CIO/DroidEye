# DroidEye
Capture and retrieve photo from your Android device via this minimal API. Written in Python. Can be compiled into .APK with Buildozer.

## Overview

This API runs as an HTTP server on android device and integrates with camera hardware.
DroidEye API provides a simple REST interface for:
- Capturing photos remotely HTTP call
- Retrieving captured photo for using in <img src='urlToThisApi'> tag
- Downloading large image files in chunks
- Retrieving operation logs
- App must run in foreground for capture to happen

## API Endpoints

### 1. Capture Photo

**Endpoint:** `GET /capture`

**Purpose:** Triggers photo capture with a specified ID and returns capture status with metadata. App must run in foreground for capture to happen - if that is not the case app will wait several seconds (specified in .ini) and return error if timed out.

#### Request Parameters

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `id` | string | Yes | Unique identifier for the photo |

#### Request Example

```
GET /capture?id=my_photo_001
```

#### Response Format

```json
{
  "has_error": false,
  "message": "Ok",
  "id": "my_photo_001",
  "file_size_in_bytes": 2048576,
  "file_path": "/path/to/photos/DroidEye_2025-01-15_10-30-45_my_photo_001.jpg",
  "log": "2025-01-15 10:30:45 - Photo capture initiated..."
}
```

#### Response Fields

| Field | Type | Description |
|-------|------|-------------|
| `has_error` | boolean | `true` if capture failed, `false` if successful |
| `message` | string | Status message (HTML-escaped) |
| `id` | string | The photo ID from request |
| `file_size_in_bytes` | integer | Size of captured file in bytes |
| `file_path` | string | Full path to captured photo file |
| `log` | string | Current log content (HTML-escaped) |

#### Error Response Example

```json
{
  "has_error": true,
  "message": "Camera timeout after 60 seconds",
  "id": "my_photo_001",
  "file_size_in_bytes": 0,
  "file_path": "",
  "log": "2025-01-15 10:30:45 - Camera capture failed..."
}
```

---

### 2. Get File Chunk

**Endpoint:** `GET /get_file_chunk`

**Purpose:** Downloads a specific chunk of a file, useful for large files or resumable downloads.

#### Request Parameters

| Parameter | Type | Required | Default | Description |
|-----------|------|----------|---------|-------------|
| `id` | string | Yes | - | Photo ID for logging |
| `file_path` | string | Yes | - | Path to the file to download |
| `offset_in_bytes` | integer | No | 0 | Starting byte position |
| `chunk_size_in_bytes` | integer | No | 1048576 | Chunk size (1MB default) |

#### Request Example

```
GET /get_file_chunk?id=my_photo_001&file_path=/photos/image.jpg&offset_in_bytes=0&chunk_size_in_bytes=524288
```

#### Response Format

```json
{
  "has_error": false,
  "message": "Ok",
  "id": "my_photo_001",
  "file_size_in_bytes": 2048576,
  "file_path": "/photos/image.jpg",
  "is_last_chunk": false,
  "offset_in_bytes": 0,
  "chunk_size_in_bytes": 524288,
  "chunk_body_as_base64": "iVBORw0KGgoAAAANSUhEUgAAA...",
  "log": "2025-01-15 10:30:45 - File chunk retrieved..."
}
```

#### Response Fields

| Field | Type | Description |
|-------|------|-------------|
| `has_error` | boolean | `true` if chunk read failed |
| `message` | string | Status message (HTML-escaped) |
| `id` | string | The photo ID from request |
| `file_size_in_bytes` | integer | Total file size in bytes |
| `file_path` | string | The requested file path |
| `is_last_chunk` | boolean | `true` if this is the final chunk |
| `offset_in_bytes` | integer | Starting byte position of this chunk |
| `chunk_size_in_bytes` | integer | Size of this chunk |
| `chunk_body_as_base64` | string | Base64-encoded chunk data |
| `log` | string | Current log content (HTML-escaped) |

#### Usage Pattern for Large Files

```javascript
// Example: Download complete file in chunks
let offset = 0;
const chunkSize = 1024 * 1024; // 1MB chunks
const chunks = [];

do {
  const response = await fetch(`/get_file_chunk?id=photo1&file_path=/photos/large_image.jpg&offset_in_bytes=${offset}&chunk_size_in_bytes=${chunkSize}`);
  const data = await response.json();
  
  if (data.has_error) {
    console.error('Chunk download failed:', data.message);
    break;
  }
  
  chunks.push(data.chunk_body_as_base64);
  offset += data.chunk_size_in_bytes;
  
} while (!data.is_last_chunk);

// Reconstruct file from base64 chunks
const completeFile = chunks.join('');
```

---

### 3. Get Image

**Endpoint:** `GET /get_img`

**Purpose:** Directly serves image files as binary data with proper MIME types.

#### Request Parameters

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `id` | string | Yes | Photo ID for logging |
| `file_name` | string | Yes | Name of image file to retrieve |

#### Request Example

```
GET /get_img?id=my_photo_001&file_name=DroidEye_2025-01-15_10-30-45_my_photo_001.jpg
```

#### Response

- **Content-Type:** Determined by file extension (e.g., `image/jpeg`, `image/png`)
- **Content-Length:** File size in bytes
- **Body:** Binary image data

#### Success Response

```
HTTP/1.1 200 OK
Content-Type: image/jpeg
Content-Length: 2048576

[Binary JPEG data]
```

#### File Not Found Behavior

If the requested file doesn't exist, the API serves a fallback dummy image (which is specified in .ini):

```
HTTP/1.1 200 OK
Content-Type: image/jpeg
Content-Length: 12345

[Binary dummy image data]
```

---

## Security Features

### Path Traversal Protection

- **File Chunk Downloads:** Only files within the configured photo folder are accessible
- **Image Serving:** Requested files are validated against the photo folder path
- **Access Denied:** Attempts to access files outside the photo folder return dummy content

### Example Security Check

```python
# This request would be blocked:
GET /get_file_chunk?file_path=../../../etc/passwd

# Response:
{
  "has_error": true,
  "message": "Access denied: file_path not in allowed photo folder",
  ...
}
```

## Configuration

### Default Settings

- **Photo Folder:** `./photos/` (configurable via camera handler)
- **Dummy Image:** `./dummy.jpg` (configurable via `DroidEye.ini`)
- **Capture Timeout:** 60 seconds (configurable via camera handler)
- **Default Chunk Size:** 1MB (1048576 bytes)

### INI Configuration

The `DroidEye.ini` file contains all configuration options:

```ini
[DEFAULT]
# TCP port the HTTP API listens on
port = 8080

# Where to store captured photos. Examples:
#   default  – value default means use Android user_data_dir (internal storage)
#   //photos  – if value starts with //, it is relative to this ini location (i.e. <app dir>/photos)
#   /storage/emulated/0/DCIM/Camera – if value starts with / it means absolute path
photo_folder_path = default 

# Timeout in seconds to wait for UI capture to complete
wait_x_seconds_on_ui_capture = 60 

# Path to dummy image file to serve by get_img method if requested file is not found
dummy_file_path = dummy.jpg 
```

#### Configuration Options

| Option | Description | Default Value |
|--------|-------------|---------------|
| `port` | TCP port the HTTP API listens on | `8080` |
| `photo_folder_path` | Where to store captured photos | `default` |
| `wait_x_seconds_on_ui_capture` | Timeout in seconds to wait for UI capture to complete | `60` |
| `dummy_file_path` | Path to dummy image file to serve if requested file is not found | `dummy.jpg` |

#### Photo Folder Path Options

- **`default`** - Use Android user_data_dir (internal storage)
- **`//photos`** - Relative to ini location (e.g., `<app dir>/photos`)
- **`/storage/emulated/0/DCIM/Camera`** - Absolute path

## Error Handling

All endpoints return consistent error responses:

```json
{
  "has_error": true,
  "message": "Error description",
  "id": "request_id",
  "log": "Complete operation log"
}
```

### Common Error Scenarios

1. **Camera Timeout:** Photo capture exceeds timeout period
2. **File Not Found:** Requested file doesn't exist
3. **Access Denied:** Path traversal attempt detected
4. **Read Error:** File system or permission issues

## Integration Example

```python
import requests
import base64

# Capture a photo
response = requests.get('http://localhost:8080/capture?id=test_photo')
data = response.json()

if not data['has_error']:
    file_path = data['file_path']
    print(f"Photo captured: {file_path}")
    
    # Download the image in chunks
    offset = 0
    chunk_size = 512 * 1024  # 512KB chunks
    file_data = b''
    
    while True:
        chunk_response = requests.get(f'http://localhost:8080/get_file_chunk', params={
            'id': 'test_photo',
            'file_path': file_path,
            'offset_in_bytes': offset,
            'chunk_size_in_bytes': chunk_size
        })
        
        chunk_data = chunk_response.json()
        if chunk_data['has_error']:
            print(f"Download failed: {chunk_data['message']}")
            break
            
        # Decode and append chunk
        chunk_bytes = base64.b64decode(chunk_data['chunk_body_as_base64'])
        file_data += chunk_bytes
        
        if chunk_data['is_last_chunk']:
            break
            
        offset += len(chunk_bytes)
    
    # Save complete file
    with open('downloaded_photo.jpg', 'wb') as f:
        f.write(file_data)
```

## Requirements

- Python 3.6+
- No external dependencies (uses only standard library)
- Camera handler component (implementation specific)
- Logger component (implementation specific)

## License

MIT
