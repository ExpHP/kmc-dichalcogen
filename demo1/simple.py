
from functools import partial
import itertools
import warnings

import hexagonal as hex

try: import cPickle as pickle
except ImportError: import pickle

# FIXME these shouldn't be constant.  They are right now simply so
#  the script can run
RATE_CREATE_VACANCY = 1.
RATE_MIGRATE_VACANCY = 1.
RATE_CREATE_TREFOIL = 50.
RATE_DESTROY_TREFOIL = 25.

# Node occupation flags used in the node status cache
STATUS_NO_VACANCY = 0
STATUS_DIVACANCY = 1
STATUS_TREFOIL_PARTICIPANT = 2

# Names identifying the layer to which a point vacancy belongs.
# This is just kind of a "general idea".
LAYER_DIVACANCY = 'both'
LAYER_MONOVACANCY_1 = 'top'
LAYER_MONOVACANCY_2 = 'bottom'

class SimpleState:

	def __init__(self, dim):
		self.grid = Grid(dim)
		self.__vacancies = {}
		self.__trefoils = {}
		self.__nodes = self.__compute_nodes_lookup()
		self.__next_id = 0

	def dim(self):
		return self.grid.dim

	def clone(self):
		return pickle.loads(pickle.dumps(self))

	#------------------------------------------
	# prot

	# FIXME: I think I may want to switch these dicts out for named tuples,
	#  to help dodge bugs caused by mispelling keys in __setitem__

	def __compute_nodes_lookup(self):
		''' generates __nodes from __vacancies and __trefoils '''
		cache = {
			x: {'status': STATUS_NO_VACANCY, 'owner': None }
			for x in self.grid.nodes()
		}

		for id, v in self.__vacancies.items():
			assert v['layer'] == LAYER_DIVACANCY, ('looks like this function'
				' (and all users of status functions) needs updating')
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
	# High-level mutators
	# All of these (ought to) maintain the class invariants tested
	#  by __debug_validate_nodes_lookup

	def make_vacancy(self, layer, node):
		id = self.__gen_vacancy(layer, node)

		self.__nodes[node]['status'] = STATUS_DIVACANCY
		self.__nodes[node]['owner'] = id
		self.__debug_validate_nodes_lookup()
		return id

	def move_vacancy(self, id, dest):
		old = self.__vacancies[id]['where']
		status = self.__nodes[old]['status']

		self.__vacancies[id]['where'] = tuple(dest)

		self.__nodes[old]['status']  = STATUS_NO_VACANCY
		self.__nodes[dest]['status'] = status

		self.__nodes[old]['owner']  = None
		self.__nodes[dest]['owner'] = id
		self.__debug_validate_nodes_lookup()

	def make_trefoil_from_vacancies(self, ids):
		ids = tuple(ids)
		nodes = [self.__vacancies[i]['where'] for i in ids]
		new_id = self.__gen_trefoil(nodes)
		for n,i in zip(nodes, ids):
			del self.__vacancies[i]
			self.__nodes[n]['status'] = STATUS_TREFOIL_PARTICIPANT
			self.__nodes[n]['owner'] = new_id

		self.__debug_validate_nodes_lookup()
		return new_id

	def make_vacancies_from_trefoil(self, id):
		trefoil = self.__trefoils.pop(id)
		nodes = trefoil['where']
		ids = [self.__gen_vacancy(LAYER_DIVACANCY, node) for node in nodes]

		for n,i in zip(nodes, ids):
			self.__nodes[n]['status'] = STATUS_DIVACANCY
			self.__nodes[n]['owner'] = i

		self.__debug_validate_nodes_lookup()
		return ids

	#------------------------------------------
	# Low-level mutators

	def __consume_id(self):
		id = self.__next_id
		self.__next_id = self.__next_id + 1
		assert id not in self.__vacancies
		assert id not in self.__trefoils
		return id

	def __gen_vacancy(self, layer, node):
		id = self.__consume_id()
		self.__vacancies[id] = {'layer': layer, 'where': tuple(node)}
		return id

	def __gen_trefoil(self, nodes):
		nodes = frozenset(map(tuple, nodes))
		assert len(nodes) == 3
		id = self.__consume_id()
		self.__trefoils[id] = {'where': nodes}
		return id

