"""Same stdlib sandbox runner inside a configured existing local container.

The coordinator passes metadata through a private mounted file, prompt on stdin,
and cancellation through a private marker. No model credentials are copied.
"""
import argparse
import json
import os
from pathlib import Path
import sys

sys.path.insert(0,str(Path(__file__).resolve().parents[2]))
from agent_hub.engine.process import sandbox,run_command


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--request',required=True)
    args=parser.parse_args()
    path=Path(args.request)
    if not path.is_absolute() or path.stat().st_size>1024*1024:
        raise ValueError('Invalid container execution descriptor')
    request=json.loads(path.read_text())
    cancellation=Path(request['cancel'])
    command=sandbox(request['argv'],request['workspace'],request['writable'],request['network'],
                    request['runtime_paths'],source_workspace=request['source_workspace'],
                    aliases=request['aliases'],common_directory=request['common_directory'],inherited_proc=True)
    result=run_command(command,request['source_workspace'],sys.stdin.read(1024*1024),
                       request['timeout'],cancelled=cancellation.exists,environment=request.get('environment'))
    # Acknowledgement contains no prompt, credentials or model output.
    Path(request['complete']).write_text('finished\n')
    print(json.dumps(result,ensure_ascii=False))
    return 0


if __name__=='__main__':
    try:
        sys.exit(main())
    except (ValueError,OSError,KeyError) as error:
        print(str(error),file=sys.stderr)
        sys.exit(1)
