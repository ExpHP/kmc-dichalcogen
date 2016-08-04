
from __future__ import division

import itertools
import random
import hexagonal as hex

from .incremental import ZobristKey
from .validate import validate_dict, validate_equal
from .util import zip_exact, window2

try: import cPickle as pickle
except ImportError: import pickle

# Every Rule has at least one kind; for those with one it is usually this:
# (appears as config key, and as a possible value in MoveCache)
DEFAULT_KIND = 'natural'

# These constants are for named for purposes of clarity, not for abstraction;
# Most of the code WILL assume that they have these numeric values,
#  and may use bitwise operations to manipulate them.
LAYERS = [1,2]   # possible values of "layers" for monovacancy
BOTH_LAYERS = 3  # value of "layers" for divacancy

# These namedtuples are used together with their type as a tagged union;
# e.g.  (type(obj), obj), where the type serves as the discriminator.
#
# (the explicit discriminator is because namedtuples are (unfortunately)
#  designed to be compatible with tuples, which means their __eq__ and
#  __hash__ methods do not care about the type)
from collections import namedtuple
Pristine = namedtuple('Pristine', [])
Vacancy = namedtuple('Vacancy', ['node', 'layers'])
Trefoil = namedtuple('Trefoil', ['nodes'])

# only need one instance
PRISTINE = Pristine()
PRISTINE_ENTRY = (Pristine, PRISTINE)

# ``State(zobrist=HASH)`` uses ``hash`` for zobrist diffs.
HASH = object()

