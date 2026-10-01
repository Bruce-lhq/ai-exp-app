"""Frozen CLI and desktop bootstrap. Runtime data never lives in the bundle."""
import os
from pathlib import Path
import sys

if getattr(sys,'frozen',False):
    os.environ.setdefault('AI_EXP_WEB_ROOT',str(Path(sys._MEIPASS)/'web'))

from ai_exp_app.cli import main

if __name__ == '__main__':
    if sys.argv[1:] == ['--prepare-install']:
        from ai_exp_app.native import prepare_installation
        try:
            prepare_installation()
        except (OSError,RuntimeError,ValueError,KeyError) as exc:
            print(str(exc),file=sys.stderr)
            raise SystemExit(3)
        raise SystemExit(0)
    raise SystemExit(main())
