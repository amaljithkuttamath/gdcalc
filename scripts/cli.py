"""Run the CLI from a source checkout without installing it."""
import sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'src'))
from gdcalc.cli import main

if __name__=='__main__':sys.exit(main())
