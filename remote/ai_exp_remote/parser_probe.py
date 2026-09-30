"""Read an isolated argparse definition without importing training dependencies."""
import argparse
import ast
import math
import os
import warnings
from pathlib import Path


def namespace(path, entrypoint="train.py", parser_function="build_parser"):
    path = Path(path)
    source = (path / entrypoint).resolve()
    if path.resolve() not in source.parents: raise ValueError('entrypoint 必须位于项目目录内')
    tree = ast.parse(source.read_text())
    names = {parser_function}
    scope = {'argparse': argparse, 'math': math, 'os': os, 'warnings': warnings}
    def str2bool(value):
        if isinstance(value, bool): return value
        if str(value).lower() in {'true','1','yes','y','on'}: return True
        if str(value).lower() in {'false','0','no','n','off'}: return False
        raise argparse.ArgumentTypeError('invalid boolean')
    scope['str2bool'] = str2bool
    for node in tree.body:
        if isinstance(node, ast.Assign):
            try: value = ast.literal_eval(node.value)
            except (ValueError, TypeError): continue
            for target in node.targets:
                if isinstance(target, ast.Name): scope[target.id] = value
    functions = [n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name in names]
    future = ast.ImportFrom(module='__future__', names=[ast.alias(name='annotations')], level=0)
    module = ast.fix_missing_locations(ast.Module(body=[future, *functions], type_ignores=[]))
    exec(compile(module, str(source), 'exec'), scope)
    if parser_function not in scope: raise ValueError('源码没有 ' + parser_function)
    return scope


def fields(path, entrypoint="train.py", parser_function="build_parser"):
    parser = namespace(path, entrypoint, parser_function)[parser_function]()
    result = []
    for group in parser._action_groups:
        for action in group._group_actions:
            if action.dest == 'help' or not action.option_strings: continue
            typ = getattr(action.type, '__name__', '')
            kind = 'integer' if action.type is int else 'number' if action.type is float else 'boolean' if typ in {'str2bool','bool'} or isinstance(action,(argparse._StoreTrueAction,argparse._StoreFalseAction)) else 'string'
            result.append(dict(key=action.dest,flags=action.option_strings,kind=kind,nullable=action.default is None,has_default=not action.required and action.default != argparse.SUPPRESS,default=None if action.default == argparse.SUPPRESS else action.default,required=action.required,choices=list(action.choices) if action.choices else None,group=group.title,help=action.help or '',constraints={},action=type(action).__name__))
    return result


def resolve(path, argv, entrypoint="train.py", parser_function="build_parser"):
    scope = namespace(path, entrypoint, parser_function)
    return vars(scope[parser_function]().parse_args(argv))
