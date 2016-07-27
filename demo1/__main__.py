#!/usr/bin

from __future__ import print_function

import sys
import argparse
from functools import partial

from .state import State
from .state import EventManager
from . import kmc
from . import config

PROG = 'demo1'

def main():
	import logging

	parser = argparse.ArgumentParser('python -m ' + PROG, description='')


	parser.add_argument('CONFIG', type=argparse.FileType('r'),
		help='path to config file')
	parser.add_argument('-d', '--dimensions', metavar='ARM,ZAG',
		default=[50,50],
		type=delim_parser(positive_int, n=2, sep=','),
		help='PBC grid dimensions as a number of unit cells in each dimension')
	parser.add_argument('-n', '--steps', type=positive_int, default=20,
		help='stop after this many events')
	parser.add_argument('-P', '--output-pstats',
		help='record profiling data, readable by the pstats module')
	parser.add_argument('-p', '--profile', action='store_true',
		help='display profiling data')
	parser.add_argument('-D', '--debug', action='store_true',
		help='display debug logs, hide standard output')
	parser.add_argument('-g', '--gold-standard', action='store_true',
		help='use gold standard ruleset (debugging flag)')
	args = parser.parse_args()

	if args.debug:
		logging.getLogger().setLevel(10)

	# FIXME now that I think about it why is GoldStandard implemented through a class hack?
	global KmcSim
	if args.gold_standard:
		from .state import GoldStandardRuleSet as KmcSim
	else:
		from .state import RuleSet as KmcSim

	import yaml
	config_dict = yaml.load(args.CONFIG)

	# bind arguments for ease of wrapping with profiler...
	def myrun():
		run(
			ofile = DevNull() if args.debug else sys.stdout,
			nsteps = args.steps,
			dims = args.dimensions,
			config_dict = config_dict,
		)

	if args.output_pstats or args.profile:
		stats_out = args.output_pstats
		text_out = sys.stderr if args.profile else None
		with_profiling(myrun, stats_out, text_out)
	else:
		myrun()

class DevNull:
	def write(self, *a, **kw): pass

#-----------------------------

def run(ofile, nsteps, dims, config_dict):
	import json

	cfg = config.from_dict(config_dict)

	event_manager = EventManager()
	init_state = State(dims, emit=event_manager.emit)
	sim = KmcSim(init_state, cfg['rule_specs'], event_manager)

	# to write json incrementally we'll need to do a bit ourselves
	with write_enclosing('{', '\n}', ofile):
		ofile.write('"grid": ')
		json.dump(grid_info(dims), ofile, indent=2)
		ofile.write(',\n')

		ofile.write('"config": ')
		json.dump(config_dict, ofile, indent=2)
		ofile.write(',\n')

		with write_enclosing(' "events": [\n  ', '\n ]', ofile):
			# everything here is done with iterators for the sake of
			# incremental output
			infos = (sim.perform_random_move() for _ in range(nsteps))
			strs = (json.dumps(x, sort_keys=True) for x in infos)
			for s in with_separator(',\n  ', strs):
				ofile.write(s)

	ofile.write('\n')

class write_enclosing:
	'''
	Context manager that writes strings to a file.

	Writes strings when the block is entered & exited, be it cleanly
	or via an exception. For a computation that streams structured
	output (XML, JSON, ...), this may result in a more easily
	salvagable output file if the computation is interrupted.
	(just don't bet your life on it)
	'''
	def __init__(self, start, end, file):
		self.file = file
		self.start = start
		self.end = end
	def __enter__(self): self.file.write(self.start)
	def __exit__(self, *args): self.file.write(self.end)

def with_separator(separator, iterable):
	'''
	Turns ``[a,b,c,d,...e,f]`` into ``[a,x,b,x,...e,x,f]``.
	'''
	it = iter(iterable)
	first = next(it)
	yield first
	for x in it:
		yield separator
		yield x

def grid_info(dims):
	return {
		'lattice_type': 'hexagonal',
		'coord_format': 'axial',
		'dim': dims,
	}

#-----------------------------

# Because this script is run via -m, we cannot do "-m cProfile".
# Hence profiling is provided as a flag.
def with_profiling(f, stats_out=None, text_out=None):
	try: from cProfile import Profile
	except: from profile import Profile
	from pstats import Stats
	prof = Profile()

	prof.enable()
	retval = f()
	prof.disable()

	if stats_out:
		try:
			prof.dump_stats(stats_out)
		except (IOError,OSError) as e: # not worth losing our return value over
			warn('could not write pstats (%s)', e)
	if text_out:
		try:
			MAX_LINES = 20
			stats = Stats(prof, stream=text_out)
			stats.sort_stats('cumtime')
			stats.print_stats(MAX_LINES)
		except (IOError,OSError) as e:
			warn('could not write profiling summary (%s)', e)
	return retval

#-----------------------------
# argparse argument types

def int_with_min(min, errmsg, s):
	x = int(s)
	if x < min:
		raise argparse.ArgumentTypeError('%s: %d' % (errmsg, x))
	return x
positive_int = partial(int_with_min, 1, 'Not a positive integer')
nonnegative_int = partial(int_with_min, 0, 'Not a non-negative integer')

def delim_parser(typ, n=None, sep=','):
	def inner(s):
		toks = s.split(',')
		xs = []
		for t in toks:
			try: xs.append(typ(t))
			except ValueError: raise argparse.ArgumentTypeError(
				'Bad %s value: %r' % (typ.__name__, t))

		if n not in (None, len(xs)):
			raise argparse.ArgumentTypeError(
				'Expected %d arguments separated by %r; got %d'
				% (n, sep, len(xs))
			)
		return xs
	return inner

#-----------------------------

def say(msg, *args, **kw):     print(msg.format(*args, **kw), file=sys.stdout)
def say_err(msg, *args, **kw): print('%s: %s' % (PROG, msg.format(*args, **kw)), file=sys.stderr)

def warn(msg, *args, **kw):
	say_err('Warning: ' + msg, *args, **kw)

def die(msg, *args, **kw):
	say_err('FATAL: ' + msg, *args, **kw)
	say_err('Aborting.')
	sys.exit(1)

#-----------------------------

main()