class State:

	def __init__(self, dim, zobrist=None):
		self.grid = Grid(dim)
		self.__vacancies = set()
		self.__trefoils = set()
		self.__nodes = self.__compute_nodes_lookup()

		self.__zobrist = None
		if isinstance(zobrist, int): self.__zobrist = ZobristKey(bits=zobrist)
		elif zobrist is HASH:        self.__zobrist = ZobristKey(rng=None)
		elif zobrist is not None:    raise TypeError('zobrist')

	@classmethod
	def from_entity_lists(cls, dim, vacancies, trefoils, zobrist=None):
		self = cls(dim, zobrist=zobrist)
		for (node, layer) in vacancies:
			self.new_vacancy(node, layer)
		for (nodes,) in trefoils:
			self.new_trefoil(nodes)
		return self

	def dim(self):
		return self.grid.dim

	def clone(self):
		''' Creates a copy of the state (minus event bindings). '''
		return pickle.loads(pickle.dumps(self))

	#------------------------------------------
	# Serialization

	@classmethod
	def from_dict(cls, d):
		from itertools import starmap
		dim = tuple(d.pop('dim'))
		if len(dim) != 2: raise ValueError
		if not all(isinstance(x,int) for x in dim): raise ValueError
		if not all(x>0 for x in dim): raise ValueError

		vacancies = starmap(Vacancy, d.pop('vacancies'))
		trefoils  = starmap(Trefoil, d.pop('trefoils'))
		return cls.from_entity_lists(dim, vacancies, trefoils)

	def to_dict(self):
		return {
			'dim': list(self.dim()),
			'vacancies': list(map(tuple, self.vacancies())),
			'trefoils': list(map(tuple, self.trefoils())),
		}

	#------------------------------------------
	# THE __nodes CACHE:
	# A lookup of data for individual nodes.

	# The values of __nodes are like a tagged union.
	# They are of the form (status, data), where status serves as a descriminator
	#  for how to interpret the data.

	def validate(self):
		'''
		Validate incrementalized computations with an expensive test.

		Throws an exception or returns True (for use in assert).
		'''
		self.__validate_entity_invariants()
		self.__validate_nodes_lookup()
		self.__validate_zobrist_key()
		return True

	# This function is the "gold standard" for what __nodes should look like.
	# Rules must strive to preserve this definition.
	def __compute_nodes_lookup(self):
		''' generates __nodes from __vacancies and __trefoils '''
		cache = { x:PRISTINE_ENTRY for x in self.grid.nodes() }

		for vacancy in self.__vacancies:
			cache[vacancy.node] = (Vacancy, vacancy)

		for trefoil in self.__trefoils:
			for node in trefoil.nodes:
				cache[node] = (Trefoil, trefoil)

		return cache

	def __validate_nodes_lookup(self):
		validate_dict(
			self.__nodes,
			self.__compute_nodes_lookup(),
			name1='cached', name2='expected', key='node')

		return True

	def __validate_zobrist_key(self):
		if self.__zobrist:
			expected = self.__zobrist.derive()
			expected.update((Vacancy,x) for x in self.__vacancies)
			expected.update((Trefoil,x) for x in self.__trefoils)
			validate_equal(self.__zobrist.value(), expected.value())
		return True

	def __validate_entity_invariants(self):
		for x in self.__vacancies:
			if not (1 <= x.layers <= 3):
				raise AssertionError('vacancy with bad layer: %s' % x.layers)

		return True

	#------------------------------------------
	# Accessors/iterators

	def pristine_nodes(self): return filter(self.is_pristine, self.grid.nodes())

	def vacancies(self): return self.__vacancies.__iter__()
	def divacancies(self): return (x for x in self.__vacancies if x.layers == BOTH_LAYERS)
	def monovacancies(self): return (x for x in self.__vacancies if x.layers != BOTH_LAYERS)

	def nodes(self): return self.grid.nodes()
	def node_status(self, node): return self.__nodes[node][0]
	def nodes_with_status(self): return [(n, self.node_status(n)) for n in self.nodes()]

	def trefoils(self): return self.__trefoils.__iter__()
	def trefoil_nodes_at(self, node):
		(status,trefoil) = self.__nodes[node]
		if status is not Trefoil:
			raise KeyError('node not a trefoil')
		return frozenset(trefoil.nodes)

	def vacant_layerset_at(self, node):
		''' Get the layers value (an int to manipulate as a bitset) of a node.
		0 = no vacancies, 1 or 2 = monovacancy, 3 = divacancy '''
		(status,vacancy) = self.__nodes[node]
		if status is Pristine: return 0
		elif status is Vacancy: return vacancy.layers
		else: raise KeyError('monovacancy layers not defined at node')

	#------------------------------------------
	# Public mutators
	# These are discrete actions which modify the State and perform
	# incrementalized updates to all caches, so that all objects
	# are left in a consistent state.

	# General flow is:
	# * Update the entity lists (__vacancies, __trefoils)
	# * Update the __nodes table.
	# * Update the __zobrist key.

	# NOTES on implementation constraints:
	# * These methods should be regarded as the primitive operations for
	#   modifying the State.  Any other operations are composed of these.
	# * They must be members of State so that they can modify private members.

	def new_divacancy(self, node):
		''' Turn a pristine node into a divacancy. '''
		self.new_vacancy(node, BOTH_LAYERS)

	def new_vacancy(self, node, layers):
		''' Turn a pristine node into a mono- or divacancy. '''
		node = tuple(node)
		assert self.is_pristine(node)

		vacancy = Vacancy(node, layers)
		self.__vacancies.add(vacancy)
		self.__nodes[node] = (Vacancy, vacancy)
		self.__zobrist_toggle((Vacancy, vacancy))

	def new_trefoil(self, nodes):
		''' Turn three pristine nodes into a trefoil. '''
		nodes = frozenset(map(tuple, nodes))
		assert len(nodes) == 3
		assert all(map(self.is_pristine, nodes))

		trefoil = Trefoil(nodes)
		self.__trefoils.add(trefoil)
		for node in nodes:
			self.__nodes[node] = (Trefoil, trefoil)
		self.__zobrist_toggle((Trefoil, trefoil))

	def pop_divacancy(self, node):
		''' Turn a divacancy into a pristine node. '''
		assert self.is_divacancy(node)
		self.pop_vacancy(node)

	def pop_vacancy(self, node):
		''' Turn a mono- or divacancy into a pristine node. '''
		vacancy = self.__find_vacancy(node)
		self.__vacancies.remove(vacancy)
		self.__nodes[node] = PRISTINE_ENTRY
		self.__zobrist_toggle((Vacancy, vacancy))
		return vacancy

	def pop_trefoil(self, nodes):
		''' Turn a trefoil into three pristine nodes. '''
		nodes = frozenset(map(tuple, nodes))
		assert len(nodes) == 3

		trefoil = self.__find_trefoil(nodes)
		self.__trefoils.remove(trefoil)
		for node in nodes:
			self.__nodes[node] = PRISTINE_ENTRY
		self.__zobrist_toggle((Trefoil, trefoil))
		return trefoil

	def __zobrist_toggle(self, value):
		if self.__zobrist:
			self.__zobrist.toggle(value)

	def __find_vacancy(self, node):
		(status,vacancy) = self.__nodes[node]
		assert status is Vacancy
		assert vacancy.node == node
		return vacancy

	def __find_trefoil(self, nodes):
		nodes = frozenset(nodes)
		(status,trefoil) = self.__nodes[next(iter(nodes))]
		assert status is Trefoil
		assert trefoil.nodes == nodes
		return trefoil

	#------------------------------------------
	def is_monovacancy(self, node):
		''' Test that a node is a monovacancy. '''
		tag, data = self.__nodes[node]
		assert tag in [Pristine, Vacancy, Trefoil], 'function not updated'
		return tag is Vacancy and data.layers in LAYERS

	def is_divacancy(self, node):
		''' Test that a node is a divacancy. '''
		tag, data = self.__nodes[node]
		assert tag in [Pristine, Vacancy, Trefoil], 'function not updated'
		return tag is Vacancy and data.layers == BOTH_LAYERS

	def is_vacancy(self, node):
		''' Test that a node is a mono or divacancy. '''
		tag, data = self.__nodes[node]
		assert tag in [Pristine, Vacancy, Trefoil], 'function not updated'
		return tag is Vacancy

	def is_trefoil(self, node):
		''' Test that a node is in a trefoil. '''
		tag, data = self.__nodes[node]
		assert tag in [Pristine, Vacancy, Trefoil], 'function not updated'
		return tag is Trefoil

	def is_pristine(self, node):
		''' Test that a node is pristine. (i.e. all atoms are present)'''
		tag, data = self.__nodes[node]
		assert tag in [Pristine, Vacancy, Trefoil], 'function not updated'
		return tag is Pristine

	def has_defined_layerset(self, node):
		''' Test that a node has a well-defined set of monovacancies.
		True for pristine nodes, monovacancies and divacancies. '''
		tag, data = self.__nodes[node]
		assert tag in [Pristine, Vacancy, Trefoil], 'function not updated'
		return tag is not Trefoil

	#------------------------------------------
	def zobrist_key(self):
		'''
		Get the current value of the zobrist key, an incrementally
		computed hash for identifying previously visited states.

		In general, zobrist keys between two different instances of State
		are incompatible.  However, if one is ``clone``d from the other,
		then the two will always at least agree on the hashes for states
		visited *prior* to the ``clone``.)
		'''
		assert self.__zobrist, "shouldn't be called unless --zobrist is set..."
		return self.__zobrist.value()

