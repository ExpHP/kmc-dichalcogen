
from __future__ import division

from collections import defaultdict
import itertools

from .incremental import IncrementalMoveCache
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

class State:

	def __init__(self, dim, emit):
		self.grid = Grid(dim)
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
	# Each corresponds to a rule.

	# emit is a function that sends update messages to rules

	def make_vacancy(self, node):
		return self.gen_vacancy(node)

	def move_vacancy(self, id, dest):
		self.pop_vacancy(id)
		return self.gen_vacancy(dest)

	def make_trefoil_from_vacancies(self, ids):
		vacancies = [self.del_vacancy(i) for i in ids]
		nodes = [x['where'] for x in vacancies]
		return self.new_trefoil(nodes)

	def make_vacancies_from_trefoil(self, id):
		trefoil = self.del_trefoil(id)
		nodes = trefoil['where']
		return [self.new_vacancy(node) for node in nodes]

	#------------------------------------------
	# Mid-level mutators
	# These are discrete actions which modify the State and perform
	# incrementalized updates to all caches, so that all objects
	# are left in a consistent state.

	# General flow is:
	# * Emit a message to objects dependent on the State.  This is done
	#   first so they can see how the state looks before the change.
	# * Update the primary storage (__vacancies, __trefoils)
	# * Update the __nodes cache (this is not done via `emit` because other
	#   objects depend on the node cache).

	def new_vacancy(self, node):
		id = self.__consume_id()
		self.emit('new_vacancy', self, node)

		self.__vacancies[id] = {'where': tuple(node)}
		self.__nodes[node]['status'] = STATUS_DIVACANCY
		self.__nodes[node]['owner'] = id
		return id

	def new_trefoil(self, nodes):
		nodes = frozenset(map(tuple, nodes))
		assert len(nodes) == 3

		id = self.__consume_id()
		self.emit('new_trefoil', self, nodes)

		self.__trefoils[id] = {'where': nodes}
		for n in nodes:
			self.__nodes[n]['status'] = STATUS_TREFOIL_PARTICIPANT
			self.__nodes[n]['owner'] = id
		return id

	def pop_vacancy(self, node):
		self.emit('del_vacancy', self, node=node)

		id = self.__find_vacancy(self, node)
		vacancy = self.__vacancies.pop(id)
		node = vacancy['where']
		self.__nodes[node]['status'] = STATUS_NO_VACANCY
		self.__nodes[node]['owner'] = None

		return vacancy

	def pop_trefoil(self, nodes):
		self.emit('del_trefoil', self, nodes=nodes)

		id = self.__find_trefoil(self, nodes)
		trefoil = self.__trefoils.pop(id)
		for node in trefoil['where']:
			self.__nodes[node]['status'] = STATUS_NO_VACANCY
			self.__nodes[node]['owner'] = None

		return trefoil

	def __find_vacancy(self, node):
		id = self.__nodes[node]['owner']
		assert self.__trefoils[id]['where'] == node
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


class RuleSet:
	def __init__(self, init_state, event_manager):
		self.move_cache = IncrementalMoveCache()
		self.rules = [
			RuleCreateVacancy(init_state, event_manager, self.move_cache),
			RuleFillVacancy(init_state, event_manager, self.move_cache),
		]

		# kinds and weights
		kw_pairs = list(flat(x.kinds().items() for x in self.rules))
		assert len(kw_pairs) == len(set(k for (k,w) in kw_pairs)), 'kinds not unique!'

		self.weight = dict(kw_pairs)

	# Returns ([(obj, weight)], Metadata), where Metadata is just something
	# requried by perform()
	def edges(self, state):
		(counts, sources) = self.move_cache.randomly_decided_counts()

		def weighted_kinds():
			for kind,count in counts.items():
				yield (kind, count * self.weight[kind])

		metadata = (counts, sources)
		return (list(weighted_kinds()), metadata)

	def perform_move(self, kind, state, metadata):
		# decide a single move
		counts, sources = metadata
		(rule, move) = self.move_cache.random_by_kind(kind, sources, check_total=counts[kind])
		# old function of perform
		rule.perform(move, state)
		return rule.info(move, kind)





