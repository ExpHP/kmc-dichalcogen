
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
	def __init__(self, dim, vacancies=(), trefoils=()):
		self.__vacancies = dict(vacancies)
		self.__trefoils = dict(trefoils)
		self.grid = Grid(dim)
		self.__status_cache = self.__compute_status_cache()
		self.__next_id = 0

	def dim(self): return self.grid.dim

	#------------------------------------------
	# STATUS CACHE
	# The status cache stores redundant information allowing for O(1) lookup
	#  of certain features of the state that would otherwise be O(n) to compute.

	def update_status_cache(self):
		self.__status_cache = self.__compute_status_cache()

	def __compute_status_cache(self):
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

	# Status cache accessors
	def node_status(self, node): return self.__status_cache[node]['status']
	def node_vacancy_id(self, node): return self.__status_cache[node]['owner']

	#------------------------------------------
	# General helpers

	def clone(self): return pickle.loads(pickle.dumps(self))
	def nodes(self): return self.grid.nodes()
	def nodes_with_status(self): return [(n, self.node_status(n)) for n in self.nodes()]
	def vacancies(self): return self.__vacancies.__iter__()
	def trefoils(self): return self.__trefoils.__iter__()
	def vacancies_with_id(self): return self.__vacancies.items()
	def trefoils_with_id(self): return self.__trefoils.items()

	#------------------------------------------
	# Mutators

	def __consume_id(self):
		id = self.__next_id
		self.__next_id = self.__next_id + 1
		assert id not in self.__vacancies
		assert id not in self.__trefoils
		return id

	def add_vacancy(self, layer, node):
		id = self.__consume_id()
		self.__vacancies[id] = {'layer': layer, 'where': tuple(node)}
		return id

	def add_trefoil(self, nodes):
		nodes = frozenset(map(tuple, nodes))
		assert len(nodes) == 3
		id = self.__consume_id()
		self.__trefoils[id] = {'where': nodes}
		return id

	def del_vacancy(self, id): self.__vacancies.pop(id)
	def del_trefoil(self, id): self.__trefoils.pop(id)

	# these accessors and setters are intended to be a temporary solution
	def trefoil_nodes(self, id): return self.__trefoils[id]['where']
	def vacancy_node(self, id): return self.__vacancies[id]['where']
	def vacancy_layer(self, id): return self.__vacancies[id]['layer']
	def set_trefoil_nodes(self, id, value):
		self.__trefoils[id]['where'] = tuple(map(tuple, value))
	def set_vacancy_node(self, id, value):
		self.__vacancies[id]['where'] = tuple(value)
	def set_vacancy_layer(self, id, value):
		self.__vacancies[id]['layer'] = value

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

	# (note: the primary motivation for having 'perform' mutate the input
	#  state was just to make the code easier to read... though it also
	#  sets the stage for incremental status cache updates)

	# FIXME This still looks and feels overengineered. :/

	def __rule__new_vacancy(self, state):
		''' Allows new vacancies to form in sites with atoms. '''
		def perform(layer, node, state):
			state.add_vacancy(layer, node)
			state.update_status_cache()

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
			state.set_vacancy_node(id, dest)
			state.update_status_cache()

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
			vacancy_ids = tuple(vacancy_ids)
			nodes = [state.vacancy_node(x) for x in vacancy_ids]
			for x in vacancy_ids:
				state.del_vacancy(x)
			state.add_trefoil(nodes)
			state.update_status_cache()

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
			# Replace the trefoil with three divacancies
			nodes = state.trefoil_nodes(id)
			state.del_trefoil(id)
			for node in nodes:
				state.add_vacancy(LAYER_DIVACANCY, node)
			state.update_status_cache()

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

