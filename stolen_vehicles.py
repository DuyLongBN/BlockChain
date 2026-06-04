"""
Stolen Vehicles Management System
Hệ thống quản lý xe bị trộm
"""
import json
import os
from datetime import datetime, timedelta
from pathlib import Path

STOLEN_DB_FILE = 'stolen_vehicles.json'


def normalize_plate_number(plate_number):
    """Normalize Vietnamese plate numbers for local stolen-vehicle records."""
    text = str(plate_number or '').upper().strip()
    compact = ''.join(ch for ch in text if ch.isalnum())
    if len(compact) < 7:
        return text

    bottom_len = 5 if len(compact) >= 8 else 4
    top_len = len(compact) - bottom_len
    if top_len not in (3, 4):
        return text

    top = compact[:top_len]
    bottom = compact[top_len:]
    if not top[:2].isdigit() or not bottom.isdigit():
        return text

    if len(top) > 3:
        top = f"{top[:2]}-{top[2:]}"
    if len(bottom) == 5:
        bottom = f"{bottom[:3]}.{bottom[3:]}"
    return f"{top}-{bottom}"

class StolenVehicleManager:
    """Quản lý cơ sở dữ liệu xe bị trộm"""
    
    def __init__(self):
        self.db_file = STOLEN_DB_FILE
        self.data = self._load_db()

    def _plate_key(self, plate_number):
        """Return a stable key for comparing plate numbers."""
        return ''.join(ch for ch in str(plate_number or '').upper() if ch.isalnum())
    
    def _load_db(self):
        """Tải dữ liệu xe bị trộm từ file JSON"""
        if os.path.exists(self.db_file):
            try:
                with open(self.db_file, 'r', encoding='utf-8') as f:
                    return json.load(f)
            except:
                return {'vehicles': [], 'last_updated': None}
        return {'vehicles': [], 'last_updated': None}
    
    def _save_db(self):
        """Lưu dữ liệu xe bị trộm vào file JSON"""
        with open(self.db_file, 'w', encoding='utf-8') as f:
            json.dump(self.data, f, ensure_ascii=False, indent=2)
    
    def add_stolen_vehicle(self, plate_number, owner_name, vehicle_type, 
                          color, province, report_date, description=''):
        """
        Thêm xe bị trộm vào danh sách
        """
        plate_number = normalize_plate_number(plate_number)
        plate_key = self._plate_key(plate_number)
        if not plate_key:
            return {'success': False, 'error': 'Biển số không hợp lệ'}

        # Only active missing reports should block a new report.
        for vehicle in self.data['vehicles']:
            same_plate = self._plate_key(vehicle.get('plate_number')) == plate_key
            if same_plate and vehicle.get('status') == 'missing':
                return {'success': False, 'error': 'Xe này đang có trong danh sách mất cắp chưa xử lý'}
        
        stolen_record = {
            'plate_number': plate_number,
            'owner_name': owner_name,
            'vehicle_type': vehicle_type,
            'color': color,
            'province': province,
            'report_date': report_date,
            'description': description,
            'added_at': datetime.now().isoformat(),
            'status': 'missing'  # missing, recovered, canceled
        }
        
        self.data['vehicles'].append(stolen_record)
        self.data['last_updated'] = datetime.now().isoformat()
        self._save_db()
        
        return {
            'success': True,
            'message': f'Đã thêm xe {plate_number} vào danh sách xe bị trộm',
            'record': stolen_record
        }
    
    def remove_stolen_vehicle(self, plate_number, status='recovered'):
        """
        Cập nhật trạng thái xe (tìm thấy hoặc hủy báo cáo)
        """
        plate_key = self._plate_key(plate_number)
        for vehicle in self.data['vehicles']:
            if self._plate_key(vehicle.get('plate_number')) == plate_key and vehicle.get('status') == 'missing':
                vehicle['status'] = status
                vehicle['resolved_at'] = datetime.now().isoformat()
                self.data['last_updated'] = datetime.now().isoformat()
                self._save_db()
                return {
                    'success': True,
                    'message': f'Đã cập nhật trạng thái xe {plate_number}',
                    'record': vehicle
                }
        
        return {'success': False, 'error': 'Không tìm thấy xe trong danh sách'}
    
    def check_stolen(self, plate_number):
        """
        Kiểm tra xe có bị trộm không
        """
        plate_key = self._plate_key(plate_number)
        for vehicle in self.data['vehicles']:
            if self._plate_key(vehicle.get('plate_number')) == plate_key and vehicle['status'] == 'missing':
                return {
                    'is_stolen': True,
                    'vehicle': vehicle,
                    'warning': f'⚠️ CẢNH BÁO: Xe {plate_number} bị báo cáo mất trộm!'
                }
        
        return {'is_stolen': False, 'vehicle': None}
    
    def get_all_stolen(self):
        """
        Lấy danh sách tất cả xe bị trộm (chưa tìm thấy)
        """
        active_stolen = [v for v in self.data['vehicles'] if v['status'] == 'missing']
        return {
            'total': len(active_stolen),
            'vehicles': active_stolen
        }
    
    def get_statistics(self):
        """
        Thống kê xe bị trộm
        """
        vehicles = self.data['vehicles']
        total = len(vehicles)
        missing = len([v for v in vehicles if v['status'] == 'missing'])
        recovered = len([v for v in vehicles if v['status'] == 'recovered'])
        canceled = len([v for v in vehicles if v['status'] == 'canceled'])
        
        # Thống kê theo tỉnh
        by_province = {}
        for vehicle in vehicles:
            if vehicle['status'] == 'missing':
                province = vehicle.get('province', 'Không rõ')
                by_province[province] = by_province.get(province, 0) + 1
        
        return {
            'total_reports': total,
            'currently_missing': missing,
            'recovered': recovered,
            'canceled_reports': canceled,
            'by_province': by_province,
            'last_updated': self.data.get('last_updated')
        }
    
    def search_vehicles(self, plate_number=None, owner_name=None, province=None):
        """
        Tìm kiếm xe bị trộm theo điều kiện
        """
        results = self.data['vehicles']
        
        if plate_number:
            plate_key = self._plate_key(plate_number)
            results = [v for v in results if plate_key in self._plate_key(v.get('plate_number'))]
        if owner_name:
            results = [v for v in results if owner_name.lower() in v['owner_name'].lower()]
        if province:
            results = [v for v in results if province.lower() in v['province'].lower()]
        
        return {'total': len(results), 'vehicles': results}


# Khởi tạo global manager
stolen_manager = StolenVehicleManager()
