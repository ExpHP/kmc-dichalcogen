from functools import partial
import datetime
import numpy as np
import warnings
import networkx as nx
import itertools
import json
import sys
import operator as op

import pylab as pl

import hexagonal as hex

PROG='anim'

DEFAULT_DT_FMT = '%Y%m%d-%M%S-%f'
DEFAULT_OFILE_PATTERN = 'ani/ani-{dts}-{i:04d}.png'

GHOST_ALPHA=0.45

def main():
	import argparse
	parser = argparse.ArgumentParser()
	parser.add_argument('INPUT')
	parser.add_argument('-o', '--output', help="Write image files to names with"
		" the specified pattern. Uses python `str.format` syntax with fields 'i'"
		" (frame index from 0), 'rand' (a randomly generated string shared by all"
		" images in the set), 'dt' (a datetime.datetime), and 'dts' (datetime"
		" with a preset format {}). Default {}"
		.format(DEFAULT_DT_FMT, DEFAULT_OFILE_PATTERN),
		default = DEFAULT_OFILE_PATTERN)
	args = parser.parse_args()

	validate_output_format(args.output, parser)

	infile = args.INPUT
	with open(infile) as f:
		fullinfo = json.load(f)

	states = do_basic(fullinfo)
	do_animation(states, args.output)

def validate_output_format(pat, parser):
	framename = partial(pat.format, dt=datetime.datetime.now(), rand='a', dts='a')
	try: framename(i=0)
	except KeyError as e:
		parser.error("Unknown variable in output filename: " + e.args[0])
	if framename(i=0) == framename(i=1):
		parser.error('Pattern is missing frame index; all output files have same name!')

#----------------------------------------------------------

# This replays the events in the script, using a simplified representation.
# (there is a high degree of coupling between this code and the original State
#  class, which is unfortunate, but I didn't want to make such a highly specialized
#  class available outside of the script because it bears the risk of becoming
#  monolithic...)
STATUS_NORMAL, STATUS_VACANCY, STATUS_TREFOIL = range(3)
def do_basic(fullinfo):

	gridinfo = fullinfo['grid']
	assert gridinfo['lattice_type'] == 'hexagonal'
	assert gridinfo['coord_format'] == 'axial'

	dim = gridinfo['dim']
	events = fullinfo['events']

	def normal(): return (STATUS_NORMAL, None)
	def vacancy(): return (STATUS_VACANCY, None)
	def trefoil(nodes): return (STATUS_TREFOIL, tuple(map(tuple, nodes)))

	# 'O,O' is an owl^H^H^H^H^H^H the data type where elements are
	# *tuples* of two objects. Or at least, it behaves close enough,
	# unlike ('O',2) which adds another dimension to the shape,
	# and 'O' which fails to broadcast against your tuples when it
	# automagically reads them as having shape (2,).
	# Except when using np.full() because, reasons apparently.
	state = np_full_not_retarded(dim, normal(), dtype='O,O')

	def tfunc(state, info):
		state = np.array(state, copy=True)
		action = info.pop('action')
		if action == 'create_vacancy':
			node, _layer = pop_entire(info, 'node', 'layer')
			state[tuple(node)] = vacancy()

		elif action == 'move_vacancy':
			was, now = pop_entire(info, 'was', 'now')
			state[tuple(was)] = normal()
			state[tuple(now)] = vacancy()

		elif action == 'create_trefoil':
			nodes, = pop_entire(info, 'nodes')
			# to [[x1,x2,x3], [y1,y2,y3]] for numpy's sake
			state[list(map(list, zip(*nodes)))] = trefoil(nodes)

		elif action == 'destroy_trefoil':
			nodes, = pop_entire(info, 'nodes')
			state[list(map(list, zip(*nodes)))] = vacancy()

		else: die('unknown action: {!r}', action)
		return state

	yield state
	yield from scan(tfunc, state, events)

def scan(function, start, iterable):
	acc = start
	for x in iterable:
		acc = function(acc, x)
		yield acc

def np_full_not_retarded(shape, fillvalue, dtype):
	arr = np.zeros(shape, dtype=dtype)
	arr[...] = fillvalue
	return arr

#----------------------------------------------------------