class Rule:
	def __init__(self, initial_state, event_man, move_cache):
		# FIXME this doesn't really belong here, it's just here for ergonomics
		# (it's basically here as an implicit parameter to on_new_vacancy and friends,
		#  via add_move and clear_move)
		self.move_cache = move_cache

		self.initialize_moves(initial_state)

		# implementations of these required on each subclass
		event_man.add_listener('new_vacancy', self.on_new_vacancy)
		event_man.add_listener('del_vacancy', self.on_del_vacancy)
		event_man.add_listener('new_trefoil', self.on_new_trefoil)
		event_man.add_listener('del_trefoil', self.on_del_trefoil)

	# API for the KMC engine

	def perform(self, move, state):
		''' Perform the given move on the state, mutating it. '''
		raise NotImplementedError

	def info(self, move, kind):
		''' Return a dict of serializable data describing the move, for output. '''
		raise NotImplementedError

	def kinds(self):
		''' Return a list of [(kind, individual_weight)] '''
		raise NotImplementedError

	# Callbacks to modify move_cache

	# callback to set up the list of moves in move_cache from scratch
	# (assuming there is initially nothing belonging to this rule in there)
	def initialize_moves(self, initial_state): raise NotImplementedError

	# callbacks to incrementally update the list of moves in move_cache
	def on_new_vacancy(self, initial_state): raise NotImplementedError
	def on_del_vacancy(self, initial_state): raise NotImplementedError
	def on_new_trefoil(self, initial_state): raise NotImplementedError
	def on_del_trefoil(self, initial_state): raise NotImplementedError

	# make debug output more readible
	def __repr__(self): return type(self).__name__

	# convenience methods intended to be used by the Rule subclasses
	# (move_cache mixin)

	def add_move(self, move, kind=None):
		# For rules that only generate moves of a single kind, allow them to omit it
		if kind is None: kind, = self.kinds()
		else: assert any(k == kind for k in self.kinds())

		# When giving the move to the MoveCache we tag it with ``self`` for two reasons:
		#  * so that moves from two separate rules can't compare equal. (and thus their
		#    representations can be simpler; like just a node for RuleCreateVacancy)
		#  * so the KMC engine can perform the action.
		self.move_cache.add((self, move), kind)

	def clear_move(self, move):
		self.move_cache.clear_all((self, move))

class RuleCreateVacancy(Rule):
	def perform(self, node, state):
		print(self.move_cache.randomly_decided_counts()[0])
		state.new_vacancy(node)

	def info(self, node, kind):
		return {
			'action': 'create_vacancy',
			'node':   node,
		}
	def kinds(self): return { type(self): 1.0 }
	def initialize_moves(self, state):
		for node in state.grid.nodes():
			self.add_move(node)
	def on_new_vacancy(self, state, node): self.clear_move(node)
	def on_del_vacancy(self, state, node): self.add_move(node)
	def on_new_trefoil(self, state, nodes): [self.clear_move(x) for x in nodes]
	def on_del_trefoil(self, state, nodes): [self.add_move(x) for x in nodes]

class RuleFillVacancy(Rule):
	def perform(self, node, state):
		state.pop_vacancy(node)

	def info(self, node, kind):
		return {
			'action': 'fill_vacancy',
			'node':   node,
		}
	def kinds(self): return { type(self): 1.0 }
	def initialize_moves(self, state): pass
	def on_new_vacancy(self, state, node): self.add_move(node)
	def on_del_vacancy(self, state, node): self.clear_move(node)
	def on_new_trefoil(self, state, nodes): pass
	def on_del_trefoil(self, state, nodes): pass

class RuleMoveVacancy(Rule):
	def perform(self, move, kind, state):
		(old,new) = move
		state.pop_vacancy(old)
		state.new_vacancy(new)

#	def info(self, move, kind):
#       (old,new) = move
#		return {
#			'action': 'move_vacancy',
#			'was': old,
#		}
	def kinds(self):
		return [(self, 1.0)]
#	def on_new_vacancy(self, state, node): self.clear_move(node)
#	def on_del_vacancy(self, state, node): self.add_move(node)
#	def on_new_trefoil(self, state, nodes): [self.clear_move(x) for x in nodes]
#	def on_del_trefoil(self, state, nodes): [self.add_move(x) for x in nodes]


# Provides a weak abstraction layer between State and Rules so that
# Rules can be incrementally updated in response to state changes
#
# Rules "listen" to events generated by the State.
class EventManager:
	def __init__(self):
		self.__handlers = defaultdict(set)

	def emit(self, symbol, *args):
		import warnings
		if not self.__handlers[symbol]:
			warnings.warn('No event handlers for %s' % symbol)
		for func in self.__handlers[symbol]:
			func(*args)

	def add_listener(self, symbol, func):
		self.__handlers[symbol].add(func)



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

