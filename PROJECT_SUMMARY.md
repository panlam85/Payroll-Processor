# Payroll Processor - Mac Application

## 🎯 Project Summary

You now have a complete **standalone Mac application** for processing Greek payroll documents! The application features a modern drag-and-drop interface and generates comprehensive Excel reports.

## 🧰 CLI Automation (v3.1.3)

The v3.1.3 release adds a single CLI entry point that can both run processing and query past runs.

### Run processing
```
./payroll_cli.sh run --zips /path/to/zips --out ~/Documents/Payroll\ Processor\ Reports/Employees\ Reports
```

### Dry run (validate inputs only)
```
./payroll_cli.sh run --zips /path/to/zips --dry-run
```

### Query run history
```
./payroll_cli.sh query latest
./payroll_cli.sh query list --limit 10
./payroll_cli.sh query by-id --id <run_id>
```

### Run ledger
- Ledger entries are stored as JSON under `~/Documents/Payroll Processor Reports/.run_ledger/`.
- Each entry captures inputs, outputs, metrics, status, and timestamps.

## 📦 What Was Created

### **Versioned Source Tree**
- `versions/v1.0/` … `versions/v3.1.5/` – frozen historical iterations, retained for reference
- `versions/v3.1.7/` – **active** source, scripts, docs and resources
- Root-level helper scripts (`launch_gui.sh`, `run_dev.sh`, `payroll_cli.sh`, `create_simple_app.py`, `create_simple_installer.sh`) delegate to `versions/v3.1.7` so you always run the latest code while keeping older releases intact.
- Use `./bump_version.sh vX.Y.Z` to cut a new version; it copies the active tree and repoints the root wrappers, `pytest.ini`, and `.coveragerc`.

### **Core Application Files (v3.1.7):**
- `versions/v3.1.7/src/payroll_gui.py` – GUI shell, sidebar views (Dashboard, Analytics, Insurance, Employees, Processing, Database, Settings), menus, and report orchestration
- `versions/v3.1.7/src/process_payroll.py` – PDF extraction and payroll/insurance/receipt parsing
- `versions/v3.1.7/src/db_storage.py` – PostgreSQL schema, migrations, imports, exports, and backup/restore
- `versions/v3.1.7/src/create_employee_reports.py` – Excel report generation (per-employee workbook + analytical detail workbook)
- `versions/v3.1.7/src/payroll_cli.py` – CLI entry point for headless runs and run-ledger queries
- `versions/v3.1.7/resources/app_icon.icns` – Custom application icon
- `versions/v3.1.7/requirements.txt` – Python dependencies for the GUI and bundler
- `versions/v3.1.7/scripts/*.sh|py` – Launchers, development runner, bundle and installer builders

### **Standalone Mac App:**
- `dist/Payroll Processor.app` - Bundle generated from v3.1.7 sources
- Universal binary (works on Intel and Apple Silicon Macs)
- Self-contained with all dependencies included
- Note: `dist/` and `releases/` are gitignored and are not present in a fresh clone — run the build scripts to produce them.

### **Development Tools:**
- `launch_gui.sh` – Wrapper that selects a Tk-capable Python, maintains a requirement-hashed runtime cache inside `versions/v3.1.7`, and launches the GUI
- `run_dev.sh` – Same launcher but with extra debug output and zero-friction restarts
- `payroll_cli.sh` – Headless processing and run-ledger queries
- `create_simple_app.py` – Simple Mac bundle builder that copies the active sources
- `create_simple_installer.sh` – Builds ZIP/DMG installers from the bundle
- Prior versions remain checked in for reference/testing

### **Tests:**
```bash
versions/v3.1.7/.venv/bin/python -m pytest -q                    # 354 tests
versions/v3.1.7/.venv/bin/python -m pytest -q --cov --cov-config=.coveragerc
```
Coverage gate is 65%; the parsing/storage/CLI core currently sits at 93.41%. `payroll_gui.py` is excluded from the gate; its display-independent helpers are covered by `tests/test_payroll_gui_helpers.py`.

## 🚀 How to Use

### **For End Users:**

1. **Install the Application:**

   `releases/` is gitignored, so build it first if it is not present:
   ```bash
   ./create_simple_app.py           # builds dist/Payroll Processor.app
   ./create_simple_installer.sh     # builds releases/v3.1.7/ artifacts
   ```
   Then install:
   ```bash
   # Option 1: Use the installer
   open releases/v3.1.7/PayrollProcessor_Installer/
   # Double-click "Install Payroll Processor.command"

   # Option 2: Mount the DMG directly
   open releases/v3.1.7/PayrollProcessor_v3.1.7_macOS.dmg
   # Drag app to Applications folder
   ```