def do_animation(states, filepat):
	from string import ascii_letters
	import random
	shared_fmt = {
		'dt': datetime.datetime.now(),
		'rand': ''.join([random.choice(ascii_letters) for _ in range(6)]),
	}
	shared_fmt['dts'] = ('{:%s}' % DEFAULT_DT_FMT).format(shared_fmt['dt'])

	for i,state in enumerate(states):
		fname = filepat.format(i=i, **shared_fmt)
		print('Generating frame {} at {}'.format(i, fname))

		# This implementation creates individual figures for each frame.
		#  `subplots` and `savefig` each constitute roughly 45% of the runtime
		#  on a 10x10 grid.
		# There is a post on stackoverflow which recommends a rather clever
		#  strategy to avoid creating multiple figures; make an artist for each
		#  individual node and edge, and save them to the graph as node/edge
		#  attributes for easy lookup and modification.
		# When I tried this, however, the script was slower; `savefig()` took
		#  more than twice as long! No idea whether this was an unavoidable
		#  consequence of having so many artists, or if it was because I called
		#  setters on every artist on every frame (because idunno, "something
		#  something blitting")
		fig, ax = pl.subplots()
		ax.set_aspect('equal')
		draw_state(ax, state)
		fig.savefig(fname)
		pl.close(fig) # Keep relatively constant memory profile

def draw_state(where, state):
	# ranges extended to include PBC ghost images
	nodes = list(itertools.product(*(range(-1,d+1) for d in state.shape)))

	# FIXME terribly slow and verbose, and underutilizes numpy.
	# Silly me was apparently stuck thinking in the functional paradigm
	#  after the recent Haskell binge...

	def pbc_reduce(node): return zip_with(op.mod, node, state.shape)
	def status(node): return state[pbc_reduce(node)][0]

	normal_nodes = [x for x in nodes if status(x) == STATUS_NORMAL]
	vacant_nodes = [x for x in nodes if status(x) == STATUS_VACANCY]
	trefoil_nodes = [x for x in nodes if status(x) == STATUS_TREFOIL]

	def is_true_node(x): return is_in_bounds(x, state.shape)
	def is_true_edge(e): return all(map(is_true_node, e))

	edges = set()
	for node in nodes:
		# no ghost edges beyond first ghost node
		if not is_true_node(node): continue
		nbrs = list(rotations_around(node, [-1, 0, 1]))
		edges.update(tuple(sorted([node,x])) for x in nbrs)
	edges = list(edges)

	g = nx.Graph()
	g.add_nodes_from(nodes)
	g.add_edges_from(edges)

	pos = {(a,b): hex.axialsum_to_cart(a, b, 0) for (a,b) in nodes}

	# functions to handle ghost alpha.
	def draw_nodes(nodelist, **kw):
		solids, ghosts = partition(is_true_node, nodelist)
		nx.draw_networkx_nodes(g, nodelist=solids, ax=where, pos=pos, alpha=1, **kw)
		nx.draw_networkx_nodes(g, nodelist=ghosts, ax=where, pos=pos, alpha=GHOST_ALPHA, **kw)
	def draw_edges(edgelist, **kw):
		solids, ghosts = partition(is_true_edge, edgelist)
		nx.draw_networkx_edges(g, edgelist=solids, ax=where, pos=pos, alpha=1, **kw)
		nx.draw_networkx_edges(g, edgelist=ghosts, ax=where, pos=pos, alpha=GHOST_ALPHA, **kw)

	artists = [
		draw_nodes(normal_nodes, node_color='k', node_size=20, linewidths=1),
		draw_nodes(vacant_nodes, node_color='r', node_size=100, linewidths=1),
		draw_nodes(trefoil_nodes, node_color='g', node_size=100, linewidths=1),
		draw_edges(edges, edge_color='k', width=1),
	]
	return artists

def rotations_around(node, disp):
	for rot_disp in hex.cubic_rotations_60(*disp):
		yield zip_with(op.add, node, rot_disp)

def is_in_bounds(node, dim):
	if any(x<0 for x in node): return False
	if any(zip_with(op.ge, node, dim)): return False
	return True

#----------------------------------------------------------

def partition(predicate, it):
	ayes, nays = [], []
	for x in it:
		if predicate(x): ayes.append(x)
		else: nays.append(x)
	return ayes, nays

def zip_with(f, xs, ys):
	return tuple(f(x,y) for (x,y) in zip(xs,ys))

def flatten(it):
	for x in it:
		yield from it

# For checking the assumption that all keys of a dict are known to us
def pop_entire(d, *keys):
	for k in keys: yield d.pop(k)
	for k in d: warnings.warn('pop_entire: Unrecognized key: {!r}'.format(k))

#----------------------------------------------------------

def say(msg, *args, **kw):     print(msg.format(*args, **kw), file=sys.stdout)
def say_err(msg, *args, **kw): print('%s: %s' % (PROG, msg.format(*args, **kw)), file=sys.stderr)

def warn(msg, *args, **kw):
	say_err('Warning: ' + msg, *args, **kw)

def die(msg, *args, **kw):
	say_err('FATAL: ' + msg, *args, **kw)
	say_err('Aborting.')
	sys.exit(1)

if __name__ == '__main__':
	main()
