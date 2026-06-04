import json
import shutil
import argparse
from datetime import datetime
from pathlib import Path

import requests
from web3 import Web3

from blockchain_config import (
    CHAIN_ID,
    CONTRACT_ADDRESS_PATH,
    PRIVATE_KEY,
    SEPOLIA_RPC_URLS,
    get_contract_abi,
    get_contract_bytecode,
    save_contract_address,
    validate_private_key,
)
from compile_contract import compile_contract


def connect_web3():
    last_error = None
    for rpc_url in SEPOLIA_RPC_URLS:
        try:
            session = requests.Session()
            session.trust_env = False
            provider = Web3.HTTPProvider(
                rpc_url,
                request_kwargs={"timeout": 20},
                session=session,
            )
            w3 = Web3(provider)
            if w3.is_connected():
                return w3, rpc_url
            last_error = f"Cannot connect to {rpc_url}"
        except Exception as exc:
            last_error = f"{rpc_url}: {exc}"
    raise RuntimeError(last_error or "Cannot connect to Sepolia RPC")


def backup_contract_address():
    path = Path(CONTRACT_ADDRESS_PATH)
    if not path.exists():
        return None
    backup = path.with_name(
        f"contract_address.backup_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
    )
    shutil.copy2(path, backup)
    return str(backup)


def load_contract_address():
    path = Path(CONTRACT_ADDRESS_PATH)
    if not path.exists():
        return ""
    return json.loads(path.read_text(encoding="utf-8")).get("address", "")


def get_dynamic_gas_price(w3):
    """Use the current Sepolia gas price instead of a stale hard-coded value."""
    return int(w3.eth.gas_price)


def estimate_migration_gas(deploy_gas, old_plates):
    gas = deploy_gas
    for plate in old_plates:
        gas += 500_000
        gas += len(plate.get("history", [])) * 300_000
        gas += len(plate.get("violations", [])) * 400_000
        gas += len([v for v in plate.get("violations", []) if v.get("is_paid")]) * 250_000
        if not plate.get("is_active", True):
            gas += 300_000
    return gas


def require_sufficient_balance(w3, account, gas_units, gas_price, label):
    balance = w3.eth.get_balance(account.address)
    required = gas_units * gas_price
    if balance <= required:
        raise RuntimeError(
            f"Insufficient SepoliaETH for {label}. "
            f"Need about {w3.from_wei(required, 'ether')} SepoliaETH, "
            f"have {w3.from_wei(balance, 'ether')} SepoliaETH. "
            "Top up the deployer wallet and rerun deploy_contract.py."
        )


def send_transaction(w3, account, tx_function, gas, gas_price):
    tx = tx_function.build_transaction({
        "chainId": CHAIN_ID,
        "from": account.address,
        "nonce": w3.eth.get_transaction_count(account.address),
        "gas": gas,
        "gasPrice": gas_price,
    })
    signed_tx = w3.eth.account.sign_transaction(tx, PRIVATE_KEY)
    tx_hash = w3.eth.send_raw_transaction(signed_tx.raw_transaction)
    receipt = w3.eth.wait_for_transaction_receipt(tx_hash, timeout=300)
    return tx_hash.hex(), receipt


def collect_old_plates(w3, abi, old_address):
    if not old_address:
        return []
    contract = w3.eth.contract(address=Web3.to_checksum_address(old_address), abi=abi)
    total = contract.functions.getTotalPlates().call()
    plates = {}
    for index in range(total):
        plate_number = contract.functions.getPlateAtIndex(index).call()
        info = contract.functions.getPlateInfo(plate_number).call()
        if not info[0]:
            continue
        history = []
        try:
            previous_owners, new_owners, timestamps = contract.functions.getTransferHistory(info[0]).call()
            for index in range(len(previous_owners)):
                history.append({
                    "previous_owner": previous_owners[index],
                    "new_owner": new_owners[index],
                    "timestamp": int(timestamps[index]),
                })
        except Exception:
            history = []

        violations = []
        try:
            descriptions, fine_amounts, timestamps, payment_statuses = contract.functions.getViolations(info[0]).call()
            for index in range(len(descriptions)):
                violations.append({
                    "description": descriptions[index],
                    "fine_amount": int(fine_amounts[index]),
                    "timestamp": int(timestamps[index]),
                    "is_paid": bool(payment_statuses[index]),
                })
        except Exception:
            violations = []

        plates[info[0]] = {
            "plate_number": info[0],
            "owner_name": info[1],
            "vehicle_type": info[2],
            "color": info[3],
            "province": info[4],
            "is_active": bool(info[7]),
            "history": history,
            "violations": violations,
        }
    return list(plates.values())


