"""Demo content: the invoice-processing workflow used by the integrated demonstration."""
from __future__ import annotations

INVOICE_OK = (
    "ACME INDUSTRIAL SUPPLY\n"
    "Invoice No: INV-2041\n"
    "Vendor: Acme Industrial Supply\n"
    "Date: 03/14/2025\n"
    "Total Due: $1,250.00\n"
    "Terms: Net 30\n"
)

INVOICE_MISSING = (
    "NORTHWIND PARTS LTD\n"
    "Invoice No: INV-2042\n"
    "Vendor: Northwind Parts Ltd\n"
    "Date: 03/15/2025\n"
    "Terms: Net 30\n"
)

GOOD_PAYLOAD = {"document": INVOICE_OK, "source": "ap-inbox", "received_at": "2025-03-17T09:12:00Z"}
FAILING_PAYLOAD = {"document": INVOICE_MISSING, "source": "ap-inbox", "received_at": "2025-03-18T08:40:00Z"}

# Deliberately under-specified: keys are named so a live model matches the validator, but the value
# types and formats are never pinned — that is the defect the demo starts from.
VAGUE_PROMPT = (
    "Extract the invoice number, vendor, date and total amount from the invoice document. "
    "Return a JSON object with exactly these keys: invoice_number, vendor, date, amount."
)

DEMO_WORKFLOW = {
    "id": "wf_invoice_demo",
    "name": "Invoice Intake → ERP Posting",
    "description": "Extracts invoice fields with Claude, validates the contract, then posts to ERP when the "
                   "amount clears a threshold. A failing validation routes to an error handler.",
    "version": 1,
    "nodes": [
        {"id": "n_input", "type": "input", "label": "Invoice Input", "position": {"x": 0, "y": 120},
         "config": {"sample": GOOD_PAYLOAD}},
        {"id": "n_llm", "type": "llm", "label": "Claude Extract", "position": {"x": 235, "y": 120},
         "config": {"prompt": VAGUE_PROMPT, "output": "json", "model": "claude-opus-5-5", "timeout_ms": 30000}},
        {"id": "n_validator", "type": "validator", "label": "Invoice Contract", "position": {"x": 470, "y": 120},
         "config": {"rules": [
             {"field": "invoice_number", "type": "string", "required": True, "pattern": "^INV-\\d{4}$"},
             {"field": "vendor", "type": "string", "required": True},
             {"field": "date", "type": "string", "required": True, "pattern": "^\\d{4}-\\d{2}-\\d{2}$"},
             {"field": "amount", "type": "number", "required": True, "min": 0.01},
         ]}},
        {"id": "n_condition", "type": "condition", "label": "Amount > 100?", "position": {"x": 705, "y": 120},
         "config": {"field": "amount", "operator": ">", "value": 100}},
        {"id": "n_http", "type": "http", "label": "Post to ERP", "position": {"x": 940, "y": 30},
         "config": {"method": "POST", "url": "mock://erp/invoices", "timeout_ms": 5000}},
        {"id": "n_out_ok", "type": "output", "label": "Posted", "position": {"x": 1175, "y": 30},
         "config": {"outcome": "success"}},
        {"id": "n_out_review", "type": "output", "label": "Manual Review", "position": {"x": 940, "y": 215},
         "config": {"outcome": "review", "note": "Below the auto-post threshold"}},
        {"id": "n_out_error", "type": "output", "label": "Error Handler", "position": {"x": 470, "y": 330},
         "config": {"outcome": "error", "note": "Routed here because an upstream node failed"}},
    ],
    "edges": [
        {"id": "e1", "source": "n_input", "target": "n_llm", "sourceHandle": "out"},
        {"id": "e2", "source": "n_llm", "target": "n_validator", "sourceHandle": "out"},
        {"id": "e3", "source": "n_validator", "target": "n_condition", "sourceHandle": "out"},
        {"id": "e4", "source": "n_condition", "target": "n_http", "sourceHandle": "true"},
        {"id": "e5", "source": "n_condition", "target": "n_out_review", "sourceHandle": "false"},
        {"id": "e6", "source": "n_http", "target": "n_out_ok", "sourceHandle": "out"},
        {"id": "e7", "source": "n_validator", "target": "n_out_error", "sourceHandle": "error"},
        {"id": "e8", "source": "n_http", "target": "n_out_error", "sourceHandle": "error"},
    ],
}
