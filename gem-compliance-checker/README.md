# GeM Bid Compliance & Document Verification Engine (SIH 26100)

Dual-dashboard AI and rule-based compliance evaluation architecture for Government e-Marketplace (GeM) tenders:
- **Bidder Portal (`bidder_dashboard.py`)**: Vendor document upload desk across 5 categories, metadata tracking, and submission.
- **Officer Dashboard (`dashboard.py`)**: Tender qualification criteria manager, 14-document OCR & compliance verification matrix, prominent risk scoring, and officer adjudication audit logging.
- **Shared SQLite Database (`bidder_documents.db`)**: Real-time synchronization of uploads (`documents`) and officer decisions (`audit_log`).

---

## How to Run the Dashboards

### 1. Officer Evaluation Dashboard (Port 8501)
Run the officer evaluation interface:
```bash
streamlit run gem-compliance-checker/dashboard.py --server.port 8501
```
Or directly:
```bash
python gem-compliance-checker/dashboard.py
```
Open in browser: `http://localhost:8501`

### 2. Bidder Document Upload Portal (Port 8502)
In a second terminal, run the vendor submission portal:
```bash
streamlit run gem-compliance-checker/bidder_dashboard.py --server.port 8502
```
Or directly:
```bash
python gem-compliance-checker/bidder_dashboard.py
```
Open in browser: `http://localhost:8502`

---

## Verification Pipeline & Testing
To execute the automated end-to-end unit tests covering the shared database, 14 document evaluators, tender criteria toggling, score calculations, and audit logs:
```bash
python gem-compliance-checker/test_dual_pipeline.py
```
