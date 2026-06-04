"""
Blockchain Service Layer
Lớp dịch vụ tương tác với Smart Contract LicensePlateRegistry
"""
import json
import time
import re
from datetime import datetime
import requests
from web3 import Web3

from blockchain_config import (
    SEPOLIA_RPC_URL, SEPOLIA_RPC_URLS, CHAIN_ID, PRIVATE_KEY,
    get_contract_abi, get_contract_address
)


def normalize_plate_number(plate_number):
    """Return one canonical plate key before reading/writing the contract."""
    text = (plate_number or '').upper().strip()
    if not text or text == 'UNKNOWN':
        return text

    compact = re.sub(r'[^A-Z0-9]', '', text)
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

    top = f"{top[:2]}-{top[2:]}" if len(top) > 3 else top
    if len(bottom) == 5:
        bottom = f"{bottom[:3]}.{bottom[3:]}"
    return f"{top}-{bottom}" if bottom else top


class BlockchainService:
    def __init__(self):
        self.w3 = None
        self.contract = None
        self.account = None
        self.connected = False
        self.rpc_url = SEPOLIA_RPC_URL
        self._connect()

    def _connect(self):
        last_error = None
        for rpc_url in SEPOLIA_RPC_URLS:
            try:
                session = requests.Session()
                # The desktop sandbox may set HTTP(S)_PROXY to a dead localhost
                # proxy. Web3 would inherit that and mark Sepolia offline even
                # when direct RPC access works.
                session.trust_env = False
                provider = Web3.HTTPProvider(
                    rpc_url,
                    request_kwargs={'timeout': 10},
                    session=session
                )
                candidate_w3 = Web3(provider)
                if candidate_w3.is_connected():
                    self.w3 = candidate_w3
                    self.rpc_url = rpc_url
                    break
                last_error = f"Cannot connect to Sepolia at {rpc_url}"
            except Exception as e:
                last_error = f"{rpc_url}: {e}"
        else:
            print(f"WARNING: {last_error or 'Cannot connect to Sepolia RPC'}")
            self.connected = False
            return

        try:

            abi = get_contract_abi()
            contract_address = get_contract_address()

            if not abi or not contract_address:
                print("WARNING: Contract not deployed yet. Run deploy_contract.py first.")
                self.connected = False
                return

            if not PRIVATE_KEY:
                print("WARNING: PRIVATE_KEY not found in .env")
                self.connected = False
                return

            # Load ví ký giao dịch từ PRIVATE_KEY
            account = self.w3.eth.account.from_key(PRIVATE_KEY)
            self.account = account.address

            # Load contract
            self.contract = self.w3.eth.contract(
                address=Web3.to_checksum_address(contract_address),
                abi=abi
            )

            self.connected = True
            print(f"Connected to Sepolia: {contract_address}")
            print(f"Using RPC: {self.rpc_url}")
            print(f"Using account: {self.account}")

        except Exception as e:
            print(f"WARNING: Connection error: {e}")
            self.connected = False

    def get_blockchain_status(self):
        if not self.connected or not self.w3:
            self._connect()
        if not self.connected or not self.w3:
            return {
                'connected': False,
                'network': 'Sepolia',
                'rpc': self.rpc_url,
                'rpc_candidates': SEPOLIA_RPC_URLS,
                'error': 'Not connected to blockchain'
            }

        try:
            block = self.w3.eth.block_number
            return {
                'connected': True,
                'network': 'Sepolia',
                'rpc': self.rpc_url,
                'chain_id': CHAIN_ID,
                'block_number': block,
                'contract_address': get_contract_address(),
                'account': self.account
            }
        except Exception as e:
            return {
                'connected': False,
                'network': 'Sepolia',
                'rpc': self.rpc_url,
                'error': str(e)
            }

    def _send_transaction(self, tx_function, gas=500000):
        nonce = self.w3.eth.get_transaction_count(self.account)

        tx = tx_function.build_transaction({
            'chainId': CHAIN_ID,
            'from': self.account,
            'nonce': nonce,
            'gas': gas,
            'gasPrice': self.w3.to_wei('2', 'gwei')
        })

        signed_tx = self.w3.eth.account.sign_transaction(tx, PRIVATE_KEY)
        tx_hash = self.w3.eth.send_raw_transaction(signed_tx.raw_transaction)
        receipt = self.w3.eth.wait_for_transaction_receipt(tx_hash, timeout=300)

        return tx_hash, receipt

    def _plate_lookup_candidates(self, plate_number):
        candidates = []
        canonical = normalize_plate_number(plate_number)
        raw = (plate_number or '').strip()
        upper_raw = raw.upper()
        compact = re.sub(r'[^A-Z0-9]', '', upper_raw)

        def add(value):
            if value and value not in candidates:
                candidates.append(value)

        for value in (canonical, raw, upper_raw, compact):
            add(value)

        canonical_compact = re.sub(r'[^A-Z0-9]', '', canonical)
        if len(canonical_compact) >= 7:
            bottom_len = 5 if len(canonical_compact) >= 8 else 4
            top = canonical_compact[:-bottom_len]
            bottom = canonical_compact[-bottom_len:]
            bottom_variants = [bottom]
            if len(bottom) == 5:
                bottom_variants.insert(0, f"{bottom[:3]}.{bottom[3:]}")

            top_variants = [top]
            if len(top) > 3:
                top_variants.insert(0, f"{top[:2]}-{top[2:]}")

            for top_variant in top_variants:
                for bottom_variant in bottom_variants:
                    add(f"{top_variant}-{bottom_variant}")
        return candidates

    def _find_plate_key(self, plate_number, require_active=False):
        for candidate in self._plate_lookup_candidates(plate_number):
            try:
                info = self.contract.functions.getPlateInfo(candidate).call()
                exists = bool(info[0]) or info[5] > 0
                active = bool(info[7])
                if exists and (active or not require_active):
                    return candidate, info
            except Exception:
                continue
        return normalize_plate_number(plate_number), None

    def _contract_has_function(self, signature):
        if not self.connected or not self.w3 or not self.contract:
            return False
        try:
            selector = self.w3.keccak(text=signature)[:4].hex().lower().replace('0x', '')
            code = self.w3.eth.get_code(self.contract.address).hex().lower().replace('0x', '')
            return selector in code
        except Exception:
            return False

    def register_plate(self, plate_number, owner_name, vehicle_type='', color='', province=''):
        if not self.connected:
            return {'success': False, 'error': 'Blockchain not connected'}

        try:
            canonical_plate = normalize_plate_number(plate_number)
            existing_key, existing_info = self._find_plate_key(plate_number)
            if existing_info:
                return {'success': False, 'error': f'Biển số {existing_key} đã được đăng ký'}

            tx_function = self.contract.functions.registerPlate(
                canonical_plate, owner_name, vehicle_type, color, province
            )

            tx_hash, receipt = self._send_transaction(tx_function, gas=500000)

            return {
                'success': True,
                'plate_number': canonical_plate,
                'input_plate_number': plate_number,
                'owner': owner_name,
                'tx_hash': tx_hash.hex(),
                'etherscan': f'https://sepolia.etherscan.io/tx/{tx_hash.hex()}',
                'block_number': receipt.blockNumber,
                'gas_used': receipt.gasUsed,
                'timestamp': datetime.now().isoformat()
            }

        except Exception as e:
            return {'success': False, 'error': str(e)}

    def verify_plate(self, plate_number):
        if not self.connected:
            return {
                'verified': False,
                'is_registered': False,
                'error': 'Blockchain not connected'
            }

        try:
            lookup_key, info = self._find_plate_key(plate_number, require_active=False)
            is_registered = bool(info)

            result = {
                'verified': True,
                'plate_number': normalize_plate_number(info[0] or lookup_key) if info else lookup_key,
                'contract_plate_number': info[0] if info else '',
                'input_plate_number': plate_number,
                'is_registered': is_registered,
                'is_active': bool(info[7]) if info else False,
                'timestamp': datetime.now().isoformat()
            }

            if is_registered:
                result.update({
                    'owner_name': info[1],
                    'vehicle_type': info[2],
                    'color': info[3],
                    'province': info[4],
                    'registered_at': datetime.fromtimestamp(info[5]).isoformat() if info[5] > 0 else '',
                    'last_updated': datetime.fromtimestamp(info[6]).isoformat() if info[6] > 0 else '',
                    'is_active': info[7]
                })

            return result

        except Exception as e:
            return {
                'verified': False,
                'is_registered': False,
                'plate_number': plate_number,
                'error': str(e)
            }

    def get_plate_info(self, plate_number):
        if not self.connected:
            return {'success': False, 'error': 'Blockchain not connected'}

        try:
            lookup_key, info = self._find_plate_key(plate_number)
            if not info:
                info = ('', '', '', '', '', 0, 0, False)

            return {
                'success': True,
                'found': bool(info[0]) or info[5] > 0,
                'plate_number': info[0] or lookup_key,
                'input_plate_number': plate_number,
                'owner_name': info[1],
                'vehicle_type': info[2],
                'color': info[3],
                'province': info[4],
                'registered_at': datetime.fromtimestamp(info[5]).isoformat() if info[5] > 0 else '',
                'last_updated': datetime.fromtimestamp(info[6]).isoformat() if info[6] > 0 else '',
                'is_active': info[7]
            }

        except Exception as e:
            return {'success': False, 'error': str(e)}

    def reactivate_plate(self, plate_number, owner_name='', vehicle_type='', color='', province=''):
        if not self.connected:
            return {'success': False, 'error': 'Blockchain not connected'}

        try:
            plate_number, info = self._find_plate_key(plate_number)
            if not info:
                info = ('', '', '', '', '', 0, 0, False)
            if not info[0] and info[5] == 0:
                return {'success': False, 'error': f'Biển số {plate_number} chưa từng được đăng ký'}
            if info[7]:
                return {'success': False, 'error': f'Biển số {plate_number} đang Active'}

            owner_name = (owner_name or info[1]).strip()
            vehicle_type = (vehicle_type or info[2]).strip()
            color = (color or info[3]).strip()
            province = (province or info[4]).strip()
            if not owner_name:
                return {'success': False, 'error': 'Thiếu tên chủ xe để kích hoạt lại'}

            if not hasattr(self.contract.functions, 'reactivatePlate'):
                return {
                    'success': False,
                    'error': 'Smart contract hiện tại chưa hỗ trợ reactivatePlate(). Cần deploy contract mới trước khi mở khóa phương tiện.'
                }

            tx_function = self.contract.functions.reactivatePlate(plate_number)
            tx_hash, receipt = self._send_transaction(tx_function, gas=300000)
            result = {
                'success': True,
                'plate_number': plate_number,
                'owner': owner_name,
                'tx_hash': tx_hash.hex(),
                'etherscan': f'https://sepolia.etherscan.io/tx/{tx_hash.hex()}',
                'block_number': receipt.blockNumber,
                'gas_used': receipt.gasUsed,
                'timestamp': datetime.now().isoformat()
            }
            if result.get('success'):
                result['reactivated'] = True
                result['message'] = f'Đã kích hoạt lại biển số {plate_number}'
            return result

        except Exception as e:
            return {'success': False, 'error': str(e)}

    def transfer_ownership(self, plate_number, new_owner):
        if not self.connected:
            return {'success': False, 'error': 'Blockchain not connected'}

        try:
            plate_number, info = self._find_plate_key(plate_number, require_active=True)
            if not info:
                info = ('', '', '', '', '', 0, 0, False)
            if not info[7]:
                return {'success': False, 'error': f'Biển số {plate_number} không tồn tại hoặc đã bị vô hiệu hóa'}

            previous_owner = info[1]

            tx_function = self.contract.functions.transferOwnership(
                plate_number, new_owner
            )

            tx_hash, receipt = self._send_transaction(tx_function, gas=300000)

            return {
                'success': True,
                'plate_number': plate_number,
                'previous_owner': previous_owner,
                'new_owner': new_owner,
                'tx_hash': tx_hash.hex(),
                'etherscan': f'https://sepolia.etherscan.io/tx/{tx_hash.hex()}',
                'block_number': receipt.blockNumber,
                'gas_used': receipt.gasUsed,
                'timestamp': datetime.now().isoformat()
            }

        except Exception as e:
            return {'success': False, 'error': str(e)}

    def update_vehicle(self, plate_number, vehicle_type='', color='', province=''):
        if not self.connected:
            return {'success': False, 'error': 'Blockchain not connected'}

        try:
            plate_number, info = self._find_plate_key(plate_number)
            if not info:
                return {'success': False, 'error': f'Biển số {plate_number} chưa được đăng ký'}

            vehicle_type = (vehicle_type or info[2]).strip()
            color = (color or info[3]).strip()
            province = (province or info[4]).strip()

            if vehicle_type == info[2] and color == info[3] and province == info[4]:
                return {'success': False, 'error': 'Không có thông tin phương tiện nào thay đổi'}

            if not self._contract_has_function('updateVehicle(string,string,string,string)'):
                return {
                    'success': False,
                    'error': 'Smart contract hiện tại chưa hỗ trợ updateVehicle(). Cần deploy contract mới trước khi cập nhật phương tiện.'
                }

            tx_function = self.contract.functions.updateVehicle(
                plate_number, vehicle_type, color, province
            )
            tx_hash, receipt = self._send_transaction(tx_function, gas=350000)

            return {
                'success': True,
                'plate_number': plate_number,
                'vehicle_type': vehicle_type,
                'color': color,
                'province': province,
                'tx_hash': tx_hash.hex(),
                'etherscan': f'https://sepolia.etherscan.io/tx/{tx_hash.hex()}',
                'block_number': receipt.blockNumber,
                'gas_used': receipt.gasUsed,
                'timestamp': datetime.now().isoformat()
            }

        except Exception as e:
            return {'success': False, 'error': str(e)}

    def deactivate_plate(self, plate_number):
        if not self.connected:
            return {'success': False, 'error': 'Blockchain not connected'}

        try:
            plate_number, info = self._find_plate_key(plate_number, require_active=True)
            if not info:
                return {'success': False, 'error': f'Biển số {plate_number} không tồn tại hoặc đã inactive'}
            tx_function = self.contract.functions.deactivatePlate(plate_number)
            tx_hash, receipt = self._send_transaction(tx_function, gas=300000)

            return {
                'success': True,
                'plate_number': plate_number,
                'tx_hash': tx_hash.hex(),
                'etherscan': f'https://sepolia.etherscan.io/tx/{tx_hash.hex()}',
                'block_number': receipt.blockNumber,
                'gas_used': receipt.gasUsed,
                'timestamp': datetime.now().isoformat()
            }

        except Exception as e:
            return {'success': False, 'error': str(e)}

    def add_violation(self, plate_number, description, fine_amount):
        if not self.connected:
            return {'success': False, 'error': 'Blockchain not connected'}

        try:
            plate_number, info = self._find_plate_key(plate_number)
            if not info:
                return {'success': False, 'error': f'Biển số {plate_number} chưa được đăng ký'}
            try:
                fine_amount = int(fine_amount)
            except (TypeError, ValueError):
                return {'success': False, 'error': 'Số tiền phạt không hợp lệ'}
            if fine_amount < 0:
                return {'success': False, 'error': 'Số tiền phạt không được âm'}
            tx_function = self.contract.functions.addViolation(
                plate_number, description, fine_amount
            )

            tx_hash, receipt = self._send_transaction(tx_function, gas=400000)

            return {
                'success': True,
                'plate_number': plate_number,
                'tx_hash': tx_hash.hex(),
                'etherscan': f'https://sepolia.etherscan.io/tx/{tx_hash.hex()}',
                'block_number': receipt.blockNumber,
                'gas_used': receipt.gasUsed,
                'timestamp': datetime.now().isoformat()
            }

        except Exception as e:
            return {'success': False, 'error': str(e)}

    def mark_violation_paid(self, plate_number, violation_index):
        if not self.connected:
            return {'success': False, 'error': 'Blockchain not connected'}

        try:
            plate_number, info = self._find_plate_key(plate_number)
            if not info:
                return {'success': False, 'error': f'Biển số {plate_number} chưa được đăng ký'}

            try:
                violation_index = int(violation_index)
            except (TypeError, ValueError):
                return {'success': False, 'error': 'Số thứ tự vi phạm không hợp lệ'}
            if violation_index < 0:
                return {'success': False, 'error': 'Số thứ tự vi phạm không được âm'}

            if not self._contract_has_function('markViolationPaid(string,uint256)'):
                return {
                    'success': False,
                    'error': 'Smart contract hiện tại chưa hỗ trợ markViolationPaid(). Cần deploy contract mới trước khi xử lý nộp phạt.'
                }

            tx_function = self.contract.functions.markViolationPaid(plate_number, violation_index)
            tx_hash, receipt = self._send_transaction(tx_function, gas=250000)

            return {
                'success': True,
                'plate_number': plate_number,
                'violation_index': violation_index,
                'tx_hash': tx_hash.hex(),
                'etherscan': f'https://sepolia.etherscan.io/tx/{tx_hash.hex()}',
                'block_number': receipt.blockNumber,
                'gas_used': receipt.gasUsed,
                'timestamp': datetime.now().isoformat()
            }

        except Exception as e:
            return {'success': False, 'error': str(e)}

    def get_violations(self, plate_number):
        if not self.connected:
            return []

        try:
            plate_number, _info = self._find_plate_key(plate_number)
            result = self.contract.functions.getViolations(plate_number).call()
            descriptions, fine_amounts, timestamps, payment_statuses = result

            violations_list = []
            for i in range(len(descriptions)):
                violations_list.append({
                    'index': i,
                    'description': descriptions[i],
                    'fine_amount': fine_amounts[i],
                    'timestamp': datetime.fromtimestamp(timestamps[i]).isoformat() if timestamps[i] > 0 else '',
                    'is_paid': payment_statuses[i]
                })

            return violations_list

        except Exception as e:
            print(f"Error getting violations: {e}")
            return []

    def get_all_plates(self):
        if not self.connected:
            return []

        try:
            total = self.contract.functions.getTotalPlates().call()
            plates_by_number = {}

            for i in range(total):
                plate_number = self.contract.functions.getPlateAtIndex(i).call()
                info = self.contract.functions.getPlateInfo(plate_number).call()

                original_plate_number = info[0] or plate_number
                canonical_plate_number = normalize_plate_number(original_plate_number)
                record = {
                    'plate_number': canonical_plate_number,
                    'contract_plate_number': original_plate_number,
                    'owner_name': info[1],
                    'vehicle_type': info[2],
                    'color': info[3],
                    'province': info[4],
                    'registered_at': datetime.fromtimestamp(info[5]).isoformat() if info[5] > 0 else '',
                    'last_updated': datetime.fromtimestamp(info[6]).isoformat() if info[6] > 0 else '',
                    'is_active': info[7]
                }
                dedupe_key = re.sub(r'[^A-Z0-9]', '', canonical_plate_number.upper())
                if dedupe_key in plates_by_number:
                    del plates_by_number[dedupe_key]
                plates_by_number[dedupe_key] = record

            return list(plates_by_number.values())

        except Exception as e:
            print(f"Error getting plates: {e}")
            return []

    def get_plate_history(self, plate_number):
        if not self.connected:
            return []

        try:
            plate_number, _info = self._find_plate_key(plate_number)
            result = self.contract.functions.getTransferHistory(plate_number).call()
            previous_owners, new_owners, timestamps = result

            history = []
            for i in range(len(previous_owners)):
                history.append({
                    'previous_owner': previous_owners[i],
                    'new_owner': new_owners[i],
                    'transferred_at': datetime.fromtimestamp(timestamps[i]).isoformat() if timestamps[i] > 0 else ''
                })

            return history

        except Exception as e:
            print(f"Error getting history: {e}")
            return []

    def get_statistics(self):
        if not self.connected:
            return {
                'total_registered': 0,
                'total_verifications': 0,
                'total_transfers': 0,
                'total_plates': 0,
                'connected': False
            }

        try:
            stats = self.contract.functions.getStatistics().call()
            plates = self.get_all_plates()
            unique_plate_count = len(plates)
            active_plate_count = sum(1 for plate in plates if plate.get('is_active'))

            return {
                'total_registered': unique_plate_count,
                'total_registered_events': stats[0],
                'total_verifications': stats[1],
                'total_transfers': stats[2],
                'total_violations': stats[3],
                'total_plates': unique_plate_count,
                'contract_total_plates': stats[4],
                'active_plates': active_plate_count,
                'inactive_plates': unique_plate_count - active_plate_count,
                'connected': True
            }

        except Exception as e:
            return {
                'total_registered': 0,
                'total_registered_events': 0,
                'total_verifications': 0,
                'total_transfers': 0,
                'total_violations': 0,
                'total_plates': 0,
                'contract_total_plates': 0,
                'active_plates': 0,
                'inactive_plates': 0,
                'connected': False,
                'error': str(e)
            }

    def get_verification_logs(self, limit=20):
        if not self.connected:
            return []

        try:
            total = self.contract.functions.getVerificationLogCount().call()
            logs = []

            start = max(0, total - limit)
            for i in range(start, total):
                log = self.contract.functions.getVerificationLog(i).call()
                logs.append({
                    'plate_number': log[0],
                    'is_valid': log[1],
                    'verified_at': datetime.fromtimestamp(log[2]).isoformat() if log[2] > 0 else ''
                })

            logs.reverse()
            return logs

        except Exception as e:
            print(f"Error getting verification logs: {e}")
            return []

    def get_admin_address(self):
        """Get admin address from Smart Contract"""
        if not self.connected:
            return None
        try:
            admin_address = self.contract.functions.admin().call()
            return admin_address
        except Exception as e:
            print(f"Error getting admin address: {e}")
            return None

    def is_admin(self, address):
        """Check if an address is the admin of the contract"""
        if not self.connected or not address:
            return False
        try:
            admin_address = self.get_admin_address()
            if admin_address:
                return address.lower() == admin_address.lower()
            return False
        except Exception as e:
            print(f"Error checking admin: {e}")
            return False
