"""
Web Interface for License Plate Recognition + Blockchain Verification
Giao diện web cho nhận dạng biển số xe + Xác thực Blockchain
"""
import os
import cv2
import base64
import hashlib
import hmac
import secrets
import threading
import queue
import time
import traceback
import re
from flask import Flask, render_template, request, jsonify, send_from_directory
from flask_cors import CORS
import numpy as np
from pathlib import Path
from datetime import datetime
import json

from inference import LicensePlateRecognizer
from video_recognition import VideoPlateRecognizer
from src import utils

try:
    from eth_account import Account
    from eth_account.messages import encode_defunct
    wallet_signature_available = True
except Exception as e:
    print(f"Warning: Wallet signature verification not available: {e}")
    wallet_signature_available = False

try:
    from blockchain_service import BlockchainService, normalize_plate_number
    blockchain_available = True
except Exception as e:
    print(f"Warning: Blockchain module not available: {e}")
    blockchain_available = False
    normalize_plate_number = None

try:
    from stolen_vehicles import stolen_manager
    stolen_manager_available = True
except Exception as e:
    print(f"Warning: Stolen vehicles module not available: {e}")
    stolen_manager_available = False

try:
    from qr_generator import qr_manager
    qr_available = True
except Exception as e:
    print(f"Warning: QR code module not available: {e}")
    qr_available = False

try:
    from blockchain_timeline import timeline_manager
    timeline_available = True
except Exception as e:
    print(f"Warning: Blockchain timeline module not available: {e}")
    timeline_available = False

app = Flask(__name__, template_folder='templates', static_folder='static')
CORS(app)
app.config['TEMPLATES_AUTO_RELOAD'] = True

UPLOAD_FOLDER = 'uploads'
RESULTS_FOLDER = 'results'
ALLOWED_VIDEO_EXTENSIONS = {'mp4', 'avi', 'mov', 'mkv', 'flv', 'wmv'}
ALLOWED_IMAGE_EXTENSIONS = {'jpg', 'jpeg', 'png', 'bmp'}
MAX_FILE_SIZE = 500 * 1024 * 1024

os.makedirs(UPLOAD_FOLDER, exist_ok=True)
os.makedirs(RESULTS_FOLDER, exist_ok=True)
app.config['UPLOAD_FOLDER'] = UPLOAD_FOLDER
app.config['MAX_CONTENT_LENGTH'] = MAX_FILE_SIZE

webcam_thread = None
webcam_recognition_thread = None
is_streaming = False
stream_queue = queue.Queue(maxsize=2)
recognition_queue = queue.Queue(maxsize=1)
webcam_lock = threading.Lock()
latest_webcam_detections = []
latest_webcam_detections_at = 0
latest_webcam_signature = None
current_webcam_signature = None
webcam_recognition_busy = False
webcam_candidate_history = []
latest_stream_payload = None
latest_stream_payload_at = 0
WEBCAM_TEMP_FRAME_PATH = os.path.join(UPLOAD_FOLDER, '_temp_webcam_frame.jpg')
WEBCAM_STREAM_INTERVAL_SECONDS = 0.08
WEBCAM_FAST_RECOGNITION_INTERVAL_SECONDS = 0.22
WEBCAM_BACKGROUND_RECOGNITION_INTERVAL_SECONDS = 0.6
WEBCAM_DEEP_RECOGNITION_INTERVAL_SECONDS = 1.2
WEBCAM_DETECTION_TTL_SECONDS = 4.0
WEBCAM_CANDIDATE_WINDOW_SECONDS = 5.0
WEBCAM_CANDIDATE_MIN_CONFIDENCE = 0.12
WEBCAM_PUBLISH_MIN_CONFIDENCE = 0.22
WEBCAM_PUBLISH_HIGH_CONFIDENCE = 0.72
WEBCAM_PUBLISH_SINGLE_CONFIDENCE = 0.20
WEBCAM_PUBLISH_SINGLE_QUALITY = 0.58
WEBCAM_PUBLISH_REPEAT_CONFIDENCE = 0.16
WEBCAM_PUBLISH_REPEAT_QUALITY = 0.48
WEBCAM_PUBLISH_MIN_HITS = 1
WEBCAM_SIGNATURE_RESULT_TOLERANCE_SECONDS = 1.8
WEBCAM_ENABLE_DEEP_SCAN = True
recognizer = LicensePlateRecognizer()
video_recognizer = VideoPlateRecognizer()

blockchain_service = None
if blockchain_available:
    try:
        blockchain_service = BlockchainService()
    except Exception as e:
        print(f"Warning: Blockchain service init failed: {e}")

detection_history = []
MAX_HISTORY = 100
last_timeline_chain_sync_at = 0
ADMIN_CHALLENGE_TTL_SECONDS = 300
ADMIN_TOKEN_TTL_SECONDS = 3600
ADMIN_TOKEN_SECRET = os.environ.get('ADMIN_TOKEN_SECRET', 'blockplate-local-admin-token-v1')
CONFIGURED_ADMIN_ADDRESS = os.environ.get('ADMIN_ADDRESS', '').strip()
admin_challenges = {}
admin_tokens = {}
revoked_admin_tokens = {}
admin_auth_lock = threading.Lock()


def allowed_file(filename, allowed_extensions):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in allowed_extensions

def normalize_wallet_address(address):
    address = (address or '').strip()
    if len(address) != 42 or not address.startswith('0x'):
        return None
    try:
        int(address[2:], 16)
    except ValueError:
        return None
    return address.lower()

def cleanup_admin_auth():
    now = time.time()
    with admin_auth_lock:
        expired_challenges = [
            nonce for nonce, challenge in admin_challenges.items()
            if challenge['expires_at'] <= now
        ]
        for nonce in expired_challenges:
            admin_challenges.pop(nonce, None)

        expired_tokens = [
            token for token, token_data in admin_tokens.items()
            if token_data['expires_at'] <= now
        ]
        for token in expired_tokens:
            admin_tokens.pop(token, None)

        expired_revocations = [
            token_hash for token_hash, expires_at in revoked_admin_tokens.items()
            if expires_at <= now
        ]
        for token_hash in expired_revocations:
            revoked_admin_tokens.pop(token_hash, None)

def admin_token_fingerprint(token):
    return hashlib.sha256((token or '').encode('utf-8')).hexdigest()

def revoke_admin_token(token):
    if not token:
        return

    token_data = decode_signed_admin_token(token)
    expires_at = token_data['expires_at'] if token_data else time.time() + ADMIN_TOKEN_TTL_SECONDS
    with admin_auth_lock:
        admin_tokens.pop(token, None)
        revoked_admin_tokens[admin_token_fingerprint(token)] = expires_at

def get_expected_admin_address():
    """Use ADMIN_ADDRESS when configured, while requiring it to match the contract admin."""
    configured_address = normalize_wallet_address(CONFIGURED_ADMIN_ADDRESS)
    if CONFIGURED_ADMIN_ADDRESS and not configured_address:
        return None, 'ADMIN_ADDRESS in .env is invalid'

    contract_address = None
    if blockchain_service:
        contract_address = normalize_wallet_address(blockchain_service.get_admin_address())

    if configured_address and contract_address and configured_address != contract_address:
        return None, 'ADMIN_ADDRESS does not match the deployed smart contract admin'

    address = configured_address or contract_address
    if not address:
        return None, 'Cannot read contract admin address'
    return address, None

def build_admin_challenge_message(address, nonce):
    return (
        "BlockPlate Admin Authorization\n"
        f"Address: {address}\n"
        f"Nonce: {nonce}\n"
        "Only sign this message when you are using the local BlockPlate app."
    )

def encode_admin_token_payload(payload):
    raw = json.dumps(payload, separators=(',', ':'), sort_keys=True).encode('utf-8')
    return base64.urlsafe_b64encode(raw).decode('ascii').rstrip('=')

def decode_admin_token_payload(payload_b64):
    padding = '=' * (-len(payload_b64) % 4)
    raw = base64.urlsafe_b64decode((payload_b64 + padding).encode('ascii'))
    return json.loads(raw.decode('utf-8'))

def sign_admin_token_payload(payload_b64):
    return hmac.new(
        ADMIN_TOKEN_SECRET.encode('utf-8'),
        payload_b64.encode('ascii'),
        hashlib.sha256
    ).hexdigest()

def decode_signed_admin_token(token):
    try:
        payload_b64, signature = token.rsplit('.', 1)
    except ValueError:
        return None

    expected_signature = sign_admin_token_payload(payload_b64)
    if not hmac.compare_digest(signature, expected_signature):
        return None

    try:
        payload = decode_admin_token_payload(payload_b64)
    except Exception:
        return None

    address = normalize_wallet_address(payload.get('address'))
    expires_at = float(payload.get('expires_at') or 0)
    if not address or expires_at <= 0:
        return None

    return {
        'address': address,
        'expires_at': expires_at,
        'issued_at': payload.get('issued_at') or datetime.fromtimestamp(
            float(payload.get('issued_at_ts') or 0)
        ).isoformat()
    }

def issue_admin_token(address):
    address = normalize_wallet_address(address)
    issued_at = time.time()
    expires_at = issued_at + ADMIN_TOKEN_TTL_SECONDS
    payload_b64 = encode_admin_token_payload({
        'address': address,
        'expires_at': expires_at,
        'issued_at_ts': issued_at,
        'nonce': secrets.token_urlsafe(12)
    })
    token = f"{payload_b64}.{sign_admin_token_payload(payload_b64)}"
    with admin_auth_lock:
        admin_tokens[token] = {
            'address': address,
            'expires_at': expires_at,
            'issued_at': datetime.now().isoformat()
        }
    return token, expires_at

def validate_admin_token(token):
    cleanup_admin_auth()
    if not token:
        return False, None, 'Admin authentication required'

    with admin_auth_lock:
        if admin_token_fingerprint(token) in revoked_admin_tokens:
            return False, None, 'Admin token is missing, invalid, or expired'
        token_data = admin_tokens.get(token)

    if not token_data:
        token_data = decode_signed_admin_token(token)

    if not token_data:
        return False, None, 'Admin token is missing, invalid, or expired'

    if token_data['expires_at'] <= time.time():
        with admin_auth_lock:
            admin_tokens.pop(token, None)
        return False, None, 'Admin token is missing, invalid, or expired'

    address = token_data['address']
    ready_error = get_blockchain_ready_error()
    if ready_error:
        return False, None, ready_error

    if not blockchain_service.is_admin(address):
        with admin_auth_lock:
            admin_tokens.pop(token, None)
        return False, None, 'Admin wallet is no longer authorized'

    return True, token_data, None

def get_blockchain_ready_error():
    if not blockchain_service:
        return 'Blockchain service not available'

    status = blockchain_service.get_blockchain_status()
    if not status.get('connected'):
        return f"Blockchain backend is offline: {status.get('error', 'Not connected to blockchain')}"
    if not blockchain_service.contract:
        return 'Blockchain contract is not loaded'
    return None

def require_admin_request(data=None):
    if not blockchain_service:
        return False, 'Blockchain service not available'
    if data is None:
        data = request.get_json(silent=True) or {}

    token = request.headers.get('X-Admin-Token') or data.get('admin_token')
    ok, _token_data, error = validate_admin_token(token)
    return ok, error

