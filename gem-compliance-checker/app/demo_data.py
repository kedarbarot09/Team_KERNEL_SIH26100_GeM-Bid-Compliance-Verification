"""Demo Bidders Dataset and Realistic Document Generator for GeM Compliance Verification.

Generates realistic documents for all 10 bidder entities (BID-001 to BID-010)
from sample_data/mock_registry.json with synthetic applicant photos and signatures.

Identity Consistency Verification Test Scenarios:
- Intentional MATCH Profiles (8 bidders):
  BID-001, BID-002, BID-003, BID-005, BID-006, BID-008, BID-009, BID-010
  Embed identical synthetic applicant headshot and authorized signature across
  PAN Card, GST Registration, and OEM Authorization letters. Demonstrates PASS verdict.

- Intentional MISMATCH Profiles (2 bidders):
  BID-004 (Delta Precision Engineering) and BID-007 (Kavya Textiles)
  Both entities are otherwise fully clean on statutory text and portal checks,
  but deliberately embed Person A's photo/signature on PAN and Person B's photo/signature
  on GST Certificate. Demonstrates live visual identity MISMATCH / FAIL advisory verdict.
"""

import io
import json
import logging
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import fitz  # PyMuPDF
from PIL import Image, ImageDraw

logger = logging.getLogger(__name__)

DB_PATH = Path(__file__).resolve().parent.parent / "sample_data" / "mock_registry.json"


def load_all_bidders() -> List[Dict[str, Any]]:
    """Load the 10 bidder records from mock_registry.json."""
    if not DB_PATH.exists():
        logger.warning("mock_registry.json not found at %s", DB_PATH)
        return []
    try:
        with open(DB_PATH, "r", encoding="utf-8") as f:
            data = json.load(f)
            return data.get("bidders", [])
    except Exception as e:
        logger.error("Failed to load bidders: %s", e)
        return []


def get_bidder_by_id(bidder_id: str) -> Optional[Dict[str, Any]]:
    """Get a specific bidder dict by ID (case-insensitive)."""
    clean_id = bidder_id.strip().upper()
    for b in load_all_bidders():
        if b.get("bidder_id", "").upper() == clean_id:
            return b
    return None


PORTRAITS_DIR = Path(__file__).resolve().parent.parent / "sample_data" / "portraits"


def generate_synthetic_headshot(seed_str: str, variant: str = "A") -> bytes:
    """Generate or load an authentic photorealistic ID headshot for an applicant."""
    clean_seed = (seed_str or "").strip().upper()
    variant_upper = (variant or "A").strip().upper()

    # 1. Attempt to load real photograph of applicant
    candidate_files = [
        PORTRAITS_DIR / f"{clean_seed}_{variant_upper}.jpg",
        PORTRAITS_DIR / f"{clean_seed}_A.jpg",
        PORTRAITS_DIR / f"{clean_seed}.jpg",
    ]
    for ppath in candidate_files:
        if ppath.is_file():
            try:
                with Image.open(ppath) as pimg:
                    pimg_rgb = pimg.convert("RGB").resize((200, 240), Image.Resampling.LANCZOS)
                    buf = io.BytesIO()
                    pimg_rgb.save(buf, format="PNG")
                    return buf.getvalue()
            except Exception as e:
                logger.debug("Failed loading portrait file %s: %s", ppath, e)

    # 2. Fallback to programmatic geometric avatar if real image asset is missing
    img = Image.new("RGB", (200, 240), color=(235, 242, 250))
    draw = ImageDraw.Draw(img)

    if variant == "A":
        bg_color = (220, 233, 247)
        skin_color = (238, 195, 154)
        hair_color = (40, 30, 25)
        suit_color = (30, 58, 110)
        tie_color = (180, 40, 40)
        has_glasses = False
    else:
        # Deliberately different appearance for mismatch test cases
        bg_color = (245, 235, 224)
        skin_color = (180, 125, 85)
        hair_color = (80, 50, 30)
        suit_color = (50, 60, 55)
        tie_color = (40, 120, 100)
        has_glasses = True

    # Background
    draw.rectangle([0, 0, 200, 240], fill=bg_color)

    # Suit / Shoulders
    draw.polygon([(15, 240), (45, 180), (155, 180), (185, 240)], fill=suit_color)
    # White Collar
    draw.polygon([(75, 180), (100, 215), (125, 180)], fill=(255, 255, 255))
    # Tie
    draw.polygon([(95, 190), (105, 190), (108, 240), (92, 240)], fill=tie_color)

    # Neck
    draw.rectangle([85, 155, 115, 185], fill=skin_color)

    # Face Oval
    draw.ellipse([60, 65, 140, 165], fill=skin_color)

    # Hair
    if variant == "A":
        draw.chord([58, 48, 142, 110], start=180, end=360, fill=hair_color)
        draw.polygon([(58, 80), (60, 55), (100, 45), (140, 55), (142, 80)], fill=hair_color)
    else:
        draw.ellipse([54, 45, 146, 100], fill=hair_color)

    # Eyes
    draw.ellipse([76, 105, 88, 114], fill=(255, 255, 255))
    draw.ellipse([112, 105, 124, 114], fill=(255, 255, 255))
    draw.ellipse([80, 107, 86, 113], fill=(30, 20, 20))
    draw.ellipse([116, 107, 122, 113], fill=(30, 20, 20))

    # Eyebrows
    draw.line([(74, 98), (90, 97)], fill=hair_color, width=2)
    draw.line([(110, 97), (126, 98)], fill=hair_color, width=2)

    # Nose
    draw.line([(100, 112), (97, 128), (103, 128)], fill=(160, 110, 80), width=2)

    # Mouth
    draw.arc([85, 134, 115, 146], start=20, end=160, fill=(160, 80, 80), width=2)

    # Glasses if variant B
    if has_glasses:
        draw.rectangle([72, 102, 92, 117], outline=(30, 30, 30), width=2)
        draw.rectangle([108, 102, 128, 117], outline=(30, 30, 30), width=2)
        draw.line([(92, 108), (108, 108)], fill=(30, 30, 30), width=2)

    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