def deploy_contract(migrate=True):
    if not validate_private_key():
        raise RuntimeError("PRIVATE_KEY is missing or invalid")

    old_address = load_contract_address()
    compile_result = compile_contract()
    abi = get_contract_abi()
    bytecode = get_contract_bytecode()
    if not abi or not bytecode:
        raise RuntimeError("Contract ABI/bytecode not found after compile")

    w3, rpc_url = connect_web3()
    account = w3.eth.account.from_key(PRIVATE_KEY)
    balance = w3.eth.get_balance(account.address)
    if balance <= 0:
        raise RuntimeError(f"Account {account.address} has no SepoliaETH")

    old_plates = collect_old_plates(w3, abi, old_address) if migrate and old_address else []

    contract_factory = w3.eth.contract(abi=abi, bytecode=bytecode)
    deploy_gas_estimate = contract_factory.constructor().estimate_gas({"from": account.address})
    deploy_gas = max(4_500_000, int(deploy_gas_estimate * 1.25))
    gas_price = get_dynamic_gas_price(w3)
    estimated_total_gas = estimate_migration_gas(deploy_gas, old_plates if migrate else [])
    require_sufficient_balance(
        w3,
        account,
        estimated_total_gas,
        gas_price,
        "deployment and migration" if migrate else "deployment"
    )

    deploy_tx_hash, receipt = send_transaction(
        w3,
        account,
        contract_factory.constructor(),
        gas=deploy_gas,
        gas_price=gas_price
    )
    if receipt.status != 1:
        raise RuntimeError(f"Deploy transaction failed: {deploy_tx_hash}")

    new_address = receipt.contractAddress
    backup_path = backup_contract_address()
    save_contract_address(new_address)

    new_contract = w3.eth.contract(address=Web3.to_checksum_address(new_address), abi=abi)
    migrated = []
    skipped = []
    if migrate:
        for plate in old_plates:
            try:
                initial_owner = plate["owner_name"]
                if plate.get("history"):
                    initial_owner = plate["history"][0].get("previous_owner") or initial_owner

                migration_tx_hash, migration_receipt = send_transaction(
                    w3,
                    account,
                    new_contract.functions.registerPlate(
                        plate["plate_number"],
                        initial_owner,
                        plate["vehicle_type"],
                        plate["color"],
                        plate["province"],
                    ),
                    gas=500_000,
                    gas_price=gas_price,
                )
                if migration_receipt.status != 1:
                    skipped.append({"plate_number": plate["plate_number"], "reason": "register migration tx failed"})
                    continue

                transfer_count = 0
                for transfer in plate.get("history", []):
                    transfer_tx_hash, transfer_receipt = send_transaction(
                        w3,
                        account,
                        new_contract.functions.transferOwnership(
                            plate["plate_number"],
                            transfer["new_owner"],
                        ),
                        gas=300_000,
                        gas_price=gas_price,
                    )
                    if transfer_receipt.status == 1:
                        transfer_count += 1

                violation_count = 0
                paid_count = 0
                for violation in plate.get("violations", []):
                    violation_tx_hash, violation_receipt = send_transaction(
                        w3,
                        account,
                        new_contract.functions.addViolation(
                            plate["plate_number"],
                            violation["description"],
                            violation["fine_amount"],
                        ),
                        gas=400_000,
                        gas_price=gas_price,
                    )
                    if violation_receipt.status == 1:
                        violation_count += 1
                        if violation.get("is_paid") and hasattr(new_contract.functions, "markViolationPaid"):
                            paid_tx_hash, paid_receipt = send_transaction(
                                w3,
                                account,
                                new_contract.functions.markViolationPaid(
                                    plate["plate_number"],
                                    violation_count - 1,
                                ),
                                gas=250_000,
                                gas_price=gas_price,
                            )
                            if paid_receipt.status == 1:
                                paid_count += 1

                deactivated = False
                if not plate["is_active"]:
                    deactivate_tx_hash, deactivate_receipt = send_transaction(
                        w3,
                        account,
                        new_contract.functions.deactivatePlate(plate["plate_number"]),
                        gas=300_000,
                        gas_price=gas_price,
                    )
                    deactivated = deactivate_receipt.status == 1

                migrated.append({
                    "plate_number": plate["plate_number"],
                    "tx_hash": migration_tx_hash,
                    "block_number": migration_receipt.blockNumber,
                    "transfers": transfer_count,
                    "violations": violation_count,
                    "paid_violations": paid_count,
                    "inactive_restored": deactivated,
                })
            except Exception as exc:
                skipped.append({"plate_number": plate["plate_number"], "reason": str(exc)})

    return {
        "compiled": compile_result,
        "rpc_url": rpc_url,
        "deployer": account.address,
        "old_address": old_address,
        "new_address": new_address,
        "backup_path": backup_path,
        "deploy_tx": deploy_tx_hash,
        "deploy_block": receipt.blockNumber,
        "gas_price_gwei": str(w3.from_wei(gas_price, "gwei")),
        "estimated_total_gas": estimated_total_gas,
        "migrated_count": len(migrated),
        "migrated": migrated,
        "skipped": skipped,
        "explorer": f"https://sepolia.etherscan.io/address/{new_address}",
    }


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Deploy LicensePlateRegistry to Sepolia")
    parser.add_argument("--no-migrate", action="store_true", help="Deploy a fresh contract without migrating old data")
    args = parser.parse_args()
    result = deploy_contract(migrate=not args.no_migrate)
    print(json.dumps(result, ensure_ascii=False, indent=2))