class SimpleModel:

	#------------------------------------------
	# Rules
	# These enumerate all of the possible events that can happen to the state.
	# (an event represents one transition across an energy barrier)

	# The purpose of the 'perform' methods is twofold:
	#  1. To serve as a callback for generating the new state. One will be
	#     called AFTER an event has been selected, and it will be passed in
	#     the current state object (or a copy thereof) to modify in-place.
	#  2. To construct and return a serializable dict of info about the
	#     event (enough info for e.g. an animation script to be able to
	#     "replay" the simulation).
	# This info dict may contain details that weren't decided until the
	# 'perform' method was run; hence the double duty.

	# FIXME This still looks and feels overengineered. :/
	# Now that SimpleState and SimpleModel have been separated, it may be
	# easier to think about what this code is really trying to do, and how
	# it might be cleaned up.

	def __rule__new_vacancy(self, state):
		''' Allows new vacancies to form in sites with atoms. '''
		def perform(layer, node, state):
			state.make_vacancy(layer, node)
			return { 'action': 'create_vacancy', 'layer': layer, 'node': node }

		def collect(state):
			for (node, status) in state.nodes_with_status():
				if status is STATUS_NO_VACANCY:
					yield (partial(perform, LAYER_DIVACANCY, node), RATE_CREATE_VACANCY)

				elif status is STATUS_DIVACANCY: pass
				elif status is STATUS_TREFOIL_PARTICIPANT: pass
				else: assert False, 'complete switch'

		# FIXME: honestly the only reason this was written as an inner method
		# is because it makes the code read better. (any less wtf solution?)
		# The same goes for all other collect() methods.
		return collect(state)

	def __rule__migrate_vacancy(self, state):
		''' Allows vacancies to move to adjacent sites. '''
		def perform(id, dest, state):
			old = tuple(state.vacancy_node(id))
			state.move_vacancy(id, dest)
			return { 'action': 'move_vacancy', 'was': old, 'now': dest }

		def collect(state):
			for (id, vacancy) in state.vacancies_with_id():
				for nbr in state.grid.neighbors(vacancy['where']):
					status = state.node_status(nbr)

					if status is STATUS_NO_VACANCY:
						yield (partial(perform, id, nbr), RATE_MIGRATE_VACANCY)

					elif status is STATUS_DIVACANCY: pass
					elif status is STATUS_TREFOIL_PARTICIPANT: pass
					else: assert False, 'complete switch'

		return collect(state)

	def __rule__create_trefoil(self, state):
		''' Allows 3 divacancies to join into a rotated, trefoil defect. '''
		def perform(vacancy_ids, state):
			id = state.make_trefoil_from_vacancies(vacancy_ids)
			nodes = state.trefoil_nodes(id)
			return { 'action': 'create_trefoil', 'nodes': sorted(nodes) }

		def collect(state):
			# another trick to catch missing cases (allow getitem to fail)
			can_become_trefoil = (lambda node: {
				STATUS_DIVACANCY: True,
				STATUS_NO_VACANCY: False,
				STATUS_TREFOIL_PARTICIPANT: False,
			}[state.node_status(node)])

			for id1, v1 in state.vacancies_with_id():
				assert v1['layer'] == LAYER_DIVACANCY
				node1 = v1['where']

				# find two "trefoil neighbors" of node1 that are also trefoil
				#  neighbors with each other (forming a 3-clique)
				neighbors = state.grid.trefoil_neighbors(node1)
				neighbors = list(filter(can_become_trefoil, neighbors))
				for node2, node3 in itertools.combinations(neighbors, r=2):
					if node2 in state.grid.trefoil_neighbors(node3):

						ids = (id1, state.node_vacancy_id(node2), state.node_vacancy_id(node3))
						yield (partial(perform, ids), RATE_CREATE_TREFOIL)

		return collect(state)

	def __rule__destroy_trefoil(self, state):
		''' Allows a trefoil defect to revert back into 3 divacancies. '''
		def perform(id, state):
			ids = state.make_vacancies_from_trefoil(id)
			nodes = [state.vacancy_node(x) for x in ids]
			return { 'action': 'destroy_trefoil', 'nodes': sorted(nodes) }

		def collect(state):
			for id, _ in state.trefoils_with_id():
				yield (partial(perform, id), RATE_DESTROY_TREFOIL)

		return collect(state)

	rules = [
		__rule__new_vacancy,
		__rule__migrate_vacancy,
		__rule__create_trefoil,
		__rule__destroy_trefoil,
	]
	def edges(self, state):
		for rule in self.rules:
			for e in rule(self, state):
				yield e

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
		return self.rotations_around(node, [2,-2,0])

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