def admin_required_response(error):
    return jsonify({
        'success': False,
        'error': 'Bạn không có quyền thực hiện thao tác này. Vui lòng đăng nhập Admin bằng MetaMask.',
        'detail': error
    }), 403

def recognizer_status(instance):
    return {
        'status': 'ok',
        'type': type(instance).__name__,
        'use_yolo': getattr(instance, 'use_yolo', None),
        'detector_model': getattr(instance, 'detector_model_path', None),
        'detector_classes': getattr(instance, 'detector_model_names', None),
    }

def bbox_to_xyxy(bbox):
    if not bbox or len(bbox) != 4:
        return None

    x, y, w, h = [int(v) for v in bbox]
    if w <= 0 or h <= 0:
        return None

    return x, y, x + w, y + h

def format_plate_for_display(plate_number):
    text = (plate_number or '').upper().strip()
    if not text or text == 'UNKNOWN':
        return text

    parts = [p for p in re.split(r'-+', text) if p]
    compact = re.sub(r'[^A-Z0-9]', '', text)
    if len(compact) < 7:
        return text

    if len(parts) >= 2:
        top = ''.join(parts[:-1])
        bottom = parts[-1]
    else:
        top_len = 4 if len(compact) >= 9 else 3
        top = compact[:top_len]
        bottom = compact[top_len:]

    top = re.sub(r'[^A-Z0-9]', '', top)
    bottom = re.sub(r'[^0-9]', '', bottom)
    if len(top) == 3:
        top = top
    elif len(top) > 3:
        top = f"{top[:2]}-{top[2:]}"
    if len(bottom) == 5:
        bottom = f"{bottom[:3]}.{bottom[3:]}"

    return f"{top}-{bottom}" if bottom else top

def normalize_plate_input(plate_number):
    """Normalize plate input before all blockchain/local lookups."""
    text = (plate_number or '').strip()
    if not text:
        return ''
    if normalize_plate_number:
        try:
            return normalize_plate_number(text)
        except Exception:
            pass
    return format_plate_for_display(text)

def mask_owner_name(name):
    """Mask owner name for public/non-admin access. 'Nguyễn Văn A' -> 'N****** A'"""
    name = (name or '').strip()
    if not name:
        return 'Đã xác thực chủ sở hữu'
    parts = name.split()
    if len(parts) == 1:
        if len(parts[0]) <= 1:
            return parts[0] + '***'
        return parts[0][0] + '*' * (len(parts[0]) - 1)
    first = parts[0][0] + '*' * max(1, len(parts[0]) - 1)
    last = parts[-1]
    return f"{first} {last}"

def is_request_admin():
    """Check if the current request has valid admin credentials (non-blocking)."""
    try:
        data = request.get_json(silent=True) or {}
        token = request.headers.get('X-Admin-Token') or data.get('admin_token') or request.args.get('admin_token')
        if not token:
            return False
        ok, _token_data, _error = validate_admin_token(token)
        return ok
    except Exception:
        return False

def public_blockchain_status(status):
    status = dict(status or {})
    for field in ('rpc', 'rpc_candidates', 'account', 'contract_address'):
        status.pop(field, None)
    return status

def public_plate_summary(plate):
    return {
        'plate_number': plate.get('plate_number', ''),
        'owner_name': mask_owner_name(plate.get('owner_name', '')),
        'vehicle_type': plate.get('vehicle_type', ''),
        'province': plate.get('province', ''),
        'registered_at': plate.get('registered_at', ''),
        'is_active': bool(plate.get('is_active')),
    }

def public_plate_info(info):
    info = dict(info or {})
    info['owner_name'] = mask_owner_name(info.get('owner_name', ''))
    for field in ('color', 'last_updated', 'contract_plate_number'):
        info.pop(field, None)
    return info

def public_transfer_history(history):
    return [
        {
            **dict(item),
            'previous_owner': mask_owner_name(item.get('previous_owner', '')),
            'new_owner': mask_owner_name(item.get('new_owner', '')),
        }
        for item in (history or [])
    ]

def public_stolen_result(result):
    sanitized = dict(result or {})
    vehicles = []
    for item in sanitized.get('vehicles', []):
        vehicle = dict(item)
        vehicle['owner_name'] = mask_owner_name(vehicle.get('owner_name', ''))
        vehicle.pop('description', None)
        vehicles.append(vehicle)
    sanitized['vehicles'] = vehicles
    return sanitized

def public_stolen_check_result(result):
    sanitized = dict(result or {})
    vehicle = sanitized.get('vehicle')
    if vehicle:
        vehicle = dict(vehicle)
        vehicle['owner_name'] = mask_owner_name(vehicle.get('owner_name', ''))
        vehicle.pop('description', None)
        sanitized['vehicle'] = vehicle
    return sanitized

def public_timeline_result(result):
    sanitized = dict(result or {})
    transactions = []
    for item in sanitized.get('transactions', []):
        transaction = dict(item)
        transaction.pop('owner_name', None)
        transaction.pop('details', None)
        transactions.append(transaction)
    sanitized['transactions'] = transactions
    return sanitized

def public_qr_result(result):
    sanitized = dict(result or {})
    if 'owner_name' in sanitized:
        sanitized['owner_name'] = mask_owner_name(sanitized.get('owner_name', ''))
    data = sanitized.get('data')
    if isinstance(data, dict):
        data = dict(data)
        data['owner_name'] = mask_owner_name(data.get('owner_name', ''))
        sanitized['data'] = data
    return sanitized

def frame_to_base64(frame, quality=60, max_width=640):
    """Convert frame to base64 with optimization"""
    # Resize if too large
    if frame.shape[1] > max_width:
        ratio = max_width / frame.shape[1]
        new_height = int(frame.shape[0] * ratio)
        frame = cv2.resize(frame, (max_width, new_height))
    
    # Encode to JPEG with low quality for speed
    _, buffer = cv2.imencode('.jpg', frame, [cv2.IMWRITE_JPEG_QUALITY, quality])
    return base64.b64encode(buffer).decode('utf-8')

def draw_detections(frame, detections):
    frame_copy = frame.copy()
    for detection in detections:
        bbox = detection.get('bbox', (0, 0, 0, 0))
        plate_number = detection.get('display_plate_number') or format_plate_for_display(detection.get('plate_number', 'UNKNOWN'))
        confidence = detection.get('confidence', 0.0)
        xyxy = bbox_to_xyxy(bbox)
        if xyxy:
            x1, y1, x2, y2 = xyxy
            cv2.rectangle(frame_copy, (x1, y1), (x2, y2), (0, 255, 0), 2)
            text = f"{plate_number} ({confidence:.2f})"
            font = cv2.FONT_HERSHEY_SIMPLEX
            text_size = cv2.getTextSize(text, font, 0.6, 2)[0]
            text_x, text_y = x1, max(y1 - 10, 20)
            cv2.rectangle(frame_copy, (text_x-5, text_y-text_size[1]-5),
                         (text_x+text_size[0]+5, text_y+5), (0, 255, 0), -1)
            cv2.putText(frame_copy, text, (text_x, text_y), font, 0.6, (0, 0, 0), 2)
    return frame_copy

def assess_ocr_detection(detection, frame_shape=None):
    """Calibrate OCR confidence so UI does not present a partial read as certain."""
    plate_number = (detection.get('plate_number') or '').upper().strip()
    raw_confidence = float(detection.get('confidence', 0.0) or 0.0)
    compact = re.sub(r'[^A-Z0-9]', '', plate_number)
    warnings = []
    cap = 0.90

    if not plate_number or plate_number == 'UNKNOWN':
        cap = 0.0
        warnings.append('Chưa đọc được biển số')
    elif not recognizer._is_plausible_plate_number(plate_number):
        cap = 0.20
        warnings.append('Không khớp định dạng biển số Việt Nam')
    else:
        top, bottom = recognizer._split_plate_top_bottom(plate_number)
        top = re.sub(r'[^A-Z0-9]', '', top)
        bottom = re.sub(r'[^0-9]', '', bottom)

        if len(top) == 4 and len(bottom) == 5:
            cap = 0.90
        elif len(top) == 3 and len(bottom) == 5:
            cap = 0.86
        elif len(top) == 4 and len(bottom) == 4:
            cap = 0.62
            warnings.append('Biển có nhóm số cuối ngắn, cần xác nhận lại')
        else:
            cap = 0.45
            warnings.append('OCR có thể chỉ đọc được một phần biển số')

        if len(compact) < 8:
            cap = min(cap, 0.45)
            warnings.append('Biển số đọc được quá ngắn so với biển hiện hành')

    bbox = detection.get('bbox')
    if bbox and frame_shape:
        xyxy = bbox_to_xyxy(bbox)
        if xyxy:
            x1, y1, x2, y2 = xyxy
            h, w = frame_shape[:2]
            margin = 3
            if x1 <= margin or y1 <= margin or x2 >= w - margin or y2 >= h - margin:
                cap = min(cap, 0.70)
                warnings.append('Khung biển chạm mép ảnh, có thể bị cắt mất ký tự')

    adjusted_confidence = max(0.0, min(raw_confidence, cap))
    needs_review = adjusted_confidence < 0.70 or bool(warnings)

    detection['raw_confidence'] = raw_confidence
    detection['confidence'] = adjusted_confidence
    detection['needs_review'] = needs_review
    detection['quality_label'] = 'high' if adjusted_confidence >= 0.75 and not needs_review else ('medium' if adjusted_confidence >= 0.50 else 'low')
    detection['quality_message'] = '; '.join(dict.fromkeys(warnings)) if warnings else 'OCR khớp định dạng, vẫn cần xác nhận trước khi tra blockchain'
    return detection

def replace_queue_item(queue_obj, item):
    try:
        while True:
            queue_obj.get_nowait()
    except queue.Empty:
        pass

    try:
        queue_obj.put_nowait(item)
    except queue.Full:
        pass

def clear_queue(queue_obj):
    try:
        while True:
            queue_obj.get_nowait()
    except queue.Empty:
        pass

def warmup_webcam_ocr():
    try:
        recognizer._ensure_easyocr_reader()
    except Exception as e:
        utils.log_message(f"Webcam OCR warmup failed: {e}", 'WARNING')

def get_plate_region_signature(frame):
    try:
        regions = recognizer._find_bright_plate_like_regions(frame)
    except Exception as e:
        utils.log_message(f"Fast webcam plate scan failed: {e}", 'DEBUG')
        regions = []

    if regions:
        region, x, y = regions[0]
        h, w = region.shape[:2]
        if w > 0 and h > 0:
            # Quantize the box so minor camera jitter does not enqueue redundant OCR jobs.
            return (1, int(x / 64), int(y / 64), int(w / 64), int(h / 64))

    # Fallback signature for a plate image shown on a phone screen.  The old
    # logic returned None here, so deep recognition was rarely scheduled.
    h, w = frame.shape[:2]
    x1 = int(w * 0.24)
    y1 = int(h * 0.14)
    x2 = int(w * 0.84)
    y2 = int(h * 0.92)
    roi = frame[y1:y2, x1:x2]
    if roi.size == 0:
        return None

    gray = cv2.cvtColor(roi, cv2.COLOR_BGR2GRAY) if len(roi.shape) == 3 else roi
    p95 = float(np.percentile(gray, 95))
    p99 = float(np.percentile(gray, 99))
    edge_ratio = float(np.mean(cv2.Canny(gray, 60, 160) > 0))
    bright_ratio = float(np.mean(gray > 150))
    if p95 < 95 and p99 < 145 and edge_ratio < 0.025 and bright_ratio < 0.015:
        return None

    return (
        2,
        int(float(np.mean(gray)) / 18),
        int(float(np.std(gray)) / 18),
        int(p95 / 18),
        int(edge_ratio * 60)
    )

