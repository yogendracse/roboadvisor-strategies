import sys
from pathlib import Path

# Add backend to path so we can import from analysis
sys.path.append(str(Path(__file__).resolve().parent.parent))

import yaml
from analysis.sensitivity_regression import SensitivityRegressor

def main():
    config_path = Path(__file__).resolve().parent.parent / "config" / "overlay.yaml"
    with open(config_path) as f:
        overlay_cfg = yaml.safe_load(f) or {}
    reg = SensitivityRegressor(overlay_cfg)
    
    print("Running FRED proxy regression (2015-2025)...")
    fred_results = reg.run_all("2015-01-01", "2025-09-01", window="fred_proxy")
    
    print("Running Polymarket live window regression (Sep 2025 - Apr 2026)...")
    pm_results = reg.run_all("2025-09-01", "2026-04-23", window="polymarket")
    
    print("Generating report and plots...")
    report_text = reg.generate_report(fred_results, pm_results)
    
    print("Report generation complete.")

if __name__ == "__main__":
    main()
