"""Installed `mcdxkit` command, also runnable as `python scripts/cli.py`."""
import argparse
import sys
if __package__:
    from . import generate, validate
else:
    import generate  # type: ignore[no-redef]
    import validate  # type: ignore[no-redef]


def main(argv=None):
    args=list(sys.argv[1:] if argv is None else argv)
    parser=argparse.ArgumentParser(prog='mcdxkit',description='Convert final GROUP local-load summaries to native Mathcad worksheets.')
    parser.add_argument('--version',action='version',version='mcdxkit 0.3.0')
    sub=parser.add_subparsers(dest='command',required=True)
    for name,description in [('inspect','Inspect local loads and strength case selection'),
                             ('convert','Generate and calculate open and Mathcad worksheets'),
                             ('setup-engine','Install the required local CalcpadCE calculator'),
                             ('validate','Check an .mcdx package without executing Mathcad'),
                             ('serve','Start the local browser interface'),
                             ('batch','Convert files or folders with parallel workers and resume'),
                             ('summary','Write a CSV of per-case loads for several reports or output directories'),
                             ('standards','Create or inspect a versioned engineering provenance register')]:
        sub.add_parser(name,help=description,add_help=False)
    selected,rest=parser.parse_known_args(args)
    if selected.command=='standards':
        from .standards import main as standards
        return standards(rest)
    if selected.command=='setup-engine':
        from .setup_engine import main as setup
        return setup(rest)
    if selected.command=='batch':
        from .batch import main as batch
        return batch(rest)
    if selected.command=='summary':
        from .summary import main as summary
        return summary(rest)
    if selected.command=='serve':
        from .server import main as serve
        return serve(rest)
    if selected.command=='convert':return generate.main(rest,prog='mcdxkit convert')
    if selected.command=='inspect':return generate.main(rest+['--inspect'],prog='mcdxkit inspect')
    return validate.main(rest,prog='mcdxkit validate')


if __name__=='__main__':sys.exit(main())