def signatures_match(first, second):
    if first is None or second is None:
        return first is None and second is None
    if len(first) != len(second):
        return False
    if int(first[0]) != int(second[0]):
        return False
    tolerance = 4 if int(first[0]) == 2 else 2
    return all(abs(int(a) - int(b)) <= tolerance for a, b in zip(first[1:], second[1:]))

def should_publish_webcam_result(candidates, frame_signature, current_signature, frame_started_at):
    """Accept valid OCR results even if the phone/frame signature drifted while OCR ran."""
    if not candidates:
        return False
    if signatures_match(frame_signature, current_signature):
        return True

    now = time.time()
    if frame_started_at and now - frame_started_at > WEBCAM_SIGNATURE_RESULT_TOLERANCE_SECONDS:
        return False

    best = max(
        candidates,
        key=lambda item: float(item.get('quality', item.get('confidence', 0.0)) or 0.0)
    )
    best_confidence = float(best.get('confidence', 0.0) or 0.0)
    best_quality = float(best.get('quality', best_confidence) or 0.0)

    if frame_signature is None or current_signature is None:
        return best_confidence >= WEBCAM_PUBLISH_SINGLE_CONFIDENCE

    if len(frame_signature) == len(current_signature) and int(frame_signature[0]) == int(current_signature[0]):
        return best_confidence >= WEBCAM_CANDIDATE_MIN_CONFIDENCE

    return best_confidence >= WEBCAM_PUBLISH_SINGLE_CONFIDENCE and best_quality >= WEBCAM_PUBLISH_REPEAT_QUALITY

def clear_latest_webcam_result(clear_candidates=True):
    global latest_webcam_detections, latest_webcam_detections_at, latest_webcam_signature, webcam_candidate_history
    latest_webcam_detections = []
    latest_webcam_detections_at = 0
    latest_webcam_signature = None
    if clear_candidates:
        webcam_candidate_history = []

def remove_webcam_temp_frame():
    try:
        os.remove(WEBCAM_TEMP_FRAME_PATH)
    except FileNotFoundError:
        pass
    except Exception as e:
        utils.log_message(f"Could not remove webcam temp frame: {e}", 'DEBUG')

def score_webcam_detection(detection, frame_shape):
    bbox = detection.get('bbox', (0, 0, 0, 0))
    confidence = float(detection.get('confidence', 0.0) or 0.0)
    method = detection.get('method', '')
    strategy = detection.get('strategy', '')
    quality = confidence

    if method == 'full_frame_easyocr':
        quality += 0.18
    if 'bright_plate_region' in strategy:
        quality += 0.22

    xyxy = bbox_to_xyxy(bbox)
    if xyxy:
        x1, y1, x2, y2 = xyxy
        w = max(1, x2 - x1)
        h = max(1, y2 - y1)
        aspect = w / h
        area_ratio = (w * h) / max(1, frame_shape[0] * frame_shape[1])

        if 1.4 <= aspect <= 6.2:
            quality += 0.12
        if area_ratio > 0.22:
            quality -= 0.5
        if h > frame_shape[0] * 0.38:
            quality -= 0.35

    return quality

def webcam_candidate_key(plate_number):
    return re.sub(r'[^A-Z0-9]', '', (plate_number or '').upper())

def update_webcam_stable_detections(candidates, frame_signature):
    """Return detections only after confidence/temporal stability checks pass."""
    global webcam_candidate_history

    now = time.time()
    webcam_candidate_history = [
        item for item in webcam_candidate_history
        if now - item['timestamp'] <= WEBCAM_CANDIDATE_WINDOW_SECONDS
    ]

    current_keys = set()
    for candidate in candidates:
        confidence = float(candidate.get('confidence', 0.0) or 0.0)
        if confidence < WEBCAM_CANDIDATE_MIN_CONFIDENCE:
            continue

        key = webcam_candidate_key(candidate.get('plate_number', ''))
        if not key:
            continue

        current_keys.add(key)
        webcam_candidate_history.append({
            'key': key,
            'signature': frame_signature,
            'timestamp': now,
            'detection': candidate
        })

    if not webcam_candidate_history:
        return []

    grouped = {}
    for item in webcam_candidate_history:
        grouped.setdefault(item['key'], []).append(item)

    publishable = []
    for key, items in grouped.items():
        if key not in current_keys:
            continue

        best_item = max(items, key=lambda item: float(item['detection'].get('confidence', 0.0) or 0.0))
        best_confidence = float(best_item['detection'].get('confidence', 0.0) or 0.0)
        best_quality = float(best_item['detection'].get('quality', best_confidence) or 0.0)
        avg_confidence = float(np.mean([
            float(item['detection'].get('confidence', 0.0) or 0.0)
            for item in items
        ]))
        avg_quality = float(np.mean([
            float(item['detection'].get('quality', item['detection'].get('confidence', 0.0)) or 0.0)
            for item in items
        ]))

        if (
            best_confidence >= WEBCAM_PUBLISH_HIGH_CONFIDENCE
            or (
                best_confidence >= WEBCAM_PUBLISH_SINGLE_CONFIDENCE
                and best_quality >= WEBCAM_PUBLISH_SINGLE_QUALITY
            )
            or (
                len(items) >= WEBCAM_PUBLISH_MIN_HITS
                and (
                    avg_confidence >= WEBCAM_PUBLISH_MIN_CONFIDENCE
                    or (
                        avg_confidence >= WEBCAM_PUBLISH_REPEAT_CONFIDENCE
                        and avg_quality >= WEBCAM_PUBLISH_REPEAT_QUALITY
                    )
                )
            )
        ):
            publishable.append(best_item['detection'])

    publishable.sort(key=lambda item: float(item.get('confidence', 0.0) or 0.0), reverse=True)
    return publishable[:1]

def select_webcam_detections(plates, frame_shape):
    best_by_plate = {}

    for p in plates:
        r = p.get('recognition', {})
        plate_number = r.get('plate_number', 'UNKNOWN')
        confidence = float(r.get('confidence', 0.0) or 0.0)
        if (
            not plate_number
            or plate_number == 'UNKNOWN'
            or not recognizer._is_plausible_plate_number(plate_number)
        ):
            continue

        candidate = {
            'bbox': p.get('bbox', (0, 0, 0, 0)),
            'plate_number': plate_number,
            'display_plate_number': format_plate_for_display(plate_number),
            'confidence': confidence,
            'method': r.get('method', ''),
            'strategy': r.get('strategy', '')
        }
        candidate = assess_ocr_detection(candidate, frame_shape)
        candidate['quality'] = score_webcam_detection(candidate, frame_shape)
        existing = best_by_plate.get(plate_number)
        if not existing or candidate['quality'] > existing['quality']:
            best_by_plate[plate_number] = candidate

    selected = sorted(best_by_plate.values(), key=lambda item: item['quality'], reverse=True)
    return selected[:1]

def open_webcam():
    if os.name == 'nt':
        cap = cv2.VideoCapture(0, cv2.CAP_DSHOW)
        if cap.isOpened():
            return cap
        cap.release()
    return cv2.VideoCapture(0)

def webcam_recognition_worker():
    global latest_webcam_detections, latest_webcam_detections_at, latest_webcam_signature, webcam_recognition_busy

    while is_streaming:
        try:
            item = recognition_queue.get(timeout=0.5)
        except queue.Empty:
            continue

        try:
            if isinstance(item, dict):
                frame = item.get('frame')
                frame_signature = item.get('signature')
                deep_scan = item.get('deep_scan', True)
            else:
                frame = item
                frame_signature = None
                deep_scan = True
            if frame is None:
                continue

            with webcam_lock:
                webcam_recognition_busy = True

            frame_started_at = time.time()
            fast_result = recognizer.recognize_webcam_frame_fast(frame)
            flat = select_webcam_detections(fast_result.get('plates', []), frame.shape)

            if not flat and deep_scan:
                result = recognizer.recognize_webcam_frame_deep(
                    frame,
                    detection_confidence=0.12,
                    yolo_imgsz=480
                )
                flat = select_webcam_detections(result.get('plates', []), frame.shape)

            stable = []
            with webcam_lock:
                current_signature = current_webcam_signature
                if should_publish_webcam_result(flat, frame_signature, current_signature, frame_started_at):
                    publish_signature = current_signature if current_signature is not None else frame_signature
                    stable = update_webcam_stable_detections(flat, publish_signature)
                    if stable:
                        latest_webcam_detections = stable
                        latest_webcam_detections_at = time.time()
                        latest_webcam_signature = publish_signature
                else:
                    utils.log_message("Discarded stale webcam recognition result", 'DEBUG')

            for d in stable:
                detection_history.append({
                    'timestamp': datetime.now().isoformat(),
                    'plate_number': d['plate_number'],
                    'confidence': d['confidence']
                })
            while len(detection_history) > MAX_HISTORY:
                detection_history.pop(0)
        except Exception as e:
            utils.log_message(f"Error processing webcam recognition frame: {e}", 'ERROR')
            with webcam_lock:
                clear_latest_webcam_result()
        finally:
            with webcam_lock:
                webcam_recognition_busy = False
            try:
                recognition_queue.task_done()
            except ValueError:
                pass

