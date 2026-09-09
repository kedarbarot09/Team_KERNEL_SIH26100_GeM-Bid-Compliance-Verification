# GeM Bid Compliance & Document Verification Engine (SIH 26100)

Automated compliance verification pipeline combining OCR ingestion, dual-layer entity extraction (Regex + Gemini LLM), simulated government portal validation, deterministic tender clause rules, and risk scoring.

## How to Run the Dashboard

### Option 1: VS Code "Run and Debug" (F5)
1. Open the project in VS Code.
2. Go to the **Run and Debug** panel (`Ctrl+Shift+D` / `Cmd+Shift+D`).
3. Select **Streamlit: Debug Dashboard** and press `F5` (or click the green Play button).
4. Breakpoints set inside `dashboard.py` and `app/` will be hit as normal.

### Option 2: Run Python File Directly
You can run `dashboard.py` directly using Python:
```bash
python gem-compliance-checker/dashboard.py
```
*(The script automatically detects direct execution and bootstraps the Streamlit server).*

### Option 3: Standard Streamlit CLI
Run via the virtual environment's Streamlit CLI:
```bash
streamlit run gem-compliance-checker/dashboard.py
```
Or:
```bash
python -m streamlit run gem-compliance-checker/dashboard.py
```

The dashboard will open in your browser at `http://localhost:8501`.
