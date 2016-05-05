import sys

from .simple import SimpleState as State
from . import kmc

def main():
	import argparse
	parser = argparse.ArgumentParser(description='')
	parser.add_argument('-o', '--output-raw')
	parser.add_argument('-P', '--output-pstats', help='record profiling data, '
		'readable by the pstats module')
	parser.add_argument('-p', '--profile', action='store_true', help='display profiling data')
	args = parser.parse_args()

	def myrun():
		run(ofile=args.output_raw or sys.stdout)

	if args.output_pstats or args.profile:
		stats_out = args.output_pstats
		text_out = args.profile and sys.stderr
		with_profiling(myrun, stats_out, text_out)
	else:
		myrun()

def run(ofile):
	import json
	state = State((100,100))
	for _ in range(20):
		performer = kmc.weighted_choice(state.edges())
		info = performer(state) # warning: this mutates state
		json.dump(info, ofile)
		ofile.write('\n')
		ofile.flush()

def with_profiling(f, stats_out=None, text_out=None):
	try: from cProfile import Profile
	except: from profile import Profile
	from pstats import Stats
	prof = Profile()

	prof.enable()
	f()
	prof.disable()

	if stats_out: prof.dump_stats(stats_out)
	if text_out:
		MAX_LINES = 20
		stats = Stats(prof, stream=text_out)
		stats.sort_stats('cumtime')
		stats.print_stats(MAX_LINES)

main()
