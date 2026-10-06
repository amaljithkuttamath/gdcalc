"""Validate MCDX package integrity; does not execute Mathcad."""
import argparse
import json
import sys
if __package__:
    from . import mcdx
else:
    import mcdx  # type: ignore[no-redef]


def main(argv=None,prog=None):
    parser=argparse.ArgumentParser(prog=prog,description=__doc__)
    parser.add_argument('worksheet')
    args=parser.parse_args(argv)
    try:print(json.dumps(mcdx.validate(args.worksheet),indent=2))
    except (ValueError,OSError,mcdx.E.XMLSyntaxError,mcdx.zipfile.BadZipFile) as exc:
        print('mcdxkit: '+str(exc),file=sys.stderr);return 2
    return 0


if __name__=='__main__':sys.exit(main())
