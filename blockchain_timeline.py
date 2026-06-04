"""
Blockchain Transaction Timeline & History
Lịch sử giao dịch blockchain
"""
import json
import os
from datetime import datetime
from pathlib import Path

TIMELINE_DB_FILE = 'blockchain_timeline.json'

class BlockchainTimeline:
    """Quản lý lịch sử giao dịch blockchain"""
    
    def __init__(self):
        self.db_file = TIMELINE_DB_FILE
        self.data = self._load_db()

    def _plate_key(self, plate_number):
        return ''.join(ch for ch in str(plate_number or '').upper() if ch.isalnum())
    
    def _load_db(self):
        """Tải lịch sử giao dịch"""
        if os.path.exists(self.db_file):
            try:
                with open(self.db_file, 'r', encoding='utf-8') as f:
                    return json.load(f)
            except:
                return {'transactions': [], 'statistics': {}}
        return {'transactions': [], 'statistics': {}}
    
    def _save_db(self):
        """Lưu lịch sử giao dịch"""
        with open(self.db_file, 'w', encoding='utf-8') as f:
            json.dump(self.data, f, ensure_ascii=False, indent=2)
    
    def add_transaction(self, transaction_type, plate_number, tx_hash, 
                       block_number, gas_used, owner_name='', details='', timestamp=None):
        """
        Thêm giao dịch vào timeline
        transaction_type: 'register', 'transfer', 'violation', 'deactivate', 'reactivate'
        """
        tx_hash = str(tx_hash or '')
        if tx_hash:
            for existing in self.data['transactions']:
                if str(existing.get('tx_hash', '')).lower() == tx_hash.lower():
                    return {'success': True, 'transaction': existing, 'duplicate': True}

        transaction = {
            'id': len(self.data['transactions']) + 1,
            'type': transaction_type,
            'plate_number': plate_number,
            'tx_hash': tx_hash,
            'block_number': block_number,
            'gas_used': gas_used,
            'owner_name': owner_name,
            'details': details,
            'timestamp': timestamp or datetime.now().isoformat(),
            'etherscan_url': f'https://sepolia.etherscan.io/tx/{tx_hash}',
            'block_url': f'https://sepolia.etherscan.io/block/{block_number}'
        }
        
        self.data['transactions'].append(transaction)
        self.data['transactions'].sort(key=lambda x: x['timestamp'], reverse=True)
        self._save_db()
        
        return {'success': True, 'transaction': transaction}
    
    def get_plate_history(self, plate_number, limit=50):
        """
        Lấy lịch sử giao dịch của một biển số
        """
        plate_key = self._plate_key(plate_number)
        history = [
            t for t in self.data['transactions']
            if self._plate_key(t.get('plate_number')) == plate_key
        ]
        return {
            'plate_number': plate_number,
            'total_transactions': len(history),
            'transactions': history[:limit]
        }
    
    def get_timeline(self, transaction_type=None, limit=100):
        """
        Lấy timeline các giao dịch
        """
        transactions = self.data['transactions']
        
        if transaction_type:
            transactions = [t for t in transactions if t['type'] == transaction_type]
        
        return {
            'total': len(transactions),
            'transactions': transactions[:limit]
        }
    
    def get_statistics(self):
        """
        Lấy thống kê giao dịch
        """
        transactions = self.data['transactions']
        
        if not transactions:
            return {
                'total_transactions': 0,
                'by_type': {},
                'total_gas_used': 0,
                'unique_plates': 0
            }
        
        stats = {
            'total_transactions': len(transactions),
            'by_type': {},
            'total_gas_used': sum(t.get('gas_used', 0) for t in transactions),
            'unique_plates': len(set(self._plate_key(t.get('plate_number')) for t in transactions)),
            'first_transaction': transactions[-1]['timestamp'],
            'last_transaction': transactions[0]['timestamp']
        }
        
        # Đếm theo loại giao dịch
        for tx in transactions:
            tx_type = tx['type']
            if tx_type not in stats['by_type']:
                stats['by_type'][tx_type] = 0
            stats['by_type'][tx_type] += 1
        
        return stats
    
    def get_timeline_json(self):
        """
        Trả về dữ liệu timeline dưới dạng JSON
        """
        return {
            'transactions': self.data['transactions'],
            'statistics': self.get_statistics()
        }
    
    def search_transactions(self, plate_number=None, tx_hash=None, tx_type=None):
        """
        Tìm kiếm giao dịch
        """
        results = self.data['transactions']
        
        if plate_number:
            plate_key = self._plate_key(plate_number)
            results = [
                t for t in results
                if plate_key in self._plate_key(t.get('plate_number'))
            ]
        if tx_hash:
            results = [t for t in results if tx_hash.lower() in t['tx_hash'].lower()]
        if tx_type:
            results = [t for t in results if t['type'] == tx_type]
        
        return {'total': len(results), 'transactions': results}


# Khởi tạo global manager
timeline_manager = BlockchainTimeline()