#------------------------------------------------------------------

RANDOM_MODES =  ['exact','approx']
RANDOM_ASSIGN_FUNC = {
	'divacancy':   lambda s,n,rng: s.new_divacancy(n),
	'monovacancy': lambda s,n,rng: s.new_monovacancy(n, layer=rng.choice(LAYERS)),
	'remainder':   lambda s,n,rng: None,
}
RANDOM_PARAMS = list(set(RANDOM_ASSIGN_FUNC) - set(['remainder']))

def gen_random_state(dim, mode, params, rng=random, **kw):
	state = State(dim, **kw)
	__populate_state(state, mode=mode, params=params, rng=rng)
	return state

def __populate_state(state, mode, params, rng=random):
	''' randomly populate an empty state '''
	params = dict(params)
	if mode == 'exact':    return __populate_state__exact(state, params, rng=rng)
	elif mode == 'approx': return __populate_state__approx(state, params, rng=rng)
	else: assert False, 'complete switch'

# interprets each rate as a probability of occurence for each individual site
def __populate_state__approx(state, params, rng=random):
	from math import fsum
	from .kmc import weighted_choice

	kw_pairs = list(params.items())

	remainder_prob = 1. - fsum(params.values())
	assert remainder_prob >= (-1e-10), 'already required sum() <= 1.'
	if remainder_prob > 0:
		kw_pairs.append(('remainder', remainder_prob))

	nodes = list(state.nodes())
	chosen = weighted_choice(kw_pairs, howmany=len(nodes), rng=rng)
	for (node,param) in zip_exact(nodes, chosen):
		RANDOM_ASSIGN_FUNC[param](state, node, rng)