def webcam_worker():
    """Stream webcam frames continuously; recognition runs in a separate worker."""
    global is_streaming, current_webcam_signature, latest_stream_payload, latest_stream_payload_at
    cap = open_webcam()
    if not cap.isOpened():
        utils.log_message("Could not open webcam device 0", 'ERROR')
        is_streaming = False
        return

    # Reduce capture resolution for speed
    cap.set(cv2.CAP_PROP_FRAME_WIDTH, 640)
    cap.set(cv2.CAP_PROP_FRAME_HEIGHT, 480)
    cap.set(cv2.CAP_PROP_FPS, 30)
    cap.set(cv2.CAP_PROP_BUFFERSIZE, 1)
    
    last_stream_at = 0
    last_recognition_request_at = 0
    last_deep_recognition_request_at = 0
    last_background_recognition_request_at = 0
    last_region_signature = None
    read_failures = 0

    while is_streaming:
        ret, frame = cap.read()
        if not ret:
            read_failures += 1
            if read_failures >= 20:
                utils.log_message("Webcam stopped returning frames", 'ERROR')
                break
            time.sleep(0.05)
            continue

        read_failures = 0
        now = time.time()

        try:
            region_signature = get_plate_region_signature(frame)
            should_recognize = False
            signature_changed = not signatures_match(region_signature, last_region_signature)

            with webcam_lock:
                current_webcam_signature = region_signature
            if signature_changed and region_signature is None:
                last_region_signature = None
                remove_webcam_temp_frame()

            if region_signature:
                if (
                    signature_changed
                    or now - last_recognition_request_at >= WEBCAM_FAST_RECOGNITION_INTERVAL_SECONDS
                ):
                    should_recognize = True
                    last_region_signature = region_signature
            else:
                # Still run a deep scan periodically. A plate displayed on a phone
                # screen often fails the bright-region signature check even though it
                # is readable to OCR.
                deep_due = (
                    last_deep_recognition_request_at == 0
                    or now - last_deep_recognition_request_at >= WEBCAM_DEEP_RECOGNITION_INTERVAL_SECONDS
                )
                if (
                    deep_due
                    and now - last_background_recognition_request_at >= WEBCAM_BACKGROUND_RECOGNITION_INTERVAL_SECONDS
                ):
                    should_recognize = True
                    last_background_recognition_request_at = now
                    last_region_signature = None

            with webcam_lock:
                recognition_busy = webcam_recognition_busy

            if should_recognize and not recognition_busy and recognition_queue.empty():
                deep_due = (
                    last_deep_recognition_request_at == 0
                    or now - last_deep_recognition_request_at >= WEBCAM_DEEP_RECOGNITION_INTERVAL_SECONDS
                )
                deep_scan = WEBCAM_ENABLE_DEEP_SCAN and deep_due
                if deep_scan:
                    last_deep_recognition_request_at = now
                replace_queue_item(recognition_queue, {
                    'frame': frame.copy(),
                    'signature': region_signature,
                    'deep_scan': deep_scan
                })
                last_recognition_request_at = now

            if now - last_stream_at >= WEBCAM_STREAM_INTERVAL_SECONDS:
                with webcam_lock:
                    detections = list(latest_webcam_detections)
                    detection_age = now - latest_webcam_detections_at if latest_webcam_detections_at else None
                    detection_signature = latest_webcam_signature
                    active_signature = current_webcam_signature
                    recognition_pending = webcam_recognition_busy or not recognition_queue.empty()

                active_detections = detections if (
                    detection_age is not None
                    and detection_age <= WEBCAM_DETECTION_TTL_SECONDS
                ) else []
                output_frame = draw_detections(frame, active_detections) if active_detections else frame
                payload = {
                    'frame': frame_to_base64(output_frame, quality=55, max_width=640),
                    'detections': active_detections,
                    'recognition_pending': recognition_pending,
                    'timestamp': datetime.now().isoformat()
                }
                with webcam_lock:
                    latest_stream_payload = payload
                    latest_stream_payload_at = now
                replace_queue_item(stream_queue, payload)
                last_stream_at = now

            time.sleep(0.005)
        except Exception as e:
            utils.log_message(f"Webcam worker error: {e}", 'ERROR')
            break
    
    cap.release()
    is_streaming = False


# ============ PAGE ROUTES ============
@app.route('/')
def index():
    return render_template('index.html')

# ============ RECOGNITION API ============
@app.route('/api/start-webcam', methods=['POST'])
def start_webcam():
    global webcam_thread, webcam_recognition_thread, is_streaming, current_webcam_signature, webcam_recognition_busy, latest_stream_payload, latest_stream_payload_at
    if is_streaming: return jsonify({'status': 'already_running'})
    is_streaming = True
    clear_queue(stream_queue)
    clear_queue(recognition_queue)
    with webcam_lock:
        clear_latest_webcam_result()
        current_webcam_signature = None
        webcam_recognition_busy = False
        latest_stream_payload = None
        latest_stream_payload_at = 0
    remove_webcam_temp_frame()
    threading.Thread(target=warmup_webcam_ocr, daemon=True).start()
    webcam_recognition_thread = threading.Thread(target=webcam_recognition_worker, daemon=True)
    webcam_thread = threading.Thread(target=webcam_worker, daemon=True)
    webcam_recognition_thread.start()
    webcam_thread.start()
    return jsonify({'status': 'started'})

@app.route('/api/stop-webcam', methods=['POST'])
def stop_webcam():
    global is_streaming, current_webcam_signature, webcam_recognition_busy, latest_stream_payload, latest_stream_payload_at
    is_streaming = False
    clear_queue(stream_queue)
    clear_queue(recognition_queue)
    with webcam_lock:
        clear_latest_webcam_result()
        current_webcam_signature = None
        webcam_recognition_busy = False
        latest_stream_payload = None
        latest_stream_payload_at = 0
    remove_webcam_temp_frame()
    return jsonify({'status': 'stopped'})

@app.route('/api/stream')
def stream_frames():
    def gen():
        last_payload_at = 0
        last_ping_at = 0
        while is_streaming:
            now = time.time()
            with webcam_lock:
                payload = latest_stream_payload.copy() if latest_stream_payload else None
                payload_at = latest_stream_payload_at

            if payload and payload_at != last_payload_at:
                last_payload_at = payload_at
                yield f"data: {json.dumps(payload)}\n\n"
            elif now - last_ping_at >= 1.5:
                last_ping_at = now
                yield f"data: {json.dumps({'type': 'ping'})}\n\n"

            time.sleep(WEBCAM_STREAM_INTERVAL_SECONDS)
    return app.response_class(gen(), mimetype='text/event-stream')

@app.route('/api/webcam-status')
def webcam_status():
    now = time.time()
    with webcam_lock:
        latest_payload_age = now - latest_stream_payload_at if latest_stream_payload_at else None
        latest_detection_age = now - latest_webcam_detections_at if latest_webcam_detections_at else None
        return jsonify({
            'streaming': is_streaming,
            'recognition_busy': webcam_recognition_busy,
            'recognition_queue_size': recognition_queue.qsize(),
            'stream_queue_size': stream_queue.qsize(),
            'candidate_count': len(webcam_candidate_history),
            'latest_payload_age': latest_payload_age,
            'latest_detection_age': latest_detection_age,
            'latest_detections': latest_webcam_detections,
            'current_signature': current_webcam_signature,
            'latest_signature': latest_webcam_signature
        })

@app.route('/api/process-image', methods=['POST'])
def process_image():
    if 'image' not in request.files:
        return jsonify({'error': 'No image file provided'}), 400
    file = request.files['image']
    if file.filename == '' or not allowed_file(file.filename, ALLOWED_IMAGE_EXTENSIONS):
        return jsonify({'error': 'Invalid image'}), 400
    try:
        filename = f"img_{int(datetime.now().timestamp()*1000)}.jpg"
        filepath = os.path.join(UPLOAD_FOLDER, filename)
        file.save(filepath)
        if not os.path.exists(filepath) or os.path.getsize(filepath) == 0:
            return jsonify({'error': 'Upload failed'}), 400
        image = cv2.imread(filepath)
        if image is None: return jsonify({'error': 'Failed to read image'}), 400
        result = recognizer.recognize_plate(filepath)
        flat = []
        for p in result.get('plates', []):
            r = p.get('recognition', {})
            pn = normalize_plate_input(r.get('plate_number', 'UNKNOWN'))
            if not pn or pn == 'UNKNOWN':
                continue
            detection = {'bbox': p.get('bbox', (0,0,0,0)),
                         'plate_number': pn,
                         'display_plate_number': format_plate_for_display(pn),
                         'confidence': r.get('confidence', 0.0),
                         'raw_text': r.get('raw_text', ''),
                         'strategy': r.get('strategy', '')}
            flat.append(assess_ocr_detection(detection, image.shape))
        for d in flat:
            detection_history.append({'timestamp': datetime.now().isoformat(),
                                      'plate_number': d['plate_number'], 'confidence': d['confidence']})
        img_result = draw_detections(image, flat)
        result_fn = f"result_{int(datetime.now().timestamp()*1000)}.jpg"
        result_path = os.path.join(RESULTS_FOLDER, result_fn)
        cv2.imwrite(result_path, img_result)
        return jsonify({'status': 'success', 'detections': flat,
                       'result_image': result_path, 'detection_count': len(flat)})
    except Exception as e:
        traceback.print_exc()
        return jsonify({'error': str(e)}), 500

@app.route('/api/upload-video', methods=['POST'])
def upload_video():
    if 'video' not in request.files:
        return jsonify({'error': 'No video file provided'}), 400
    file = request.files['video']
    if file.filename == '': return jsonify({'error': 'No video selected'}), 400
    ext = file.filename.rsplit('.', 1)[1].lower() if '.' in file.filename else ''
    if not allowed_file(file.filename, ALLOWED_VIDEO_EXTENSIONS):
        return jsonify({'error': 'Invalid video format'}), 400
    try:
        filename = f"vid_{int(datetime.now().timestamp()*1000)}.{ext}"
        filepath = os.path.join(UPLOAD_FOLDER, filename)
        file.save(filepath)
        result_fn = f"result_{int(datetime.now().timestamp()*1000)}.mp4"
        result_path = os.path.join(RESULTS_FOLDER, result_fn)
        detections = video_recognizer.process_video(
            filepath,
            output_path=result_path,
            confidence_threshold=0.5,
            render_preview=False
        )
        plates = set()
        for d in detections:
            if isinstance(d, dict) and 'plate_number' in d: plates.add(d['plate_number'])
        return jsonify({'status': 'success', 'result_video': result_path,
                       'total_detections': len(detections), 'unique_plates': list(plates),
                       'unique_count': len(plates)})
    except Exception as e:
        traceback.print_exc()
        return jsonify({'error': str(e)}), 500

@app.route('/api/history')
def get_history():
    return jsonify(detection_history[-50:])

@app.route('/api/stats')
def get_stats():
    if not detection_history:
        return jsonify({'total_detections': 0, 'unique_plates': 0, 'unique_count': 0, 'detection_rate': 0})
    unique = set(d['plate_number'] for d in detection_history)
    return jsonify({'total_detections': len(detection_history), 'unique_plates': list(unique),
                   'unique_count': len(unique),
                   'average_confidence': float(np.mean([d['confidence'] for d in detection_history if 'confidence' in d]))})

def record_timeline_transaction(transaction_type, result, owner_name='', details=''):
    if not timeline_available or not result or not result.get('success'):
        return

    try:
        timeline_manager.add_transaction(
            transaction_type=transaction_type,
            plate_number=result.get('plate_number', ''),
            tx_hash=result.get('tx_hash', ''),
            block_number=result.get('block_number', 0),
            gas_used=result.get('gas_used', 0),
            owner_name=owner_name,
            details=details
        )
    except Exception as e:
        utils.log_message(f"Could not record timeline transaction: {e}", 'WARNING')

