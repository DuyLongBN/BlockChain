"""
QR Code Generator for License Plates
Tạo và xác minh QR code cho biển số xe
"""
import qrcode
import json
import os
import re
from datetime import datetime
from pathlib import Path
from PIL import Image, ImageDraw, ImageFont

QR_OUTPUT_FOLDER = 'qr_codes'

os.makedirs(QR_OUTPUT_FOLDER, exist_ok=True)

class QRCodeManager:
    @staticmethod
    def _safe_filename_part(value):
        safe = re.sub(r'[^A-Za-z0-9_.-]+', '_', str(value or '')).strip('._')
        return safe or 'plate'

    @staticmethod
    def _plate_key(value):
        return re.sub(r'[^A-Z0-9]', '', str(value or '').upper())

    """Quản lý QR code cho biển số xe"""
    
    @staticmethod
    def generate_qr_code(plate_number, owner_name, vehicle_type, 
                        color, province, contract_address='', tx_hash=''):
        """
        Tạo QR code chứa thông tin biển số xe
        """
        try:
            # Dữ liệu QR code
            qr_data = {
                'plate_number': plate_number,
                'owner_name': owner_name,
                'vehicle_type': vehicle_type,
                'color': color,
                'province': province,
                'generated_at': datetime.now().isoformat(),
                'contract_address': contract_address,
                'tx_hash': tx_hash
            }
            
            # Tạo QR code
            qr = qrcode.QRCode(
                version=1,
                error_correction=qrcode.constants.ERROR_CORRECT_L,
                box_size=10,
                border=4,
            )
            qr.add_data(json.dumps(qr_data, ensure_ascii=False))
            qr.make(fit=True)
            
            # Tạo ảnh QR code
            qr_img = qr.make_image(fill_color="black", back_color="white")
            
            # Thêm thông tin vào ảnh
            qr_img = QRCodeManager._add_info_to_qr(qr_img, qr_data)
            
            # Lưu file
            timestamp = int(datetime.now().timestamp() * 1000)
            filename = f"qr_{QRCodeManager._safe_filename_part(plate_number)}_{timestamp}.png"
            filepath = os.path.join(QR_OUTPUT_FOLDER, filename)
            
            qr_img.save(filepath)
            
            return {
                'success': True,
                'plate_number': plate_number,
                'qr_code_path': filepath,
                'qr_filename': filename,
                'qr_data': qr_data,
                'generated_at': datetime.now().isoformat()
            }
        
        except Exception as e:
            return {'success': False, 'error': str(e)}
    
    @staticmethod
    def _load_text_font(size):
        candidates = [
            r'C:\Windows\Fonts\arial.ttf',
            r'C:\Windows\Fonts\segoeui.ttf',
            r'C:\Windows\Fonts\tahoma.ttf',
            '/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf',
        ]
        for font_path in candidates:
            if os.path.exists(font_path):
                try:
                    return ImageFont.truetype(font_path, size)
                except Exception:
                    continue
        return ImageFont.load_default()

    @staticmethod
    def _text_width(draw, text, font):
        bbox = draw.textbbox((0, 0), text, font=font)
        return bbox[2] - bbox[0]

    @staticmethod
    def _add_info_to_qr(qr_img, qr_data):
        """
        Thêm thông tin text vào ảnh QR code
        """
        try:
            if hasattr(qr_img, 'get_image'):
                qr_img = qr_img.get_image()
            qr_img = qr_img.convert('RGB')

            width, height = qr_img.size
            info_lines = [
                f"Biển số: {qr_data.get('plate_number', '')}",
                f"Chủ xe: {qr_data.get('owner_name', '')}",
                f"Loại xe: {qr_data.get('vehicle_type', '')}",
            ]
            if qr_data.get('color'):
                info_lines.append(f"Màu sắc: {qr_data.get('color')}")
            if qr_data.get('province'):
                info_lines.append(f"Tỉnh/TP: {qr_data.get('province')}")

            title_font = QRCodeManager._load_text_font(18)
            body_font = QRCodeManager._load_text_font(16)
            line_height = 24
            padding_top = 12
            padding_bottom = 14
            new_height = height + padding_top + padding_bottom + line_height * len(info_lines)
            new_img = Image.new('RGB', (width, new_height), 'white')
            new_img.paste(qr_img, (0, 0))
            
            draw = ImageDraw.Draw(new_img)
            y = height + padding_top
            for index, text in enumerate(info_lines):
                font = title_font if index == 0 else body_font
                text_width = QRCodeManager._text_width(draw, text, font)
                text_x = max(8, (width - text_width) // 2)
                draw.text((text_x, y), text, fill='black', font=font)
                y += line_height
            
            return new_img
        except Exception:
            return qr_img
    
    @staticmethod
    def verify_qr_code_data(qr_data, plate_number):
        """
        Xác minh dữ liệu từ QR code
        """
        try:
            data = json.loads(qr_data) if isinstance(qr_data, str) else qr_data
            
            if QRCodeManager._plate_key(data.get('plate_number')) != QRCodeManager._plate_key(plate_number):
                return {'verified': False, 'error': 'Biển số không khớp'}
            
            return {
                'verified': True,
                'data': data,
                'plate_number': data.get('plate_number'),
                'owner_name': data.get('owner_name'),
                'vehicle_type': data.get('vehicle_type'),
                'color': data.get('color'),
                'province': data.get('province'),
                'generated_at': data.get('generated_at')
            }
        
        except Exception as e:
            return {'verified': False, 'error': str(e)}
    
    @staticmethod
    def get_qr_code_url(plate_number):
        """
        Lấy đường dẫn QR code cho biển số
        """
        # Tìm file QR code gần nhất cho biển số này
        safe_plate = QRCodeManager._safe_filename_part(plate_number)
        for filename in os.listdir(QR_OUTPUT_FOLDER):
            if safe_plate in filename:
                return os.path.join(QR_OUTPUT_FOLDER, filename)
        return None


# Khởi tạo global manager
qr_manager = QRCodeManager()
