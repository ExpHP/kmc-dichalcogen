
from functools import partial
import itertools
import warnings

try: import cPickle as pickle
except ImportError: import pickle

from monty.json import MSONable

# FIXME these shouldn't be constant.  They are right now simply so
#  the script can run
RATE_CREATE_VACANCY = 1.
RATE_MIGRATE_VACANCY = 1.
RATE_CREATE_TREFOIL = 50.
RATE_DESTROY_TREFOIL = 1.

# Node occupation flags used in the node status cache
STATUS_NO_VACANCY = 0
STATUS_DIVACANCY = 1
STATUS_TREFOIL_PARTICIPANT = 2

# Names identifying the layer to which a point vacancy belongs.
# This is just kind of a "general idea".
LAYER_DIVACANCY = 'both'
LAYER_MONOVACANCY_1 = 'top'
LAYER_MONOVACANCY_2 = 'bottom'

# FIXME One side-goal is to be able to replay events for old data, which is
#  most easily implemented as part of the class, and therefore might require
#  keeping old versions of the State class around.  This makes it troubling
#  to have a class that does so much because it may result in a lot of code
#  duplication between classes.

class SimpleState(MSONable):
	def __init__(self, dim, vacancies=(), trefoils=()):
		self.__vacancies = dict(vacancies)
		self.__trefoils = dict(trefoils)
		self.grid = TriangularGrid(*dim)
		self.__status_cache = self.__compute_status_cache()
		self.__next_id = 0

	#------------------------------------------
	# Monty.MSONable

	def as_dict(self):
		return {
			'@module': self.__class__.__module__,
			'@class': self.__class__.__name__,
			'next_id': self.__next_id,
			'arm_dim': self.grid.arm_dim(),
			'zag_dim': self.grid.zag_dim(),
			'vacancies': tuple(self.__vacancies.items()),
			'trefoils': tuple(self.__trefoils.items()),
		}
	@classmethod
	def from_dict(klass, d):
		d = dict(d)
		self = klass(
			dim = (d.pop('arm_dim'), d.pop('zag_dim')),
			vacancies = d.pop('vacancies'),
			trefoils = d.pop('trefoils'),
		)
		self.__next_id = d.pop('next_id')
		qual_name = '%s.%s'.format(d.pop('@module'), d.pop('@class'))
		for key in d:
			warnings.warn('Unrecognized key in dict for class {!s}: {!r}'.format(
				qual_name, key))
		return self

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
	# STATUS CACHE
	# The status cache stores redundant information allowing for O(1) lookup
	#  of certain features of the state that would otherwise be O(n) to compute.

	def __update_status_cache(self):
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
	# Mutating functions

	def __consume_id(self):
		id = self.__next_id
		self.__next_id = self.__next_id + 1
		assert id not in self.__vacancies
		assert id not in self.__trefoils
		return id

	def __new_vacancy(self, layer, node):
		id = self.__consume_id()
		self.__vacancies[id] = {'layer': layer, 'where': tuple(node)}
		return id

	def __new_trefoil(self, nodes):
		nodes = frozenset(map(tuple, nodes))
		assert len(nodes) == 3
		id = self.__consume_id()
		self.__trefoils[id] = {'where': nodes}
		return id

	#------------------------------------------
	# Rules
	# These enumerate all of the possible events that can happen to the state.
	# (an event represents one transition across an energy barrier)

	# The purpose of the 'perform' methods is to serve as a callback for
	# generating the new state.  One will be called AFTER an event has
	# been selected, and it will produce the new state as a modified copy
	# of the original state.  It will also generate a serializable dict of
	# info about the move (including the ids assigned to new defects,
	# to assist in playback)

	# FIXME The signal-to-noise ratio here is terrible.
	# I tried to organize the logic best I can, but still too many things are
	# intertwined together; it borders on unreadable.
	#
	# The big blockers preventing me from pulling things apart more is:
	# * (a) Adding entities involves the generation of ids which must be
	#       unambiguously associated with the items in the output.
	# * (b) I want to be able to have aggregated events; e.g. combine all events
	#       for vacancy formation into a single event with total weight N.
	#       (the selection of a node is then deferred until the event is actually
	#        chosen in the weighted selection).
	#       This is trivial to do now, but I'm not sure how it could be done if
	#        perform() was not responsible for constructing the info() dict.

	def __rule__new_vacancy(self):
		''' Allows new vacancies to form in sites with atoms. '''
		def perform(layer, node):
			clone = self.clone()
			id = clone.__new_vacancy(layer, node)
			clone.__update_status_cache()
			return (clone, info(id, layer, node))

		def info(id, layer, node):
			return {
				'action': 'create_vacancy', 'id': id,
				'layer': layer, 'node': node,
				}

		def collect():
			for (node, status) in self.nodes_with_status():
				if status is STATUS_NO_VACANCY:
					yield (partial(perform, LAYER_DIVACANCY, node), RATE_CREATE_VACANCY)

				elif status is STATUS_DIVACANCY: pass
				elif status is STATUS_TREFOIL_PARTICIPANT: pass
				else: assert False, 'complete switch'

		return collect()

	def __rule__migrate_vacancy(self):
		''' Allows vacancies to move to adjacent sites. '''
		def perform(id, dest):
			clone = self.clone()
			clone.__vacancies[id]['where'] = tuple(dest)
			clone.__update_status_cache()
			return (clone, info(id, dest))

		def info(id, dest):
			return {
				'action': 'move_vacancy', 'id': id,
				'dest': dest,
			}

		def collect():
			for (id, vacancy) in self.vacancies_with_id():
				for nbr in self.grid.neighbors(vacancy['where']):
					status = self.node_status(nbr)

					if status is STATUS_NO_VACANCY:
						yield (partial(perform, id, nbr), RATE_MIGRATE_VACANCY)

					elif status is STATUS_DIVACANCY: pass
					elif status is STATUS_TREFOIL_PARTICIPANT: pass
					else: assert False, 'complete switch'

		return collect()

	def __rule__create_trefoil(self):
		''' Allows 3 divacancies to join into a rotated, trefoil defect. '''
		def perform(vacancy_ids):
			clone = self.clone()
			vacancy_ids = tuple(vacancy_ids)
			vacancies = [clone.__vacancies.pop(x) for x in vacancy_ids]
			id = clone.__new_trefoil(x['where'] for x in vacancies)

			clone.__update_status_cache()
			return (clone, info(id, vacancy_ids))

		def info(id, vacancy_ids):
			return {
				'action': 'create_trefoil', 'trefoil_id': id,
				'vacancy_ids': vacancy_ids,
			}

		def collect():
			# another trick to catch missing cases (allow getitem to fail)
			can_become_trefoil = (lambda node: {
				STATUS_DIVACANCY: True,
				STATUS_NO_VACANCY: False,
				STATUS_TREFOIL_PARTICIPANT: False,
			}[self.node_status(node)])

			for id1, v1 in self.vacancies_with_id():
				assert v1['layer'] == LAYER_DIVACANCY
				node1 = v1['where']

				# find two "trefoil neighbors" of node1 that are also trefoil
				#  neighbors with each other (forming a 3-clique)
				neighbors = self.grid.trefoil_neighbors(node1)
				neighbors = list(filter(can_become_trefoil, neighbors))
				for node2, node3 in itertools.combinations(neighbors, r=2):
					if node2 in self.grid.trefoil_neighbors(node3):

						ids = (id1, self.node_vacancy_id(node2), self.node_vacancy_id(node3))
						yield (partial(perform, ids), RATE_CREATE_TREFOIL)

		return collect()

	def __rule__destroy_trefoil(self):
		''' Allows a trefoil defect to revert back into 3 divacancies. '''
		def perform(id):
			clone = self.clone()

			# Replace the trefoil with three divacancies
			trefoil = clone.__trefoils.pop(id)
			nodes = trefoil['where']
			vacancy_ids = [clone.__new_vacancy(LAYER_DIVACANCY, x) for x in nodes]

			clone.__update_status_cache()
			return (clone, info(id, vacancy_ids, nodes))

		def info(id, vacancy_ids, nodes):
			return {
				'action': 'destroy_trefoil', 'trefoil_id': id,
				'vacancy_ids': vacancy_ids, 'vacancy_nodes': nodes,
			}

		def collect():
			for id, _ in self.trefoils_with_id():
				yield (partial(perform, id), RATE_DESTROY_TREFOIL)

		return collect()


	rules = [
		__rule__new_vacancy,
		__rule__migrate_vacancy,
		__rule__create_trefoil,
		__rule__destroy_trefoil,
	]
	def edges(self):
		for rule in self.rules:
			yield from rule(self)