def sync_timeline_from_chain_events(force=False):
    global last_timeline_chain_sync_at
    if not timeline_available or not blockchain_service or not getattr(blockchain_service, 'connected', False):
        return

    now = time.time()
    if not force and now - last_timeline_chain_sync_at < 60:
        return

    try:
        latest_block = blockchain_service.w3.eth.block_number
        from_block = max(0, latest_block - 49000)

        def event_timestamp(args):
            try:
                ts = int(args.get('timestamp', 0) or 0)
                return datetime.fromtimestamp(ts).isoformat() if ts > 0 else None
            except Exception:
                return None

        def receipt_for(log):
            try:
                return blockchain_service.w3.eth.get_transaction_receipt(log.transactionHash)
            except Exception:
                return None

        for log in blockchain_service.contract.events.PlateRegistered().get_logs(from_block=from_block, to_block='latest'):
            args = dict(log.args)
            receipt = receipt_for(log)
            timeline_manager.add_transaction(
                transaction_type='register',
                plate_number=args.get('plateNumber', ''),
                tx_hash=log.transactionHash.hex(),
                block_number=log.blockNumber,
                gas_used=getattr(receipt, 'gasUsed', 0) if receipt else 0,
                owner_name=args.get('ownerName', ''),
                details=f"Đăng ký biển số; loại xe: {args.get('vehicleType', 'N/A')}; tỉnh: {args.get('province', 'N/A')}",
                timestamp=event_timestamp(args)
            )

        for log in blockchain_service.contract.events.OwnershipTransferred().get_logs(from_block=from_block, to_block='latest'):
            args = dict(log.args)
            receipt = receipt_for(log)
            timeline_manager.add_transaction(
                transaction_type='transfer',
                plate_number=args.get('plateNumber', ''),
                tx_hash=log.transactionHash.hex(),
                block_number=log.blockNumber,
                gas_used=getattr(receipt, 'gasUsed', 0) if receipt else 0,
                owner_name=args.get('newOwner', ''),
                details=f"Chuyển từ {args.get('previousOwner', 'N/A')} sang {args.get('newOwner', 'N/A')}",
                timestamp=event_timestamp(args)
            )

        if hasattr(blockchain_service.contract.events, 'VehicleUpdated'):
            for log in blockchain_service.contract.events.VehicleUpdated().get_logs(from_block=from_block, to_block='latest'):
                args = dict(log.args)
                receipt = receipt_for(log)
                timeline_manager.add_transaction(
                    transaction_type='update',
                    plate_number=args.get('plateNumber', ''),
                    tx_hash=log.transactionHash.hex(),
                    block_number=log.blockNumber,
                    gas_used=getattr(receipt, 'gasUsed', 0) if receipt else 0,
                    details=f"Cập nhật phương tiện; loại xe: {args.get('vehicleType', 'N/A')}; màu: {args.get('color', 'N/A')}; tỉnh: {args.get('province', 'N/A')}",
                    timestamp=event_timestamp(args)
                )

        for log in blockchain_service.contract.events.PlateDeactivated().get_logs(from_block=from_block, to_block='latest'):
            args = dict(log.args)
            receipt = receipt_for(log)
            timeline_manager.add_transaction(
                transaction_type='deactivate',
                plate_number=args.get('plateNumber', ''),
                tx_hash=log.transactionHash.hex(),
                block_number=log.blockNumber,
                gas_used=getattr(receipt, 'gasUsed', 0) if receipt else 0,
                details='Khóa phương tiện / vô hiệu hóa biển số',
                timestamp=event_timestamp(args)
            )

        if hasattr(blockchain_service.contract.events, 'PlateReactivated'):
            for log in blockchain_service.contract.events.PlateReactivated().get_logs(from_block=from_block, to_block='latest'):
                args = dict(log.args)
                receipt = receipt_for(log)
                timeline_manager.add_transaction(
                    transaction_type='reactivate',
                    plate_number=args.get('plateNumber', ''),
                    tx_hash=log.transactionHash.hex(),
                    block_number=log.blockNumber,
                    gas_used=getattr(receipt, 'gasUsed', 0) if receipt else 0,
                    details='Mở khóa phương tiện / kích hoạt lại biển số',
                    timestamp=event_timestamp(args)
                )

        for log in blockchain_service.contract.events.ViolationAdded().get_logs(from_block=from_block, to_block='latest'):
            args = dict(log.args)
            receipt = receipt_for(log)
            timeline_manager.add_transaction(
                transaction_type='violation',
                plate_number=args.get('plateNumber', ''),
                tx_hash=log.transactionHash.hex(),
                block_number=log.blockNumber,
                gas_used=getattr(receipt, 'gasUsed', 0) if receipt else 0,
                details=f"{args.get('description', '')}; tiền phạt: {args.get('fineAmount', 0)} VND",
                timestamp=event_timestamp(args)
            )

        if hasattr(blockchain_service.contract.events, 'ViolationPaid'):
            for log in blockchain_service.contract.events.ViolationPaid().get_logs(from_block=from_block, to_block='latest'):
                args = dict(log.args)
                receipt = receipt_for(log)
                timeline_manager.add_transaction(
                    transaction_type='fine_paid',
                    plate_number=args.get('plateNumber', ''),
                    tx_hash=log.transactionHash.hex(),
                    block_number=log.blockNumber,
                    gas_used=getattr(receipt, 'gasUsed', 0) if receipt else 0,
                    details=f"Đã xử lý nộp phạt cho lỗi #{args.get('violationIndex', 0)}",
                    timestamp=event_timestamp(args)
                )

        last_timeline_chain_sync_at = now
    except Exception as e:
        utils.log_message(f"Could not sync timeline from chain events: {e}", 'WARNING')


# ============ BLOCKCHAIN API ============
@app.route('/api/blockchain/status')
def blockchain_status():
    if not blockchain_service:
        return jsonify({'connected': False, 'error': 'Blockchain service not initialized'})
    status = blockchain_service.get_blockchain_status()
    return jsonify(status if is_request_admin() else public_blockchain_status(status))

@app.route('/api/blockchain/register', methods=['POST'])
def blockchain_register():
    if not blockchain_service:
        return jsonify({'success': False, 'error': 'Blockchain not available'}), 503
    data = request.get_json(silent=True)
    if not data: return jsonify({'success': False, 'error': 'No data provided'}), 400

    is_admin, auth_error = require_admin_request(data)
    if not is_admin:
        return admin_required_response(auth_error)

    pn = normalize_plate_input(data.get('plate_number', ''))
    on = data.get('owner_name', '').strip()
    vt = data.get('vehicle_type', '').strip()
    cl = data.get('color', '').strip()
    pv = data.get('province', '').strip()
    if not pn or not on:
        return jsonify({'success': False, 'error': 'Biển số và tên chủ xe là bắt buộc'}), 400
    result = blockchain_service.register_plate(pn, on, vt, cl, pv)
    record_timeline_transaction(
        'register',
        result,
        owner_name=on,
        details=f"Đăng ký biển số cho {on}; loại xe: {vt or 'N/A'}; màu: {cl or 'N/A'}; tỉnh: {pv or 'N/A'}"
    )
    return jsonify(result), 200 if result['success'] else 400

@app.route('/api/blockchain/verify/<plate_number>')
def blockchain_verify(plate_number):
    if not blockchain_service:
        return jsonify({'verified': False, 'is_registered': False, 'error': 'Blockchain not available'}), 503
    plate_number = normalize_plate_input(plate_number)
    result = blockchain_service.verify_plate(plate_number)
    if not is_request_admin() and result.get('is_registered'):
        result = public_plate_info(result)
    return jsonify(result)

@app.route('/api/blockchain/info/<plate_number>')
def blockchain_info(plate_number):
    if not blockchain_service:
        return jsonify({'success': False, 'error': 'Blockchain not available'}), 503
    plate_number = normalize_plate_input(plate_number)
    result = blockchain_service.get_plate_info(plate_number)
    if not is_request_admin() and result.get('found'):
        result = public_plate_info(result)
    return jsonify(result)

@app.route('/api/blockchain/update', methods=['POST'])
def blockchain_update():
    if not blockchain_service:
        return jsonify({'success': False, 'error': 'Blockchain not available'}), 503
    data = request.get_json(silent=True) or {}
    is_admin, auth_error = require_admin_request(data)
    if not is_admin:
        return admin_required_response(auth_error)

    pn = normalize_plate_input(data.get('plate_number', ''))
    vt = data.get('vehicle_type', '').strip()
    cl = data.get('color', '').strip()
    pv = data.get('province', '').strip()
    if not pn:
        return jsonify({'success': False, 'error': 'Biển số là bắt buộc'}), 400

    result = blockchain_service.update_vehicle(pn, vt, cl, pv)
    record_timeline_transaction(
        'update',
        result,
        details=f"Cập nhật thông tin phương tiện; loại xe: {result.get('vehicle_type', vt or 'N/A')}; màu: {result.get('color', cl or 'N/A')}; tỉnh: {result.get('province', pv or 'N/A')}"
    )
    return jsonify(result), 200 if result['success'] else 400

@app.route('/api/blockchain/transfer', methods=['POST'])
def blockchain_transfer():
    if not blockchain_service:
        return jsonify({'success': False, 'error': 'Blockchain not available'}), 503
    data = request.get_json(silent=True)
    if not data: return jsonify({'success': False, 'error': 'No data'}), 400
    is_admin, auth_error = require_admin_request(data)
    if not is_admin:
        return admin_required_response(auth_error)

    pn = normalize_plate_input(data.get('plate_number', ''))
    no = data.get('new_owner', '').strip()
    if not pn or not no:
        return jsonify({'success': False, 'error': 'Biển số và tên chủ mới là bắt buộc'}), 400
    result = blockchain_service.transfer_ownership(pn, no)
    record_timeline_transaction(
        'transfer',
        result,
        owner_name=no,
        details=f"Chuyển nhượng sang chủ mới: {no}"
    )
    return jsonify(result), 200 if result['success'] else 400

@app.route('/api/blockchain/deactivate', methods=['POST'])
def blockchain_deactivate():
    if not blockchain_service:
        return jsonify({'success': False, 'error': 'Blockchain not available'}), 503
    data = request.get_json(silent=True)
    if not data: return jsonify({'success': False, 'error': 'No data'}), 400

    is_admin, auth_error = require_admin_request(data)
    if not is_admin:
        return admin_required_response(auth_error)

    pn = normalize_plate_input(data.get('plate_number', ''))
    if not pn:
        return jsonify({'success': False, 'error': 'Biển số là bắt buộc'}), 400
    result = blockchain_service.deactivate_plate(pn)
    record_timeline_transaction('deactivate', result, details='Khóa phương tiện / vô hiệu hóa biển số')
    return jsonify(result), 200 if result['success'] else 400

@app.route('/api/blockchain/reactivate', methods=['POST'])
def blockchain_reactivate():
    if not blockchain_service:
        return jsonify({'success': False, 'error': 'Blockchain not available'}), 503
    data = request.get_json(silent=True)
    if not data:
        return jsonify({'success': False, 'error': 'No data'}), 400

    is_admin, auth_error = require_admin_request(data)
    if not is_admin:
        return admin_required_response(auth_error)

    pn = normalize_plate_input(data.get('plate_number', ''))
    if not pn:
        return jsonify({'success': False, 'error': 'Biển số là bắt buộc'}), 400

    result = blockchain_service.reactivate_plate(
        pn,
        owner_name=data.get('owner_name', '').strip(),
        vehicle_type=data.get('vehicle_type', '').strip(),
        color=data.get('color', '').strip(),
        province=data.get('province', '').strip()
    )
    record_timeline_transaction(
        'reactivate',
        result,
        owner_name=result.get('owner', ''),
        details='Mở khóa phương tiện / kích hoạt lại biển số'
    )
    return jsonify(result), 200 if result['success'] else 400

