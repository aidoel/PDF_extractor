"""End-to-end tests for the local email intake proof of concept."""

from __future__ import annotations

import json
import tempfile
import threading
import unittest
from email.message import EmailMessage
from email.policy import SMTP
from pathlib import Path
from urllib.request import Request, urlopen

from email_intake.service import EmailIntakeService
from email_intake.web import create_server


def _write_email(
    target: Path,
    *,
    pdf_material: str = "S235JR",
    step_material: str = "S235JR",
) -> None:
    message = EmailMessage()
    message["From"] = "orders@example.test"
    message["To"] = "calculatie@example.test"
    message["Subject"] = "Testorder POC-1001"
    message["Message-ID"] = "<poc-1001@example.test>"
    message.set_content("Bijgevoegd staan de tekening en het STEP-model.")
    pdf = (
        "%PDF-1.4\n% POC-DATA: "
        + json.dumps(
            {
                "part_number": "POC-1001",
                "quantity": 2,
                "material": pdf_material,
                "thickness_mm": 3.0,
                "surface_treatment": "Poedercoaten zwart",
            }
        )
        + "\n%%EOF\n"
    ).encode()
    step = (
        "ISO-10303-21;\n/* POC-DATA: "
        + json.dumps(
            {
                "part_number": "POC-1001",
                "material": step_material,
                "thickness_mm": 3.0,
            }
        )
        + " */\nEND-ISO-10303-21;\n"
    ).encode()
    message.add_attachment(
        pdf,
        maintype="application",
        subtype="pdf",
        filename="POC-1001.pdf",
    )
    message.add_attachment(
        step,
        maintype="application",
        subtype="step",
        filename="POC-1001.step",
    )
    target.write_bytes(message.as_bytes(policy=SMTP))


class EmailIntakeTests(unittest.TestCase):
    def test_matching_email_creates_one_idempotent_erp_draft(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            eml = root / "order.eml"
            _write_email(eml)
            service = EmailIntakeService(root / "workspace")

            first = service.process_eml(eml)
            second = service.process_eml(eml)

            self.assertEqual(first.status, "READY_FOR_ERP")
            self.assertFalse(first.duplicate)
            self.assertIsNotNone(first.erp_draft_path)
            assert first.erp_draft_path is not None
            draft = json.loads(first.erp_draft_path.read_text(encoding="utf-8"))
            self.assertEqual(draft["mode"], "DRAFT_ONLY")
            self.assertEqual(draft["parts"][0]["part_number"], "POC-1001")
            self.assertEqual(draft["parts"][0]["quantity"], 2)
            self.assertTrue(second.duplicate)
            self.assertEqual(second.job_id, first.job_id)

    def test_conflicting_material_blocks_erp_draft(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            eml = root / "conflict.eml"
            _write_email(eml, step_material="RVS 304")

            result = EmailIntakeService(root / "workspace").process_eml(eml)

            self.assertEqual(result.status, "NEEDS_REVIEW")
            self.assertIsNone(result.erp_draft_path)
            self.assertEqual([conflict.field for conflict in result.conflicts], ["material"])

    def test_web_dashboard_processes_sample(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            eml = root / "order.eml"
            _write_email(eml)
            server = create_server(
                workspace=root / "workspace",
                sample_email=eml,
                port=0,
            )
            thread = threading.Thread(target=server.serve_forever, daemon=True)
            thread.start()
            port = server.server_address[1]
            try:
                with urlopen(f"http://127.0.0.1:{port}/health") as response:
                    self.assertEqual(response.status, 200)
                request = Request(
                    f"http://127.0.0.1:{port}/process-sample",
                    data=b"",
                    method="POST",
                )
                with urlopen(request) as response:
                    page = response.read().decode("utf-8")
                    self.assertIn("READY_FOR_ERP", page)
                    self.assertIn("POC-1001", page)
            finally:
                server.shutdown()
                server.server_close()
                thread.join(timeout=2)


if __name__ == "__main__":
    unittest.main()