# interprets each rate as a target frequency and tries to match them
#  as closely as possible
def __populate_state__exact(state, params, rng=random):
	from .util import partial_sums, differences

	nodes = list(state.nodes())
	rng.shuffle(nodes)

	# From the shuffled list, select intervals of lengths that best approximate
	# the specified rate distribution.
	(keys,rates) = zip(*sorted(params.items(), key=lambda kv:kv[1]))
	cumul = partial_sums(rates, with_zero=True)
	indices = list(round(r*len(nodes)) for r in cumul) # interval endpoints

	assert all(x >= 0 for x in differences(indices)), 'tested prior to this func'
	assert indices[-1] <= len(nodes), 'not possible through floating point error alone'

	for (key,(start,end)) in zip_exact(keys, window2(indices)):
		f = RANDOM_ASSIGN_FUNC[key]
		for node in nodes[start:end]:
			f(state, node, rng)

#------------------------------------------------------------------

# Periodic hexagonal grid, stored in axial coords.
class Grid:
	def __init__(self, dim):
		self.dim = dim
		assert len(self.dim) == 2

	def nodes(self):
		''' Iterate over all nodes. '''
		return itertools.product(*(range(d) for d in self.dim))

	def neighbors(self, node):
		''' The six neighbors of a node on a hexagonal lattice. '''
		return self.rotations_around(node, [-1, 0, 1])

	def trefoil_neighbors(self, node):
		''' The six nodes with which a node can form a trefoil defect.

		For one to actually form, three nodes must all mutually be
		trefoil neighbors. '''
		return self.rotations_around(node, [2, -2, 0])

	def nodes_in_distance_range(self, nodes, mindist, maxdist):
		'''
		Collect nodes in a range of distances from a set of nodes.

		Collects nodes at a distance from ``mindist`` to ``maxdist``, inclusive.
		The input nodes have distance 0, their neighbors (excluding themselves)
		are distance 1, et cetera.

		Designed for functions which need to invalidate a region of the grid
		after making several modifications.
		'''
		# structured to avoid unnecessarily computing an extra group
		if maxdist < mindist: return
		for (n,group) in enumerate(bfs_groups_by_distance(nodes, self.neighbors)):
			if n < mindist: continue
			yield from group
			if n >= maxdist: break

	def rotations_around(self, node, disp):
		''' Get the node at node+disp, together with the other 5 nodes
		related to it by the sixfold rotational symmetry around node. '''
		a,b = node
		for da, db, _ in hex.cubic_rotations_60(*disp):
			yield self.reduce((a + da, b + db))

	def can_form_trefoil(self, nodes):
		''' Determine if the three given nodes can form a trefoil defect. '''
		n1,n2,n3 = nodes
		return all(
			u in self.trefoil_neighbors(v)
			for (u,v) in [(n1,n2), (n2,n3), (n3,n1)]
		)

	def reduce(self, node):
		''' Apply PBC to get a node's image in the unit cell. '''
		a, b = node
		return (a % self.dim[0], b % self.dim[1])


def bfs_groups_by_distance(roots, edge_func):
	seen = set()
	current = set(roots)
	while True:
		yield current
		seen |= current
		prev = current

		current = set()
		for x in prev:
			new = set(edge_func(x))
			new -= seen
			current.update(new)

