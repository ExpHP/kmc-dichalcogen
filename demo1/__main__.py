#!/usr/bin

from __future__ import print_function

import sys
import argparse
from functools import partial

from .sim import KmcSim
from . import config

PROG = 'demo1'

def main():
	import logging

	parser = argparse.ArgumentParser('python -m ' + PROG, description='')

	parser.add_argument('CONFIG', nargs='+',
		type=argparse.FileType('r'),
		help='paths to config files')

	parser.add_argument('-d', '--dimensions', metavar='ARM,ZAG',
		type=delim_parser(positive_int, n=2, sep=','), default=[200,200],
		help='PBC grid dimensions as a number of unit cells in each dimension')

	parser.add_argument('-n', '--steps',
		type=positive_int, default=10000,
		help='stop after this many events')

	parser.add_argument('-P', '--output-pstats',
		help='record profiling data, readable by the pstats module')

	parser.add_argument('-p', '--profile',
		action='store_true',
		help='display profiling data')

	parser.add_argument('-D', '--debug',
		action='store_true',
		help='display debug logs, hide standard output')

	parser.add_argument('-T', '--temperature',
		type=float, default=None,
		help='temperature in kelvin. Only meaningful if config files specify'
		' barriers instead of rates.')

	parser.add_argument('--write-initial', metavar='PATH',
		help='write initial state to PATH')
	parser.add_argument('--embed-initial',
		action='store_true',
		help='embed initial state in output')

	group = parser.add_mutually_exclusive_group()
	group.add_argument('--no-incremental',
		dest='incremental', action='store_false',
		help='disable incremental updates (debugging flag)')

	group.add_argument('--validate-every', metavar='NSTEP',
		type=nonnegative_int, default=0,
		help='do incremental updates, but perform an expensive validation '
		'of all objects every NSTEP steps. (debugging flag)')

	group = parser.add_mutually_exclusive_group()
	group.add_argument('--zobrist-bits', metavar='NBITS',
		type=positive_int, default=None,
		help='Experimental flag. Computes and prints zobrist keys with this '
		'many bits of randomness.')

	group.add_argument('--zobrist-hash',
		action='store_true',
		help='Experimental flag. Computes and prints deterministic zobrist '
		'keys using hash(). ')

	args = parser.parse_args()

	if args.debug:
		logging.getLogger().setLevel(10)

	config_dict = config.load_all(args.CONFIG)

	# bind arguments for ease of wrapping with profiler...
	def myrun():
		from .state import HASH
		run(
			ofile = DevNull() if args.debug else sys.stdout,
			nsteps = args.steps,
			dims = args.dimensions,
			config_dict = config_dict,
			validate_every = args.validate_every,
			incremental = args.incremental,
			save_initial_path = args.write_initial,
			embed_initial = args.embed_initial,
			temperature = args.temperature,
			zobrist = HASH if args.zobrist_hash else args.zobrist_bits,
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

# The long explicit argument list is deliberate; if this thing took
#  the 'args' object it would be impossible to lint for unused vars.
# That said, perhaps the function needs to be broken up.
def run(ofile, nsteps, dims, config_dict, validate_every, incremental, save_initial_path, embed_initial, temperature, zobrist):
	from .util import intersperse
	import json

	cfg = config.from_dict(config_dict)

	init_state = cfg['state_gen_func'](dims, zobrist=zobrist)
	if save_initial_path:
		with open(save_initial_path, 'w') as f:
			json.dump(init_state.to_dict(), f)

	sim = KmcSim(init_state, cfg['rule_specs'], incremental=incremental, temperature=temperature)

	def maybe_do_validation(steps_done):
		if not validate_every: return
		if not steps_done > 0: return
		if not steps_done % validate_every == 0: return
		sim.validate()

	# to write json incrementally we'll need to do a bit ourselves
	with write_enclosing('{', '\n}', ofile):
		def write_key_val(key, val, end=',\n', pretty=True, **kw):
			ofile.write('"%s": ' % key)
			json.dump(val, ofile, indent=2 if pretty else None, **kw)
			ofile.write(end)

		write_key_val('grid', grid_info(dims))
		write_key_val('config', config_dict)
		write_key_val('temperature', temperature, pretty=False)
		write_key_val('rates', sim.rates_info(), sort_keys=True)
		if embed_initial:
			write_key_val('initial_state', init_state.to_dict(), pretty=False)

		with write_enclosing(' "events": [\n  ', '\n ]', ofile):
			# everything here is done with iterators for the sake of
			# incremental output
			infos = (sim.perform_random_move() for _ in range(nsteps))
			strs = (json.dumps(x, sort_keys=True) for x in infos)
			for n,s in enumerate(intersperse(',\n  ', strs)):
				ofile.write(s)

				# somewhat silly HACK to recover step number
				if n%2 == 0: # only perform after writing step (not comma)
					maybe_do_validation(steps_done = n//2 + 1)

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