@app.route('/api/blockchain/violation', methods=['POST'])
def blockchain_violation():
    if not blockchain_service:
        return jsonify({'success': False, 'error': 'Blockchain not available'}), 503
    data = request.get_json(silent=True)
    if not data: return jsonify({'success': False, 'error': 'No data'}), 400

    is_admin, auth_error = require_admin_request(data)
    if not is_admin:
        return admin_required_response(auth_error)

    pn = normalize_plate_input(data.get('plate_number', ''))
    desc = data.get('description', '').strip()
    fine = data.get('fine_amount', 0)
    if not pn or not desc:
        return jsonify({'success': False, 'error': 'Thiếu thông tin bắt buộc'}), 400
    result = blockchain_service.add_violation(pn, desc, fine)
    record_timeline_transaction(
        'violation',
        result,
        details=f"{desc}; tiền phạt: {fine} VND"
    )
    return jsonify(result), 200 if result['success'] else 400

@app.route('/api/blockchain/violation/paid', methods=['POST'])
def blockchain_violation_paid():
    if not blockchain_service:
        return jsonify({'success': False, 'error': 'Blockchain not available'}), 503
    data = request.get_json(silent=True)
    if not data:
        return jsonify({'success': False, 'error': 'No data'}), 400

    is_admin, auth_error = require_admin_request(data)
    if not is_admin:
        return admin_required_response(auth_error)

    pn = normalize_plate_input(data.get('plate_number', ''))
    violation_index = data.get('violation_index')
    if not pn:
        return jsonify({'success': False, 'error': 'Biển số là bắt buộc'}), 400
    if violation_index is None:
        return jsonify({'success': False, 'error': 'Số thứ tự vi phạm là bắt buộc'}), 400

    result = blockchain_service.mark_violation_paid(pn, violation_index)
    record_timeline_transaction(
        'fine_paid',
        result,
        details=f"Đã xử lý nộp phạt cho lỗi #{result.get('violation_index', violation_index)}"
    )
    return jsonify(result), 200 if result['success'] else 400

@app.route('/api/blockchain/violations/<plate_number>')
def blockchain_violations_get(plate_number):
    if not blockchain_service: return jsonify([])
    return jsonify(blockchain_service.get_violations(normalize_plate_input(plate_number)))

@app.route('/api/blockchain/plates')
def blockchain_plates():
    if not blockchain_service: return jsonify([])
    plates = blockchain_service.get_all_plates()
    if not is_request_admin():
        plates = [public_plate_summary(p) for p in plates]
    return jsonify(plates)

@app.route('/api/blockchain/history/<plate_number>')
def blockchain_history(plate_number):
    if not blockchain_service: return jsonify([])
    history = blockchain_service.get_plate_history(normalize_plate_input(plate_number))
    return jsonify(history if is_request_admin() else public_transfer_history(history))

@app.route('/api/blockchain/statistics')
def blockchain_statistics():
    if not blockchain_service:
        return jsonify({'total_registered': 0, 'total_verifications': 0,
                       'total_transfers': 0, 'total_violations': 0,
                       'total_plates': 0, 'active_plates': 0,
                       'inactive_plates': 0, 'connected': False})
    return jsonify(blockchain_service.get_statistics())

@app.route('/api/recognize-and-verify', methods=['POST'])
def recognize_and_verify():
    if 'image' not in request.files:
        return jsonify({'error': 'No image file provided'}), 400
    file = request.files['image']
    if file.filename == '' or not allowed_file(file.filename, ALLOWED_IMAGE_EXTENSIONS):
        return jsonify({'error': 'Invalid image'}), 400
    try:
        filename = f"img_{int(datetime.now().timestamp()*1000)}.jpg"
        filepath = os.path.join(UPLOAD_FOLDER, filename)
        file.save(filepath)
        image = cv2.imread(filepath)
        if image is None:
            return jsonify({'error': 'Failed to read image'}), 400
        result = recognizer.recognize_plate(filepath)
        results = []
        for p in result.get('plates', []):
            r = p.get('recognition', {})
            pn = r.get('plate_number', 'UNKNOWN')
            if not pn or pn == 'UNKNOWN':
                continue
            det = {'bbox': p.get('bbox', (0,0,0,0)), 'plate_number': pn,
                   'display_plate_number': format_plate_for_display(pn),
                   'confidence': r.get('confidence', 0.0),
                   'blockchain_verified': False, 'blockchain_info': None,
                   'violations': [], 'is_active': True}
            det = assess_ocr_detection(det, image.shape)
            if blockchain_service and pn != 'UNKNOWN':
                vr = blockchain_service.verify_plate(pn)
                det['blockchain_verified'] = vr.get('is_registered', False)
                if vr.get('is_registered'): 
                    info = blockchain_service.get_plate_info(pn)
                    det['blockchain_info'] = info if is_request_admin() else public_plate_info(info)
                    det['is_active'] = info.get('is_active', True)
                    # Fetch violations
                    det['violations'] = blockchain_service.get_violations(pn)
            results.append(det)
        result_path = ''
        img_result = draw_detections(image, results)
        result_fn = f"result_{int(datetime.now().timestamp()*1000)}.jpg"
        result_path = os.path.join(RESULTS_FOLDER, result_fn)
        cv2.imwrite(result_path, img_result)
        return jsonify({'status': 'success', 'detections': results,
                       'result_image': result_path, 'detection_count': len(results)})
    except Exception as e:
        traceback.print_exc()
        return jsonify({'error': str(e)}), 500

@app.route('/api/image-authenticate', methods=['POST'])
def image_authenticate():
    """
    Comprehensive image-based authentication endpoint
    Nhận dạng biển số từ ảnh và xác thực trên blockchain
    Returns detailed verification results
    """
    if 'image' not in request.files:
        return jsonify({'success': False, 'error': 'Không tìm thấy tệp ảnh'}), 400
    
    file = request.files['image']
    if file.filename == '' or not allowed_file(file.filename, ALLOWED_IMAGE_EXTENSIONS):
        return jsonify({'success': False, 'error': 'Định dạng ảnh không hợp lệ'}), 400
    
    try:
        # Save uploaded image
        filename = f"auth_{int(datetime.now().timestamp()*1000)}.jpg"
        filepath = os.path.join(UPLOAD_FOLDER, filename)
        file.save(filepath)
        
        # Recognize plates from image
        image = cv2.imread(filepath)
        if image is None:
            return jsonify({'success': False, 'error': 'Khong doc duoc anh'}), 400
        result = recognizer.recognize_plate(filepath)
        detections = []
        
        for p in result.get('plates', []):
            r = p.get('recognition', {})
            plate_number = normalize_plate_input(r.get('plate_number', 'UNKNOWN'))
            if not plate_number or plate_number == 'UNKNOWN':
                continue
            confidence = r.get('confidence', 0.0)
            
            # Build detection result
            detection = {
                'plate_number': plate_number,
                'display_plate_number': format_plate_for_display(plate_number),
                'confidence': float(confidence),
                'bbox': p.get('bbox', (0, 0, 0, 0)),
                'recognized': plate_number != 'UNKNOWN',
                'blockchain': {
                    'registered': False,
                    'active': False,
                    'owner_name': '',
                    'vehicle_type': '',
                    'color': '',
                    'province': '',
                    'registered_at': '',
                    'violations': [],
                    'is_stolen': False,
                    'violation_count': 0,
                    'unpaid_fines': 0
                },
                'verification_status': 'UNKNOWN',  # VERIFIED, STOLEN, UNREGISTERED, UNKNOWN
                'alert': None
            }
            detection = assess_ocr_detection(detection, image.shape)
            
            # Verify on blockchain if plate was recognized
            req_is_admin = is_request_admin()

            if blockchain_service and plate_number != 'UNKNOWN':
                try:
                    vr = blockchain_service.verify_plate(plate_number)
                    
                    if vr.get('is_registered'):
                        canonical_plate_number = vr.get('plate_number') or format_plate_for_display(plate_number)
                        detection['display_plate_number'] = canonical_plate_number
                        detection['blockchain']['plate_number'] = canonical_plate_number
                        detection['blockchain']['registered'] = True
                        
                        # Get detailed plate info
                        info = blockchain_service.get_plate_info(plate_number)
                        if info:
                            detection['blockchain']['active'] = info.get('is_active', True)
                            raw_owner = info.get('owner_name', '')
                            detection['blockchain']['owner_name'] = raw_owner if req_is_admin else mask_owner_name(raw_owner)
                            detection['blockchain']['vehicle_type'] = info.get('vehicle_type', '')
                            detection['blockchain']['color'] = info.get('color', '')
                            detection['blockchain']['province'] = info.get('province', '')
                            detection['blockchain']['registered_at'] = info.get('registered_at', '')
                        
                        # Check violations
                        violations = blockchain_service.get_violations(plate_number)
                        detection['blockchain']['violations'] = violations if violations else []
                        detection['blockchain']['violation_count'] = len(violations) if violations else 0
                        
                        # Calculate unpaid fines
                        unpaid_violations = [v for v in violations if not v.get('is_paid', False)] if violations else []
                        detection['blockchain']['unpaid_fines'] = sum(v.get('fine_amount', 0) for v in unpaid_violations)
                        
                        # Determine verification status
                        if not detection['blockchain']['active']:
                            detection['verification_status'] = 'STOLEN'
                            detection['alert'] = '🚨 XE BÁO MẤT CẮP / BIỂN GIẢ'
                        elif unpaid_violations:
                            detection['verification_status'] = 'VIOLATION'
                            detection['alert'] = f'⚠️ CÓ {len(unpaid_violations)} LỖI PHẠT NGUỘI'
                        else:
                            detection['verification_status'] = 'VERIFIED'
                            detection['alert'] = '✅ XE HỢP LỆ'
                    else:
                        detection['verification_status'] = 'UNREGISTERED'
                        detection['alert'] = '❓ CHƯA ĐĂNG KÝ TRÊN BLOCKCHAIN'
                        
                except Exception as e:
                    utils.log_message(f"Blockchain verification error: {e}", 'WARNING')
                    detection['blockchain']['error'] = str(e)
            
            detections.append(detection)
            
            # Add to history
            detection_history.append({
                'timestamp': datetime.now().isoformat(),
                'plate_number': plate_number,
                'confidence': detection['confidence'],
                'is_registered': detection['blockchain']['registered']
            })
        
        # Create result image with detections
        result_path = ''
        result_image_b64 = ''
        
        img_result = draw_detections(image, detections)
        result_fn = f"auth_result_{int(datetime.now().timestamp()*1000)}.jpg"
        result_path = os.path.join(RESULTS_FOLDER, result_fn)
        cv2.imwrite(result_path, img_result)
        
        # Also encode to base64 for direct display
        _, buffer = cv2.imencode('.jpg', img_result, [cv2.IMWRITE_JPEG_QUALITY, 85])
        result_image_b64 = base64.b64encode(buffer).decode('utf-8')
        
        # Trim history
        while len(detection_history) > MAX_HISTORY:
            detection_history.pop(0)
        
        return jsonify({
            'success': True,
            'timestamp': datetime.now().isoformat(),
            'image_file': filename,
            'result_image_path': result_path,
            'result_image_base64': result_image_b64,
            'detections': detections,
            'detection_count': len(detections),
            'registered_count': sum(1 for d in detections if d['blockchain']['registered']),
            'alert_count': sum(1 for d in detections if d['alert'] and 'lỗi' in d['alert'].lower()),
            'stolen_count': sum(1 for d in detections if d['verification_status'] == 'STOLEN')
        })
        
    except Exception as e:
        utils.log_message(f"Image authentication error: {e}", 'ERROR')
        traceback.print_exc()
        return jsonify({
            'success': False,
            'error': f'Lỗi xử lý ảnh: {str(e)}'
        }), 500

