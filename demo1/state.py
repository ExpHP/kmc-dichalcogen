
from __future__ import division

import itertools
import hexagonal as hex

try: import cPickle as pickle
except ImportError: import pickle

# Node occupation flags used in the node status cache
STATUS_NO_VACANCY = 0
STATUS_DIVACANCY = 1
STATUS_TREFOIL_PARTICIPANT = 2

# Every Rule has at least one kind; for those with one it is usually this:
# (appears as config key, and as a possible value in MoveCache)
DEFAULT_KIND = 'natural'

class State:

	def __init__(self, dim, emit):
		self.grid = Grid(dim)
		# FIXME so this was a bad idea; surprisingly, it looks like bound member
		#  functions can be pickled; unsurprisingly, it needs to create new copies
		#  of the bound class objects when unpickling.
		# As a result, the presence of the emit member indirectly causes clone()
		#  to create a brand new IncrementalNodeCache.
		self.emit = emit
		self.__vacancies = {}
		self.__trefoils = {}
		self.__nodes = self.__compute_nodes_lookup()
		self.__next_id = 0

	def dim(self):
		return self.grid.dim

	def clone(self):
		return pickle.loads(pickle.dumps(self))

	#------------------------------------------
	# FIXME: I think I may want to switch these dicts out for named tuples,
	#  to help dodge bugs caused by mispelling keys in __setitem__

	def __compute_nodes_lookup(self):
		''' generates __nodes from __vacancies and __trefoils '''
		cache = {
			x: {'status': STATUS_NO_VACANCY, 'owner': None }
			for x in self.grid.nodes()
		}

		for id, v in self.__vacancies.items():
			node = v['where']
			cache[node]['status'] = STATUS_DIVACANCY
			cache[node]['owner'] = id

		for id, v in self.__trefoils.items():
			for node in v['where']:
				cache[node]['status'] = STATUS_TREFOIL_PARTICIPANT
				cache[node]['owner'] = id

		return cache

	def __debug_validate_nodes_lookup(self):
		def run_in_debug_only():
			expected = self.__compute_nodes_lookup()
			actual   = self.__nodes

			missing_nodes = set(expected) - set(actual)
			if missing_nodes:
				raise AssertionError("node not in lookup: {!r}".format(missing_nodes.pop()))

			unexpected_nodes = set(actual) - set(expected)
			if unexpected_nodes:
				raise AssertionError("unexpected node in lookup: {!r}".format(unexpected_nodes.pop()))

			for n in expected:
				if expected[n] != actual[n]:
					raise AssertionError("bad data for node {!r}\n"
						"  In Table: {!r}\n"
						"  Expected: {!r}".format(n, actual[n], expected[n]))

			return True

		assert run_in_debug_only()

	#------------------------------------------
	# Accessors/iterators

	def vacancies(self): return self.__vacancies.__iter__()
	def vacancy_node(self, id): return self.__vacancies[id]['where']
	def vacancy_layer(self, id): return self.__vacancies[id]['layer']
	def vacancies_with_id(self): return self.__vacancies.items()

	def nodes(self): return self.grid.nodes()
	def node_status(self, node): return self.__nodes[node]['status']
	def node_vacancy_id(self, node): return self.__nodes[node]['owner']
	def nodes_with_status(self): return [(n, self.node_status(n)) for n in self.nodes()]

	def trefoils(self): return self.__trefoils.__iter__()
	def trefoil_nodes(self, id): return self.__trefoils[id]['where']
	def trefoils_with_id(self): return self.__trefoils.items()

	#------------------------------------------
	# Public mutators
	# These are discrete actions which modify the State and perform
	# incrementalized updates to all caches, so that all objects
	# are left in a consistent state.

	# General flow is:
	# * Emit a message to objects dependent on the State.  This is done
	#   first so they can see how the state looks before the change.
	# * Update the primary storage (__vacancies, __trefoils)
	# * Update the __nodes cache (this is not done via `emit` because other
	#   objects depend on the node cache).

	# NOTES on implementation constraints:
	# * These methods should be regarded as the primitive operations for
	#   modifying the State.  Any other operations are composed of these.
	# * They must be members of State so that they can modify private members.
	# * They contain 'emit' calls to ensure that all composite operations
	#   send the necessary messages.
	# * In theory, the emit member could be removed, and another object with a
	#   parallel set of methods could first call emit and then call these methods.
	#   But then composite operations would have to be implemented on that object
	#   as well; not this class.

	def new_vacancy(self, node):
		self.emit('pre_new_vacancy', self, node)
		self.emit('pre_status_change', self, [node])

		id = self.__consume_id()
		self.__vacancies[id] = {'where': tuple(node)}
		self.__nodes[node]['status'] = STATUS_DIVACANCY
		self.__nodes[node]['owner'] = id

		self.emit('post_new_vacancy', self, node)
		self.emit('post_status_change', self, [node])

	def new_trefoil(self, nodes):
		nodes = frozenset(map(tuple, nodes))
		assert len(nodes) == 3

		self.emit('pre_new_trefoil', self, nodes)
		self.emit('pre_status_change', self, nodes)

		id = self.__consume_id()
		self.__trefoils[id] = {'where': nodes}
		for n in nodes:
			self.__nodes[n]['status'] = STATUS_TREFOIL_PARTICIPANT
			self.__nodes[n]['owner'] = id

		self.emit('post_new_trefoil', self, nodes)
		self.emit('post_status_change', self, nodes)

	def pop_vacancy(self, node):
		self.emit('pre_del_vacancy', self, node)
		self.emit('pre_status_change', self, [node])

		id = self.__find_vacancy(node)
		vacancy = self.__vacancies.pop(id)
		self.__nodes[node]['status'] = STATUS_NO_VACANCY
		self.__nodes[node]['owner'] = None

		self.emit('post_del_vacancy', self, node)
		self.emit('post_status_change', self, [node])
		return vacancy

	def pop_trefoil(self, nodes):
		nodes = frozenset(map(tuple, nodes))
		assert len(nodes) == 3

		self.emit('pre_del_trefoil', self, nodes)
		self.emit('pre_status_change', self, nodes)

		id = self.__find_trefoil(nodes)
		trefoil = self.__trefoils.pop(id)
		for node in nodes:
			self.__nodes[node]['status'] = STATUS_NO_VACANCY
			self.__nodes[node]['owner'] = None

		self.emit('post_del_trefoil', self, nodes)
		self.emit('post_status_change', self, nodes)
		return trefoil

	def __find_vacancy(self, node):
		id = self.__nodes[node]['owner']
		assert self.__vacancies[id]['where'] == node
		return id

	def __find_trefoil(self, nodes):
		nodes = frozenset(nodes)
		id = self.__nodes[nodes[0]]['owner']
		assert self.__trefoils[id]['where'] == nodes
		return id

	#------------------------------------------
	# Low-level mutators
	# These do not necessarily leave the object in a consistent state.

	def __consume_id(self):
		id = self.__next_id
		self.__next_id = self.__next_id + 1
		assert id not in self.__vacancies
		assert id not in self.__trefoils
		return id


# An Event is a (physically meaningful) State transition which occurs
#  through some stochastic process.
# One randomly chosen Event occurs every step of the computation.
# The term is used rather loosely.

# A Move is an event that has a fully determined outcome.
# That is, given an initial State and a Move, the final state is uniquely
#  specified, without randomness.

# Oftentimes, many Moves can be classified under a single umbrella;
# e.g. in the absence of second order effects, the action of creating a
# vacancy will have the same energy barrier regardless of where it is placed.
# In such cases, these similar Moves are said to be of the same Kind.


def flat(it):
	for x in it:
		yield from x

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

