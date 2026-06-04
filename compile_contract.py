import json
from pathlib import Path

import solcx

from blockchain_config import (
    CONTRACT_ABI_PATH,
    CONTRACT_BYTECODE_PATH,
    CONTRACT_SOL_PATH,
    SOLC_VERSION,
)


def compile_contract():
    source_path = Path(CONTRACT_SOL_PATH)
    source = source_path.read_text(encoding="utf-8")

    if SOLC_VERSION not in [str(version) for version in solcx.get_installed_solc_versions()]:
        solcx.install_solc(SOLC_VERSION)

    compiled = solcx.compile_standard(
        {
            "language": "Solidity",
            "sources": {
                source_path.name: {
                    "content": source,
                }
            },
            "settings": {
                "outputSelection": {
                    "*": {
                        "*": ["abi", "evm.bytecode.object"],
                    }
                }
            },
        },
        solc_version=SOLC_VERSION,
    )

    contract = compiled["contracts"][source_path.name]["LicensePlateRegistry"]
    abi = contract["abi"]
    bytecode = contract["evm"]["bytecode"]["object"]

    Path(CONTRACT_ABI_PATH).write_text(
        json.dumps(abi, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    Path(CONTRACT_BYTECODE_PATH).write_text(
        json.dumps({"bytecode": bytecode}, indent=2),
        encoding="utf-8",
    )

    return {
        "abi_path": CONTRACT_ABI_PATH,
        "bytecode_path": CONTRACT_BYTECODE_PATH,
        "abi_entries": len(abi),
        "bytecode_bytes": len(bytecode) // 2,
    }


if __name__ == "__main__":
    result = compile_contract()
    print(json.dumps(result, indent=2))
