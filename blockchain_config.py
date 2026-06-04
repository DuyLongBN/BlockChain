"""
Blockchain Configuration
Cấu hình kết nối Ethereum blockchain (Sepolia Testnet)
"""
import os
import json
from pathlib import Path

# Load environment variables from .env file
try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

# ============ SEPOLIA TESTNET CONFIG ============

NETWORK_NAME = "Sepolia"
NETWORK_CHAIN_ID = 11155111

# RPC URL - Sepolia public RPC ổn định hơn
SEPOLIA_RPC_URL = os.environ.get(
    'SEPOLIA_RPC_URL',
    'https://ethereum-sepolia-rpc.publicnode.com'
)

def _unique_rpc_urls(urls):
    unique = []
    for url in urls:
        url = (url or '').strip()
        if url and url not in unique:
            unique.append(url)
    return unique

SEPOLIA_RPC_URLS = _unique_rpc_urls([
    SEPOLIA_RPC_URL,
    os.environ.get('SEPOLIA_RPC_FALLBACK_URL', ''),
    'https://ethereum-sepolia-rpc.publicnode.com',
    'https://sepolia.drpc.org',
    'https://rpc.sepolia.org',
])

# Chain ID
CHAIN_ID = int(os.environ.get('CHAIN_ID', '11155111'))

# Private Key - đặt trong file .env
PRIVATE_KEY = os.environ.get('PRIVATE_KEY', '')

# Default account address
DEFAULT_ACCOUNT = os.environ.get('DEFAULT_ACCOUNT', '')

# MetaMask wallet that is allowed to open the Admin UI. Keep this equal to the
# admin address stored in the deployed smart contract.
ADMIN_ADDRESS = os.environ.get('ADMIN_ADDRESS', '')

# ============ CONTRACT CONFIG ============

CONTRACTS_DIR = os.path.join(os.path.dirname(__file__), 'contracts')
CONTRACT_SOL_PATH = os.path.join(CONTRACTS_DIR, 'LicensePlateRegistry.sol')
CONTRACT_ABI_PATH = os.path.join(CONTRACTS_DIR, 'LicensePlateRegistry_abi.json')
CONTRACT_BYTECODE_PATH = os.path.join(CONTRACTS_DIR, 'LicensePlateRegistry_bytecode.json')
CONTRACT_ADDRESS_PATH = os.path.join(CONTRACTS_DIR, 'contract_address.json')

SOLC_VERSION = '0.8.19'

# ============ HELPER FUNCTIONS ============

def get_contract_address():
    """Load deployed contract address from file"""
    if os.path.exists(CONTRACT_ADDRESS_PATH):
        with open(CONTRACT_ADDRESS_PATH, 'r') as f:
            data = json.load(f)
            return data.get('address', '')
    return ''

def save_contract_address(address):
    """Save deployed contract address to file"""
    os.makedirs(os.path.dirname(CONTRACT_ADDRESS_PATH), exist_ok=True)
    with open(CONTRACT_ADDRESS_PATH, 'w') as f:
        json.dump({
            'address': address,
            'network': NETWORK_NAME,
            'rpc_url': SEPOLIA_RPC_URL,
            'chain_id': CHAIN_ID,
            'explorer': f'https://sepolia.etherscan.io/address/{address}'
        }, f, indent=2)

def get_contract_abi():
    """Load compiled ABI from file"""
    if os.path.exists(CONTRACT_ABI_PATH):
        with open(CONTRACT_ABI_PATH, 'r') as f:
            return json.load(f)
    return None

def get_contract_bytecode():
    """Load compiled bytecode from file"""
    if os.path.exists(CONTRACT_BYTECODE_PATH):
        with open(CONTRACT_BYTECODE_PATH, 'r') as f:
            data = json.load(f)
            return data.get('bytecode', '')
    return ''

CONTRACT_ADDRESS = get_contract_address()

def validate_private_key():
    """Validate that PRIVATE_KEY is set and valid format"""
    if not PRIVATE_KEY:
        print("\n" + "=" * 60)
        print("ERROR: PRIVATE_KEY not set!")
        print("=" * 60)
        print("\nAdd to .env file:")
        print("  PRIVATE_KEY=0x...")
        print("=" * 60 + "\n")
        return False

    if not PRIVATE_KEY.startswith('0x') or len(PRIVATE_KEY) != 66:
        print("\nERROR: Invalid PRIVATE_KEY format!")
        print("  Expected: 0x + 64 hex characters\n")
        return False

    return True