def generate_synthetic_signature(seed_str: str, variant: str = "A", name: str = "Signatory") -> bytes:
    """Generate a cursive signature on high-contrast white document background."""
    img = Image.new("RGB", (260, 85), color=(255, 255, 255))
    draw = ImageDraw.Draw(img)
    ink = (15, 45, 105) if variant == "A" else (25, 25, 25)

    if variant == "A":
        # Ascending cursive loops with flourish underline
        points = [
            (25, 55), (35, 25), (42, 60), (52, 30), (62, 58),
            (75, 40), (88, 48), (102, 32), (115, 52), (130, 38),
            (145, 50), (165, 30), (185, 48), (210, 35), (235, 52),
        ]
        for i in range(len(points) - 1):
            draw.line([points[i], points[i + 1]], fill=ink, width=3)
        draw.line([(20, 68), (240, 65)], fill=ink, width=2)
        draw.line([(60, 74), (200, 72)], fill=ink, width=1)
    else:
        # Compact rounded angular script with cross slash and dot
        points = [
            (30, 42), (48, 20), (58, 55), (70, 35), (82, 50),
            (98, 22), (112, 48), (128, 30), (145, 45), (170, 25),
            (195, 48), (215, 20),
        ]
        for i in range(len(points) - 1):
            draw.line([points[i], points[i + 1]], fill=ink, width=3)
        draw.line([(40, 62), (220, 38)], fill=ink, width=2)
        draw.ellipse([228, 36, 234, 42], fill=ink)

    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


def create_pdf_with_visuals(
    title: str,
    subtitle: str,
    fields: List[Tuple[str, str]],
    notes_paragraph: str = "",
    photo_png_bytes: Optional[bytes] = None,
    photo_caption: str = "Photograph",
    signature_png_bytes: Optional[bytes] = None,
    signatory_title: str = "Authorised Signatory",
) -> bytes:
    """Create a high-fidelity government-styled PDF document with embedded text, photo, and signature."""
    doc = fitz.open()
    page = doc.new_page(width=595, height=842)

    # 1. Header Bar
    page.draw_rect(fitz.Rect(36, 36, 559, 78), color=(0.08, 0.20, 0.38), fill=(0.93, 0.95, 0.98))
    page.insert_text(fitz.Point(50, 55), title, fontsize=12, fontname="helv", color=(0.08, 0.20, 0.38))
    page.insert_text(fitz.Point(50, 70), subtitle, fontsize=8.5, fontname="helv", color=(0.35, 0.40, 0.48))
    page.draw_line(fitz.Point(36, 88), fitz.Point(559, 88), color=(0.08, 0.20, 0.38), width=1.5)

    y_pos = 115.0

    # 2. Insert Photo if present
    if photo_png_bytes:
        photo_rect = fitz.Rect(435, 98, 540, 224)
        page.draw_rect(photo_rect, color=(0.7, 0.7, 0.7), width=1.0)
        page.insert_image(photo_rect, stream=photo_png_bytes)
        page.insert_text(fitz.Point(440, 236), photo_caption, fontsize=7.5, fontname="helv", color=(0.3, 0.3, 0.3))

    # 3. Fields
    for label, val in fields:
        page.insert_text(fitz.Point(50, y_pos), f"{label}:", fontsize=9.5, fontname="helv", color=(0.2, 0.2, 0.2))
        page.insert_text(fitz.Point(210, y_pos), str(val), fontsize=9.5, fontname="helv", color=(0.05, 0.05, 0.05))
        y_pos += 22.0

    if notes_paragraph:
        y_pos = max(y_pos + 15.0, 250.0 if photo_png_bytes else y_pos + 15.0)
        page.draw_rect(fitz.Rect(45, y_pos - 10, 550, y_pos + 45), fill=(0.97, 0.97, 0.98), color=(0.85, 0.85, 0.88))
        page.insert_text(fitz.Point(55, y_pos + 8), "Statutory Verification & Legal Standing Notes:", fontsize=8.5, fontname="helv", color=(0.15, 0.15, 0.25))
        page.insert_text(fitz.Point(55, y_pos + 25), notes_paragraph[:120], fontsize=8.0, fontname="helv", color=(0.3, 0.3, 0.3))
        y_pos += 60.0

    # 4. Signature Block
    sig_y = max(y_pos + 40.0, 640.0)
    if signature_png_bytes:
        sig_rect = fitz.Rect(380, sig_y, 530, sig_y + 65)
        page.insert_image(sig_rect, stream=signature_png_bytes)
        page.draw_line(fitz.Point(370, sig_y + 70), fitz.Point(540, sig_y + 70), color=(0.4, 0.4, 0.4), width=0.8)
        page.insert_text(fitz.Point(380, sig_y + 82), signatory_title, fontsize=9.5, fontname="helv", color=(0.1, 0.1, 0.1))
        page.insert_text(fitz.Point(380, sig_y + 94), "Digitally signed / Verified Authority", fontsize=8.0, fontname="helv", color=(0.4, 0.4, 0.4))
    else:
        page.draw_line(fitz.Point(370, sig_y + 70), fitz.Point(540, sig_y + 70), color=(0.4, 0.4, 0.4), width=0.8)
        page.insert_text(fitz.Point(380, sig_y + 82), signatory_title, fontsize=9.5, fontname="helv", color=(0.1, 0.1, 0.1))

    # Page Footer
    page.draw_line(fitz.Point(36, 800), fitz.Point(559, 800), color=(0.8, 0.8, 0.8), width=0.5)
    page.insert_text(fitz.Point(50, 814), "Government e-Marketplace (GeM) Verification Document • For Official Tender Audit Only", fontsize=7.5, fontname="helv", color=(0.5, 0.5, 0.5))

    pdf_bytes = doc.tobytes()
    doc.close()
    return pdf_bytes


