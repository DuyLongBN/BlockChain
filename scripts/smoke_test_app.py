import json
import re
import sys
import time
from pathlib import Path

import requests
from eth_account import Account
from eth_account.messages import encode_defunct

ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from blockchain_config import PRIVATE_KEY


BASE_URL = "http://127.0.0.1:5000"
ADMIN_ADDRESS = Account.from_key(PRIVATE_KEY).address if PRIVATE_KEY else ""
SAMPLE_IMAGE = ROOT_DIR / "uploads/img_1779820921570.jpg"


class SmokeRunner:
    def __init__(self, base_url=BASE_URL):
        self.base_url = base_url.rstrip("/")
        self.session = requests.Session()
        self.session.headers.update({"X-Session-ID": "codex-smoke-test"})
        self.results = []
        self.context = {}

    def add(self, name, ok, detail="", status=None, duration=None):
        self.results.append({
            "name": name,
            "ok": bool(ok),
            "status": status,
            "duration_ms": int(duration * 1000) if duration is not None else None,
            "detail": str(detail)[:500],
        })

    def request_json(self, name, method, path, *, expected=(200,), json_body=None,
                     files=None, timeout=45, validate=None):
        started = time.time()
        try:
            response = self.session.request(
                method,
                self.base_url + path,
                json=json_body,
                files=files,
                timeout=timeout,
            )
            duration = time.time() - started
            try:
                data = response.json()
            except Exception:
                data = {"_text": response.text[:300]}

            ok = response.status_code in expected
            detail = ""
            if ok and validate:
                try:
                    valid = validate(data, response)
                    ok = bool(valid)
                    if valid is not True:
                        detail = valid
                except Exception as exc:
                    ok = False
                    detail = f"validate_error: {exc}"
            if not ok and not detail:
                detail = json.dumps(data, ensure_ascii=False)

            self.add(name, ok, detail, response.status_code, duration)
            return data, response
        except Exception as exc:
            self.add(name, False, str(exc), None, time.time() - started)
            return None, None

    def run(self):
        self.request_json("home", "GET", "/", validate=lambda d, r: "BlockPlate" in r.text)
        self.request_json("health", "GET", "/health",
                          validate=lambda d, r: d.get("status") == "healthy"
                          and "rpc" not in d.get("blockchain", {}))
        self.request_json("test_system_protected", "GET", "/api/test-system", expected=(403,),
                          validate=lambda d, r: d.get("success") is False)

        self.request_json("wallet_connect", "POST", "/api/wallet-connect",
                          json_body={"address": ADMIN_ADDRESS, "network": "Sepolia"},
                          validate=lambda d, r: d.get("success") is True)
        self.request_json("wallet_status", "GET", "/api/wallet-status",
                          validate=lambda d, r: d.get("connected") is True
                          and "..." in d.get("address", ""))
        self.request_json("admin_challenge_denied", "POST", "/api/auth/challenge",
                          json_body={"address": "0x0000000000000000000000000000000000000001"},
                          expected=(403,),
                          validate=lambda d, r: d.get("success") is False
                          and "admin_address" not in d and "contract_address" not in d)
        challenge, _ = self.request_json("admin_challenge", "POST", "/api/auth/challenge",
                                         json_body={"address": ADMIN_ADDRESS},
                                         validate=lambda d, r: d.get("success") is True and d.get("is_admin") is True)
        self.request_json("admin_check_without_signature", "POST", "/api/admin/check",
                          json_body={"address": ADMIN_ADDRESS}, expected=(401,),
                          validate=lambda d, r: d.get("is_admin") is False)

        status, _ = self.request_json("blockchain_status", "GET", "/api/blockchain/status",
                                      validate=lambda d, r: d.get("connected") is True
                                      and "rpc" not in d and "account" not in d
                                      and "contract_address" not in d)
        stats, _ = self.request_json("blockchain_statistics", "GET", "/api/blockchain/statistics",
                                     validate=lambda d, r: d.get("total_registered") == d.get("total_plates"))
        plates, _ = self.request_json("blockchain_plates", "GET", "/api/blockchain/plates",
                                      validate=lambda d, r: isinstance(d, list)
                                      and all("color" not in p and "last_updated" not in p for p in d))

        if isinstance(plates, list) and plates:
            plate = plates[0].get("plate_number")
            self.context["plate"] = plate
            self.request_json("plate_info", "GET", f"/api/blockchain/info/{plate}",
                              validate=lambda d, r: d.get("success") is True
                              and "color" not in d and "last_updated" not in d)
            self.request_json("plate_verify", "GET", f"/api/blockchain/verify/{plate}",
                              validate=lambda d, r: d.get("verified") is True)
            compact_plate = re.sub(r"[^A-Z0-9]", "", str(plate).upper())
            self.request_json("plate_verify_normalized_input", "GET", f"/api/blockchain/verify/{compact_plate}",
                              validate=lambda d, r: d.get("verified") is True
                              and d.get("is_registered") is True)
            self.request_json("plate_info_normalized_input", "GET", f"/api/blockchain/info/{compact_plate}",
                              validate=lambda d, r: d.get("success") is True
                              and d.get("found") is True)
            self.request_json("plate_history", "GET", f"/api/blockchain/history/{plate}",
                              validate=lambda d, r: isinstance(d, list))
            self.request_json("plate_violations", "GET", f"/api/blockchain/violations/{plate}",
                              validate=lambda d, r: isinstance(d, list))

        protected = [
            ("register_protected", "/api/blockchain/register", {"plate_number": "TEST-000.00", "owner_name": "Test"}),
            ("transfer_protected", "/api/blockchain/transfer", {"plate_number": self.context.get("plate", "TEST-000.00"), "new_owner": "Test"}),
            ("deactivate_protected", "/api/blockchain/deactivate", {"plate_number": self.context.get("plate", "TEST-000.00")}),
            ("reactivate_protected", "/api/blockchain/reactivate", {"plate_number": self.context.get("plate", "TEST-000.00")}),
            ("violation_protected", "/api/blockchain/violation", {"plate_number": self.context.get("plate", "TEST-000.00"), "description": "Test", "fine_amount": 1}),
            ("violation_paid_protected", "/api/blockchain/violation/paid", {"plate_number": self.context.get("plate", "TEST-000.00"), "violation_index": 0}),
            ("update_protected", "/api/blockchain/update", {"plate_number": self.context.get("plate", "TEST-000.00"), "color": "Test"}),
        ]
        for name, path, payload in protected:
            self.request_json(name, "POST", path, json_body=payload, expected=(403,),
                              validate=lambda d, r: d.get("success") is False)

        self.request_json("timeline_all", "GET", "/api/timeline/all",
                          validate=lambda d, r: all(
                              "owner_name" not in tx and "details" not in tx
                              for tx in d.get("transactions", [])
                          ))
        self.request_json("stolen_list", "GET", "/api/stolen/list",
                          validate=lambda d, r: all(
                              "description" not in vehicle
                              for vehicle in d.get("vehicles", [])
                          ))

        for name, path in [
            ("timeline_statistics", "/api/timeline/statistics"),
            ("timeline_register", "/api/timeline/all?type=register"),
            ("timeline_reactivate", "/api/timeline/all?type=reactivate"),
            ("timeline_violation", "/api/timeline/all?type=violation"),
            ("stolen_statistics", "/api/stolen/statistics"),
            ("stolen_search", "/api/stolen/search?plate=36"),
            ("stolen_check", "/api/stolen/check/36X1-123.45"),
        ]:
            self.request_json(name, "GET", path)

        self.request_json("stolen_add_protected", "POST", "/api/stolen/add",
                          json_body={"plate_number": "TEST-000.00", "owner_name": "Test"},
                          expected=(403,), validate=lambda d, r: d.get("success") is False)

        qr_payload = {
            "plate_number": "36B-123.45",
            "owner_name": "Quan Test",
            "vehicle_type": "O to",
            "color": "Den",
            "province": "Thanh Hoa",
            "contract_address": (status or {}).get("contract_address", ""),
            "tx_hash": "0x" + "1" * 64,
        }
        self.request_json("qr_generate_protected", "POST", "/api/qr/generate",
                          json_body=qr_payload, expected=(403,),
                          validate=lambda d, r: d.get("success") is False)

        if challenge and PRIVATE_KEY:
            signature = Account.sign_message(
                encode_defunct(text=challenge["message"]),
                private_key=PRIVATE_KEY
            ).signature.hex()
            admin, _ = self.request_json("admin_login_signed", "POST", "/api/admin/check",
                                         json_body={
                                             "address": ADMIN_ADDRESS,
                                             "nonce": challenge["nonce"],
                                             "signature": signature,
                                         },
                                         validate=lambda d, r: d.get("is_admin") is True
                                         and bool(d.get("admin_token")))
            if admin and admin.get("admin_token"):
                self.session.headers.update({"X-Admin-Token": admin["admin_token"]})
                status, _ = self.request_json("blockchain_status_admin", "GET", "/api/blockchain/status",
                                              validate=lambda d, r: d.get("connected") is True
                                              and bool(d.get("contract_address")))
                self.request_json("test_system_admin", "GET", "/api/test-system",
                                  validate=lambda d, r: d.get("status") == "ok")

        qr, _ = self.request_json("qr_generate_admin", "POST", "/api/qr/generate",
                                  json_body=qr_payload,
                                  validate=lambda d, r: d.get("success") is True and d.get("qr_image_url"))
        if qr and qr.get("qr_data"):
            self.request_json("qr_verify", "POST", "/api/qr/verify",
                              json_body={"qr_data": qr["qr_data"], "plate_number": qr_payload["plate_number"]},
                              validate=lambda d, r: d.get("verified") is True)
            if qr.get("qr_image_url"):
                self.request_json("qr_file", "GET", qr["qr_image_url"],
                                  validate=lambda d, r: r.headers.get("content-type", "").startswith("image/"))
                qr_image_path = Path(qr["qr_image_url"].lstrip("/"))
                if qr_image_path.exists():
                    with qr_image_path.open("rb") as qr_file:
                        files = {"image": (qr_image_path.name, qr_file, "image/png")}
                        self.request_json("qr_scan", "POST", "/api/qr/scan", files=files,
                                          validate=lambda d, r: d.get("verified") is True)

        self.request_json("admin_logout", "POST", "/api/admin/logout", json_body={},
                          validate=lambda d, r: d.get("success") is True and d.get("is_admin") is False)
        self.request_json("admin_token_revoked", "GET", "/api/test-system", expected=(403,),
                          validate=lambda d, r: d.get("success") is False)
        self.session.headers.pop("X-Admin-Token", None)

        if SAMPLE_IMAGE.exists():
            for name, path in [
                ("ocr_process_image", "/api/process-image"),
                ("ocr_recognize_verify", "/api/recognize-and-verify"),
                ("ocr_image_authenticate", "/api/image-authenticate"),
            ]:
                with SAMPLE_IMAGE.open("rb") as image_file:
                    files = {"image": (SAMPLE_IMAGE.name, image_file, "image/jpeg")}
                    self.request_json(name, "POST", path, files=files, timeout=180,
                                      validate=lambda d, r: (d.get("status") == "success" or d.get("success") is True)
                                      and isinstance(d.get("detection_count"), int))

        self.request_json("history", "GET", "/api/history", validate=lambda d, r: isinstance(d, list))
        self.request_json("stats", "GET", "/api/stats", validate=lambda d, r: isinstance(d, dict))
        self.request_json("video_validation", "POST", "/api/upload-video", expected=(400,),
                          validate=lambda d, r: "error" in d)
        self.request_json("webcam_status", "GET", "/api/webcam-status",
                          validate=lambda d, r: "streaming" in d)

        passed = sum(1 for result in self.results if result["ok"])
        failed = [result for result in self.results if not result["ok"]]
        return {
            "summary": {"passed": passed, "failed": len(failed), "total": len(self.results)},
            "failed": failed,
            "results": self.results,
        }


if __name__ == "__main__":
    report = SmokeRunner().run()
    print(json.dumps(report, ensure_ascii=False, indent=2))
    raise SystemExit(0 if report["summary"]["failed"] == 0 else 1)
