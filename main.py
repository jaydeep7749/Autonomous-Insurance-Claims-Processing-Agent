import re, json
import pdfplumber

MANDATORY_FIELDS = [
    "policy_number", "policyholder_name", "effective_dates",
    "incident_date", "incident_time", "incident_location",
    "incident_description", "claimant", "third_parties",
    "contact_details", "asset_type", "asset_id",
    "estimated_damage", "claim_type", "attachments",
    "initial_estimate",
]

def pdf_to_text(path: str) -> str:
    with pdfplumber.open(path) as pdf:
        return "\n".join((p.extract_text() or "") for p in pdf.pages)

def first_group(pattern, text, flags=re.I | re.S):
    m = re.search(pattern, text, flags)
    return m.group(1).strip() if m else None

def extract_fields(text: str):
    f = {}
    # Policy info (ACORD auto loss has "POLICY NUMBER", "NAME OF INSURED") [file:1]
    f["policy_number"] = first_group(r"POLICY\s*NUMBER[:\s]*([A-Z0-9\-]+)", text)
    f["policyholder_name"] = first_group(r"NAME OF INSURED[^\n]*\n(.*)", text)
    f["effective_dates"] = first_group(r"Effective\s*Dates?[:\s]*([0-9/.\-\s]+to[0-9/.\-\s]+)", text)

    # Incident info (DATE OF LOSS, TIME, LOCATION OF LOSS, DESCRIPTION OF ACCIDENT) [file:1]
    f["incident_date"] = first_group(r"DATE OF LOSS[:\s]*([0-9]{2}/[0-9]{2}/[0-9]{4})", text)
    f["incident_time"] = first_group(r"TIME[:\s]*([0-9]{1,2}:[0-9]{2}\s*(?:AM|PM)?)", text)
    f["incident_location"] = first_group(r"LOCATION OF LOSS[^\n]*\n(.*)", text)
    f["incident_description"] = first_group(
        r"DESCRIPTION OF ACCIDENT[^\n]*\n(.+?)(?:\n[A-Z ]{5,}:|\Z)", text
    )

    # Parties (you can adjust these patterns to your sample docs)
    f["claimant"] = first_group(r"CLAIMANT[:\s]*([^\n]+)", text)
    f["third_parties"] = first_group(r"THIRD PART(?:Y|IES)[:\s]*([^\n]+)", text)
    f["contact_details"] = first_group(r"PHONE\s*#.*?\n(.+?)(?:\n\n|\Z)", text)

    # Asset details (auto: VIN, estimate amount) [file:1]
    f["asset_type"] = "Vehicle"
    f["asset_id"] = first_group(r"V\.?I\.?N\.?[:\s]*([A-HJ-NPR-Z0-9]{11,17})", text)
    f["estimated_damage"] = first_group(r"ESTIMATE AMOUNT[:\s]*([$]?\s*[0-9,\.]+)", text)

    # Other
    f["claim_type"] = first_group(r"CLAIM TYPE[:\s]*([^\n]+)", text)
    f["attachments"] = "Yes" if re.search(r"ATTACHMENT", text, re.I) else "Unknown"
    f["initial_estimate"] = first_group(r"INITIAL ESTIMATE[:\s]*([$]?\s*[0-9,\.]+)", text)

    return f

def find_missing_fields(f):
    return [k for k in MANDATORY_FIELDS if not f.get(k) or str(f[k]).strip() == ""]

def parse_amount(s: str) -> float:
    if not s: return 0.0
    n = re.sub(r"[^\d\.]", "", s)
    try: return float(n) if n else 0.0
    except ValueError: return 0.0

def route_claim(f, missing):
    desc = (f.get("incident_description") or "").lower()
    ctype = (f.get("claim_type") or "").lower()
    est = parse_amount(f.get("estimated_damage") or f.get("initial_estimate"))
    reasons = []

    if missing:
        return "Manual review", "Missing mandatory fields: " + ", ".join(missing)

    if any(w in desc for w in ["fraud", "inconsistent", "staged"]):
        return "Investigation Flag", "Description contains potential fraud indicators."

    if "injury" in ctype:
        return "Specialist Queue", "Claim type indicates injury."

    if est and est < 25000:
        return "Fast-track", f"Estimated damage {est} < 25000."

    return "Manual review", "No specific routing rule matched."

def process_fnol(path: str):
    text = pdf_to_text(path)
    fields = extract_fields(text)
    missing = find_missing_fields(fields)
    route, reason = route_claim(fields, missing)
    return {
        "extractedFields": fields,
        "missingFields": missing,
        "recommendedRoute": route,
        "reasoning": reason,
    }

if __name__ == "__main__":
    result = process_fnol("ACORD-Automobile-Loss-Notice-12.05.16.pdf")
    print(json.dumps(result, indent=2))