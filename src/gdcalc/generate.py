"""CLI: GROUP final local summary -> native Mathcad input/formula worksheet."""
import argparse
import json
import os
import sys
from pathlib import Path
from . import engine, mcdx


def case_ids(value):
    try:
        result=[]
        for word in value.split(','):
            if '-' in word:
                first,last=map(int,word.split('-'))
                if last<first or last-first>100:raise ValueError
                result.extend(range(first,last+1))
            else:result.append(int(word))
        if any(i<1 for i in result) or len(set(result))!=len(result):raise ValueError
        return result
    except ValueError:raise argparse.ArgumentTypeError('Use unique positive cases, e.g. 1-10 or 1,3,7') from None


def default_template():
    """Resolve explicit, checkout, generic user and legacy template locations."""
    if os.environ.get('GDCALC_TEMPLATE'):
        return Path(os.environ['GDCALC_TEMPLATE'])
    home = Path.home()
    generic = Path(os.environ.get('XDG_CONFIG_HOME', str(home / '.config'))) / 'gdcalc/reference.mcdx'
    candidates = (
        Path(__file__).resolve().parents[2] / 'assets/local/reference.mcdx',
        generic,
        home / '.agents/skills/gdcalc/assets/local/reference.mcdx',
        Path(os.environ.get('CODEX_HOME', str(home / '.codex'))) / 'skills/gdcalc/assets/local/reference.mcdx',
    )
    return next((path for path in candidates if path.is_file()), generic)


def main(argv=None,prog=None):
    parser=argparse.ArgumentParser(prog=prog,description=__doc__)
    parser.add_argument('input',type=Path,help='GROUP .gp11t or text report, in kip/in units')
    parser.add_argument('--template',type=Path,default=default_template(),help='Compatible .mcdx template; also GDCALC_TEMPLATE or installed private template')
    parser.add_argument('--output',type=Path,help='New .mcdx output path (never overwritten)')
    parser.add_argument('--inspect',action='store_true',help='Inspect case selection and load envelopes without generating')
    parser.add_argument('--cases',type=case_ids,help='Explicit strength case IDs; default detects STR case names')
    parser.add_argument('--load-source',choices=['effects','reactions'],default='effects',help='Use local pile effects (default) or local pile-top reactions for shear/moments')
    parser.add_argument('--title',help='Title on generated source pages; template header remains unchanged')
    parser.add_argument('--set',action='append',default=[],metavar='VARIABLE=VALUE',help='Override a single literal template input, retaining its units')
    args=parser.parse_args(argv)
    try:
        if args.inspect:
            print(json.dumps(engine.inspect_report(args.input,cases=args.cases,load_source=args.load_source),indent=2))
            return 0
        if args.output is None:raise ValueError('--output is required unless using --inspect')
        overrides={}
        for assignment in args.set:
            key,value=assignment.split('=',1)
            if key in overrides:raise ValueError('Duplicate override: '+key)
            overrides[key]=float(value)
        result=engine.convert(args.input,args.template,args.output,cases=args.cases,load_source=args.load_source,title=args.title,overrides=overrides)
        print(json.dumps({'output':result['output'],'audit':result['audit'],'cases':result['cases'],
                          'envelope':result['envelope'],'open_worksheet':result['open_worksheet'],
                          'calculated_worksheet':result['calculated_worksheet'],
                          'calculation':{k:result['calculation'][k] for k in ('engine','calculated','translated_math_regions')},
                          'native_execution_verified':False},indent=2))
        return 0
    except (ValueError,OSError,KeyError,IndexError,mcdx.E.XMLSyntaxError,mcdx.zipfile.BadZipFile) as exc:
        print('gdcalc: '+str(exc),file=sys.stderr);return 2


if __name__=='__main__':sys.exit(main())
