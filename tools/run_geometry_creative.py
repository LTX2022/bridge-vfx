#!/usr/bin/env python3
"""从最终安装runtime准备或运行有界几何作业；不代写模型计划。"""
from pathlib import Path
import argparse,json,sys
ROOT=Path(__file__).resolve().parents[1]
for name in ('dcc-task-runtime','houdini-bridge','nuke-bridge','vfx-pipeline'):
    sys.path.insert(0,str(ROOT/'packages'/name/'src'))

def main():
    parser=argparse.ArgumentParser();commands=parser.add_subparsers(dest='command',required=True)
    p=commands.add_parser('prepare');p.add_argument('--output',type=Path,required=True);p.add_argument('--source-preparation',type=Path,required=True)
    p.add_argument('--reference-front',type=Path,required=True);p.add_argument('--reference-perspective',type=Path,required=True);p.add_argument('--criteria',type=Path,required=True);p.add_argument('--instruction',required=True)
    p=commands.add_parser('run-job');p.add_argument('--job',type=Path,required=True)
    p=commands.add_parser('execute-job');p.add_argument('--job',type=Path,required=True)
    args=parser.parse_args()
    from vfx_pipeline.geometry_job import prepare_project,run_job
    if args.command=='prepare':
        result=prepare_project(args.output.resolve(),args.source_preparation.resolve(),args.reference_front.resolve(),args.reference_perspective.resolve(),args.criteria.resolve(),instruction=args.instruction)
        print(json.dumps(result,ensure_ascii=False))
    else:run_job(args.job,execute=args.command=='execute-job')
if __name__=='__main__':main()
