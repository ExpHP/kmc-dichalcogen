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
		.format(DEFAULT_DT_FMT, DEFAULT_OFILE_PATTERN)
		.replace('%','%%'), # argparser does its own % formatting on helpstr
		default = DEFAULT_OFILE_PATTERN)
	parser.add_argument('--no-metal',
		dest='metal', action='store_false',
		help='only show chalcogens')
	args = parser.parse_args()

	validate_output_format(args.output, parser)

	infile = args.INPUT
	with open(infile) as f:
		fullinfo = json.load(f)

	states = do_basic(fullinfo)
	do_animation(states, args.output, args.metal)

def validate_output_format(pat, parser):
	framename = partial(pat.format, dt=datetime.datetime.now(), rand='a', dts='a')
	try: framename(i=0)
	except KeyError as e:
		parser.error("Unknown variable in output filename: " + e.args[0])
	if framename(i=0) == framename(i=1):
		parser.error('Pattern is missing frame index; all output files have same name!')

#----------------------------------------------------------
# This script will replay the events in the KMC sim, using a vastly
# simplified representation from that used in the KMC script.

# Node format is now encoded in an integer, because trying to stick tuples of
# unknown heterogenous types into numpy arrays only creates misery. Le sigh.
#  * non-trefoils encode their vacant layers in the two least significant bits.
#    0: pristine,  {1,2}: monovacancy,   3: divacancy
#  * trefoil nodes are assigned ids from a range of integers that have a certain bit
#    flipped.  Nodes in the same trefoil have the same id.
FLAG_TREFOIL = 2**16
VALUE_PRISTINE = 0
VALUE_DIVACANCY = 3
def iter_valid_trefoil_ids():
	return iter(range(FLAG_TREFOIL, 2*FLAG_TREFOIL))

# Vectorized testing functions
def is_trefoil(value): return value & FLAG_TREFOIL
def is_non_trefoil(value): return np.logical_not(is_trefoil(value))
def is_pristine(value): return value == 0
def is_monovacancy(value, layer=None):
	if layer is None:
		return (value & 1) | (value & 2)
	else: return value & layer
def is_divacancy(value): return value == 3

def do_basic(fullinfo):

	gridinfo = fullinfo['grid']
	assert gridinfo['lattice_type'] == 'hexagonal'
	assert gridinfo['coord_format'] == 'axial'

	dim = gridinfo['dim']
	events = fullinfo['events']
	stateinfo = fullinfo['initial_state']

	trefoil_ids = iter_valid_trefoil_ids()
	def new_trefoil_id(): return next(trefoil_ids)

	state = np.full(dim, VALUE_PRISTINE, dtype=np.int32)
	for (node,layers) in stateinfo['vacancies']:
		state[tuple(node)] = layers
	for (nodes,) in stateinfo['trefoils']:
		state[list(map(list, zip(*nodes)))] = new_trefoil_id()

	def tfunc(state, info):
		state = np.array(state, copy=True)
		rule = info['rule']
		move = dict(info['move'])
		if rule == 'CreateDivacancy':
			node, = pop_entire(move, 'node')
			state[tuple(node)] = VALUE_DIVACANCY
		elif rule == 'FillDivacancy':
			node, = pop_entire(move, 'node')
			state[tuple(node)] = VALUE_PRISTINE

		elif rule == 'CreateMonovacancy':
			node,layer = pop_entire(move, 'node', 'layer')
			state[tuple(node)] |= layer
		elif rule == 'FillMonovacancy':
			node,layer = pop_entire(move, 'node', 'layer')
			state[tuple(node)] &= ~layer

		elif rule == 'MoveDivacancy':
			was, now = pop_entire(move, 'was', 'now')
			state[tuple(was)] = VALUE_PRISTINE
			state[tuple(now)] = VALUE_DIVACANCY

		elif rule == 'CreateTrefoil':
			# indexing state with [[x1,x2,x3], [y1,y2,y3]]
			nodes, = pop_entire(move, 'nodes')
			nodes = list(map(list, zip(*nodes)))
			state[nodes] = new_trefoil_id()
		elif rule == 'DestroyTrefoil':
			nodes, = pop_entire(move, 'nodes')
			nodes = list(map(list, zip(*nodes)))
			state[nodes] = VALUE_DIVACANCY

		else: die('unknown rule: {!r}', rule)
		return state

	yield state
	yield from scan(tfunc, state, events)

def scan(function, start, iterable):
	acc = start
	for x in iterable:
		acc = function(acc, x)
		yield acc

#----------------------------------------------------------

def do_animation(states, filepat, do_metal):
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
		draw_state(ax, state, do_metal=do_metal)
		fig.savefig(fname)
		pl.close(fig) # Keep relatively constant memory profile