BID_PRESETS = [
    {
        "bidder_id": "BID-001",
        "company_name": "Alpha Tech Solutions Pvt Ltd",
        "label": "BID-001: Alpha Tech Solutions (Micro MSE - Fully Compliant)",
        "badge": "🟢 COMPLIANT",
        "category": "Micro",
        "notes": (
            "Udyam: UDYAM-MH-01-0012345 (Permanent/Active, DigiLocker verified) | "
            "GSTIN: 27AAACA1234A1Z5 (Active, Regular 3B filing) | "
            "ITR: Filed AY 2022-23 to 2024-25 | "
            "Turnover: ₹5.27 Cr avg (CA UDIN: 25412356AAAAAA1234) | "
            "MII: 68.5% Class-1 (Pune, MH) | "
            "OEM: ComputeTech Global AUTH-CTG-2026-991 (to 31-Dec-2027) | "
            "Clean Notarized Non-Blacklist Affidavit"
        ),
    },
    {
        "bidder_id": "BID-002",
        "company_name": "Beta Infra Projects Ltd",
        "label": "BID-002: Beta Infra Projects (Medium - Suspended GST, Expired Udyam)",
        "badge": "🔴 DISQUALIFIED",
        "category": "Medium",
        "notes": (
            "Udyam: UDYAM-GJ-01-0098765 (EXPIRED on 31-Mar-2022, Annual re-declaration overdue) | "
            "GSTIN: 24BBBCB5678B1Z2 (SUSPENDED under Rule 21A, GSTR-3B Defaulter since Oct-2025) | "
            "ITR: Missing AY 2023-24 (Unfiled/Unacknowledged) | "
            "Turnover CA UDIN: INVALID_UDIN_NOT_RESOLVED (Unverified) | "
            "EMD: Invalid MSE exemption claim (Medium category & expired Udyam, No BG) | "
            "MII: 25.0% Non-Local Supplier (Min 50% required for Class-1) | "
            "Unnotarized Non-Blacklisting Affidavit"
        ),
    },
    {
        "bidder_id": "BID-003",
        "company_name": "Gamma Trading Corporation",
        "label": "BID-003: Gamma Trading Corp (Small MSE - Blacklisted by Min of Coal)",
        "badge": "🔴 BLACKLISTED",
        "category": "Small",
        "notes": (
            "Central Watchlist Match: DEBARRED by Ministry of Coal "
            "(Order: MoC/Vig/2025/112, Period: 10-Feb-2025 to 09-Feb-2028, Reason: 'Corrupt and fraudulent practice') | "
            "Udyam: UDYAM-DL-01-0034567 (Small, Active) | "
            "GSTIN: 07CCCGC9012C1Z8 (Active, Regular) | "
            "ITR: 3-Year filed & ack | "
            "Turnover: ₹4.13 Cr avg (UDIN: 25512489BBBBBB4321) | "
            "MII: 52.0% Class-1 | "
            "OEM: National Cabling Ltd AUTH-NCL-4412"
        ),
    },
    {
        "bidder_id": "BID-004",
        "company_name": "Delta Precision Engineering Ltd",
        "label": "BID-004: Delta Precision Eng (Small MSE - NSIC, Direct OEM, 82% MII)",
        "badge": "🟢 COMPLIANT",
        "category": "Small",
        "notes": (
            "NSIC Single Point Reg: NSIC/BNG/2023/8891 (Monetary Limit: ₹15.0 Cr, Valid to 30-Jun-2027, EMD exempt) | "
            "Udyam: UDYAM-KR-03-0045678 (Small, DigiLocker verified) | "
            "GSTIN: 29DDDCD3456D1ZC (Active, DigiLocker verified) | "
            "Turnover: ₹9.27 Cr avg (UDIN: 25098765CCCCCC7890) | "
            "MII: 82.0% Class-1 Local (Peenya, Bengaluru) | "
            "OEM: Direct Manufacturer (Self, Permanent) | "
            "ISO: 9001:2015 & 14001:2015 | "
            "Past Orders: HAL ₹2.4 Cr, ISRO ₹1.9 Cr"
        ),
    },
    {
        "bidder_id": "BID-005",
        "company_name": "Epsilon Office Supplies LLP",
        "label": "BID-005: Epsilon Office Supplies (Micro Startup - DPIIT Exemptions)",
        "badge": "🟡 STARTUP EXEMPT",
        "category": "Micro Startup",
        "notes": (
            "DPIIT Recognized Startup: Cert DIPP98765 (Recognized: 01-Mar-2024 to 28-Feb-2034, Turnover & Experience Waivers applied) | "
            "Udyam: UDYAM-HR-05-0067890 (Micro, DigiLocker verified) | "
            "GSTIN: 06EEEPE7890E1ZF (Active) | "
            "LLPIN: AAR-8765 (Inc: 20-Jan-2024) | "
            "ITR: AY 2025-26 filed 18-Jul-2025 | "
            "MII: 50.0% Class-1 (Gurugram, HR) | "
            "OEM: DeskMate Stationery AUTH-DMS-8871 (to 31-Jan-2027)"
        ),
    },
    {
        "bidder_id": "BID-006",
        "company_name": "Zenith Defence Systems Ltd",
        "label": "BID-006: Zenith Defence Systems (Large - SBI Bank Guarantee EMD)",
        "badge": "🟢 COMPLIANT",
        "category": "Large",
        "notes": (
            "Large Enterprise (CIN: L32100TN2005PLC044321, Udyam exempt) | "
            "EMD: SBI Bank Guarantee SBI-BG-2026-88741 (₹25,00,000, Valid to 31-Mar-2027, SFMS Verified: YES) | "
            "GSTIN: 33ZZZPZ9999Z1ZK (Active) | "
            "Turnover: ₹278.5 Cr avg (UDIN: 25100234EEEEEE9988) | "
            "MII: 58.0% Class-1 (Avadi, Chennai) | "
            "OEM: Direct Manufacturer (Self) | "
            "Standards: Aerospace AS9100D (to 12-Apr-2028) & ISO 9001 | "
            "Past Orders: MoD ₹45 Cr, DRDO ₹18.5 Cr"
        ),
    },
    {
        "bidder_id": "BID-007",
        "company_name": "Kavya Textiles Pvt Ltd",
        "label": "BID-007: Kavya Textiles (Small MSE - NSIC Exemption, 94% MII, BIS)",
        "badge": "🟢 COMPLIANT",
        "category": "Small",
        "notes": (
            "NSIC Single Point Reg: NSIC/AHD/GP/2022/4512 (Limit: ₹10.0 Cr, Valid to 15-May-2027, EMD exempt, Uniform Fabrics) | "
            "Udyam: UDYAM-GJ-04-0078912 (Small, DigiLocker verified) | "
            "GSTIN: 24KKKPK1122K1ZL (Active) | "
            "Turnover: ₹7.83 Cr avg (UDIN: 25334455FFFFFF1122) | "
            "MII: 94.0% Class-1 Local (Ahmedabad, GJ) | "
            "BIS IS 15748:2007 (Valid to 19-Aug-2027) | "
            "OEM: Direct Manufacturer | "
            "Past Work: CRPF Training Wing ₹2.1 Cr"
        ),
    },
    {
        "bidder_id": "BID-008",
        "company_name": "Omega Pharma Distributors",
        "label": "BID-008: Omega Pharma (Small MSE - Cancelled GST, EPFO Defaulter)",
        "badge": "🔴 DISQUALIFIED",
        "category": "Small",
        "notes": (
            "GSTIN: 27OOOPO3344O1ZQ CANCELLED on 15-Jan-2026 (Suo Moto Cancellation by GSTN, Filing: Inactive) | "
            "EPFO/ESIC: Defaulter notice issued (EPFO MH/PUN/0067891/000, ESIC 31000678910000606, Unpaid dues since Nov-2025) | "
            "Turnover: ₹5.43 Cr avg (UDIN: 25445566GGGGGG3344) | "
            "MII: 42.0% Class-2 Local Supplier (Fails Class-1 >=50% requirement) | "
            "Technical Specs: 3 Deviations Unmitigated | "
            "WHO-GMP Cert: Valid to 30-Aug-2026 | "
            "OEM: Apex Formulations AUTH-AFL-993"
        ),
    },
    {
        "bidder_id": "BID-009",
        "company_name": "Nova Renewable Energy Pvt Ltd",
        "label": "BID-009: Nova Renewable Energy (Micro Startup - BIS Solar PV IS 14286)",
        "badge": "🟡 STARTUP EXEMPT",
        "category": "Micro Startup",
        "notes": (
            "DPIIT Recognized Startup: Cert DIPP11223 (Recognized: 10-May-2023 to 09-May-2033, Solar & Renewable, Turnover & Exp waivers applied) | "
            "Udyam: UDYAM-RJ-02-0091234 (Micro, DigiLocker verified) | "
            "GSTIN: 08NNNPN5566N1ZR (Active) | "
            "MII: 78.0% Class-1 (Jaipur, RJ) | "
            "BIS IS 14286 Solar PV Standard (Valid to 20-Nov-2027) | "
            "OEM: Direct Manufacturer (Self) | "
            "ITR: Filed AY 2024-25 & 2025-26"
        ),
    },
    {
        "bidder_id": "BID-010",
        "company_name": "Sundar Facility Management Services",
        "label": "BID-010: Sundar Facility Mgmt (Micro - Expired Udyam, Missing Docs)",
        "badge": "🔴 DISQUALIFIED",
        "category": "Micro",
        "notes": (
            "Udyam: UDYAM-TS-09-0019283 (EXPIRED on 31-Dec-2022, Unverified manual upload) | "
            "GSTIN: 36SSSS57788S1ZU (Active, Late_Filer on GSTR-3B) | "
            "ITR: Missing AY 2024-25 (Unfiled/No Ack) | "
            "EPFO/ESIC: Default notice (TS/HYD/0077881/000, Unpaid dues since Mar-2026) | "
            "Turnover: ₹0.94 Cr avg (Fails ₹3.0 Cr tender threshold) | "
            "EMD: MSE Exemption Rejected (Invalid Udyam, No BG) | "
            "Missing MCA Incorporation & MII Declaration | "
            "Defective Blacklist Declaration (Unnotarized)"
        ),
    },
]