2. **Launch the Application:**
   - Find "Payroll Processor" in Applications folder
   - Or search in Launchpad
   - Or double-click the app icon

3. **Process Payroll Files:**
   - Drag ZIP files containing payroll PDFs into the app
   - Or click "Browse" to select files
   - Click "Generate Reports" 
   - The app saves two Excel files automatically to `~/Documents/Payroll Processor Reports`
     (one per-employee summary, one analytical detail list)
   - Wait for processing to complete; the status text shows both destination paths

### **For Developers:**

```bash
# Quick development testing (uses versions/v3.1.7 automatically)
./run_dev.sh

# Build/refresh the macOS bundle in dist/
./create_simple_app.py

# Generate installer artifacts in releases/v3.1.7/
./create_simple_installer.sh

# Cut a new version and repoint the root wrappers
./bump_version.sh v3.1.7
```

## ✨ Key Features

### **User Interface:**
- ✅ **Drag-and-Drop Support** - Drop ZIP files directly
- ✅ **File Browser** - Alternative file selection method
- ✅ **Progress Tracking** - Real-time progress bar and status
- ✅ **Multi-file Processing** - Handle multiple ZIP files at once
- ✅ **Error Handling** - Graceful error messages and recovery
- ✅ **Auto-Save Folder Indicator** - GUI tells you exactly where Excel files are stored

### **Document Processing:**
- ✅ **Greek Language Support** - Handles Greek text and characters
- ✅ **Multiple Document Types:**
  - Regular payslips (`ΑΠΟΔΕΙΞΕΙΣ ΠΛΗΡΩΜΩΝ`)
  - Vacation allowances (`ΕΠΙΔΟΜΑ ΑΔΕΙΑΣ`)
  - Christmas/Easter bonuses (`ΔΩΡΟ`)
  - Unused leave compensation (`ΑΠΟΖΗΜΙΩΣΗ`)
- ✅ **Data Extraction:**
  - Employee codes and names
  - Basic salary and total earnings
  - Net pay amounts
  - EFKA/TEKA contributions (employee & employer)
  - Payment dates

### **Report Generation:**
- ✅ **Excel Output** - Professional formatted spreadsheets
- ✅ **Per-Employee Sheets** - Separate sheet for each employee
- ✅ **Monthly Summaries** - Grouped by month and document type
- ✅ **Currency Formatting** - Proper Euro formatting
- ✅ **Automatic Totals** - Monthly totals across document types
- ✅ **Analytical Detail Workbook** - Second Excel file listing every payroll entry with its source archive/PDF

## 🔧 System Requirements

- **macOS:** 10.12 (Sierra) or later
- **Architecture:** Universal (Intel x64 + Apple Silicon ARM64)
- **Dependencies:** 
  - `pdftotext` utility (install with `brew install poppler`)
  - All Python dependencies are bundled in the app

## 📁 File Structure

```
payment processor/
├── versions/
│   ├── v1.0/ … v3.1.6/    # Older code paths retained for reference
│   └── v3.1.7/            # Active codebase (src/scripts/resources/docs/tools/tests)
├── dist/                  # Generated “Payroll Processor.app” (gitignored)
├── releases/              # Distributables: ZIP/DMG/Installer (gitignored)
├── launch_gui.sh          # Wrapper → versions/v3.1.7/scripts/launch_gui.sh
├── run_dev.sh             # Wrapper → versions/v3.1.7/scripts/run_dev.sh
├── payroll_cli.sh         # Wrapper → versions/v3.1.7/scripts/payroll_cli.sh
├── create_simple_app.py   # Wrapper → versions/v3.1.7/scripts/create_simple_app.py
├── create_simple_installer.sh  # Wrapper → versions/v3.1.7/scripts/create_simple_installer.sh
└── bump_version.sh        # Cuts a new version from the active one
```

## 🎉 Success Metrics

✅ **Complete GUI Application** - Modern, user-friendly interface  
✅ **Standalone Mac App** - No Python installation required  
✅ **Professional Installer** - Easy distribution and installation  
✅ **Drag-and-Drop Support** - Intuitive user experience  
✅ **Progress Tracking** - Real-time feedback during processing  
✅ **Error Handling** - Robust error management  
✅ **Documentation** - Complete user and developer guides  
✅ **Cross-Architecture** - Works on Intel and Apple Silicon Macs  

## 🚀 Next Steps

The application is **production-ready** and can be distributed to users. You can:

1. **Share the DMG file** for easy installation
2. **Customize the interface** by modifying `payroll_gui.py`
3. **Add new features** by extending the processing logic
4. **Create app store version** with proper code signing
5. **Add automatic updates** using frameworks like Sparkle

The payroll processor has been transformed from command-line scripts into a **professional Mac application** ready for business use! 🎯