def draw_state(where, state, do_metal):
	# ranges extended to include PBC ghost images
	nodes = list(itertools.product(*(range(-1,d+1) for d in state.shape)))

	# FIXME terribly slow and verbose, and underutilizes numpy.
	# Silly me was apparently stuck thinking in the functional paradigm
	#  after the recent Haskell binge...

	def pbc_reduce(node): return tuple(zip_with(op.mod, node, state.shape))
	def filter_nodes(pred, nodes):
		for node in nodes:
			if pred(state[pbc_reduce(node)]):
				yield node

	normal_nodes = list(filter_nodes(is_pristine, nodes))
	monovacant1_nodes = list(filter_nodes(partial(is_monovacancy, layer=1), nodes))
	monovacant2_nodes = list(filter_nodes(partial(is_monovacancy, layer=2), nodes))
	divacant_nodes = list(filter_nodes(is_divacancy, nodes))
	trefoil_nodes = list(filter_nodes(is_trefoil, nodes))

	def is_true_node(x): return is_in_bounds(x, state.shape)
	def is_true_edge(e): return all(map(is_true_node, e))

	def no_metal_graph():
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
		return (g, edges, pos)

	def vec_add(a,b): return tuple(zip_with(op.add, a, b))
	def with_metal_graph():
		# FIXME this is full of disgusting hacks compared to the no-metal code

		# axialsum differences from node to neighbors of cnode and mnode
		M_NBR_DIFFS = [-1, 0, 0], [ 0,-1, 0]
		C_NBR_DIFFS = [ 0, 1, 1], [ 1, 0, 1]
		edges = set()
		g = nx.Graph()
		pos = {}
		for node in nodes:
			# work with nodes in axialsum format.
			# However, when building the graph, we will leave out the sum for chalcogens
			#  so that the filtered node lists built previously can still be used.
			cnode = node + (0,)
			mnode = node + (1,)
			pos[cnode[:2]] = hex.axialsum_to_cart(*cnode)
			pos[mnode] = hex.axialsum_to_cart(*mnode)

			g.add_node(cnode[:2])

			# FIXME this makes poor choices w.r.t. ghost edges for metals
			# no ghost edges beyond first ghost node
			if not is_true_node(node): continue
			g.add_node(mnode)

			edges.add(tuple(sorted([cnode[:2], mnode])))
			for diff in M_NBR_DIFFS:
				edges.add(tuple(sorted([mnode, vec_add(cnode,diff)[:2]])))
			for diff in C_NBR_DIFFS:
				edges.add(tuple(sorted([cnode[:2], vec_add(cnode,diff)])))

		g.add_edges_from(edges)
		return (g, edges, pos)
	(g, edges, pos) = with_metal_graph() if do_metal else no_metal_graph()

	# functions to handle ghost alpha.
	def draw_nodes(nodelist, **kw):
		solids, ghosts = partition(is_true_node, nodelist)
		nx.draw_networkx_nodes(g, nodelist=solids, ax=where, pos=pos, alpha=1, **kw)
		nx.draw_networkx_nodes(g, nodelist=ghosts, ax=where, pos=pos, alpha=GHOST_ALPHA, **kw)
	def draw_edges(edgelist, **kw):
		solids, ghosts = partition(is_true_edge, edgelist)
		nx.draw_networkx_edges(g, edgelist=solids, ax=where, pos=pos, alpha=1, **kw)
		nx.draw_networkx_edges(g, edgelist=ghosts, ax=where, pos=pos, alpha=GHOST_ALPHA, **kw)

	# color for pristine chalcogens; white makes more sense when metals are shown,
	#  but looks horrific when metals aren't shown.
	maincolor = 'w' if do_metal else 'k'
	artists = [
		draw_nodes(normal_nodes, node_color=maincolor, node_size=20, linewidths=1),
		draw_nodes(monovacant1_nodes, node_color='r', node_size=80, linewidths=1),
		draw_nodes(monovacant2_nodes, node_color='b', node_size=80, linewidths=1),
		draw_nodes(divacant_nodes, node_color='m', node_size=100, linewidths=1),
		draw_nodes(trefoil_nodes, node_color='g', node_size=100, linewidths=1),
		draw_edges(edges, edge_color='k', width=1),
	]
	if do_metal:
		metals = [node for node in g.nodes() if len(node) == 3]
		artists.append(draw_nodes(metals, node_color='k', node_size=20, linewidths=1))

	# Bit of a HACK to fix up boundaries
	where.set_xlim(*findlimits(pos[x][0] for x in nodes))
	return artists

def findlimits(xs, fudge=0.02):
	xs = list(xs)
	xmin,xmax = min(xs), max(xs)
	width = xmax - xmin
	xmin -= width * fudge
	xmax += width * fudge
	return xmin,xmax

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
