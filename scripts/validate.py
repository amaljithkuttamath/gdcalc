"""Compatibility entry point for skill runners."""
import sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'src'))
from gdcalc.validate import main

if __name__=='__main__':sys.exit(main())