def generate_bidder_demo_documents(bidder_id: str) -> Dict[Tuple[str, str], Tuple[str, bytes]]:
    """Generate realistic text files for any of the 10 bidders based on database profile.

    Returns:
        Mapping: (category_name, document_type) -> (filename, file_bytes)
    """
    bidder = get_bidder_by_id(bidder_id)
    if not bidder:
        logger.error("Bidder %s not found in database.", bidder_id)
        return {}

    b_id = bidder.get("bidder_id", bidder_id)
    name = bidder.get("company_name", "Unknown Bidder")
    prof = bidder.get("profile", {})
    docs = bidder.get("documents", {})

    statutory = docs.get("statutory", {})
    financial = docs.get("financial", {})
    exempt = docs.get("eligibility_exemption", {})
    tech = docs.get("technical", {})
    comp = docs.get("compliance_background", {})

    sample_docs: Dict[Tuple[str, str], Tuple[str, bytes]] = {}

    # Visual identity assets configuration:
    # BID-004 and BID-007 are intentionally configured as visual identity MISMATCH demo cases
    is_mismatch_case = b_id in ("BID-004", "BID-007")
    pan_variant = "A"
    gst_variant = "B" if is_mismatch_case else "A"
    oem_variant = "A"

    photo_pan = generate_synthetic_headshot(b_id, variant=pan_variant)
    photo_gst = generate_synthetic_headshot(b_id, variant=gst_variant)
    sig_pan = generate_synthetic_signature(b_id, variant=pan_variant, name=name)
    sig_gst = generate_synthetic_signature(b_id, variant=gst_variant, name=name)
    sig_oem = generate_synthetic_signature(b_id, variant=oem_variant, name=name)

    # -------------------------------------------------------------------------
    # 1. Statutory Documents
    # -------------------------------------------------------------------------
    # Udyam Certificate
    udyam = statutory.get("udyam_certificate")
    if udyam:
        unum = udyam.get("number", "UDYAM-XX-00-0000000")
        etype = udyam.get("enterprise_type", "Micro")
        idate = udyam.get("issue_date", "2021-01-01")
        validity = udyam.get("validity", "PERMANENT")
        verified = udyam.get("verified", True)
        source = udyam.get("source", "MANUAL_UPLOAD")
        exp_date = udyam.get("expiry_date")
        exp_reason = udyam.get("expiry_reason")

        if validity == "PERMANENT":
            status_text = "ACTIVE (PERPETUAL)"
            validity_line = "Validity: Permanent (Active on National MSME Udyam Portal)\n"
        else:
            status_text = f"EXPIRED (Lapsed on {exp_date or '2022-03-31'})"
            validity_line = (
                f"Certificate Expiration Date: {exp_date or '2022-03-31'}\n"
                f"Status: EXPIRED / LAPSED ({exp_reason or 'Annual re-declaration overdue under MSME Notification S.O. 2119(E)'})\n"
            )

        udyam_body = (
            f"GOVERNMENT OF INDIA - MINISTRY OF MICRO, SMALL & MEDIUM ENTERPRISES\n"
            f"UDYAM REGISTRATION CERTIFICATE\n"
            f"------------------------------------------------------------------\n"
            f"Udyam Registration Number: {unum}\n"
            f"Name of Enterprise: {name}\n"
            f"Enterprise Type: {etype} Enterprise\n"
            f"Date of Incorporation / Registration: {idate}\n"
            f"Validity Status: {status_text}\n"
            f"{validity_line}"
            f"Issuing Source: {source}\n"
            f"Statutory Portal Verified: {'YES' if verified else 'NO'}\n"
            f"Major Activity: Manufacturing / Services under MSME Development Act, 2006.\n"
        )
        sample_docs[("Statutory / registration documents", "Udyam Registration Certificate")] = (
            f"{unum}.txt",
            udyam_body.encode("utf-8"),
        )

    # GST Registration Certificate (PDF with photo & signature)
    gst = statutory.get("gst_registration")
    if gst:
        gstin = gst.get("gstin", prof.get("gstin", "27AAAAA0000A1Z5"))
        status = gst.get("status", "Active")
        filing_status = gst.get("filing_status_3b", "Regular")
        c_date = gst.get("cancellation_date")

        gst_notes = ""
        if c_date:
            gst_notes = f"Date of Cancellation: {c_date}. Cancellation Reason: Non-compliance or Suo Moto Cancellation under GST Rules."
        elif status.lower() == "suspended":
            gst_notes = "Remarks: GSTIN temporarily suspended under Rule 21A due to return filing non-compliance."
        else:
            gst_notes = "Remarks: Registration valid and in good statutory standing."

        gst_fields = [
            ("Registration Number (GSTIN)", gstin),
            ("Legal Name", name),
            ("Trade Name", name),
            ("Registration Status", status.upper()),
            ("GSTR-3B Tax Filing Track", filing_status),
            ("Members of Managing Committee", "Managing Committee Member - Verified"),
        ]

        gst_pdf_bytes = create_pdf_with_visuals(
            title="GOVERNMENT OF INDIA - GOODS AND SERVICES TAX",
            subtitle="REGISTRATION CERTIFICATE (FORM GST REG-06) • DETAILS OF MANAGING COMMITTEE",
            fields=gst_fields,
            notes_paragraph=gst_notes,
            photo_png_bytes=photo_gst,
            photo_caption="Members of Managing Committee",
            signature_png_bytes=sig_gst,
            signatory_title="Approving Authority / Authorised Signatory",
        )

        sample_docs[("Statutory / registration documents", "GST Registration Certificate")] = (
            f"gst_registration_{b_id}.pdf",
            gst_pdf_bytes,
        )

    # PAN Card (PDF with photo & signature)
    pan_doc = statutory.get("pan_card")
    if pan_doc:
        pan_num = pan_doc.get("pan", prof.get("pan", "AAAAA0000A"))
        p_status = pan_doc.get("status", "VALID")

        pan_fields = [
            ("Permanent Account Number", pan_num),
            ("Name", name),
            ("Category", prof.get("category", "Company")),
            ("Status", p_status),
            ("Issuance Date", "15/04/2018"),
        ]

        pan_pdf_bytes = create_pdf_with_visuals(
            title="INCOME TAX DEPARTMENT - GOVERNMENT OF INDIA",
            subtitle="PERMANENT ACCOUNT NUMBER CARD",
            fields=pan_fields,
            notes_paragraph="Valid Permanent Account Number registered under Income Tax Department database.",
            photo_png_bytes=photo_pan,
            photo_caption="Applicant Photograph",
            signature_png_bytes=sig_pan,
            signatory_title="Signature of Cardholder / Authorized Signatory",
        )

        sample_docs[("Statutory / registration documents", "PAN Card")] = (
            f"pan_card_{b_id}.pdf",
            pan_pdf_bytes,
        )

    # MCA Incorporation Certificate
    mca = statutory.get("mca_incorporation")
    if mca:
        cin = mca.get("cin", prof.get("cin", "U72200MH2018PTC308912"))
        inc_date = mca.get("inc_date", "2018-01-01")
        mca_status = mca.get("status", "Active")
        mca_body = (
            f"MINISTRY OF CORPORATE AFFAIRS - REGISTRAR OF COMPANIES\n"
            f"CERTIFICATE OF INCORPORATION\n"
            f"------------------------------------------------------------------\n"
            f"Corporate Identity Number (CIN): {cin}\n"
            f"Company / LLP Name: {name}\n"
            f"Date of Incorporation: {inc_date}\n"
            f"Status: {mca_status}\n"
            f"Registered under the Companies Act / LLP Act with Registrar of Companies.\n"
        )
        sample_docs[("Statutory / registration documents", "Certificate of Incorporation (MCA)")] = (
            f"mca_incorporation_{b_id}.txt",
            mca_body.encode("utf-8"),
        )

    # Income Tax Returns
    itr_list = statutory.get("itr_v_3years", [])
    if itr_list:
        itr_body = (
            f"INCOME TAX DEPARTMENT - GOVT OF INDIA\n"
            f"ACKNOWLEDGMENT OF INCOME TAX RETURNS (ITR-V)\n"
            f"------------------------------------------------------------------\n"
            f"Entity Name: {name}\n"
            f"PAN: {prof.get('pan')}\n\n"
        )
        for entry in itr_list:
            ay = entry.get("ay", "N/A")
            fdate = entry.get("filed_date")
            ack = entry.get("acknowledged", False)
            if fdate and ack:
                itr_body += f"Assessment Year {ay}: Filed on {fdate} | Acknowledged & Verified: YES (Ack No: {hash(ay + b_id) % 1000000000000})\n"
            else:
                itr_body += f"Assessment Year {ay}: NOT FILED / NO VERIFICATION ACKNOWLEDGMENT FOUND (Deficient)\n"

        sample_docs[("Statutory / registration documents", "Income Tax Returns")] = (
            f"itr_returns_{b_id}.txt",
            itr_body.encode("utf-8"),
        )

    # EPFO / ESIC Clearance
    epfo_esic = statutory.get("epfo_esic_clearance")
    if epfo_esic:
        epfo_code = epfo_esic.get("epfo_code", "N/A")
        esic_code = epfo_esic.get("esic_code", "N/A")
        default_flag = epfo_esic.get("default_flag", False)
        last_paid = epfo_esic.get("last_paid_month", "N/A")

        labour_body = (
            f"EMPLOYEES PROVIDENT FUND ORGANISATION (EPFO) & ESIC\n"
            f"STATUTORY LABOUR COMPLIANCE CLEARANCE CERTIFICATE\n"
            f"------------------------------------------------------------------\n"
            f"Establishment Name: {name}\n"
            f"EPFO Establishment Code: {epfo_code}\n"
            f"ESIC 17-digit Code: {esic_code}\n"
            f"Last Remittance Month Logged: {last_paid}\n"
            f"Default Flag: {'YES - DEFAULT DETECTED IN STATUTORY DUES' if default_flag else 'NO - ALL DUES REGULAR AND UP TO DATE'}\n"
        )
        sample_docs[("Statutory / registration documents", "EPFO/ESIC registration certificate")] = (
            f"epfo_esic_clearance_{b_id}.txt",
            labour_body.encode("utf-8"),
        )

    # -------------------------------------------------------------------------
    # 2. Financial Documents
    # -------------------------------------------------------------------------
    # Audited Turnover Certificate
    turnover_data = financial.get("audited_turnover_certificate")
    if turnover_data:
        ca_mem = turnover_data.get("ca_membership_num", "000000")
        udin = turnover_data.get("udin", "25000000AAAAAA0000")
        fy1 = turnover_data.get("fy_2023_24_inr_cr", 0.0)
        fy2 = turnover_data.get("fy_2024_25_inr_cr", 0.0)
        fy3 = turnover_data.get("fy_2025_26_inr_cr", 0.0)
        avg_cr = (fy1 + fy2 + fy3) / 3.0
        avg_lakhs = avg_cr * 100.0

        # Note DPIIT startup note if applicable
        dpiit = exempt.get("dpiit_startup")
        startup_note = ""
        if dpiit and dpiit.get("turnover_exemption_eligible"):
            startup_note = f"\n[STARTUP RELAXATION CLAIM]: Vendor holds valid DPIIT Startup Certificate #{dpiit.get('cert_num')} and requests turnover criteria waiver as per GeM/DPIIT procurement guidelines."

        turnover_body = (
            f"CHARTERED ACCOUNTANTS AUDITED TURNOVER CERTIFICATE\n"
            f"------------------------------------------------------------------\n"
            f"Client Name: {name}\n"
            f"CA Membership Number: {ca_mem}\n"
            f"Unique Document Identification Number (UDIN): {udin}\n"
            f"Audited Turnover Records:\n"
            f"  - Financial Year 2023-24: INR {fy1:.2f} Crores ({fy1 * 100:.2f} Lakhs)\n"
            f"  - Financial Year 2024-25: INR {fy2:.2f} Crores ({fy2 * 100:.2f} Lakhs)\n"
            f"  - Financial Year 2025-26: INR {fy3:.2f} Crores ({fy3 * 100:.2f} Lakhs)\n"
            f"Average Annual Turnover (Last 3 FYs): INR {avg_cr:.2f} Crores ({avg_lakhs:.2f} Lakhs)\n"
            f"{startup_note}\n"
        )
        sample_docs[("Financial documents", "Audited financial statement / turnover certificate")] = (
            f"turnover_certificate_{b_id}.txt",
            turnover_body.encode("utf-8"),
        )

    # EMD Proof
    emd = financial.get("emd_proof")
    if emd:
        emd_type = emd.get("type", "EXEMPTION_MSE")
        claimed = emd.get("exemption_claimed", False)
        basis = emd.get("claimed_basis")
        valid = emd.get("exemption_valid")
        bg_details = emd.get("bg_details")

        if emd_type == "BANK_GUARANTEE" and bg_details:
            bname = bg_details.get("bank_name", "Nationalized Bank")
            bgnum = bg_details.get("bg_number", "BG-000")
            amt = bg_details.get("amount_inr", 0)
            v_until = bg_details.get("valid_until", "2027-01-01")
            sfms = bg_details.get("sfms_verified", True)

            emd_body = (
                f"BANK GUARANTEE FOR EARNEST MONEY DEPOSIT (EMD)\n"
                f"------------------------------------------------------------------\n"
                f"Issuing Bank: {bname}\n"
                f"Bank Guarantee Number (BG No): {bgnum}\n"
                f"Beneficiary: Government e-Marketplace / Procuring Entity\n"
                f"Amount: INR {amt:,} (Twenty-Five Lakhs Only)\n"
                f"Valid Until: {v_until}\n"
                f"SFMS Message Confirmation: {'VERIFIED ON SFMS PORTAL' if sfms else 'SFMS PENDING'}\n"
            )
        elif emd_type == "EXEMPTION_STARTUP":
            dpiit_c = exempt.get("dpiit_startup", {})
            emd_body = (
                f"EMD EXEMPTION CLAIM - STARTUP INDIA / DPIIT POLICY\n"
                f"------------------------------------------------------------------\n"
                f"Entity Name: {name}\n"
                f"DPIIT Startup Certificate: {dpiit_c.get('cert_num', 'DIPP00000')}\n"
                f"Exemption Claimed: 100% EMD Waiver as per Rule 170(i) of General Financial Rules (GFR), 2017.\n"
                f"Exemption Validity: VALID AND ELIGIBLE\n"
            )
        elif emd_type == "EXEMPTION_NSIC":
            nsic_c = exempt.get("nsic_certificate", {})
            emd_body = (
                f"EMD EXEMPTION CLAIM - NSIC SINGLE POINT REGISTRATION SCHEME\n"
                f"------------------------------------------------------------------\n"
                f"Entity Name: {name}\n"
                f"NSIC Registration Number: {nsic_c.get('cert_num', 'NSIC/0000')}\n"
                f"Monetary Limit: INR {nsic_c.get('monetary_limit_cr', 10.0)} Crores\n"
                f"Exemption Basis: NSIC Single Point Registration Scheme for Government Purchases\n"
                f"Exemption Status: VALID\n"
            )
        elif emd_type == "EXEMPTION_MSE" and valid:
            emd_body = (
                f"EMD EXEMPTION UNDER PUBLIC PROCUREMENT POLICY FOR MSEs\n"
                f"------------------------------------------------------------------\n"
                f"Entity Name: {name}\n"
                f"Claimed Basis: Active Udyam Registration Certificate\n"
                f"Enterprise Category: {prof.get('category', 'Micro')} MSE\n"
                f"Exemption Status: VALID 100% EMD WAIVER GRANTED\n"
            )
        else:
            emd_body = (
                f"EMD EXEMPTION CLAIM - DEFICIENT / INVALID\n"
                f"------------------------------------------------------------------\n"
                f"Entity Name: {name}\n"
                f"Claimed Basis: {basis or 'Udyam'}\n"
                f"Status: EXEMPTION INVALID / NOT ENTITLED (Udyam expired or entity not MSE/Startup)\n"
                f"DEFICIENCY: No valid payment receipt or Bank Guarantee furnished.\n"
            )

        sample_docs[("Financial documents", "EMD proof")] = (
            f"emd_submission_{b_id}.txt",
            emd_body.encode("utf-8"),
        )

    # -------------------------------------------------------------------------
    # 3. Eligibility Exemption / Preference Documents
    # -------------------------------------------------------------------------
    # Make in India declaration
    mii = exempt.get("make_in_india_declaration")
    if mii:
        pct = mii.get("local_content_percentage", 50.0)
        ctype = mii.get("class_type", "Class-1 Local Supplier")
        loc = mii.get("location_of_value_add", "India")

        mii_body = (
            f"LOCAL CONTENT SELF-DECLARATION UNDER MAKE IN INDIA (MII) POLICY\n"
            f"Reference: Ministry of Commerce and Industry Public Procurement Order\n"
            f"------------------------------------------------------------------\n"
            f"Supplier Name: {name}\n"
            f"Local Content Percentage: {pct:.1f}%\n"
            f"Supplier Classification: {ctype}\n"
            f"Location of Local Value Addition: {loc}\n"
            f"We solemn affirm that the products offered satisfy the minimum local content criteria.\n"
        )
        sample_docs[("Eligibility exemption / preference documents", "Make in India / local content self-declaration")] = (
            f"mii_declaration_{b_id}.txt",
            mii_body.encode("utf-8"),
        )

    # -------------------------------------------------------------------------
    # 4. Technical / Product-Specific Documents
    # -------------------------------------------------------------------------
    # OEM Authorization (PDF with signature)
    oem = tech.get("oem_authorization")
    if oem:
        oem_name = oem.get("oem_name", "ComputeTech Global Ltd")
        acode = oem.get("auth_code", "AUTH-000")
        vuntil = oem.get("valid_until", "2027-12-31")

        if acode == "SELF_MANUFACTURER":
            oem_fields = [
                ("Manufacturer Name", name),
                ("Authorization Code", "SELF_MANUFACTURER"),
                ("Validity", "PERMANENT"),
                ("Direct OEM Certification", "We hereby certify that we are the Original Equipment Manufacturer (OEM) directly manufacturing the products quoted in this bid."),
            ]
            oem_pdf_bytes = create_pdf_with_visuals(
                title="ORIGINAL EQUIPMENT MANUFACTURER (OEM) SELF-DECLARATION",
                subtitle="DIRECT OEM MANUFACTURING CERTIFICATE",
                fields=oem_fields,
                notes_paragraph="Direct manufacturer self-certification recognized for tender compliance.",
                signature_png_bytes=sig_oem,
                signatory_title="Authorised Signatory - Factory Operations",
            )
        else:
            oem_fields = [
                ("OEM Principal", oem_name),
                ("Authorized Bidder", name),
                ("Authorization Code", acode),
                ("Valid Until", vuntil),
                ("Authorization Scope", "Authorized to quote products with full OEM warranty and support."),
            ]
            oem_pdf_bytes = create_pdf_with_visuals(
                title="MANUFACTURER AUTHORIZATION FORM (MAF)",
                subtitle="OFFICIAL OEM DIRECT AUTHORIZATION LETTER",
                fields=oem_fields,
                notes_paragraph=f"We authorize the bidder to quote our products under code {acode} with full warranty.",
                signature_png_bytes=sig_oem,
                signatory_title=f"Authorised Signatory - {oem_name}",
            )

        sample_docs[("Technical / product-specific documents", "OEM authorization letter")] = (
            f"oem_authorization_{b_id}.pdf",
            oem_pdf_bytes,
        )

    # BIS / ISO Certificates
    certs = tech.get("bis_iso_certificates", [])
    if certs:
        cert_body = (
            f"QUALITY ACCREDITATIONS & STANDARDS CERTIFICATES\n"
            f"------------------------------------------------------------------\n"
            f"Entity: {name}\n\n"
        )
        for c in certs:
            std = c.get("standard", "ISO 9001:2015")
            vdate = c.get("valid_until", "2027-01-01")
            accred = c.get("accreditation", "NABCB")
            cert_body += f"- Standard: {std}\n  Valid Until: {vdate}\n  Accreditation Body: {accred}\n"

        sample_docs[("Technical / product-specific documents", "BIS certification / quality certificate")] = (
            f"quality_certificates_{b_id}.txt",
            cert_body.encode("utf-8"),
        )

    # Technical Spec Brochure
    tspec = tech.get("tech_spec_compliance_sheet")
    if tspec:
        matches = tspec.get("matches_tender_specs", True)
        mitigated = tspec.get("all_deviations_mitigated", True)

        if matches and mitigated:
            spec_body = (
                f"TECHNICAL SPECIFICATIONS COMPLIANCE MATRIX & PRODUCT BROCHURE\n"
                f"------------------------------------------------------------------\n"
                f"Model: Enterprise Standard Solution Series\n"
                f"Manufacturer: {name}\n"
                f"Compliance Statement: FULLY COMPLIANT WITH TENDER TECHNICAL SCHEDULE.\n"
                f"All technical deviations are fully mitigated without compromise.\n"
            )
        else:
            spec_body = (
                f"TECHNICAL SPECIFICATIONS COMPLIANCE SHEET (WITH DEVIATIONS)\n"
                f"------------------------------------------------------------------\n"
                f"Model: Standard Commercial Offering\n"
                f"Supplier: {name}\n"
                f"Compliance Statement: DEVIATIONS OBSERVED.\n"
                f"Note: Certain tender parameters deviate from requested specifications without mitigation.\n"
            )

        sample_docs[("Technical / product-specific documents", "Product technical specification sheet/brochure")] = (
            f"technical_specs_{b_id}.txt",
            spec_body.encode("utf-8"),
        )

    # Past Performance Proofs
    past_orders = tech.get("past_performance_proofs", [])
    if past_orders:
        perf_body = (
            f"PAST PERFORMANCE & EXPERIENCE COMPLETION CERTIFICATES\n"
            f"------------------------------------------------------------------\n"
            f"Vendor: {name}\n\n"
        )
        for po in past_orders:
            client = po.get("client", "Govt Entity")
            val_cr = po.get("order_val_cr", 1.0)
            status_po = po.get("status", "COMPLETED")
            perf_body += (
                f"- Client: {client}\n"
                f"  Order Value: INR {val_cr:.2f} Crores ({val_cr * 100:.2f} Lakhs)\n"
                f"  Execution Status: {status_po}\n"
                f"  Satisfactory Completion Certificate: Attached\n"
            )
        sample_docs[("Technical / product-specific documents", "Past performance / experience certificate")] = (
            f"past_performance_{b_id}.txt",
            perf_body.encode("utf-8"),
        )

    # -------------------------------------------------------------------------
    # 5. Compliance / Background Documents
    # -------------------------------------------------------------------------
    # Non-blacklisting declaration (PDF with signature)
    nb = comp.get("non_blacklisting_declaration")
    if nb:
        clean = nb.get("self_declared_clean", True)
        notarized = nb.get("notarized", True)

        nb_fields = [
            ("Deponent Entity", name),
            ("Clean Record Assertion", "Organization has never been blacklisted by any Central/State Ministry, GeM, or PSU" if clean else "Previously penalized / debarred record"),
            ("Notarization Status", "DULY NOTARIZED BEFORE NOTARY PUBLIC" if notarized else "UNNOTARIZED DRAFT COPY"),
            ("Legal Undertaking", "We solemnly affirm that the entity is eligible and not debarred under GFR Rule 151"),
        ]
        nb_pdf_bytes = create_pdf_with_visuals(
            title="UNDERTAKING & SELF-DECLARATION OF NON-BLACKLISTING",
            subtitle="AFFIDAVIT FOR TENDER COMPLIANCE BEFORE NOTARY PUBLIC",
            fields=nb_fields,
            notes_paragraph="Duly sworn affidavit submitted for GeM procurement compliance audit.",
            signature_png_bytes=sig_pan,
            signatory_title="Authorised Signatory - Deponent",
        )
        sample_docs[("Compliance / background documents", "Self-declaration of non-blacklisting")] = (
            f"non_blacklisting_{b_id}.pdf",
            nb_pdf_bytes,
        )

    return sample_docs
