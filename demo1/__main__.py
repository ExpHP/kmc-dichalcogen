import sys
import argparse
from functools import partial

from .simple import SimpleState as State
from . import kmc

PROG = 'demo1'

def main():
	parser = argparse.ArgumentParser('python -m ' + PROG, description='')

	parser.add_argument('-o', '--output-raw')
	parser.add_argument('-d', '--dimensions', metavar='ARM,ZAG',
		default=[50,50],
		type=delim_parser(positive_int, n=2, sep=','),
		help='PBC grid dimensions '
		' as # chalcogenides in the armchair/zigzag directions.')
	parser.add_argument('-n', '--steps', default=20, help='stop after this many events')
	parser.add_argument('-P', '--output-pstats', help='record profiling data, '
		'readable by the pstats module')
	parser.add_argument('-p', '--profile', action='store_true', help='display profiling data')
	args = parser.parse_args()

	def myrun():
		run(
			ofile = args.output_raw or sys.stdout,
			nsteps = args.steps,
			dims = args.dimensions,
		)

	if args.output_pstats or args.profile:
		stats_out = args.output_pstats
		text_out = args.profile and sys.stderr
		with_profiling(myrun, stats_out, text_out)
	else:
		myrun()

#-----------------------------

def run(ofile, nsteps, dims):
	import json
	state = State(dims)
	for _ in range(nsteps):
		performer = kmc.weighted_choice(state.edges())
		info = performer(state) # warning: this mutates state
		json.dump(info, ofile, sort_keys=True)
		ofile.write('\n')
		ofile.flush()

#-----------------------------

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