# ============ WALLET CONNECTION ============
user_wallets = {}  # Store connected wallets {session_id: {address, network, connected_at}}

@app.route('/api/wallet-connect', methods=['POST'])
def wallet_connect():
    """Handle Metamask wallet connection"""
    try:
        data = request.json
        address = data.get('address', '').lower()
        network = data.get('network', '')
        
        if not address or len(address) != 42 or not address.startswith('0x'):
            return jsonify({'success': False, 'error': 'Invalid wallet address'}), 400
        
        # Store wallet info
        session_id = request.headers.get('X-Session-ID', 'default')
        user_wallets[session_id] = {
            'address': address,
            'network': network,
            'connected_at': datetime.now().isoformat(),
            'transaction_count': 0
        }
        
        utils.log_message(f"Wallet connected: {address} on network {network}", 'INFO')
        
        return jsonify({
            'success': True,
            'message': f'Ví được kết nối thành công: {address}',
            'wallet': {
                'address': address,
                'network': network,
                'connected_at': user_wallets[session_id]['connected_at']
            }
        })
    
    except Exception as e:
        utils.log_message(f"Wallet connection error: {e}", 'ERROR')
        return jsonify({'success': False, 'error': str(e)}), 500

@app.route('/api/wallet-status', methods=['GET'])
def wallet_status():
    """Get current wallet connection status"""
    try:
        session_id = request.headers.get('X-Session-ID', 'default')
        wallet = user_wallets.get(session_id)
        
        if wallet:
            result = {
                'connected': True,
                'address': wallet['address'] if is_request_admin() else f"{wallet['address'][:6]}...{wallet['address'][-4:]}",
                'network': wallet['network'],
                'connected_at': wallet['connected_at'],
                'transaction_count': wallet['transaction_count']
            }
            return jsonify(result)
        else:
            return jsonify({'connected': False})
    
    except Exception as e:
        return jsonify({'connected': False, 'error': str(e)}), 500

# ============ ADMIN AUTHORIZATION ============
@app.route('/api/auth/challenge', methods=['POST'])
def admin_auth_challenge():
    """Create a one-time MetaMask signing challenge for the contract admin."""
    try:
        data = request.get_json(silent=True) or {}
        address = normalize_wallet_address(data.get('address'))
        if not address:
            return jsonify({'success': False, 'is_admin': False, 'error': 'Invalid wallet address'}), 400

        if not blockchain_service:
            return jsonify({'success': False, 'is_admin': False, 'error': 'Blockchain service not available'}), 503

        ready_error = get_blockchain_ready_error()
        if ready_error:
            return jsonify({'success': False, 'is_admin': False, 'error': ready_error}), 503

        admin_address, admin_error = get_expected_admin_address()
        if admin_error:
            return jsonify({'success': False, 'is_admin': False, 'error': admin_error}), 503

        if address != admin_address or not blockchain_service.is_admin(address):
            return jsonify({
                'success': False,
                'is_admin': False,
                'error': 'Bạn không có quyền Admin'
            }), 403

        nonce = secrets.token_urlsafe(24)
        message = build_admin_challenge_message(address, nonce)
        expires_at = time.time() + ADMIN_CHALLENGE_TTL_SECONDS

        cleanup_admin_auth()
        with admin_auth_lock:
            admin_challenges[nonce] = {
                'address': address,
                'message': message,
                'expires_at': expires_at
            }

        return jsonify({
            'success': True,
            'is_admin': True,
            'message': message,
            'nonce': nonce,
            'expires_in': ADMIN_CHALLENGE_TTL_SECONDS
        })

    except Exception as e:
        utils.log_message(f"Admin challenge error: {e}", 'ERROR')
        return jsonify({'success': False, 'is_admin': False, 'error': str(e)}), 500

@app.route('/api/admin/check', methods=['POST'])
def admin_check():
    """Verify a signed admin challenge or validate an existing admin token."""
    try:
        data = request.get_json(silent=True) or {}
        if not data and not request.headers.get('X-Admin-Token'):
            return jsonify({'is_admin': False, 'error': 'Admin authentication required'}), 200

        if not blockchain_service:
            return jsonify({'is_admin': False, 'error': 'Blockchain service not available'}), 503

        ready_error = get_blockchain_ready_error()
        if ready_error:
            return jsonify({'is_admin': False, 'error': ready_error}), 503

        admin_address, admin_error = get_expected_admin_address()
        if admin_error:
            return jsonify({'is_admin': False, 'error': admin_error}), 503

        token = request.headers.get('X-Admin-Token') or data.get('admin_token')
        if token:
            ok, token_data, error = validate_admin_token(token)
            result = {
                'is_admin': ok,
                'error': error,
                'wallet_address': token_data['address'] if token_data else None,
                'expires_at': token_data['expires_at'] if token_data else None
            }
            if ok:
                result['admin_address'] = admin_address
                result['contract_address'] = blockchain_service.contract.address if blockchain_service.contract else None
            return jsonify(result)

        address = normalize_wallet_address(data.get('address'))
        if not address:
            return jsonify({'is_admin': False, 'error': 'Invalid wallet address'}), 400

        nonce = data.get('nonce', '')
        signature = data.get('signature', '')
        if not nonce or not signature:
            return jsonify({
                'is_admin': False,
                'error': 'Signed admin challenge required',
                'wallet_address': address
            }), 401

        if not wallet_signature_available:
            return jsonify({'is_admin': False, 'error': 'Wallet signature verification not available'}), 503

        cleanup_admin_auth()
        with admin_auth_lock:
            challenge = admin_challenges.get(nonce)

        if not challenge or challenge['address'] != address:
            return jsonify({'is_admin': False, 'error': 'Admin challenge is invalid or expired'}), 401

        try:
            recovered = Account.recover_message(
                encode_defunct(text=challenge['message']),
                signature=signature
            ).lower()
        except Exception as e:
            return jsonify({'is_admin': False, 'error': f'Invalid signature: {e}'}), 401

        if recovered != address:
            return jsonify({'is_admin': False, 'error': 'Signature does not match wallet address'}), 401

        if address != admin_address or not blockchain_service.is_admin(address):
            return jsonify({
                'is_admin': False,
                'error': 'Bạn không có quyền Admin'
            }), 403

        with admin_auth_lock:
            admin_challenges.pop(nonce, None)

        admin_token, expires_at = issue_admin_token(address)
        utils.log_message(f"Admin authorized: {address}", 'INFO')

        return jsonify({
            'is_admin': True,
            'wallet_address': address,
            'admin_address': admin_address,
            'contract_address': blockchain_service.contract.address if blockchain_service.contract else None,
            'admin_token': admin_token,
            'expires_at': expires_at,
            'expires_in': ADMIN_TOKEN_TTL_SECONDS
        })

    except Exception as e:
        utils.log_message(f"Admin check error: {e}", 'ERROR')
        return jsonify({'is_admin': False, 'error': str(e)}), 500

@app.route('/api/admin/logout', methods=['POST'])
def admin_logout():
    """Revoke the current local admin token."""
    data = request.get_json(silent=True) or {}
    token = request.headers.get('X-Admin-Token') or data.get('admin_token')
    revoke_admin_token(token)
    return jsonify({'success': True, 'is_admin': False})

# ============ UTILITY ROUTES ============
@app.route('/results/<filename>')
def serve_result(filename):
    try:
        file_path = os.path.join(RESULTS_FOLDER, filename)
        if not os.path.exists(file_path):
            return jsonify({'error': 'File not found'}), 404
        return send_from_directory(RESULTS_FOLDER, filename)
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/health')
def health():
    blockchain_status = blockchain_service.get_blockchain_status() if blockchain_service else {'connected': False}
    return jsonify({'status': 'healthy',
                   'blockchain': blockchain_status if is_request_admin() else public_blockchain_status(blockchain_status)})

@app.route('/api/test-system', methods=['GET'])
def test_system():
    is_admin, auth_error = require_admin_request()
    if not is_admin:
        return admin_required_response(auth_error)

    result = {'status': 'ok', 'components': {}}
    result['components']['recognizer'] = recognizer_status(recognizer)
    result['components']['video_recognizer'] = {'status': 'ok', 'type': type(video_recognizer).__name__}
    video_inner_recognizer = getattr(video_recognizer, 'recognizer', None)
    if video_inner_recognizer is not None:
        result['components']['video_recognizer']['recognizer'] = recognizer_status(video_inner_recognizer)
    if blockchain_service:
        bc = blockchain_service.get_blockchain_status()
        result['components']['blockchain'] = {'status': 'ok' if bc.get('connected') else 'disconnected', 'details': bc}
    else:
        result['components']['blockchain'] = {'status': 'not_initialized'}
    result['folders'] = {'uploads': os.path.exists(UPLOAD_FOLDER), 'results': os.path.exists(RESULTS_FOLDER)}
    return jsonify(result)


# ============ STOLEN VEHICLES API ============
@app.route('/api/stolen/add', methods=['POST'])
def stolen_add():
    """Thêm xe bị trộm vào danh sách"""
    if not stolen_manager_available:
        return jsonify({'success': False, 'error': 'Stolen vehicles service not available'}), 503
    
    data = request.get_json(silent=True)
    if not data:
        return jsonify({'success': False, 'error': 'No data provided'}), 400

    is_admin, auth_error = require_admin_request(data)
    if not is_admin:
        return admin_required_response(auth_error)
    
    result = stolen_manager.add_stolen_vehicle(
        plate_number=normalize_plate_input(data.get('plate_number', '')),
        owner_name=data.get('owner_name', '').strip(),
        vehicle_type=data.get('vehicle_type', '').strip(),
        color=data.get('color', '').strip(),
        province=data.get('province', '').strip(),
        report_date=data.get('report_date', '').strip(),
        description=data.get('description', '').strip()
    )
    if result.get('success'):
        if blockchain_service and getattr(blockchain_service, 'connected', False):
            lock_result = blockchain_service.deactivate_plate(normalize_plate_input(data.get('plate_number', '')))
        else:
            lock_result = {'success': False, 'error': 'Blockchain not available'}
        result['blockchain_lock'] = lock_result
        record_timeline_transaction(
            'deactivate',
            lock_result,
            details='Báo mất cắp và khóa phương tiện trên blockchain'
        )
    return jsonify(result), 200 if result['success'] else 400


@app.route('/api/stolen/check/<plate_number>')
def stolen_check(plate_number):
    """Kiểm tra xe có bị trộm không"""
    if not stolen_manager_available:
        return jsonify({'is_stolen': False, 'error': 'Service not available'}), 503
    
    plate_number = normalize_plate_input(plate_number)
    result = stolen_manager.check_stolen(plate_number)
    return jsonify(result if is_request_admin() else public_stolen_check_result(result))


