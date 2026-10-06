"""Installed `gdcalc` command, also runnable as `python scripts/cli.py`."""
import argparse
import sys
if __package__:
    from . import generate, validate
else:
    import generate
    import validate


def main(argv=None):
    args=list(sys.argv[1:] if argv is None else argv)
    parser=argparse.ArgumentParser(prog='gdcalc',description='Convert final GROUP local-load summaries to native Mathcad worksheets.')
    parser.add_argument('--version',action='version',version='gdcalc 0.1.0')
    sub=parser.add_subparsers(dest='command',required=True)
    for name,description in [('inspect','Inspect local loads and strength case selection'),
                             ('convert','Generate a native .mcdx and source audit'),
                             ('validate','Check an .mcdx package without executing Mathcad')]:
        sub.add_parser(name,help=description,add_help=False)
    selected,rest=parser.parse_known_args(args)
    if selected.command=='convert':return generate.main(rest,prog='gdcalc convert')
    if selected.command=='inspect':return generate.main(rest+['--inspect'],prog='gdcalc inspect')
    return validate.main(rest,prog='gdcalc validate')


if __name__=='__main__':sys.exit(main())