class TriangularGrid:
	def __init__(self, arm_dim, zag_dim):
		self.arm_dim = arm_dim
		self.zag_dim = zag_dim

	def nodes(self):
		''' Iterate over all nodes. '''
		return itertools.product(range(self.arm_dim), range(self.zag_dim))

	def dim(self):
		''' Get (armchair, zigzag) dimensions. '''
		return (self.arm_dim, self.zag_dim)

	def neighbors(self, node):
		''' Get the six immediate neighbors of a node. '''
		arm, zag = node
		def inner():
			offset = 1 - 2 * (arm%2)
			for plusminus in [-1, 1]:
				yield (arm, zag + plusminus) # zigzag edges
				yield (arm + plusminus, zag) # some armchair edges
				yield (arm + plusminus, zag + offset) # more armchairs
		return set(map(self.reduce, inner()))

	def trefoil_neighbors(self, node):
		'''
		The six nodes with which this node can form a trefoil defect.

		A trefoil defect may form when three divacancies are mutually
		"trefoil neighbors" of each other.
		'''
		arm, zag = node
		def inner():
			for plusminus in [-1, 1]:
				yield (arm, zag + 2*plusminus)
				yield (arm + 2, zag + plusminus)
				yield (arm - 2, zag + plusminus)
		return set(map(self.reduce, inner()))

	def can_form_trefoil(self, nodes):
		''' Determine if the three given nodes can form a trefoil defect. '''
		a,b,c = nodes
		return all(
			u in self.trefoil_neighbors(v)
			for (u,v) in [(a,b), (b,c), (c,a)]
		)

	def reduce(self, node):
		''' Apply PBC to get a node's image in the unit cell. '''
		arm, zag = node
		return (arm % self.arm_dim, zag % self.zag_dim)

	# FIXME: try to describe this, it describes where the diagonal edges
	#        coming off of a node lead
	def __neighbor_zag_offset(self, arm):
		return 1 - 2 * (arm%2)