@app.route('/api/stolen/list')
def stolen_list():
    """Lấy danh sách xe bị trộm"""
    if not stolen_manager_available:
        return jsonify({'total': 0, 'vehicles': []}), 503
    
    result = stolen_manager.get_all_stolen()
    return jsonify(result if is_request_admin() else public_stolen_result(result))


@app.route('/api/stolen/statistics')
def stolen_statistics():
    """Thống kê xe bị trộm"""
    if not stolen_manager_available:
        return jsonify({'error': 'Service not available'}), 503
    
    return jsonify(stolen_manager.get_statistics())


@app.route('/api/stolen/resolve/<plate_number>', methods=['POST'])
def stolen_resolve(plate_number):
    """Đánh dấu xe đã tìm thấy hoặc hủy báo cáo"""
    if not stolen_manager_available:
        return jsonify({'success': False, 'error': 'Service not available'}), 503
    
    data = request.get_json(silent=True) or {}
    is_admin, auth_error = require_admin_request(data)
    if not is_admin:
        return admin_required_response(auth_error)

    status = data.get('status', 'recovered')  # recovered or canceled
    
    plate_number = normalize_plate_input(plate_number)
    result = stolen_manager.remove_stolen_vehicle(plate_number, status)
    if result.get('success') and status in ('recovered', 'canceled'):
        if blockchain_service and getattr(blockchain_service, 'connected', False):
            unlock_result = blockchain_service.reactivate_plate(plate_number)
        else:
            unlock_result = {'success': False, 'error': 'Blockchain not available'}
        result['blockchain_unlock'] = unlock_result
        record_timeline_transaction(
            'reactivate',
            unlock_result,
            details='Xe mất cắp đã xử lý và mở khóa phương tiện trên blockchain'
        )
    return jsonify(result), 200 if result['success'] else 400


@app.route('/api/stolen/search')
def stolen_search():
    """Tìm kiếm xe bị trộm"""
    if not stolen_manager_available:
        return jsonify({'total': 0, 'vehicles': []}), 503
    
    plate = normalize_plate_input(request.args.get('plate', ''))
    owner = request.args.get('owner', '') if is_request_admin() else ''
    province = request.args.get('province', '')
    
    result = stolen_manager.search_vehicles(
        plate_number=plate if plate else None,
        owner_name=owner if owner else None,
        province=province if province else None
    )
    return jsonify(result if is_request_admin() else public_stolen_result(result))


# ============ QR CODE API ============
@app.route('/api/qr/generate', methods=['POST'])
def qr_generate():
    """Tạo QR code cho biển số xe"""
    if not qr_available:
        return jsonify({'success': False, 'error': 'QR code service not available'}), 503
    
    data = request.get_json(silent=True)
    if not data:
        return jsonify({'success': False, 'error': 'No data provided'}), 400

    is_admin, auth_error = require_admin_request(data)
    if not is_admin:
        return admin_required_response(auth_error)
    
    result = qr_manager.generate_qr_code(
        plate_number=normalize_plate_input(data.get('plate_number', '')),
        owner_name=mask_owner_name(data.get('owner_name', '').strip()),
        vehicle_type=data.get('vehicle_type', '').strip(),
        color=data.get('color', '').strip(),
        province=data.get('province', '').strip(),
        contract_address=data.get('contract_address', ''),
        tx_hash=data.get('tx_hash', '')
    )
    
    if result['success']:
        result['qr_image_url'] = f"/qr_codes/{result['qr_filename']}"
    
    return jsonify(result), 200 if result['success'] else 400


@app.route('/api/qr/verify', methods=['POST'])
def qr_verify():
    """Xác minh dữ liệu từ QR code"""
    if not qr_available:
        return jsonify({'verified': False, 'error': 'QR code service not available'}), 503
    
    data = request.get_json(silent=True)
    if not data:
        return jsonify({'verified': False, 'error': 'No data provided'}), 400
    
    qr_data = data.get('qr_data', '')
    plate_number = normalize_plate_input(data.get('plate_number', ''))
    
    result = qr_manager.verify_qr_code_data(qr_data, plate_number)
    return jsonify(result if is_request_admin() else public_qr_result(result))


@app.route('/api/qr/scan', methods=['POST'])
def qr_scan():
    """Scan QR code from an uploaded image and optionally verify plate number."""
    if 'image' not in request.files:
        return jsonify({'success': False, 'verified': False, 'error': 'No image file provided'}), 400

    file = request.files['image']
    if file.filename == '' or not allowed_file(file.filename, ALLOWED_IMAGE_EXTENSIONS):
        return jsonify({'success': False, 'verified': False, 'error': 'Invalid image'}), 400

    try:
        filename = f"qr_scan_{int(datetime.now().timestamp()*1000)}.jpg"
        filepath = os.path.join(UPLOAD_FOLDER, filename)
        file.save(filepath)

        image = cv2.imread(filepath)
        if image is None:
            return jsonify({'success': False, 'verified': False, 'error': 'Failed to read image'}), 400

        detector = cv2.QRCodeDetector()
        decoded_text, points, _ = detector.detectAndDecode(image)
        if not decoded_text:
            ok, decoded_info, points, _ = detector.detectAndDecodeMulti(image)
            if ok and decoded_info:
                decoded_text = next((item for item in decoded_info if item), '')

        if not decoded_text:
            return jsonify({'success': False, 'verified': False, 'error': 'No QR code detected'}), 400

        requested_plate = normalize_plate_input(request.form.get('plate_number') or '')
        data = json.loads(decoded_text)
        if requested_plate:
            verify_result = qr_manager.verify_qr_code_data(data, requested_plate)
        else:
            verify_result = {
                'verified': True,
                'data': data,
                'plate_number': data.get('plate_number'),
                'owner_name': data.get('owner_name'),
                'vehicle_type': data.get('vehicle_type'),
                'color': data.get('color'),
                'province': data.get('province'),
                'generated_at': data.get('generated_at')
            }

        verify_result.update({
            'success': verify_result.get('verified', False),
            'decoded_text': decoded_text,
            'image_file': filename
        })
        if not is_request_admin():
            verify_result = public_qr_result(verify_result)
        return jsonify(verify_result), 200 if verify_result.get('verified') else 400

    except json.JSONDecodeError:
        return jsonify({'success': False, 'verified': False, 'error': 'QR data is not valid JSON'}), 400
    except Exception as e:
        return jsonify({'success': False, 'verified': False, 'error': str(e)}), 500


@app.route('/qr_codes/<filename>')
def serve_qr(filename):
    """Phục vụ file QR code"""
    try:
        file_path = os.path.join('qr_codes', filename)
        if not os.path.exists(file_path):
            return jsonify({'error': 'File not found'}), 404
        return send_from_directory('qr_codes', filename)
    except Exception as e:
        return jsonify({'error': str(e)}), 500


# ============ BLOCKCHAIN TIMELINE API ============
@app.route('/api/timeline/add', methods=['POST'])
def timeline_add():
    """Thêm giao dịch vào timeline"""
    if not timeline_available:
        return jsonify({'success': False, 'error': 'Timeline service not available'}), 503
    
    data = request.get_json(silent=True)
    if not data:
        return jsonify({'success': False, 'error': 'No data provided'}), 400

    is_admin, auth_error = require_admin_request(data)
    if not is_admin:
        return admin_required_response(auth_error)
    
    result = timeline_manager.add_transaction(
        transaction_type=data.get('type', ''),
        plate_number=normalize_plate_input(data.get('plate_number', '')),
        tx_hash=data.get('tx_hash', ''),
        block_number=data.get('block_number', 0),
        gas_used=data.get('gas_used', 0),
        owner_name=data.get('owner_name', '').strip(),
        details=data.get('details', '').strip()
    )
    return jsonify(result)


@app.route('/api/timeline/plate/<plate_number>')
def timeline_plate(plate_number):
    """Lấy lịch sử giao dịch của một biển số"""
    if not timeline_available:
        return jsonify({'plate_number': plate_number, 'total_transactions': 0, 'transactions': []}), 503
    
    sync_timeline_from_chain_events()
    limit = request.args.get('limit', 50, type=int)
    result = timeline_manager.get_plate_history(normalize_plate_input(plate_number), limit=limit)
    return jsonify(result if is_request_admin() else public_timeline_result(result))


@app.route('/api/timeline/all')
def timeline_all():
    """Lấy toàn bộ timeline"""
    if not timeline_available:
        return jsonify({'total': 0, 'transactions': []}), 503
    
    sync_timeline_from_chain_events()
    tx_type = request.args.get('type', None)
    limit = request.args.get('limit', 100, type=int)
    
    result = timeline_manager.get_timeline(transaction_type=tx_type, limit=limit)
    return jsonify(result if is_request_admin() else public_timeline_result(result))


@app.route('/api/timeline/statistics')
def timeline_statistics():
    """Thống kê blockchain timeline"""
    if not timeline_available:
        return jsonify({'total_transactions': 0}), 503
    
    sync_timeline_from_chain_events()
    result = timeline_manager.get_statistics()
    return jsonify(result)


@app.route('/api/timeline/search')
def timeline_search():
    """Tìm kiếm giao dịch"""
    if not timeline_available:
        return jsonify({'total': 0, 'transactions': []}), 503
    
    sync_timeline_from_chain_events()
    plate = normalize_plate_input(request.args.get('plate', None)) if request.args.get('plate', None) else None
    tx_hash = request.args.get('tx_hash', None)
    tx_type = request.args.get('type', None)
    
    result = timeline_manager.search_transactions(
        plate_number=plate,
        tx_hash=tx_hash,
        tx_type=tx_type
    )
    return jsonify(result if is_request_admin() else public_timeline_result(result))


@app.route('/api/etherscan/link/<tx_hash>')
def etherscan_link(tx_hash):
    """Lấy link Etherscan cho transaction"""
    return jsonify({
        'tx_hash': tx_hash,
        'etherscan_url': f'https://sepolia.etherscan.io/tx/{tx_hash}',
        'network': 'Sepolia Testnet'
    })


@app.route('/api/etherscan/block/<int:block_number>')
def etherscan_block(block_number):
    """Lấy link Etherscan cho block"""
    return jsonify({
        'block_number': block_number,
        'etherscan_url': f'https://sepolia.etherscan.io/block/{block_number}',
        'network': 'Sepolia Testnet'
    })


if __name__ == '__main__':
    print("=" * 60)
    print("License Plate Recognition + Blockchain Verification")
    print("=" * 60)
    bc_status = 'Connected' if blockchain_service and blockchain_service.connected else 'Not connected'
    print(f"Blockchain: {bc_status}")
    print(f"Open browser at: http://localhost:5000")
    print("=" * 60)
    threading.Thread(target=warmup_webcam_ocr, daemon=True).start()
    debug_mode = os.environ.get('FLASK_DEBUG', '').lower() in {'1', 'true', 'yes', 'on'}
    app.run(debug=debug_mode, use_reloader=False, host='0.0.0.0', port=5000, threaded=True)
